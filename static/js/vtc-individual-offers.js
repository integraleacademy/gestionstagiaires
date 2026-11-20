/* Individual VTC package selection; other training types never load this file. */
(() => {
  "use strict";
  const panel = document.getElementById("vtcIndividualOffer");
  const practice = document.getElementById("vtcPracticeOnly");
  const vehicle = document.getElementById("vtcVehicleOnly");
  const status = document.getElementById("vtcIndividualOfferStatus");
  if (!panel || !practice || !vehicle) return;
  let current = panel.dataset.currentOffer || "full";
  let saving = false;
  const draw = offer => {
    practice.checked = offer === "practice";
    vehicle.checked = offer === "vehicle";
  };
  const message = (text, error = false) => {
    if (!status) return;
    status.textContent = text;
    status.style.color = error ? "#b91c1c" : "#475569";
  };
  const select = async offer => {
    if (saving) return;
    saving = true;
    const previous = current;
    draw(offer);
    practice.disabled = true;
    vehicle.disabled = true;
    message("Enregistrement de la formule VTC…");
    try {
      const response = await fetch(panel.dataset.updateUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({offer}),
      });
      const data = await response.json();
      if (!response.ok || data.ok !== true)
        throw new Error(data.error || "La formule VTC n'a pas été sauvegardée.");
      current = data.offer;
      draw(current);
      message("Formule enregistrée. Mise à jour de la convention, du tarif et des automatisations…");
      // Re-render the PDF actions and the financing panel on the same record.
      window.location.reload();
    } catch (error) {
      draw(previous);
      message(error.message || "Erreur d'enregistrement.", true);
    } finally {
      saving = false;
      const readOnly = panel.dataset.readOnly === "1";
      practice.disabled = readOnly;
      vehicle.disabled = readOnly;
    }
  };
  practice.addEventListener("change", () => select(practice.checked ? "practice" : "full"));
  vehicle.addEventListener("change", () => select(vehicle.checked ? "vehicle" : "full"));
  draw(current);
})();
