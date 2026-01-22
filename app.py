import os
import re
import uuid
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
import requests

APP_TITLE = "Intégrale Academy - Admin"

DB_PATH = os.environ.get("DB_PATH", "data.db")

# Brevo (ex Sendinblue)
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "ecole@integraleacademy.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "Intégrale Academy")

# Lien vers espace stagiaire public (placeholder pour l’instant)
PUBLIC_STUDENT_SPACE_BASE_URL = os.environ.get("PUBLIC_STUDENT_SPACE_BASE_URL", "https://example.com/espace/")

# Intégrations externes (tu brancheras tes apps Render ensuite)
CNAPS_LOOKUP_URL = os.environ.get("CNAPS_LOOKUP_URL", "")       # ex: https://ton-app-cnaps.onrender.com/api/status?email=
HOSTING_LOOKUP_URL = os.environ.get("HOSTING_LOOKUP_URL", "")   # ex: https://ton-app-hebergement.onrender.com/api/booking?email=

# Basique "admin key" (protège /admin via un paramètre ?key=)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

FORMATION_TYPES = [
    "APS",
    "A3P",
    "DIRIGEANT initial",
    "DIRIGEANT VAE",
    "SSIAP 1",
    "CHEF DE POSTE"
]

# Status enums
CONVENTION_STATUSES = ["soon", "signing", "signed"]  # prochainement, en cours, signée
TEST_FR_STATUSES = ["soon", "in_progress", "validated", "relance"]  # prochainement, en cours, validé, relancé
DOSSIER_STATUSES = ["complete", "incomplete"]  # complet, incomplet
FINANCE_STATUSES = ["soon", "in_review", "validated"]  # prochainement, en cours de validation, validé

def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    def db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db():
        conn = db()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            training_type TEXT NOT NULL,
            date_start TEXT NOT NULL,
            date_end TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trainees (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            personal_id TEXT NOT NULL,

            convention_status TEXT NOT NULL DEFAULT 'soon',
            test_fr_status TEXT NOT NULL DEFAULT 'soon',
            dossier_status TEXT NOT NULL DEFAULT 'incomplete',
            financement_status TEXT NOT NULL DEFAULT 'soon',

            cnaps_status TEXT NOT NULL DEFAULT 'unknown',
            hosting_status TEXT NOT NULL DEFAULT 'unknown',
            vae_status TEXT NOT NULL DEFAULT 'soon',

            comment TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL,

            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_trainees_session ON trainees(session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trainees_email ON trainees(email)")
        conn.commit()
        conn.close()

    def admin_guard():
        if not ADMIN_KEY:
            return  # pas de clé -> pas de protection (tu peux en mettre une plus tard)
        key = request.args.get("key", "")
        if key != ADMIN_KEY:
            abort(403)

    def iso_now():
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    def parse_date(s: str) -> str:
        # Attendu: YYYY-MM-DD
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""):
            raise ValueError("Bad date")
        return s

    def personal_id():
        # Identifiant personnel lisible (ex: IA-2026-AB12CD)
        token = uuid.uuid4().hex[:6].upper()
        year = datetime.utcnow().year
        return f"IA-{year}-{token}"

    def status_label(kind: str, val: str) -> str:
        maps = {
            "convention": {"soon": "prochainement", "signing": "en cours de signature", "signed": "signée"},
            "test_fr": {"soon": "prochainement", "in_progress": "en cours", "validated": "validé", "relance": "relancé"},
            "dossier": {"complete": "complet", "incomplete": "incomplet"},
            "finance": {"soon": "prochainement", "in_review": "en cours de validation", "validated": "validé"},
            "cnaps": {}, "hosting": {}, "vae": {"soon": "prochainement", "in_progress": "en cours", "validated": "validé"}
        }
        return maps.get(kind, {}).get(val, val)

    def is_trainee_conform(t: sqlite3.Row) -> bool:
        # Règle minimale (tu ajouteras “etc” ensuite) :
        # conforme si Convention signée ET Dossier complet ET (Test FR validé OU non applicable ?)
        # Ici on compte Test FR comme requis -> validé
        return (
            t["convention_status"] == "signed"
            and t["dossier_status"] == "complete"
            and t["test_fr_status"] == "validated"
        )

    def session_conformity(session_id: str) -> dict:
        conn = db()
        trainees = conn.execute("SELECT * FROM trainees WHERE session_id=? ORDER BY created_at DESC", (session_id,)).fetchall()
        conn.close()

        total = len(trainees)
        conform_count = sum(1 for t in trainees if is_trainee_conform(t))
        non_conform_count = total - conform_count

        # Session 100% conforme si toutes les lignes sont conformes et qu’il y a au moins 1 stagiaire
        session_is_conform = (total > 0 and conform_count == total)

        return {
            "total": total,
            "conform_count": conform_count,
            "non_conform_count": non_conform_count,
            "session_is_conform": session_is_conform
        }

    def brevo_send_email(to_email: str, to_name: str, subject: str, html: str):
        if not BREVO_API_KEY:
            return
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "api-key": BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        }
        payload = {
            "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=10)
        except Exception:
            pass

    def brevo_send_sms(phone: str, message: str):
        if not BREVO_API_KEY:
            return
        url = "https://api.brevo.com/v3/transactionalSMS/sms"
        headers = {
            "api-key": BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        }
        payload = {
            "sender": "Integrale",
            "recipient": phone,
            "content": message,
            "type": "transactional"
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=10)
        except Exception:
            pass

    def lookup_cnaps_status(email: str) -> str:
        # Si tu configures CNAPS_LOOKUP_URL = "...?email="
        if not CNAPS_LOOKUP_URL:
            return "unknown"
        try:
            r = requests.get(CNAPS_LOOKUP_URL + requests.utils.quote(email), timeout=8)
            if r.status_code != 200:
                return "unknown"
            data = r.json()
            # attendu: {"status":"..."} ou similaire
            s = (data.get("status") or "").strip()
            return s if s else "unknown"
        except Exception:
            return "unknown"

    def lookup_hosting_status(email: str) -> str:
        # Si tu configures HOSTING_LOOKUP_URL = "...?email="
        if not HOSTING_LOOKUP_URL:
            return "unknown"
        try:
            r = requests.get(HOSTING_LOOKUP_URL + requests.utils.quote(email), timeout=8)
            if r.status_code != 200:
                return "unknown"
            data = r.json()
            # attendu: {"reserved":true} ou {"status":"reserved"}
            if data.get("reserved") is True:
                return "reserved"
            s = (data.get("status") or "").strip().lower()
            if s in ("reserved", "réservé", "reserve", "reservé"):
                return "reserved"
            return "unknown"
        except Exception:
            return "unknown"

    @app.before_request
    def _guard():
        if request.path.startswith("/admin"):
            admin_guard()

    @app.get("/")
    def home():
        return redirect(url_for("admin_sessions"))

    # -----------------------
    # ADMIN SESSIONS
    # -----------------------
    @app.get("/admin/sessions")
    def admin_sessions():
        conn = db()
        sessions = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        conn.close()

        cards = []
        for s in sessions:
            stats = session_conformity(s["id"])
            cards.append({
                "id": s["id"],
                "name": s["name"],
                "training_type": s["training_type"],
                "date_start": s["date_start"],
                "date_end": s["date_end"],
                "exam_date": s["exam_date"],
                "session_is_conform": stats["session_is_conform"],
                "total": stats["total"]
            })

        return render_template(
            "admin_sessions.html",
            title=APP_TITLE,
            formation_types=FORMATION_TYPES,
            sessions=cards
        )

    @app.post("/admin/sessions/create")
    def create_session():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        training_type = (data.get("training_type") or "").strip()
        date_start = parse_date(data.get("date_start"))
        date_end = parse_date(data.get("date_end"))
        exam_date = parse_date(data.get("exam_date"))

        if not name:
            return jsonify({"ok": False, "error": "Nom de session requis"}), 400
        if training_type not in FORMATION_TYPES:
            return jsonify({"ok": False, "error": "Type de formation invalide"}), 400

        session_id = uuid.uuid4().hex
        conn = db()
        conn.execute(
            "INSERT INTO sessions (id, name, training_type, date_start, date_end, exam_date, created_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, name, training_type, date_start, date_end, exam_date, iso_now())
        )
        conn.commit()
        conn.close()

        return jsonify({"ok": True, "id": session_id})

    @app.post("/admin/sessions/<session_id>/delete")
    def delete_session(session_id):
        conn = db()
        conn.execute("DELETE FROM trainees WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": cur.rowcount > 0})

    @app.get("/admin/sessions/<session_id>/trainees")
    def admin_trainees(session_id):
        conn = db()
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            conn.close()
            abort(404)

        trainees = conn.execute("SELECT * FROM trainees WHERE session_id=? ORDER BY created_at DESC", (session_id,)).fetchall()
        conn.close()

        stats = session_conformity(session_id)

        # pour affichage conditionnel
        show_hosting = (session["training_type"] == "A3P")
        show_vae = (session["training_type"] == "DIRIGEANT VAE")

        trainees_payload = []
        for t in trainees:
            trainees_payload.append({
                "id": t["id"],
                "personal_id": t["personal_id"],
                "last_name": t["last_name"],
                "first_name": t["first_name"],
                "email": t["email"],
                "phone": t["phone"],

                "convention_status": t["convention_status"],
                "test_fr_status": t["test_fr_status"],
                "dossier_status": t["dossier_status"],
                "cnaps_status": t["cnaps_status"],
                "hosting_status": t["hosting_status"],
                "vae_status": t["vae_status"],
                "financement_status": t["financement_status"],
                "comment": t["comment"],

                "is_conform": is_trainee_conform(t)
            })

        return render_template(
            "admin_trainees.html",
            title=APP_TITLE,
            session={
                "id": session["id"],
                "name": session["name"],
                "training_type": session["training_type"],
                "date_start": session["date_start"],
                "date_end": session["date_end"],
                "exam_date": session["exam_date"],
            },
            stats=stats,
            trainees=trainees_payload,
            show_hosting=show_hosting,
            show_vae=show_vae,
            enums={
                "convention": CONVENTION_STATUSES,
                "test_fr": TEST_FR_STATUSES,
                "dossier": DOSSIER_STATUSES,
                "finance": FINANCE_STATUSES
            }
        )

    # -----------------------
    # API TRAINEES
    # -----------------------
    @app.post("/api/trainees/add")
    def api_add_trainee():
        data = request.get_json(force=True)

        session_id = (data.get("session_id") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        first_name = (data.get("first_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip()

        if not (session_id and last_name and first_name and email and phone):
            return jsonify({"ok": False, "error": "Champs requis manquants"}), 400

        conn = db()
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            conn.close()
            return jsonify({"ok": False, "error": "Session introuvable"}), 404

        trainee_id = uuid.uuid4().hex
        pid = personal_id()

        # lookups externes
        cnaps = lookup_cnaps_status(email) or "unknown"
        hosting = "unknown"
        if session["training_type"] == "A3P":
            hosting = lookup_hosting_status(email) or "unknown"

        conn.execute("""
        INSERT INTO trainees (
            id, session_id, last_name, first_name, email, phone, personal_id,
            convention_status, test_fr_status, dossier_status, financement_status,
            cnaps_status, hosting_status, vae_status,
            comment, created_at
        ) VALUES (?,?,?,?,?,?,?, 'soon','soon','incomplete','soon', ?, ?, 'soon', '', ?)
        """, (
            trainee_id, session_id, last_name, first_name, email, phone, pid,
            cnaps, hosting, iso_now()
        ))
        conn.commit()
        conn.close()

        # Message bienvenue
        formation_name = session["training_type"]
        date_start = session["date_start"]
        date_end = session["date_end"]

        public_link = PUBLIC_STUDENT_SPACE_BASE_URL.rstrip("/") + "/" + pid

        subject = f"Bienvenue à Intégrale Academy – Inscription {formation_name}"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;line-height:1.5">
          <h2>Bienvenue à Intégrale Academy</h2>
          <p>Vous êtes bien inscrit(e) en formation <strong>{formation_name}</strong> prévue du <strong>{date_start}</strong> au <strong>{date_end}</strong>.</p>
          <p>Vous devez nous faire parvenir vos documents dès que possible afin de compléter votre dossier.</p>
          <p>
            Pour fournir vos documents, cliquez ici :
            <br>
            <a href="{public_link}" style="display:inline-block;margin-top:8px;padding:10px 14px;background:#1f8f4a;color:#fff;text-decoration:none;border-radius:10px">
              Accéder à mon espace stagiaire
            </a>
          </p>
          <p style="margin-top:14px">
            Rassurez-vous : même si vous n’avez pas encore tous les documents, vous pouvez les envoyer au fur et à mesure.
          </p>
          <p style="color:#666;font-size:13px;margin-top:18px">Intégrale Academy</p>
        </div>
        """

        sms = f"Bienvenue à Intégrale Academy ! Inscription {formation_name} du {date_start} au {date_end}. Espace stagiaire: {public_link}"

        # Envois
        brevo_send_email(email, f"{first_name} {last_name}", subject, html)
        brevo_send_sms(phone, sms)

        return jsonify({"ok": True, "id": trainee_id})

    @app.post("/api/trainees/update")
    def api_update_trainee():
        data = request.get_json(force=True)
        trainee_id = (data.get("trainee_id") or "").strip()
        field = (data.get("field") or "").strip()
        value = data.get("value")

        allowed = {
            "convention_status": CONVENTION_STATUSES,
            "test_fr_status": TEST_FR_STATUSES,
            "dossier_status": DOSSIER_STATUSES,
            "financement_status": FINANCE_STATUSES,
            "comment": None,
            "cnaps_status": None,     # optionnel (si tu veux éditer à la main)
            "hosting_status": None,   # optionnel
            "vae_status": ["soon", "in_progress", "validated"]
        }
        if field not in allowed:
            return jsonify({"ok": False, "error": "Champ non autorisé"}), 400

        if field != "comment" and allowed[field] is not None:
            if value not in allowed[field]:
                return jsonify({"ok": False, "error": "Valeur invalide"}), 400

        conn = db()
        row = conn.execute("SELECT session_id FROM trainees WHERE id=?", (trainee_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "Stagiaire introuvable"}), 404

        if field == "comment":
            value = (value or "").strip()
        else:
            value = (value or "").strip()

        conn.execute(f"UPDATE trainees SET {field}=? WHERE id=?", (value, trainee_id))
        conn.commit()
        conn.close()

        return jsonify({"ok": True})

    @app.post("/api/trainees/refresh_external")
    def api_refresh_external():
        data = request.get_json(force=True)
        trainee_id = (data.get("trainee_id") or "").strip()

        conn = db()
        t = conn.execute("SELECT * FROM trainees WHERE id=?", (trainee_id,)).fetchone()
        if not t:
            conn.close()
            return jsonify({"ok": False, "error": "Introuvable"}), 404

        s = conn.execute("SELECT * FROM sessions WHERE id=?", (t["session_id"],)).fetchone()
        if not s:
            conn.close()
            return jsonify({"ok": False, "error": "Session introuvable"}), 404

        cnaps = lookup_cnaps_status(t["email"]) or "unknown"
        hosting = t["hosting_status"]
        if s["training_type"] == "A3P":
            hosting = lookup_hosting_status(t["email"]) or "unknown"

        conn.execute("UPDATE trainees SET cnaps_status=?, hosting_status=? WHERE id=?", (cnaps, hosting, trainee_id))
        conn.commit()
        conn.close()

        return jsonify({"ok": True, "cnaps_status": cnaps, "hosting_status": hosting})

    # Health check
    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    init_db()
    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
