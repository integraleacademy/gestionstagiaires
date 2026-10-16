(() => {
  "use strict";
  const root = document.querySelector("[data-production-ai]");
  const form = document.getElementById("apsProductionForm");
  const configNode = document.getElementById("apsProductionAIConfig");
  const productionNode = document.getElementById("apsProductionConfig");
  if (!root || !form || !configNode || !productionNode || root.dataset.initialized) return;
  root.dataset.initialized = "true";
  let config, productionConfig;
  try {
    config = JSON.parse(configNode.textContent || "{}");
    productionConfig = JSON.parse(productionNode.textContent || "{}");
  } catch (_error) { return; }

  const requestButton = root.querySelector("[data-ai-request]");
  const refreshButton = root.querySelector("[data-ai-refresh]");
  const statusNode = root.querySelector("[data-ai-status]");
  const staleNode = root.querySelector("[data-ai-stale]");
  const resultNode = root.querySelector("[data-ai-result]");
  const historyNode = root.querySelector("[data-ai-history]");
  const historySelect = root.querySelector("[data-ai-history-select]");
  const snapshotNode = root.querySelector("[data-ai-answer-snapshot]");
  const fields = Array.from(form.querySelectorAll("[data-production-field]"));
  const fieldLabels = new Map((productionConfig.production?.response_fields || []).map(field => [field.id, field.label]));
  const state = { history: [], latest: null, selectedId: "", busy: false, timer: null, retryTimer: null, retryUntil: 0, polls: 0 };
  const previewReadOnly = productionConfig.preview && !config.configured;
  const pending = job => job && ["queued", "running"].includes(job.status);
  const statusLabels = { queued: "En attente", running: "En cours", completed: "Analyse disponible", failed: "Analyse indisponible" };
  const levelLabels = { satisfactory: "Satisfaisant", partial: "À approfondir", missing: "À compléter", incorrect: "À corriger" };

  function element(tag, text = "", className = "") {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function answers() {
    return Object.fromEntries(fields.map(field => [field.dataset.productionField, field.value.trim()]));
  }

  function sameAnswers(left, right) {
    return fields.every(field => (left?.[field.dataset.productionField] || "").trim() === (right?.[field.dataset.productionField] || "").trim());
  }

  function selectedJob() {
    return state.history.find(job => job.id === state.selectedId) || state.latest;
  }

  function setStatus(message, isError = false) {
    statusNode.textContent = message;
    statusNode.classList.toggle("is-error", isError);
  }

  function updateButton() {
    const unchanged = sameAnswers(answers(), state.latest?.answers);
    requestButton.disabled = !config.configured || state.busy || pending(state.latest);
    if (state.busy || pending(state.latest)) {
      requestButton.textContent = "Analyse en cours…";
    } else if (state.latest?.status === "failed" && unchanged) {
      const waiting = Date.now() < state.retryUntil;
      requestButton.textContent = waiting ? "Nouvel essai disponible dans un instant" : state.latest.retryable ? "Réessayer l’analyse" : "Analyse indisponible pour cette version";
      requestButton.disabled ||= !state.latest.retryable || waiting;
    } else if (state.latest?.status === "completed" && unchanged) {
      requestButton.textContent = "Revoir l’analyse de cette version";
    } else {
      requestButton.textContent = state.latest ? "Analyser ma nouvelle version" : "Analyser ma production";
    }
    refreshButton.disabled = state.busy || !config.historyUrl || previewReadOnly;
    const selected = selectedJob();
    // A stale analysis remains readable while the learner improves the original.
    staleNode.hidden = !selected || sameAnswers(answers(), selected.answers);
  }

  function addList(parent, title, items, className = "") {
    if (!Array.isArray(items) || !items.length) return;
    const section = element("section", "", className);
    section.append(element("h4", title));
    const list = element("ul");
    items.forEach(item => list.append(element("li", String(item))));
    section.append(list);
    parent.append(section);
  }

  function addReferences(parent, ids, references) {
    const titles = (ids || []).map(id => references.get(id)?.title).filter(Boolean);
    if (!titles.length) return;
    const node = element("p", "", "aps-ai-references");
    node.append(element("strong", "Repères à relire : "), document.createTextNode([...new Set(titles)].join(" · ")));
    parent.append(node);
  }

  function renderFeedback(feedback, job) {
    resultNode.replaceChildren();
    resultNode.hidden = false;
    const references = new Map((feedback.references || []).map(reference => [reference.id, reference]));
    const summary = element("section", "", "aps-ai-summary");
    const intro = element("div");
    intro.append(element("span", `Analyse de votre version ${job.revision}`, "aps-label"), element("h3", "Votre bilan personnalisé"), element("p", feedback.summary));
    summary.append(intro);
    if (typeof feedback.indicative_grade === "number") {
      const grade = element("div", "", "aps-ai-grade");
      const gradeText = feedback.indicative_grade.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
      grade.append(element("strong", gradeText), element("span", "/ 20"), element("small", "Note indicative IA"));
      summary.append(grade);
    }
    resultNode.append(summary, element("p", feedback.notice || "Analyse IA indicative : la validation du formateur reste distincte.", "aps-ai-notice"));
    addList(resultNode, "Vos points forts", feedback.strengths, "aps-ai-strengths");

    const criteria = element("section", "", "aps-ai-criteria");
    criteria.append(element("h3", "L’analyse de chaque critère"));
    (feedback.criteria || []).forEach(criterion => {
      const detail = element("details", "", `aps-ai-criterion aps-ai-criterion--${Object.hasOwn(levelLabels, criterion.level) ? criterion.level : "partial"}`);
      detail.open = criterion.level !== "satisfactory";
      const heading = element("summary");
      heading.append(element("span", criterion.label), element("span", `${levelLabels[criterion.level] || "À revoir"} · ${criterion.score}/4`, "aps-ai-level"));
      detail.append(heading, element("p", criterion.explanation));
      (criterion.evidence || []).forEach(evidence => {
        const quote = element("blockquote");
        quote.append(element("small", fieldLabels.get(evidence.field_id) || "Dans votre réponse"), element("p", `« ${evidence.quote} »`));
        detail.append(quote);
      });
      addList(detail, "Ce qui est réussi", criterion.strengths);
      addList(detail, "Ce qui doit être corrigé", criterion.errors);
      addList(detail, "Ce qu’il manque", criterion.missing);
      addReferences(detail, criterion.course_reference_ids, references);
      criteria.append(detail);
    });
    resultNode.append(criteria);

    if (feedback.priority_corrections?.length) {
      const corrections = element("section", "", "aps-ai-corrections");
      corrections.append(element("h3", "Vos corrections prioritaires"));
      feedback.priority_corrections.forEach((correction, index) => {
        const item = element("article");
        item.append(element("h4", `${index + 1}. ${correction.problem}`), element("p", correction.why));
        const how = element("p", "", "aps-ai-action");
        how.append(element("strong", "Comment améliorer : "), document.createTextNode(correction.how));
        item.append(how);
        addReferences(item, correction.course_reference_ids, references);
        corrections.append(item);
      });
      resultNode.append(corrections);
    }
    addList(resultNode, "Les éléments à compléter", feedback.missing_points, "aps-ai-missing");

    const plan = element("section", "", "aps-ai-plan");
    plan.append(element("h3", "Votre plan de progrès"));
    (feedback.progress_plan || []).slice().sort((a, b) => a.priority - b.priority).forEach((step, index) => {
      const item = element("article");
      item.append(element("span", `Étape ${index + 1}`, "aps-label"), element("h4", step.action));
      const check = element("p");
      check.append(element("strong", "Pour vérifier votre progrès : "), document.createTextNode(step.success_check));
      item.append(check);
      addReferences(item, step.course_reference_ids, references);
      plan.append(item);
    });
    resultNode.append(plan);

    const corrected = element("details", "", "aps-ai-corrected");
    corrected.append(element("summary", "Voir une proposition de réponse améliorée"), element("p", "Cette proposition est une formulation possible pour comprendre les améliorations. Comparez-la à votre propre travail."));
    (feedback.corrected_response || []).forEach(field => {
      const block = element("section");
      block.append(element("h4", field.label || fieldLabels.get(field.field_id) || "Réponse"), element("p", field.text, "aps-ai-written-text"));
      corrected.append(block);
    });
    const copy = element("button", "Copier la proposition", "aps-ai-secondary");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText((feedback.corrected_response || []).map(field => `${field.label || fieldLabels.get(field.field_id) || "Réponse"}\n${field.text}`).join("\n\n"));
        copy.textContent = "Proposition copiée";
      } catch (_error) { copy.textContent = "Sélectionnez le texte pour le copier"; }
    });
    corrected.append(copy);
    resultNode.append(corrected);
    addList(resultNode, "À discuter avec votre formateur", feedback.questions_for_trainer, "aps-ai-trainer");
    addList(resultNode, "Limites de cette analyse", feedback.limits, "aps-ai-limits");
  }

  function renderSnapshot(job) {
    snapshotNode.replaceChildren();
    fields.forEach(field => {
      const id = field.dataset.productionField;
      const section = element("section");
      section.append(element("h4", fieldLabels.get(id) || id), element("p", job.answers?.[id] || "—", "aps-ai-written-text"));
      snapshotNode.append(section);
    });
  }

  function renderSelected() {
    const job = selectedJob();
    resultNode.hidden = !job || job.status !== "completed" || !job.feedback;
    if (!job) { updateButton(); return; }
    renderSnapshot(job);
    if (job.status === "completed" && job.feedback) {
      renderFeedback(job.feedback, job);
      setStatus("Votre analyse est disponible. Vous pouvez revenir sur chaque critère et consulter les versions précédentes.");
    } else if (pending(job)) {
      setStatus(job.status === "queued" ? "Votre production est enregistrée. L’analyse va démarrer ; vous pouvez continuer à consulter le cours." : "L’IA examine votre production et prépare les conseils détaillés. Vous pouvez rester sur cette page ou revenir plus tard.");
    } else if (job.status === "failed") {
      setStatus(job.error || "Aucune analyse n’a pu être produite. Votre travail reste enregistré.", true);
    }
    updateButton();
  }

  function setHistory(data, preferredId = "") {
    if (Array.isArray(data.history)) state.history = data.history;
    if (data.latest !== undefined) state.latest = data.latest;
    const single = data.analysis || (data.status && data.id ? data : null);
    if (single) {
      state.history = [single, ...state.history.filter(job => job.id !== single.id)].sort((a, b) => b.revision - a.revision);
      state.latest = state.history[0];
    }
    window.clearTimeout(state.retryTimer);
    state.retryUntil = Date.now() + (state.latest?.retry_after || 0) * 1000;
    if (state.retryUntil > Date.now()) state.retryTimer = window.setTimeout(updateButton, state.retryUntil - Date.now() + 50);
    if (preferredId) state.selectedId = preferredId;
    if (!state.history.some(job => job.id === state.selectedId)) state.selectedId = state.latest?.id || "";
    historyNode.hidden = !state.history.length;
    historySelect.replaceChildren();
    state.history.forEach(job => {
      const date = new Date(job.created_at);
      const label = Number.isNaN(date.valueOf()) ? "" : date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
      const option = element("option", `Version ${job.revision} · ${label} · ${statusLabels[job.status] || job.status}`);
      option.value = job.id;
      historySelect.append(option);
    });
    historySelect.value = state.selectedId;
    renderSelected();
    schedulePoll();
  }

  async function post(url, payload = {}) {
    if (!url) throw new Error("L’analyse personnalisée n’est pas disponible sur cette page.");
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin) throw new Error("L’adresse du service d’analyse est invalide.");
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(target.href, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Accept": "application/json", "Content-Type": "application/json", "X-Elearning-CSRF": config.csrfToken || "" },
        body: JSON.stringify({ access_token: config.accessToken || "", version: config.version || "", ...payload }),
      });
      let data;
      try { data = await response.json(); }
      catch (_error) {
        throw new Error(response.status === 401 ? "Votre session a expiré. Rechargez la page pour retrouver vos analyses." :
          response.status === 403 ? "Cette session ne permet pas d’accéder à cette analyse." :
          "Le service d’analyse n’a pas pu répondre. Votre travail reste disponible sur cette page.");
      }
      if (!response.ok || data.ok === false) {
        const error = new Error(typeof data.error === "string" ? data.error : "Le service d’analyse est indisponible.");
        error.retryAfter = data.retry_after || 0;
        throw error;
      }
      return data;
    } finally { window.clearTimeout(timer); }
  }

  function schedulePoll() {
    window.clearTimeout(state.timer);
    if (!pending(state.latest)) { state.polls = 0; return; }
    if (state.polls >= 75) {
      setStatus("L’analyse se poursuit. Vous pouvez revenir plus tard ou actualiser vos analyses pour consulter son résultat.");
      return;
    }
    state.timer = window.setTimeout(async () => {
      state.polls += 1;
      try { setHistory(await post(config.historyUrl, { analysis_id: state.latest.id })); }
      catch (_error) {
        setStatus("La connexion au suivi a été interrompue. Actualisez vos analyses pour retrouver le résultat.", true);
      }
    }, 2400);
  }

  async function refresh() {
    state.polls = 0;
    refreshButton.disabled = true;
    try { setHistory(await post(config.historyUrl)); }
    catch (error) { setStatus(error.message || "Impossible de charger vos analyses.", true); }
    finally { updateButton(); }
  }

  requestButton.addEventListener("click", async () => {
    if (state.busy || pending(state.latest) || !config.configured) return;
    if (!fields.every(field => field.checkValidity())) { form.reportValidity(); return; }
    const current = answers();
    if (state.latest?.status === "completed" && sameAnswers(current, state.latest.answers)) {
      state.selectedId = state.latest.id;
      renderSelected();
      resultNode.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const retry = state.latest?.status === "failed" && sameAnswers(current, state.latest.answers);
    state.busy = true;
    state.polls = 0;
    updateButton();
    setStatus("Votre demande d’analyse est en cours d’enregistrement…");
    try {
      const data = await post(config.analysisUrl, { production_answers: current, retry: Boolean(retry) });
      const job = data.analysis || (data.id ? data : data.latest);
      setHistory(data, job?.id || "");
    } catch (error) {
      setStatus(error.name === "AbortError" ? "La demande n’a pas pu être confirmée. Actualisez vos analyses avant de la relancer." : error.message, true);
    } finally { state.busy = false; updateButton(); }
  });
  refreshButton.addEventListener("click", refresh);
  historySelect.addEventListener("change", () => { state.selectedId = historySelect.value; renderSelected(); });
  fields.forEach(field => field.addEventListener("input", updateButton));
  window.addEventListener("pagehide", () => { window.clearTimeout(state.timer); window.clearTimeout(state.retryTimer); });
  updateButton();
  if (config.historyUrl && !previewReadOnly) refresh();
})();
