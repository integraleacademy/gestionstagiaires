import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import partner_presence as presence
import app as host
from test_manuals_shop import shop, signup, login, all_data
from test_partner_workspace import as_admin


def test_historical_account_actions_and_visits_ignore_other_tenants_and_admin(tmp_path):
    h=SimpleNamespace(PERSIST_DIR=tmp_path,_parse_iso_datetime=host._parse_iso_datetime,app=host.app)
    data={'users':[{'id':'u','partner_id':'p','email':'partner@example.test','last_login_at':'2026-10-27T12:25:00Z'}],
          'manual_orders':[{'partner_id':'p','created_by':'u','created_at':'2026-11-06T10:00:00Z','updated_at':'2026-11-07T10:00:00Z',
                            'terms_acceptance':{'user_id':'u','accepted_at':'2026-11-05T12:45:00Z'}},
                           {'partner_id':'p','created_by':'admin','created_at':'2026-11-08T12:00:00Z'}],
          'activity_logs':[{'partner_id':'p','user':'admin@example.test','action':'super_admin_assist_started','created_at':'2026-11-08T12:00:00Z'}]}
    assert presence.latest(h,data)['u']==dt.datetime(2026,11,5,12,45)
    assert not (tmp_path/'partner-presence.sqlite3').exists()  # A platform read never creates a visit.
    presence.record(h,'other','u','2026-11-08T12:00:00Z')
    assert presence.latest(h,data)['u']==dt.datetime(2026,11,5,12,45)
    presence.record(h,'p','u','2026-11-06T09:30:00Z')
    presence.record(h,'p','u','2026-10-25T09:30:00Z')
    assert presence.latest(h,data)['u']==dt.datetime(2026,11,6,9,30)


def test_persistent_partner_session_updates_access_without_new_password(shop):
    c=shop['client'];signup(c);login(c)
    data=all_data(shop);u=data['users'][0];pid=u['partner_id']
    path=Path(host.PERSIST_DIR)/'partner-presence.sqlite3'
    assert not path.exists()
    assert c.get('/admin/organisme').status_code==200
    stamps=presence.latest(host,all_data(shop)); assert u['id'] in stamps
    import sqlite3
    with sqlite3.connect(path) as db: first=db.execute('SELECT seen FROM presence').fetchone()[0]
    assert c.get('/admin/organisme').status_code==200
    with sqlite3.connect(path) as db: assert db.execute('SELECT seen FROM presence').fetchone()[0]==first
    as_admin(c)
    assert c.get('/admin/partners?tab=organisations').status_code==200
    assert c.get('/admin/partners/'+pid+'?tab=account').status_code==200
    with c.session_transaction() as sess: sess['assist_partner_id']=pid
    c.get('/admin/organisme')
    with sqlite3.connect(path) as db: assert db.execute('SELECT seen FROM presence').fetchone()[0]==first
