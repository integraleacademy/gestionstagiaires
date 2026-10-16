/* A local sample exercise. No tracking, writes, native tokens, or answer bank. */
(() => {
  "use strict";
  document.querySelectorAll("[data-demo-exercise]").forEach((exercise) => {
    const feedback = exercise.querySelector("[data-demo-feedback]");
    exercise.querySelector("[data-demo-check]").addEventListener("click", () => {
      const selected = exercise.querySelector('input[name="demo-answer"]:checked');
      feedback.hidden = false;
      feedback.classList.remove("success");
      if (!selected) {
        feedback.textContent = "Choisissez une réponse pour découvrir l’explication.";
        exercise.querySelector('input[name="demo-answer"]').focus();
        return;
      }
      if (selected.value === "explain") {
        feedback.classList.add("success");
        feedback.textContent = "Bonne réponse. Le client ne peut pas élargir vos pouvoirs par une simple demande. Vous maintenez la surveillance du site et rendez compte à votre responsable.";
      } else {
        feedback.textContent = "À revoir. Aucun incident ne justifie ici de suivre la personne ou d’abandonner le poste. Expliquez la limite de votre mission et prévenez votre responsable. Vous pouvez essayer une autre réponse.";
      }
    });
  });
})();
