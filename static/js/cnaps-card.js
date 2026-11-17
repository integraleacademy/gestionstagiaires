(function () {
  function checkedLabel(value) {
    if (!value) return "";
    const checked = new Date(value);
    if (Number.isNaN(checked.getTime())) return "";
    return "Dernière vérification le " + checked.toLocaleString("fr-FR", {
      dateStyle: "short", timeStyle: "short", timeZone: "Europe/Paris"
    });
  }

  function bind(box, render) {
    const button = box.querySelector("[data-card-pro-refresh]");
    const message = box.querySelector("[data-card-pro-message]");
    const checked = box.querySelector("[data-card-pro-date]");
    const saved = JSON.parse(box.dataset.cnapsSnapshot || "null");
    if (saved) render(saved);
    checked.textContent = checkedLabel(box.dataset.cnapsCheckedAt || saved?.checked_at);
    let pending;
    button.addEventListener("click", () => {
      if (pending) return;
      pending = (async () => {
        button.disabled = true;
        message.textContent = "Actualisation en cours…";
        try {
          const params = new URLSearchParams({
            nom: box.dataset.nom, prenom: box.dataset.prenom || "",
            nub: box.dataset.nub, cache: "bypass"
          });
          const response = await window.cnapsRead("/api/cnaps_public_annuaire?" + params);
          const data = await response.json();
          if (!response.ok || !data.ok || data.check_status === "error") throw new Error();
          render(data);
          checked.textContent = checkedLabel(data.checked_at);
          message.textContent = "";
        } catch {
          message.textContent = "Actualisation impossible. Vous pouvez réessayer.";
        } finally {
          button.disabled = false;
        }
      })().finally(() => { pending = null; });
    });
    return () => pending;
  }

  window.cnapsCards = {bind, checkedLabel};
})();
