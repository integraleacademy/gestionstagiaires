// Optional DOM interaction regression suite. Requires jsdom on NODE_PATH.
// NODE_PATH=/path/to/node_modules node tests/test_native_elearning_path_ui.cjs
const { JSDOM } = require("jsdom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const course = (id, title, sections = 2) => ({ course_id: id, course_version: "pinned-v1", title,
  sections: Array.from({ length: sections }, (_, i) => ({ id: `s${i + 1}`, title: `Séquence ${i + 1}`,
    activities: [{ title: `Activité ${i + 1}`, scored: false }] })) });
const config = {
  catalog: [course("first", "Cadre légal"), course("second", "Cadre pénal")],
  modules: [{ course_id: "first", course_version: "pinned-v1", section_ids: ["s1", "s2"], title: "" }],
  revision: "revision-1", csrfToken: "csrf-test", saveUrl: "/save", readOnly: false,
};
const dom = new JSDOM(`<!doctype html><div id="nativeModuleLibrary"></div>
  <div id="nativePathModules"></div><input id="nativeModuleSearch"><input id="nativePathTitle" value="Parcours APS">
  <div id="nativePathTotals"></div><button id="nativePathSave">Enregistrer</button><strong id="nativePathSaveState"></strong>
  <script id="nativePathConfig" type="application/json">${JSON.stringify(config)}</script>`, { runScripts: "outside-only", url: "https://test.invalid/" });
const { window } = dom;
const document = window.document;
let saved, conflict = false;
window.confirm = () => true;
window.fetch = async (url, options) => {
  assert.equal(url, "/save");
  assert.equal(options.headers["X-Elearning-CSRF"], "csrf-test");
  saved = JSON.parse(options.body);
  return { ok: !conflict, json: async () => conflict ? { ok: false, error: "Conflit de version" }
    : { ok: true, modules: saved.modules, revision: "revision-2" } };
};
window.eval(fs.readFileSync(path.join(__dirname, "../static/js/native-elearning-path.js"), "utf8"));
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const moduleCards = () => [...document.querySelectorAll("#nativePathModules > details")];
const click = (selector) => { const node = document.querySelector(selector); assert.ok(node, selector); node.click(); };
const input = (selector, value) => { const node = document.querySelector(selector); node.value = value; node.dispatchEvent(new window.Event("input")); };

(async () => {
  assert.equal(moduleCards().length, 1);
  assert.equal(document.querySelector(".np-library-item button").disabled, true);
  input("#nativeModuleSearch", "penal");
  assert.equal(document.querySelectorAll(".np-library-item").length, 1);
  click(".np-library-item button");
  assert.equal(moduleCards().length, 2);
  click('[aria-label="Monter le module 2"]');
  assert.equal(moduleCards()[0].querySelector("h3").textContent, "Cadre pénal");
  input('[data-duration="hours"]', "4");
  assert.equal(moduleCards()[0].querySelector(".np-duration-summary").textContent, "Durée obligatoire : 4 h 00 min");
  moduleCards()[0].open = true;
  await tick();
  click('[aria-label="Descendre la séquence Séquence 1"]');
  assert.equal(moduleCards()[0].querySelector(".np-check span").textContent, "1. Séquence 2");
  // Remove the first sequence from the selection (without deleting content).
  const check = moduleCards()[0].querySelector(".np-check input");
  check.checked = false;
  check.dispatchEvent(new window.Event("change"));
  assert.equal(document.querySelector("#nativePathTotals").textContent, "2 modules3 séquences3 activités4 h 00 min obligatoires");
  assert.equal(document.querySelector('[data-duration="hours"]').value, "4");
  input('[data-duration="minutes"]', "60");
  click("#nativePathSave"); await tick();
  assert.equal(saved, undefined);
  assert.match(document.querySelector("#nativePathSaveState").textContent, /Corrigez les durées/);
  input('[data-duration="minutes"]', "0");
  input("#nativePathTitle", "Formation complète");
  click("#nativePathSave");
  assert.equal(document.querySelector("#nativePathSave").disabled, true);
  await tick();
  assert.equal(saved.title, "Formation complète");
  assert.deepEqual(saved.modules.map((item) => item.course_id), ["second", "first"]);
  assert.deepEqual(saved.modules[0].section_ids, ["s1"]);
  assert.equal(saved.modules[0].course_version, "pinned-v1");
  assert.equal(saved.modules[0].required_minutes, 240);
  assert.equal(saved.modules[1].required_minutes, 0);
  assert.equal(document.querySelector("#nativePathSaveState").textContent, "Parcours enregistré pour cette session");
  // Subsequent saves carry the new revision, and errors never discard changes.
  conflict = true;
  input("#nativePathTitle", "Nouvelle composition");
  click("#nativePathSave"); await tick();
  assert.equal(saved.revision, "revision-2");
  assert.equal(document.querySelector("#nativePathSaveState").textContent, "Conflit de version");
  assert.equal(document.querySelector("#nativePathTitle").value, "Nouvelle composition");
  assert.equal(moduleCards().length, 2);
  // Module removal is only local until explicitly saved.
  moduleCards()[0].querySelector(".np-module-controls button:last-child").click();
  assert.equal(moduleCards().length, 1);
  assert.equal(document.querySelector("#nativePathTotals").textContent, "1 modules2 séquences2 activités0 h 00 min obligatoires");
  dom.window.close();
  console.log("PASS: search, composition, duration validation/persistence, save, pinned version, stale revision, removal.");
})().catch((error) => { console.error(error); process.exitCode = 1; dom.window.close(); });
