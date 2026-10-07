const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const template = fs.readFileSync(path.join(__dirname, '../templates/admin_afc_candidate_sheet.html'), 'utf8');
const start = template.indexOf("cnapsPriority.addEventListener('change'");
const end = template.indexOf('\nif(btnRefreshCnaps)', start);
assert.ok(start >= 0 && end > start);
const listenerSource = template.slice(start, end);

for (const decision of ['', 'NON RETENU', 'RETENU']) {
  test(`checking CNAPS preserves the chosen decision ${decision || '(pending)'} in the saved form`, async () => {
    let onChange;
    let savedDecision;
    const selectedDecision = { value: decision };
    const context = {
      cnapsPriority: { checked: true, addEventListener: (_, callback) => { onChange = callback; } },
      cnapsStatusBadge: { textContent: 'INCONNU', dataset: { cnapsHistory: '[]' } },
      decision: selectedDecision,
      renderAfcCnapsStatuses() {},
      refreshUI() {},
      applyCnapsBadge() {},
      async saveCandidate() { savedDecision = selectedDecision.value; return true; },
    };
    vm.runInNewContext(listenerSource, context);
    await onChange();
    assert.equal(selectedDecision.value, decision);
    assert.equal(savedDecision, decision);
  });
}
