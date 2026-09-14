const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const crypto = require("node:crypto");

const source = fs.readFileSync("static/manual-docs-reminder.js", "utf8");

function setup({ confirmed = true } = {}) {
  const requests = [], alerts = [];
  const button = {
    disabled: false, textContent: "RELANCE MANUELLE", dataset: { previewUrl: "/preview" },
    classList: { contains: () => false },
    addEventListener(name, handler) { this.click = handler; },
  };
  vm.runInNewContext(source, {
    document: { querySelectorAll: () => [button] }, crypto,
    confirm: () => confirmed, alert: (message) => alerts.push(message),
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => url === "/preview" ? {
        csrf: "csrf-test", eligible: [
          { name: "Alice", email: "alice@example.test", phone: "0600000000", send_url: "/send/T1", preview_token: "p1" },
          { name: "Bob", email: "bob@example.test", phone: "", send_url: "/send/T2", preview_token: "p2" },
        ], skipped: [{ name: "Camille", reason: "Inscription annulée" }],
      } : { ok: url === "/send/T1", email_status: "ACCEPTE", sms_status: url === "/send/T1" ? "ACCEPTE" : "ABSENT" } };
    },
  });
  return { button, requests, alerts };
}

test("one click sends each eligible dossier once, with its own preview token", async () => {
  const { button, requests, alerts } = setup();
  const firstClick = button.click();
  await button.click(); // An immediate double click must not start a second batch.
  await firstClick;
  assert.deepEqual(requests.map((request) => request.url), ["/preview", "/send/T1", "/send/T2"]);
  const bodies = requests.slice(1).map((request) => JSON.parse(request.options.body));
  assert.deepEqual(bodies.map((body) => body.preview_token), ["p1", "p2"]);
  assert.ok(bodies.every((body) => body.csrf === "csrf-test" && body.request_id.length === 36));
  assert.notEqual(bodies[0].request_id, bodies[1].request_id);
  assert.match(alerts[0], /Alice — E-mail : accepté ; SMS : accepté/);
  assert.match(alerts[0], /Bob — E-mail : accepté ; SMS : coordonnée manquante/);
  assert.match(alerts[0], /Camille : Inscription annulée/);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "RELANCE MANUELLE");
});

test("cancelling the batch leaves both notification channels untouched", async () => {
  const { button, requests, alerts } = setup({ confirmed: false });
  await button.click();
  assert.deepEqual(requests.map((request) => request.url), ["/preview"]);
  assert.equal(alerts.length, 0);
  assert.equal(button.disabled, false);
});
