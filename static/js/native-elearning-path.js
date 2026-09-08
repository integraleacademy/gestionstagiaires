(() => {
  "use strict";
  const configNode = document.getElementById("nativePathConfig");
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent);
  const library = document.getElementById("nativeModuleLibrary");
  const moduleList = document.getElementById("nativePathModules");
  const search = document.getElementById("nativeModuleSearch");
  const title = document.getElementById("nativePathTitle");
  const totals = document.getElementById("nativePathTotals");
  const save = document.getElementById("nativePathSave");
  const status = document.getElementById("nativePathSaveState");
  let dirty = false;
  let busy = false;
  const opened = new Set();
  const key = (item) => `${item.course_id}@${item.course_version}`;
  const outlines = new Map(config.catalog.map((item) => [key(item), item]));
  const outlineFor = (item) => outlines.get(key(item)) || (!item.course_version
    ? config.catalog.find((course) => course.course_id === item.course_id) : null);
  const modules = config.modules.map((item) => {
    const outline = outlineFor(item);
    return { ...item, course_version: item.course_version || outline?.course_version || "",
      title: item.title || "", section_ids: item.section_ids || outline?.sections.map((section) => section.id) || [] };
  });
  const readonly = () => config.readOnly || busy;
  const textNode = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function button(label, action, disabled = false, primary = false) {
    const node = textNode("button", `np-button${primary ? " np-button--primary" : ""}`, label);
    node.type = "button";
    node.disabled = readonly() || disabled;
    node.addEventListener("click", action);
    return node;
  }
  function changed() {
    dirty = true;
    status.textContent = "Modifications non enregistrées";
    status.classList.remove("np-error");
    renderTotals();
  }
  function move(items, index, delta) {
    if (index + delta < 0 || index + delta >= items.length || readonly()) return;
    [items[index], items[index + delta]] = [items[index + delta], items[index]];
    changed();
    renderModules();
  }
  function renderTotals() {
    let sequenceCount = 0, activityCount = 0;
    modules.forEach((item) => {
      outlineFor(item)?.sections.forEach((section) => {
        if (item.section_ids.includes(section.id)) {
          sequenceCount += 1;
          activityCount += section.activities.length;
        }
      });
    });
    totals.replaceChildren(...[`${modules.length} modules`, `${sequenceCount} séquences`, `${activityCount} activités`]
      .map((value) => textNode("span", "", value)));
  }
  function renderLibrary() {
    const normalize = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const term = normalize(search.value.trim());
    const matches = config.catalog.filter((course) => normalize(course.title).includes(term));
    library.replaceChildren();
    matches.forEach((course) => {
      const card = textNode("article", "np-library-item");
      card.append(textNode("h3", "", course.title));
      card.append(textNode("p", "", `${course.sections.length} séquences · ${course.sections.reduce((sum, section) => sum + section.activities.length, 0)} activités`));
      card.append(textNode("small", "np-version", `Version ${course.course_version}`));
      const present = modules.some((item) => item.course_id === course.course_id);
      card.append(button(present ? "Déjà dans le parcours" : "+ Ajouter au parcours", () => {
        if (readonly() || modules.length >= 100) return;
        modules.push({ course_id: course.course_id, course_version: course.course_version,
          title: "", section_ids: course.sections.map((section) => section.id) });
        changed();
        renderModules();
        renderLibrary();
      }, present || modules.length >= 100));
      library.append(card);
    });
    if (!matches.length) library.append(textNode("p", "np-empty", "Aucun module trouvé. Importez un ZIP depuis la bibliothèque."));
  }
  function renderModules() {
    moduleList.replaceChildren();
    modules.forEach((item, index) => {
      const outline = outlineFor(item);
      const card = textNode("details", "np-panel np-module");
      card.open = opened.has(item.course_id);
      card.addEventListener("toggle", () => {
        if (card.open) opened.add(item.course_id); else opened.delete(item.course_id);
      });
      const heading = textNode("summary", "np-module-heading");
      heading.append(textNode("span", "np-number", String(index + 1).padStart(2, "0")));
      const identity = textNode("div", "np-module-identity");
      const headingTitle = textNode("h3", "", item.title || outline?.title || "Module indisponible");
      identity.append(headingTitle, textNode("p", "", `${item.section_ids.length} séquences sélectionnées · Déplier pour composer`));
      heading.append(identity);
      const controls = textNode("div", "np-module-controls");
      const up = button("↑", () => move(modules, index, -1), index === 0);
      up.setAttribute("aria-label", `Monter le module ${index + 1}`);
      const down = button("↓", () => move(modules, index, 1), index === modules.length - 1);
      down.setAttribute("aria-label", `Descendre le module ${index + 1}`);
      controls.append(up, down, button("Retirer", () => {
        if (!window.confirm("Retirer ce module du parcours ? Sa progression enregistrée sera conservée.")) return;
        modules.splice(index, 1);
        changed(); renderModules(); renderLibrary();
      }));
      controls.addEventListener("click", (event) => { event.preventDefault(); });
      heading.append(controls);
      card.append(heading);
      if (!outline) {
        card.append(textNode("p", "np-error", "La version de ce module est indisponible. Retirez-le ou restaurez sa version avant d’enregistrer."));
        moduleList.append(card);
        return;
      }
      const body = textNode("div", "np-module-body");
      const label = textNode("label", "np-field", "Nom du module dans ce parcours");
      const input = document.createElement("input");
      input.value = item.title; input.placeholder = outline.title; input.maxLength = 180;
      input.disabled = readonly();
      input.addEventListener("input", () => { item.title = input.value; headingTitle.textContent = input.value || outline.title; changed(); });
      label.append(input);
      body.append(label, textNode("small", "np-version", `Source : ${outline.title} · Version ${item.course_version}`));
      const bulk = textNode("div", "np-sequence-tools");
      bulk.append(textNode("strong", "", "Séquences du module"), button("Tout inclure", () => {
        item.section_ids.push(...outline.sections.map((section) => section.id).filter((id) => !item.section_ids.includes(id)));
        changed(); renderModules();
      }));
      body.append(bulk);
      const sections = new Map(outline.sections.map((section) => [section.id, section]));
      const displayOrder = [...item.section_ids, ...outline.sections.map((section) => section.id).filter((id) => !item.section_ids.includes(id))];
      displayOrder.forEach((sectionId) => {
        const section = sections.get(sectionId);
        if (!section) return;
        const selectedIndex = item.section_ids.indexOf(section.id);
        const selected = selectedIndex >= 0;
        const row = textNode("div", `np-sequence${selected ? "" : " is-excluded"}`);
        const rowHead = textNode("div", "np-sequence-heading");
        const checkboxLabel = textNode("label", "np-check");
        const check = document.createElement("input");
        check.type = "checkbox"; check.checked = selected; check.disabled = readonly();
        check.addEventListener("change", () => {
          if (check.checked) item.section_ids.push(section.id);
          else item.section_ids.splice(selectedIndex, 1);
          changed(); renderModules();
        });
        checkboxLabel.append(check, textNode("span", "", `${selected ? selectedIndex + 1 + '. ' : ''}${section.title}`));
        rowHead.append(checkboxLabel);
        const actions = textNode("div", "np-sequence-controls");
        const moveUp = button("↑", () => move(item.section_ids, selectedIndex, -1), !selected || selectedIndex === 0);
        moveUp.setAttribute("aria-label", `Monter la séquence ${section.title}`);
        const moveDown = button("↓", () => move(item.section_ids, selectedIndex, 1), !selected || selectedIndex === item.section_ids.length - 1);
        moveDown.setAttribute("aria-label", `Descendre la séquence ${section.title}`);
        actions.append(moveUp, moveDown); rowHead.append(actions); row.append(rowHead);
        const activities = textNode("details", "np-activities");
        activities.append(textNode("summary", "", `${section.activities.length} activités · Voir le contenu`));
        const list = document.createElement("ol");
        section.activities.forEach((activity) => list.append(textNode("li", "", `${activity.title}${activity.scored ? ' · Question' : ''}`)));
        activities.append(list); row.append(activities); body.append(row);
      });
      if (!item.section_ids.length) body.append(textNode("p", "np-error", "Choisissez au moins une séquence pour ce module."));
      card.append(body); moduleList.append(card);
    });
    if (!modules.length) {
      const empty = textNode("div", "np-panel np-empty");
      empty.append(textNode("h2", "", "Votre parcours commence ici"), textNode("p", "", "Ajoutez des modules depuis la bibliothèque, puis organisez leurs séquences."));
      moduleList.append(empty);
    }
    renderTotals();
  }
  save.addEventListener("click", async () => {
    if (readonly()) return;
    if (modules.some((item) => !item.section_ids.length)) {
      status.textContent = "Choisissez au moins une séquence dans chaque module.";
      status.classList.add("np-error"); return;
    }
    if (!modules.length && config.modules.length && !window.confirm("Enregistrer un parcours vide ? L’accès aux modules sera retiré, mais les progressions seront conservées.")) return;
    busy = true; save.disabled = true; title.disabled = true;
    status.textContent = "Enregistrement…"; status.classList.remove("np-error");
    renderModules(); renderLibrary();
    try {
      const response = await fetch(config.saveUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Elearning-CSRF": config.csrfToken },
        body: JSON.stringify({ title: title.value, modules, revision: config.revision }) });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Enregistrement impossible.");
      config.revision = result.revision;
      config.modules = result.modules;
      dirty = false;
      status.textContent = "Parcours enregistré pour cette session";
    } catch (error) {
      status.textContent = error.message || "Enregistrement impossible. Réessayez.";
      status.classList.add("np-error");
    } finally {
      busy = false; save.disabled = Boolean(config.readOnly); title.disabled = Boolean(config.readOnly);
      renderModules(); renderLibrary();
    }
  });
  title.addEventListener("input", changed);
  search.addEventListener("input", renderLibrary);
  window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
  renderLibrary(); renderModules();
})();
