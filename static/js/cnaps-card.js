(function () {
  // Limit simultaneous source lookups when several trainees have no local number.
  const nubReads = [Promise.resolve(), Promise.resolve()];

  function queueNubRead(read) {
    const pending = nubReads.shift().then(read);
    nubReads.push(pending.catch(() => {}));
    return pending;
  }

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

    function resolveMissingNub() {
      const label = box.dataset.nubLabelId ? document.getElementById(box.dataset.nubLabelId)
        : box.querySelector("[data-card-pro-nub]");
      button.disabled = true;
      label.textContent = "Recherche du NUB…";
      message.textContent = "";
      pending = queueNubRead(async () => {
        const response = await window.cnapsRead(box.dataset.nubUrl);
        const data = await response.json();
        if (!response.ok || !data.ok) {
          label.textContent = response.status === 409 ? "NUB à vérifier" : "NUB indisponible";
          message.textContent = data.error || "Vous pouvez réessayer.";
          return;
        }
        if (!data.nub) {
          label.textContent = "NUB manquant";
          return;
        }
        box.dataset.nub = data.nub;
        label.textContent = "NUB : " + data.nub;
        const snapshot = data.snapshot || {};
        if (snapshot.result) {
          render(snapshot.result);
          checked.textContent = checkedLabel(snapshot.checked_at || snapshot.result.checked_at);
        } else {
          box.querySelector("[data-card-pro-result], [data-trainee-card-pro-result]").textContent = "Aucune vérification enregistrée";
        }
      }).catch(() => {
        label.textContent = "NUB indisponible";
        message.textContent = "Vous pouvez réessayer.";
      }).finally(() => {
        button.disabled = false;
        pending = null;
      });
    }

    if (!box.dataset.nub && box.dataset.nubUrl) resolveMissingNub();
    button.addEventListener("click", () => {
      if (pending) return;
      if (!box.dataset.nub && box.dataset.nubUrl) {
        resolveMissingNub();
        return;
      }
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
