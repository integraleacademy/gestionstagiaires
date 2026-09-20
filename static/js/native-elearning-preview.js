(() => {
  "use strict";

  const configNode = document.getElementById("nativePreviewConfig");
  if (!configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent || "{}"); } catch (_error) { return; }

  // This reader intentionally has no learner token, clock or tracking calls.
  const button = document.getElementById("nativePreviewAnswerButton");
  const form = document.getElementById("nativeQuestionForm");
  const feedback = document.getElementById("nativeAnswerFeedback");

  function collectAnswer() {
    if (["single_choice", "multiple_choice", "statement"].includes(config.questionType)) {
      const selected = Array.from(form.querySelectorAll('input[name="answer"]:checked'), (input) => input.value);
      if (!selected.length) throw new Error("Sélectionnez au moins une réponse.");
      return { selected };
    }
    if (config.questionType === "matching") {
      const selected = Array.from(form.querySelectorAll("[data-match-index]"), (select) => select.value);
      if (!selected.length || selected.some((value) => !value)) throw new Error("Réalisez toutes les associations.");
      return { selected };
    }
    if (config.questionType === "fill_blank") {
      const fields = Array.from(form.querySelectorAll(".native-elearning-blank[data-group-id]"));
      if (!fields.length || fields.some((field) => !field.value.trim())) throw new Error("Complétez toutes les zones.");
      return { groups: Object.fromEntries(fields.map((field) => [field.dataset.groupId, field.value])) };
    }
    throw new Error("Ce format de question doit être vérifié par l’équipe pédagogique.");
  }

  function showFeedback(message, correct) {
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.add("is-visible");
    feedback.classList.toggle("is-correct", correct);
    feedback.classList.toggle("is-incorrect", !correct);
  }

  async function testAnswer() {
    if (!button || !form || button.disabled) return;
    button.disabled = true;
    button.textContent = "Vérification…";
    try {
      const answer = collectAnswer();
      const response = await fetch(config.answerUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/json", "X-Elearning-CSRF": config.csrfToken },
        body: JSON.stringify({ answer }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error([401, 403].includes(response.status)
          ? "Votre accès a expiré ou ne permet pas cette action. Rechargez la page."
          : result.error || "Impossible de vérifier cette réponse. Réessayez.");
      }
      showFeedback(result.correct ? "Bonne réponse ! Aucun résultat n’est enregistré."
        : "Réponse incorrecte. Vous pouvez modifier votre réponse et réessayer.", Boolean(result.correct));
    } catch (error) {
      showFeedback(error.message || "Impossible de vérifier cette réponse.", false);
    } finally {
      button.disabled = false;
      button.textContent = "Tester ma réponse";
    }
  }

  button?.addEventListener("click", testAnswer);
  form?.addEventListener("submit", (event) => { event.preventDefault(); testAnswer(); });
  form?.addEventListener("input", () => feedback?.classList.remove("is-visible"));
  form?.addEventListener("change", () => feedback?.classList.remove("is-visible"));

  function makeToggle(element, className, role, attribute) {
    element.tabIndex = 0;
    element.setAttribute("role", role);
    element.setAttribute(attribute, "false");
    const toggle = () => element.setAttribute(attribute, String(element.classList.toggle(className)));
    element.addEventListener("click", toggle);
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); }
    });
  }
  document.querySelectorAll(".native-block--checklistitem,.native-block--howtoitem")
    .forEach((item) => makeToggle(item, "is-checked", "checkbox", "aria-checked"));
  document.querySelectorAll(".flip-card-wrapper")
    .forEach((card) => makeToggle(card, "is-flipped", "button", "aria-pressed"));

  const menuButton = document.getElementById("nativeMenuButton");
  const sidebar = document.getElementById("nativeSidebar");
  const overlay = document.getElementById("nativeSidebarOverlay");
  function setMenu(open) {
    sidebar?.classList.toggle("is-open", open);
    overlay?.classList.toggle("is-open", open);
    menuButton?.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
  }
  menuButton?.addEventListener("click", () => setMenu(!sidebar?.classList.contains("is-open")));
  overlay?.addEventListener("click", () => setMenu(false));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") setMenu(false); });
})();
