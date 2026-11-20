// Run with NODE_PATH pointing to an installation of jsdom.
const {JSDOM} = require('jsdom');
const {readFileSync} = require('node:fs');
const assert = require('node:assert/strict');
const source = readFileSync('static/js/mandate-amount.js', 'utf8');
const dom = new JSDOM(`<input name="paymentMode" type="radio" value="sepa" checked>
  <div class="billing-modal-grid"><select id="installments"></select></div>
  <div id="installmentPreview">${[1, 2].map(i => `<div data-installment-row>
    <input data-installment-date type="date" value="2027-0${i}-15">
    <input data-installment-amount type="number" min="0.01" step="0.01"></div>`).join('')}</div>`,
  {runScripts:'outside-only'});
const {document, Event} = dom.window;
const helper = dom.window.eval(source + '\nSepaMandateAmount');
const amounts = [...document.querySelectorAll('[data-installment-amount]')];
helper.mount({amountTTC: 950, mandateAvailableCents: 80000}, () => {
  amounts.forEach(field => { field.value = (helper.total() / 2).toFixed(2); });
});
const field = document.querySelector('#mandateDebitAmount');
assert.equal(field.value, '800.00');
field.value = '250.50';
field.dispatchEvent(new Event('input', {bubbles:true}));
const plan = helper.plan(message => assert.fail(message));
assert.equal(plan.debitAmount, 250.50);
assert.equal(plan.schedule[0].amount, 125.25);
amounts[0].value = '125.50';
amounts[0].dispatchEvent(new Event('input', {bubbles:true}));
assert.equal(helper.plan(message => assert.fail(message)).debitAmount, 250.75);
field.value = '850';
assert.equal(helper.plan(() => {}), null);
