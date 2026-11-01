const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../templates/admin_trainee.html'), 'utf8');

function source(name) {
  const start = template.search(new RegExp(`^  (?:async )?function ${name}\\(`, 'm'));
  assert.ok(start >= 0, name);
  const rest = template.slice(start + 1);
  const end = rest.search(/\n  (?:async )?function /);
  return template.slice(start, end < 0 ? undefined : start + 1 + end);
}

function setup() {
  const ui = {box: {innerHTML: ''}, readOnly: false, feedback: [], modalLoading: false,
    currentLine: null, calls: 0, opened: 0};
  const context = vm.createContext({...ui,
    esc: value => String(value ?? '').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    fmtMoney: value => Number(value || 0).toFixed(2),
    formatIsoDateFr: value => value,
    isCpfQontoLine: line => line.financingType === 'CPF',
    logicalInstallmentsForLine: line => line.directDebitInstallments || [],
    lineHasPendingMandate: () => false,
    paymentStatusLabel: value => value,
    computeFinance: () => ({}),
    renderFinancingValidation: () => {}, renderSummary: () => {},
    renderBreakdown: () => {}, renderAlerts: () => {}, renderPayments: () => {},
    renderInstallments: () => {},
    document: {body: {insertAdjacentHTML() {context.opened++;}}},
    window: {},
    showQontoFeedback: message => context.feedback.push(message),
    modalMessage: message => context.feedback.push(message),
    billingApi: async () => {context.calls++;},
  });
  for (const name of ['canonicalInvoiceEntry', 'lineHasExternalInvoice', 'lineHasGeneratedInvoice',
    'lineAmount', 'linePaid', 'lineRemaining', 'linePaymentStatus', 'invoiceStatusLabel',
    'invoiceBadge', 'badge', 'renderInvoiceModalContent', 'openGenerateInvoiceModal',
    'createCurrentInvoice', 'financePaymentRows', 'render']) {
    vm.runInContext(source(name), context);
  }
  return context;
}

for (const status of ['external_generated', 'external', 'generated_externally']) {
  test(`external invoice ${status} has no create/PDF action and is clearly labelled`, async () => {
    const ui = setup();
    const line = {id: 'personal', financingType: 'PERSONNEL', amountTTC: 1830, invoiceStatus: status};
    ui.render([line]);
    assert.match(ui.box.innerHTML, /Facture générée ailleurs/);
    assert.match(ui.box.innerHTML, /téléchargement sera disponible après rattachement/);
    assert.doesNotMatch(ui.box.innerHTML, /data-create=|\/admin\/qonto\/invoices\//);
    assert.equal(ui.invoiceStatusLabel(line), 'Facture générée ailleurs');
    ui.openGenerateInvoiceModal(line);
    assert.equal(ui.opened, 0);
    assert.match(ui.feedback[0], /déjà générée ailleurs/);
    const modal = ui.renderInvoiceModalContent(line);
    assert.doesNotMatch(modal, /openInvoiceDecision|Continuer/);
    ui.currentLine = line;
    await ui.createCurrentInvoice();
    assert.equal(ui.calls, 0);
    assert.match(ui.feedback[1], /Une facture existe déjà/);
  });
}

test('new invoices can be created; linked Qonto invoices remain viewable', () => {
  const ui = setup();
  ui.render([{id: 'new', financingType: 'PERSONNEL', amountTTC: 100, invoiceStatus: 'not_generated'}]);
  assert.match(ui.box.innerHTML, /data-create="new"/);
  ui.render([{id: 'linked', financingType: 'PERSONNEL', amountTTC: 100,
    invoiceStatus: 'external_generated', qontoInvoiceId: 'real-invoice'}]);
  assert.doesNotMatch(ui.box.innerHTML, /data-create=/);
  assert.match(ui.box.innerHTML, /\/admin\/qonto\/invoices\/real-invoice\/pdf/);
});

test('bank transfer displays actual payment date and reference exactly once', () => {
  const ui = setup();
  const transfer = {id: 'tx-1', status: 'completed', amount_cents: 183000, paid_at: '2026-09-03T14:32:00Z',
    reference: 'Virement de M Exemple Test', label: 'M Exemple Test'};
  const line = {id: 'personal', amountTTC: 1830, invoiceStatus: 'external_generated',
    qontoBankTransfers: [transfer], qontoBankTransferPaidCents: 183000};
  const summary = {qontoPaymentEntries: [{source: 'qonto_bank_transfer',
    paid_amount_cents: 183000, transactions: [transfer], last_synced_at: '2026-11-01T16:00:00Z'}]};
  const rows = ui.financePaymentRows([line], summary);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].amount, 1830);
  assert.equal(rows[0].date, transfer.paid_at);
  assert.equal(rows[0].dateLabel, 'Reçu le');
  assert.equal(rows[0].note, transfer.reference);
  assert.equal(rows[0].mode, 'Virement bancaire');
  assert.equal(ui.linePaid(line), 1830);
  assert.equal(ui.lineRemaining(line), 0);
  assert.equal(ui.linePaymentStatus(line), 'paid');
});

test('linked invoice and bank transfer are represented by one aggregate payment', () => {
  const ui = setup();
  const line = {qontoInvoiceId: 'invoice-1', amountTTC: 100,
    qonto_invoice: {total_amount_cents: 10000, paid_amount_cents: 10000},
    qontoBankTransfers: [{id: 'tx-2', amount_cents: 10000}], qontoBankTransferPaidCents: 10000};
  const rows = ui.financePaymentRows([line], {qontoPaymentEntries: [{source: 'qonto',
    invoice_id: 'invoice-1', paid_amount_cents: 10000, remaining_amount_cents: 0}]});
  assert.equal(rows.length, 1);
  assert.equal(rows[0].amount, 100);
  assert.equal(ui.linePaid(line), 100);
});


test('reversed transfers do not appear as received payments', () => {
  const ui = setup();
  const transfers = [{id: 'paid', status: 'completed', amount_cents: 5000},
    {id: 'reversed', status: 'reversed', amount_cents: 5000}];
  const line = {amountTTC: 100, qontoBankTransfers: transfers, qontoBankTransferPaidCents: 5000};
  const rows = ui.financePaymentRows([line], {});
  assert.equal(rows.length, 1);
  assert.equal(rows[0].amount, 50);
});
