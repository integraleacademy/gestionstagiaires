"""Validation et analyse structurée des captures France Travail pour l'AFC."""

import base64
import json
import os
import re
from io import BytesIO
from typing import Any, Dict, List, Tuple

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
GENERIC_ANALYSIS_ERROR = "L’image n’a pas pu être analysée. Vérifiez qu’elle est suffisamment nette puis réessayez."


class AfcVisionError(Exception):
    pass


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_ft_id(value: Any) -> Tuple[str, str]:
    compact = re.sub(r"[\s-]+", "", str(value or "")).upper()
    if not re.fullmatch(r"\d{7}[A-Z](?:\d{3})?", compact):
        return compact, normalize_text(value)
    display = f"{compact[:8]} - {compact[8:]}" if len(compact) == 11 else compact
    # France Travail may show the identifier without its three-digit suffix.
    # The first eight characters identify the candidate in both representations.
    return compact[:8], display


def normalize_phone(value: Any) -> Tuple[str, str]:
    raw = normalize_text(value)
    compact = re.sub(r"[\s.()\-]", "", raw)
    if compact.startswith("+33"):
        compact = "0" + compact[3:]
    elif compact.startswith("0033"):
        compact = "0" + compact[4:]
    digits = re.sub(r"\D", "", compact)
    display = " ".join(digits[i:i + 2] for i in range(0, len(digits), 2)) if digits else raw
    return digits, display


def normalize_email(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def normalize_candidate(raw: Dict[str, Any]) -> Dict[str, Any]:
    ft_key, ft_display = normalize_ft_id(raw.get("france_travail_id", raw.get("identifiant_ft")))
    phone_key, phone_display = normalize_phone(raw.get("phone", raw.get("telephone")))
    return {
        "france_travail_id": ft_display,
        "last_name": normalize_text(raw.get("last_name", raw.get("nom"))),
        "first_names": normalize_text(raw.get("first_names", raw.get("prenom"))),
        "phone": phone_display,
        "email": normalize_email(raw.get("email")),
        "department": normalize_text(raw.get("department")) or None,
        "raw_name": normalize_text(raw.get("raw_name")) or None,
        "warnings": [normalize_text(w) for w in (raw.get("warnings") or []) if normalize_text(w)],
        "_keys": {"ft": ft_key, "phone": phone_key},
    }


def validation_errors(candidate: Dict[str, Any]) -> List[str]:
    errors = []
    if not re.fullmatch(r"\d{7}[A-Z]", candidate.get("_keys", {}).get("ft", "")):
        errors.append("Identifiant France Travail invalide ou ambigu")
    if not candidate.get("last_name"):
        errors.append("Nom obligatoire")
    if not candidate.get("first_names"):
        errors.append("Prénom(s) obligatoire(s)")
    phone_key = candidate.get("_keys", {}).get("phone", "")
    if phone_key and not re.fullmatch(r"0\d{9}", phone_key):
        errors.append("Numéro de téléphone invalide")
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", candidate.get("email", "")):
        errors.append("Adresse e-mail invalide")
    return errors


def prepare_image(file_bytes: bytes) -> Tuple[bytes, str]:
    if not file_bytes:
        raise ValueError("Le fichier image est vide.")
    if len(file_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("L’image dépasse la taille maximale de 10 Mo.")
    try:
        with Image.open(BytesIO(file_bytes)) as source:
            source.verify()
        with Image.open(BytesIO(file_bytes)) as source:
            if source.format not in ALLOWED_FORMATS:
                raise ValueError("Format non autorisé. Utilisez PNG, JPG, JPEG ou WEBP.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
            return output.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError):
        raise ValueError("Le fichier sélectionné n’est pas une image valide.")


VISION_PROMPT = """Analyse uniquement les cartes de candidats visibles sur cette capture France Travail. Ignore le titre « Candidats » et les boutons « Détails de la Candidature ». Extrais toutes les cartes, dans l'ordre de lecture de haut en bas. N'invente jamais une donnée absente et retourne null si elle est illisible. Conserve les noms composés, tous les prénoms, les accents, apostrophes et traits d'union. Utilise la typographie pour séparer le nom écrit en majuscules des prénoms : BENBEGHILA CHERIF Soraya Hadria signifie nom « BENBEGHILA CHERIF » et prénoms « Soraya Hadria » ; le nom n'est pas automatiquement le premier mot."""


def analyze_image(file_bytes: bytes, mime_type: str) -> List[Dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AfcVisionError(GENERIC_ANALYSIS_ERROR)
    model = os.environ.get("AFC_IMPORT_VISION_MODEL", "gpt-4.1-mini").strip()
    schema = {
        "name": "afc_candidates", "strict": True,
        "schema": {"type": "object", "additionalProperties": False, "properties": {
            "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "properties": {
                    "france_travail_id": {"type": ["string", "null"]}, "last_name": {"type": ["string", "null"]},
                    "first_names": {"type": ["string", "null"]}, "phone": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]}, "department": {"type": ["string", "null"]},
                    "raw_name": {"type": ["string", "null"]}, "warnings": {"type": "array", "items": {"type": "string"}}},
                "required": ["france_travail_id", "last_name", "first_names", "phone", "email", "department", "raw_name", "warnings"]}},
        }, "required": ["candidates"]},
    }
    payload = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode('ascii')}", "detail": "high"}},
    ]}], "response_format": {"type": "json_schema", "json_schema": schema}, "temperature": 0}
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=(5, 25))
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return parsed.get("candidates") if isinstance(parsed.get("candidates"), list) else []
    except (requests.RequestException, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AfcVisionError(GENERIC_ANALYSIS_ERROR) from exc
