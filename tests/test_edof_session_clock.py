import edof_session_clock as clock
from edof_gmail import Vault, connector_key
from edof_server_test import ServerTestStore


def test_running_frozen_expired_and_reauthenticated(tmp_path):
    vault = Vault(tmp_path,connector_key("local-observation-key"*3))
    clock.record(vault,"A","verified",fresh=True,now=1000)
    clock.record(vault,"A","verified",now=1300)
    measured = clock.read_clock(vault,"A")
    running = clock.clock_view(measured,1310,open_now=True,verified=True)
    assert running["display"] == "00:05:10" and running["tick_for"] > 0
    for now,opened,verified in ((2000,True,True),(1310,False,True),(1320,True,False)):
        frozen = clock.clock_view(measured, now, open_now=opened, verified=verified)
        assert frozen["display"] == "00:05:00" and not frozen["tick_for"]
    clock.record(vault,"A","reauth",now=1420)
    clock.record(vault,"A","reauth",now=1440)
    clock.record(vault,"A","interrupted",now=1450)
    measured = clock.read_clock(vault,"A")
    view = clock.clock_view(measured,1450,open_now=True,verified=False)
    assert "entre 00:05:00 et 00:07:00" in view["previous"] and view["tick_for"] == 0
    clock.record(vault,"A","verified",fresh=True,now=1460)
    assert clock.read_clock(vault,"A")["current"]["start"] == 1460
    assert clock.read_clock(vault,"A")["previous"] == measured["previous"]
    assert clock.read_clock(vault,"B") == {}


def test_restart_or_local_interruption_is_not_expiry(tmp_path):
    store = ServerTestStore(tmp_path)
    store.connector_key = connector_key("local-fixtures"*4)
    store.use_directory("A",enable=True)
    vault = Vault(tmp_path,store.connector_key)
    clock.record(vault,"A","verified",now=1000)
    clock.record(vault,"A","verified",now=1060)
    store.recover_directory_reads()
    clock.record(vault,"A","reauth",now=1300)
    assert clock.read_clock(vault,"A") == {"current":{"start":1000,"last":1060,"authenticated":False,"interrupted":True}}
    clock.record(vault,"A","verified",now=1400)
    clock.record(vault,"A","reauth",now=1460)
    view = clock.clock_view(clock.read_clock(Vault(tmp_path,store.connector_key),"A"),1500,open_now=True,verified=False)
    assert "depuis le premier accès observé" in view["previous"] and "entre 00:00:00 et 00:01:00" in view["previous"]


def test_legacy_reads_only_show_the_verified_span(tmp_path):
    import json
    import time
    store = ServerTestStore(tmp_path)
    now = time.time()
    with store.connect() as db:
        for i, (owner, result) in enumerate([
                ("A",{"fresh_session":True,"gmail_code_used":True,"session_saved":True}),
                ("A",{"fresh_session":False,"session_saved":True}),
                ("A",{"code":"day_login_used"}), ("B",{"fresh_session":False,"session_saved":True}),
                ("A",{"fresh_session":False,"session_saved":True})]):
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",(str(i),owner,now+i*120-1,now+i*120,"directory",json.dumps(result)))
    view = store.live_connection("A",True)["clock"]
    assert view["display"] == "00:02:00" and view["tick_for"] == 0
    assert "anciens contrôles" in view["detail"] and "Aucune expiration" in view["previous"]
