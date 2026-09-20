const { JSDOM } = require("jsdom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/js/native-elearning-preview.js"), "utf8");

async function checkQuestion(questionType, fields, fill, expected) {
  const config = { questionType, csrfToken: "csrf", answerUrl: "/api/admin/preview/answer?version=pinned" };
  const dom = new JSDOM(`<button id="nativeMenuButton" aria-expanded="false"></button>
    <aside id="nativeSidebar"></aside><button id="nativeSidebarOverlay"></button>
    <div class="flip-card-wrapper"></div><div class="native-block--checklistitem"></div>
    <form id="nativeQuestionForm">${fields}</form><div id="nativeAnswerFeedback"></div>
    <button id="nativePreviewAnswerButton">Tester ma réponse</button>
    <script id="nativePreviewConfig" type="application/json">${JSON.stringify(config)}</script>`,
    { runScripts: "outside-only", url: "https://test.invalid/" });
  const { window } = dom, { document } = window;
  const requests = [];
  let correct = false;
  window.setInterval = () => { throw new Error("Preview must not start a clock or heartbeat"); };
  window.fetch = async (url, options) => {
    requests.push({ url, options, body: JSON.parse(options.body) });
    return { ok: true, json: async () => ({ ok: true, correct }) };
  };
  const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
  try {
    window.eval(source);
    window.dispatchEvent(new window.Event("focus"));
    window.dispatchEvent(new window.Event("pagehide"));
    document.dispatchEvent(new window.Event("visibilitychange"));
    assert.equal(requests.length, 0, "opening or leaving a preview does not track activity");
    const button = document.getElementById("nativePreviewAnswerButton");
    button.click();
    await settle();
    assert.equal(requests.length, 0, "empty answers are not submitted");
    fill(document);
    button.click();
    await settle();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, config.answerUrl);
    assert.equal(requests[0].options.headers["X-Elearning-CSRF"], "csrf");
    assert.deepEqual(requests[0].body, { answer: expected });
    assert.match(document.getElementById("nativeAnswerFeedback").textContent, /incorrecte/);
    assert.equal(document.querySelectorAll("input:disabled,select:disabled").length, 0);
    correct = true;
    button.click();
    await settle();
    assert.equal(requests.length, 2, "the same question can be tested again");
    assert.match(document.getElementById("nativeAnswerFeedback").textContent, /Bonne réponse/);
    window.fetch = async () => { throw new Error("Connexion interrompue"); };
    button.click();
    await settle();
    assert.equal(button.disabled, false);
    assert.match(document.getElementById("nativeAnswerFeedback").textContent, /Connexion interrompue/);

    const menu = document.getElementById("nativeMenuButton");
    menu.click();
    assert.equal(menu.getAttribute("aria-expanded"), "true");
    window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
    assert.equal(menu.getAttribute("aria-expanded"), "false");
    document.querySelector(".flip-card-wrapper").click();
    assert.equal(document.querySelector(".flip-card-wrapper").getAttribute("aria-pressed"), "true");
    document.querySelector(".native-block--checklistitem").dispatchEvent(new window.KeyboardEvent("keydown", { key: " " }));
    assert.equal(document.querySelector(".native-block--checklistitem").getAttribute("aria-checked"), "true");
  } finally { window.close(); }
}

(async () => {
  for (const type of ["single_choice", "multiple_choice", "statement"]) {
    await checkQuestion(type, '<input type="checkbox" name="answer" value="a">',
      (document) => { document.querySelector("input").checked = true; }, { selected: ["a"] });
  }
  await checkQuestion("matching", '<select data-match-index="0"><option value=""></option><option value="a">A</option></select>',
    (document) => { document.querySelector("select").value = "a"; }, { selected: ["a"] });
  await checkQuestion("fill_blank", '<input class="native-elearning-blank" data-group-id="g">',
    (document) => { document.querySelector("input").value = "texte"; }, { groups: { g: "texte" } });
  console.log("PASS: preview has no tracking; all question formats, repeat attempts, errors, menu and interactive content work.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
