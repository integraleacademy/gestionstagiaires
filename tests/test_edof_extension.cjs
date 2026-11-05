const assert = require("node:assert/strict");
const test = require("node:test");
const core = require("../browser_extensions/edof_test/core.js");
const id = "123456789012";
const url = `https://of.moncompteformation.gouv.fr/edof-api/v1/api/private/siret/${core.SIRET}/organisms/current/registration-folders/${id}`;

test("observes only the selected legitimate read response", () => {
  assert.equal(core.matches(url, "GET", 200, id), true);
  for (const [u, method, status, expected] of [
    [url, "POST", 200, id], [url, "GET", 401, id], [url, "GET", 200, "555555555555"],
    [url.replace("https:", "http:"), "GET", 200, id], [url + "?secret=x", "GET", 200, id],
    [url.replace(core.SIRET, "00000000000000"), "GET", 200, id],
    [url.replace(".gouv.fr", ".gouv.fr.evil.example"), "GET", 200, id],
    [url.replace("https://", "https://user:pass@"), "GET", 200, id],
  ]) assert.equal(core.matches(u, method, status, expected), false);
});
test("sends only selected fields, without authentication or unrelated personal data", () => {
  const payload = core.sanitize({id, title: "0", Authorization: "prohibited", cookie: "prohibited", history: ["private"],
    attendee: {firstName: "Camille", email: "demo@example.invalid", birthDate: "01/01/2000", address: {street: "private"}, phoneNumber: "private"},
    trainingActionInfo: {title: "Intitulé réel", totalIncl: 1600, vat: 1600, solicitations: ["private"]}}, id);
  assert.equal(payload.folder.trainingActionInfo.title, "Intitulé réel");
  assert.equal(payload.folder.title, undefined);
  assert.equal(payload.folder.trainingActionInfo.vat, undefined);
  assert.equal(JSON.stringify(payload).includes("prohibited"), false);
  assert.equal(JSON.stringify(payload).includes("private"), false);
  assert.equal(JSON.stringify(payload).includes("2000"), false);
  assert.throws(() => core.sanitize({id: "555555555555"}, id));
});
test("pairing codes bind a folder and do not accept arbitrary URLs", () => {
  assert.equal(core.parseKey(`edoftest1.${id}.${"a".repeat(43)}`).id, id);
  assert.equal(core.parseKey("https://other.example"), null);
  assert.equal(core.parseKey(`edoftest1.${id}.short`), null);
});
