(() => {
  const form = document.getElementById("ssiapDiplomaInfoForm");
  if (!form) return;

  const city = form.elements.birth_city;
  const country = form.elements.birth_country;
  const department = form.elements.birth_department;
  const hint = document.getElementById("ssiapInfoBirthDepartmentHint");
  const normalize = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim();
  const placeKey = () => `${normalize(city.value)}|${normalize(country.value)}`;
  let previousPlace = placeKey();
  let revision = 0;
  let timer;
  let controller;

  function cancelLookup() {
    revision += 1;
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = null;
    department.removeAttribute("aria-busy");
  }

  async function lookup() {
    cancelLookup();
    const currentRevision = revision;
    const currentPlace = placeKey();
    hint.textContent = "";
    if (department.value.trim() || city.value.trim().length < 2) return;
    if (!["", "FRANCE", "FR", "FRA"].includes(normalize(country.value))) return;

    controller = new AbortController();
    department.setAttribute("aria-busy", "true");
    hint.textContent = "Recherche du département…";
    const params = new URLSearchParams({city: city.value.trim(), country: country.value.trim()});
    try {
      const response = await fetch(`${form.dataset.birthDepartmentUrl}?${params}`, {
        signal: controller.signal,
        headers: {Accept: "application/json"},
      });
      if (!response.ok) throw new Error("lookup_failed");
      const data = await response.json();
      if (!data.ok) throw new Error("lookup_failed");
      if (revision !== currentRevision || placeKey() !== currentPlace || department.value.trim()) return;
      if (/^(?:\d{2,3}|2A|2B)$/.test(data.department || "")) {
        department.value = data.department;
        hint.textContent = "Département trouvé automatiquement. Vous pouvez le modifier.";
      } else {
        hint.textContent = "Ville non reconnue ou homonyme : renseignez le département.";
      }
    } catch (error) {
      if (error.name !== "AbortError" && revision === currentRevision) {
        hint.textContent = "Recherche indisponible. Vous pouvez saisir le département.";
      }
    } finally {
      if (revision === currentRevision) {
        department.removeAttribute("aria-busy");
        controller = null;
      }
    }
  }

  function placeChanged() {
    const currentPlace = placeKey();
    if (currentPlace === previousPlace) return;
    previousPlace = currentPlace;
    cancelLookup();
    // A department belongs to the previous place, including a saved value.
    // Manual edits made after this change remain authoritative.
    department.value = "";
    hint.textContent = "";
    timer = setTimeout(lookup, 350);
  }

  city.addEventListener("input", placeChanged);
  city.addEventListener("change", placeChanged);
  country.addEventListener("input", placeChanged);
  country.addEventListener("change", placeChanged);
  department.addEventListener("input", () => {
    cancelLookup();
    hint.textContent = "";
  });
  form.addEventListener("ssiap-diploma-info-opened", () => {
    previousPlace = placeKey();
    lookup();
  });
})();
