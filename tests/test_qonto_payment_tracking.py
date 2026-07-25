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

    def test_qonto_paid_amount_aliases_are_normalized(self):
        got=gestion_app.normalize_qonto_invoice_payment_data({"total_amount":{"value":"1650.00"},"paid_amount":{"value":"600.00"},"status":"unpaid"})
        self.assertEqual(got["qonto_amount_paid_cents"],60000)
        self.assertEqual(got["qonto_remaining_amount_cents"],105000)
        self.assertEqual(got["qonto_payment_status"],"partially_paid")
        got=gestion_app.normalize_qonto_invoice_payment_data({"total_amount":{"value":"1650.00"},"remaining_amount":{"value":"1050.00"},"status":"unpaid"})
        self.assertEqual(got["qonto_amount_paid_cents"],60000)
        self.assertEqual(got["qonto_remaining_amount_cents"],105000)
        self.assertEqual(got["qonto_payment_status"],"partially_paid")

    def test_partial_progress(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoTotalAmountCents":165000,"qontoAmountPaidCents":60000,"amount":1650}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['invoiced_amount_cents'],165000); self.assertEqual(s['paid_amount_cents'],60000); self.assertEqual(s['remaining_amount_cents'],105000); self.assertAlmostEqual(s['payment_percentage'],36.36)

    def test_cpf_external_billing_is_excluded_from_qonto_payment_objective(self):
        trainee={"id":"T1","cpf_amount":3885,"personal_amount":415}
        lines=[
            {"traineeId":"T1","financingType":"CPF","amount":3885},
            {"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoTotalAmountCents":41500,"qontoAmountPaidCents":0,"amount":415},
        ]
        summary=gestion_app.calculate_trainee_financial_summary(trainee, lines)
        # CPF is invoiced and collected in its dedicated external system. Only
        # the personal invoice is expected and collected through Qonto here.
        self.assertEqual(summary["funded_total_cents"], 430000)
        self.assertEqual(summary["externally_invoiced_total_cents"], 388500)
        self.assertEqual(summary["planned_total_cents"], 41500)
        self.assertEqual(summary["invoiced_total_cents"], 41500)
        self.assertEqual(summary["remaining_total_cents"], 41500)
        self.assertEqual(summary["invoicing_percentage"], 100)
        self.assertEqual(summary["payment_percentage"], 0)
        self.assertEqual(summary["by_financer"]["CPF"]["invoiced_amount_cents"], 388500)
        self.assertTrue(summary["by_financer"]["CPF"]["externally_managed"])
        self.assertEqual(summary["by_financer"]["CPF"]["remaining_amount_cents"], 0)

    def test_qonto_invoice_partial_payment_without_manual_payment_builds_entry(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoInvoiceNumber":"FL-2026-314","qontoTotalAmountCents":165000,"qontoAmountPaidCents":60000,"qontoStatus":"unpaid","amount":1650}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['paid_total_cents'],60000)
        self.assertEqual(s['remaining_total_cents'],105000)
        self.assertAlmostEqual(s['payment_percentage'],36.36)
        self.assertEqual(s['qonto_payment_entries'][0]['payment_status'],'partially_paid')
        self.assertEqual(s['qonto_payment_entries'][0]['invoice_number'],'FL-2026-314')

    def test_qonto_invoice_and_linked_manual_payment_are_not_double_counted(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoTotalAmountCents":165000,"qontoAmountPaidCents":60000,"qontoStatus":"unpaid","amount":1650},{"traineeId":"T1","financingType":"PERSONNEL","manualPaymentInvoiceId":"inv","amountPaid":600}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['paid_total_cents'],60000)
        self.assertEqual(s['qonto_paid_total_cents'],60000)
        self.assertEqual(s['manual_paid_total_cents'],0)

    def test_returned_sepa_collections_cancel_cumulative_invoice_paid_amount(self):
        line={
            "traineeId":"T1", "financingType":"PERSONNEL", "paymentMode":"sepa_direct_debit",
            "qontoInvoiceId":"inv", "qonto_total_amount_cents":347400,
            "qonto_amount_paid_cents":139000, "amount":3474,
            "directDebitInstallments":[
                {"date":"2026-06-05","amount":695,"status":"returned"},
                {"date":"2026-07-06","amount":695,"status":"returned"},
                {"date":"2026-08-05","amount":695,"status":"scheduled"},
            ],
        }
        self.assertEqual(gestion_app._reconciled_qonto_paid_cents(line,139000),0)
        line["qonto_amount_paid_cents"]=gestion_app._reconciled_qonto_paid_cents(line,139000)
        summary=gestion_app.calculate_trainee_financial_summary({"id":"T1","personal_amount":3474},[line])
        self.assertEqual(summary["paid_total_cents"],0)
        self.assertEqual(summary["remaining_total_cents"],347400)
        self.assertEqual(summary["payment_status"],"unpaid")

    def test_completed_sepa_collection_is_counted_but_returned_one_is_not(self):
        line={"paymentMode":"sepa_direct_debit","directDebitInstallments":[
            {"amount":695,"status":"completed"},{"amount":695,"status":"returned"}
        ]}
        self.assertEqual(gestion_app._reconciled_qonto_paid_cents(line,139000),69500)

    def test_pending_sepa_plan_keeps_invoice_amount_until_collection_is_terminal(self):
        line={"paymentMode":"sepa_direct_debit","directDebitInstallments":[
            {"amount":695,"status":"scheduled"}
        ]}
        self.assertEqual(gestion_app._reconciled_qonto_paid_cents(line,69500),69500)

    def test_api_error_keeps_existing_amount(self):
        data={"sessions":[{"id":"S1","date_start":"2026-01-01","trainees":[{"id":"T1","personal_amount":1650}]}],"billing_lines":[{"id":gestion_app._billing_line_id("S1","T1","PERSONNEL","0"),"traineeId":"T1","sessionId":"S1","financingType":"PERSONNEL","amount":1650,"qontoInvoiceId":"inv","qontoInvoiceAmountPaid":600,"qontoAmountPaidCents":60000}]}
        line=data["billing_lines"][0]
        with patch.object(gestion_app,"get_qonto_invoice",side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError): gestion_app._sync_billing_line_with_qonto(data,line)
        saved=data["billing_lines"][0]
        self.assertEqual(saved['qonto_amount_paid_cents'],60000); self.assertTrue(saved.get('qontoSyncError'))
    def test_two_invoices_no_double_count_and_legacy(self):
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"A","qontoTotalAmountCents":100000,"qontoAmountPaidCents":60000,"amount":1000},{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"B","qontoTotalAmountCents":65000,"amount":650},{"traineeId":"T1","financingType":"PERSONNEL","manualPaymentInvoiceId":"A","amountPaid":600}]
        s=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(s['invoiced_amount_cents'],165000); self.assertEqual(s['paid_amount_cents'],60000); self.assertEqual(s['remaining_amount_cents'],105000); self.assertEqual(s['by_financer']['PERSONNEL']['payment_status'],'partially_paid')
    def test_canceled_excluded(self):
        s=gestion_app.calculate_trainee_financial_summary({"id":"T1","personal_amount":1650},[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"A","qontoTotalAmountCents":165000,"qontoAmountPaidCents":165000,"invoiceStatus":"canceled"}])
        self.assertEqual(s['invoiced_amount_cents'],0); self.assertEqual(s['paid_amount_cents'],0)

    def test_real_partial_invoice_1100_over_1650_is_canonical(self):
        got=gestion_app.normalize_qonto_invoice_payment_data({"total_amount":{"value":"1650.00"},"amount_paid":{"value":"1100.00"},"status":"unpaid"})
        self.assertEqual(got["qonto_total_amount_cents"],165000)
        self.assertEqual(got["qonto_amount_paid_cents"],110000)
        self.assertEqual(got["qonto_remaining_amount_cents"],55000)
        self.assertEqual(got["qonto_payment_status"],"partially_paid")
        trainee={"id":"T1","personal_amount":1650}
        lines=[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoInvoiceNumber":"FL-2026-314","qonto_total_amount_cents":165000,"qonto_amount_paid_cents":110000,"qonto_status":"unpaid","amount":1650}]
        summary=gestion_app.calculate_trainee_financial_summary(trainee,lines)
        self.assertEqual(summary["planned_total_cents"],165000)
        self.assertEqual(summary["invoiced_total_cents"],165000)
        self.assertEqual(summary["qonto_paid_total_cents"],110000)
        self.assertEqual(summary["manual_paid_total_cents"],0)
        self.assertEqual(summary["paid_total_cents"],110000)
        self.assertEqual(summary["remaining_total_cents"],55000)
        self.assertAlmostEqual(summary["payment_percentage"],66.67,places=2)
        self.assertEqual(summary["payment_status"],"partially_paid")
        entry=summary["qonto_payment_entries"][0]
        self.assertEqual(entry["invoice_number"],"FL-2026-314")
        self.assertEqual(entry["total_amount_cents"],165000)
        self.assertEqual(entry["paid_amount_cents"],110000)
        self.assertEqual(entry["remaining_amount_cents"],55000)
        self.assertEqual(entry["payment_status"],"partially_paid")

    def test_billing_payment_progress_template_contract(self):
        template = open('templates/admin_sessions_billing.html', encoding='utf-8').read()
        partial = gestion_app.serialize_qonto_invoice_for_frontend({'qontoInvoiceId':'inv','qontoInvoiceNumber':'FL-2026-314','qonto_total_amount_cents':165000,'qonto_amount_paid_cents':110000})
        self.assertEqual(partial['remaining_amount_cents'], 55000)
        self.assertAlmostEqual(partial['payment_percentage'], 66.67, places=2)
        self.assertEqual(partial['payment_status'], 'partially_paid')
        self.assertIn('paymentProgressCell', template)
        self.assertIn('fmtMoneyCents(p.paid_amount_cents)} encaissé', template)
        self.assertIn('Reste ${fmtMoneyCents(p.remaining_amount_cents)}', template)
        self.assertIn('width:${width}%', template)
        self.assertIn('payment-progress--partial', template)
        self.assertIn("function matchesPaymentFilter(pay, filter)", template)
        self.assertIn("function matchesPaymentFilter(pay, filter){if(!filter)return true;if(filter==='paid_or_partially_paid')return pay==='paid'||pay==='partially_paid';return pay===filter;}", template)
        self.assertIn('<option value="partially_paid">Paiement partiel</option>', template)
        self.assertIn('<option value="paid">Payée</option>', template)
        self.assertNotIn('badge yellow">En attente</span>', template)
        self.assertNotEqual(partial['payment_status'], 'paid')
        trainee_template = open('templates/admin_trainee.html', encoding='utf-8').read()
        self.assertIn("installmentDate(i)>=today", trainee_template)

    def test_billing_payment_progress_unpaid_and_paid_cases(self):
        unpaid = gestion_app.serialize_qonto_invoice_for_frontend({'qontoInvoiceId':'inv','qonto_total_amount_cents':165000,'qonto_amount_paid_cents':0})
        self.assertEqual(unpaid['remaining_amount_cents'], 165000)
        self.assertEqual(unpaid['payment_percentage'], 0)
        self.assertEqual(unpaid['payment_status'], 'unpaid')
        paid = gestion_app.serialize_qonto_invoice_for_frontend({'qontoInvoiceId':'inv','qonto_total_amount_cents':165000,'qonto_amount_paid_cents':165000})
        self.assertEqual(paid['remaining_amount_cents'], 0)
        self.assertEqual(paid['payment_percentage'], 100)
        self.assertEqual(paid['payment_status'], 'paid')


    def test_frontend_serializer_1100_partial_shape(self):
        invoice={"qontoInvoiceId":"inv","qontoInvoiceNumber":"FL-2026-314","qonto_total_amount_cents":165000,"qonto_amount_paid_cents":110000,"qonto_payment_status":"partially_paid","qonto_status":"unpaid","qontoLastSyncedAt":"2026-07-17T00:00:00Z"}
        got=gestion_app.serialize_qonto_invoice_for_frontend(invoice)
        self.assertEqual(got,{"invoice_number":"FL-2026-314","total_amount_cents":165000,"paid_amount_cents":110000,"remaining_amount_cents":55000,"payment_percentage":66.67,"payment_status":"partially_paid","qonto_status":"unpaid","last_synced_at":"2026-07-17T00:00:00Z","invoice_id":"inv"})

    def test_render_contract_uses_canonical_invoice_json(self):
        trainee={"id":"T1","personal_amount":1650}
        line={"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qontoInvoiceNumber":"FL-2026-314","qonto_total_amount_cents":165000,"qonto_amount_paid_cents":110000,"qonto_payment_status":"partially_paid","qonto_status":"unpaid","amount":1650}
        line["qonto_invoice"]=gestion_app.serialize_qonto_invoice_for_frontend(line)
        summary=gestion_app.calculate_trainee_financial_summary(trainee,[line])
        html=json.dumps({"lines":[line],"financial_summary":summary},ensure_ascii=False)
        self.assertIn('110000',html)
        self.assertIn('55000',html)
        self.assertIn('66.67',html)
        self.assertIn('partially_paid',html)
        display='ENCAISSÉ 1 100,00 € RESTE À PAYER 550,00 € 67 % Partiellement payé'
        self.assertIn('1 100,00 €',display)
        self.assertIn('550,00 €',display)
        self.assertIn('67 %',display)
        self.assertIn('Partiellement payé',display)
        forbidden='ENCAISSÉ 0,00 € RESTE À PAYER 1 650,00 € Aucun paiement enregistré pour le moment'
        self.assertNotIn('ENCAISSÉ 0,00 €',display)
        self.assertNotIn('RESTE À PAYER 1 650,00 €',display)
        self.assertNotIn('Aucun paiement enregistré pour le moment',display)

    def test_missing_paid_field_never_creates_false_paid_status(self):
        summary=gestion_app.calculate_trainee_financial_summary({"id":"T1","personal_amount":1650},[{"traineeId":"T1","financingType":"PERSONNEL","qontoInvoiceId":"inv","qonto_total_amount_cents":165000,"qonto_status":"unpaid"}])
        self.assertEqual(summary["paid_total_cents"],0)
        self.assertEqual(summary["remaining_total_cents"],165000)
        self.assertEqual(summary["payment_status"],"unpaid")
        self.assertEqual(summary["qonto_payment_entries"],[])

    def test_admin_template_uses_canonical_payment_rendering(self):
        html=open("templates/admin_trainee.html",encoding="utf-8").read()
        self.assertIn("canonicalInvoiceEntry",html)
        self.assertIn("lineRemaining(l)>0?fmtMoney(lineRemaining(l))",html)
        self.assertIn("Partiellement payé",html)
        self.assertIn("Math.round(c.progressPaiement)}%",html)
        self.assertIn("function lineHasGeneratedInvoice", html)
        self.assertIn("c.resteAFacturer>0.01", html)
        self.assertIn("Géré hors plateforme", html)

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
