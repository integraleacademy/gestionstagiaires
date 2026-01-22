import os
import json
import uuid
import datetime
from typing import Dict, Any, Optional, List

import requests
from flask import Flask, request, redirect, url_for, jsonify, render_template, abort, send_file

import zipfile
from io import BytesIO
from docx import Document


app = Flask(__name__)

# =========================
# Persistent disk (Render)
# =========================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/data")
os.makedirs(PERSIST_DIR, exist_ok=True)
DATA_FILE = os.path.join(PERSIST_DIR, "data.json")

UPLOADS_DIR = os.path.join(PERSIST_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

def trainee_upload_dir(session_id: str, trainee_id: str) -> str:
    d = os.path.join(UPLOADS_DIR, session_id, trainee_id)
    os.makedirs(d, exist_ok=True)
    return d


# =========================
# Brevo (Sendinblue) config
# =========================
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "ecole@integraleacademy.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "Intégrale Academy")
CNAPS_LOOKUP_ENDPOINT = os.environ.get("CNAPS_LOOKUP_ENDPOINT", "")

PUBLIC_STUDENT_PORTAL_BASE = os.environ.get("PUBLIC_STUDENT_PORTAL_BASE", "https://example.com/espace-stagiaire")

CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")


# =========================
# Helpers
# =========================

def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        base = {"sessions": []}
        save_data(base)
        return base
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            backup = DATA_FILE + ".corrupt." + str(int(datetime.datetime.utcnow().timestamp()))
            os.replace(DATA_FILE, backup)
        except Exception:
            pass
        base = {"sessions": []}
        save_data(base)
        return base


def save_data(data: Dict[str, Any]) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def find_session(data: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    for s in data.get("sessions", []):
        if s.get("id") == session_id:
            return s
    return None


def find_trainee(session: Dict[str, Any], trainee_id: str) -> Optional[Dict[str, Any]]:
    for t in session.get("trainees", []):
        if t.get("id") == trainee_id:
            return t
    return None


def _session_get(s: Dict[str, Any], key: str, fallback: str = "") -> str:
    """
    Backward compatible getter: support old FR keys if needed.
    """
    if key in s and s.get(key) not in (None, ""):
        return s.get(key)

    # old keys from previous versions
    fr_map = {
        "name": "nom",
        "date_start": "date_debut",
        "date_end": "date_fin",
        "exam_date": "date_examen",
        "training_type": "type_formation",
        "trainees": "stagiaires",
    }
    fr_key = fr_map.get(key)
    if fr_key and fr_key in s and s.get(fr_key) not in (None, ""):
        return s.get(fr_key)

    return fallback


def _session_trainees_list(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "trainees" in s and isinstance(s.get("trainees"), list):
        return s.get("trainees", [])
    if "stagiaires" in s and isinstance(s.get("stagiaires"), list):
        # convert on the fly (non destructif)
        out = []
        for st in s.get("stagiaires", []):
            out.append(_convert_old_stagiaire_to_trainee(st))
        return out
    return []


def _convert_old_stagiaire_to_trainee(st: Dict[str, Any]) -> Dict[str, Any]:
    # best-effort mapping
    return {
        "id": st.get("id") or ("TRN-" + uuid.uuid4().hex[:8].upper()),
        "personal_id": st.get("id") or "",
        "last_name": st.get("nom") or "",
        "first_name": st.get("prenom") or "",
        "email": st.get("email") or "",
        "phone": st.get("telephone") or "",
        "comment": st.get("commentaire") or "",
        "cnaps": (st.get("cnaps") or "INCONNU"),
        "convention_status": _map_convention_to_enum(st.get("convention")),
        "test_fr_status": _map_testfr_to_enum(st.get("test_francais")),
        "dossier_status": "complete" if (st.get("dossier") == "complet") else "incomplete",
        "financement_status": _map_financement_to_enum(st.get("financement")),
        "vae_status": _map_vae_to_enum(st.get("vae")),
        "hosting_status": _map_hosting_to_enum(st.get("hebergement")),
        "documents": st.get("documents") or [],
        "public_token": st.get("public_token") or "",
        "created_at": st.get("created_at") or "",
        "updated_at": st.get("updated_at") or "",
    }


def _map_convention_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("signée", "signee", "signed"):
        return "signed"
    if "signature" in v or v in ("en cours de signature", "signing"):
        return "signing"
    return "soon"


def _map_testfr_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if v in ("relancé", "relance", "relancé(e)", "relancee"):
        return "relance"
    if v in ("en cours", "in progress", "in_progress", "en_cours"):
        return "in_progress"
    return "soon"


def _map_financement_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if "validation" in v or v in ("en cours de validation", "in_review"):
        return "in_review"
    return "soon"


def _map_vae_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("validé", "valide", "validated"):
        return "validated"
    if v in ("en cours", "in_progress", "in progress"):
        return "in_progress"
    return "soon"


def _map_hosting_to_enum(v: Optional[str]) -> str:
    v = (v or "").strip().lower()
    if v in ("réservé", "reserve", "reserved"):
        return "reserved"
    return "unknown"


# =========================
# Conformity logic (matching your enums)
# =========================

def trainee_is_conform(t: Dict[str, Any], training_type: str) -> bool:
    if t.get("convention_status") != "signed":
        return False
    if t.get("test_fr_status") != "validated":
        return False
    if t.get("dossier_status") != "complete":
        return False
    if t.get("financement_status") != "validated":
        return False
    if training_type == "DIRIGEANT VAE":
        if t.get("vae_status") != "validated":
            return False
    return True


def session_is_conform(session: Dict[str, Any]) -> bool:
    training_type = _session_get(session, "training_type", "")
    trainees = _session_trainees_list(session)
    if not trainees:
        return False
    return all(trainee_is_conform(t, training_type) for t in trainees)


def compute_stats(session: Dict[str, Any]) -> Dict[str, Any]:
    training_type = _session_get(session, "training_type", "")
    trainees = _session_trainees_list(session)
    conform_count = sum(1 for t in trainees if trainee_is_conform(t, training_type))
    total = len(trainees)
    return {
        "total": total,
        "conform_count": conform_count,
        "non_conform_count": total - conform_count,
        "session_is_conform": (total > 0 and conform_count == total),
    }


# =========================
# CNAPS / Hosting fetchers
# =========================

def fetch_cnaps_status_by_name(nom: str, prenom: str) -> Optional[str]:
    if not CNAPS_LOOKUP_ENDPOINT:
        return None
    try:
        r = requests.get(CNAPS_LOOKUP_ENDPOINT, params={"nom": nom, "prenom": prenom}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("statut_cnaps") or data.get("status")
    except Exception:
        return None


def fetch_hebergement_status(email: str) -> Optional[str]:
    if not HEBERGEMENT_STATUS_ENDPOINT:
        return None
    try:
        r = requests.get(HEBERGEMENT_STATUS_ENDPOINT, params={"email": email}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("reserved") is True:
            return "reserved"
        if data.get("reserved") is False:
            return "unknown"
        return data.get("status")
    except Exception:
        return None


# =========================
# UI enums (for template)
# =========================

FORMATION_TYPES = ["APS", "A3P", "DIRIGEANT initial", "DIRIGEANT VAE", "SSIAP 1", "CHEF DE POSTE"]

ENUMS = {
    "convention": ["soon", "signing", "signed"],
    "test_fr": ["soon", "in_progress", "validated", "relance"],
    "dossier": ["complete", "incomplete"],
    "financement": ["soon", "in_review", "validated"],
    "vae": ["soon", "in_progress", "validated"],
}


# =========================
# Pages (templates)
# =========================

@app.get("/")
def home():
    return redirect(url_for("admin_sessions"))


@app.get("/admin/sessions")
def admin_sessions():
    data = load_data()
    out_sessions = []
    for s in data.get("sessions", []):
        trainees = _session_trainees_list(s)
        st = compute_stats(s)
        out_sessions.append({
            "id": s.get("id"),
            "name": _session_get(s, "name", ""),
            "training_type": _session_get(s, "training_type", ""),
            "date_start": _session_get(s, "date_start", ""),
            "date_end": _session_get(s, "date_end", ""),
            "exam_date": _session_get(s, "exam_date", ""),
            "total": st["total"],
            "session_is_conform": st["session_is_conform"],
        })

    return render_template(
        "admin_sessions.html",
        sessions=out_sessions,
        formation_types=FORMATION_TYPES,
    )


@app.get("/admin/sessions/<session_id>/trainees")
def admin_trainees(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    # normalize session view
    session_view = {
        "id": s.get("id"),
        "name": _session_get(s, "name", ""),
        "training_type": _session_get(s, "training_type", ""),
        "date_start": _session_get(s, "date_start", ""),
        "date_end": _session_get(s, "date_end", ""),
        "exam_date": _session_get(s, "exam_date", ""),
    }

    trainees = _session_trainees_list(s)

    # refresh CNAPS (best-effort) using last_name/first_name
    for t in trainees:
        ln = (t.get("last_name") or "").strip()
        fn = (t.get("first_name") or "").strip()
        if ln and fn:
            cn = fetch_cnaps_status_by_name(ln, fn)
            if cn:
                t["cnaps"] = str(cn).upper()
        if not t.get("cnaps"):
            t["cnaps"] = "INCONNU"

        # hosting only for A3P
        if session_view["training_type"] == "A3P":
            email = t.get("email") or ""
            hb = fetch_hebergement_status(email) if email else None
            t["hosting_status"] = hb if hb else (t.get("hosting_status") or "unknown")
        else:
            t.pop("hosting_status", None)

    # persist normalized trainees back into storage (so future pages are consistent)
    s["trainees"] = trainees
    s.pop("stagiaires", None)  # optional cleanup
    save_data(data)

    stats = compute_stats(s)
    show_hosting = (session_view["training_type"] == "A3P")
    show_vae = (session_view["training_type"] == "DIRIGEANT VAE")

    return render_template(
        "admin_trainees.html",
        session=session_view,
        trainees=trainees,
        stats=stats,
        show_hosting=show_hosting,
        show_vae=show_vae,
        enums=ENUMS,
    )


# =========================
# FICHE STAGIAIRE (HTML)
# =========================
@app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>")
def admin_trainee_sheet(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        abort(404)

    # vue session (même format que admin_trainees)
    session_view = {
        "id": s.get("id"),
        "name": _session_get(s, "name", ""),
        "training_type": _session_get(s, "training_type", ""),
        "date_start": _session_get(s, "date_start", ""),
        "date_end": _session_get(s, "date_end", ""),
        "exam_date": _session_get(s, "exam_date", ""),
    }

    trainees = _session_trainees_list(s)
    trainee = next((x for x in trainees if x.get("id") == trainee_id), None)
    if not trainee:
        abort(404)

    show_hosting = (session_view["training_type"] == "A3P")
    show_vae = (session_view["training_type"] == "DIRIGEANT VAE")

    # (optionnel) on force le CNAPS à être propre pour l'affichage
    if not trainee.get("cnaps"):
        trainee["cnaps"] = "INCONNU"
    trainee["cnaps"] = str(trainee["cnaps"]).upper()

    return render_template(
        "admin_trainee.html",
        session=session_view,
        trainee=trainee,
        show_hosting=show_hosting,
        show_vae=show_vae,
        enums=ENUMS,
    )


# =========================
# API - Sessions (used by your modal JS)
# =========================

@app.post("/api/sessions/create")
def api_create_session():
    data = load_data()
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    training_type = (payload.get("training_type") or "").strip()
    date_start = (payload.get("date_start") or "").strip()
    date_end = (payload.get("date_end") or "").strip()
    exam_date = (payload.get("exam_date") or "").strip()

    if not name or not training_type:
        return jsonify({"ok": False, "error": "missing_name_or_training_type"}), 400

    session_id = uuid.uuid4().hex[:10]
    s = {
        "id": session_id,
        "name": name,
        "training_type": training_type,
        "date_start": date_start,
        "date_end": date_end,
        "exam_date": exam_date,
        "created_at": _now_iso(),
        "trainees": [],
    }
    data["sessions"].insert(0, s)
    save_data(data)
    return jsonify({"ok": True, "id": session_id})


@app.post("/api/sessions/<session_id>/delete")
def api_delete_session(session_id: str):
    data = load_data()
    before = len(data.get("sessions", []))
    data["sessions"] = [s for s in data.get("sessions", []) if s.get("id") != session_id]
    save_data(data)
    return jsonify({"ok": True, "deleted": (len(data["sessions"]) != before)})


# =========================
# API - Trainees (create + update for autosave)
# =========================

@app.post("/api/sessions/<session_id>/trainees/create")
def api_create_trainee(session_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    last_name = (payload.get("last_name") or "").strip()
    first_name = (payload.get("first_name") or "").strip()
    email = (payload.get("email") or "").strip()
    phone = (payload.get("phone") or "").strip()

    if not last_name or not first_name:
        return jsonify({"ok": False, "error": "missing_name"}), 400

    trainee_id = "TRN-" + uuid.uuid4().hex[:8].upper()

    training_type = _session_get(s, "training_type", "")
    show_hosting = (training_type == "A3P")
    show_vae = (training_type == "DIRIGEANT VAE")

    t = {
        "id": trainee_id,
        "personal_id": trainee_id,

        "last_name": last_name,
        "first_name": first_name,
        "email": email,
        "phone": phone,

        "comment": "",
        "cnaps": "INCONNU",

        "convention_status": "soon",
        "test_fr_status": "soon",
        "dossier_status": "incomplete",
        "financement_status": "soon",
        "vae_status": "soon" if show_vae else "",
        "hosting_status": "unknown" if show_hosting else "",

        "public_token": uuid.uuid4().hex,

        "documents": [
            {"key": "id", "label": "Pièce d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "dom", "label": "Justificatif de domicile (-3 mois)", "status": "A CONTRÔLER", "comment": "", "file": ""},
            {"key": "photo", "label": "Photo d'identité", "status": "A CONTRÔLER", "comment": "", "file": ""},
        ],

        "created_at": _now_iso(),
    }

    trainees = _session_trainees_list(s)
    trainees.insert(0, t)
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True, "id": trainee_id})


@app.post("/api/sessions/<session_id>/stagiaires/<trainee_id>/update")
def api_update_trainee(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    trainees = _session_trainees_list(s)
    t = None
    for x in trainees:
        if x.get("id") == trainee_id:
            t = x
            break
    if not t:
        return jsonify({"ok": False, "error": "trainee_not_found"}), 404

    payload = request.get_json(silent=True) or {}

    # Your template uses:
    # - convention_status, test_fr_status, dossier_status, financement_status, vae_status, comment, cnaps
    allowed = {
        "convention_status",
        "test_fr_status",
        "dossier_status",
        "financement_status",
        "vae_status",
        "comment",
        "cnaps",
    }

    for k, v in payload.items():
        if k in allowed:
            t[k] = v

    t["updated_at"] = _now_iso()
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/sessions/<session_id>/trainees/<trainee_id>/delete")
def api_delete_trainee(session_id: str, trainee_id: str):
    data = load_data()
    s = find_session(data, session_id)
    if not s:
        return jsonify({"ok": False, "error": "session_not_found"}), 404

    trainees = _session_trainees_list(s)
    before = len(trainees)
    trainees = [x for x in trainees if x.get("id") != trainee_id]
    s["trainees"] = trainees
    s.pop("stagiaires", None)
    save_data(data)
    return jsonify({"ok": True, "deleted": (len(trainees) != before)})


# =========================
# CNAPS lookup API (used by your refresh button)
# =========================

@app.get("/api/cnaps_lookup")
def api_cnaps_lookup():
    nom = (request.args.get("nom") or "").strip()
    prenom = (request.args.get("prenom") or "").strip()

    if not nom or not prenom:
        return jsonify({"ok": False, "error": "missing_nom_or_prenom"}), 400

    status = fetch_cnaps_status_by_name(nom, prenom) or "INCONNU"
    return jsonify({"ok": True, "nom": nom, "prenom": prenom, "statut_cnaps": str(status).upper()})


# =========================
# Health
# =========================

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "data_file": DATA_FILE})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
