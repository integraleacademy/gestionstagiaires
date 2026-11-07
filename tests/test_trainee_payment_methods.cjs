const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');

const source = readFileSync(join(__dirname, '../static/js/trainee-sheet.js'), 'utf8');
const start = source.indexOf('  function paymentMethodTotals(');
const end = source.indexOf('  function cashCoversEntirePersonalFunding(', start);
const paymentMethodTotals = Function(source.slice(start, end) + '\nreturn paymentMethodTotals;')();

test('mixed payments show the cash and the collected debit exactly once', () => {
  const line = {qontoInvoiceId:'personal', qontoCollectedAmountCents:30000};
  const receipts = {totalPaye:902, cashPaid:602, qontoPaymentEntries:[
    {source:'qonto', invoice_id:'personal', paid_amount_cents:30000},
  ]};
  const lines = [line, {qontoInvoiceId:'cpf', qontoCollectedAmountCents:7800}];
  assert.deepEqual(paymentMethodTotals(receipts, lines, {qonto_paid_total_cents:30000}), [
    ['Espèces',60200], ['Prélèvements Qonto',30000],
  ]);
});

test('bank credits, unidentified invoice receipts and manual payments retain their source', () => {
  const receipts = {totalPaye:245.23, cashPaid:10, qontoPaymentEntries:[
    {source:'qonto', invoice_id:'personal', paid_amount_cents:10000},
    {source:'qonto_direct_debit', paid_amount_cents:10000},
    {source:'qonto_bank_transfer', paid_amount_cents:2000},
  ]};
  const lines = [{qontoInvoiceId:'personal', qontoCollectedAmountCents:0, qontoBankTransferPaidCents:7500}];
  assert.deepEqual(paymentMethodTotals(receipts, lines, {qonto_paid_total_cents:22000}), [
    ['Espèces',1000], ['Prélèvements Qonto',10000], ['Virements bancaires',9500],
    ['Qonto · mode non précisé',2500], ['Autres règlements saisis',1523],
  ]);
});
