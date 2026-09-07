(() => {
  "use strict";

  const dataNode = document.getElementById("cancellationPageData");
  if (!dataNode) return;

  let pageData = {};
  try {
    pageData = JSON.parse(dataNode.textContent || "{}");
  } catch (error) {
    console.error("Cancellation dashboard data is invalid", error);
  }

  const rows = Array.from(document.querySelectorAll(".cancellation-row"));
  const filters = {
    search: document.getElementById("cancellationSearch"),
    collection: document.getElementById("cancellationCollectionFilter"),
    caseStatus: document.getElementById("cancellationCaseFilter"),
    training: document.getElementById("cancellationTrainingFilter"),
    session: document.getElementById("cancellationSessionFilter"),
    assignee: document.getElementById("cancellationAssigneeFilter"),
  };
  const emptyState = document.getElementById("cancellationEmpty");
  const resultCount = document.getElementById("cancellationResultCount");
  const quickButtons = Array.from(document.querySelectorAll("[data-quick-filter]"));
  const filterStorageKey = "integrale-cancellation-filters-v1";
  let quickFilter = "all";

  const normalize = (value) => String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();

  function visibleForQuickFilter(row) {
    const collection = row.dataset.collectionStatus || "";
    const caseStatus = row.dataset.caseStatus || "";
    if (quickFilter === "all") return true;
    if (quickFilter === "attention") {
      return ["pending", "partial", "overdue", "calculation_required", "refund_due"].includes(collection);
    }
    if (quickFilter === "paid") return ["paid", "waived"].includes(collection);
    if (quickFilter === "disputed") return ["disputed", "collections"].includes(caseStatus);
    return collection === quickFilter;
  }

  function filterSnapshot() {
    return {
      search: filters.search?.value || "",
      collection: filters.collection?.value || "",
      caseStatus: filters.caseStatus?.value || "",
      training: filters.training?.value || "",
      session: filters.session?.value || "",
      assignee: filters.assignee?.value || "",
      quickFilter,
    };
  }

  function persistFilters() {
    try {
      sessionStorage.setItem(filterStorageKey, JSON.stringify(filterSnapshot()));
    } catch (_error) {
      // Browsers with storage disabled still retain all filtering features.
    }
  }

  function restoreFilters() {
    let saved = {};
    try {
      saved = JSON.parse(sessionStorage.getItem(filterStorageKey) || "{}");
    } catch (_error) {
      saved = {};
    }
    if (filters.search && saved.search) filters.search.value = saved.search;
    if (filters.collection && saved.collection) filters.collection.value = saved.collection;
    if (filters.caseStatus && saved.caseStatus) filters.caseStatus.value = saved.caseStatus;
    if (filters.training && saved.training) filters.training.value = saved.training;
    if (filters.assignee && saved.assignee) filters.assignee.value = saved.assignee;
    if (filters.session) {
      const requestedSession = pageData.initial_session_id || saved.session || "";
      if (Array.from(filters.session.options).some((option) => option.value === requestedSession)) {
        filters.session.value = requestedSession;
      }
    }
    if (!pageData.initial_session_id && saved.quickFilter) quickFilter = saved.quickFilter;
  }

  function applyFilters() {
    const query = normalize(filters.search?.value);
    const collection = filters.collection?.value || "";
    const caseStatus = filters.caseStatus?.value || "";
    const training = filters.training?.value || "";
    const sessionId = filters.session?.value || "";
    const assignee = filters.assignee?.value || "";
    let visible = 0;

    rows.forEach((row) => {
      const matches = (
        (!query || normalize(row.dataset.search).includes(query))
        && (!collection || row.dataset.collectionStatus === collection)
        && (!caseStatus || row.dataset.caseStatus === caseStatus)
        && (!training || row.dataset.trainingType === training)
        && (!sessionId || row.dataset.sessionId === sessionId)
        && (!assignee || row.dataset.assignee === assignee)
        && visibleForQuickFilter(row)
      );
      row.hidden = !matches;
      if (matches) visible += 1;
    });

    if (resultCount) resultCount.textContent = `${visible} dossier${visible === 1 ? "" : "s"}`;
    if (emptyState) emptyState.hidden = visible > 0;
    const clear = document.getElementById("cancellationSearchClear");
    if (clear) clear.hidden = !filters.search?.value;
    quickButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.quickFilter === quickFilter);
    });
    persistFilters();
  }

  function resetFilters() {
    Object.values(filters).forEach((field) => { if (field) field.value = ""; });
    quickFilter = "all";
    applyFilters();
  }

  restoreFilters();
  Object.values(filters).forEach((field) => {
    if (!field) return;
    field.addEventListener(field.tagName === "INPUT" ? "input" : "change", applyFilters);
  });
  quickButtons.forEach((button) => {
    button.addEventListener("click", () => {
      quickFilter = button.dataset.quickFilter || "all";
      if (filters.collection) filters.collection.value = "";
      applyFilters();
    });
  });
  document.getElementById("cancellationResetFilters")?.addEventListener("click", resetFilters);
  document.querySelector("[data-empty-reset]")?.addEventListener("click", resetFilters);
  document.getElementById("cancellationSearchClear")?.addEventListener("click", () => {
    if (filters.search) {
      filters.search.value = "";
      filters.search.focus();
      applyFilters();
    }
  });
  applyFilters();

  document.getElementById("cancellationRefresh")?.addEventListener("click", () => window.location.reload());

  function csvCell(value) {
    return `"${String(value || "").replace(/"/g, '""')}"`;
  }

  document.getElementById("cancellationExportCsv")?.addEventListener("click", () => {
    const headers = [
      "Stagiaire", "Formation", "Session", "Date d'annulation", "Statut du dossier",
      "État financier", "Indemnité retenue", "Déjà couvert", "Reste à encaisser",
      "Échéance", "Prochaine action", "Responsable",
    ];
    const content = [headers.map(csvCell).join(";")];
    rows.filter((row) => !row.hidden).forEach((row) => {
      content.push([
        row.dataset.exportName,
        row.dataset.exportTraining,
        row.dataset.exportSession,
        row.dataset.exportCancellation,
        row.dataset.exportCaseStatus,
        row.dataset.exportCollectionStatus,
        row.dataset.exportTotal,
        row.dataset.exportPaid,
        row.dataset.exportRemaining,
        row.dataset.exportDue,
        row.dataset.exportNextAction,
        row.dataset.exportAssignee,
      ].map(csvCell).join(";"));
    });
    const blob = new Blob(["\ufeff", content.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `suivi-annulations-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  });

  const layer = document.getElementById("cancellationDrawerLayer");
  const loading = document.getElementById("cancellationDrawerLoading");
  const body = document.getElementById("cancellationDrawerBody");
  const footer = document.getElementById("cancellationDrawerFooter");
  const drawerError = document.getElementById("cancellationDrawerError");
  const caseForm = document.getElementById("cancellationCaseForm");
  const paymentForm = document.getElementById("cancellationPaymentForm");
  const contactForm = document.getElementById("cancellationContactForm");
  const saveButton = document.getElementById("cancellationSaveCase");
  const toast = document.getElementById("cancellationToast");
  let currentItem = null;
  let activeTab = "case";
  let needsRefresh = false;
  let toastTimer = null;
  let draftTimer = null;
  let drawerRequest = 0;

  const todayIso = () => {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${now.getFullYear()}-${month}-${day}`;
  };

  function money(cents) {
    return new Intl.NumberFormat("fr-FR", {
      style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 2,
    }).format(Number(cents || 0) / 100);
  }

  function moneyInput(cents) {
    if (cents === null || cents === undefined || cents === "") return "";
    const value = Number(cents || 0) / 100;
    return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(".", ",");
  }

  function dateLabel(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${match[3]}/${match[2]}/${match[1]}` : "—";
  }

  function dateTimeLabel(value) {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return dateLabel(value);
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
  }

  function showToast(message, isError = false) {
    if (!toast) return;
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.toggle("is-error", isError);
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 4200);
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "L’action n’a pas pu être effectuée.");
    }
    return payload;
  }

  function initials(item) {
    return `${String(item.first_name || "").slice(0, 1)}${String(item.last_name || "").slice(0, 1)}`.toUpperCase() || "IA";
  }

  function setStatusChip(node, prefix, key, label) {
    if (!node) return;
    node.className = `cancellation-status cancellation-status--${prefix}-${key}`;
    node.textContent = label || "—";
  }

  function populateSelect(select, options, selected) {
    if (!select) return;
    select.replaceChildren();
    (options || []).forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = String(value) === String(selected || "");
      select.appendChild(option);
    });
  }

  function setField(name, value) {
    const field = caseForm?.elements.namedItem(name);
    if (field) field.value = value ?? "";
  }

  function fieldValue(name) {
    const field = caseForm?.elements.namedItem(name);
    return field ? field.value.trim() : "";
  }

  function recordNode({ icon, title, meta, note, amount, className = "", voidAction = null }) {
    const article = document.createElement("article");
    article.className = `cancellation-record ${className}`.trim();
    const iconNode = document.createElement("span");
    iconNode.className = "cancellation-record__icon";
    iconNode.textContent = icon;
    const content = document.createElement("div");
    content.className = "cancellation-record__content";
    const titleNode = document.createElement("strong");
    titleNode.textContent = title;
    const metaNode = document.createElement("span");
    metaNode.textContent = meta;
    content.append(titleNode, metaNode);
    if (note) {
      const noteNode = document.createElement("p");
      noteNode.textContent = note;
      content.appendChild(noteNode);
    }
    article.append(iconNode, content);
    if (amount) {
      const amountNode = document.createElement("strong");
      amountNode.className = "cancellation-record__amount";
      amountNode.textContent = amount;
      article.appendChild(amountNode);
    }
    if (voidAction) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cancellation-record__void";
      button.textContent = "Annuler";
      button.addEventListener("click", voidAction);
      article.appendChild(button);
    }
    return article;
  }

  function renderPayments(item) {
    const list = document.getElementById("cancellationPaymentList");
    const count = document.getElementById("cancellationPaymentsCount");
    const payments = Array.isArray(item.payments) ? item.payments : [];
    const activeCount = payments.filter((entry) => !entry.voided_at).length;
    if (count) count.textContent = String(activeCount);
    if (!list) return;
    list.replaceChildren();
    if (!payments.length) {
      const empty = document.createElement("div");
      empty.className = "cancellation-record-empty";
      empty.textContent = "Aucun règlement enregistré pour le moment.";
      list.appendChild(empty);
      return;
    }
    payments.forEach((payment) => {
      const voided = Boolean(payment.voided_at);
      const method = Object.fromEntries(item.options.payment_methods || [])[payment.method] || "Paiement";
      const reference = payment.reference ? ` · Réf. ${payment.reference}` : "";
      const voidMeta = voided ? ` · Annulé le ${dateTimeLabel(payment.voided_at)}` : "";
      const note = [payment.note, voided ? `Motif d’annulation : ${payment.void_reason || "—"}` : ""].filter(Boolean).join("\n");
      list.appendChild(recordNode({
        icon: voided ? "×" : "€",
        title: voided ? "Règlement annulé" : method,
        meta: `${dateLabel(payment.paid_at)}${reference}${voidMeta} · ${payment.created_by || "Administrateur"}`,
        note,
        amount: money(payment.amount_cents),
        className: voided ? "is-void" : "",
        voidAction: (!voided && !pageData.is_read_only) ? () => voidPayment(payment) : null,
      }));
    });
  }

  function renderContacts(item) {
    const list = document.getElementById("cancellationContactList");
    const count = document.getElementById("cancellationContactsCount");
    const contacts = Array.isArray(item.contacts) ? item.contacts : [];
    if (count) count.textContent = String(contacts.length);
    if (!list) return;
    list.replaceChildren();
    if (!contacts.length) {
      const empty = document.createElement("div");
      empty.className = "cancellation-record-empty";
      empty.textContent = "Aucune relance consignée pour le moment.";
      list.appendChild(empty);
      return;
    }
    const channels = Object.fromEntries(item.options.contact_channels || []);
    const outcomes = Object.fromEntries(item.options.contact_outcomes || []);
    contacts.forEach((contact) => {
      list.appendChild(recordNode({
        icon: contact.channel === "phone" ? "☎" : contact.channel === "email" ? "@" : "↗",
        title: `${channels[contact.channel] || "Contact"} · ${outcomes[contact.outcome] || "Échange"}`,
        meta: `${dateLabel(contact.contacted_at)} · ${contact.created_by || "Administrateur"}`,
        note: contact.note || "",
        className: "cancellation-record--contact",
      }));
    });
  }

  function renderTimeline(item) {
    const list = document.getElementById("cancellationTimeline");
    if (!list) return;
    list.replaceChildren();
    const timeline = Array.isArray(item.timeline) ? item.timeline : [];
    if (!timeline.length) {
      const empty = document.createElement("div");
      empty.className = "cancellation-record-empty";
      empty.textContent = "L’historique se construira au fil des actions.";
      list.appendChild(empty);
      return;
    }
    timeline.forEach((event) => {
      const article = document.createElement("article");
      article.className = `cancellation-timeline-item cancellation-timeline-item--${event.kind || "action"}`;
      const dot = document.createElement("span");
      dot.className = "cancellation-timeline-item__dot";
      dot.textContent = event.kind === "payment" ? "€" : event.kind === "contact" || event.kind === "email" ? "↗" : event.kind === "warning" ? "!" : "•";
      const content = document.createElement("div");
      content.className = "cancellation-timeline-item__content";
      const title = document.createElement("strong");
      title.textContent = event.label || "Action";
      content.appendChild(title);
      if (event.details) {
        const details = document.createElement("p");
        details.textContent = event.details;
        content.appendChild(details);
      }
      const meta = document.createElement("div");
      meta.className = "cancellation-timeline-item__meta";
      const date = document.createElement("span");
      date.textContent = dateTimeLabel(event.at);
      meta.appendChild(date);
      if (event.actor) {
        const actor = document.createElement("span");
        actor.textContent = event.actor;
        meta.appendChild(actor);
      }
      content.appendChild(meta);
      article.append(dot, content);
      list.appendChild(article);
    });
  }

  function updateFinancialDisplay(item, calculationOverride = null) {
    const calculation = calculationOverride || item.calculation || {};
    const penalty = Number(calculation.penalty_cents || 0);
    const prorata = Number(calculation.prorata_cents || 0);
    const contractual = Number(calculation.total_due_cents || 0);
    const deductible = Number(calculation.deductible_paid_cents || 0);
    const payments = Number(item.payments_received_cents || 0);
    let effective = contractual;
    const decision = fieldValue("decision") || item.decision;
    if (decision === "waived") effective = 0;
    if (decision === "custom") {
      const custom = fieldValue("manual_total_due_amount").replace(/\s/g, "").replace(",", ".");
      if (custom !== "" && Number.isFinite(Number(custom))) effective = Math.max(Math.round(Number(custom) * 100), 0);
    }
    const credited = deductible + payments;
    const remaining = Math.max(effective - credited, 0);
    const refund = Math.max(credited - effective, 0);
    document.getElementById("cancellationRecapPenalty").textContent = money(penalty);
    document.getElementById("cancellationRecapProrata").textContent = money(prorata);
    document.getElementById("cancellationRecapContractual").textContent = money(contractual);
    document.getElementById("cancellationRecapDeductible").textContent = money(deductible);
    document.getElementById("cancellationRecapEffective").textContent = money(effective);
    document.getElementById("cancellationRecapRemaining").textContent = refund ? `${money(refund)} à rembourser` : money(remaining);
  }

  function syncDecisionFields() {
    const decision = fieldValue("decision");
    const customField = caseForm?.elements.namedItem("manual_total_due_amount");
    const reasonField = caseForm?.elements.namedItem("adjustment_reason");
    if (customField) customField.disabled = pageData.is_read_only || decision !== "custom";
    if (reasonField) reasonField.required = ["custom", "waived"].includes(decision);
    if (currentItem) updateFinancialDisplay(currentItem);
  }

  function renderItem(item) {
    currentItem = item;
    const state = item.state || {};
    const calculation = item.calculation || {};
    const options = item.options || {};

    document.getElementById("cancellationDrawerAvatar").textContent = initials(item);
    document.getElementById("cancellationDrawerTitle").textContent = item.full_name || "Dossier sans nom";
    document.getElementById("cancellationDrawerSubtitle").textContent = `${item.training_type || "Formation"} · ${item.session_name || "Session"}`;
    setStatusChip(document.getElementById("cancellationDrawerCaseStatus"), "case", item.case_status, item.case_status_label);
    setStatusChip(document.getElementById("cancellationDrawerMoneyStatus"), "money", item.collection_status, item.collection_status_label);
    document.getElementById("cancellationDrawerUpdated").textContent = item.updated_at ? `Mis à jour ${dateTimeLabel(item.updated_at)}` : "";
    document.getElementById("cancellationSummaryDue").textContent = money(item.effective_total_due_cents);
    document.getElementById("cancellationSummaryRule").textContent = item.rule_label || "Calcul à finaliser";
    document.getElementById("cancellationSummaryPaid").textContent = money(item.credited_total_cents);
    document.getElementById("cancellationSummaryRemaining").textContent = item.refund_due_cents ? `${money(item.refund_due_cents)} à rembourser` : money(item.remaining_cents);
    document.getElementById("cancellationSummaryDueDate").textContent = item.payment_due_date ? `Échéance ${dateLabel(item.payment_due_date)}` : "Sans échéance";
    document.getElementById("cancellationOpenTrainee").href = item.trainee_url;
    document.getElementById("cancellationOpenTraineeCalculator").href = `${item.trainee_url}#cancellationIndemnityModal`;

    populateSelect(caseForm.elements.namedItem("case_status"), options.case_statuses, item.case_status);
    populateSelect(caseForm.elements.namedItem("origin"), options.origins, state.origin);
    populateSelect(caseForm.elements.namedItem("reason"), options.reasons, state.reason);
    populateSelect(caseForm.elements.namedItem("decision"), options.decisions, state.decision);
    populateSelect(caseForm.elements.namedItem("payment_terms"), options.payment_terms, state.payment_terms);
    populateSelect(paymentForm.elements.namedItem("method"), options.payment_methods, "bank_transfer");
    populateSelect(contactForm.elements.namedItem("channel"), options.contact_channels, "email");
    populateSelect(contactForm.elements.namedItem("outcome"), options.contact_outcomes, "sent");

    ["assigned_to", "reason_details", "request_received_at", "confirmation_received_at", "next_action_date", "payment_due_date", "payment_plan_notes", "adjustment_reason", "internal_notes"].forEach((name) => setField(name, state[name] || ""));
    setField("manual_total_due_amount", moneyInput(state.manual_total_due_cents));
    const inputs = state.calculation_inputs || {};
    setField("calculation_cancellation_date", inputs.cancellation_date || calculation.cancellation_date || item.cancellation_date || "");
    setField("calculation_training_price_amount", inputs.training_price_amount || moneyInput(calculation.training_price_cents));
    setField("calculation_deductible_paid_amount", inputs.deductible_paid_amount || moneyInput(calculation.deductible_paid_cents));
    setField("calculation_total_training_hours", inputs.total_training_hours ?? calculation.total_training_hours ?? "");
    setField("calculation_delivered_hours", inputs.delivered_hours ?? calculation.delivered_hours ?? "");

    const calculationBanner = document.getElementById("cancellationCalculationBanner");
    calculationBanner.classList.toggle("is-error", Boolean(item.calculation_error || !item.calculation_complete));
    document.getElementById("cancellationCalculationRule").textContent = item.calculation_error || item.rule_label || "Calcul à finaliser";
    document.getElementById("cancellationCalculationBreakdown").textContent = item.calculation_complete
      ? `${item.penalty_rate || 0} % du coût initial${item.prorata_cents ? ` + ${money(item.prorata_cents)} de formation dispensée` : ""}`
      : "Complétez les informations manquantes avant de valider le montant.";
    updateFinancialDisplay(item);

    const paymentBalance = document.getElementById("cancellationPaymentBalance");
    paymentBalance.classList.toggle("is-alert", Boolean(item.refund_due_cents || item.overdue_days));
    if (item.refund_due_cents) {
      paymentBalance.textContent = `${money(item.refund_due_cents)} ont été versés en trop : remboursement à vérifier.`;
    } else if (item.remaining_cents) {
      paymentBalance.textContent = `${money(item.remaining_cents)} restent à encaisser sur ${money(item.effective_total_due_cents)}${item.overdue_days ? ` · échéance dépassée de ${item.overdue_days} jour(s)` : ""}.`;
    } else {
      paymentBalance.textContent = `Le dossier est couvert à hauteur de ${money(item.credited_total_cents)}.`;
    }

    paymentForm.elements.namedItem("paid_at").value = todayIso();
    paymentForm.elements.namedItem("amount").value = item.remaining_cents ? moneyInput(item.remaining_cents) : "";
    paymentForm.elements.namedItem("reference").value = "";
    paymentForm.elements.namedItem("note").value = "";
    contactForm.elements.namedItem("contacted_at").value = todayIso();
    contactForm.elements.namedItem("next_action_date").value = state.next_action_date || "";
    contactForm.elements.namedItem("note").value = "";

    renderPayments(item);
    renderContacts(item);
    renderTimeline(item);
    syncDecisionFields();
    caseForm.querySelectorAll("input,select,textarea").forEach((field) => {
      if (!field.matches('[name="manual_total_due_amount"]')) field.disabled = Boolean(pageData.is_read_only);
    });
    paymentForm.querySelectorAll("input,select,textarea,button").forEach((field) => { field.disabled = Boolean(pageData.is_read_only); });
    contactForm.querySelectorAll("input,select,textarea,button").forEach((field) => { field.disabled = Boolean(pageData.is_read_only); });
    if (saveButton) saveButton.disabled = Boolean(pageData.is_read_only);
    syncDecisionFields();
  }

  function activateTab(tab) {
    activeTab = tab;
    document.querySelectorAll("[data-cancellation-tab]").forEach((button) => {
      const active = button.dataset.cancellationTab === tab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-cancellation-panel]").forEach((panel) => {
      const active = panel.dataset.cancellationPanel === tab;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    if (saveButton) saveButton.hidden = !["case", "indemnity"].includes(tab);
  }

  document.querySelectorAll("[data-cancellation-tab]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.cancellationTab));
  });

  async function openDrawer(url) {
    const requestId = ++drawerRequest;
    currentItem = null;
    needsRefresh = false;
    activeTab = "case";
    if (layer) layer.hidden = false;
    document.body.classList.add("cancellation-drawer-open");
    if (loading) loading.hidden = false;
    if (body) body.hidden = true;
    if (footer) footer.hidden = true;
    if (drawerError) drawerError.hidden = true;
    activateTab("case");
    try {
      const payload = await requestJson(url, { method: "GET", headers: {} });
      if (requestId !== drawerRequest) return;
      renderItem(payload.item);
      loading.hidden = true;
      body.hidden = false;
      footer.hidden = false;
    } catch (error) {
      if (requestId !== drawerRequest) return;
      loading.hidden = true;
      drawerError.hidden = false;
      drawerError.querySelector("p").textContent = error.message;
    }
  }

  function closeDrawer() {
    drawerRequest += 1;
    if (layer) layer.hidden = true;
    document.body.classList.remove("cancellation-drawer-open");
    if (needsRefresh) window.location.reload();
  }

  document.querySelectorAll("[data-open-cancellation-case]").forEach((button) => {
    button.addEventListener("click", () => openDrawer(button.dataset.detailUrl));
  });
  document.querySelectorAll("[data-close-cancellation-drawer]").forEach((button) => button.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && layer && !layer.hidden) closeDrawer();
  });

  function setBusy(button, busy, busyText) {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = busyText;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  caseForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentItem || pageData.is_read_only) return;
    const payload = {
      case_status: fieldValue("case_status"),
      assigned_to: fieldValue("assigned_to"),
      origin: fieldValue("origin"),
      reason: fieldValue("reason"),
      request_received_at: fieldValue("request_received_at"),
      confirmation_received_at: fieldValue("confirmation_received_at"),
      next_action_date: fieldValue("next_action_date"),
      payment_due_date: fieldValue("payment_due_date"),
      reason_details: fieldValue("reason_details"),
      internal_notes: fieldValue("internal_notes"),
      decision: fieldValue("decision"),
      manual_total_due_amount: fieldValue("manual_total_due_amount"),
      adjustment_reason: fieldValue("adjustment_reason"),
      payment_terms: fieldValue("payment_terms"),
      payment_plan_notes: fieldValue("payment_plan_notes"),
      calculation_inputs: {
        cancellation_date: fieldValue("calculation_cancellation_date"),
        training_price_amount: fieldValue("calculation_training_price_amount"),
        deductible_paid_amount: fieldValue("calculation_deductible_paid_amount"),
        total_training_hours: fieldValue("calculation_total_training_hours"),
        delivered_hours: fieldValue("calculation_delivered_hours"),
      },
    };
    setBusy(saveButton, true, "Enregistrement…");
    try {
      const response = await requestJson(currentItem.update_url, { method: "POST", body: JSON.stringify(payload) });
      renderItem(response.item);
      activateTab(activeTab);
      needsRefresh = true;
      showToast("Le dossier d’annulation a bien été enregistré.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setBusy(saveButton, false);
    }
  });

  paymentForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentItem || pageData.is_read_only) return;
    const button = paymentForm.querySelector('button[type="submit"]');
    const formData = new FormData(paymentForm);
    setBusy(button, true, "Enregistrement…");
    try {
      const response = await requestJson(currentItem.payment_url, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(formData.entries())),
      });
      renderItem(response.item);
      activateTab("payments");
      needsRefresh = true;
      showToast("Le règlement a été ajouté au dossier.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setBusy(button, false);
    }
  });

  contactForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentItem || pageData.is_read_only) return;
    const button = contactForm.querySelector('button[type="submit"]');
    const formData = new FormData(contactForm);
    setBusy(button, true, "Enregistrement…");
    try {
      const response = await requestJson(currentItem.contact_url, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(formData.entries())),
      });
      renderItem(response.item);
      activateTab("contacts");
      needsRefresh = true;
      showToast("La relance a été ajoutée à l’historique.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setBusy(button, false);
    }
  });

  async function voidPayment(payment) {
    if (!currentItem || pageData.is_read_only) return;
    const reason = window.prompt("Pourquoi faut-il annuler ce règlement ?\nLe paiement restera visible dans l’historique.");
    if (reason === null) return;
    if (reason.trim().length < 3) {
      showToast("Précisez un motif d’au moins 3 caractères.", true);
      return;
    }
    try {
      const response = await requestJson(`${currentItem.payment_url}/${encodeURIComponent(payment.id)}/void`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      renderItem(response.item);
      activateTab("payments");
      needsRefresh = true;
      showToast("Le règlement a été annulé sans supprimer sa trace.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function refreshDraftCalculation() {
    if (!currentItem?.calculation_url) return;
    const params = new URLSearchParams({
      cancellation_date: fieldValue("calculation_cancellation_date"),
      training_price_amount: fieldValue("calculation_training_price_amount"),
      deductible_paid_amount: fieldValue("calculation_deductible_paid_amount"),
      total_training_hours: fieldValue("calculation_total_training_hours"),
      delivered_hours: fieldValue("calculation_delivered_hours"),
    });
    try {
      const response = await requestJson(`${currentItem.calculation_url}?${params.toString()}`, { method: "GET", headers: {} });
      const calculation = response.calculation || {};
      const banner = document.getElementById("cancellationCalculationBanner");
      banner.classList.toggle("is-error", !calculation.calculation_complete);
      document.getElementById("cancellationCalculationRule").textContent = calculation.rule_label || "Calcul à finaliser";
      document.getElementById("cancellationCalculationBreakdown").textContent = calculation.calculation_complete
        ? `${calculation.penalty_rate || 0} % du coût initial${calculation.prorata_cents ? ` + ${money(calculation.prorata_cents)} de formation dispensée` : ""}`
        : "Complétez le nombre d’heures dispensées avant de valider le montant.";
      updateFinancialDisplay(currentItem, calculation);
    } catch (error) {
      const banner = document.getElementById("cancellationCalculationBanner");
      banner.classList.add("is-error");
      document.getElementById("cancellationCalculationRule").textContent = error.message;
      document.getElementById("cancellationCalculationBreakdown").textContent = "Corrigez les valeurs indiquées pour poursuivre.";
    }
  }

  caseForm?.elements.namedItem("decision")?.addEventListener("change", syncDecisionFields);
  caseForm?.elements.namedItem("manual_total_due_amount")?.addEventListener("input", () => {
    if (currentItem) updateFinancialDisplay(currentItem);
  });
  ["calculation_cancellation_date", "calculation_training_price_amount", "calculation_deductible_paid_amount", "calculation_total_training_hours", "calculation_delivered_hours"].forEach((name) => {
    caseForm?.elements.namedItem(name)?.addEventListener("input", () => {
      window.clearTimeout(draftTimer);
      draftTimer = window.setTimeout(refreshDraftCalculation, 450);
    });
  });
})();
