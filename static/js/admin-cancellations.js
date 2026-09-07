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
    if (
      !pageData.initial_session_id
      && saved.quickFilter
      && quickButtons.some((button) => button.dataset.quickFilter === saved.quickFilter)
    ) quickFilter = saved.quickFilter;
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
      "État financier", "Périmètre", "Motif de mise hors suivi", "Indemnité retenue", "Déjà couvert", "Reste à encaisser",
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
        row.dataset.exportScope,
        row.dataset.exportExclusionReason,
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
  const reminderPreviewLayer = document.getElementById("cancellationReminderPreviewLayer");
  const reminderPreviewLoading = document.getElementById("cancellationReminderPreviewLoading");
  const reminderPreviewBody = document.getElementById("cancellationReminderPreviewBody");
  const reminderPreviewError = document.getElementById("cancellationReminderPreviewError");
  const reminderPreviewSend = document.getElementById("cancellationReminderSend");
  const reminderPreviewFrame = document.getElementById("cancellationReminderPreviewFrame");
  let currentItem = null;
  let currentReminderPreview = null;
  let caseDirty = false;
  let activeTab = "case";
  let needsRefresh = false;
  let toastTimer = null;
  let draftTimer = null;
  let drawerRequest = 0;
  let reminderPreviewRequest = 0;

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

  function setChecked(name, value) {
    const field = caseForm?.elements.namedItem(name);
    if (field) field.checked = Boolean(value);
  }

  function fieldValue(name) {
    const field = caseForm?.elements.namedItem(name);
    return field ? field.value.trim() : "";
  }

  function checkboxValue(name) {
    return Boolean(caseForm?.elements.namedItem(name)?.checked);
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
    const reminders = Array.isArray(item.reminders) ? item.reminders : [];
    if (count) count.textContent = String(contacts.length + reminders.length);
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

  function renderReminders(item) {
    const levels = Array.isArray(item.reminder_levels) ? item.reminder_levels : [];
    const reminders = Array.isArray(item.reminders) ? item.reminders : [];
    const notice = document.getElementById("cancellationReminderNotice");
    const historyCount = document.getElementById("cancellationReminderHistoryCount");
    const list = document.getElementById("cancellationReminderList");
    if (historyCount) historyCount.textContent = `${reminders.length} envoi${reminders.length > 1 ? "s" : ""}`;

    levels.forEach((level) => {
      const card = document.querySelector(`[data-cancellation-reminder-card="${level.level}"]`);
      const button = card?.querySelector("[data-cancellation-reminder-level]");
      const state = document.getElementById(`cancellationReminderState${level.level}`);
      if (button) {
        button.dataset.previewUrl = level.preview_url || "";
        button.dataset.serverAvailable = String(Boolean(level.available));
        button.disabled = !level.available;
        button.title = level.available ? `Prévisualiser ${String(level.label || "la relance").toLowerCase()}` : (level.blocked_reason || "Relance indisponible");
      }
      card?.classList.toggle("is-disabled", !level.available);
      if (state) {
        state.classList.toggle("is-sent", Boolean(level.sent_count));
        state.classList.toggle("is-blocked", !level.available);
        state.textContent = !level.available
          ? (level.blocked_reason || "Relance indisponible")
          : level.sent_count
            ? `Envoyée ${level.sent_count} fois · dernier envoi ${dateTimeLabel(level.last_sent_at)}`
            : "Jamais envoyée";
      }
    });

    if (notice) {
      const firstBlocked = levels.find((level) => !level.available);
      notice.classList.toggle("is-blocked", Boolean(firstBlocked));
      const copy = notice.querySelector("p");
      if (copy) {
        copy.replaceChildren();
        const strong = document.createElement("strong");
        strong.textContent = firstBlocked ? "Envoi indisponible pour ce dossier." : "Choisissez le niveau adapté au dossier.";
        copy.appendChild(strong);
        copy.append(document.createTextNode(firstBlocked
          ? ` ${firstBlocked.blocked_reason || "Vérifiez les informations du dossier."}`
          : " Les montants et l’échéance sont recalculés au moment de l’envoi."));
      }
    }

    if (!list) return;
    list.replaceChildren();
    if (!reminders.length) {
      const empty = document.createElement("div");
      empty.className = "cancellation-record-empty";
      empty.textContent = "Aucun e-mail de relance envoyé pour le moment.";
      list.appendChild(empty);
      return;
    }
    reminders.forEach((reminder) => {
      const level = Number(reminder.level || 0);
      const levelConfig = levels.find((entry) => Number(entry.level) === level) || {};
      list.appendChild(recordNode({
        icon: String(level || "@"),
        title: `${levelConfig.label || `Relance ${level}`} · ${levelConfig.tone || "E-mail"}`,
        meta: `${dateTimeLabel(reminder.sent_at)} · ${reminder.recipient || "Destinataire inconnu"} · ${reminder.sent_by || "Administrateur"}`,
        note: `${reminder.subject || ""}${reminder.deadline ? `\nÉchéance fixée au ${dateLabel(reminder.deadline)}` : ""}`,
        amount: money(reminder.remaining_cents),
        className: `cancellation-record--reminder is-level-${level}`,
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
    const payments = Number(
      item.raw_financials?.payments_received_cents ?? item.payments_received_cents ?? 0
    );
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
    const excluded = checkboxValue("excluded_from_follow_up");
    document.getElementById("cancellationRecapPenalty").textContent = money(penalty);
    document.getElementById("cancellationRecapProrata").textContent = money(prorata);
    document.getElementById("cancellationRecapContractual").textContent = money(contractual);
    document.getElementById("cancellationRecapDeductible").textContent = money(deductible);
    document.getElementById("cancellationRecapEffective").textContent = excluded ? "Non applicable" : money(effective);
    document.getElementById("cancellationRecapRemaining").textContent = excluded ? "Non applicable" : refund ? `${money(refund)} à rembourser` : money(remaining);
  }

  function syncDecisionFields() {
    const decision = fieldValue("decision");
    const excluded = checkboxValue("excluded_from_follow_up");
    const customField = caseForm?.elements.namedItem("manual_total_due_amount");
    const reasonField = caseForm?.elements.namedItem("adjustment_reason");
    if (customField) customField.disabled = pageData.is_read_only || excluded || decision !== "custom";
    if (reasonField) {
      reasonField.disabled = pageData.is_read_only || excluded;
      reasonField.required = !excluded && ["custom", "waived"].includes(decision);
    }
    if (currentItem) updateFinancialDisplay(currentItem);
  }

  function syncExclusionFields() {
    const excluded = checkboxValue("excluded_from_follow_up");
    const exclusionFields = document.getElementById("cancellationExclusionFields");
    const exclusionReason = caseForm?.elements.namedItem("exclusion_reason");
    if (exclusionFields) exclusionFields.hidden = !excluded;
    if (exclusionReason) exclusionReason.required = excluded;

    const indemnityPanel = document.querySelector('[data-cancellation-panel="indemnity"]');
    indemnityPanel?.querySelectorAll("input,select,textarea").forEach((field) => {
      field.disabled = Boolean(pageData.is_read_only || excluded);
    });
    paymentForm?.classList.toggle("is-disabled", excluded);
    paymentForm?.querySelectorAll("input,select,textarea,button").forEach((field) => {
      field.disabled = Boolean(pageData.is_read_only || excluded);
    });
    document.querySelectorAll("[data-cancellation-reminder-level]").forEach((button) => {
      button.disabled = excluded || button.dataset.serverAvailable !== "true";
    });
    const calculationBanner = document.getElementById("cancellationCalculationBanner");
    if (calculationBanner && currentItem) {
      calculationBanner.classList.toggle("is-excluded", excluded);
      calculationBanner.classList.toggle(
        "is-error",
        Boolean(!excluded && (currentItem.calculation_error || !currentItem.calculation_complete)),
      );
      document.getElementById("cancellationCalculationRule").textContent = excluded
        ? "Dossier hors suivi financier"
        : currentItem.calculation_error || currentItem.rule_label || "Calcul à finaliser";
      document.getElementById("cancellationCalculationBreakdown").textContent = excluded
        ? "Le calcul éventuel est conservé pour la traçabilité, sans alimenter les indicateurs."
        : currentItem.calculation_complete
          ? `${currentItem.penalty_rate || 0} % du coût initial${currentItem.prorata_cents ? ` + ${money(currentItem.prorata_cents)} de formation dispensée` : ""}`
          : "Complétez les informations manquantes avant de valider le montant.";
    }
    syncDecisionFields();
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
    document.getElementById("cancellationSummaryDue").textContent = item.excluded_from_follow_up ? "Non applicable" : money(item.effective_total_due_cents);
    document.getElementById("cancellationSummaryRule").textContent = item.excluded_from_follow_up ? (item.exclusion_reason_label || "Hors suivi financier") : (item.rule_label || "Calcul à finaliser");
    document.getElementById("cancellationSummaryPaid").textContent = item.excluded_from_follow_up ? "Non suivi" : money(item.credited_total_cents);
    document.getElementById("cancellationSummaryRemaining").textContent = item.excluded_from_follow_up ? "Aucun" : item.refund_due_cents ? `${money(item.refund_due_cents)} à rembourser` : money(item.remaining_cents);
    document.getElementById("cancellationSummaryDueDate").textContent = item.excluded_from_follow_up ? "Retiré des indicateurs" : item.payment_due_date ? `Échéance ${dateLabel(item.payment_due_date)}` : "Sans échéance";
    document.getElementById("cancellationOpenTrainee").href = item.trainee_url;
    document.getElementById("cancellationOpenTraineeCalculator").href = `${item.trainee_url}#cancellationIndemnityModal`;

    populateSelect(caseForm.elements.namedItem("case_status"), options.case_statuses, item.case_status);
    populateSelect(caseForm.elements.namedItem("origin"), options.origins, state.origin);
    populateSelect(
      caseForm.elements.namedItem("exclusion_reason"),
      [["", "Choisir un motif"], ...(options.exclusion_reasons || [])],
      state.exclusion_reason,
    );
    populateSelect(caseForm.elements.namedItem("reason"), options.reasons, state.reason);
    populateSelect(caseForm.elements.namedItem("decision"), options.decisions, state.decision);
    populateSelect(caseForm.elements.namedItem("payment_terms"), options.payment_terms, state.payment_terms);
    populateSelect(paymentForm.elements.namedItem("method"), options.payment_methods, "bank_transfer");
    populateSelect(contactForm.elements.namedItem("channel"), options.contact_channels, "email");
    populateSelect(contactForm.elements.namedItem("outcome"), options.contact_outcomes, "sent");

    setChecked("excluded_from_follow_up", item.excluded_from_follow_up);
    ["assigned_to", "reason_details", "exclusion_details", "request_received_at", "confirmation_received_at", "next_action_date", "payment_due_date", "payment_plan_notes", "adjustment_reason", "internal_notes"].forEach((name) => setField(name, state[name] || ""));
    setField("manual_total_due_amount", moneyInput(state.manual_total_due_cents));
    const inputs = state.calculation_inputs || {};
    setField("calculation_cancellation_date", inputs.cancellation_date || calculation.cancellation_date || item.cancellation_date || "");
    setField("calculation_training_price_amount", inputs.training_price_amount || moneyInput(calculation.training_price_cents));
    setField("calculation_deductible_paid_amount", inputs.deductible_paid_amount || moneyInput(calculation.deductible_paid_cents));
    setField("calculation_total_training_hours", inputs.total_training_hours ?? calculation.total_training_hours ?? "");
    setField("calculation_delivered_hours", inputs.delivered_hours ?? calculation.delivered_hours ?? "");

    const calculationBanner = document.getElementById("cancellationCalculationBanner");
    calculationBanner.classList.toggle("is-error", Boolean(!item.excluded_from_follow_up && (item.calculation_error || !item.calculation_complete)));
    calculationBanner.classList.toggle("is-excluded", Boolean(item.excluded_from_follow_up));
    document.getElementById("cancellationCalculationRule").textContent = item.excluded_from_follow_up
      ? "Dossier hors suivi financier"
      : item.calculation_error || item.rule_label || "Calcul à finaliser";
    document.getElementById("cancellationCalculationBreakdown").textContent = item.excluded_from_follow_up
      ? "Le calcul éventuel est conservé pour la traçabilité, sans alimenter les indicateurs."
      : item.calculation_complete
        ? `${item.penalty_rate || 0} % du coût initial${item.prorata_cents ? ` + ${money(item.prorata_cents)} de formation dispensée` : ""}`
        : "Complétez les informations manquantes avant de valider le montant.";
    updateFinancialDisplay(item);

    const paymentBalance = document.getElementById("cancellationPaymentBalance");
    paymentBalance.classList.toggle("is-alert", Boolean(!item.excluded_from_follow_up && (item.refund_due_cents || item.overdue_days)));
    paymentBalance.classList.toggle("is-excluded", Boolean(item.excluded_from_follow_up));
    if (item.excluded_from_follow_up) {
      const recorded = Number(item.raw_financials?.payments_received_cents || 0);
      paymentBalance.textContent = `Ce dossier est hors suivi financier : aucun règlement n’est attendu ni comptabilisé${recorded ? `. ${money(recorded)} restent visibles dans l’historique et peuvent être annulés en cas d’erreur` : ""}.`;
    } else if (item.refund_due_cents) {
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
    renderReminders(item);
    renderTimeline(item);
    syncDecisionFields();
    caseForm.querySelectorAll("input,select,textarea").forEach((field) => {
      if (!field.matches('[name="manual_total_due_amount"]')) field.disabled = Boolean(pageData.is_read_only);
    });
    paymentForm.querySelectorAll("input,select,textarea,button").forEach((field) => { field.disabled = Boolean(pageData.is_read_only); });
    contactForm.querySelectorAll("input,select,textarea,button").forEach((field) => { field.disabled = Boolean(pageData.is_read_only); });
    if (saveButton) saveButton.disabled = Boolean(pageData.is_read_only);
    syncExclusionFields();
    caseDirty = false;
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
    closeReminderPreview();
    if (layer) layer.hidden = true;
    document.body.classList.remove("cancellation-drawer-open");
    if (needsRefresh) window.location.reload();
  }

  document.querySelectorAll("[data-open-cancellation-case]").forEach((button) => {
    button.addEventListener("click", () => openDrawer(button.dataset.detailUrl));
  });
  document.querySelectorAll("[data-close-cancellation-drawer]").forEach((button) => button.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (reminderPreviewLayer && !reminderPreviewLayer.hidden) {
      closeReminderPreview();
    } else if (layer && !layer.hidden) {
      closeDrawer();
    }
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

  function closeReminderPreview() {
    reminderPreviewRequest += 1;
    currentReminderPreview = null;
    if (reminderPreviewLayer) reminderPreviewLayer.hidden = true;
    if (reminderPreviewFrame) reminderPreviewFrame.srcdoc = "";
    if (reminderPreviewSend) {
      reminderPreviewSend.disabled = true;
      reminderPreviewSend.textContent = "Envoyer la relance";
      reminderPreviewSend.classList.add("cancellation-btn--primary");
      reminderPreviewSend.classList.remove("cancellation-btn--danger");
      delete reminderPreviewSend.dataset.sendUrl;
    }
  }

  async function openReminderPreview(button) {
    if (caseDirty) {
      showToast("Enregistrez d’abord les modifications du dossier afin de prévisualiser le bon montant.", true);
      return;
    }
    if (!currentItem || !button?.dataset.previewUrl || button.disabled) return;
    const requestId = ++reminderPreviewRequest;
    currentReminderPreview = null;
    reminderPreviewLayer.hidden = false;
    reminderPreviewLoading.hidden = false;
    reminderPreviewBody.hidden = true;
    reminderPreviewError.hidden = true;
    reminderPreviewSend.disabled = true;
    if (reminderPreviewFrame) reminderPreviewFrame.srcdoc = "";
    try {
      const payload = await requestJson(button.dataset.previewUrl, { method: "GET", headers: {} });
      if (requestId !== reminderPreviewRequest) return;
      const preview = payload.preview || {};
      currentReminderPreview = preview;
      document.getElementById("cancellationReminderPreviewTone").textContent = `${preview.label || "Relance"} · ${preview.tone || ""}`;
      document.getElementById("cancellationReminderPreviewTitle").textContent = `Prévisualisation de la ${String(preview.label || "relance").toLowerCase()}`;
      document.getElementById("cancellationReminderPreviewRecipient").textContent = preview.recipient || "—";
      document.getElementById("cancellationReminderPreviewAmount").textContent = preview.remaining_label || "—";
      document.getElementById("cancellationReminderPreviewDeadline").textContent = preview.deadline_label || "—";
      document.getElementById("cancellationReminderPreviewSubject").textContent = preview.subject || "—";
      const warning = document.getElementById("cancellationReminderPreviewWarning");
      const warningMessages = [];
      if (preview.sequence_warning) {
        warningMessages.push(`Attention : ${preview.sequence_warning} Vous pouvez continuer si une relance a été effectuée par un autre canal.`);
      }
      if (preview.legal_warning) warningMessages.push(preview.legal_warning);
      warning.hidden = !warningMessages.length;
      warning.textContent = warningMessages.join(" ");
      if (reminderPreviewFrame) reminderPreviewFrame.srcdoc = preview.html || "";
      reminderPreviewSend.dataset.sendUrl = preview.send_url || "";
      reminderPreviewSend.textContent = preview.level === 3 ? "Envoyer la mise en demeure" : `Envoyer la relance ${preview.level || ""}`;
      reminderPreviewSend.classList.toggle("cancellation-btn--danger", preview.level === 3);
      reminderPreviewSend.classList.toggle("cancellation-btn--primary", preview.level !== 3);
      reminderPreviewSend.disabled = Boolean(pageData.is_read_only || !preview.send_url);
      document.getElementById("cancellationReminderPreviewConfirmation").textContent = pageData.is_read_only
        ? "Mode consultation : l’envoi est désactivé."
        : "L’e-mail ne partira qu’après votre confirmation.";
      reminderPreviewLoading.hidden = true;
      reminderPreviewBody.hidden = false;
    } catch (error) {
      if (requestId !== reminderPreviewRequest) return;
      reminderPreviewLoading.hidden = true;
      reminderPreviewError.hidden = false;
      reminderPreviewError.querySelector("p").textContent = error.message;
    }
  }

  document.querySelectorAll("[data-cancellation-reminder-level]").forEach((button) => {
    button.addEventListener("click", () => openReminderPreview(button));
  });
  document.querySelectorAll("[data-close-cancellation-reminder-preview]").forEach((button) => {
    button.addEventListener("click", closeReminderPreview);
  });
  reminderPreviewSend?.addEventListener("click", async () => {
    if (!currentReminderPreview || pageData.is_read_only || !reminderPreviewSend.dataset.sendUrl) return;
    const sendUrl = reminderPreviewSend.dataset.sendUrl;
    const level = Number(currentReminderPreview.level || 0);
    setBusy(reminderPreviewSend, true, level === 3 ? "Envoi de la mise en demeure…" : `Envoi de la relance ${level}…`);
    try {
      const response = await requestJson(sendUrl, {
        method: "POST",
        body: JSON.stringify({ preview_token: currentReminderPreview.preview_token || "" }),
      });
      closeReminderPreview();
      renderItem(response.item);
      activateTab("contacts");
      needsRefresh = true;
      showToast(response.message || `La relance ${level} a bien été envoyée.`);
    } catch (error) {
      showToast(error.message, true);
      setBusy(reminderPreviewSend, false);
    }
  });

  caseForm?.addEventListener("input", () => { caseDirty = true; });
  caseForm?.addEventListener("change", () => { caseDirty = true; });

  caseForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentItem || pageData.is_read_only) return;
    const payload = {
      case_status: fieldValue("case_status"),
      assigned_to: fieldValue("assigned_to"),
      origin: fieldValue("origin"),
      excluded_from_follow_up: checkboxValue("excluded_from_follow_up"),
      exclusion_reason: fieldValue("exclusion_reason"),
      exclusion_details: fieldValue("exclusion_details"),
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
    if (!currentItem || pageData.is_read_only || checkboxValue("excluded_from_follow_up")) return;
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
      syncExclusionFields();
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
  caseForm?.elements.namedItem("excluded_from_follow_up")?.addEventListener("change", syncExclusionFields);
  caseForm?.elements.namedItem("origin")?.addEventListener("change", (event) => {
    if (event.target.value !== "training_center") return;
    const excludedField = caseForm?.elements.namedItem("excluded_from_follow_up");
    const reasonField = caseForm?.elements.namedItem("exclusion_reason");
    if (excludedField && !excludedField.checked) excludedField.checked = true;
    if (reasonField && !reasonField.value) reasonField.value = "center_initiated";
    syncExclusionFields();
  });
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
