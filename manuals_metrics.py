"""First-party aggregate counters: no IP, user ID, cookie or session tracking."""
import datetime as dt
import sqlite3
from pathlib import Path
from flask import abort, request
from manuals_catalogue import CATALOGUE

CUSTOMER_ENDPOINTS = {'manuals_shop.catalogue_event'}


def connection(host):
    path = Path(host.PERSIST_DIR) / 'manuals-metrics.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=1)
    db.execute('CREATE TABLE IF NOT EXISTS daily (day TEXT, event TEXT, product TEXT, count INTEGER, PRIMARY KEY(day,event,product))')
    return db


def increment(host, event, product=''):
    try:
        with connection(host) as db:
            today = dt.date.today()
            db.execute('INSERT INTO daily VALUES (?,?,?,1) ON CONFLICT(day,event,product) DO UPDATE SET count=count+1', (today.isoformat(),event,product))
            db.execute('DELETE FROM daily WHERE day < ?', ((today - dt.timedelta(days=89)).isoformat(),))
    except (OSError,sqlite3.Error):
        host.app.logger.warning('commercial_metrics_unavailable')


def register_routes(host,bp,*,page,customer,check_csrf):
    from manuals_presentation import presentation_books
    specimens = {b['specimen']:b['code'] for b in presentation_books(CATALOGUE) if b.get('specimen')}
    @host.app.after_request
    def count_public_events(response):
        if request.method != 'GET' or response.status_code != 200 or host._is_super_admin_session():
            return response
        if any(bot in request.user_agent.string.lower() for bot in ('bot','crawler','spider','headless')):
            return response
        if request.endpoint in {'manuals_shop.public_manual_detail','manuals_shop.usb_detail','manuals_shop.public_course'}:
            increment(host,'product_view',request.path)
        elif request.endpoint == 'static' and (request.view_args or {}).get('filename') in specimens:
            increment(host,'specimen_download',specimens[request.view_args['filename']])
        return response

    @bp.post('/admin/manuels/evenement-panier')
    @customer
    def catalogue_event():
        check_csrf()
        if host._partner_login_is_rate_limited('cart-event:' + str(host._current_partner_id())):
            return '',204
        increment(host,'cart_started')
        return '',204

    @bp.get('/admin/commandes-manuels/statistiques')
    @host.admin_login_required
    @host.require_super_admin
    def commercial_metrics():
        if host._is_partner_data_scope_session():
            abort(403)
        since = (dt.date.today() - dt.timedelta(days=29)).isoformat()
        try:
            with connection(host) as db:
                rows = db.execute('SELECT event,product,SUM(count) FROM daily WHERE day>=? GROUP BY event,product ORDER BY SUM(count) DESC',(since,)).fetchall()
        except (OSError,sqlite3.Error):
            rows=[]
        data=host.load_data()
        orders=[o for o in data.get('manual_orders',[]) if o.get('order_type') != 'elearning_group' and str(o.get('created_at',''))[:10]>=since]
        summary={'drafts':sum(o.get('status')=='draft' for o in orders), 'confirmed':sum(o.get('status') not in {'draft','cancelled'} for o in orders), 'paid':sum(o.get('commerce',{}).get('payment_status')=='paid' for o in orders), 'revenue':sum(o.get('total_cents',0) for o in orders if o.get('commerce',{}).get('payment_status')=='paid')}
        return page('metrics.html',staff=True,rows=rows,summary=summary,since=since)
