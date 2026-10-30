import copy
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import unquote
import zipfile

from lxml import html
import pytest
from werkzeug.datastructures import MultiDict

import app as host
import desp_jury_projects as projects


@pytest.fixture
def portal(monkeypatch, tmp_path):
    data_file = tmp_path / "data.json"
    person = {"id": "T1", "first_name": "élodie", "last_name": "dupré", "public_token": "PUB-T1",
              "documents": [], "public_has_logged_in": True}
    training = {"id": "S1", "name": "DESP initial Paris", "training_type": "DIRIGEANT initial",
                "date_start": "2026-10-01", "date_end": "2026-11-09", "exam_date": "2026-11-10",
                "trainees": [person, {"id": "T2", "first_name": "Camille", "last_name": "TEST",
                                      "public_token": "PUB-T2", "documents": []}]}
    data_file.write_text(json.dumps({"sessions": [training]}))
    monkeypatch.setattr(host, "PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(host, "DATA_FILE", str(data_file))
    monkeypatch.setattr(host, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(host, "load_data", lambda **kw: json.loads(data_file.read_text()))
    monkeypatch.setattr(host, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(host, "fetch_cnapsv3_tracking_requests", lambda: ([], ""))
    monkeypatch.setattr(host, "_remember_admin_trainee_consultation", lambda *a: None)
    monkeypatch.setattr(host.app, "testing", True)
    client = host.app.test_client()
    with client.session_transaction() as session:
        session.update({"public_auth_PUB-T1": True, "trainee_document_check_token": "csrf-test"})
    return client, data_file


def person(portal):
    return json.loads(portal[1].read_text())["sessions"][0]["trainees"][0]


def upload(portal, files=None, **fields):
    data = {"document_check_token": "csrf-test", "revision": str(projects.state(person(portal)).get("revision", 0)), **fields}
    for slot, content in (files or {}).items():
        data[f"file_{slot}"] = (BytesIO(content), f"dossier{slot}.pdf")
    return portal[0].post("/espace/PUB-T1/projet-cadrage", data=data, content_type="multipart/form-data")


def error(portal):
    with portal[0].session_transaction() as session:
        return session.get("_flashes", [])[-1][1]


@pytest.mark.parametrize("kind,allowed", [("DIRIGEANT initial", True), ("DESP INITIAL", True),
    ("DIRIGEANT VAE", False), ("DESP VAE", False), ("MAC DESP", False), ("APS", False), ("A3P", False)])
def test_only_initial_desp(portal, kind, allowed):
    data = json.loads(portal[1].read_text())
    data["sessions"][0]["training_type"] = kind
    portal[1].write_text(json.dumps(data))
    response = upload(portal, {1: b"jury project"})
    assert response.status_code == (302 if allowed else 404)
    assert bool(projects.documents(person(portal))) is allowed


def test_one_file_and_unicode_download_name(portal):
    assert upload(portal, {1: b"jury contents"}).status_code == 302
    row = projects.documents(person(portal))[0]
    assert row["size"] == 13
    response = portal[0].get("/espace/PUB-T1/projet-cadrage/download")
    assert response.status_code == 200 and response.data == b"jury contents"
    assert "Projet de cadrage Élodie DUPRÉ.pdf" in unquote(response.headers["Content-Disposition"])
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "jury contents" not in portal[1].read_text()


def test_two_files_exact_limit_and_zip_names(portal):
    assert upload(portal, {1: b"a" * 7_000_000, 2: b"b" * 8_000_000}).status_code == 302
    response = portal[0].get("/espace/PUB-T1/projet-cadrage/download")
    assert "Projet de cadrage Élodie DUPRÉ.zip" in unquote(response.headers["Content-Disposition"])
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == ["Projet de cadrage Élodie DUPRÉ - 1.pdf", "Projet de cadrage Élodie DUPRÉ - 2.pdf"]
        assert len(archive.read(archive.namelist()[1])) == 8_000_000


@pytest.mark.parametrize("sizes", [(15_000_001,), (7_000_001, 8_000_000), (26_000_000,)])
def test_oversize_batch_is_rejected_without_saving(portal, sizes):
    assert upload(portal, {i: b"x" * size for i, size in enumerate(sizes, 1)}).status_code == 302
    assert error(portal) == projects.SIZE_ERROR
    assert not projects.documents(person(portal))
    assert not list(portal[1].parent.rglob("*.pdf"))


def test_retained_file_counts_and_replacement_frees_capacity(portal):
    upload(portal, {1: b"a" * 10_000_000})
    original = copy.deepcopy(person(portal)[projects.KEY])
    upload(portal, {2: b"b" * 5_000_001})
    assert person(portal)[projects.KEY] == original
    assert error(portal) == projects.SIZE_ERROR
    upload(portal, {1: b"c" * 2_000_000, 2: b"d" * 13_000_000})
    assert sum(d["size"] for d in projects.documents(person(portal))) == 15_000_000
    assert not Path(host._detokenize_path(original["documents"][0]["file"])).exists()


def test_second_file_can_be_added_later_and_removed(portal):
    upload(portal, {1: b"one"})
    upload(portal, {2: b"two"})
    assert len(projects.documents(person(portal))) == 2
    upload(portal, remove_1="1")
    assert [d["slot"] for d in projects.documents(person(portal))] == [2]
    upload(portal, remove_2="1")
    assert projects.documents(person(portal)) == []
    assert portal[0].get("/espace/PUB-T1/projet-cadrage/download").status_code == 404


def test_extra_files_rejected_atomically(portal):
    data = MultiDict([("document_check_token", "csrf-test"), ("revision", "0"),
                      ("file_1", (BytesIO(b"1"), "a.pdf")), ("file_1", (BytesIO(b"2"), "b.pdf")),
                      ("file_2", (BytesIO(b"3"), "c.pdf"))])
    assert portal[0].post("/espace/PUB-T1/projet-cadrage", data=data).status_code == 302
    assert "2 documents au maximum" in error(portal)
    assert not projects.documents(person(portal))


@pytest.mark.parametrize("content,name", [(b"", "empty.pdf"), (b"binary", "program.exe"), (b"x", "no-extension")])
def test_invalid_files_preserve_previous_deposit(portal, content, name):
    upload(portal, {1: b"existing"})
    before = person(portal)[projects.KEY]
    response = upload(portal, file_1=(BytesIO(content), name))
    assert response.status_code == 302
    assert person(portal)[projects.KEY] == before


def test_authentication_csrf_and_other_trainee_isolation(portal):
    upload(portal, {1: b"private jury document"})
    assert upload(portal, {2: b"x"}, document_check_token="wrong").status_code == 403
    assert portal[0].get("/espace/PUB-T2/projet-cadrage/download").status_code == 302
    with portal[0].session_transaction() as session:
        session["public_auth_PUB-T2"] = True
    assert portal[0].get("/espace/PUB-T2/projet-cadrage/download").status_code == 404
    assert portal[0].get("/admin/sessions/S1/stagiaires/T1/projet-cadrage/download").status_code == 302
    with portal[0].session_transaction() as session:
        session.clear()
    assert upload(portal, {2: b"x"}).status_code == 302
    assert len(projects.documents(person(portal))) == 1
    assert portal[0].get("/espace/PUB-T1/projet-cadrage/download").status_code == 302


def test_stale_submission_and_unrelated_save_keep_latest_documents(portal):
    stale = json.loads(portal[1].read_text())
    upload(portal, {1: b"new"})
    upload(portal, {2: b"stale"}, revision="0")
    assert "autre onglet" in error(portal)
    with host.app.test_request_context():
        host.save_data(stale)
    assert len(projects.documents(person(portal))) == 1
    assert projects.documents(person(portal))[0]["size"] == 3
    before_delete = json.loads(portal[1].read_text())
    upload(portal, remove_1="1")
    with host.app.test_request_context():
        host.save_data(before_delete)
    assert projects.documents(person(portal)) == []


def test_storage_failure_rolls_back_all_files(portal, monkeypatch):
    real_write = Path.write_bytes
    count = 0
    def fail_second(path, data):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("disk full")
        return real_write(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail_second)
    with pytest.raises(OSError, match="disk full"):
        upload(portal, {1: b"one", 2: b"two"})
    assert not projects.documents(person(portal))
    assert not list(portal[1].parent.rglob("*.pdf"))


def test_read_only_admin_cannot_deposit(portal):
    with portal[0].session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="viewer")
    assert upload(portal, {1: b"jury"}).status_code == 403
    assert not projects.documents(person(portal))


def test_missing_file_can_be_replaced(portal):
    upload(portal, {1: b"old"})
    Path(host._detokenize_path(projects.documents(person(portal))[0]["file"])).unlink()
    upload(portal, {1: b"new file"})
    response = portal[0].get("/espace/PUB-T1/projet-cadrage/download")
    assert response.status_code == 200 and response.data == b"new file"


def test_real_public_and_admin_pages_and_download(portal):
    public = portal[0].get("/espace/PUB-T1")
    assert public.status_code == 200
    page = html.fromstring(public.data)
    section = page.get_element_by_id("projet-cadrage")
    assert "15 Mo maximum au total" in section.text_content()
    assert len(section.xpath('.//input[@type="file"]')) == 2
    upload(portal, {1: b"jury"})
    with portal[0].session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    admin = portal[0].get("/admin/sessions/S1/stagiaires/T1")
    assert admin.status_code == 200
    section = html.fromstring(admin.data).get_element_by_id("projet-cadrage")
    assert "Projet de cadrage Élodie DUPRÉ.pdf" in section.text_content()
    assert not section.xpath('.//input[@type="file"]')
    response = portal[0].get(section.xpath('.//a')[0].get('href'))
    assert response.status_code == 200 and response.data == b"jury"
