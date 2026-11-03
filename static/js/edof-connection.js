(() => {
  const box = document.getElementById("edof-live");
  const lamp = document.getElementById("edof-lamp");
  const note = document.getElementById("edof-connection-note");
  if (!box || !lamp || !note) return;
  async function refresh() {
    if (!document.hidden) {
      try {
        const response = await fetch(box.dataset.statusUrl, {cache: "no-store"});
        if (!response.ok) throw Error();
        const state = await response.json();
        lamp.classList.toggle("on", state.active);
        lamp.textContent = state.active ? "Connexion EDOF active" : "Connexion EDOF inactive";
        note.textContent = [state.pending ? "Lecture en cours…" : state.error,
          state.until && "Activation manuelle jusqu’à " + state.until,
          state.checked && "Dernier contrôle le " + state.checked].filter(Boolean).join(" · ");
        if (state.active && box.dataset.list === "1" && state.stamp > Number(box.dataset.stamp)
            && !document.activeElement.matches("input, textarea, select")) location.reload();
      } catch {
        lamp.classList.remove("on");
        lamp.textContent = "Connexion EDOF inactive";
        note.textContent = "Le serveur n’a pas pu confirmer la connexion.";
      }
    }
    setTimeout(refresh, 15000);
  }
  setTimeout(refresh, 3000);
})();
