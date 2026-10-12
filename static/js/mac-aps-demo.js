/* The public specimen stays local to this page: no tracking or persistence. */
(() => {
  "use strict";
  const quiz = document.querySelector("[data-mac-demo-quiz]");
  if (quiz) {
    const questions = JSON.parse(document.getElementById("mac-demo-answers").textContent);
    const result = quiz.querySelector("[data-mac-demo-result]");
    const fields = [...quiz.querySelectorAll("[data-question-id]")];
    quiz.querySelector("[data-mac-demo-check]").addEventListener("click", () => {
      const missing = fields.find(field => !field.querySelector("input:checked"));
      result.hidden = false;
      if (missing) {
        result.textContent = "Choisissez une réponse à chacune des trois questions avant de voir la correction.";
        missing.querySelector("input").focus();
        return;
      }
      let score = 0;
      fields.forEach(field => {
        const question = questions.find(item => item.id === field.dataset.questionId);
        const correct = field.querySelector("input:checked").value === question.answer;
        const feedback = field.querySelector("[data-question-feedback]");
        if (correct) score += 1;
        feedback.classList.toggle("correct", correct);
        feedback.textContent = (correct ? "Bonne réponse. " : "À revoir. ") + question.explanation;
        feedback.hidden = false;
      });
      result.textContent = `${score} réponse${score === 1 ? "" : "s"} correcte${score === 1 ? "" : "s"} sur 3. Lisez les explications pour consolider vos repères. Ce résultat de démonstration n’est pas enregistré.`;
    });
    quiz.querySelector("[data-mac-demo-reset]").addEventListener("click", () => {
      quiz.querySelectorAll("input").forEach(input => { input.checked = false; });
      quiz.querySelectorAll("[data-question-feedback]").forEach(feedback => {
        feedback.hidden = true;
        feedback.textContent = "";
        feedback.classList.remove("correct");
      });
      result.hidden = true;
      result.textContent = "";
      quiz.querySelector("input").focus();
    });
  }
  document.querySelectorAll(".mac-demo-video").forEach(video => {
    video.addEventListener("loadedmetadata", () => {
      // French captions are already in the image; retain the accessible track.
      [...video.textTracks].forEach(track => { track.mode = "hidden"; });
    });
  });
})();
