import json
from urllib.parse import parse_qs, urlparse
import pytest
import app as host
from manuals_shop import CATALOGUE, quote_items


def test_brochure_2026_exact_totals():
    prices = {
        'aps': (2000,1800), 'mac_aps': (1200,1000), 'a3p': (2200,2000),
        'dssp': (2200,2000), 'ssiap1': (1700,1500), 'ssiap2': (1700,1500),
        'ssiap3': (2200,2000), 'ssiap1_recyclage': (1200,1000),
        'ssiap2_recyclage': (1200,1000), 'ssiap3_recyclage': (1200,1000),
        'h0b0': (900,800), 'bs_be': (1200,1000), 'vtc': (2200,2000),
        'sst': (1200,1000), 'mac_sst': (900,800),
    }
    assert {book['code'] for book in CATALOGUE} == set(prices)
    premium_usb = {'aps', 'a3p', 'dssp', 'ssiap1', 'ssiap2', 'ssiap3', 'vtc'}
    for code, (regular, bulk) in prices.items():
        for qty, price in [(50,regular),(99,regular),(100,bulk),(101,bulk)]:
            line = quote_items({'manual_'+code: str(qty)})[0]
            assert line['unit_cents'] == price
            assert line['total_cents'] == qty * price
        if code == 'mac_sst':
            with pytest.raises(ValueError):
                quote_items({'usb_'+code:'1'})
        else:
            assert quote_items({'usb_'+code:'1'})[0]['total_cents'] == (19900 if code in premium_usb else 9900)
    mixed = quote_items({'manual_aps':'50', 'manual_sst':'50'})
    assert sum(i['total_cents'] for i in mixed) == 160000  # 100 mixed copies do not trigger a per-title reduction.


def test_payment_transport_requires_oauth_and_passes_idempotency(monkeypatch):
    monkeypatch.setattr(host, '_qonto_oauth_connected', lambda *a: True)
    monkeypatch.setattr(host, '_qonto_oauth_has_scope', lambda scope,*a: True)
    monkeypatch.setattr(host, '_qonto_oauth_bearer_token', lambda: 'merchant-test-token')
    monkeypatch.setattr(host, '_sanitize_qonto_error', lambda s: s)
    calls=[]
    class Response:
        ok=True
        status_code=201
        headers={}
        text='{"payment_link":{"id":"link"}}'
        def json(self): return json.loads(self.text)
    def send(*args,**kwargs):
        calls.append((args,kwargs)); return Response()
    monkeypatch.setattr(host.requests,'request',send)
    with host.app.app_context():
        host._qonto_request('POST','/v2/payment_links',{'payment_link':{}},idempotency_key='stable-test-key')
    headers=calls[0][1]['headers']
    assert headers['Authorization'] == 'Bearer merchant-test-token'
    assert headers['X-Qonto-Idempotency-Key'] == 'stable-test-key'
    monkeypatch.setattr(host, '_qonto_oauth_has_scope', lambda *a: False)
    with host.app.app_context(), pytest.raises(host.QontoConfigurationError):
        host._qonto_request('POST','/v2/payment_links',{})
    assert len(calls)==1


def test_external_tenant_still_cannot_call_merchant_qonto(monkeypatch):
    monkeypatch.setattr(host, '_is_external_partner_session', lambda: True)
    with host.app.test_request_context('/api/admin/example'), pytest.raises(host.QontoConfigurationError):
        host._qonto_request('POST','/v2/client_invoices',{},idempotency_key='tenant-attack')
