const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const crypto = require("node:crypto");

const source = fs.readFileSync("static/manual-docs-reminder.js", "utf8");
const historySource = fs.readFileSync("static/trainee-email-history.js", "utf8");
const markup = fs.readFileSync("templates/_manual_docs_reminder.html", "utf8");
const flush = () => new Promise(setImmediate);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

class Element {
  constructor() {
    this.handlers = new Map(); this.dataset = {}; this.children = [];
    this.disabled = false; this.hidden = false; this.textContent = "";
    this.classList = { contains: (name) => (this.className || "").split(" ").includes(name) };
  }
  addEventListener(name, handler) { this.handlers.set(name, [...(this.handlers.get(name) || []), handler]); }
  removeEventListener(name, handler) { this.handlers.set(name, (this.handlers.get(name) || []).filter((h) => h !== handler)); }
  emit(name, event = {}) { return Promise.all((this.handlers.get(name) || []).map((handler) => handler(event))); }
  dispatchEvent(event) { this.emit(event.type, event); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit("close"); }
  contains(node) { return this.children.includes(node); }
}

function setup({ loadPreview, sendResult } = {}) {
  const requests = [], events = [];
  const elements = Object.fromEntries([...markup.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const get = (name) => elements[`manualReminder${name}`];
  const button = new Element();
  button.textContent = "RELANCE MANUELLE";
  button.dataset.previewUrl = "/preview";
  const window = new Element(), document = new Element();
  document.getElementById = (id) => elements[id];
  document.querySelectorAll = () => [button];
  document.createElement = () => new Element();
  document.addEventListener("manual-docs-reminder-updated", (event) => events.push(event.detail));
  const preview = {
    csrf: "csrf-test", eligible: [
      { trainee_id: "T1", name: "Alice", email: "alice@example.test", phone: "0600000000", send_url: "/send/T1", preview_token: "p1" },
      { trainee_id: "T2", name: "Bob", email: "bob@example.test", phone: "", send_url: "/send/T2", preview_token: "p2" },
    ], skipped: [{ name: "Camille", reason: "Inscription annulée" }],
  };
  vm.runInNewContext(source, {
    document, window, crypto,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const body = url === "/preview" ? await (loadPreview ? loadPreview(preview) : preview)
        : await (sendResult ? sendResult(url) : { ok: url === "/send/T1", email_status: "ACCEPTE", sms_status: url === "/send/T1" ? "ACCEPTE" : "ABSENT" });
      return { ok: true, json: async () => body };
    },
    // No native alert or confirm: every state must remain in the application dialog.
  });
  return { button, requests, events, get, window, document, dialog: elements.manualDocsReminderModal };
}

test("opens immediately, shows progress during delivery, prevents duplicates, and retains separate results", async () => {
  const previewGate = deferred(), deliveryGate = deferred();
  const ui = setup({ loadPreview: async (preview) => { await previewGate.promise; return preview; },
    sendResult: async (url) => { await deliveryGate.promise; return { email_status: "ACCEPTE", sms_status: url === "/send/T1" ? "ACCEPTE" : "ABSENT" }; } });
  const opening = ui.button.emit("click");
  assert.equal(ui.dialog.open, true);
  assert.match(ui.get("Title").textContent, /Préparation/);
  await ui.button.emit("click");
  assert.equal(ui.requests.length, 1);
  previewGate.resolve();
  await opening;
  assert.equal(ui.get("Recipients").children.length, 2);
  assert.match(ui.get("SkippedList").children[0].textContent, /Camille : Inscription annulée/);
  assert.equal(ui.requests.length, 1); // Preview never sends.
  const sending = ui.get("Send").emit("click");
  await ui.get("Send").emit("click");
  assert.match(ui.get("Title").textContent, /en cours de transmission/);
  assert.equal(ui.get("Close").disabled, true);
  assert.equal(ui.get("Progress").value, 0);
  assert.equal(ui.get("Recipients").children[0].dataset.state, "sending");
  let cancelled = false;
  await ui.dialog.emit("cancel", { preventDefault() { cancelled = true; } });
  assert.equal(cancelled, true);
  await ui.get("Close").emit("click");
  assert.equal(ui.dialog.open, true);
  const leave = { preventDefault() { this.prevented = true; } };
  await ui.window.emit("beforeunload", leave);
  assert.equal(leave.prevented, true);
  deliveryGate.resolve();
  await sending;
  assert.deepEqual(ui.requests.map((request) => request.url), ["/preview", "/send/T1", "/send/T2"]);
  const bodies = ui.requests.slice(1).map((request) => JSON.parse(request.options.body));
  assert.deepEqual(bodies.map((body) => body.preview_token), ["p1", "p2"]);
  assert.ok(bodies.every((body) => body.csrf === "csrf-test" && body.request_id.length === 36));
  assert.notEqual(bodies[0].request_id, bodies[1].request_id);
  assert.match(ui.get("Summary").textContent, /2 e-mail\(s\) transmis · 1 SMS transmis · 1 dossier/);
  assert.equal(ui.get("Recipients").children[0].dataset.state, "success");
  assert.equal(ui.get("Recipients").children[1].dataset.state, "warning");
  assert.equal(ui.get("Progress").value, 2);
  assert.equal(ui.get("Close").disabled, false);
  assert.equal(ui.window.handlers.get("beforeunload").length, 0);
  assert.deepEqual(ui.events.map((event) => event.traineeId), ["T1", "T2"]);
  await ui.get("Close").emit("click");
  assert.equal(ui.dialog.open, false);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.button.textContent, "RELANCE MANUELLE");
});

test("cancelling preview sends nothing and ignores its late response", async () => {
  const gate = deferred();
  const ui = setup({ loadPreview: async (preview) => { await gate.promise; return preview; } });
  const opening = ui.button.emit("click");
  await ui.get("Close").emit("click");
  gate.resolve();
  await opening;
  assert.equal(ui.dialog.open, false);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.get("Send").hidden, true);
  assert.deepEqual(ui.requests.map((request) => request.url), ["/preview"]);
});

test("excluded dossiers and preparation failures remain visible without sending", async () => {
  const ui = setup({ loadPreview: (preview) => ({...preview, eligible: []}) });
  await ui.button.emit("click");
  assert.match(ui.get("Title").textContent, /Aucun stagiaire/);
  assert.equal(ui.get("Send").hidden, true);
  assert.equal(ui.get("Skipped").hidden, false);
  assert.equal(ui.requests.length, 1);
  const failed = setup({ loadPreview: () => { throw new Error("Service indisponible"); } });
  await failed.button.emit("click");
  assert.match(failed.get("Description").textContent, /Service indisponible/);
  assert.equal(failed.get("Close").disabled, false);
});

test("lost responses are not presented as successful and do not stop the next dossier", async () => {
  const ui = setup({ sendResult: (url) => {
    if (url === "/send/T1") throw new Error("Connexion interrompue");
    return {email_status: "ACCEPTE", sms_status: "ABSENT"};
  } });
  await ui.button.emit("click");
  await ui.get("Send").emit("click");
  const first = ui.get("Recipients").children[0];
  assert.equal(first.children[1].children[0].dataset.status, "INCONNU");
  assert.match(first.children[2].textContent, /Vérifiez l’historique/);
  assert.match(ui.get("Summary").textContent, /1 e-mail\(s\) transmis · 0 SMS transmis/);
  assert.equal(ui.get("Close").disabled, false);
  assert.equal(ui.requests.length, 3);
});

test("history refreshes after the matching reminder and preview works on newly inserted entries", async () => {
  const ids = ["traineeEmailHistoryContent", "traineeEmailHistoryStatus", "emailHtmlPreviewFrame", "emailHtmlPreviewMeta"];
  const elements = Object.fromEntries(ids.map((id) => [id, new Element()]));
  const content = elements.traineeEmailHistoryContent;
  content.dataset = {historyUrl: "/history", traineeId: "T1"};
  const document = new Element();
  document.getElementById = (id) => elements[id];
  const opened = [], requests = [];
  const window = {openModal: (id) => opened.push(id)};
  vm.runInNewContext(historySource, { document, window, fetch: async (url, options) => {
    requests.push({url, options});
    return {ok: true, text: async () => "<div>Nouvelle relance</div>"};
  } });
  await document.emit("manual-docs-reminder-updated", {detail: {traineeId: "T2"}});
  assert.equal(requests.length, 0);
  await document.emit("manual-docs-reminder-updated", {detail: {traineeId: "T1"}});
  await flush();
  assert.equal(content.innerHTML, "<div>Nouvelle relance</div>");
  assert.equal(requests[0].options.cache, "no-store");
  assert.equal(content["aria-busy"], "false");
  const button = new Element();
  button.dataset = {emailSubject: "Relance", emailDate: "14/09/2026 à 16h12", emailHtml: "<h1>Mail transmis</h1>"};
  content.append(button);
  await content.emit("click", {target: {closest: () => button}});
  assert.equal(elements.emailHtmlPreviewFrame.srcdoc, button.dataset.emailHtml);
  assert.match(elements.emailHtmlPreviewMeta.textContent, /16h12/);
  assert.deepEqual(opened, ["emailHtmlPreviewModal"]);
});
