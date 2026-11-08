const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../templates/admin_sessions_billing.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const filterIds = ['q', 'formationFilter', 'sessionFilter', 'financingFilter', 'invoiceFilter',
  'paymentFilter', 'startDateFilter', 'endDateFilter', 'minAmount', 'maxAmount'];

function ui(now = '2026-11-08T12:00:00Z') {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        value: '', innerHTML: '', textContent: '', checked: false, options: [],
        classList: {toggle(name, on) {if (on) classes.add(name); else classes.delete(name);}},
        setAttribute() {}, add(option) {this.options.push(option);},
      });
    }
    return elements.get(id);
  }
  const ctx = vm.createContext({
    console, Intl, URL, URLSearchParams,
    Date: class extends Date {constructor(...args) {super(...(args.length ? args : [now]));}},
    window: {location: {search: '', href: 'https://example.test/admin/sessions/facturation'}},
    history: {replaceState() {}},
    document: {
      getElementById: element, addEventListener() {},
      querySelector: () => element('page'),
      querySelectorAll: selector => selector === '.billing-filters input,.billing-filters select'
        ? filterIds.map(element) : [],
    },
    Option: class {constructor(text, value) {this.text = text; this.value = value;}},
    fetch() {throw new Error('These UI tests must never contact an external service.');},
  });
  vm.runInContext(script, ctx);
  const run = code => vm.runInContext(code, ctx);
  return {
    ctx, element, run,
    setLines(rows, cpfRows = []) {
      ctx.rows = rows; ctx.cpfRows = cpfRows;
      run('billingLines=rows; cpfInvoiceLines=cpfRows; lines=billingLines;');
      ctx.applyFilters();
    },
    filteredIds() {return Array.from(run('filtered.map(line=>line.id)'));},
  };
}

function invoice(id, fields = {}) {
  return {
    id, sessionId: 'session-aps', traineeId: `trainee-${id}`, traineeLastName: id,
    traineeFirstName: 'Exemple', formationName: 'APS', sessionName: 'APS Novembre',
    financingType: 'PERSONNEL', invoiceStatus: 'sent', qontoInvoiceId: `invoice-${id}`,
    amount: 1000, total_amount_cents: 100000, paid_amount_cents: 0,
    remaining_amount_cents: 100000, nextDirectDebitDate: null,
    ...fields,
  };
}

test('the follow-up filter excludes CPF invoices and includes personal balances, even for mixed financing', () => {
  const page = ui();
  page.setLines([
    invoice('unpaid', {traineeId: 'mixed-financing'}),
    invoice('partial', {paid_amount_cents: 40000, remaining_amount_cents: 60000}),
    invoice('cancelled-registration', {registrationCancelled: true, remaining_amount_cents: 25000,
      paid_amount_cents: 75000}),
    invoice('scheduled', {nextDirectDebitDate: '2026-12-04'}),
    invoice('settled', {invoiceStatus: 'paid', paid_amount_cents: 100000, remaining_amount_cents: 0}),
    invoice('cancelled-invoice', {invoiceStatus: 'cancelled'}),
    invoice('draft', {invoiceStatus: 'draft'}),
    invoice('external', {invoiceStatus: 'external_generated'}),
    invoice('unknown', {cpfPaymentUnknown: true}),
    invoice('control', {syncWarning: 'La synchronisation doit être vérifiée.'}),
    invoice('not-created', {qontoInvoiceId: '', invoiceStatus: 'not_invoiced'}),
    invoice('cpf-unpaid', {financingType: 'CPF', traineeId: 'mixed-financing'}),
    invoice('cpf-partial', {financingType: 'CPF', paid_amount_cents: 40000, remaining_amount_cents: 60000}),
    invoice('cpf-legacy', {financingType: 'AUTRE', financeurName: 'Caisse des dépôts et consignations'}),
    invoice('cpf-wedof', {financingType: '', cpfWedofInvoice: true}),
    invoice('cpf-reference', {financingType: '', cpfWedofReferenceOnly: true}),
  ]);
  page.ctx.applyStatFilter('no_next_debit');
  assert.deepEqual(page.filteredIds(), ['unpaid', 'partial', 'cancelled-registration']);
  const card = page.element('stats').innerHTML.split('data-stat-filter="no_next_debit"')[1];
  assert.match(card, /aria-pressed="true"/);
  assert.match(card, /3 factures/);
  assert.match(card.replace(/\s/g, ' '), /1 850,00 € restant à payer/);
  assert.match(page.element('tbody').innerHTML, /billing-registration-cancelled/);
  assert.equal((page.element('tbody').innerHTML.match(/Aucun prélèvement confirmé/g) || []).length, 3);
  assert.equal((page.element('tbody').innerHTML.match(/Synchroniser paiement/g) || []).length, 3);
  assert.doesNotMatch(page.ctx.paymentProgressCell(invoice('cpf', {financingType: 'CPF'})), /Aucun prélèvement confirmé/);

  page.ctx.applyStatFilter('no_next_debit');
  assert.equal(page.filteredIds().length, 16, 'a second click clears the quick filter and restores CPF invoices');
});

test('the filter respects search, training and financing filters, polling, reset and the CPF view', () => {
  const page = ui();
  page.setLines([
    invoice('Durand'),
    invoice('Martin', {formationName: 'A3P'}),
    invoice('Organisme', {financingType: 'AUTRE'}),
    invoice('future', {nextDirectDebitDate: '2026-12-04'}),
  ], [invoice('CPF-unpaid', {financingType: 'CPF'}),
    invoice('CPF-unknown', {financingType: 'CPF', cpfPaymentUnknown: true})]);
  page.ctx.applyStatFilter('no_next_debit');
  page.element('q').value = 'Durand';
  page.ctx.applyFilters();
  assert.deepEqual(page.filteredIds(), ['Durand']);
  assert.match(page.element('stats').innerHTML, /<b>1 facture<\/b>/);
  page.element('q').value = '';
  page.element('formationFilter').value = 'APS';
  page.element('financingFilter').value = 'PERSONNEL';
  page.ctx.applyFilters();
  assert.deepEqual(page.filteredIds(), ['Durand']);
  page.ctx.setBillingView('all', {updateUrl: false, resetFilters: false});
  assert.deepEqual(page.filteredIds(), ['Durand'], 'a periodic refresh preserves the active filter');
  assert.equal(page.run('activeBillingStatFilter'), 'no_next_debit');

  page.ctx.setBillingView('cpf', {updateUrl: false});
  assert.deepEqual(page.filteredIds(), ['CPF-unpaid', 'CPF-unknown']);
  assert.doesNotMatch(page.element('stats').innerHTML, /data-stat-filter="no_next_debit"/);
  page.ctx.applyStatFilter('no_next_debit');
  assert.deepEqual(page.filteredIds(), [], 'CPF invoices are never eligible for the no-debit filter');
  page.ctx.resetBillingFilters(); page.ctx.applyFilters();
  assert.deepEqual(page.filteredIds(), ['CPF-unpaid', 'CPF-unknown']);
});

test('an explicit API null or past date never falls back to the original payment plan', () => {
  const page = ui();
  const planned = {index: 1, date: '2026-12-04', status: 'scheduled',
    qonto_direct_debit_subscription_id: 'subscription-A'};
  for (const nextDirectDebitDate of [null, '', '2026-11-07']) {
    const line = invoice('without-future', {nextDirectDebitDate, directDebitInstallments: [planned]});
    assert.equal(page.ctx.nextDirectDebitDate(line), '');
    assert.match(page.ctx.paymentProgressCell(line), /Aucun prélèvement confirmé/);
  }
  const current = invoice('today', {nextDirectDebitDate: '2026-11-08'});
  assert.equal(page.ctx.nextDirectDebitDate(current), '2026-11-08');
  assert.match(page.ctx.paymentProgressCell(current), /Prochain prélèvement prévu le 08\/11\/2026/);
  assert.doesNotMatch(page.ctx.paymentProgressCell(current), /Aucun prélèvement confirmé/);
});

test('a failed debit synchronization is shown as unknown and is excluded from the no-debit filter', () => {
  const page = ui();
  const warning = invoice('debit-sync-warning', {qontoDirectDebitSyncWarning: 'Qonto temporairement indisponible'});
  page.setLines([warning, invoice('no-debit')]);
  page.ctx.applyStatFilter('no_next_debit');
  assert.deepEqual(page.filteredIds(), ['no-debit']);
  assert.match(page.ctx.paymentProgressCell(warning), /Programmation à vérifier/);
  assert.doesNotMatch(page.ctx.paymentProgressCell(warning), /Aucun prélèvement confirmé/);
});

test('upcoming dates use the French business day even before midnight UTC', () => {
  const page = ui('2026-11-07T23:30:00Z');
  assert.equal(page.ctx.nextDirectDebitDate(invoice('past', {nextDirectDebitDate: '2026-11-07'})), '');
  assert.equal(page.ctx.nextDirectDebitDate(invoice('today', {nextDirectDebitDate: '2026-11-08'})), '2026-11-08');
});

test('legacy responses only use an actionable Qonto installment, never a theoretical or failed date', () => {
  const page = ui();
  const line = invoice('legacy');
  delete line.nextDirectDebitDate;
  const schedule = {index: 1, date: '2026-12-04', status: 'scheduled'};
  const confirmed = {...schedule, qonto_direct_debit_subscription_id: 'subscription-A'};
  const withoutDate = [schedule,
    {...confirmed, status: 'declined'}, {...confirmed, status: 'cancelled'},
    {...confirmed, tracking_pending_qonto: true},
    {...confirmed, qonto_subscription_status: 'canceled'},
    {...confirmed, qonto_subscription_status: 'pending_mandate_signature'},
    {...confirmed, qonto_collection_status_raw: 'returned'},
  ];
  for (const item of withoutDate) {
    assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [item]}), '', JSON.stringify(item));
  }
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [confirmed]}), '2026-12-04');
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [
    {...confirmed, status: 'pending', date: '2026-11-09'},
  ]}), '2026-11-09');
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [confirmed,
    {...confirmed, schedule_index: 1, is_rejection_retry: true, date: '2026-12-12',
      qonto_direct_debit_subscription_id: 'retry-subscription', created_at: '2026-11-08'},
  ]}), '2026-12-04', 'another subscription on the same contract slot can still be active at the bank');
});

test('local tracking edits and removal do not cancel a confirmed bank operation', () => {
  const page = ui();
  const line = invoice('local-edit');
  delete line.nextDirectDebitDate;
  const confirmed = {index: 1, date: '2026-12-04', status: 'scheduled',
    qonto_direct_debit_subscription_id: 'subscription-A'};
  const edited = {...confirmed, tracking_pending_qonto: true, date: '2026-11-10',
    qonto_original_due_date: '2026-12-04'};
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [edited]}), '2026-12-04');
  for (const field of [
    {tracking_removed_at: '2026-11-07'}, {excluded_from_schedule_totals: true}, {rejection_treated: true},
  ]) {
    assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [{...confirmed, ...field}]}),
      '2026-12-04', JSON.stringify(field));
  }
});

test('bank collection status supersedes stale copies and subscription-only placeholders', () => {
  const page = ui();
  const line = invoice('duplicates');
  delete line.nextDirectDebitDate;
  const placeholder = {date: '2026-12-04', status: 'scheduled',
    qonto_direct_debit_subscription_id: 'subscription-A'};
  const collection = {...placeholder, qonto_direct_debit_collection_id: 'collection-A'};
  const failed = {...collection, qonto_collection_status_raw: 'returned'};
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [placeholder, collection, failed]}), '');
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [failed, collection, placeholder]}), '',
    'a terminal duplicate wins even when the stale active copy occurs later');
  const pending = {...collection, qonto_collection_status_raw: 'pending', qonto_subscription_status: 'cancelled'};
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [pending]}), '2026-12-04',
    'cancelling the subscription does not cancel an already submitted collection');
  const cancelled = {...collection, qonto_collection_status_raw: 'cancelled', updated_at: '2026-11-08T12:00:00Z'};
  assert.equal(page.ctx.nextDirectDebitDate({...line, directDebitInstallments: [
    {...collection, updated_at: '2026-11-08T10:00:00Z'}, cancelled,
  ]}), '');
});

test('a stale paid label cannot hide an unpaid balance or the synchronization button', () => {
  const page = ui();
  const stale = invoice('stale-paid', {invoiceStatus: 'paid', qonto_status: 'paid',
    qonto_invoice: {total_amount_cents: 347400, paid_amount_cents: 0,
      remaining_amount_cents: 347400, payment_status: 'unpaid'}, amount: 3474});
  assert.equal(page.ctx.normalizedPaymentStatus(stale), 'unpaid');
  assert.equal(page.ctx.normalizedInvoiceStatus(stale), 'finalized');
  assert.doesNotMatch(page.ctx.statusBadge(stale), />Payée</);
  assert.doesNotMatch(page.ctx.actionButtons(stale), />Payée</);
  assert.match(page.ctx.actionButtons(stale), /Synchroniser paiement/);
  assert.equal(page.ctx.hasNoNextDirectDebit(stale), true);
  page.setLines([stale]);
  page.ctx.applyStatFilter('paid');
  assert.deepEqual(page.filteredIds(), []);
  page.ctx.applyStatFilter('to_pay');
  assert.deepEqual(page.filteredIds(), ['stale-paid']);

  const partial = invoice('partial-paid', {invoiceStatus: 'paid', paid_amount_cents: 10000,
    remaining_amount_cents: 90000});
  assert.doesNotMatch(page.ctx.statusBadge(partial), />Payée</);
  assert.match(page.ctx.actionButtons(partial), /Synchroniser paiement/);
  const settled = invoice('settled', {invoiceStatus: 'finalized', paid_amount_cents: 100000,
    remaining_amount_cents: 0});
  assert.equal(page.ctx.normalizedInvoiceStatus(settled), 'paid');
  assert.match(page.ctx.statusBadge(settled), />Payée</);
  assert.doesNotMatch(page.ctx.paymentProgressCell(settled), /Aucun prélèvement confirmé/);
  assert.equal(page.ctx.normalizedInvoiceStatus({...settled, invoiceStatus: 'draft'}), 'draft');
});
