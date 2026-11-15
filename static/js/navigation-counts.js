(() => {
  const nodes = {
    documents: ["sidebarDocsToControlBadge"],
    conventions: ["sidebarConventionsSignedBadge"],
    cnaps: ["sidebarCnapsBadge", "sidebarCnapsTrackingBadge"],
    tools: ["sidebarToolsConventionsSignedBadge"],
    sales: ["sidebarSalesTodayBadge"],
  };
  const labels = {
    documents: "document(s) à contrôler", conventions: "convention(s) à imprimer",
    cnaps: "changement(s) de statut CNAPS", tools: "notification(s) dans les outils",
    sales: "inscription(s) aujourd’hui",
  };
  if (!Object.values(nodes).flat().some(id => document.getElementById(id))) return;
  function paint(type, value) {
    for (const id of nodes[type]) {
      const el = document.getElementById(id);
      if (!el) continue;
      el.textContent = value == null ? "!" : String(value);
      el.style.display = value === 0 ? "none" : "inline-flex";
      el.setAttribute("aria-label", value == null ? "Compteur indisponible" : value + " " + labels[type]);
    }
  }
  function paintCounts(data) {
    const counts = {...data, tools: data.sales + data.conventions};
    for (const type of Object.keys(nodes)) paint(type, counts[type]);
  }
  let generation = 0;
  async function refresh(fresh = false) {
    if (document.hidden) return;
    const current = ++generation;
    try {
      const reply = await window.adminReadFetch("/api/admin/navigation-counts" + (fresh ? "?fresh=1" : ""));
      if (!reply.ok) throw new Error();
      const data = await reply.json();
      if (!data.ok || current !== generation) return;
      paintCounts(data);
    } catch {
      if (current === generation) Object.keys(nodes).forEach(type => paint(type, null));
    }
  }
  window.refreshSidebarCnapsTrackingBadge = count => count == null ? refresh(true) : paint("cnaps", count);
  window.refreshSidebarConventionsSignedBadge = () => refresh(true);
  document.addEventListener("visibilitychange", () => refresh());
  window.addEventListener("focus", () => refresh());
  const initial = document.currentScript?.dataset.counts;
  if (initial) paintCounts(JSON.parse(initial));
  else refresh();
})();
