"""Ordering choices and the shared purchase history keep tenant boundaries."""
import app as host
from test_manuals_shop import shop, signup, login, all_data


def test_support_choices_and_history_require_a_customer_session(shop):
    client = shop['client']
    for path in ('/admin/organisme/commander', '/admin/organisme/commandes'):
        response = client.get(path)
        assert response.status_code == 302
        assert '/admin/login' in response.location
    signup(client)
    login(client)
    choices = client.get('/admin/organisme/commander')
    assert choices.status_code == 200
    for destination in ('/manuels', '/supports-formateurs', '/admin/organisme/e-learning?view=catalogue'):
        assert f'href="{destination}"' in choices.text
    for path in ('/admin/organisme', '/admin/manuels', '/admin/organisme/commandes'):
        page = client.get(path)
        assert page.status_code == 200
        assert 'href="/admin/organisme/commander"' in page.text
        assert 'href="/admin/organisme/commandes"' in page.text
        assert '>Mes commandes</a>' in page.text


def test_purchase_history_includes_invoices_and_excludes_drafts_groups_and_other_centres(shop):
    client = shop['client']
    signup(client)
    login(client)
    pid = all_data(shop)['users'][0]['partner_id']
    purchases = [
        dict(id='manual-purchase', partner_id=pid, reference='MAN-VISIBLE', status='received',
             submitted_at='2026-10-14T08:00:00', total_cents=90000,
             commerce={'invoice_url': 'https://invoice.example.test/manual-visible', 'invoice_status': 'paid'}),
        dict(id='learning-purchase', partner_id=pid, reference='EL-VISIBLE', order_type='elearning',
             status='received', submitted_at='2026-10-14T09:00:00', course_code='aps',
             group_name='Mon groupe', learners=[], free_snapshot=False, total_cents=5900,
             commerce={'invoice_id': 'invoice-test', 'invoice_status': 'paid'}),
        dict(id='draft', partner_id=pid, reference='DRAFT-HIDDEN', status='draft'),
        dict(id='group', partner_id=pid, reference='GROUP-HIDDEN', order_type='elearning_group', status='received'),
    ]
    host._atomic_update_data(lambda data: data.setdefault('manual_orders', []).extend(purchases), partner_id=pid)
    history = client.get('/admin/organisme/commandes')
    assert history.status_code == 200
    assert 'MAN-VISIBLE' in history.text and 'EL-VISIBLE' in history.text
    assert 'https://invoice.example.test/manual-visible' in history.text
    assert '/admin/organisme/e-learning/commandes/learning-purchase/facture' in history.text
    assert 'DRAFT-HIDDEN' not in history.text and 'GROUP-HIDDEN' not in history.text
    other = host.app.test_client()
    signup(other, email='other@example.test')
    login(other, email='other@example.test')
    other_history = other.get('/admin/organisme/commandes')
    assert other_history.status_code == 200
    assert 'MAN-VISIBLE' not in other_history.text and 'EL-VISIBLE' not in other_history.text
    assert 'manual-visible' not in other_history.text
    assert other.get('/admin/organisme/e-learning/commandes/learning-purchase/facture').status_code == 404


def test_public_pages_share_brand_footer_and_current_brochure(shop):
    client = shop['client']
    for path in ('/', '/manuels', '/supports-formateurs', '/e-learning'):
        page = client.get(path)
        assert page.status_code == 200
        assert 'class="connect-brand__mark"' in page.text
        assert 'Intégrale <span>Connect</span>' in page.text
        assert '<footer class="organisme-identity"' in page.text
        assert '54 chemin du Carréou' in page.text
    page = client.get('/')
    assert 'brochure-manuels-2026.pdf?v=20261014' in page.text
    assert 'Commander ce support' in client.get('/supports-formateurs/aps').text
