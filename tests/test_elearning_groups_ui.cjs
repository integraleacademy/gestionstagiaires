/* Focused controller tests without browser permissions or external packages.
 * Execute the production script in a VM against the small DOM surface it uses.
 * This verifies interactions, not browser layout or native form validation.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../static/js/elearning-orders.js'), 'utf8');

class Element {
  constructor(props = {}) {
    Object.assign(this, {dataset: {}, disabled: false, hidden: false, textContent: '', listeners: {}}, props);
    const classes = new Set();
    this.classList = {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x), toggle: (x, enabled) => enabled ? classes.add(x) : classes.delete(x)};
  }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  dispatch(name, props = {}) {
    const event = {target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...props};
    (this.listeners[name] || []).forEach(handler => handler(event));
    return event;
  }
  focus() { this.focused = true; }
  setAttribute(name, value) { (this.attributes ||= {})[name] = value; }
  removeAttribute(name) { delete (this.attributes ||= {})[name]; }
}

class Input extends Element {
  constructor(name, value = '') { super({name, value, required: false, validationMessage: ''}); }
  setCustomValidity(message) { this.validationMessage = message; }
  valid() { return !this.validationMessage && (!this.required || Boolean(this.value.trim())); }
}

class Row extends Element {
  constructor(values = {}) {
    super();
    this.inputs = ['learner_id', 'last_name', 'first_name', 'email'].map(name => new Input(name, values[name] || ''));
    this.number = new Element();
    this.removeButton = new Element();
    this.removeButton.closest = selector => selector === '.el-remove' ? this.removeButton : selector === '.el-person' ? this : null;
  }
  querySelector(selector) {
    if (selector === '.el-row-number') return this.number;
    if (selector === '.el-remove') return this.removeButton;
    const match = selector.match(/^\[name="(.+)"\]$/);
    if (match) return this.inputs.find(input => input.name === match[1]);
    throw new Error('Unhandled row selector: ' + selector);
  }
  querySelectorAll(selector) {
    if (selector === 'input') return this.inputs;
    if (selector === 'input:not([type="hidden"])') return this.inputs.slice(1);
    throw new Error('Unhandled row selector: ' + selector);
  }
  cloneNode() { return new Row(Object.fromEntries(this.inputs.map(input => [input.name, input.value]))); }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}

class People extends Element {
  constructor(rows) { super(); this.children = []; rows.forEach(row => this.append(row)); }
  append(row) { row.parent = this; this.children.push(row); }
  get firstElementChild() { return this.children[0]; }
  querySelectorAll(selector) { assert.equal(selector, '.el-person'); return this.children; }
}

const complete = (email = 'alice@example.fr', id = 'learner-1') => ({learner_id: id, last_name: 'Martin', first_name: 'Alice', email});

function boot({rows = [{}], individual = false, locked = 0, price = '5900', unsaved = false, conflict = false} = {}) {
  const people = rows === null ? null : new People(rows.map(values => new Row(values)));
  const roster = new Element({dataset: {mode: individual ? 'individual' : 'group', lockedCount: String(locked), maxLearners: individual ? '1' : '100', unsaved: String(unsaved), conflict: String(conflict)}});
  roster.checkValidity = () => !people || people.children.every(row => row.inputs.every(input => input.valid()));
  roster.reportValidity = () => { roster.reported = true; };
  const course = new Element({selectedOptions: [{dataset: {price}}]});
  const review = new Element({name: 'next', value: 'review'});
  const save = new Element({name: 'next', value: 'save'});
  const add = individual ? null : new Element();
  const status = new Element();
  const nodes = {
    'el-roster-form': roster, 'el-learners': people, 'el-add': add,
    'el-course-code': course, 'el-save-status': status, 'el-review-button': review,
    'el-count': new Element(), 'el-total': new Element(), 'el-roster-count': people ? new Element() : null,
  };
  const document = {querySelector: () => null, querySelectorAll: () => [], getElementById: id => nodes[id] || null};
  const window = new Element();
  vm.runInNewContext(script, {document, window, Intl}, {filename: 'elearning-orders.js'});
  return {people, roster, course, review, save, add, status, nodes, window};
}

test('add creates an empty learner without duplicating identity; removing updates totals and numbering', () => {
  const page = boot({rows: [complete()]});
  assert.equal(page.nodes['el-count'].textContent, '1');
  page.add.dispatch('click');
  assert.equal(page.people.children.length, 2);
  const added = page.people.children[1];
  assert.ok(added.inputs.every(input => input.value === ''));
  assert.equal(added.querySelector('[name="last_name"]').focused, true);
  assert.equal(page.nodes['el-count'].textContent, '1');
  assert.equal(added.number.textContent, '2');
  const values = complete('bob@example.fr', '');
  added.inputs.forEach(input => { input.value = values[input.name]; });
  page.roster.dispatch('input');
  assert.equal(page.nodes['el-count'].textContent, '2');
  assert.match(page.nodes['el-total'].textContent, /^118,00\s+€/);
  page.people.dispatch('click', {target: page.people.children[0].removeButton});
  assert.equal(page.people.children.length, 1);
  assert.equal(added.number.textContent, '1');
  assert.equal(page.nodes['el-count'].textContent, '1');
  assert.match(page.nodes['el-total'].textContent, /^59,00\s+€/);
});

test('removing the last saved learner clears its ID and keeps a usable empty row', () => {
  const page = boot({rows: [complete()]});
  page.people.dispatch('click', {target: page.people.children[0].removeButton});
  assert.equal(page.people.children.length, 1);
  assert.ok(page.people.children[0].inputs.every(input => input.value === '' && !input.required));
  assert.equal(page.nodes['el-count'].textContent, '0');
  assert.equal(page.review.disabled, true);
  assert.equal(page.roster.checkValidity(), true);
});

test('duplicate e-mails are rejected case-insensitively and recover after correction', () => {
  const page = boot({rows: [complete(), complete(' ALICE@EXAMPLE.FR ', 'learner-2')]});
  const secondEmail = page.people.children[1].querySelector('[name="email"]');
  assert.match(secondEmail.validationMessage, /déjà/);
  const badSubmit = page.roster.dispatch('submit', {submitter: page.review});
  assert.equal(badSubmit.defaultPrevented, true);
  assert.equal(page.roster.reported, true);
  secondEmail.value = 'bob@example.fr';
  page.roster.dispatch('input');
  assert.equal(secondEmail.validationMessage, '');
  assert.equal(page.roster.checkValidity(), true);
});

test('partial rows require all identity fields while untouched blank rows stay optional', () => {
  const page = boot();
  assert.ok(page.people.children[0].inputs.every(input => !input.required));
  page.people.children[0].querySelector('[name="last_name"]').value = 'Martin';
  page.roster.dispatch('input');
  assert.ok(page.people.children[0].inputs.slice(1).every(input => input.required));
  assert.equal(page.roster.checkValidity(), false);
  assert.equal(page.roster.dispatch('submit', {submitter: page.save}).defaultPrevented, true);
});

test('save and review preserve the clicked submit button name/value for native submission', () => {
  for (const next of ['save', 'review']) {
    const page = boot({rows: [complete()]});
    page.roster.dispatch('input');
    assert.equal(page.window.dispatch('beforeunload').defaultPrevented, true);
    const submitter = page[next];
    const event = page.roster.dispatch('submit', {submitter});
    assert.equal(event.defaultPrevented, false);
    assert.equal(submitter.disabled, false);
    assert.deepEqual([submitter.name, submitter.value], ['next', next]);
    assert.equal(page.window.dispatch('beforeunload').defaultPrevented, false);
    assert.match(page.status.textContent, /Enregistrement en cours/);
  }
});

test('one individual learner has no add button; a fully locked individual has no editable DOM', () => {
  const individual = boot({individual: true, rows: [complete()]});
  assert.equal(individual.add, null);
  assert.equal(individual.people.children.length, 1);
  assert.equal(individual.review.disabled, false);
  const paid = boot({individual: true, locked: 1, rows: null});
  assert.equal(paid.people, null);
  assert.equal(paid.add, null);
  assert.equal(paid.nodes['el-count'].textContent, '0');
  assert.equal(paid.review.disabled, true);
  assert.equal(paid.roster.dispatch('submit', {submitter: paid.save}).defaultPrevented, false);
});

test('locked learners count toward the 100-person group limit', () => {
  const page = boot({locked: 99, rows: [complete()]});
  assert.equal(page.add.disabled, true);
  page.add.dispatch('click');
  assert.equal(page.people.children.length, 1);
  const full = boot({rows: Array.from({length: 100}, (_, n) => complete(`person${n}@example.fr`, String(n + 1)))});
  assert.equal(full.add.disabled, true);
  full.add.dispatch('click');
  assert.equal(full.people.children.length, 100);
});

test('free and unknown tariffs display accurately; course changes refresh the estimate', () => {
  const page = boot({rows: [complete()], price: ''});
  assert.equal(page.nodes['el-total'].textContent, 'Tarif à définir');
  page.course.selectedOptions[0].dataset.price = '0';
  page.roster.dispatch('change');
  assert.equal(page.nodes['el-total'].textContent, 'Gratuit');
  page.course.selectedOptions[0].dataset.price = '7500';
  page.roster.dispatch('change');
  assert.match(page.nodes['el-total'].textContent, /^75,00\s+€/);
});

test('individual creation hides/disables group naming, switching back restores it', () => {
  const create = new Element();
  const mode = {value: 'individual'};
  create.querySelector = selector => { assert.equal(selector, '[name="mode"]:checked'); return mode; };
  const input = new Input('group_name');
  const field = new Element();
  field.querySelector = selector => { assert.equal(selector, 'input'); return input; };
  const createLabel = new Element();
  const nodes = {'el-create-form': create, 'el-group-name-field': field, 'el-create-label': createLabel};
  vm.runInNewContext(script, {document: {querySelector: () => null, getElementById: id => nodes[id] || null}, Intl});
  assert.equal(field.hidden, true); assert.equal(input.disabled, true); assert.equal(input.required, false);
  assert.equal(createLabel.textContent, 'Créer mon accès individuel');
  mode.value = 'group'; create.dispatch('change');
  assert.equal(field.hidden, false); assert.equal(input.disabled, false); assert.equal(input.required, true);
  assert.equal(createLabel.textContent, 'Créer mon groupe');
});

function bootDashboard() {
  const card = (name, states, people = []) => {
    const result = new Element({dataset: {search: name, states}});
    result.people = people.map(([name, email]) => new Element({dataset: {personSearch: name + ' ' + email, personName: name}}));
    result.matches = new Element();
    result.querySelectorAll = selector => { assert.equal(selector, '[data-person-search]'); return result.people; };
    result.querySelector = selector => { assert.equal(selector, '[data-el-matches]'); return result.matches; };
    return result;
  };
  const cards = [
    card('APS septembre 2026 aps', 'draft active', [['Élodie Martin', 'elodie@example.fr']]),
    card('VTC novembre 2026 vtc', 'waiting', [['Marie Dupont', 'marie@example.fr']]),
    card('APS décembre 2026 aps', 'active', [['Jean Durand', 'jean@example.fr']]),
  ];
  const search = new Input('q');
  const filter = new Input('state', 'all');
  const links = ['all', 'draft', 'waiting', 'active'].map(state => new Element({dataset: {elState: state}}));
  const nodes = {'#el-search': search, '#el-filter': filter, '#el-filter-form': new Element(), '#el-clear-search': new Element(), '#el-reset-filters': new Element(), '#el-results-count': new Element(), '#el-no-results': new Element()};
  const dashboard = new Element();
  dashboard.querySelector = selector => nodes[selector] || null;
  dashboard.querySelectorAll = selector => selector === '[data-el-group]' ? cards : selector === '[data-el-state]' ? links : [];
  const document = {querySelector: selector => selector === '[data-el-dashboard]' ? dashboard : null, getElementById: () => null};
  const window = new Element({location: {href: 'https://example.fr/admin/organisme/e-learning'}});
  window.history = {replaceState: (_state, _title, url) => { window.lastUrl = url; }};
  vm.runInNewContext(script, {document, window, Intl, URL}, {filename: 'elearning-orders.js'});
  return {cards, links, nodes, search, filter, window};
}

test('dashboard metric cards filter results, update selected state and preserve clickable URL fallback', () => {
  const page = bootDashboard();
  assert.equal(page.nodes['#el-results-count'].textContent, '3 résultats');
  const active = page.links.find(link => link.dataset.elState === 'active');
  assert.equal(active.dispatch('click').defaultPrevented, true);
  assert.equal(page.filter.value, 'active');
  assert.equal(page.cards[0].hidden, false);
  assert.equal(page.cards[1].hidden, true);
  assert.equal(page.cards[2].hidden, false);
  assert.equal(active.attributes['aria-current'], 'true');
  assert.equal(active.classList.contains('is-selected'), true);
  assert.match(page.nodes['#el-results-count'].textContent, /^2 résultats · Accès activés$/);
  assert.match(page.window.lastUrl, /state=active/);
  assert.equal(active.dispatch('click', {ctrlKey: true}).defaultPrevented, false);
  page.links[0].dispatch('click');
  assert.ok(page.cards.every(card => !card.hidden));
  assert.equal(active.attributes['aria-current'], undefined);
});

test('dashboard search finds groups or people, accents, reversed names and e-mails', () => {
  const page = bootDashboard();
  page.search.value = 'septembre'; page.search.dispatch('input');
  assert.deepEqual(page.cards.map(card => card.hidden), [false, true, true]);
  page.search.value = 'martin elodie'; page.search.dispatch('input');
  assert.deepEqual(page.cards.map(card => card.hidden), [false, true, true]);
  assert.equal(page.cards[0].matches.hidden, false);
  assert.equal(page.cards[0].matches.textContent, 'Stagiaire : Élodie Martin');
  page.search.value = 'marie@example.fr'; page.search.dispatch('input');
  assert.deepEqual(page.cards.map(card => card.hidden), [true, false, true]);
  assert.match(page.window.lastUrl, /q=marie%40example.fr/);
  page.links.find(link => link.dataset.elState === 'active').dispatch('click');
  assert.equal(page.nodes['#el-no-results'].hidden, false);
  assert.match(page.nodes['#el-results-count'].textContent, /^0 résultats/);
  assert.equal(page.nodes['#el-reset-filters'].hidden, false);
  page.nodes['#el-reset-filters'].dispatch('click');
  assert.equal(page.search.value, '');
  assert.equal(page.filter.value, 'all');
  assert.ok(page.cards.every(card => !card.hidden));
  assert.equal(page.nodes['#el-reset-filters'].hidden, true);
});

test('search form and clear button work without losing the selected state', () => {
  const page = bootDashboard();
  page.filter.value = 'waiting'; page.filter.dispatch('change');
  page.search.value = 'introuvable';
  const submit = page.nodes['#el-filter-form'].dispatch('submit');
  assert.equal(submit.defaultPrevented, true);
  assert.equal(page.nodes['#el-no-results'].hidden, false);
  page.nodes['#el-clear-search'].dispatch('click');
  assert.equal(page.search.value, '');
  assert.equal(page.filter.value, 'waiting');
  assert.equal(page.cards[1].hidden, false);
  assert.equal(page.nodes['#el-no-results'].hidden, true);
  assert.equal(page.nodes['#el-clear-search'].hidden, true);
});
