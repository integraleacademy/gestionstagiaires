"""CMA simulation pages and authenticated, CSRF-protected attempt API."""
import secrets

from flask import abort, jsonify, render_template, request, session, url_for

from . import vtc_cma as cma
from .paths import allows_free_module_navigation, assigned_modules


CORRECTION_UNAVAILABLE = "La correction est momentanément indisponible. Vos réponses sont conservées ; vous pourrez réessayer dans quelques instants."


def register(blueprint, *, admin_required, learner_context, root, csrf_token, require_csrf):
    def database(*, preview=False):
        # Timed administrator trials use the learner engine without appearing
        # in learner records, course progress or organisation reports.
        return cma.CmaStore(root() / ("cma_admin_preview.sqlite3" if preview else "tracking.sqlite3"))

    def preview_access(*, create=False):
        if not session.get("admin_logged_in"):
            abort(403)
        if create and not session.get("cma_preview_owner"):
            session["cma_preview_owner"] = secrets.token_hex(16)
        owner = session.get("cma_preview_owner")
        if not owner:
            raise cma.CmaError("Essai introuvable. Démarrez une simulation chronométrée.", status=404)
        return ("admin-preview", owner)

    def learner_access(token):
        # Resolve current authentication/entitlement/date once on every request.
        # The independent CMA paper only needs module assignments, not seven
        # full video/course projections for each autosave.
        session_obj, trainee, _ = learner_context(token, "academy-vtc-a")
        assigned = {module["course_id"] for module in assigned_modules(session_obj)}
        required = {"academy-vtc-" + letter.lower() for letter in cma.LETTERS}
        identity = (str(session_obj["id"]), str(trainee.get("id") or trainee.get("trainee_id") or ""))
        if not identity[1] or not allows_free_module_navigation(session_obj) or not required <= assigned:
            abort(403)
        return identity

    def payload():
        require_csrf()
        if session.get("admin_logged_in") and session.get("admin_role") == "viewer":
            abort(403)
        if request.content_length and request.content_length > 100_000:
            abort(413)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise cma.CmaError("Requête invalide.")
        return data

    def ai_available():
        from .vtc_ai import ai_configured
        return ai_configured()

    def serialize(state, token=None):
        bank = cma.load_bank(state["version"])
        public = cma.public_attempt(bank, state)
        prefix = "cma_learner_" if token else "cma_admin_exam_"
        public["urls"] = {action: url_for("native_elearning." + prefix + action,
                                          **({"token": token} if token else {}), attempt_id=state["id"])
                          for action in ("state", "save", "submit", "start_part", "pause", "resume", "reset", "grade")}
        if public.get("result"):
            # Older attempts may have retained an obsolete provider-labelled
            # error. Keep the stored history and expose the current wording.
            for result in public["result"]["subjects"]:
                if result.get("grading_error"):
                    result["grading_error"] = CORRECTION_UNAVAILABLE
            add_links(public["result"]["subjects"], token)
        return public

    def add_links(subjects, token=None):
        for result in subjects:
            for correction in result["corrections"]:
                correction["lesson_links"] = [{"ref": ref, "url": url_for(
                    "native_elearning.annales_learner_lesson", token=token, ref=ref) if token else url_for(
                    "native_elearning.annales_admin_lesson", ref=ref)} for ref in correction["lesson_refs"]]
            result["lesson_links"] = [{"ref": ref, "url": url_for(
                "native_elearning.annales_learner_lesson", token=token, ref=ref) if token else url_for(
                "native_elearning.annales_admin_lesson", ref=ref)} for ref in result["lesson_refs"]]

    def home(token=None):
        bank, state, history = cma.load_bank(), None, []
        if token:
            principal = learner_access(token)
            db = database()
            history = db.history(*principal)
            for row in history:
                row["url"] = url_for("native_elearning.cma_learner_home", token=token, attempt=row["id"])
            if request.args.get("attempt"):
                state = db.read(*principal, request.args["attempt"])
                bank = cma.load_bank(state["version"])
        elif request.args.get("attempt"):
            state = database(preview=True).read(*preview_access(), request.args["attempt"])
            bank = cma.load_bank(state["version"])
        config = {"bank": cma.public_bank(bank, questions=not token), "preview": not token,
                  "adminPreview": not token,
                  "csrfToken": csrf_token(), "aiAvailable": ai_available(),
                  "homeUrl": url_for("native_elearning.cma_learner_home", token=token) if token else url_for("native_elearning.cma_admin_home"),
                  "startUrl": url_for("native_elearning.cma_learner_create", token=token) if token else url_for("native_elearning.cma_admin_exam_create"),
                  "previewGradeUrl": url_for("native_elearning.cma_admin_correct") if not token else None,
                  "state": serialize(state, token) if state else None}
        return render_template("vtc_cma_simulation.html", config=config, bank=config["bank"], history=history,
                               preview=not token, back_url=url_for("native_elearning.learner_path", token=token)
                               if token else url_for("native_elearning.admin_vtc_catalog"))

    def json_state(state, token):
        return jsonify(ok=True, state=serialize(state, token))

    def validate_version(data, state):
        if data.get("version") != state["version"]:
            raise cma.CmaError("L’édition du sujet ne correspond pas à votre tentative. Rechargez la page.", status=409)

    def mutate(token, attempt_id, action):
        data = payload()
        principal = learner_access(token) if token else preview_access()
        db = database(preview=not token)
        state = db.read(*principal, attempt_id)
        validate_version(data, state)
        letter = data.get("subject")
        cma.subject_for(cma.load_bank(state["version"]), letter)
        if action == "start":
            state = db.start_part(*principal, attempt_id, letter)
        elif action in {"pause", "resume", "reset"}:
            state = db.control(*principal, attempt_id, letter, action, data.get("revision"), answers=data.get("answers"))
        else:
            state = db.save(*principal, attempt_id, letter, data.get("answers"), data.get("revision"), submit=action == "submit")
        return json_state(state, token)

    @blueprint.errorhandler(cma.CmaError)
    def cma_error(exc):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=str(exc), code=exc.code), exc.status
        return render_template("vtc_cma_unavailable.html", message=str(exc)), exc.status

    @blueprint.after_request
    def cma_private(response):
        if (request.endpoint or "").startswith("native_elearning.cma_"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @blueprint.get("/admin/elearning/vtc/simulation-cma")
    @admin_required
    def cma_admin_home():
        return home()

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/start")
    @admin_required
    def cma_admin_exam_create():
        data = payload()
        if data.get("version") != cma.CURRENT_VERSION:
            raise cma.CmaError("Le sujet a évolué. Rechargez la page avant de commencer.", status=409)
        return json_state(database(preview=True).create(*preview_access(create=True)), None)

    @blueprint.get("/api/admin/elearning/vtc/simulation-cma/<attempt_id>")
    @admin_required
    def cma_admin_exam_state(attempt_id):
        return json_state(database(preview=True).read(*preview_access(), attempt_id), None)

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/save")
    @admin_required
    def cma_admin_exam_save(attempt_id):
        return mutate(None, attempt_id, "save")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/submit")
    @admin_required
    def cma_admin_exam_submit(attempt_id):
        return mutate(None, attempt_id, "submit")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/pause")
    @admin_required
    def cma_admin_exam_pause(attempt_id):
        return mutate(None, attempt_id, "pause")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/resume")
    @admin_required
    def cma_admin_exam_resume(attempt_id):
        return mutate(None, attempt_id, "resume")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/reset")
    @admin_required
    def cma_admin_exam_reset(attempt_id):
        return mutate(None, attempt_id, "reset")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/next")
    @admin_required
    def cma_admin_exam_start_part(attempt_id):
        return mutate(None, attempt_id, "start")

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/<attempt_id>/grade")
    @admin_required
    def cma_admin_exam_grade(attempt_id):
        return grade_attempt(None, attempt_id)

    @blueprint.get("/espace/<token>/elearning/vtc/simulation-cma")
    def cma_learner_home(token):
        return home(token)

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/start")
    def cma_learner_create(token):
        data, principal = payload(), learner_access(token)
        if data.get("version") != cma.CURRENT_VERSION:
            raise cma.CmaError("Le sujet a évolué. Rechargez la page avant de commencer.", status=409)
        return json_state(database().create(*principal), token)

    @blueprint.get("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>")
    def cma_learner_state(token, attempt_id):
        principal = learner_access(token)
        return json_state(database().read(*principal, attempt_id), token)

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/save")
    def cma_learner_save(token, attempt_id):
        return mutate(token, attempt_id, "save")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/submit")
    def cma_learner_submit(token, attempt_id):
        return mutate(token, attempt_id, "submit")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/pause")
    def cma_learner_pause(token, attempt_id):
        return mutate(token, attempt_id, "pause")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/resume")
    def cma_learner_resume(token, attempt_id):
        return mutate(token, attempt_id, "resume")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/reset")
    def cma_learner_reset(token, attempt_id):
        return mutate(token, attempt_id, "reset")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/next")
    def cma_learner_start_part(token, attempt_id):
        return mutate(token, attempt_id, "start")

    @blueprint.post("/api/espace/<token>/elearning/vtc/simulation-cma/<attempt_id>/grade")
    def cma_learner_grade(token, attempt_id):
        return grade_attempt(token, attempt_id)

    def grade_attempt(token, attempt_id):
        from .vtc_ai import VtcAIError
        data = payload()
        principal = learner_access(token) if token else preview_access()
        db = database(preview=not token)
        state = db.read(*principal, attempt_id)
        validate_version(data, state)
        letter = data.get("subject")
        state, claim = db.claim_grading(*principal, attempt_id, letter)
        if claim is None:
            return json_state(state, token)
        try:
            correction = cma.grade_subject(cma.load_bank(state["version"]), letter, state["parts"][letter]["answers"])
        except VtcAIError:
            state = db.finish_grading(*principal, attempt_id, letter, claim,
                                     error=CORRECTION_UNAVAILABLE)
            return jsonify(ok=False, code="ai_unavailable", error=state["parts"][letter]["grading_error"], state=serialize(state, token)), 503
        # The entitlement is checked again after a potentially slow provider call.
        if token:
            learner_access(token)
        state = db.finish_grading(*principal, attempt_id, letter, claim, correction=correction)
        return json_state(state, token)

    @blueprint.post("/api/admin/elearning/vtc/simulation-cma/correct")
    @admin_required
    def cma_admin_correct():
        from .vtc_ai import VtcAIError
        data = payload()
        bank = cma.load_bank()
        if data.get("version") != bank["version"]:
            raise cma.CmaError("Rechargez l’aperçu de cette édition.", status=409)
        try:
            result = cma.grade_subject(bank, data.get("subject"), data.get("answers"))
        except VtcAIError:
            return jsonify(ok=False, error="La correction est momentanément indisponible. Réessayez dans quelques instants."), 503
        add_links([result])
        return jsonify(ok=True, result=result)
