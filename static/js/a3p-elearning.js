/* Local, repeatable case practice; no score, personal data or certification record. */
(() => {
  "use strict";
  document.querySelectorAll("[data-a3p-decision]").forEach(root => {
    const steps = Array.from(root.querySelectorAll(".a3p-decision-step"));
    steps.forEach((step, index) => {
      const feedback = step.querySelector(".a3p-decision-feedback");
      const next = step.querySelector("[data-next]");
      step.querySelectorAll("[data-choice]").forEach(button => {
        button.addEventListener("click", () => {
          const correct = button.dataset.choice === step.dataset.answer;
          step.querySelectorAll("[data-choice]").forEach(other => {
            other.classList.remove("is-correct", "is-incorrect");
            other.setAttribute("aria-pressed", String(other === button));
          });
          button.classList.add(correct ? "is-correct" : "is-incorrect");
          feedback.textContent = (correct ? "Décision adaptée. " : "À reprendre. ") + feedback.dataset.explanation;
          next.hidden = !correct;
        });
      });
      next.addEventListener("click", () => {
        if (next.hidden) return;
        if (steps[index + 1]) {
          step.hidden = true;
          steps[index + 1].hidden = false;
          steps[index + 1].querySelector("[data-choice]").focus();
        } else {
          root.querySelector(".a3p-decision-done").hidden = false;
          next.hidden = true;
          const review = root.parentElement.querySelector(".a3p-case-feedback");
          review.open = true;
          review.querySelector("summary").focus();
        }
      });
    });
  });
})();
