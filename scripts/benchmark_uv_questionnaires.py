"""Exercise the actual UV routes over local HTTP with synchronized learners.

This is a local load test, not a production load generator. Its default harness
uses the real questionnaire routes/storage with synthetic business checks.
With --full-app it instead imports crm_app and uses its real checks, data loader
and general writer. Both modes use synthetic data and the production Gunicorn
worker/thread counts. The full-app worker blocks non-loopback network access.

Example::

    python scripts/benchmark_uv_questionnaires.py --clients 24 --json-output /tmp/uv.json

Pass --module-file /path/to/previous/uv_questionnaires.py to compare an earlier
implementation against the same workload. The question bank remains the bank
from this checkout. The artificial general-save delay is reported separately;
it is a contention scenario, not a claim about measured production disk speed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import resource
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARTNER = "UV-BENCH-PARTNER"
TRAINING = "UV-BENCH-SESSION"
UV_NUMBER = 2
FIELDS = ("uv_questionnaire_attempts", "uv_questionnaires", "uv_questionnaire_resets")


def synthetic_data(clients: int, padding_mib: float = 0, legacy_duplicates=False,
                   trainee_records: int = 0) -> dict:
    """Build synthetic records; padding alone does not model normalization cost.

    ``trainee_records`` is the total number of distinct registrations, including
    the active cohort. Historical records include nested documents and billing
    histories so JSON decoding, billing snapshots and roster scans do real work.
    None of these records has a deliverable email address or telephone number.
    """
    if trainee_records and trainee_records < clients:
        raise ValueError("trainee_records must include every active client")
    people = [
        {"id": f"BENCH-{i:03}", "public_token": f"bench-token-{i:03}",
         "first_name": "Synthetic", "last_name": f"Learner {i}"}
        for i in range(clients)
    ]
    if legacy_duplicates:
        for person in people:
            person["created_at"] = "2026-10-26T08:00:00Z"
        people += [{**person, "first_name": "Divergent legacy copy"} for person in people]
    data = {
        "sessions": [{"id": TRAINING, "partner_id": PARTNER, "training_type": "APS",
                      "name": "Synthetic UV load test", "date_start": "2026-10-26",
                      "aps_in_person_start": "2026-10-26", "date_end": "2099-12-31",
                      "trainees": people}],
        "benchmark_padding": "x" * int(padding_mib * 1024 * 1024),
        "benchmark_revision": 0,
    }
    if not trainee_records:
        return data
    data.update(billing_lines=[], activity_logs=[], notifications_vtc_books=[])
    for ordinal in range(clients, trainee_records):
        group = (ordinal - clients) // 24
        if (ordinal - clients) % 24 == 0:
            course = ("APS", "SSIAP1", "A3P", "VTC")[group % 4]
            training = {"id": f"ARCHIVE-SESSION-{group:05}", "partner_id": PARTNER,
                        "training_type": course, "name": f"Synthetic archive {group}",
                        "date_start": "2025-01-01", "date_end": "2025-06-30", "trainees": []}
            data["sessions"].append(training)
        identifier = f"ARCHIVE-LEARNER-{ordinal:06}"
        person = {"id": identifier, "partner_id": PARTNER,
                  "public_token": f"synthetic-archive-token-{ordinal:06}",
                  "first_name": "Fictitious", "last_name": f"Record {ordinal}",
                  "birth_date": "1990-01-01", "created_at": "2025-01-01T08:00:00Z",
                  "email": "", "phone": "", "vae_action_dates": {},
                  "documents": [
                      {"key": f"synthetic-{ordinal}-{number}", "name": f"Fictitious document {number}",
                       "status": "received", "filename": f"missing-synthetic-{number}.pdf",
                       "uploaded_at": "2025-01-01T08:00:00Z",
                       "checks": {"format": "pdf", "status": "accepted", "synthetic": True}}
                      for number in range(8)]}
        training["trainees"].append(person)
        for number in range(3):
            data["billing_lines"].append({
                "id": f"SYNTHETIC-BILL-{ordinal}-{number}", "partner_id": PARTNER,
                "session_id": training["id"], "trainee_id": identifier,
                "label": "Synthetic archived billing record", "amount": 100,
                "invoiceStatus": "not_invoiced", "paymentStatus": "not_applicable",
                "billingHistory": [{"at": "2025-01-01T08:00:00Z", "action": "synthetic",
                                    "details": {"position": item, "label": "Non-production history"}}
                                   for item in range(12)]})
        data["activity_logs"].append({"id": f"SYNTHETIC-ACTIVITY-{ordinal}", "partner_id": PARTNER,
                                      "action": "synthetic fixture", "trainee_id": identifier})
        if training["training_type"] == "VTC":
            data["notifications_vtc_books"].append({
                "id": f"SYNTHETIC-NOTICE-{ordinal}", "partner_id": PARTNER, "done": True,
                "meta": {"session_id": training["id"], "trainee_id": identifier}})
    return data


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("uv_benchmark_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load questionnaire module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BANK_DIR = ROOT / "uv_questionnaires"
    # Keep course access deterministic when the benchmark is rerun in future.
    module.today = lambda: datetime(2026, 11, 18).date()
    return module


class SyntheticServices(SimpleNamespace):
    """Small business boundary with real JSON read/replace and locking."""

    def __init__(self, data_file: Path, save_delay_ms=0, background_hold_ms=120,
                 background_mode="save"):
        super().__init__()
        self.DATA_FILE = str(data_file)
        self.INTEGRALE_PARTNER_ID = PARTNER
        self.write_lock = threading.RLock()
        self.save_delay = save_delay_ms / 1000
        self.background_hold = background_hold_ms / 1000
        self.general_saves = 0
        self.background_saves = 0
        self.background_holds = 0
        self.background_mode = background_mode
        self.background_error = None
        self.background_stop = threading.Event()
        self.background_ready = threading.Event()
        self.background_thread = None
        self.admin_login_required = lambda view: view
        self.admin_write_required = lambda view: view

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _trainee_registration_is_cancelled(trainee):
        return bool(trainee.get("cancelled"))

    @staticmethod
    def _public_is_authed(token):
        from flask import session
        return session.get("benchmark_token") == token

    @staticmethod
    def _is_super_admin_session():
        return True

    @staticmethod
    def _current_partner_id():
        return PARTNER

    @staticmethod
    def find_session_and_trainee_by_token(data, token):
        for training in data.get("sessions", []):
            for trainee in training.get("trainees", []):
                if trainee.get("public_token") == token:
                    return training, trainee
        return None, None

    @staticmethod
    def _find_session_trainee(data, session_id, trainee_id):
        for training in data.get("sessions", []):
            if training["id"] == session_id:
                for index, trainee in enumerate(training.get("trainees", [])):
                    if trainee["id"] == trainee_id:
                        return training, index, trainee
        return None, None, None

    def load_data(self, **_kwargs):
        with open(self.DATA_FILE, encoding="utf-8") as source:
            return json.load(source)

    @contextmanager
    def locked_general_data(self):
        with self.write_lock, open(self.DATA_FILE + ".lock", "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _replace(self, data):
        destination = Path(self.DATA_FILE)
        temporary = destination.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as target:
            json.dump(data, target, separators=(",", ":"), ensure_ascii=False)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)

    def _atomic_update_data(self, mutate):
        with self.locked_general_data():
            data = self.load_data()
            result = mutate(data)
            if self.save_delay:
                time.sleep(self.save_delay)
            self._replace(data)
            self.general_saves += 1
            return result

    def start_background(self):
        if self.background_mode == "none":
            return
        if self.background_thread is not None:
            return

        def run():
            if self.background_mode == "hold":
                with self.locked_general_data():
                    self.background_holds += 1
                    self.background_ready.set()
                    self.background_stop.wait()
                return
            while not self.background_stop.is_set():
                try:
                    with self.locked_general_data():
                        data = self.load_data()
                        data["benchmark_revision"] += 1
                        time.sleep(self.background_hold)
                        self._replace(data)
                        self.background_saves += 1
                    if self.background_mode == "once":
                        return
                except Exception as exc:
                    self.background_error = repr(exc)
                    return
                self.background_stop.wait(0.35)

        self.background_thread = threading.Thread(target=run, name="synthetic-general-save", daemon=True)
        self.background_thread.start()
        if self.background_mode == "hold" and not self.background_ready.wait(timeout=5):
            raise RuntimeError("The general writer lock could not be held for the test")

    def stop_background(self):
        self.background_stop.set()
        if self.background_thread:
            self.background_thread.join(timeout=10)


def block_external_network():
    """Install the repository test-suite's loopback-only rule before app import."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def allowed(sock, address):
        if sock.family == socket.AF_UNIX:
            return True
        host = str(address[0]).strip().lower() if isinstance(address, tuple) and address else ""
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def connect(sock, address):
        if not allowed(sock, address):
            raise RuntimeError("External network disabled during UV load test")
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if not allowed(sock, address):
            raise RuntimeError("External network disabled during UV load test")
        return original_connect_ex(sock, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


class FullAppControls(SyntheticServices):
    """Load-test control endpoints around the unmodified application services."""

    def __init__(self, services, background_hold_ms, background_mode="save"):
        super().__init__(Path(services.DATA_FILE), background_hold_ms=background_hold_ms,
                         background_mode=background_mode)
        self.real_services = services
        self.write_lock = services._data_lock
        self.other_general_saves = 0
        self.uv_side_effect_writes = 0
        self.uv_load_data_seconds = []
        self.uv_context_seconds = []
        self.counter_lock = threading.Lock()
        original_write = services._write_json_with_backups

        def counted_write(path, *args, **kwargs):
            from flask import has_request_context, request
            if has_request_context() and "/questionnaires-uv/" in request.path:
                with self.counter_lock:
                    self.uv_side_effect_writes += 1
            if os.path.abspath(path) == os.path.abspath(services.DATA_FILE):
                with self.counter_lock:
                    if has_request_context() and "/questionnaires-uv/" in request.path:
                        self.general_saves += 1
                    elif threading.current_thread().name != "synthetic-general-save":
                        self.other_general_saves += 1
            return original_write(path, *args, **kwargs)

        services._write_json_with_backups = counted_write

    def start_background(self):
        if self.background_mode == "none":
            return
        if self.background_thread is not None:
            return
        if self.background_mode == "hold":
            return super().start_background()

        def run():
            while not self.background_stop.is_set():
                try:
                    def mutate(data):
                        data["benchmark_revision"] = data.get("benchmark_revision", 0) + 1
                        time.sleep(self.background_hold)
                    # The real writer holds its RLock/file lock, reconciles the
                    # general payload, takes backups and fsyncs the replacement.
                    self.real_services._atomic_update_data(mutate)
                    self.background_saves += 1
                    if self.background_mode == "once":
                        return
                except Exception as exc:
                    self.background_error = repr(exc)
                    return
                self.background_stop.wait(.35)

        self.background_thread = threading.Thread(target=run, name="synthetic-general-save", daemon=True)
        self.background_thread.start()


def create_harness(config: dict):
    """Construct real UV routes; callable directly by concurrency regression tests."""
    from flask import Flask, abort, jsonify, session

    block_external_network()
    full_app = bool(config.get("full_app"))
    if full_app:
        os.environ["PERSIST_DIR"] = str(Path(config["data_file"]).parent)
        os.environ["SECRET_KEY"] = config["secret"]
        # Freeze the UV modules under their canonical import names before
        # app.py imports them. Concurrent review edits cannot change this run.
        for name in ("uv_questionnaire_context", "uv_questionnaires"):
            frozen = config.get("frozen_uv_modules", {}).get(name)
            if not frozen:
                continue
            spec = importlib.util.spec_from_file_location(name, frozen)
            frozen_module = importlib.util.module_from_spec(spec)
            sys.modules[name] = frozen_module
            spec.loader.exec_module(frozen_module)
            if name == "uv_questionnaires":
                frozen_module.BANK_DIR = ROOT / "uv_questionnaires"
        # Do not import the CRM until the temporary storage and network guard
        # are in place. No Gunicorn production lifecycle hooks are loaded.
        import crm_app
        import app as real_services
        app = crm_app.app
        assert Path(real_services.DATA_FILE).resolve() == Path(config["data_file"]).resolve()
        module = real_services.uv_questionnaires
        module.today = lambda: datetime(2026, 11, 18).date()
        services = FullAppControls(real_services, config.get("background_hold_ms", 120),
                                   config.get("background_mode", "save"))
        if config.get("legacy_context"):
            if not hasattr(module, "_public_pair"):
                raise RuntimeError("--legacy-context requires the cached-context implementation")

            def legacy_pair(host, token, **_kwargs):
                began = time.perf_counter()
                try:
                    payload = host.load_data(run_background_tasks=False, persist_normalization=False)
                    return host.find_session_and_trainee_by_token(payload, token)
                finally:
                    with services.counter_lock:
                        services.uv_load_data_seconds.append(time.perf_counter() - began)

            module._public_pair = legacy_pair
        if hasattr(module, "_public_pair"):
            original_pair = module._public_pair

            def timed_pair(host, token, **kwargs):
                began = time.perf_counter()
                try:
                    return original_pair(host, token, **kwargs)
                finally:
                    with services.counter_lock:
                        services.uv_context_seconds.append(time.perf_counter() - began)

            module._public_pair = timed_pair
    else:
        module = _load_module(Path(config.get("module_file") or ROOT / "uv_questionnaires.py"))
        app = Flask("uv-load-harness", template_folder=str(ROOT / "templates"),
                    static_folder=str(ROOT / "static"))
        services = SyntheticServices(Path(config["data_file"]), config.get("save_delay_ms", 0),
                                     config.get("background_hold_ms", 120),
                                     config.get("background_mode", "save"))
        services.app = app
    app.secret_key = config.get("secret") or secrets.token_hex(32)
    app.config.update(TESTING=full_app, UV_QUESTIONNAIRE_DB_PATH=config["db_path"],
                      SESSION_COOKIE_SECURE=False)  # this server binds loopback HTTP only

    @app.get("/benchmark/health", endpoint="uv_benchmark_health")
    def health():
        return jsonify(ok=True)

    @app.post("/benchmark/login/<int:learner>", endpoint="uv_benchmark_login")
    def login(learner):
        if learner < 0 or learner >= config["clients"]:
            abort(404)
        session.clear()
        session["benchmark_token"] = f"bench-token-{learner:03}"
        if full_app:
            session[f"public_auth_bench-token-{learner:03}"] = True
            real_services._stamp_authenticated_session()
        session["uv_questionnaire_csrf"] = f"benchmark-csrf-{learner:03}"
        return jsonify(csrf=session["uv_questionnaire_csrf"], generation="")

    if not full_app:
        @app.get("/healthz", endpoint="uv_benchmark_public_health")
        def public_health():
            return jsonify(ok=True)

        @app.get("/login/<token>", endpoint="public_trainee_login")
        def learner_login(token):
            return jsonify(error="Not authenticated"), 401

        @app.get("/espace/<token>", endpoint="public_trainee_space")
        def learner_space(token):
            return jsonify(ok=True)

        @app.get("/admin/<session_id>/<trainee_id>", endpoint="admin_trainee_page")
        def admin_space(session_id, trainee_id):
            return jsonify(ok=True)

    @app.post("/benchmark/background/start", endpoint="uv_benchmark_background_start")
    def background_start():
        services.start_background()
        return jsonify(ok=True)

    @app.post("/benchmark/background/stop", endpoint="uv_benchmark_background_stop")
    def background_stop():
        services.stop_background()
        return jsonify(ok=True)

    @app.get("/benchmark/results", endpoint="uv_benchmark_results")
    def results():
        data = services.load_data()
        native = Path(config["db_path"]).exists()
        database = None
        if native:
            from uv_questionnaire_store import UVQuestionnaireStore
            database = UVQuestionnaireStore(config["db_path"])
        states = []
        training = data["sessions"][0]
        seen = set()
        for trainee in training["trainees"]:
            creation_key = (trainee["id"], trainee.get("public_token"), trainee.get("created_at"))
            if creation_key in seen:
                continue
            seen.add(creation_key)
            state = database.read((training["partner_id"], training["id"], trainee["id"])) if database else None
            if state is None:
                state = {field: trainee[field] for field in FIELDS if field in trainee}
            states.append({"id": trainee["id"], "state": state})
        return jsonify(states=states, dedicated_database=native,
                       general_saves=services.general_saves,
                       background_saves=services.background_saves,
                       background_holds=services.background_holds,
                       uv_side_effect_writes=getattr(services, "uv_side_effect_writes", None),
                       raw_registration_rows=len(training["trainees"]),
                       background_error=services.background_error,
                       legacy_context_load_data=latency_summary([{"seconds": value} for value in
                                                     getattr(services, "uv_load_data_seconds", [])]),
                       uv_context_lookup=latency_summary([{"seconds": value} for value in
                                                     getattr(services, "uv_context_seconds", [])]),
                       worker_peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                       uv_context_index_builds=(module.index_for(config["data_file"]).build_count
                                                if hasattr(module, "index_for") else None),
                       json_contains_uv_states=any(any(field in t for field in FIELDS)
                           for t in data["sessions"][0]["trainees"]))

    if not full_app:
        module.register(app, services)
    return app, services, module


def create_app():
    """Gunicorn factory. The config file is created only by the local launcher."""
    config_path = Path(os.environ["UV_BENCH_CONFIG"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return create_harness(config)[0]


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def latency_summary(samples):
    values = [sample["seconds"] * 1000 for sample in samples]
    return {"count": len(values), "p50_ms": round(_percentile(values, .5), 2) if values else None,
            "p95_ms": round(_percentile(values, .95), 2) if values else None,
            "p99_ms": round(_percentile(values, .99), 2) if values else None,
            "max_ms": round(max(values), 2) if values else None}


class HealthProbe:
    """Exercise the real HTTP liveness route while all four threads are busy."""

    def __init__(self, base_url, budget_seconds=5, interval_seconds=.5):
        self.url = base_url + "/healthz"
        self.budget = budget_seconds
        self.interval = interval_seconds
        self.samples = []
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name="synthetic-health-probe", daemon=True)

    def _run(self):
        import requests

        with requests.Session() as client:
            while not self.stopping.is_set():
                started = time.perf_counter()
                sample = {"status": None}
                try:
                    response = client.get(self.url, timeout=(min(1, self.budget), self.budget),
                                          allow_redirects=False)
                    sample["status"] = response.status_code
                    sample["ok"] = response.status_code == 200 and response.json().get("ok") is True
                except (requests.RequestException, ValueError) as exc:
                    sample.update(ok=False, error=type(exc).__name__)
                sample["seconds"] = time.perf_counter() - started
                sample["within_deadline"] = sample["seconds"] < self.budget
                self.samples.append(sample)
                self.stopping.wait(self.interval)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=self.budget + 3)
        if self.thread.is_alive():
            raise RuntimeError("The bounded local health probe did not stop")

    def report(self):
        failed = sum(not sample["ok"] for sample in self.samples)
        missed = sum(not sample["within_deadline"] for sample in self.samples)
        return {"path": "/healthz", "budget_seconds": self.budget,
                "interval_seconds": self.interval, **latency_summary(self.samples),
                "failed_requests": failed, "missed_deadlines": missed,
                "passed": bool(self.samples) and not failed and not missed,
                "samples": [{**{key: value for key, value in sample.items() if key != "seconds"},
                             "duration_ms": round(sample["seconds"] * 1000, 2)}
                            for sample in self.samples]}


def validate_persisted_states(result, questions, clients, *, require_background_saves=True):
    failures = []
    expected = {question["id"]: question["answer"] for question in questions}
    if len(result["states"]) != clients:
        failures.append(f"Expected {clients} persisted learners, got {len(result['states'])}")
    for saved in result["states"]:
        state = saved["state"]
        attempt = state.get("uv_questionnaire_attempts", {}).get("aps", {}).get(str(UV_NUMBER), {})
        completed = state.get("uv_questionnaires", {}).get("aps", {}).get(str(UV_NUMBER), {})
        if completed.get("answers") != expected or completed.get("score") != len(questions):
            failures.append(f"{saved['id']}: answers/score were not fully persisted")
        if attempt.get("index") != len(questions) or attempt.get("answers") != expected:
            failures.append(f"{saved['id']}: attempt did not finish exactly once per question")
        if attempt.get("expired_deadlines"):
            failures.append(f"{saved['id']}: unexpected expired answer")
    if result.get("background_error"):
        failures.append(f"Background save failed: {result['background_error']}")
    if require_background_saves and not result.get("background_saves"):
        failures.append("The concurrent background writer did not execute")
    return failures


def run_http_workload(base_url, clients, questions, *, health_budget_seconds=5,
                      health_interval_seconds=.5):
    import requests

    barrier = threading.Barrier(clients)
    samples = []
    errors = []
    sample_lock = threading.Lock()
    health = HealthProbe(base_url, health_budget_seconds, health_interval_seconds)

    def learner(index):
        client = requests.Session()
        login = client.post(f"{base_url}/benchmark/login/{index}", timeout=30, allow_redirects=False)
        login.raise_for_status()
        csrf = login.json()["csrf"]
        path = f"{base_url}/espace/bench-token-{index:03}/questionnaires-uv/{UV_NUMBER}"

        def submit(action, label=None, **payload):
            started = time.perf_counter()
            response = client.post(path, json={"csrf": csrf, "generation": "", "action": action,
                                               **payload}, timeout=60, allow_redirects=False)
            elapsed = time.perf_counter() - started
            sample = {"action": label or action, "seconds": elapsed,
                      "status": response.status_code, "learner": index,
                      "question_id": payload.get("question_id")}
            with sample_lock:
                samples.append(sample)
            if response.status_code != 200:
                raise AssertionError(f"learner {index}: HTTP {response.status_code} ({action}), "
                                     f"location={response.headers.get('Location', '')}")
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise AssertionError(f"learner {index}: UV route returned non-JSON content ({action})")
            state = response.json()
            if "server_processing_ms" in state:
                sample["server_processing_seconds"] = state["server_processing_ms"] / 1000
                sample["outside_handler_seconds"] = max(0, elapsed - sample["server_processing_seconds"])
            if state.get("answer_expired"):
                raise AssertionError(f"learner {index}: on-time answer expired")
            return state

        try:
            barrier.wait(timeout=90)
            state = submit("start", in_class="yes")
            for number, question in enumerate(questions):
                if state.get("question", {}).get("id") != question["id"]:
                    raise AssertionError(f"learner {index}: wrong question before submission {number + 1}")
                barrier.wait(timeout=90)
                state = submit("answer", question_id=question["id"], answer=question["answer"])
                if number in {0, 4, 9, 14, 19}:
                    # Simulate losing an acknowledgement then retrying after a
                    # new connection. Server-side answer receipt really happened.
                    if number == 9:
                        cookies = client.cookies.copy()
                        client.close()
                        client = requests.Session()
                        client.cookies.update(cookies)
                    replay = submit("answer", label="answer_replay", question_id=question["id"],
                                    answer=question["answer"])
                    if replay.get("index") != state.get("index") or replay.get("completed") != state.get("completed"):
                        raise AssertionError(f"learner {index}: repeated answer advanced the questionnaire")
                    state = replay
                if index == 0 and (number + 1) % 5 == 0:
                    print(f"UV load test: {clients} learners, question {number + 1}/{len(questions)}",
                          file=sys.stderr, flush=True)
            if state != {"completed": True, "score": len(questions)}:
                raise AssertionError(f"learner {index}: incorrect completion {state}")
            barrier.wait(timeout=90)
            return index
        except Exception:
            barrier.abort()
            raise
        finally:
            client.close()

    started = time.perf_counter()
    completed = []
    health.start()
    try:
        with ThreadPoolExecutor(max_workers=clients) as pool:
            futures = [pool.submit(learner, i) for i in range(clients)]
            for future in as_completed(futures):
                try:
                    completed.append(future.result())
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        health.stop()
    return {"duration_seconds": round(time.perf_counter() - started, 3),
            "completed_clients": len(completed), "errors": errors,
            "http_status_counts": {str(code): sum(s["status"] == code for s in samples)
                                   for code in sorted({s["status"] for s in samples})},
            "all_requests": latency_summary(samples),
            "health": health.report(),
            "server_processing": latency_summary([{"seconds": s["server_processing_seconds"]}
                                                     for s in samples if "server_processing_seconds" in s]),
            "outside_handler": latency_summary([{"seconds": s["outside_handler_seconds"]}
                                                   for s in samples if "outside_handler_seconds" in s]),
            "by_action": {action: latency_summary([s for s in samples if s["action"] == action])
                          for action in sorted({s["action"] for s in samples})}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=24)
    parser.add_argument("--padding-mib", type=float, default=8)
    parser.add_argument("--trainee-records", type=int, default=0,
                        help="Total structured registrations, including active clients; zero keeps the small fixture")
    parser.add_argument("--save-delay-ms", type=float, default=75,
                        help="Artificial delay per legacy general save, explicitly recorded in report")
    parser.add_argument("--background-hold-ms", type=float, default=120)
    parser.add_argument("--background-mode", choices=("none", "once", "save", "hold"), default="save",
                        help="No writer, one real save, repeated saves, or hold the general writer lock")
    parser.add_argument("--legacy-duplicates", action="store_true",
                        help="Add divergent old copies of each registration to exercise read-only normalization")
    parser.add_argument("--module-file", type=Path, default=ROOT / "uv_questionnaires.py")
    parser.add_argument("--full-app", action="store_true",
                        help="Exercise crm_app with real access checks/load_data and its real general writer")
    parser.add_argument("--legacy-context", action="store_true",
                        help="In full-app mode, force pre-cache load_data for every public UV lookup")
    parser.add_argument("--health-budget-seconds", type=float, default=5,
                        help="Maximum acceptable HTTP /healthz latency during the workload")
    parser.add_argument("--health-interval-seconds", type=float, default=.5)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    if args.clients < 2 or args.clients > 100:
        parser.error("--clients must be between 2 and 100")
    if min(args.padding_mib, args.save_delay_ms, args.background_hold_ms) < 0:
        parser.error("Sizes and artificial delays must be nonnegative")
    if args.trainee_records and not args.clients <= args.trainee_records <= 10000:
        parser.error("--trainee-records must be zero or between --clients and 10000")
    if args.health_budget_seconds <= 0 or args.health_interval_seconds <= 0:
        parser.error("Health deadlines and intervals must be positive")
    if args.legacy_context and not args.full_app:
        parser.error("--legacy-context requires --full-app")
    module_file = args.module_file.resolve()
    if args.full_app and module_file != ROOT / "uv_questionnaires.py":
        parser.error("--full-app uses this checkout's real application; it cannot load an alternate UV module")
    module_source = module_file.read_bytes()
    module_sha256 = hashlib.sha256(module_source).hexdigest()
    dependencies = (["app.py", "crm_app.py", "uv_questionnaires.py", "uv_questionnaire_store.py",
                     "uv_questionnaire_context.py"]
                    if args.full_app else (["uv_questionnaire_store.py"]
                                          if b"uv_questionnaire_store" in module_source else []))
    source_bytes = {name: (module_source if name == "uv_questionnaires.py" else (ROOT / name).read_bytes())
                    for name in dependencies if (ROOT / name).exists()}
    source_hashes = {name: hashlib.sha256(contents).hexdigest() for name, contents in source_bytes.items()}
    import requests

    with tempfile.TemporaryDirectory(prefix="uv-load-") as directory:
        temporary = Path(directory)
        # Root/agents may still be working on the checkout. Both the launcher
        # and the server must execute exactly the source identified in report.
        frozen_module = temporary / "uv_questionnaires_target.py"
        frozen_module.write_bytes(module_source)
        frozen_uv_modules = {}
        if args.full_app:
            for name in ("uv_questionnaire_context", "uv_questionnaires"):
                if name + ".py" in source_bytes:
                    path = temporary / (name + ".py")
                    path.write_bytes(source_bytes[name + ".py"])
                    frozen_uv_modules[name] = str(path)
        module = _load_module(frozen_module)
        questions = module.unit("aps", UV_NUMBER)["questions"]
        data_file = temporary / "data.json"
        fixture = synthetic_data(args.clients, args.padding_mib, args.legacy_duplicates, args.trainee_records)
        fixture_dimensions = {"distinct_trainees": args.trainee_records or args.clients,
                              "sessions": len(fixture["sessions"]),
                              "billing_lines": len(fixture.get("billing_lines", [])),
                              "documents_per_historical_trainee": 8 if args.trainee_records else 0,
                              "history_entries_per_billing_line": 12 if args.trainee_records else 0}
        data_file.write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")
        initial_data_bytes = data_file.stat().st_size
        del fixture
        config = {"data_file": str(data_file), "db_path": str(temporary / "uv-questionnaires.sqlite3"),
                  "module_file": str(frozen_module), "clients": args.clients,
                  "full_app": args.full_app,
                  "legacy_context": args.legacy_context,
                  "frozen_uv_modules": frozen_uv_modules,
                  "background_mode": args.background_mode,
                  "save_delay_ms": args.save_delay_ms, "background_hold_ms": args.background_hold_ms,
                  "secret": secrets.token_hex(32)}
        config_path = temporary / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        log_path = temporary / "gunicorn.log"
        # The child receives runtime settings only, never inherited application
        # credentials, payment/email keys, Render IDs or production endpoints.
        runtime_keys = ("PATH", "LANG", "LC_ALL", "TZ", "VIRTUAL_ENV", "LD_LIBRARY_PATH",
                        "SSL_CERT_FILE", "SSL_CERT_DIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE", "HOME")
        env = {name: os.environ[name] for name in runtime_keys if name in os.environ}
        env.update(UV_BENCH_CONFIG=str(config_path), PYTHONPATH=str(ROOT),
                   PERSIST_DIR=str(temporary), SECRET_KEY=config["secret"])
        command = [sys.executable, "-m", "gunicorn", "--config", os.devnull,
                   "--bind", f"127.0.0.1:{port}",
                   "--workers", "1", "--worker-class", "gthread", "--threads", "4",
                   "--timeout", "120", "--keep-alive", "90", "--access-logfile", os.devnull,
                   "--error-logfile", str(log_path), "scripts.benchmark_uv_questionnaires:create_app()"]
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            startup_end = time.monotonic() + (90 if args.full_app else 30)
            while True:
                try:
                    with urlopen(base_url + "/benchmark/health", timeout=.5) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if process.poll() is not None or time.monotonic() >= startup_end:
                        raise RuntimeError("Gunicorn could not start:\n" +
                                           (log_path.read_text()[-6000:] if log_path.exists() else "No log"))
                    time.sleep(.05)
            control = requests.Session()
            control.post(base_url + "/benchmark/background/start", timeout=30).raise_for_status()
            workload = run_http_workload(base_url, args.clients, questions,
                                         health_budget_seconds=args.health_budget_seconds,
                                         health_interval_seconds=args.health_interval_seconds)
            control.post(base_url + "/benchmark/background/stop", timeout=30).raise_for_status()
            result = control.get(base_url + "/benchmark/results", timeout=30)
            result.raise_for_status()
            persisted = result.json()
            control.close()
            failures = validate_persisted_states(persisted, questions, args.clients,
                                                require_background_saves=args.background_mode in ("save", "once"))
            if args.background_mode == "once" and persisted.get("background_saves") != 1:
                failures.append("The single concurrent general save did not execute exactly once")
            if args.background_mode == "hold" and persisted.get("background_holds") != 1:
                failures.append("The general writer lock was not held throughout the workload")
            if args.legacy_duplicates and args.background_mode == "hold" and persisted["raw_registration_rows"] != 2 * args.clients:
                failures.append("The old duplicate rows did not remain present for the entire lock test")
            if args.full_app and (not persisted["dedicated_database"] or persisted["uv_side_effect_writes"]):
                failures.append("Full-app UV requests must use SQLite without general or archive writes")
            execution_paths = {name: Path(frozen_uv_modules.get(name.removesuffix(".py"), ROOT / name))
                               for name in source_hashes}
            unchanged = all(hashlib.sha256(execution_paths[name].read_bytes()).hexdigest() == digest
                            for name, digest in source_hashes.items())
            changed_checkout_files = [name for name, digest in source_hashes.items()
                                      if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
            if not unchanged:
                failures.append("Application sources changed during the run; rerun on a stable checkout")
            report = {
                "scope": ("local HTTP full crm_app; real access checks, load_data, UV persistence and general writer; synthetic data"
                          if args.full_app else "local HTTP harness; real UV routes/storage; synthetic business access checks/data"),
                "full_app": args.full_app,
                "public_context_mode": "legacy_normalization" if args.legacy_context else "checkout_implementation",
                "module_file": str(module_file), "module_sha256": module_sha256,
                "source_hashes": source_hashes, "sources_unchanged_during_run": unchanged,
                "frozen_source_modules": sorted(frozen_uv_modules),
                "live_checkout_files_changed": changed_checkout_files,
                "gunicorn": {"workers": 1, "threads": 4, "worker_class": "gthread", "keepalive_seconds": 90},
                "clients": args.clients, "questions_per_client": len(questions),
                "expected_persisted_answers": args.clients * len(questions),
                "fixture": fixture_dimensions,
                "initial_general_json_bytes": initial_data_bytes,
                "padding_mib": args.padding_mib, "general_json_bytes": data_file.stat().st_size,
                "legacy_duplicate_registrations": args.legacy_duplicates,
                "raw_registration_rows_at_end": persisted["raw_registration_rows"],
                "background_mode": args.background_mode,
                "artificial_general_save_delay_ms": args.save_delay_ms,
                "artificial_background_lock_hold_ms": (args.background_hold_ms
                                                       if args.background_mode in ("save", "once") else None),
                "background_lock_hold_scope": ("per_save" if args.background_mode in ("save", "once")
                                               else "entire_workload" if args.background_mode == "hold" else "none"),
                **workload,
                "dedicated_database": persisted["dedicated_database"],
                "general_saves_from_uv": persisted["general_saves"],
                "background_saves": persisted["background_saves"],
                "background_lock_holds": persisted["background_holds"],
                "uv_side_effect_writes": persisted["uv_side_effect_writes"],
                "uv_context_lookup": persisted["uv_context_lookup"],
                "legacy_context_load_data": persisted["legacy_context_load_data"],
                "worker_peak_rss_mib": persisted["worker_peak_rss_mib"],
                "uv_context_index_builds": persisted["uv_context_index_builds"],
                "general_json_contains_uv_states": persisted["json_contains_uv_states"],
                "persistence_failures": failures,
                "performance_failures": ([] if workload["health"]["passed"]
                                         else ["The /healthz liveness probe exceeded its deadline or failed"]),
            }
            report["passed"] = (not workload["errors"] and not failures
                                and workload["health"]["passed"]
                                and workload["completed_clients"] == args.clients)
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            if args.json_output:
                args.json_output.parent.mkdir(parents=True, exist_ok=True)
                args.json_output.write_text(encoded + "\n", encoding="utf-8")
            print(encoded)
            return 0 if report["passed"] else 1
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
