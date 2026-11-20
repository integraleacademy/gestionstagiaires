"""A projection of learning access. The Campus never reads the administrative file."""
from contextlib import nullcontext
import datetime as dt
import hashlib
import hmac
import re
import secrets

from psycopg.types.json import Jsonb

from campus import db
from campus.identity import (_birth_to_ddmmyyyy, _norm_lastname, _public_trainee_birth_dates,
                             _public_trainee_last_names, _trainee_registration_is_cancelled)
import elearning_orders
import uv_questionnaires
from elearning_native.paths import assigned_modules
from elearning_native.vtc_enrolments import effective_learner_session

INTERNAL = "11111111-1111-4111-8111-111111111111"
TRAINING = ("id", "partner_id", "name", "nom", "training_type", "type", "type_formation",
            "date_start", "date_end", "date_debut", "date_fin", "afc_enabled", "aps_remote_start",
            "aps_remote_end", "aps_in_person_start", "aps_in_person_end", "aps_elearning_enabled",
            "aps_native_course_id", "aps_native_course_version", "aps_native_path_title",
            "aps_native_modules", "aps_native_automatic", "vtc_auto_access_available", "individual_aps_access")
PERSON = ("id", "first_name", "last_name", "training_date_start", "training_date_end",
          "afc_withdrawal_last_day", "aps_elearning_login", "vtc_programme_version",
          "vtc_lesson_video_version", *uv_questionnaires.UV_FIELDS)


def initialize():
    db.initialize_schemas()
    with db.pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.schema'))")
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.settings (
            name TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        conn.execute("""INSERT INTO campus_directory.settings VALUES ('identity_key', %s)
                      ON CONFLICT DO NOTHING""", (secrets.token_hex(32),))
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.enrolments (
            owner TEXT PRIMARY KEY, aliases TEXT[] NOT NULL, identities TEXT[] NOT NULL,
            public_link TEXT NOT NULL, training JSONB NOT NULL, learner JSONB NOT NULL,
            external BOOLEAN NOT NULL, revision TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.login_failures (
            key TEXT PRIMARY KEY, since TIMESTAMPTZ NOT NULL, failures INTEGER NOT NULL)""")
        for field in ("aliases", "identities"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS campus_{field} ON campus_directory.enrolments USING GIN ({field})")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _identity(secret, last, birth):
    return hmac.new(secret.encode(), (last + "|" + birth).encode(), hashlib.sha256).hexdigest()


def _select(obj, fields):
    return {k: obj[k] for k in fields if k in obj}


def project(data, host, secret):
    """Project access and module versions, never billing, documents or admin accounts."""
    import json
    for training in data.get("sessions", ()):
        if training.get("cancelled"):
            continue
        for learner in host._session_trainees_list(training):
            tokens = [learner.get(k) for k in ("public_token", "token")]
            tokens = list(dict.fromkeys(t.strip() for t in tokens if isinstance(t, str) and t.strip()))
            if not tokens or not training.get("id") or not learner.get("id") or _trainee_registration_is_cancelled(learner):
                continue
            effective = effective_learner_session(training, learner)
            if not (uv_questionnaires.eligible(training) or assigned_modules(effective)
                    or (effective.get("aps_elearning_enabled") and learner.get("aps_elearning_login"))):
                continue
            # UV eligibility uses the original classroom dates. Individual VTC/DESP grants
            # apply to e-learning only and must not unlock a classroom questionnaire.
            selected = _select(training, TRAINING)
            selected["campus_native"] = _select(effective, TRAINING)
            selected["partner_id"] = training.get("partner_id") or INTERNAL
            person = _select(learner, PERSON)
            person["first_name"] = learner.get("first_name") or learner.get("prenom") or ""
            person["last_name"] = learner.get("last_name") or learner.get("nom") or ""
            identities = sorted({_identity(secret, last, birth) for last in _public_trainee_last_names(learner)
                                 for birth in _public_trainee_birth_dates(learner)})
            owner = json.dumps([selected["partner_id"], training["id"], learner["id"]], separators=(",", ":"))
            yield owner, sorted(digest(t) for t in tokens), identities, tokens[0], selected, person, False
    active = {partner["id"] for partner in data.get("partners", ()) if partner.get("status") in {"active", "trial"}}
    for order in data.get("manual_orders", ()):
        if order.get("partner_id") not in active or not elearning_orders.entitled(order):
            continue
        for person in order.get("learners", ()):
            key = person.get("token_hash", "")
            if not person.get("activated_at") or not re.fullmatch(r"[a-f0-9]{64}", key):
                continue
            training = {"id": "el-" + order["id"], "partner_id": order["partner_id"],
                        "name": order.get("group_name") or elearning_orders.course_label(order["course_code"]),
                        "training_type": elearning_orders.course_label(order["course_code"]),
                        "date_start": person["activated_at"][:10], "aps_elearning_enabled": True,
                        "aps_native_modules": order["modules"], "aps_native_path_title": "Mon parcours " + elearning_orders.course_label(order["course_code"]),
                        "learner_brand": elearning_orders.learner_brand(data, order)}
            owner = json.dumps([order["partner_id"], training["id"], person["id"]], separators=(",", ":"))
            yield owner, [key], [], "", training, _select(person, ("id", "first_name", "last_name")), True


def synchronize(read_source, host, *, connection=None):
    """Take one authoritative snapshot and publish additions and revocations atomically."""
    import json
    with (nullcontext(connection) if connection is not None else db.pool().connection()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.roster'))")
        data = read_source()
        if not isinstance(data.get("sessions"), list):
            raise ValueError("Annuaire administratif incomplet.")
        secret = conn.execute("SELECT value FROM campus_directory.settings WHERE name='identity_key'").fetchone()[0]
        owners, seen_tokens = set(), set()
        for owner, aliases, identities, link, training, learner, external in project(data, host, secret):
            if owner in owners or seen_tokens.intersection(aliases):
                raise ValueError("Accès pédagogique ambigu. Annuaire précédent conservé.")
            seen_tokens.update(aliases)
            owners.add(owner)
            revision = digest(json.dumps([aliases, identities, link, training, learner, external], sort_keys=True))
            conn.execute("""INSERT INTO campus_directory.enrolments VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(owner) DO UPDATE SET aliases=EXCLUDED.aliases, identities=EXCLUDED.identities,
                public_link=EXCLUDED.public_link, training=EXCLUDED.training, learner=EXCLUDED.learner,
                external=EXCLUDED.external, revision=EXCLUDED.revision
                WHERE campus_directory.enrolments.revision <> EXCLUDED.revision""",
                (owner, aliases, identities, link, Jsonb(training), Jsonb(learner), external, revision))
        conn.execute("DELETE FROM campus_directory.enrolments WHERE NOT (owner = ANY(%s::text[]))", (list(owners),))
        conn.execute("""INSERT INTO campus_directory.settings VALUES ('roster_synced',%s)
                     ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value""",(dt.datetime.now(dt.timezone.utc).isoformat(),))
    return len(owners)


def lookup(token):
    if not isinstance(token, str) or not 1 <= len(token) <= 160:
        return None
    with db.pool().connection() as conn:
        rows = conn.execute("""SELECT training, learner, external FROM campus_directory.enrolments
                            WHERE aliases @> ARRAY[%s] LIMIT 2""", (digest(token),)).fetchall()
    return rows[0] if len(rows) == 1 else None


def authenticate(last, birth, token=None):
    last, birth = _norm_lastname(last), _birth_to_ddmmyyyy(birth)
    if not last or not birth:
        return None
    with db.pool().connection() as conn:
        secret = conn.execute("SELECT value FROM campus_directory.settings WHERE name='identity_key'").fetchone()[0]
        key = _identity(secret, last, birth)
        if token:
            row = conn.execute("""SELECT public_link FROM campus_directory.enrolments
                    WHERE identities @> ARRAY[%s] AND aliases @> ARRAY[%s] AND NOT external""",
                    (key, digest(token))).fetchone()
            return token if row else None
        rows = conn.execute("""SELECT public_link FROM campus_directory.enrolments
                          WHERE identities @> ARRAY[%s] AND NOT external LIMIT 2""", (key,)).fetchall()
        return rows[0][0] if len(rows) == 1 else None


def failure_key(secret, remote):
    return hmac.new(secret.encode(), remote.encode(), hashlib.sha256).hexdigest()


def too_many_failures(key):
    with db.pool().connection() as conn:
        return bool(conn.execute("""SELECT 1 FROM campus_directory.login_failures WHERE key=%s
            AND since > now() - interval '10 minutes' AND failures >= 40""", (key,)).fetchone())


def note_failure(key):
    with db.pool().connection() as conn:
        conn.execute("""INSERT INTO campus_directory.login_failures VALUES (%s,now(),1)
            ON CONFLICT(key) DO UPDATE SET
              failures=CASE WHEN login_failures.since < now() - interval '10 minutes' THEN 1 ELSE login_failures.failures+1 END,
              since=CASE WHEN login_failures.since < now() - interval '10 minutes' THEN now() ELSE login_failures.since END""", (key,))
        conn.execute("DELETE FROM campus_directory.login_failures WHERE since < now() - interval '1 day'")
