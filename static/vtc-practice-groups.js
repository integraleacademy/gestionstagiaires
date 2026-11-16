function readVtcPracticeSlots(rows) {
  return Array.from(rows, row => Object.fromEntries(
    Array.from(row.querySelectorAll("input"), input => [input.name, input.value])
  ));
}

// The session editor is shared. Reset the VTC controls every time it opens.
const vtcPracticeEditor = (() => {
  const panel = document.getElementById("vtcPracticeGroups");
  if (!panel) return;
  const toggle = document.getElementById("vtcPracticeSplit");
  const fields = document.getElementById("vtcPracticeSlots");
  const rows = Array.from(fields.querySelectorAll("[data-slot]"));
  let previouslySplit = false;

  function showFields() {
    fields.hidden = !toggle.checked;
  }
  toggle.addEventListener("change", showFields);

  return {
    open(button) {
      const slots = JSON.parse(button.dataset.vtcSlots || "[]");
      previouslySplit = slots.length === 2;
      panel.hidden = !button.hasAttribute("data-vtc-slots");
      toggle.checked = previouslySplit;
      document.getElementById("vtcPracticeHint").textContent = previouslySplit
        ? "Les groupes sont enregistrés. Vous pouvez modifier leurs horaires."
        : "Les stagiaires seront répartis automatiquement en deux groupes équilibrés.";
      rows.forEach((row, index) => {
        const slot = slots[index];
        for (const input of row.querySelectorAll("input")) {
          input.value = slot?.[input.name] ?? input.defaultValue;
        }
      });
      showFields();
    },
    payload() {
      if (panel.hidden || (!toggle.checked && !previouslySplit)) return {};
      if (!toggle.checked) return {vtc_practice_slots: null};
      return {vtc_practice_slots: readVtcPracticeSlots(rows)};
    }
  };
})();

document.getElementById("vtcRosterForm")?.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const error = form.querySelector('[role="alert"]');
  submit.disabled = true;
  error.textContent = "";
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        practice_training_date: form.elements.practice_training_date.value,
        vtc_practice_slots: readVtcPracticeSlots(form.querySelectorAll("[data-slot]"))
      })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      error.textContent = result.error || "Impossible d’enregistrer les créneaux.";
      return;
    }
    window.location.reload();
  } catch {
    error.textContent = "Impossible d’enregistrer les créneaux. Veuillez réessayer.";
  } finally {
    submit.disabled = false;
  }
});

document.addEventListener("click", async event => {
  const badge = event.target.closest("button[data-move-url]");
  if (!badge || badge.disabled) return;
  badge.disabled = true;
  const status = badge.nextElementSibling;
  const group = Number(badge.dataset.group) === 1 ? 2 : 1;
  status.textContent = "Changement de groupe…";
  try {
    const response = await fetch(badge.dataset.moveUrl, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({group})
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Error(result.error || "Le groupe n’a pas été modifié.");
    location.reload();
  } catch (error) {
    badge.disabled = false;
    status.textContent = error.message || "Le groupe n’a pas été modifié.";
  }
});
