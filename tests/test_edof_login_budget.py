"""Shared EFP budget: Paris hours, durable count, cooldown and safe automatic resume."""
import datetime as dt

import pytest

from edof_day_session import PARIS, LOGIN_RETRY_SECONDS, allow_login, login_policy
from edof_gmail import Vault, connector_key
from edof_server_test import ServerTestStore


@pytest.mark.parametrize('instant,allowed', [
    ('2026-11-04T05:59:59+00:00',False), ('2026-11-04T06:00:00+00:00',True),
    ('2026-11-04T17:59:59+00:00',True), ('2026-11-04T18:00:00+00:00',False),
    ('2027-07-05T04:59:59+00:00',False), ('2027-07-05T05:00:00+00:00',True),
    ('2027-07-05T17:00:00+00:00',False),
])
def test_automatic_codes_are_limited_to_paris_watch_hours(tmp_path,instant,allowed):
    vault = Vault(tmp_path,connector_key('local-only'*6))
    assert allow_login(vault,now=dt.datetime.fromisoformat(instant)) is allowed
    assert bool(vault.get('efp-login-day')) is allowed


def test_four_shared_attempts_persist_across_restarts_and_cooldown(tmp_path):
    key = connector_key('local-only'*6)
    day = dt.datetime(2026,11,4,8,tzinfo=PARIS)
    for index in range(4):
        vault = Vault(tmp_path,key)
        instant = day+dt.timedelta(seconds=index*LOGIN_RETRY_SECONDS)
        assert allow_login(vault,owner='A' if index%2 else 'B',now=instant)
        assert not allow_login(vault,owner='A',now=instant+dt.timedelta(seconds=1))
        assert vault.get('efp-login-day')['count'] == index+1
    state = login_policy(Vault(tmp_path,key),now=day+dt.timedelta(hours=5))
    assert not state['allowed'] and state['code']=='day_login_used' and state['remaining']==0
    assert allow_login(Vault(tmp_path,key),now=day+dt.timedelta(days=1))
    assert Vault(tmp_path,key).get('efp-login-day')['count']==1


def test_portal_pause_wins_even_with_manual_permit_and_does_not_consume_budget(tmp_path):
    vault = Vault(tmp_path,connector_key('local-only'*6))
    now = dt.datetime(2026,11,4,10,tzinfo=PARIS)
    vault.put('day-login-override:A',now.date().isoformat())
    vault.put('edof-throttled',True)
    assert not allow_login(vault,owner='A',now=now)
    assert login_policy(vault,owner='A',now=now)['code']=='portal_throttled'
    assert vault.get('day-login-override:A') and not vault.get('efp-login-day')


def test_scheduler_resumes_old_pause_and_waits_until_next_allowed_attempt(tmp_path,monkeypatch):
    now = dt.datetime(2026,11,4,14,tzinfo=PARIS)
    clock = [now.timestamp()]
    monkeypatch.setattr('time.time',lambda:clock[0])
    store = ServerTestStore(tmp_path)
    store.connector_key = connector_key('local-only'*6)
    vault = Vault(tmp_path,store.connector_key)
    store.use_directory('A',enable=True)
    vault.put('efp-login-day',{'date':now.date().isoformat(),'count':2,'at':clock[0]-3600})
    vault.put('efp-paused-day',now.date().isoformat())
    with store.connect() as db:
        db.execute("INSERT INTO jobs VALUES ('old','A',?,?,'directory',?)",
                   (clock[0]-120,clock[0]-60,'{"code":"day_login_used","day_session":true}'))
    assert store.day_owners(now)==['A']
    assert allow_login(vault,owner='A',now=now)
    assert vault.get('efp-login-day')['count']==3 and not vault.get('efp-paused-day')
    job=store.reserve('A','directory',day_session=True)
    store.finish(job,{'code':'day_login_wait'})
    assert not store.day_owners(now+dt.timedelta(seconds=899))
    assert store.day_owners(now+dt.timedelta(seconds=900))==['A']
    vault.put('edof-throttled',True)
    assert not store.day_owners(now+dt.timedelta(seconds=900))


def test_live_budget_does_not_present_legacy_pause_as_exhausted(tmp_path,monkeypatch):
    now=dt.datetime(2026,11,4,14,tzinfo=PARIS)
    class Clock(dt.datetime):
        @classmethod
        def now(cls,tz=None):
            return now.astimezone(tz)
    monkeypatch.setattr('edof_server_test.dt.datetime',Clock)
    monkeypatch.setattr('edof_day_session.datetime',Clock)
    monkeypatch.setattr('time.time',lambda:now.timestamp())
    store=ServerTestStore(tmp_path)
    store.connector_key=connector_key('local-only'*6)
    vault=Vault(tmp_path,store.connector_key)
    store.use_directory('A',enable=True)
    job=store.reserve('A','directory',day_session=True)
    store.finish(job,{'code':'day_login_used'})
    vault.put('efp-login-day',{'date':now.date().isoformat(),'count':2,'at':now.timestamp()-3600})
    view=store.live_connection('A',False)
    assert view['login_budget']['used']==2 and view['login_budget']['remaining']==2
    assert view['login_budget']['limit']==4
    assert not view['paused'] and 'Reconnexion automatique programmée' in view['error']
    assert store.connection_status('A',False)['state']=='reconnect'
    vault.put('efp-login-day',{'date':now.date().isoformat(),'count':4,'at':now.timestamp()-3600})
    assert store.live_connection('A',False)['paused']
    assert store.connection_status('A',False)['state']=='day_paused'


def test_service_restart_restores_one_verified_session_outside_normal_quota(tmp_path, monkeypatch):
    import edof_session_clock as clock

    key = connector_key("restart-fixture" * 4)
    store = ServerTestStore(tmp_path)
    store.connector_key = key
    start = dt.datetime(2026, 11, 6, 7, tzinfo=PARIS)
    now = start
    monkeypatch.setattr("time.time", lambda: now.timestamp())
    store.use_directory("A", enable=True)
    vault = Vault(tmp_path, key)
    for _ in range(4):
        assert allow_login(vault, owner="A", now=now)
        now += dt.timedelta(minutes=15)
    clock.record(vault, "A", "verified", now=now.timestamp())
    assert not allow_login(vault, owner="A", now=now)
    store.recover_directory_reads()
    assert not allow_login(vault, owner="B", now=now)
    assert not allow_login(vault, owner="A", now=now, shared_session=False)
    vault.put("edof-throttled", True)
    assert not allow_login(vault, owner="A", now=now)
    vault.delete("edof-throttled")
    assert allow_login(vault, owner="A", now=now)
    assert vault.get("efp-login-day")["count"] == 4
    assert vault.get("efp-login-day")["restarts"] == 1
    now += dt.timedelta(minutes=16)
    store.recover_directory_reads()  # No new verified session to recover.
    assert not allow_login(vault, owner="A", now=now)
    clock.record(vault, "A", "verified", now=now.timestamp())
    store.recover_directory_reads()
    assert allow_login(vault, owner="A", now=now)
    assert login_policy(vault, owner="A", now=now)["restarts"] == 2
    assert login_policy(vault, owner="A", now=now + dt.timedelta(days=1))["used"] == 0


def test_restored_cookies_clear_credit_and_expiry_counts_as_normal(tmp_path):
    import edof_session_clock as clock

    vault = Vault(tmp_path, connector_key("restart-fixture" * 4))
    now = dt.datetime(2026, 11, 6, 10, tzinfo=PARIS)
    clock.record(vault, "A", "verified", now=now.timestamp())
    clock.record(vault, "A", "server_restart", now=now.timestamp() + 1)
    assert login_policy(vault, owner="A", now=now)["restart_witness"]
    clock.record(vault, "A", "verified", now=now.timestamp() + 2)
    clock.record(vault, "A", "reauth", now=now.timestamp() + 100)
    assert allow_login(vault, owner="A", now=now + dt.timedelta(hours=1))
    policy = login_policy(vault, owner="A", now=now + dt.timedelta(hours=2))
    assert policy["used"] == 1 and policy["restarts"] == 0
