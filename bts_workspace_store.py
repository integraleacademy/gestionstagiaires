"""BTS workspace data, separate from data.json and from the AKTO snapshot.

Local drafts are NOT contracts transmitted to an OPCO. Invoice drafts are NOT
issued invoices. Synchronising AKTO never deletes or overwrites these tables.
All locally entered monetary amounts are stored as integer euro cents.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import re
import sqlite3
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from akto_bts import AktoBtsStore, normalize_contract, redact_sensitive_payload

TABS = (("suivi", "Suivi dossier"), ("etudiant", "Étudiant"),
        ("contrat", "Contrat"), ("entreprise", "Entreprise"),
        ("gestion", "Gestion"), ("comptabilite", "Comptabilité"))
FEE_LABELS = {"HEBERGEMENT": "Hébergement", "RESTAURATION": "Restauration",
              "PREMIER_EQUIPEMENT": "Premier équipement", "MOBILITE": "Mobilité internationale"}
FIELD_GROUPS = {
    "etudiant": (
        ("apprentice_first_name", "Prénom", "text"),
        ("apprentice_last_name", "Nom", "text"),
        ("apprentice_birth_date", "Date de naissance", "date"),
        ("apprentice_email", "Adresse e-mail", "email"),
        ("apprentice_phone", "Téléphone", "tel"),
        ("apprentice_address", "Adresse", "text"),
        ("apprentice_postcode", "Code postal", "text"),
        ("apprentice_city", "Ville", "text"),
    ),
    "entreprise": (
        ("employer_name", "Raison sociale", "text"),
        ("employer_siret", "SIRET", "text"),
        ("employer_email", "Adresse e-mail", "email"),
        ("employer_phone", "Téléphone", "tel"),
        ("employer_address", "Adresse", "text"),
        ("employer_postcode", "Code postal", "text"),
        ("employer_city", "Ville", "text"),
        ("tutor_name", "Maître d’apprentissage", "text"),
        ("tutor_email", "E-mail du maître d’apprentissage", "email"),
    ),
    "contrat": (
        ("training_title", "Intitulé du BTS", "text"),
        ("rncp", "Code RNCP", "text"),
        ("diploma_code", "Code diplôme", "text"),
        ("training_start", "Début de formation", "date"),
        ("training_end", "Fin de formation", "date"),
        ("training_hours", "Durée de formation (heures)", "number"),
        ("remote_hours", "Dont distanciel (heures)", "number"),
        ("contract_conclusion", "Date de conclusion", "date"),
        ("contract_start", "Début du contrat", "date"),
        ("contract_end", "Fin du contrat", "date"),
        ("gross_salary", "Salaire brut à l’embauche (€)", "number"),
    ),
}
ALL_FIELDS = {field[0]: field for fields in FIELD_GROUPS.values() for field in fields}
CHECKLIST = (("cerfa_prepared", "CERFA préparé"),
             ("convention_prepared", "Convention préparée"),
             ("signatures_collected", "Signatures recueillies"),
             ("supporting_documents", "Pièces justificatives réunies"))


class WorkspaceError(ValueError):
    pass


class EditConflict(WorkspaceError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def money_cents(value: Any, *, strict: bool = False) -> int | None:
    """None means unknown, never a silently invented zero."""
    try:
        raw = str(value).strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        number = Decimal(raw)
        if not number.is_finite() or abs(number) > Decimal("100000000"):
            raise InvalidOperation
        return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        if strict:
            raise WorkspaceError("Indiquez un montant valide, en euros.") from None
        return None


def euros(value: Any) -> str:
    cents = money_cents(value)
    return "Non communiqué" if cents is None else euros_cents(cents)


def euros_cents(cents: int) -> str:
    return f"{Decimal(cents) / 100:,.2f}".replace(",", " ").replace(".", ",") + " €"


def date_fr(value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "Non communiquée"


def iso_day(value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return ""


def schedule_periods(cards: list[dict]) -> None:
    """Display-only periods: explicit OPCO dates, otherwise consecutive openings.

    The requested opening-to-opening convention never changes billing eligibility
    or source data. An unknown next opening is not skipped and no final date is invented.
    """
    numbers = [str(card["raw"].get("numero") or "") for card in cards]
    if all(number.isdecimal() for number in numbers) and len(set(map(int, numbers))) == len(numbers):
        cards.sort(key=lambda card: int(card["raw"]["numero"]))
    openings = [card["opening_date"] for card in cards]
    for index, card in enumerate(cards):
        raw = card["raw"]
        start, end = iso_day(raw.get("dateDebut")), iso_day(raw.get("dateFin"))
        origin, issue = "opco", ""
        if raw.get("dateDebut") or raw.get("dateFin"):
            if (raw.get("dateDebut") and not start) or (raw.get("dateFin") and not end) or (start and end and end < start):
                start, end, issue = "", "", "Période OPCO à vérifier"
        else:
            origin, start = "calculated", card["opening_date"]
            following = openings[index + 1] if index + 1 < len(cards) else ""
            if start and following and following > start and openings.count(start) == openings.count(following) == 1:
                end = following
            elif following and start and following <= start:
                issue = "Dates d’ouverture à vérifier"
            elif start and openings.count(start) > 1:
                issue = "Plusieurs échéances ont la même ouverture"
        card.update(period_start=start, period_end=end, period_origin=origin, period_issue=issue,
                    last_opening=index == len(cards) - 1 and origin == "calculated")


def remote_id(number: str) -> str:
    return "a-" + base64.urlsafe_b64encode(number.encode()).decode().rstrip("=")


def remote_number(record_id: str) -> str:
    if not re.fullmatch(r"a-[A-Za-z0-9_-]{1,400}", record_id):
        raise WorkspaceError("Identifiant de dossier invalide.")
    try:
        part = record_id[2:]
        value = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode()
        if not value or remote_id(value) != record_id:
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise WorkspaceError("Identifiant de dossier invalide.") from None


def validate_fields(data: Mapping[str, Any], existing: Mapping[str, Any] | None = None) -> dict:
    result = dict(existing or {})
    for name, (_, label, kind) in ALL_FIELDS.items():
        if name not in data:
            continue
        value = str(data.get(name) or "").strip()
        if len(value) > 500:
            raise WorkspaceError(f"Le champ « {label} » est trop long.")
        if value and kind == "date":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                raise WorkspaceError(f"La date « {label} » est invalide.") from None
        if value and kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise WorkspaceError(f"L’adresse « {label} » est invalide.")
        if value and kind == "number":
            amount = money_cents(value, strict=True)
            if amount < 0:
                raise WorkspaceError(f"Le champ « {label} » ne peut pas être négatif.")
            raw = value.replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
            if name in {"training_hours", "remote_hours"} and Decimal(raw) % 1:
                raise WorkspaceError("Les durées doivent être saisies en heures entières.")
            value = str(Decimal(amount) / 100)
        result[name] = value
    for key in ("apprentice_first_name", "apprentice_last_name"):
        if not result.get(key):
            raise WorkspaceError("Le prénom et le nom de l’apprenti sont obligatoires.")
    siret = result.get("employer_siret", "").replace(" ", "")
    if siret and not re.fullmatch(r"\d{14}", siret):
        raise WorkspaceError("Le SIRET doit comporter 14 chiffres.")
    result["employer_siret"] = siret
    for prefix in ("contract", "training"):
        if result.get(prefix + "_start") and result.get(prefix + "_end") and result[prefix + "_start"] > result[prefix + "_end"]:
            raise WorkspaceError("Une date de fin ne peut pas précéder la date de début.")
    if result.get("training_hours") and result.get("remote_hours"):
        if Decimal(result["remote_hours"]) > Decimal(result["training_hours"]):
            raise WorkspaceError("Le distanciel ne peut pas dépasser la durée totale de formation.")
    return result


def billing_view(record: dict, today: dt.date | None = None) -> dict:
    """Partition AKTO schedule amounts, not invoice amounts, without double counting."""
    today = today or dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    buckets = {"paid": 0, "pending": 0, "due": 0, "future": 0, "unknown": 0}
    cards = []
    keys = []
    for index, schedule in enumerate(record.get("schedules", [])):
        code = str(schedule.get("codification") or "").strip()
        number = str(schedule.get("numero") or "").strip()
        key = "code:" + code if code else ("numero:" + number if number else "")
        keys.append(key)
        total = money_cents(schedule.get("montantTotal"))
        paid = money_cents(schedule.get("montantRegle"))
        pending = money_cents(schedule.get("montantEnCoursInstruction"))
        try:
            opening = dt.date.fromisoformat(str(schedule.get("dateOuverture"))[:10])
        except ValueError:
            opening = None
        valid = all(value is not None and value >= 0 for value in (total, paid, pending))
        valid = valid and paid + pending <= total
        remaining = total - paid - pending if valid else 0
        status, label = "unknown", "À vérifier"
        if valid:
            buckets["paid"] += paid
            buckets["pending"] += pending
            balance_bucket = "future" if opening and opening > today else "due" if opening else "unknown"
            buckets[balance_bucket] += remaining
            if total > 0 and paid == total:
                status, label = "paid", "Payée"
            elif pending:
                status, label = "pending", "En instruction OPCO"
            elif paid:
                status, label = "partial", "Partiellement payée"
            elif opening and opening > today:
                status, label = "future", "À venir"
            elif opening:
                status, label = "due", "À facturer"
        elif total is not None and total > 0:
            buckets["unknown"] += total
        cards.append({"number": number or str(index + 1), "key": key, "raw": schedule,
                      "opening_date": opening.isoformat() if opening else "",
                      "amount": total, "paid": paid, "pending": pending,
                      "remaining": remaining, "status": status, "label": label,
                      "valid": valid, "can_draft": bool(valid and key and remaining > 0 and opening and opening <= today)})
    for card in cards:
        if card["key"] and keys.count(card["key"]) > 1:
            card["can_draft"] = False
        if record.get("source") == "wedof" and (record.get("raw_stale") or record.get("raw_error")):
            card["can_draft"] = False
    schedule_periods(cards)
    total = sum(buckets.values())
    colors = {"paid": "#69dca5", "pending": "#83d7fb", "due": "#ffb282", "future": "#ffe074", "unknown": "#c8ccdb"}
    labels = {"paid": "Payé", "pending": "En instruction OPCO", "due": "À facturer", "future": "À venir", "unknown": "À vérifier"}
    cursor = 0.0
    stops = []
    legend = []
    for key, amount in buckets.items():
        end = cursor + (100 * amount / total if total else 0)
        if amount:
            stops.append(f"{colors[key]} {cursor:.5f}% {end:.5f}%")
        legend.append({"key": key, "label": labels[key], "amount": amount, "color": colors[key]})
        cursor = end
    return {"cards": cards, "legend": legend, "total": total,
            "gradient": "conic-gradient(" + ",".join(stops) + ")" if stops else "#eceef7",
            "has_data": bool(cards)}


def opco_costs_view(record: dict) -> dict:
    """Payment flags describe settlement, not amounts of possible partial payments."""
    groups = {}
    for cost in record.get("extra_costs", []):
        if not isinstance(cost, dict):
            continue
        nature = str(cost.get("natureFrais") or "").upper()
        if nature == "PREMIEREQUIPEMENT":
            nature = "PREMIER_EQUIPEMENT"
        group = groups.setdefault(nature, {"nature": nature, "label": FEE_LABELS.get(nature, "Autres frais OPCO"),
                                           "lines": [], "amounts": []})
        amount = money_cents(cost.get("montantTotal"))
        group["amounts"].append(amount if amount is not None and amount >= 0 else None)
        group["lines"].append({"quantity": cost.get("quantite"), "unit_price": money_cents(cost.get("prixUnitaire"))})
    details = record.get("billing_details") or {}
    stale = record.get("source") == "wedof" and bool(record.get("raw_stale") or record.get("raw_error")
            or (groups and not record.get("extra_costs_available"))
            or (details and not record.get("billing_details_available")))
    flags = {"PREMIER_EQUIPEMENT": "fraisPremierEquipementRegles", "MOBILITE": "fraisMobiliteRegles"}
    items = []
    for group in groups.values():
        amount = sum(group["amounts"]) if all(value is not None for value in group["amounts"]) else None
        settled = details.get(flags.get(group["nature"])) if not stale else None
        # False can also mean partly paid. Do not invent zero paid / full amount outstanding.
        paid = amount if settled is True else None
        outstanding = 0 if settled is True and amount is not None else None
        status, label = ("paid", "Soldé") if settled is True else ("unsettled", "Non soldé") if settled is False else ("unknown", "Règlement non communiqué")
        if stale:
            status, label = "unknown", "À actualiser"
        items.append({**group, "amount": amount, "paid": paid, "outstanding": outstanding,
                      "status": status, "status_label": label})
    return {"items": items, "available": record.get("extra_costs_available", bool(items)), "stale": stale,
            "incomplete_payments": any(item["paid"] is None or item["outstanding"] is None for item in items)}


class WorkspaceStore(AktoBtsStore):
    def __init__(self, db_path: str):
        super().__init__(db_path)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS bts_local_dossiers (
                    id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_annotations (
                    dossier_id TEXT PRIMARY KEY, notes TEXT NOT NULL DEFAULT '',
                    checklist_json TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_fees (
                    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, nature TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0), description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bts_fees_dossier ON bts_fees(dossier_id);
                CREATE TABLE IF NOT EXISTS bts_invoice_drafts (
                    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, payer TEXT NOT NULL,
                    schedule_key TEXT NOT NULL DEFAULT '', amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    description TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bts_drafts_dossier ON bts_invoice_drafts(dossier_id);
                CREATE UNIQUE INDEX IF NOT EXISTS bts_draft_unique_schedule
                    ON bts_invoice_drafts(dossier_id, payer, schedule_key) WHERE schedule_key != '';
                CREATE TABLE IF NOT EXISTS bts_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, dossier_id TEXT NOT NULL,
                    label TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bts_events_dossier ON bts_events(dossier_id, id);
                CREATE TABLE IF NOT EXISTS bts_diagnostics (
                    name TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_wedof_contracts (
                    id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_wedof_lookups (
                    owner TEXT PRIMARY KEY, payload_json TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_cerfa_complements (
                    dossier_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def _event(connection, record_id: str, label: str, actor: str):
        connection.execute("INSERT INTO bts_events(dossier_id,label,actor,created_at) VALUES (?,?,?,?)",
                           (record_id, label, actor[:120], now()))

    def create_local(self, data: Mapping[str, Any], actor: str = "Équipe") -> str:
        payload = validate_fields(data)
        record_id, stamp = "l-" + uuid.uuid4().hex, now()
        with self._connect() as connection:
            connection.execute("INSERT INTO bts_local_dossiers(id,payload_json,created_at,updated_at) VALUES (?,?,?,?)",
                               (record_id, as_json(payload), stamp, stamp))
            self._event(connection, record_id, "Dossier local créé — aucun envoi à l’OPCO", actor)
        return record_id

    def record(self, record_id: str) -> dict | None:
        with self._connect() as connection:
            if record_id.startswith("l-"):
                row = connection.execute("SELECT * FROM bts_local_dossiers WHERE id=?", (record_id,)).fetchone()
                if row is None:
                    return None
                item = json.loads(row["payload_json"])
                item.update(source="local", state="BROUILLON", state_label="Brouillon local",
                            revision=row["revision"], created_at=row["created_at"], updated_at=row["updated_at"],
                            schedules=[], extra_costs=[], invoices=[], billing_details={})
            elif record_id.startswith("w-"):
                from wedof_bts import identifier
                try:
                    key = identifier(record_id[2:])
                except Exception:
                    raise WorkspaceError("Identifiant de contrat invalide.") from None
                row = connection.execute("SELECT * FROM bts_wedof_contracts WHERE id=?", (key,)).fetchone()
                if row is None:
                    return None
                item = json.loads(row["payload_json"])
                item.update(source="wedof", revision=0, updated_at=row["updated_at"])
            else:
                number = remote_number(record_id)
                row = connection.execute("SELECT * FROM contracts WHERE internal_number=?", (number,)).fetchone()
                if row is None:
                    return None
                item = self._decode_contract_row(row)
                item.update(source="akto", revision=0, updated_at=item.get("synced_at", ""))
                payload = json.loads(row["payload_json"] or "{}")
                item["source_payload"] = redact_sensitive_payload(payload)
            item["id"] = record_id
            item["name"] = " ".join(str(item.get(k) or "") for k in ("apprentice_first_name", "apprentice_last_name")).strip() or "Identité non restituée"
            annotation = connection.execute("SELECT * FROM bts_annotations WHERE dossier_id=?", (record_id,)).fetchone()
            item["annotation"] = dict(annotation) if annotation else {"notes": "", "checklist_json": "[]", "revision": 0}
            item["checked"] = json.loads(item["annotation"]["checklist_json"])
            item["fees"] = [dict(row) for row in connection.execute("SELECT * FROM bts_fees WHERE dossier_id=? ORDER BY created_at,id", (record_id,))]
            item["drafts"] = [dict(row) for row in connection.execute("SELECT * FROM bts_invoice_drafts WHERE dossier_id=? ORDER BY created_at DESC,id", (record_id,))]
            item["events"] = [dict(row) for row in connection.execute("SELECT * FROM bts_events WHERE dossier_id=? ORDER BY id DESC LIMIT 50", (record_id,))]
        return item

    def save_fields(self, record_id: str, data: Mapping[str, Any], revision: int, actor: str):
        record = self.record(record_id)
        if not record or record["source"] != "local":
            raise WorkspaceError("Les données OPCO sont en lecture seule. Les compléments se saisissent dans Gestion.")
        existing = {name: record.get(name, "") for name in ALL_FIELDS}
        payload = validate_fields(data, existing)
        with self._connect() as connection:
            changed = connection.execute("UPDATE bts_local_dossiers SET payload_json=?,updated_at=?,revision=revision+1 WHERE id=? AND revision=?",
                                         (as_json(payload), now(), record_id, revision)).rowcount
            if not changed:
                raise EditConflict("Ce dossier a été modifié par un autre utilisateur. Rechargez-le avant d’enregistrer.")
            self._event(connection, record_id, "Informations du dossier local mises à jour", actor)

    def cerfa_complements(self, record_id: str) -> dict:
        """Sensitive CERFA fields are read explicitly, never by general listings/exports."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM bts_cerfa_complements WHERE dossier_id=?", (record_id,)).fetchone()
        return {"values": json.loads(row["payload_json"]), "revision": row["revision"], "updated_at": row["updated_at"]} if row else {"values": {}, "revision": 0}

    def save_cerfa_complements(self, record_id: str, data: Mapping[str, Any], revision: int, source_hash: str, actor: str):
        from bts_cerfa import source_values, source_version, validate_values
        submitted = validate_values(data)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self.record(record_id)
            if not record:
                raise WorkspaceError("Dossier introuvable.")
            row = connection.execute("SELECT * FROM bts_cerfa_complements WHERE dossier_id=?", (record_id,)).fetchone()
            if (row["revision"] if row else 0) != revision or source_version(record) != source_hash:
                raise EditConflict("Les informations ont changé depuis l’ouverture du formulaire. Rechargez le dossier avant d’enregistrer.")
            payload = json.loads(row["payload_json"]) if row else {}
            original = source_values(record)
            # Store only actual complements/overrides. Unchanged imported values
            # continue to follow future targeted OPCO refreshes.
            for key, value in submitted.items():
                if value == original.get(key, ""):
                    payload.pop(key, None)
                else:
                    payload[key] = value
            if record["source"] == "local":
                local_row = connection.execute("SELECT payload_json FROM bts_local_dossiers WHERE id=?", (record_id,)).fetchone()
                local_payload = json.loads(local_row[0])
                for key, value in submitted.items():
                    if key in ALL_FIELDS:
                        local_payload[key] = value
                        payload.pop(key, None)
                if not local_payload.get("apprentice_first_name") or not local_payload.get("apprentice_last_name"):
                    raise WorkspaceError("Le prénom et le nom de l’apprenti sont obligatoires.")
                connection.execute("UPDATE bts_local_dossiers SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                                   (as_json(local_payload), now(), record_id))
            connection.execute("INSERT INTO bts_cerfa_complements(dossier_id,payload_json,revision,updated_at) VALUES (?,?,?,?) ON CONFLICT(dossier_id) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision,updated_at=excluded.updated_at",
                               (record_id, as_json(payload), revision + 1, now()))
            self._event(connection, record_id, "Informations de préparation du CERFA enregistrées", actor)

    def annotate(self, record_id: str, notes: str, checked: list[str], revision: int, actor: str):
        if not self.record(record_id):
            raise WorkspaceError("Dossier introuvable.")
        if len(notes) > 8000:
            raise WorkspaceError("La note est limitée à 8 000 caractères.")
        allowed = {key for key, _ in CHECKLIST}
        checked = sorted(set(checked) & allowed)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT revision FROM bts_annotations WHERE dossier_id=?", (record_id,)).fetchone()
            if (row["revision"] if row else 0) != revision:
                raise EditConflict("Le suivi a été modifié par un autre utilisateur. Rechargez le dossier.")
            connection.execute("INSERT INTO bts_annotations(dossier_id,notes,checklist_json,revision,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(dossier_id) DO UPDATE SET notes=excluded.notes,checklist_json=excluded.checklist_json,revision=excluded.revision,updated_at=excluded.updated_at",
                               (record_id, notes.strip(), as_json(checked), revision + 1, now()))
            self._event(connection, record_id, "Suivi interne mis à jour (déclaration de l’équipe)", actor)

    def add_fee(self, record_id: str, nature: str, amount: Any, description: str, actor: str):
        if not self.record(record_id):
            raise WorkspaceError("Dossier introuvable.")
        cents = money_cents(amount, strict=True)
        if nature not in FEE_LABELS or cents <= 0 or len(description) > 500:
            raise WorkspaceError("Vérifiez la nature, le montant et le libellé du frais.")
        with self._connect() as connection:
            connection.execute("INSERT INTO bts_fees(id,dossier_id,nature,amount_cents,description,created_at) VALUES (?,?,?,?,?,?)",
                               (uuid.uuid4().hex, record_id, nature, cents, description.strip(), now()))
            self._event(connection, record_id, "Frais annexe local ajouté — non transmis à l’OPCO", actor)

    def create_invoice_draft(self, record_id: str, payer: str, schedule_key: str, amount: Any, description: str, actor: str) -> str:
        record = self.record(record_id)
        if not record:
            raise WorkspaceError("Dossier introuvable.")
        if payer not in {"opco", "entreprise"}:
            raise WorkspaceError("Destinataire invalide.")
        if payer == "opco":
            card = next((card for card in billing_view(record)["cards"] if card["key"] == schedule_key and card["can_draft"]), None)
            if card is None:
                raise WorkspaceError("Cette échéance n’est pas disponible pour préparer une facture. Actualisez le dossier.")
            cents = card["remaining"]
            description = "Échéance n° " + card["number"]
        else:
            schedule_key = ""
            cents = money_cents(amount, strict=True)
            if cents <= 0 or not description.strip() or len(description) > 500:
                raise WorkspaceError("Saisissez un montant positif et un libellé (500 caractères maximum).")
        draft_id = "BR-" + uuid.uuid4().hex[:16].upper()
        try:
            with self._connect() as connection:
                connection.execute("INSERT INTO bts_invoice_drafts VALUES (?,?,?,?,?,?,?)",
                                   (draft_id, record_id, payer, schedule_key, cents, description.strip(), now()))
                self._event(connection, record_id, "Brouillon de facture préparé — ni émis ni transmis", actor)
        except sqlite3.IntegrityError:
            raise WorkspaceError("Un brouillon existe déjà pour cette échéance. Aucun doublon n’a été créé.") from None
        return draft_id

    def remove_local_item(self, record_id: str, item_id: str, kind: str, actor: str):
        table = {"fee": "bts_fees", "draft": "bts_invoice_drafts"}.get(kind)
        if not table or not self.record(record_id):
            raise WorkspaceError("Élément introuvable.")
        with self._connect() as connection:
            changed = connection.execute(f"DELETE FROM {table} WHERE id=? AND dossier_id=?", (item_id, record_id)).rowcount
            if not changed:
                raise WorkspaceError("Élément introuvable ou déjà supprimé.")
            self._event(connection, record_id, "Brouillon local supprimé" if kind == "draft" else "Frais local supprimé", actor)

    def listing(self, query: str = "", source: str = "", page: int = 1, per_page: int = 30) -> dict:
        # SQL pagination: no per-record payload/invoice history is read for the list.
        query = query.strip()[:120]
        fields = ("apprentice_first_name", "apprentice_last_name", "employer_name", "training_title", "employer_siret", "rncp")
        local = ",".join(f"COALESCE(json_extract(payload_json,'$.{field}'),'') AS {field}" for field in fields)
        remote = ",".join(fields)
        union = f"SELECT id,'local' AS source,'BROUILLON' AS state,updated_at,{local},0 AS engagement,'' AS financer FROM bts_local_dossiers UNION ALL SELECT internal_number AS id,'akto' AS source,state,synced_at AS updated_at,{remote},engagement,'opcoCfaAkto' AS financer FROM contracts"
        wedof = f"SELECT id,'wedof' AS source,json_extract(payload_json,'$.state') AS state,updated_at,{local},json_extract(payload_json,'$.engagement') AS engagement,json_extract(payload_json,'$.financer') AS financer FROM bts_wedof_contracts"
        union += " UNION ALL " + wedof
        clauses, params = [], []
        if source in {"local", "akto", "wedof"}:
            clauses.append("source=?")
            params.append(source)
        if query:
            expressions = [f"bts_fold({field}) LIKE ?" for field in (*fields, "id")]
            expressions.append("bts_fold(apprentice_first_name || ' ' || apprentice_last_name) LIKE ?")
            clauses.append("(" + " OR ".join(expressions) + ")")
            params.extend(["%" + query.casefold() + "%"] * len(expressions))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            connection.create_function("bts_fold", 1, lambda value: str(value or "").casefold(), deterministic=True)
            count = connection.execute(f"SELECT COUNT(*) FROM ({union}){where}", params).fetchone()[0]
            pages = max(1, math.ceil(count / per_page))
            page = min(max(1, page), pages)
            rows = connection.execute(f"SELECT * FROM ({union}){where} ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                                      [*params, per_page, (page - 1) * per_page]).fetchall()
            stats = dict(connection.execute("SELECT COUNT(*) AS remote_count,COALESCE(SUM(engagement),0) AS engagement,COALESCE(SUM(total_paid),0) AS paid FROM contracts").fetchone())
            ws = connection.execute("SELECT COUNT(*),COALESCE(SUM(json_extract(payload_json,'$.engagement')),0),SUM(json_extract(payload_json,'$.engagement') IS NULL) FROM bts_wedof_contracts").fetchone()
            stats.update(wedof_count=ws[0], unknown_engagements=ws[2] or 0)
            stats["remote_count"] += ws[0]
            stats["engagement"] += ws[1]
            stats["local_count"] = connection.execute("SELECT COUNT(*) FROM bts_local_dossiers").fetchone()[0]
            stats["draft_count"] = connection.execute("SELECT COUNT(*) FROM bts_invoice_drafts").fetchone()[0]
        records = []
        for row in rows:
            item = dict(row)
            if item["source"] == "akto":
                item["id"] = remote_id(item["id"])
            elif item["source"] == "wedof":
                item["id"] = "w-" + item["id"]
            item["name"] = (item["apprentice_first_name"] + " " + item["apprentice_last_name"]).strip() or ("Contrat OPCO · " + item["id"][2:] if item["source"] == "wedof" else "Identité non restituée")
            if item["source"] == "wedof":
                from wedof_bts import STATES
                item["state_label"] = STATES.get(item["state"], "État non communiqué")
            records.append(item)
        return {"records": records, "stats": stats, "total": count, "page": page, "pages": pages,
                "query": query, "source": source}

    def save_diagnostic(self, payload: dict):
        allowed = {key: payload[key] for key in ("ok", "stage", "message", "checked_at", "configuration_id") if key in payload}
        with self._connect() as connection:
            connection.execute("INSERT INTO bts_diagnostics VALUES ('connection',?,?) ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                               (as_json(allowed), now()))

    def diagnostic(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM bts_diagnostics WHERE name='connection'").fetchone()
        return json.loads(row[0]) if row else None

    def update_remote_detail(self, number: str, detail: dict, actor: str):
        """Update one cache record; keep other records and local work untouched."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM contracts WHERE internal_number=?", (number,)).fetchone()
            if not row:
                raise WorkspaceError("Dossier absent du cache. Recherchez-le par son numéro de contrat AKTO ou DECA.")
            cerfa = detail.get("cerfa")
            if not isinstance(cerfa, dict) or str(cerfa.get("numeroInterne") or "") != number:
                raise WorkspaceError("AKTO a renvoyé un dossier non identifiable. Le cache a été conservé.")
            invoices = []
            for invoice_row in connection.execute("SELECT * FROM invoices"):
                invoice = dict(invoice_row)
                invoice["dossier_links"] = json.loads(invoice.pop("dossier_links_json"))
                invoices.append(invoice)
            normalized = normalize_contract({"numeroInterne": number, "numeroExterne": row["external_number"], "etat": row["state"]},
                                            detail, invoices, synced_at=now(), detail_loaded=True)
            for source in ("schedules", "extra_costs", "billing_details", "invoices", "payload"):
                normalized[source + "_json"] = as_json(normalized.pop(source, {} if source in {"payload", "billing_details"} else []))
            columns = {item[1] for item in connection.execute("PRAGMA table_info(contracts)")}
            values = {key: value for key, value in normalized.items() if key in columns and key != "internal_number"}
            connection.execute("UPDATE contracts SET " + ",".join(f"{key}=?" for key in values) + " WHERE internal_number=?", [*values.values(), number])
            self._event(connection, remote_id(number), "Dossier et échéances actualisés depuis AKTO (factures non réinterrogées)", actor)

    def export_workspace(self) -> dict:
        result = {"version": 1, "exported_at": now(), "akto": self.export_snapshot()}
        with self._connect() as connection:
            for table in ("bts_local_dossiers", "bts_annotations", "bts_fees", "bts_invoice_drafts", "bts_events", "bts_wedof_contracts"):
                result[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        result["notice"] = "Les brouillons ne sont ni des contrats transmis ni des factures émises. Export confidentiel réservé à l’école."
        return redact_sensitive_payload(result)

    def wedof_state(self, name="sync"):
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM bts_diagnostics WHERE name=?", ("wedof_" + name,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_wedof_state(self, value, name="sync"):
        with self._connect() as connection:
            connection.execute("INSERT INTO bts_diagnostics VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                               ("wedof_" + name, as_json(value), now()))

    def wedof_lookup(self, owner):
        if not owner:
            return {}
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM bts_wedof_lookups WHERE owner=? AND expires_at>?",
                                     (owner, int(time.time()))).fetchone()
        return json.loads(row[0]) if row else {}

    def save_wedof_lookup(self, owner, payload):
        with self._connect() as connection:
            connection.execute("DELETE FROM bts_wedof_lookups WHERE expires_at<=?", (int(time.time()),))
            connection.execute("INSERT INTO bts_wedof_lookups VALUES (?,?,?) ON CONFLICT(owner) DO UPDATE SET payload_json=excluded.payload_json,expires_at=excluded.expires_at",
                               (owner, as_json(payload), int(time.time()) + 1200))

    def upsert_wedof_summary(self, summary, actor, *, details=None, only_new=False):
        key, stamp = summary["working_contract_id"], now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload_json FROM bts_wedof_contracts WHERE id=?", (key,)).fetchone()
            if row and only_new:
                return "unchanged"
            previous = json.loads(row[0]) if row else {}
            changed = previous.get("summary_hash") != summary["summary_hash"]
            item = {**{field: "" for field in ALL_FIELDS}, "schedules": [], "extra_costs": [],
                    "invoices": [], "billing_details": {}, **previous, **summary, "synced_at": stamp,
                    "missing_from_latest": False}
            if previous.get("registration_id") == summary.get("registration_id"):
                # The summary is less complete than the CERFA. Keep known details if
                # the following optional detailed read fails; its error is shown in the UI.
                for field in ALL_FIELDS:
                    if field in summary and summary[field] in (None, "") and previous.get(field) not in (None, ""):
                        item[field] = previous[field]
            item["needs_detail"] = bool(changed or previous.get("needs_detail") or str(previous.get("details_checked_at", ""))[:10] != stamp[:10])
            if changed and previous.get("raw_checked_at"):
                item["raw_stale"] = True
            # Changing the linked registration folder invalidates its old identity.
            if previous and previous.get("registration_id") != summary.get("registration_id"):
                for field in ALL_FIELDS:
                    if field not in summary:
                        item[field] = ""
                item.update(schedules=[], extra_costs=[], billing_details={}, raw_checked_at="", details_checked_at="",
                            extra_costs_available=False, billing_details_available=False)
            if details:
                item.update(details)
            connection.execute("INSERT INTO bts_wedof_contracts VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                               (key, as_json(item), stamp))
            if not row or changed:
                from wedof_bts import financer_label
                label = financer_label(summary["financer"])
                self._event(connection, "w-" + key, f"Contrat {'importé' if not row else 'actualisé'} depuis {label} via WEDOF", actor)
        return "added" if not row else "updated" if changed else "unchanged"

    def update_wedof_details(self, key, fields):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload_json FROM bts_wedof_contracts WHERE id=?", (key,)).fetchone()
            if not row:
                raise WorkspaceError("Contrat absent de l’espace BTS.")
            item = json.loads(row[0])
            item.update(fields)
            connection.execute("UPDATE bts_wedof_contracts SET payload_json=?,updated_at=? WHERE id=?", (as_json(item), now(), key))

    def wedof_details_pending(self, ids):
        with self._connect() as connection:
            rows = connection.execute("SELECT id,payload_json FROM bts_wedof_contracts").fetchall()
        seen = set(ids)
        return [row["id"] for row in rows if row["id"] in seen and json.loads(row["payload_json"]).get("needs_detail")]

    def mark_wedof_listing(self, ids):
        # Never delete a missing/cancelled contract or its local notes and drafts.
        seen = set(ids)
        with self._connect() as connection:
            rows = connection.execute("SELECT id,payload_json FROM bts_wedof_contracts").fetchall()
            for row in rows:
                item = json.loads(row["payload_json"])
                item["missing_from_latest"] = row["id"] not in seen
                connection.execute("UPDATE bts_wedof_contracts SET payload_json=? WHERE id=?", (as_json(item), row["id"]))
