"""Immutable, tenant-scoped evidence and two-party signatures of native APS modules.

Preparing a snapshot never contacts Yousign. Sending requires a separate explicit
action. Provider mutations have durable checkpoints; an uncertain request is
reconciled by its external ID instead of issuing another request blindly.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import re
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path


class SignatureError(ValueError):
    pass


CLOSED_STATUSES = {"expired", "declined", "canceled", "rejected", "deleted"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _text(value, limit=240):
    value = str(value or "").strip()
    if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise SignatureError("Une information saisie est trop longue ou contient un caractère invalide.")
    return value


def normalize_signer(raw, label):
    raw = raw if isinstance(raw, dict) else {}
    signer = {key: _text(raw.get(key), 180 if key == "email" else 100)
              for key in ("first_name", "last_name", "email", "phone")}
    if not signer["first_name"] or not signer["last_name"]:
        raise SignatureError(f"Le prénom et le nom du {label} sont obligatoires.")
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", signer["email"]):
        raise SignatureError(f"L'adresse e-mail du {label} est invalide.")
    return signer


def retention_date(session_end):
    try:
        end = dt.date.fromisoformat(str(session_end or ""))
    except ValueError as exc:
        raise SignatureError("Renseignez la date de fin de la session pour calculer les trois ans de conservation.") from exc
    try:
        return end.replace(year=end.year + 3).isoformat()
    except ValueError as exc:
        if end.month == 2 and end.day == 29:
            return end.replace(year=end.year + 3, day=28).isoformat()
        raise SignatureError("La date de fin de session est invalide.") from exc


def build_evidence(*, tenant_id, session_obj, trainee, provider, course, progress,
                   connections, attempts, responsible, cnaps_number, session_end, origin):
    """Freeze factual traces only. Never manufacture old attempts or signatures."""
    from .assessment import describe_history
    if not str(course.get("id", "")).startswith("academy-aps62-"):
        raise SignatureError("Ce tableau est réservé aux modules du parcours natif APS.")
    if not progress.get("module_complete") or progress.get("status") != "passed":
        raise SignatureError("Terminez les activités, les questionnaires et la durée du module avant de préparer son tableau.")
    learner = normalize_signer(trainee, "stagiaire")
    responsible = normalize_signer(responsible, "responsable de l'organisme")
    if learner["email"].casefold() == responsible["email"].casefold():
        raise SignatureError("Le stagiaire et le responsable doivent avoir deux adresses e-mail distinctes.")
    cnaps_number = _text(cnaps_number, 160)
    if not cnaps_number or cnaps_number.casefold() in {"non renseigné", "non renseigne", "inconnu", "-"}:
        raise SignatureError("Renseignez le numéro de carte professionnelle ou d'autorisation préalable du stagiaire.")
    if cnaps_number.upper().startswith("NUB"):
        raise SignatureError("Le NUB ne remplace pas le numéro de carte professionnelle ou d'autorisation préalable.")
    active = float(progress.get("active_seconds") or 0)
    if not math.isfinite(active) or active < 0:
        raise SignatureError("Le temps actif enregistré est invalide.")
    identity = {"tenant_id": _text(tenant_id), "session_id": _text(session_obj["id"]),
                "trainee_id": _text(trainee.get("id") or trainee.get("trainee_id")),
                "course_id": _text(course["id"]), "course_version": _text(course["version"])}
    if not all(identity.values()):
        raise SignatureError("Les identifiants de suivi du module sont incomplets.")
    sections = []
    for section in course.get("sections", []):
        sections.append({"id": section["id"], "title": section.get("title", ""), "activities": [
            {"id": a["id"], "title": a.get("title", ""), "scored": bool(a.get("scored")),
             "prompt": a.get("prompt", ""), "options": a.get("options", []),
             "question_type": a.get("question_type", ""), "practice": a.get("practice") or {},
             "answer": progress.get("answers", {}).get(a["id"], {}),
             "completed": a["id"] in progress.get("completed_activity_ids", [])}
            for a in section.get("activities", [])]})
    return {"schema_version": 1, **identity, "origin": origin,
            "session": {"name": _text(session_obj.get("name") or "Parcours APS"),
                        "date_start": str(session_obj.get("date_start") or ""), "date_end": str(session_end)},
            "retention_until": retention_date(session_end),
            "learner": {**learner, "cnaps_number": cnaps_number,
                        "birth_date": _text(trainee.get("birth_date"), 40)},
            "responsible": responsible,
            "provider": {key: _text(provider.get(key), 300) for key in
                         ("name", "siret", "address", "postal_code", "city", "email", "phone")},
            "course": {"title": _text(course.get("title")), "sha256": sha256(canonical(course)),
                       "section_ids": [s["id"] for s in course.get("sections", [])], "sections": sections},
            "progress": {key: progress.get(key) for key in
                         ("active_seconds", "required_seconds", "progress_percent", "score_percent", "status",
                          "completed_at", "started_at", "updated_at", "completed_activity_ids", "video_progress",
                          "assessment_summary", "assessment_diagnostics")},
            "assessment_attempts": describe_history(course, list(attempts or [])), "connections": list(connections or []),
            "notice": "Historique figé lors de la préparation. Les tentatives antérieures non enregistrées ne sont pas reconstituées."}


class ModuleSignatureStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS module_signature_snapshots (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    trainee_id TEXT NOT NULL, course_id TEXT NOT NULL, course_version TEXT NOT NULL,
                    source_hash TEXT NOT NULL, frozen_at TEXT NOT NULL, retention_until TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, pdf BLOB NOT NULL, pdf_sha256 TEXT NOT NULL,
                    fields_json TEXT NOT NULL, actor TEXT NOT NULL,
                    UNIQUE(tenant_id, session_id, trainee_id, course_id, course_version, source_hash));
                CREATE TABLE IF NOT EXISTS module_signature_requests (
                    snapshot_id TEXT PRIMARY KEY REFERENCES module_signature_snapshots(id),
                    status TEXT NOT NULL DEFAULT 'prepared', state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL, lease_owner TEXT, lease_until REAL);
                CREATE TABLE IF NOT EXISTS module_signature_artifacts (
                    snapshot_id TEXT NOT NULL REFERENCES module_signature_snapshots(id),
                    kind TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, kind));
                CREATE TABLE IF NOT EXISTS module_signature_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id TEXT NOT NULL,
                    event TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, details_json TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_module_signature_snapshot
                    BEFORE UPDATE ON module_signature_snapshots BEGIN
                    SELECT RAISE(ABORT, 'Les tableaux de suivi figés ne peuvent pas être modifiés'); END;
                CREATE TRIGGER IF NOT EXISTS retain_module_signature_snapshot
                    BEFORE DELETE ON module_signature_snapshots
                    WHEN OLD.retention_until >= date('now') BEGIN
                    SELECT RAISE(ABORT, 'Conservation réglementaire du tableau de suivi'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_module_signature_artifact
                    BEFORE UPDATE ON module_signature_artifacts BEGIN
                    SELECT RAISE(ABORT, 'Une pièce de preuve archivée ne peut pas être modifiée'); END;
                CREATE TRIGGER IF NOT EXISTS retain_module_signature_artifact
                    BEFORE DELETE ON module_signature_artifacts
                    WHEN (SELECT retention_until FROM module_signature_snapshots WHERE id=OLD.snapshot_id) >= date('now') BEGIN
                    SELECT RAISE(ABORT, 'Conservation réglementaire des preuves de signature'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_module_signature_event
                    BEFORE UPDATE ON module_signature_events BEGIN
                    SELECT RAISE(ABORT, 'Le journal des signatures ne peut pas être modifié'); END;
                CREATE TRIGGER IF NOT EXISTS retain_module_signature_event
                    BEFORE DELETE ON module_signature_events
                    WHEN (SELECT retention_until FROM module_signature_snapshots WHERE id=OLD.snapshot_id) >= date('now') BEGIN
                    SELECT RAISE(ABORT, 'Conservation réglementaire du journal des signatures'); END;
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def prepare(self, evidence, *, actor="", render=None):
        from .module_signature_pdf import render_module_pdf
        source_hash = sha256(canonical(evidence))
        identity = tuple(evidence[k] for k in ("tenant_id", "session_id", "trainee_id", "course_id", "course_version"))
        with self.connect() as db:
            existing = db.execute("""SELECT id FROM module_signature_snapshots WHERE
                tenant_id=? AND session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND source_hash=?""",
                (*identity, source_hash)).fetchone()
        if existing:
            return self.get(evidence["tenant_id"], existing["id"])
        snapshot_id, frozen_at = uuid.uuid4().hex, utcnow()
        snapshot = {**evidence, "snapshot_id": snapshot_id, "frozen_at": frozen_at, "source_hash": source_hash}
        pdf, fields = (render or render_module_pdf)(snapshot)
        _valid_pdf(pdf)
        with self.connect() as db:
            inserted = db.execute("""INSERT OR IGNORE INTO module_signature_snapshots
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (snapshot_id, *identity, source_hash, frozen_at,
                evidence["retention_until"], canonical(snapshot), pdf, sha256(pdf), canonical(fields), str(actor)[:180])).rowcount
            row = db.execute("""SELECT id FROM module_signature_snapshots WHERE
                tenant_id=? AND session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND source_hash=?""",
                (*identity, source_hash)).fetchone()
            snapshot_id = row["id"]
            db.execute("INSERT OR IGNORE INTO module_signature_requests(snapshot_id,updated_at) VALUES (?,?)",
                       (snapshot_id, frozen_at))
            if inserted:
                db.execute("INSERT INTO module_signature_events(snapshot_id,event,actor,at,details_json) VALUES (?,?,?,?,?)",
                           (snapshot_id, "snapshot_prepared", str(actor)[:180], frozen_at, canonical({"source_hash": source_hash})))
        return self.get(evidence["tenant_id"], snapshot_id)

    def get(self, tenant_id, snapshot_id):
        with self.connect() as db:
            row = db.execute("""SELECT s.*, r.status, r.state_json, r.updated_at FROM module_signature_snapshots s
                JOIN module_signature_requests r ON r.snapshot_id=s.id WHERE s.tenant_id=? AND s.id=?""",
                (str(tenant_id), str(snapshot_id))).fetchone()
        if not row:
            raise SignatureError("Tableau de suivi introuvable.")
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        result["state"] = json.loads(result.pop("state_json"))
        result["fields"] = json.loads(result.pop("fields_json"))
        return result

    def reissue(self, tenant_id, snapshot_id, *, actor=""):
        """One child edition per closed snapshot, retaining the frozen facts."""
        with self.lease(tenant_id, snapshot_id):
            previous = self.get(tenant_id, snapshot_id)
            if previous["status"] not in CLOSED_STATUSES:
                raise SignatureError("Une nouvelle édition de reprise est disponible uniquement pour une demande clôturée.")
            evidence = {key: value for key, value in previous["evidence"].items()
                        if key not in {"snapshot_id", "frozen_at", "source_hash", "reissued_from", "source_captured_at"}}
            evidence["reissued_from"] = previous["id"]
            evidence["source_captured_at"] = previous["evidence"].get("source_captured_at") or previous["frozen_at"]
            return self.prepare(evidence, actor=actor)

    def list_for(self, tenant_id, session_id, trainee_id):
        with self.connect() as db:
            rows = db.execute("""SELECT s.id FROM module_signature_snapshots s WHERE
                tenant_id=? AND session_id=? AND trainee_id=? ORDER BY frozen_at DESC,id DESC""",
                (str(tenant_id), str(session_id), str(trainee_id))).fetchall()
        return [self.get(tenant_id, r["id"]) for r in rows]

    @contextlib.contextmanager
    def lease(self, tenant_id, snapshot_id):
        self.get(tenant_id, snapshot_id)
        owner = uuid.uuid4().hex
        with self.connect() as db:
            changed = db.execute("""UPDATE module_signature_requests SET lease_owner=?,lease_until=?
                WHERE snapshot_id=? AND (lease_owner IS NULL OR lease_until<?)""",
                (owner, time.time() + 150, snapshot_id, time.time())).rowcount
        if not changed:
            raise SignatureError("Une opération de signature est déjà en cours. Réessayez dans quelques instants.")
        try:
            yield owner
        finally:
            with self.connect() as db:
                db.execute("UPDATE module_signature_requests SET lease_owner=NULL,lease_until=NULL WHERE snapshot_id=? AND lease_owner=?",
                           (snapshot_id, owner))

    def save_state(self, snapshot_id, owner, state, status, *, event="", actor=""):
        with self.connect() as db:
            changed = db.execute("""UPDATE module_signature_requests SET status=?,state_json=?,updated_at=?,lease_until=?
                WHERE snapshot_id=? AND lease_owner=?""", (status, canonical(state), utcnow(), time.time() + 150, snapshot_id, owner)).rowcount
            if not changed:
                raise SignatureError("Une autre opération a repris cette demande. Actualisez son état.")
            if event:
                db.execute("INSERT INTO module_signature_events(snapshot_id,event,actor,at,details_json) VALUES (?,?,?,?,?)",
                           (snapshot_id, event, str(actor)[:180], utcnow(), canonical({"status": status})))

    def artifact(self, tenant_id, snapshot_id, kind):
        self.get(tenant_id, snapshot_id)
        with self.connect() as db:
            row = db.execute("SELECT content FROM module_signature_artifacts WHERE snapshot_id=? AND kind=?", (snapshot_id, kind)).fetchone()
        return bytes(row["content"]) if row else None

    def save_artifact(self, snapshot_id, kind, content):
        _valid_pdf(content)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO module_signature_artifacts VALUES (?,?,?,?,?)",
                       (snapshot_id, kind, content, sha256(content), utcnow()))

    def archive(self, tenant_id, snapshot_id):
        record = self.get(tenant_id, snapshot_id)
        files = {"tableau-original.pdf": bytes(record["pdf"]),
                 "traces-figees.json": canonical(record["evidence"]).encode("utf-8")}
        with self.connect() as db:
            for row in db.execute("SELECT kind,content FROM module_signature_artifacts WHERE snapshot_id=?", (snapshot_id,)):
                files[row["kind"] + ".pdf"] = bytes(row["content"])
            events = [dict(row) for row in db.execute("SELECT event,actor,at,details_json FROM module_signature_events WHERE snapshot_id=? ORDER BY id", (snapshot_id,))]
        files["journal-signature.json"] = canonical({"state": record["state"], "events": events}).encode("utf-8")
        files["empreintes-sha256.json"] = canonical({name: sha256(value) for name, value in files.items()}).encode("utf-8")
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return result.getvalue()


def _valid_pdf(content):
    if not isinstance(content, bytes) or len(content) < 100 or b"%PDF-" not in content[:1024]:
        raise SignatureError("Le document PDF reçu est invalide. Il n'a pas été archivé.")
    try:
        from pypdf import PdfReader
        if not PdfReader(io.BytesIO(content)).pages:
            raise ValueError("empty")
    except Exception as exc:
        raise SignatureError("Le document PDF reçu est illisible. Il n'a pas été archivé.") from exc


def _items(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "signers", "documents", "signature_requests"):
            if isinstance(payload.get(key), list):
                return _items(payload[key])
    return []


class YousignModuleSignatures:
    """Reuse the host transport/configuration, never sign on behalf of a person."""
    def __init__(self, host, store):
        self.host, self.store = host, store

    def _check(self):
        if not self.host._yousign_is_configured():
            raise SignatureError("Yousign n'est pas configuré pour l'envoi des tableaux.")

    def _json(self, method, path, **kwargs):
        return self.host._yousign_json(method, path, **kwargs)

    def _checkpoint(self, record, owner, state, status="preparing", **kwargs):
        self.store.save_state(record["id"], owner, state, status, **kwargs)

    def _recover_request(self, external_id):
        payload = self._json("GET", "/signature_requests", params={"external_id[eq]": external_id, "limit": 100})
        found = [x for x in _items(payload) if x.get("external_id") == external_id]
        if len(found) > 1 or (isinstance(payload, dict) and (payload.get("meta") or {}).get("next_cursor")):
            raise SignatureError("Plusieurs demandes correspondent à ce tableau. Vérifiez la demande dans Yousign.")
        return found[0] if found else None

    def _mutation(self, record, owner, state, step, call):
        if state.get("uncertain_step"):
            raise SignatureError("Le résultat de la précédente opération Yousign est encore incertain. Actualisez pour le récupérer ; si cet état persiste, vérifiez la demande dans Yousign avant de reprendre.")
        state["uncertain_step"] = step
        self._checkpoint(record, owner, state)
        try:
            result = call()
        except Exception as exc:
            # A definitive client rejection did not create the remote object.
            if (getattr(exc, "status_code", None) in {400, 401, 403, 404, 409, 413, 415, 422, 429}
                    or str(exc) == "Yousign limite temporairement les demandes. Réessayez dans quelques instants."):
                state.pop("uncertain_step", None)
                self._checkpoint(record, owner, state)
            raise
        state.pop("uncertain_step", None)
        return result

    @staticmethod
    def _reconciled(state, step):
        # A known document must never erase uncertainty about a later signer
        # creation. That would permit a duplicate if the provider is delayed.
        if state.get("uncertain_step") == step:
            state.pop("uncertain_step")

    @staticmethod
    def _verified_document(record, state, documents, *, check_original_hash):
        if len(documents) != 1:
            raise SignatureError("La demande doit contenir uniquement le tableau PDF préparé. Vérifiez son contenu dans Yousign.")
        document = documents[0]
        expected_id = state.get("document_id")
        if not document.get("id") or (expected_id and document["id"] != expected_id):
            raise SignatureError("Le document Yousign a été remplacé. Le tableau préparé ne peut pas être signé ou archivé à sa place.")
        filename = document.get("filename") or document.get("name")  # Older adapters used name.
        if filename != "tableau-aps-module-" + record["id"] + ".pdf" or document.get("nature") != "signable_document":
            raise SignatureError("Le document Yousign ne correspond pas au tableau PDF préparé.")
        # Once signatures have been applied, the bytes (and potentially the
        # provider's hash) change. The original hash was checked before sending;
        # subsequent checks require that exact, previously recorded document ID.
        if check_original_hash or not expected_id:
            if str(document.get("sha256") or "").casefold() != record["pdf_sha256"]:
                raise SignatureError("L'empreinte du document Yousign diffère du PDF figé. L'opération est interrompue.")
        return document

    def _verified_signer(self, signer, expected):
        info = signer.get("info") or {}
        for key in ("first_name", "last_name", "email"):
            if " ".join(str(info.get(key) or "").split()).casefold() != " ".join(str(expected[key]).split()).casefold():
                raise SignatureError("Les coordonnées d'un signataire Yousign diffèrent de celles du tableau préparé.")
        expected_phone = self.host._normalize_yousign_sms_phone(expected.get("phone"))
        if signer.get("signature_authentication_mode") != ("otp_sms" if expected_phone else "otp_email"):
            raise SignatureError("Le mode de confirmation d'un signataire Yousign a changé.")
        if expected_phone:
            phone = self.host._normalize_yousign_sms_phone(info.get("phone_number"))
            if phone != expected_phone:
                raise SignatureError("Le téléphone de confirmation d'un signataire Yousign a changé.")

    def send(self, tenant_id, snapshot_id, *, actor=""):
        self._check()
        with self.store.lease(tenant_id, snapshot_id) as owner:
            record = self.store.get(tenant_id, snapshot_id)
            state, evidence = record["state"], record["evidence"]
            try:
                if record["status"] in {"signed", "signed_pending_archive", "ongoing"}:
                    return self._refresh(record, owner, state)
                if record["status"] in CLOSED_STATUSES:
                    raise SignatureError("Cette demande est clôturée. Son tableau et ses preuves restent consultables ; une nouvelle demande nécessite une nouvelle édition du tableau.")
                external_id = "native-aps-module-" + snapshot_id
                state["external_id"] = external_id
                if not state.get("request_id"):
                    request_obj = self._recover_request(external_id)
                    if not request_obj:
                        request_obj = self._mutation(record, owner, state, "create", lambda: self._json("POST", "/signature_requests", json={
                            "name": ("Suivi APS - " + evidence["course"]["title"] + " - " + evidence["learner"]["last_name"])[:128],
                            "delivery_mode": "email", "ordered_signers": False, "timezone": "Europe/Paris",
                            "external_id": external_id, "audit_trail_locale": "fr"}))
                    if not request_obj.get("id"):
                        raise SignatureError("Yousign n'a pas renvoyé l'identifiant de la demande.")
                    state["request_id"] = request_obj["id"]
                    self._reconciled(state, "create")
                    self._checkpoint(record, owner, state, event="request_created", actor=actor)
                request_id = state["request_id"]
                remote = self._json("GET", f"/signature_requests/{request_id}")
                if remote.get("external_id") != external_id:
                    raise SignatureError("La demande Yousign ne correspond pas à ce tableau.")
                if remote.get("status") != "draft":
                    return self._refresh(record, owner, state, remote=remote)
                filename = "tableau-aps-module-" + snapshot_id + ".pdf"
                docs = _items(self._json("GET", f"/signature_requests/{request_id}/documents"))
                doc = self._verified_document(record, state, docs, check_original_hash=True) if docs else None
                if state.get("document_id") and not doc:
                    raise SignatureError("Le document Yousign enregistré est introuvable. Vérifiez la demande avant de reprendre.")
                if not doc:
                    doc = self._mutation(record, owner, state, "document", lambda: self._json("POST",
                        f"/signature_requests/{request_id}/documents", files={"file": (filename, bytes(record["pdf"]), "application/pdf")},
                        data={"nature": "signable_document", "parse_anchors": "false"}))
                    self._verified_document(record, state, [doc], check_original_hash=True)
                state["document_id"] = doc["id"]
                state["original_pdf_sha256"] = record["pdf_sha256"]
                self._reconciled(state, "document")
                self._checkpoint(record, owner, state)
                signers = _items(self._json("GET", f"/signature_requests/{request_id}/signers"))
                expected_emails = {evidence[k]["email"].casefold() for k in ("learner", "responsible")}
                if len(signers) > 2 or any(str(s.get("info", {}).get("email", "")).casefold() not in expected_emails for s in signers):
                    raise SignatureError("Les signataires de la demande Yousign ont changé.")
                state.setdefault("signers", {})
                for role in ("learner", "responsible"):
                    person = evidence[role]
                    matches = [s for s in signers if str(s.get("info", {}).get("email", "")).casefold() == person["email"].casefold()]
                    if len(matches) > 1:
                        raise SignatureError("Ce destinataire apparaît plusieurs fois dans Yousign.")
                    signer = matches[0] if matches else None
                    known_id = state["signers"].get(role, {}).get("id")
                    if known_id and (not signer or signer.get("id") != known_id):
                        raise SignatureError("L'identité d'un signataire Yousign a changé. Vérifiez la demande avant de l'envoyer.")
                    if not signer:
                        info = {key: person[key] for key in ("first_name", "last_name", "email")}
                        info["locale"] = "fr"
                        phone = self.host._normalize_yousign_sms_phone(person.get("phone"))
                        if phone:
                            info["phone_number"] = phone
                        field = {**record["fields"][role], "document_id": state["document_id"], "type": "signature"}
                        signer = self._mutation(record, owner, state, "signer_" + role, lambda: self._json("POST",
                            f"/signature_requests/{request_id}/signers", json={"info": info, "signature_level": "electronic_signature",
                            "signature_authentication_mode": "otp_sms" if phone else "otp_email", "fields": [field]}))
                    if not signer.get("id"):
                        raise SignatureError("Yousign n'a pas renvoyé l'identifiant d'un signataire.")
                    self._verified_signer(signer, person)
                    state["signers"][role] = {"id": signer["id"], "email": person["email"], "status": signer.get("status", "initiated")}
                    self._reconciled(state, "signer_" + role)
                    self._checkpoint(record, owner, state)
                state["send_requested_by"] = str(actor)[:180]
                state["send_requested_at"] = state.get("send_requested_at") or utcnow()
                self._verified_document(record, state, _items(self._json("GET", f"/signature_requests/{request_id}/documents")), check_original_hash=True)
                self._checkpoint(record, owner, state, event="send_requested", actor=actor)
                self._mutation(record, owner, state, "activate", lambda: self._json("POST", f"/signature_requests/{request_id}/activate", json={}))
                state["last_error"] = ""
                self._checkpoint(record, owner, state, "ongoing", event="sent_to_two_signers", actor=actor)
                return self.store.get(tenant_id, snapshot_id)
            except Exception as exc:
                state["last_error"] = self.host._sanitize_yousign_error(str(exc)) if hasattr(self.host, "_sanitize_yousign_error") else str(exc)[:800]
                latest = self.store.get(tenant_id, snapshot_id)
                status = latest["status"] if latest["status"] not in {"prepared", "preparing"} else "preparing"
                self._checkpoint(record, owner, state, status)
                raise SignatureError(state["last_error"]) from exc

    def refresh(self, tenant_id, snapshot_id):
        self._check()
        with self.store.lease(tenant_id, snapshot_id) as owner:
            record = self.store.get(tenant_id, snapshot_id)
            state = record["state"]
            try:
                return self._refresh(record, owner, state)
            except Exception as exc:
                state["last_error"] = self.host._sanitize_yousign_error(str(exc)) if hasattr(self.host, "_sanitize_yousign_error") else str(exc)[:800]
                latest = self.store.get(tenant_id, snapshot_id)
                self._checkpoint(record, owner, state, latest["status"])
                raise SignatureError(state["last_error"]) from exc

    def _refresh(self, record, owner, state, remote=None):
        request_id = state.get("request_id")
        if not request_id:
            found = self._recover_request("native-aps-module-" + record["id"])
            if not found:
                return record
            request_id = state["request_id"] = found["id"]
            state["external_id"] = "native-aps-module-" + record["id"]
            self._reconciled(state, "create")
            self._checkpoint(record, owner, state)
        remote = remote or self._json("GET", f"/signature_requests/{request_id}")
        if remote.get("external_id") != "native-aps-module-" + record["id"]:
            raise SignatureError("La demande Yousign ne correspond pas à ce tableau.")
        status = str(remote.get("status") or "")
        if status not in {"draft", "ongoing", "done", "expired", "declined", "canceled", "rejected", "deleted", "approval"}:
            raise SignatureError("L'état retourné par Yousign n'est pas reconnu.")
        if status != "draft":
            self._reconciled(state, "activate")
        documents = _items(self._json("GET", f"/signature_requests/{request_id}/documents"))
        if documents or status != "draft" or state.get("document_id"):
            doc = self._verified_document(record, state, documents, check_original_hash=(status == "draft"))
            state["document_id"] = doc["id"]
            self._reconciled(state, "document")
        signers = _items(self._json("GET", f"/signature_requests/{request_id}/signers"))
        evidence = record["evidence"]
        verified = {}
        for role in ("learner", "responsible"):
            expected = evidence[role]
            matches = [s for s in signers if str(s.get("info", {}).get("email", "")).casefold() == expected["email"].casefold()]
            if len(matches) != 1:
                if status == "draft" and not matches:
                    continue
                raise SignatureError("Les deux signataires attendus ne sont pas confirmés par Yousign.")
            signer = matches[0]
            self._verified_signer(signer, expected)
            known_id = state.get("signers", {}).get(role, {}).get("id")
            if known_id and known_id != signer.get("id"):
                raise SignatureError("L'identité d'un signataire Yousign a changé.")
            verified[role] = {"id": signer["id"], "email": expected["email"], "status": signer.get("status"),
                              "signed_at": signer.get("signed_at") or None}
            self._reconciled(state, "signer_" + role)
        if len(signers) > 2:
            raise SignatureError("La demande comporte des signataires supplémentaires non prévus.")
        if len(verified) != len(signers):
            raise SignatureError("La demande comporte un signataire différent de ceux du tableau.")
        state["signers"] = verified
        state["provider_status"] = status
        state["last_checked_at"] = utcnow()
        state["last_error"] = ""
        if status != "done":
            self._checkpoint(record, owner, state, "prepared" if status == "draft" else "ongoing" if status == "approval" else status)
            return self.store.get(record["tenant_id"], record["id"])
        if len(verified) != 2 or any(s.get("status") != "signed" for s in verified.values()):
            raise SignatureError("Yousign n'a pas confirmé les deux signatures. Le tableau n'est pas déclaré signé.")
        first_confirmation = not state.get("two_signatures_confirmed_at")
        state["two_signatures_confirmed_at"] = state.get("two_signatures_confirmed_at") or utcnow()
        state["provider_completed_at"] = remote.get("completed_at") or None
        self._checkpoint(record, owner, state, "signed_pending_archive", event="two_signatures_confirmed" if first_confirmation else "")
        try:
            targets = {"tableau-signe": (f"/signature_requests/{request_id}/documents/download", {"version": "completed", "archive": "false"})}
            for role, signer in verified.items():
                targets["preuve-" + role] = (f"/signature_requests/{request_id}/signers/{signer['id']}/audit_trails/download", {})
            for kind, (path, params) in targets.items():
                if self.store.artifact(record["tenant_id"], record["id"], kind):
                    continue
                content = self.host._yousign_request("GET", path, params=params, headers={"Accept": "application/pdf"}).content
                self.store.save_artifact(record["id"], kind, content)
                self._checkpoint(record, owner, state, "signed_pending_archive")
        except Exception:
            state["last_error"] = "Les deux signatures sont confirmées ; la récupération des pièces doit être reprise."
            self._checkpoint(record, owner, state, "signed_pending_archive")
            return self.store.get(record["tenant_id"], record["id"])
        first_archive = not state.get("archived_at")
        state["archived_at"] = state.get("archived_at") or utcnow()
        self._checkpoint(record, owner, state, "signed", event="archive_complete" if first_archive else "")
        return self.store.get(record["tenant_id"], record["id"])
