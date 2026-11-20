"""Exercise two real HTTP applications with 24 simultaneous logins and a dedicated test database.

Set CAMPUS_TEST_DATABASE_URL to a disposable local PostgreSQL administrative connection.
The script creates and drops only its uniquely named database. All trainee data is synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_uv_questionnaires import synthetic_data, TRAINING, block_external_network

PEOPLE = 24
PARTNER = "11111111-1111-4111-8111-111111111111"


@contextmanager
def database():
    source = os.environ["CAMPUS_TEST_DATABASE_URL"]
    config = conninfo_to_dict(source)
    if config.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Only a loopback PostgreSQL test server is supported")
    name = "check_campus_" + secrets.token_hex(8)
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(name)))
        try:
            yield make_conninfo(source, dbname=name)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def seed(disk):
    from elearning_native import CourseCatalog
    from elearning_native.store import NativeElearningStore
    from uv_questionnaire_store import UVQuestionnaireStore
    from tests.test_native_elearning import _write_synthetic_course
    import uv_questionnaires as uv
    # Populate the original file formats, with Postgres disabled.
    root = disk / "native_elearning"
    _write_synthetic_course(disk / "training.zip")
    course = CourseCatalog(root).import_zip(disk / "training.zip", archive_source=False)
    data = synthetic_data(PEOPLE)
    training = data["sessions"][0]
    training.update(partner_id=PARTNER, aps_elearning_enabled=True, aps_native_course_id=course["id"],
                    aps_native_course_version=course["version"])
    for person in training["trainees"]:
        person.update(birth_date="1990-03-12", partner_id=PARTNER)
    (disk / "data.json").write_text(json.dumps(data))
    store = UVQuestionnaireStore(disk / "uv-questionnaires.sqlite3")
    first = training["trainees"][0]["id"]
    row = uv.unit("aps", 2)
    question = row["questions"][0]
    old = {"uv_questionnaire_attempts": {"aps": {"2": dict(version=uv.VERSION, answers={question["id"]: question["answer"]},
            index=1, deadline=time.time()+3600, started_at="2026-10-28T09:00:00Z")}},
           "uv_questionnaire_resets": {"aps": {"3": "historic-reset"}}}
    store.mutate((PARTNER, TRAINING, first), {}, lambda learner: learner.update(old))
    native = NativeElearningStore(root / "tracking.sqlite3")
    key = dict(session_id=TRAINING, trainee_id=first, course_id=course["id"], course_version=course["version"])
    native.record_question_attempt(key, "question-1", ["answer-a"], True, request_id="historical-case")
    return course["id"], row["questions"][1]["id"]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, name, temp, env):
        self.name = name
        self.port = port()
        self.base = f"https://127.0.0.1:{self.port}"
        self.temp, self.env = temp, env
        self.process = None
        self.log = open(temp / (name + ".log"), "w+")
        self.cert = str(temp / "cert.pem")

    def start(self):
        env = dict(self.env, PORT=str(self.port))
        # The normal WSGI application and Gunicorn threads, with outbound services blocked.
        code = ("from scripts.benchmark_uv_questionnaires import block_external_network; block_external_network(); "
                "from gunicorn.app.wsgiapp import run; run()")
        args = [sys.executable, "-c", code, "--bind", f"127.0.0.1:{self.port}",
                "--config", "campus/gunicorn_conf.py" if self.name == "campus" else "/dev/null",
                "--certfile", self.cert, "--keyfile", str(self.temp / "key.pem")]
        if self.name == "gestion":
            args += ["--workers", "1", "--threads", "4"]
        args += ["campus.web:create_app()" if self.name == "campus" else "crm_app:app"]
        self.process = subprocess.Popen(args, env=env, cwd=ROOT, stdout=self.log, stderr=self.log)

    def wait(self):
        path = "/healthz" if self.name == "campus" else "/admin/login"
        for _ in range(180):
            if self.process.poll() is not None:
                break
            try:
                if requests.get(self.base+path, timeout=1, verify=self.cert, allow_redirects=False).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(.25)
        self.log.flush()
        raise RuntimeError((self.temp / (self.name+".log")).read_text()[-7000:])

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=35)


def verify(response, status=200):
    if response.status_code != status:
        raise AssertionError(f"{response.request.method} {response.url}: {response.status_code} {response.text[:240]}")
    return response


def field(html, pattern):
    found = re.search(pattern, html)
    if not found:
        raise AssertionError("Missing page element: "+pattern)
    return found.group(1)


def logged_in(campus, index, barrier=None):
    token = f"bench-token-{index:03}"
    client = requests.Session()
    client.trust_env = False
    client.verify = campus.cert
    personal = f"/espace/{token}"
    url = campus.base + (personal+"/login" if index % 2 else "/espacestagiaire")
    form = verify(client.get(url, timeout=25)).text
    csrf = field(form, r'name="csrf" value="([^"]+)"')
    if barrier:
        barrier.wait(30)
    verify(client.post(url, data=dict(csrf=csrf, last_name=f"Learner {index}", birth="1990-03-12"),
                       timeout=25, allow_redirects=False), 303)
    home = verify(client.get(campus.base+personal, timeout=25)).text
    assert "Questionnaires de fin d’UV" in home
    return client, personal


def native_smoke(campus, course, second_question):
    learner, personal = logged_in(campus, 0)
    url = campus.base + personal
    original = verify(learner.get(url+"/questionnaires-uv/2")).text
    resumed = verify(learner.post(url+"/questionnaires-uv/2", json=dict(action="sync", generation="",
                       csrf=field(original, r'data-csrf="([^"]+)"')))).json()
    assert resumed["question"]["id"] == second_question
    reset_page = verify(learner.get(url+"/questionnaires-uv/3")).text
    assert 'data-generation="historic-reset"' in reset_page
    assert "Cours de test" in verify(learner.get(url+"/elearning")).text
    player = verify(learner.get(url+"/elearning/"+course)).text
    config = json.loads(field(player, r'<script id="nativeElearningConfig" type="application/json">([^<]+)</script>'))
    asset = field(player, r'src="([^"]*/elearning/assets/[^"]+)"')
    assert verify(learner.get(campus.base+asset.replace("&amp;", "&"))).content
    params = dict(access_token=config["accessToken"], activity_id=config["activityId"], tab_id="campus-isolation-test")
    headers = {"X-Elearning-CSRF": config["csrfToken"]}
    prefix = campus.base + "/api/elearning/v1/tracking/"
    started = verify(learner.post(prefix+"start", json=params, headers=headers)).json()
    params.update(tracking_session_id=started["tracking_session_id"], visible=True,
                  focused=True, recent_activity=True, interaction_age_seconds=0)
    assert verify(learner.post(prefix+"heartbeat", json=params, headers=headers)).json()["ok"]
    verify(learner.get(campus.base+"/admin/login"), 404)
    learner.close()


def exercise(temp, dsn):
    import uv_questionnaires as uv
    disk = temp / "gestion"
    disk.mkdir()
    course, second = seed(disk)
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", str(temp/"key.pem"), "-out", str(temp/"cert.pem")], check=True, capture_output=True)
    env = {k: v for k,v in os.environ.items() if k in {"PATH","PYTHONPATH","HOME","LANG","LC_ALL","LD_LIBRARY_PATH"}}
    env.update(CAMPUS_STORAGE="postgres", CAMPUS_DATABASE_URL=dsn, SECRET_KEY=secrets.token_hex(32))
    campus = Server("campus", temp, dict(env, CAMPUS_SESSION_SECRET=secrets.token_hex(32),
                                        CAMPUS_CACHE_DIR=str(temp/"cache")))
    manager = Server("gestion", temp, dict(env, PERSIST_DIR=str(disk), CAMPUS_MANAGEMENT_MODE="active",
                 CAMPUS_PUBLIC_URL=campus.base, ADMIN_USER="local-teacher", ADMIN_PASSWORD=secrets.token_hex(16)))
    campus.env["CAMPUS_MANAGEMENT_URL"] = manager.base
    samples = []
    errors = []
    try:
        campus.start()
        campus.wait()
        verify(requests.get(campus.base+"/",verify=campus.cert),503)
        manager.start()
        manager.wait()
        manager.stop()
        native_smoke(campus, course, second)
        questions = next(r["questions"] for r in uv.bank()["courses"]["aps"]["units"] if r["number"] == 4)
        barrier = threading.Barrier(PEOPLE)
        def learner(i):
            try:
                client, personal = logged_in(campus,i,barrier)
                url = campus.base+personal+"/questionnaires-uv/4"
                html = verify(client.get(url,timeout=25)).text
                csrf = field(html,r'data-csrf="([^"]+)"')
                def submit(action, **kwargs):
                    began = time.monotonic()
                    res = verify(client.post(url,json=dict(action=action, csrf=csrf, generation="", **kwargs),timeout=25))
                    samples.append(time.monotonic()-began)
                    return res.json()
                barrier.wait(30)
                state = submit("start", in_class="yes")
                for j,q in enumerate(questions):
                    barrier.wait(30)
                    if j == 10 and i == 0:
                        assert manager.process.poll() is not None
                        manager.start()
                    assert state["question"]["id"] == q["id"]
                    state = submit("answer",question_id=q["id"],answer=q["answer"])
                assert state["completed"] and state["score"] == 20
                client.close()
            except Exception as exc:
                errors.append(exc)
                barrier.abort()
                raise
        with ThreadPoolExecutor(PEOPLE) as group:
            list(group.map(learner,range(PEOPLE)))
        manager.wait()
        staff = requests.Session()
        staff.trust_env = False
        staff.verify = manager.cert
        response = staff.post(manager.base+"/admin/login", data=dict(username=manager.env["ADMIN_USER"],
                    password=manager.env["ADMIN_PASSWORD"]),allow_redirects=False)
        verify(response,302)
        for i in range(PEOPLE):
            url = manager.base+f"/admin/sessions/{TRAINING}/stagiaires/BENCH-{i:03}/questionnaires-uv/4"
            correction = verify(staff.get(url)).text
            assert '20<span>/20</span>' in correction and correction.count("Votre réponse") == 20
        with psycopg.connect(dsn) as conn:
            histories = conn.execute("SELECT state_json FROM campus_uv.uv_questionnaire_state").fetchall()
            expected = {q["id"]:q["answer"] for q in questions}
            assert len(histories) == PEOPLE
            for (state,) in histories:
                result = json.loads(state)["uv_questionnaires"]["aps"]["4"]
                assert result["score"] == 20 and result["answers"] == expected
            assert conn.execute("SELECT count(*) FROM campus_tracking.learner_assessment_attempts").fetchone()[0] == 1
        staff.close()
        print(json.dumps(dict(learners=PEOPLE, authenticated=PEOPLE, uv_posts=len(samples),
            distinct_saved_answers=PEOPLE*len(questions), verified_admin_scores=PEOPLE,
            post_p95_seconds=round(sorted(samples)[int(.95*len(samples))],3),
            native_player_asset_heartbeat=True, historic_resume_reset=True,
            manager_offline_at_login=True, manager_restart_at_question=11),indent=2))
    except BaseException:
        for server in (campus,manager):
            server.log.flush()
            log=(temp/(server.name+".log")).read_text()
            if "Traceback" in log:
                print(log[log.rfind("Traceback") :][:4500],file=sys.stderr)
        if errors:
            raise errors[0]
        raise
    finally:
        campus.stop()
        manager.stop()
        campus.log.close()
        manager.log.close()


if __name__ == "__main__":
    block_external_network()
    os.environ.pop("CAMPUS_STORAGE", None)
    with database() as dsn, tempfile.TemporaryDirectory(prefix="campus-isolation-") as temp:
        exercise(Path(temp), dsn)
