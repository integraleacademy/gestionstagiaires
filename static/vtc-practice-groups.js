// The session editor is shared. Reset the VTC controls every time it opens.
const vtcPracticeEditor = (() => {
  const panel = document.getElementById("vtcPracticeGroups");
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
      return {vtc_practice_slots: rows.map(row => Object.fromEntries(
        Array.from(row.querySelectorAll("input"), input => [input.name, input.value])
      ))};
    }
  };
})();
