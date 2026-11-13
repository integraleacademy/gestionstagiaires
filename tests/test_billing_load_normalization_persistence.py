"""A load-time normalization must not erase a concurrent invoice recovery."""

import json

import app as gestion


def test_normalization_save_keeps_invoice_attached_after_initial_read(monkeypatch, tmp_path):
    for name, value in {
        "PERSIST_DIR": tmp_path,
        "DATA_FILE": tmp_path / "data.json",
        "BACKUP_DIR": tmp_path / "backups",
    }.items():
        monkeypatch.setattr(gestion, name, str(value))
    (tmp_path / "backups").mkdir()
    monkeypatch.setattr(gestion, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(gestion, "_partner_postgres_shadow", lambda: False)
    initial = {
        "sessions": [{
            "id": "S-NORMALIZATION", "training_type": "APS",
            "date_start": "2027-01-04", "date_end": "2027-02-18",
            "trainees": [{"id": "T-NORMALIZATION", "first_name": "Test",
                          "last_name": "Normalization", "personal_amount": 950}],
        }],
        "billing_lines": [{
            "id": "bill-normalization", "qontoInvoiceId": None,
            "invoiceStatus": "not_invoiced", "generationInProgress": True,
            "paymentMode": "cash", "directDebitInstallments": [],
        }],
    }
    gestion.save_data(initial)
    normalize = gestion.ensure_public_tokens
    interleavings = []

    def attach_during_normalization(stale):
        # load_data has already read the old invoice-less document. Another
        # operation now attaches the verified remote invoice atomically.
        def attach(current):
            current["billing_lines"][0].update(
                qontoInvoiceId="invoice-recovered", qontoInvoiceNumber="F-TEST-456",
                invoiceStatus="finalized", generationInProgress=False,
                paymentMode="sepa_direct_debit",
                directDebitInstallments=[{
                    "date": "2026-12-01", "amount": 950,
                    "qonto_direct_debit_subscription_id": "subscription-existing",
                }],
            )
            return {"ok": True}

        assert not interleavings
        gestion._atomic_update_data(attach)
        interleavings.append("invoice attached after read")
        normalize(stale)
        # Force the internal normalization save before the eventual return
        # through _cache_request_data, where tracking was previously started.
        return True

    monkeypatch.setattr(gestion, "ensure_public_tokens", attach_during_normalization)
    returned = gestion.load_data()
    persisted = json.loads((tmp_path / "data.json").read_text())
    assert interleavings == ["invoice attached after read"]
    for result in (returned, persisted):
        row = result["billing_lines"][0]
        assert row["qontoInvoiceId"] == "invoice-recovered"
        assert row["qontoInvoiceNumber"] == "F-TEST-456"
        assert row["generationInProgress"] is False
        assert row["paymentMode"] == "sepa_direct_debit"
        assert row["directDebitInstallments"][0]["qonto_direct_debit_subscription_id"] == "subscription-existing"
        assert result["sessions"][0]["trainees"][0]["public_token"]
