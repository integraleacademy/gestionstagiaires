/* Choose one limited VTC package. Clearing it restores the complete course. */
(() => {
  "use strict";
  const panel = document.getElementById("vtcIndividualOffer");
  if (!panel) return;
  const options = panel.querySelector("fieldset");
  if (options.disabled) return;
  const status = document.getElementById("vtcIndividualOfferStatus");
  const inputs = [...options.querySelectorAll("input[type=checkbox]")];
  const draw = offer => inputs.forEach(input => { input.checked = input.value === offer; });

  options.addEventListener("change", async event => {
    const input = event.target;
    if (!inputs.includes(input) || options.disabled) return;
    const offer = input.checked ? input.value : "full";
    draw(offer);
    options.disabled = true;
    status.classList.remove("is-error");
    status.textContent = "Enregistrement de la formule…";
    try {
      const response = await fetch(panel.dataset.updateUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({offer}),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "La formule n’a pas pu être enregistrée.");
      window.location.reload();
    } catch (error) {
      draw(panel.dataset.currentOffer);
      status.classList.add("is-error");
      status.textContent = error.message || "La formule n’a pas pu être enregistrée.";
      options.disabled = false;
    }
  });
})();
