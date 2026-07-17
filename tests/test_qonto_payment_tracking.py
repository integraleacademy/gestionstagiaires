import hashlib, hmac, json, os, time, unittest
from unittest.mock import patch
import app as gestion_app

class QontoPaymentTrackingTests(unittest.TestCase):
    def inv(self,total="1650.00", paid=None, status="unpaid"):
        d={"total_amount":{"value":total},"status":status}
        if paid is not None: d["amount_paid"]={"value":paid}
        return d
    def test_cases_1_to_6_normalize(self):
        cases=[(self.inv(paid="0.00"),165000,0,165000,"unpaid"),(self.inv(paid="600.00"),165000,60000,105000,"partially_paid"),(self.inv(paid="1650.00",status="paid"),165000,165000,0,"paid"),(self.inv(total="1650.00",paid="1700.00"),165000,170000,0,"paid"),(self.inv(paid="600.00",status="canceled"),165000,60000,105000,"canceled"),(self.inv(),165000,0,165000,"unpaid")]
        for payload,total,paid,remaining,status in cases:
            got=gestion_app.normalize_qonto_invoice_payment_data(payload)
            self.assertEqual((got['qonto_total_amount_cents'],got['qonto_amount_paid_cents'],got['qonto_remaining_amount_cents'],got['qonto_payment_status']),(total,paid,remaining,status))
    def test_partial_progress(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoTotalAmountCents":165000,"qontoAmountPaidCents":60000,"amount":1650}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['invoiced_amount_cents'],165000); self.assertEqual(s['paid_amount_cents'],60000); self.assertEqual(s['remaining_amount_cents'],105000); self.assertAlmostEqual(s['payment_percentage'],36.36)
    def test_api_error_keeps_existing_amount(self):
        data={"sessions":[{"id":"S1","date_start":"2026-01-01","trainees":[{"id":"T1","personal_amount":1650}]}],"billing_lines":[{"id":gestion_app._billing_line_id("S1","T1","PERSONNEL","0"),"traineeId":"T1","sessionId":"S1","financingType":"PERSONNEL","amount":1650,"qontoInvoiceId":"inv","qontoInvoiceAmountPaid":600,"qontoAmountPaidCents":60000}]}
        line=data["billing_lines"][0]
        with patch.object(gestion_app,"get_qonto_invoice",side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError): gestion_app._sync_billing_line_with_qonto(data,line)
        saved=data["billing_lines"][0]
        self.assertEqual(saved['qontoAmountPaidCents'],60000); self.assertTrue(saved.get('qontoSyncError'))
    def test_two_invoices_no_double_count_and_legacy(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"A","qontoTotalAmountCents":100000,"qontoAmountPaidCents":60000,"amount":1000},{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"B","qontoTotalAmountCents":65000,"amount":650},{"traineeId":"T1","financingType":"PERSONNEL","manualPaymentInvoiceId":"A","amountPaid":600}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['invoiced_amount_cents'],165000); self.assertEqual(s['paid_amount_cents'],60000); self.assertEqual(s['remaining_amount_cents'],105000); self.assertEqual(s['by_financer']['PERSONNEL']['payment_status'],'partially_paid')
    def test_canceled_excluded(self):
        s=gestion_app.calculate_trainee_financial_summary({"id":"T1","personal_amount":1650},[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"A","qontoTotalAmountCents":165000,"qontoAmountPaidCents":165000,"invoiceStatus":"canceled"}])
        self.assertEqual(s['invoiced_amount_cents'],0); self.assertEqual(s['paid_amount_cents'],0)
    def test_webhook_invalid_signature_and_idempotent_valid(self):
        client=gestion_app.app.test_client(); raw=json.dumps({"event":"v1/client-invoices.updated","data":{"id":"inv"}}).encode(); secret="s"
        with patch.dict(os.environ,{"QONTO_WEBHOOK_SECRET":secret}), patch.object(gestion_app,"load_data",return_value={"sessions":[],"billing_lines":[]}):
            self.assertIn(client.post('/api/qonto/webhooks',data=raw,headers={"X-Qonto-Signature":"bad","Content-Type":"application/json"}).status_code,(400,401))
        ts=str(int(time.time())); sig=hmac.new(secret.encode(),f"{ts}.".encode()+raw,hashlib.sha256).hexdigest(); header=f"t={ts},v1={sig}"
        data={"sessions":[{"id":"S1","date_start":"2026-01-01","trainees":[{"id":"T1","personal_amount":1650,"qonto_invoice":{"qonto_invoice_id":"inv","amount_ttc":1650}}]}],"billing_lines":[]}
        remote={"client_invoice":{"id":"inv","status":"unpaid","total_amount":{"value":"1650.00"},"amount_paid":{"value":"600.00"}}}
        saved=[]
        with patch.dict(os.environ,{"QONTO_WEBHOOK_SECRET":secret}), patch.object(gestion_app,"load_data",return_value=data), patch.object(gestion_app,"save_data",side_effect=saved.append), patch.object(gestion_app,"get_qonto_invoice",return_value=remote):
            self.assertEqual(client.post('/api/qonto/webhooks',data=raw,headers={"X-Qonto-Signature":header,"Content-Type":"application/json"}).status_code,200)
            self.assertEqual(client.post('/api/qonto/webhooks',data=raw,headers={"X-Qonto-Signature":header,"Content-Type":"application/json"}).status_code,200)
        self.assertEqual(saved[-1]['sessions'][0]['trainees'][0]['qonto_invoice']['qonto_amount_paid_cents'],60000)

if __name__ == '__main__': unittest.main()
