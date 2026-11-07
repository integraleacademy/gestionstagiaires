const sheetContext = JSON.parse(document.getElementById("traineeSheetContext").textContent);
const rosterReturnLink = document.querySelector("[data-return-to-roster]");
if (rosterReturnLink && document.referrer) {
  const previous = new URL(document.referrer);
  if (previous.origin === location.origin &&
      [rosterReturnLink.pathname, rosterReturnLink.dataset.allVtc].includes(previous.pathname)) {
    rosterReturnLink.href = previous.pathname + previous.search;
  }
}
const vaeResetDossierForm = document.getElementById("vaeResetDossierForm");
const vaeResetConfirmModal = document.getElementById("vaeResetConfirmModal");
const vaeResetConfirmYes = document.getElementById("vaeResetConfirmYes");
const vaeResetConfirmNo = document.getElementById("vaeResetConfirmNo");
let vaeResetConfirmed = false;

if(vaeResetDossierForm){
  vaeResetDossierForm.addEventListener("submit", (event)=>{
    if(vaeResetConfirmed) return;
    event.preventDefault();
    if(!vaeResetConfirmModal || !vaeResetConfirmYes || !vaeResetConfirmNo){
      if(window.confirm("Confirmez-vous la réinitialisation du livret 1 ? Tout le contenu du dossier de faisabilité VAE et les justificatifs seront supprimés.")){
        vaeResetConfirmed = true;
        vaeResetDossierForm.submit();
      }
      return;
    }
    openModal("vaeResetConfirmModal");
    vaeResetConfirmYes.focus();
  });
}

if(vaeResetConfirmNo){
  vaeResetConfirmNo.addEventListener("click", ()=>{
    closeModal("vaeResetConfirmModal");
  });
}

if(vaeResetConfirmYes && vaeResetDossierForm){
  vaeResetConfirmYes.addEventListener("click", ()=>{
    vaeResetConfirmed = true;
    vaeResetConfirmYes.disabled = true;
    vaeResetConfirmYes.textContent = "Réinitialisation…";
    vaeResetDossierForm.submit();
  });
}

const yousignSignatureProgress = document.getElementById("yousignSignatureProgress");
window.showConventionTransmissionProgress = function(){
  if(!yousignSignatureProgress) return;
  yousignSignatureProgress.classList.add("is-visible");
  yousignSignatureProgress.setAttribute("aria-hidden", "false");
  document.body.classList.add("yousign-sync-is-running");
};
window.hideConventionTransmissionProgress = function(){
  if(!yousignSignatureProgress) return;
  yousignSignatureProgress.classList.remove("is-visible");
  yousignSignatureProgress.setAttribute("aria-hidden", "true");
  document.body.classList.remove("yousign-sync-is-running");
};


document.addEventListener("submit", async (event)=>{
  const form = event.target.closest('form[data-convention-preview-required="true"]');
  if(!form || form.dataset.conventionPreviewConfirmed === "1") return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const previewUrl = form.dataset.conventionPreviewUrl || "";
  if(previewUrl){ await window.openConventionPreview?.(previewUrl); }
  const message = "La prévisualisation est fermée. Confirmer l’envoi Yousign maintenant ?";
  const ok = window.AppModal
    ? await window.AppModal.confirm({type:"info", title:"Vérifier la convention avant envoi", message, primaryText:"Envoyer maintenant", secondaryText:"Annuler", tertiaryText:"Envoyer plus tard"})
    : window.confirm(message);
  if(ok){
    form.dataset.conventionPreviewConfirmed = "1";
    form.requestSubmit ? form.requestSubmit() : form.submit();
  }
}, true);

document.addEventListener("submit", async (event)=>{
  const form = event.target.closest('form[data-yousign-force-new="true"]');
  if(!form || form.dataset.yousignRegenerateConfirmed === "1") return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const message = "Annuler la demande Yousign actuelle et générer une nouvelle convention ? L’ancienne signature ne sera plus considérée comme valide.";
  const ok = window.AppModal
    ? await window.AppModal.confirm({type:"warning", title:"Annuler et régénérer la convention", message, primaryText:"Annuler et régénérer", secondaryText:"Conserver"})
    : window.confirm(message);
  if(ok){
    form.dataset.yousignRegenerateConfirmed = "1";
    form.requestSubmit ? form.requestSubmit() : form.submit();
  }
}, true);

document.querySelectorAll(".automation-loading-form").forEach((form)=>{
  form.addEventListener("submit", async (event)=>{
    const btn = form.querySelector("button");
    const isConventionTransmission = form.dataset.conventionTransmissionForm === "true" || /\/convention\/(?:yousign|signature\/create)(?:$|[?#])/.test(form.action || "");
    if(isConventionTransmission){
      event.preventDefault();
      const conventionPayload = await requestVaeConventionTransmission();
      if(!conventionPayload) return;
      if(conventionPayload.company_convention_url){ window.location.href = conventionPayload.company_convention_url; return; }
      if(conventionPayload.send_convention === false){
        try{ await saveVaeConventionFinancing(conventionPayload); }catch(error){ alert(error.message || "Impossible de sauvegarder les montants de financement."); }
        return;
      }
      if(btn){ btn.disabled = true; btn.setAttribute("aria-busy", "true"); btn.dataset.originalText = btn.textContent; btn.textContent = "Transmission…"; }
      const sent = await sendVaeConventionSignature(conventionPayload, {forceNew: form.dataset.yousignForceNew === "true"});
      if(!sent && btn){ btn.disabled = false; btn.removeAttribute("aria-busy"); btn.textContent = btn.dataset.originalText || "Réessayer"; }
      return;
    }
    if(btn){ btn.disabled = true; btn.setAttribute("aria-busy", "true"); btn.dataset.originalText = btn.textContent; btn.textContent = "Traitement…"; }
    if(form.action.includes("/automation/")){
      event.preventDefault();
      try{
        const response = await fetch(form.action, {method: "POST", headers: {"X-Requested-With": "fetch"}});
        const result = await response.json().catch(()=>({ok:false,error:"Réponse serveur invalide."}));
        if(!response.ok || !result.ok) throw new Error(result.error || "Action impossible.");
        window.location.reload();
      }catch(error){
        if(isConventionTransmission && typeof window.hideConventionTransmissionProgress === "function"){
          window.hideConventionTransmissionProgress();
        }
        alert(error.message || "Action impossible.");
        if(btn){ btn.disabled = false; btn.removeAttribute("aria-busy"); btn.textContent = btn.dataset.originalText || "Réessayer"; }
      }
    }
  });
});
const btnAutomationSendEntryAttestation = document.getElementById("btnAutomationSendEntryAttestation");
if(btnAutomationSendEntryAttestation){
  btnAutomationSendEntryAttestation.addEventListener("click", async ()=>{
    if(btnAutomationSendEntryAttestation.disabled) return;
    const original = btnAutomationSendEntryAttestation.textContent;
    btnAutomationSendEntryAttestation.disabled = true;
    btnAutomationSendEntryAttestation.setAttribute("aria-busy", "true");
    btnAutomationSendEntryAttestation.textContent = "Envoi…";
    try{
      const response = await fetch(sheetContext.entryAttestationUrl, {method:"POST", headers:{"Content-Type":"application/json"}});
      const result = await response.json().catch(()=>({ok:false,error:"Réponse serveur invalide."}));
      if(!response.ok || !result.ok) throw new Error(result.error || "Erreur lors de l’envoi de l’attestation d’entrée.");
      window.location.reload();
    }catch(error){
      alert(error.message || "Erreur lors de l’envoi de l’attestation d’entrée.");
      btnAutomationSendEntryAttestation.disabled = false;
      btnAutomationSendEntryAttestation.removeAttribute("aria-busy");
      btnAutomationSendEntryAttestation.textContent = original;
    }
  });
}
const btnAutomationSendEndAttestation = document.getElementById("btnAutomationSendEndAttestation");
if(btnAutomationSendEndAttestation){
  btnAutomationSendEndAttestation.addEventListener("click", async ()=>{
    if(btnAutomationSendEndAttestation.disabled) return;
    const original = btnAutomationSendEndAttestation.textContent;
    btnAutomationSendEndAttestation.disabled = true;
    btnAutomationSendEndAttestation.setAttribute("aria-busy", "true");
    btnAutomationSendEndAttestation.textContent = "Envoi…";
    try{
      const response = await fetch(sheetContext.endAttestationUrl, {method:"POST", headers:{"Content-Type":"application/json"}});
      const result = await response.json().catch(()=>({ok:false,error:"Réponse serveur invalide."}));
      if(!response.ok || !result.ok) throw new Error(result.error || "Erreur lors de l’envoi de l’attestation de fin.");
      window.location.reload();
    }catch(error){
      alert(error.message || "Erreur lors de l’envoi de l’attestation de fin.");
      btnAutomationSendEndAttestation.disabled = false;
      btnAutomationSendEndAttestation.removeAttribute("aria-busy");
      btnAutomationSendEndAttestation.textContent = original;
    }
  });
}

const btnAutomationSendConvocation = document.getElementById("btnAutomationSendConvocation");
if(btnAutomationSendConvocation){
  btnAutomationSendConvocation.addEventListener("click", async ()=>{
    if(btnAutomationSendConvocation.disabled) return;
    const original = btnAutomationSendConvocation.textContent;
    btnAutomationSendConvocation.disabled = true;
    btnAutomationSendConvocation.setAttribute("aria-busy", "true");
    btnAutomationSendConvocation.textContent = "Envoi…";
    try{
      const response = await fetch(sheetContext.convocationUrl, {method:"POST", headers:{"Content-Type":"application/json"}});
      const result = await response.json().catch(()=>({ok:false,error:"Réponse serveur invalide."}));
      if(!response.ok || !result.ok) throw new Error(result.error || "Erreur lors de l’envoi de la convocation.");
      window.location.reload();
    }catch(error){
      alert(error.message || "Erreur lors de l’envoi de la convocation.");
      btnAutomationSendConvocation.disabled = false;
      btnAutomationSendConvocation.removeAttribute("aria-busy");
      btnAutomationSendConvocation.textContent = original;
    }
  });
}

  // =========================
// Financement details autosave + totals
// =========================
const financementDetails = document.getElementById("financementDetails");
if(financementDetails){
  const cpfAmount = document.getElementById("cpfAmount");
  const personalAmount = document.getElementById("personalAmount");
  const otherAmount = document.getElementById("otherAmount");
  const trainingPrice = document.getElementById("trainingPrice");
  const cashPaymentEnabled = document.getElementById("cashPaymentEnabled");
  const cashPaymentAmount = document.getElementById("cashPaymentAmount");
  const cashPaymentAmountWrap = document.getElementById("cashPaymentAmountWrap");
  const cashPaymentSettled = document.getElementById("cashPaymentSettled");
  const cashPaymentSettlementDetails = document.getElementById("cashPaymentSettlementDetails");
  const cashPaymentSettledDate = document.getElementById("cashPaymentSettledDate");
  const cashPaymentSettledComment = document.getElementById("cashPaymentSettledComment");
  const excludeFromSalesTracking = document.getElementById("excludeFromSalesTracking");
  const salesTrackingAmount = document.getElementById("salesTrackingAmount");
  const cashPaymentHint = document.getElementById("cashPaymentHint");
  const cashPaymentInstallmentsList = document.getElementById("cashPaymentInstallmentsList");
  const cashPaymentAddInstallmentBtn = document.getElementById("cashPaymentAddInstallmentBtn");
  const rawCashPaymentInstallments = sheetContext.cashInstallments;
  const initialCashPaymentInstallments = Array.isArray(rawCashPaymentInstallments)
    ? rawCashPaymentInstallments
    : [];
  const totalLine = document.getElementById("paymentTotalLine");
  const diffLine = document.getElementById("paymentDiffLine");
  const isReadOnly = financementDetails.getAttribute("data-read-only") === "1";

  const debounceMap = {};

  const parseAmount = (value) => {
    const normalized = (value || "").toString().replace(",", ".").trim();
    const n = parseFloat(normalized);
    return Number.isNaN(n) ? 0 : n;
  };
  let cashPaymentInstallments = initialCashPaymentInstallments.map((item)=>({
    amount: parseAmount(item?.amount),
    date: (item?.date || "").toString().trim(),
  }));

  const formatEuros = (value) => {
    const rounded = Math.round(value * 100) / 100;
    return rounded.toLocaleString("fr-FR", {
      minimumFractionDigits: rounded % 1 === 0 ? 0 : 2,
      maximumFractionDigits: 2,
    });
  };

  const computeDefaultPrice = () => {
    const dataDefault = parseAmount(financementDetails.getAttribute("data-default-price"));
    if (dataDefault > 0) return dataDefault;
    const trainingType = (financementDetails.getAttribute("data-training-type") || "").toUpperCase();
    if (trainingType === "A3P") return 4200;
    if (trainingType === "APS") return 1650;
    if (trainingType === "DIRIGEANT INITIAL") return 4300;
    if (trainingType === "DIRIGEANT VAE") return 3800;
    if (trainingType.includes("VTC")) return 1500;
    if (trainingType.includes("SSIAP")) return 980;
    return 0;
  };

  const renderTotals = () => {
    if(!totalLine) return;
    const cpfVal = parseAmount(cpfAmount?.value);
    const personalVal = parseAmount(personalAmount?.value);
    const otherVal = parseAmount(otherAmount?.value);
    const total = cpfVal + personalVal + otherVal;

    const priceRaw = parseAmount(trainingPrice?.value);
    const price = priceRaw > 0 ? priceRaw : computeDefaultPrice();

    totalLine.textContent = `TOTAL (calcul automatique) : ${formatEuros(total)} € / ${formatEuros(price)} € (prix de la formation).`;

    if(diffLine){
      const diff = price - total;
      diffLine.textContent = `Différence de : ${formatEuros(diff)} €`;
      diffLine.style.color = diff === 0 ? "#16a34a" : "#dc2626";
      diffLine.style.fontWeight = "700";
    }
  };

  const setupAutosave = (input, field) => {
    if(!input || isReadOnly) return;
    input.addEventListener("input", ()=>{
      renderTotals();
      if(debounceMap[field]) clearTimeout(debounceMap[field]);
      debounceMap[field] = setTimeout(async ()=>{
        try{
          await updateTrainee({ [field]: input.value });
          window.dispatchEvent(new CustomEvent("qonto-billing-refresh", { detail: { field } }));
        }catch(e){
          console.error("Erreur sauvegarde financement", field);
        }
      }, 450);
    });
  };

  setupAutosave(cpfAmount, "cpf_amount");
  setupAutosave(personalAmount, "personal_amount");
  setupAutosave(otherAmount, "other_amount");
  setupAutosave(trainingPrice, "training_price");
  setupAutosave(cashPaymentAmount, "cash_payment_amount");
  setupAutosave(cashPaymentSettledDate, "cash_payment_settled_date");
  setupAutosave(cashPaymentSettledComment, "cash_payment_settled_comment");
  setupAutosave(salesTrackingAmount, "sales_tracking_amount");

  if(excludeFromSalesTracking && !isReadOnly){
    excludeFromSalesTracking.addEventListener("change", async ()=>{
      try{
        await updateTrainee({ exclude_from_sales_tracking: excludeFromSalesTracking.checked });
      }catch(e){
        console.error("Erreur sauvegarde exclusion suivi des ventes");
      }
    });
  }

  const getCashInstallmentsTotal = () => {
    return cashPaymentInstallments.reduce((sum, item)=> sum + parseAmount(item?.amount), 0);
  };
  window.getFinanceCashInstallmentsTotal = getCashInstallmentsTotal;
  window.getFinanceCashInstallments = () => cashPaymentInstallments.map(item => ({...item}));

  const collectCashInstallmentsPayload = () => {
    return cashPaymentInstallments
      .map((item)=>({
        amount: Math.round(parseAmount(item?.amount) * 100) / 100,
        date: (item?.date || "").trim(),
      }))
      .filter((item)=> item.amount > 0 || item.date);
  };

  const syncCashSettledFromInstallments = async () => {
    if(!cashPaymentEnabled?.checked || !cashPaymentSettled || !cashPaymentAmount) return;
    const targetAmount = parseAmount(cashPaymentAmount.value);
    const paidAmount = getCashInstallmentsTotal();
    const isSettledFromInstallments = targetAmount > 0 && Math.abs(paidAmount - targetAmount) < 0.01;
    const settledChanged = cashPaymentSettled.checked !== isSettledFromInstallments;
    cashPaymentSettled.checked = isSettledFromInstallments;
    if(cashPaymentSettledDate && isSettledFromInstallments){
      const latestDate = cashPaymentInstallments
        .map((item)=> (item?.date || "").trim())
        .filter(Boolean)
        .sort()
        .slice(-1)[0] || "";
      cashPaymentSettledDate.value = latestDate;
    }else if(cashPaymentSettledDate && !isSettledFromInstallments){
      cashPaymentSettledDate.value = "";
    }
    renderCashPaymentState();
    if(!isReadOnly && (settledChanged || cashPaymentSettledDate)){
      try{
        await updateTrainee({
          cash_payment_settled: cashPaymentSettled.checked,
          cash_payment_settled_date: cashPaymentSettledDate?.value || "",
        });
      }catch(e){
        console.error("Erreur synchronisation règlement espèces");
      }
    }
  };

  const saveCashInstallments = async () => {
    if(isReadOnly) return;
    try{
      await updateTrainee({ cash_payment_installments: collectCashInstallmentsPayload() });
      await syncCashSettledFromInstallments();
    }catch(e){
      console.error("Erreur sauvegarde versements espèces");
    }
  };

  const renderCashInstallments = () => {
    if(!cashPaymentInstallmentsList) return;
    cashPaymentInstallmentsList.innerHTML = "";
    cashPaymentInstallments.forEach((item, index)=>{
      const row = document.createElement("div");
      row.style.display = "grid";
      row.style.gridTemplateColumns = isReadOnly ? "1fr 1fr" : "1fr 1fr auto";
      row.style.gap = "8px";

      const amountInput = document.createElement("input");
      amountInput.type = "number";
      amountInput.min = "0";
      amountInput.step = "0.01";
      amountInput.placeholder = "Montant";
      amountInput.value = item.amount > 0 ? item.amount : "";
      amountInput.disabled = isReadOnly;
      amountInput.addEventListener("change", async ()=>{
        cashPaymentInstallments[index].amount = parseAmount(amountInput.value);
        await saveCashInstallments();
      });

      const dateInput = document.createElement("input");
      dateInput.type = "date";
      dateInput.value = item.date || "";
      dateInput.disabled = isReadOnly;
      dateInput.addEventListener("change", async ()=>{
        cashPaymentInstallments[index].date = (dateInput.value || "").trim();
        await saveCashInstallments();
      });

      row.appendChild(amountInput);
      row.appendChild(dateInput);

      if(!isReadOnly){
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "btn btn-ghost";
        removeBtn.textContent = "Supprimer";
        removeBtn.addEventListener("click", async ()=>{
          cashPaymentInstallments.splice(index, 1);
          renderCashInstallments();
          await saveCashInstallments();
        });
        row.appendChild(removeBtn);
      }

      cashPaymentInstallmentsList.appendChild(row);
    });
    if(cashPaymentInstallments.length === 0){
      const empty = document.createElement("div");
      empty.className = "hint";
      empty.textContent = "Aucun versement saisi.";
      cashPaymentInstallmentsList.appendChild(empty);
    }
  };

  if(cashPaymentAddInstallmentBtn && !isReadOnly){
    cashPaymentAddInstallmentBtn.addEventListener("click", ()=>{
      cashPaymentInstallments.push({ amount: 0, date: "" });
      renderCashInstallments();
    });
  }

  const renderCashPaymentState = () => {
    if(!cashPaymentEnabled) return;
    if(cashPaymentAmountWrap){
      cashPaymentAmountWrap.style.display = cashPaymentEnabled.checked ? "flex" : "none";
    }
    if(cashPaymentSettlementDetails){
      cashPaymentSettlementDetails.style.display = "none";
    }
    if(cashPaymentHint){
      const amount = parseAmount(cashPaymentAmount?.value);
      const paid = getCashInstallmentsTotal();
      if(cashPaymentEnabled.checked && amount <= 0){
        cashPaymentHint.textContent = "Renseigne le montant qui sera réglé en espèces.";
        cashPaymentHint.style.color = "#dc2626";
      }else if(cashPaymentEnabled.checked && cashPaymentSettled?.checked){
        const settledDate = (cashPaymentSettledDate?.value || "").trim();
        const dateHint = settledDate ? ` le ${formatIsoDateFr(settledDate)}` : "";
        cashPaymentHint.textContent = `${formatEuros(paid)} € réglés en espèces${dateHint}.`;
        cashPaymentHint.style.color = "#16a34a";
      }else if(cashPaymentEnabled.checked){
        const remaining = Math.max(amount - paid, 0);
        cashPaymentHint.textContent = `${formatEuros(remaining)} € restants à régler en espèces (${formatEuros(paid)} € versés).`;
        cashPaymentHint.style.color = "#d97706";
      }else{
        cashPaymentHint.textContent = "";
      }
    }
    window.refreshFinanceDashboard?.();
  };

  if(cashPaymentEnabled && !isReadOnly){
    cashPaymentEnabled.addEventListener("change", async ()=>{
      if(!cashPaymentEnabled.checked && cashPaymentSettled){
        cashPaymentSettled.checked = false;
      }
      renderCashPaymentState();
      try{
        const payload = { cash_payment_enabled: cashPaymentEnabled.checked };
        if(!cashPaymentEnabled.checked){
          payload.cash_payment_settled = false;
        }
        await updateTrainee(payload);
      }catch(e){
        console.error("Erreur sauvegarde paiement espèces");
      }
    });
  }

  if(cashPaymentSettled && !isReadOnly){
    cashPaymentSettled.addEventListener("change", async ()=>{
      renderCashPaymentState();
      try{
        await updateTrainee({ cash_payment_settled: cashPaymentSettled.checked });
      }catch(e){
        console.error("Erreur sauvegarde statut règlement espèces");
      }
    });
  }

  [cpfAmount, personalAmount, otherAmount, trainingPrice].forEach((input)=>{
    if(!input) return;
    input.addEventListener("change", renderTotals);
  });
  cashPaymentAmount?.addEventListener("input", renderCashPaymentState);
  cashPaymentAmount?.addEventListener("change", async ()=>{
    renderCashPaymentState();
    await syncCashSettledFromInstallments();
  });
  cashPaymentSettledDate?.addEventListener("change", renderCashPaymentState);

  renderCashInstallments();
  renderTotals();
  renderCashPaymentState();
}

  function toClassSafe(s){
  return (s || "").toString().trim().toLowerCase().replace(/\s+/g,"_");
}

function applyStatusPill(selectEl){
  if(!selectEl) return;
  selectEl.classList.add("status-pill");

  [...selectEl.classList].forEach(c=>{
    if(c.startsWith("is-")) selectEl.classList.remove(c);
  });

  const v = toClassSafe(selectEl.value);
  if(v) selectEl.classList.add("is-" + v);
  else selectEl.classList.add("is-soon");
}

function setDossierPill(status){
  const pill = document.getElementById("dossierStatusPill");
  if(!pill) return;
  pill.classList.remove("pill-green", "pill-red");
  const isComplete = status === "complete";
  pill.classList.add(isComplete ? "pill-green" : "pill-red");
  pill.textContent = isComplete ? "DOSSIER COMPLET" : "DOSSIER INCOMPLET";
}

function formatIsoDateFr(isoDate){
  const raw = (isoDate || "").toString().trim();
  if(!raw) return "";
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if(!m) return raw;
  return `${m[3]}/${m[2]}/${m[1]}`;
}

function updateDocsRelanceState(status, plannedDateIso){
  const btn = document.getElementById("btnDocsRelance");
  const isComplete = status === "complete";
  const schedule = document.getElementById("docsAutomaticSchedule");
  if(schedule) schedule.style.display = isComplete ? "none" : "";
  if(btn){
    btn.disabled = isComplete;
    btn.classList.toggle("btn-disabled-muted", isComplete);
  }

  const hint = document.getElementById("docsRelancePlannedHint");
  const dateEl = document.getElementById("docsRelancePlannedDate");
  if(dateEl){
    const formatted = formatIsoDateFr(plannedDateIso);
    dateEl.textContent = formatted;
    if(hint){
      hint.style.display = formatted ? "" : "none";
    }
  }
}

  // util modal (si ton base.html fournit déjà openModal/closeModal, ça marchera aussi)
  function openModal(id){
    document.getElementById(id).setAttribute("aria-hidden","false");
    document.getElementById(id).classList.add("show");
  }
  function closeModal(id){ document.getElementById(id).setAttribute("aria-hidden","true"); document.getElementById(id).classList.remove("show"); }

  function confirmTransferTrainee(formEl){
    const select = formEl?.querySelector('select[name="target_session_id"]');
    if(!select || !select.value){
      alert("Merci de sélectionner une session de destination.");
      return false;
    }
    const selectedLabel = select.options[select.selectedIndex]?.textContent?.trim() || "la session choisie";
    return confirm(`Confirmer le transfert vers "${selectedLabel}" ?\n\nLe candidat sera retiré de la session actuelle.`);
  }

  function normalizeTransferSessionSearch(value){
    return (value || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  }

  function initTransferSessionSearch(){
    const input = document.getElementById("transferSessionSearch");
    const select = document.getElementById("transferSessionSelect");
    const wrap = document.getElementById("transferSessionSearchWrap");
    const clear = document.getElementById("transferSessionSearchClear");
    const status = document.getElementById("transferSessionSearchStatus");
    const results = document.getElementById("transferSessionResults");
    const empty = document.getElementById("transferSessionSearchEmpty");
    if(!input || !select || !wrap || !clear || !status || !results || !empty) return;
    const sessionOptions = Array.from(select.options).slice(1);
    const selectSession = (option, button)=>{
      select.value = option.value;
      results.querySelectorAll(".transfer-session-result").forEach((result)=>{
        const selected = result === button;
        result.classList.toggle("is-selected", selected);
        result.setAttribute("aria-selected", selected ? "true" : "false");
      });
      status.textContent = `Session sélectionnée : ${option.textContent.trim()}`;
    };
    const filterSessions = ()=>{
      const query = normalizeTransferSessionSearch(input.value);
      const matches = query ? sessionOptions.filter((option)=>normalizeTransferSessionSearch(option.textContent).includes(query)) : [];
      results.replaceChildren();
      matches.forEach((option)=>{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "transfer-session-result";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
        button.textContent = option.textContent.trim();
        if(option.value === select.value) button.classList.add("is-selected");
        button.addEventListener("click", ()=>selectSession(option, button));
        results.appendChild(button);
      });
      wrap.classList.toggle("has-value", Boolean(input.value));
      results.classList.toggle("show", matches.length > 0);
      input.setAttribute("aria-expanded", matches.length > 0 ? "true" : "false");
      empty.classList.toggle("show", Boolean(query) && matches.length === 0);
      status.textContent = query ? `${matches.length} session${matches.length > 1 ? "s" : ""} trouvée${matches.length > 1 ? "s" : ""}. Choisissez-la ci-dessous.` : "Saisissez le nom, la formation ou la date de la session.";
    };
    input.addEventListener("input", ()=>{ select.value = ""; filterSessions(); });
    clear.addEventListener("click", ()=>{ input.value = ""; select.value = ""; filterSessions(); input.focus(); });
    filterSessions();
  }

  initTransferSessionSearch();

  document.querySelectorAll("[data-close-modal]").forEach(b=>{
    b.addEventListener("click", ()=>{
      const id = b.getAttribute("data-close-modal");
      closeModal(id);
    });
  });


  const brevoNoCreditNotice = sheetContext.brevoNotice;
  if(brevoNoCreditNotice && Object.keys(brevoNoCreditNotice).length){
    openModal("brevoCreditModal");
  }

  updateDocsRelanceState(sheetContext.dossierStatus, sheetContext.plannedDate);

  const btnOpenFinancementReject = document.getElementById("btnOpenFinancementReject");
  const btnSendFinancementPending = document.getElementById("btnSendFinancementPending");
  const financementPendingSentAt = document.getElementById("financementPendingSentAt");
  const financementRejectForm = document.getElementById("financementRejectForm");
  const financementRejectAmount = document.getElementById("financementRejectAmount");
  const financementRejectDate = document.getElementById("financementRejectDate");
  const btnSendFinancementReject = document.getElementById("btnSendFinancementReject");
  const financementRejectedNote = document.getElementById("financementRejectedNote");

  function ensureAdminCommentFlag(updatedValue){
    const adminComment = document.getElementById("traineeComment");
    if(!adminComment) return;
    const flagText = "⚠️ Prélèvement rejeté";
    if(updatedValue){
      adminComment.value = updatedValue;
      adminComment.dispatchEvent(new Event("input"));
      return;
    }
    if((adminComment.value || "").includes(flagText)) return;
    adminComment.value = (adminComment.value || "").trim()
      ? `${adminComment.value.trim()}\n${flagText}`
      : flagText;
    adminComment.dispatchEvent(new Event("input"));
  }

  if(btnOpenFinancementReject){
    btnOpenFinancementReject.addEventListener("click", ()=>openModal("financementRejectModal"));
  }

  if(btnSendFinancementPending){
    btnSendFinancementPending.addEventListener("click", async ()=>{
      if(btnSendFinancementPending.disabled) return;
      if(!await window.confirmMailSmsSend?.()) return;
      btnSendFinancementPending.disabled = true;
      try{
        const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/financement-en-attente/send`, {
          method: "POST",
          headers: {"Content-Type":"application/json"}
        });
        const data = await res.json().catch(()=> ({}));
        if(!res.ok || data.ok === false){
          throw new Error(data.error || "send_failed");
        }

        btnSendFinancementPending.classList.remove("btn-outline");
        btnSendFinancementPending.classList.add("btn-disabled-muted");

        if(financementPendingSentAt){
          const dateText = data.sent_at_fr || "";
          financementPendingSentAt.innerHTML = `🟧 Prélèvement en attente envoyé le : <strong>${dateText}</strong>`;
          financementPendingSentAt.style.display = "block";
        }

        const emailMsg = data.email_ok ? "Mail envoyé." : "Mail non envoyé (adresse manquante).";
        const smsMsg = data.sms_ok ? "SMS envoyé." : "SMS non envoyé (numéro manquant).";
        alert(`Prélèvement en attente : ${emailMsg} ${smsMsg}`);
      }catch(e){
        alert("Erreur lors de l'envoi du mail/SMS de prélèvement en attente.");
        btnSendFinancementPending.disabled = false;
      }
    });
  }

  if(financementRejectForm){
    financementRejectForm.addEventListener("submit", async (e)=>{
      e.preventDefault();
      if(!await window.confirmMailSmsSend?.()) return;
      if(!financementRejectAmount || !financementRejectDate) return;
    const amount = (financementRejectAmount.value || "").trim();
    const scheduledDate = (financementRejectDate.value || "").trim();
    if(!amount || !scheduledDate){
      alert("Merci de renseigner le montant et la date.");
      return;
    }

    if(btnSendFinancementReject) btnSendFinancementReject.disabled = true;

    try{
      const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/financement-rejet/send`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ amount: amount, scheduled_date: scheduledDate })
      });
      const data = await res.json().catch(()=> ({}));
      if(!res.ok || data.ok === false){
        throw new Error(data.error || "send_failed");
      }

      if(financementSelect){
        financementSelect.value = "in_review";
        applyStatusPill(financementSelect);
      }

      if(financementRejectedNote){
        financementRejectedNote.textContent = data.note || "⚠️ Prélèvement rejeté";
        financementRejectedNote.style.display = "block";
      }

      if(btnOpenFinancementReject){
        btnOpenFinancementReject.classList.remove("btn-outline");
        btnOpenFinancementReject.classList.add("btn-orange");
      }

      ensureAdminCommentFlag(data.comment);

      closeModal("financementRejectModal");
      const emailMsg = data.email_ok ? "Mail envoyé." : "Mail non envoyé (adresse manquante).";
      const smsMsg = data.sms_ok ? "SMS envoyé." : "SMS non envoyé (numéro manquant).";
      alert(`Prélèvement rejeté : ${emailMsg} ${smsMsg}`);
    }catch(e){
      alert("Erreur lors de l'envoi du mail/SMS de prélèvement rejeté.");
    }finally{
      if(btnSendFinancementReject) btnSendFinancementReject.disabled = false;
    }
    });
  }

  // --- PRE/CAR live formatter ---
  function formatPreCarDisplay(raw){
    raw = (raw || "").toString().toUpperCase().replace(/\s+/g, "");
    raw = raw.replace(/[^A-Z0-9-]/g, "");

    const limitTo = (value, maxChars = 25) => {
      let out = "";
      let count = 0;
      for (const ch of value) {
        if (ch !== "-") {
          if (count >= maxChars) break;
          count += 1;
        }
        out += ch;
      }
      return out;
    };

    const compact = raw.replace(/[^A-Z0-9]/g, "");

    if (compact.startsWith("PRE") || compact.startsWith("CAR")) {
      const prefix = compact.startsWith("PRE") ? "PRE" : "CAR";
      let digits = compact.slice(3).replace(/\D/g, "");
      let out = prefix;

      let hasDep = false;
      if (raw.startsWith(prefix + "-")) {
        const firstSegment = raw.slice(prefix.length + 1).split("-")[0];
        if (/^\d{3}$/.test(firstSegment)) hasDep = true;
      }
      if (!hasDep && digits.length > 19) hasDep = true;

      if (hasDep) {
        digits = digits.slice(0, 22);
        const dep = digits.slice(0, 3);
        const y = digits.slice(3, 7);
        const m = digits.slice(7, 9);
        const d = digits.slice(9, 11);
        const last = digits.slice(11, 22);
        if (dep) out += "-" + dep;
        if (y) out += "-" + y;
        if (m) out += "-" + m;
        if (d) out += "-" + d;
        if (last) out += "-" + last;
      } else {
        digits = digits.slice(0, 19);
        const y = digits.slice(0, 4);
        const m = digits.slice(4, 6);
        const d = digits.slice(6, 8);
        const last = digits.slice(8, 19);
        if (y) out += "-" + y;
        if (m) out += "-" + m;
        if (d) out += "-" + d;
        if (last) out += "-" + last;
      }
      return limitTo(out, 25);
    }

    const year = compact.match(/^\d{0,4}/)?.[0] || "";
    let rest = compact.slice(year.length);
    const dossier = rest.match(/^\d{0,7}/)?.[0] || "";
    rest = rest.slice(dossier.length);
    const type = rest.match(/^[A-Z]{0,3}/)?.[0] || "";
    rest = rest.slice(type.length);
    const region = rest.match(/^[A-Z0-9]{0,2}/)?.[0] || "";
    rest = rest.slice(region.length);
    const serial = (rest.match(/^\d{0,7}/)?.[0] || "");

    const grouped = [year, dossier, type, region, serial].filter(Boolean);
    return limitTo(grouped.join("-"), 23);
  }

  function normalizePRE(s){
    return formatPreCarDisplay(s);
  }

  function isValidPRE(v){
    return /^(?:(PRE|CAR)-(?:\d{3}-)?\d{4}-\d{2}-\d{2}-\d{11,}|\d{4}-\d{7}-(PRE|CAR)-[A-Z0-9]{2}-\d{7})$/.test(v);
  }

  document.addEventListener("DOMContentLoaded", ()=>{
    const preReceptionForm = document.getElementById("preReceptionForm");
    const preReceptionInput = document.getElementById("preReceptionNumber");
    const btnSavePreReception = document.getElementById("btnSavePreReception");

    if(preReceptionInput){
      preReceptionInput.addEventListener("input", ()=>{
        preReceptionInput.value = normalizePRE(preReceptionInput.value);
      });
    }

    document.querySelectorAll("[data-pre-reception]").forEach((btn)=>{
      btn.addEventListener("click", ()=>{
        if(preReceptionInput){
          preReceptionInput.value = normalizePRE(preReceptionInput.value);
        }
        openModal("preReceptionModal");
      });
    });

    preReceptionForm?.addEventListener("submit", async (e)=>{
      e.preventDefault();
      if(!preReceptionInput) return;

      const normalized = normalizePRE(preReceptionInput.value || "");
      if(!isValidPRE(normalized)){
        alert("Numéro PRE/CAR invalide. Formats attendus : PRE-083-2025-12-01-20250000000, PRE-2025-12-01-20250000000 ou 2026-0002805-PRE-3P-1050370");
        return;
      }

      preReceptionInput.value = normalized;
      if(btnSavePreReception) btnSavePreReception.disabled = true;

      try{
        const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/pre-reception`, {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ pre_number: normalized })
        });
        const data = await res.json().catch(()=> ({}));
        if(!res.ok || data.ok === false){
          throw new Error(data.error || "save_failed");
        }
        traineePreNumber = normalized;
        closeModal("preReceptionModal");
        const emailMsg = data.email_ok ? "Mail envoyé au stagiaire." : "Mail non envoyé (adresse manquante).";
        alert(`Numéro PRE enregistré. ${emailMsg}`);
      }catch(e){
        alert("Erreur lors de l'enregistrement du numéro PRE.");
      }finally{
        if(btnSavePreReception) btnSavePreReception.disabled = false;
      }
    });
  });

  // Test FR modal logic
  function openTestModal(mode){
    const title = document.getElementById("testModalTitle");
    const form = document.getElementById("testForm");
    if(mode === "notify"){
      title.textContent = "Notifier test de français";
      form.action = sheetContext.testNotifyUrl;
    }else if(mode === "echec"){
      title.textContent = "Échec test de français";
      form.action = sheetContext.testFailureUrl;
    }else{
      title.textContent = "Relancer test de français";
      form.action = sheetContext.testReminderUrl;
    }
    openModal("testModal");
  }

  const forceDossierCheckbox = document.getElementById("forceDossierComplete");
  if(forceDossierCheckbox){
    forceDossierCheckbox.addEventListener("change", async ()=>{
      const value = forceDossierCheckbox.checked;
      try{
        const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
          method:"POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ force_dossier_complete: value })
        });
        const data = await res.json().catch(()=> ({}));
        if(!res.ok || data.ok === false){
          throw new Error("save_failed");
        }
        if(data?.dossier_status){
          setDossierPill(data.dossier_status);
          updateDocsRelanceState(data.dossier_status, data.docs_relance_auto_planned_date || "");
        }else{
          setDossierPill(value ? "complete" : "incomplete");
          updateDocsRelanceState(value ? "complete" : "incomplete", "");
        }
      }catch(e){
        forceDossierCheckbox.checked = !value;
        alert("Erreur sauvegarde dossier");
      }
    });
  }

  // Autosave documents
  document.addEventListener("DOMContentLoaded", ()=>{
    const docsTable = document.getElementById("docsTable");
    if(docsTable){
      const sessionId = docsTable.getAttribute("data-session-id");
      const traineeId = docsTable.getAttribute("data-trainee-id");

      async function saveDoc(key, field, value){
        const res = await fetch(`/api/sessions/${sessionId}/stagiaires/${traineeId}/documents/update`, {
          method:"POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ key, field, value })
        });
        const data = await res.json().catch(()=> ({}));
        if(!res.ok || data.ok === false){
          throw new Error(data.error || "save_doc_failed");
        }
        if(data?.dossier_status){
          setDossierPill(data.dossier_status);
          updateDocsRelanceState(data.dossier_status, data.docs_relance_auto_planned_date || "");
        }
        return data;
      }

      function updateDocPill(row, status){
        if(!row) return;
        const hint = row.querySelector("td:nth-child(2) .hint");
        if(!hint) return;
        let pillClass = "pill-yellow";
        let label = "A CONTRÔLER";
        if(status === "CONFORME"){
          pillClass = "pill-green";
          label = "CONFORME";
        }else if(status === "NON CONFORME"){
          pillClass = "pill-red";
          label = "NON CONFORME";
        }else if(status === "NON DÉPOSÉ"){
          pillClass = "pill-gray";
          label = "NON DÉPOSÉ";
        }
        hint.innerHTML = `<span class="pill ${pillClass}">${label}</span>`;
      }

      function updateDocumentsHeaderButtonState(){
        const docsBtn = document.getElementById("btnOpenDocumentsSection");
        if(!docsBtn) return;

        const rows = docsTable.querySelectorAll("tr[data-doc-key]");
        let hasToControl = false;
        let hasTrackableDoc = false;
        let allConforme = true;

        rows.forEach((tr)=>{
          const sel = tr.querySelector("select.sel-doc");
          if(!sel) return;
          hasTrackableDoc = true;
          const status = (sel.value || "").toUpperCase().trim();
          if(status === "A CONTRÔLER" || status === "A CONTROLER"){
            hasToControl = true;
          }
          if(status !== "CONFORME"){
            allConforme = false;
          }
        });

        docsBtn.classList.remove("btn-outline", "btn-docs-pending", "btn-docs-ok", "btn-docs-idle");

        if(hasToControl){
          docsBtn.classList.add("btn-docs-pending");
          docsBtn.textContent = "📁 Mes documents";
        }else if(hasTrackableDoc && allConforme){
          docsBtn.classList.add("btn-docs-ok");
          docsBtn.textContent = "📁 Mes documents ✅";
        }else{
          docsBtn.classList.add("btn-docs-idle");
          docsBtn.textContent = "📁 Mes documents";
        }
      }

      // select changes
      docsTable.querySelectorAll("tr[data-doc-key]").forEach(tr=>{
        const key = tr.getAttribute("data-doc-key");

        const sel = tr.querySelector("select.sel-doc");
        if(sel){
          sel.addEventListener("change", async ()=>{
            const previousValue = sel.getAttribute("data-prev-value") || "";
            try{
              await saveDoc(key, "status", sel.value);
              sel.setAttribute("data-prev-value", sel.value);
              updateDocPill(tr, sel.value);
              updateDocumentsHeaderButtonState();
            }catch(e){
              sel.value = previousValue;
              updateDocPill(tr, previousValue);
              updateDocumentsHeaderButtonState();
              alert("Erreur sauvegarde document");
            }
          });
          sel.setAttribute("data-prev-value", sel.value || "");
        }

      });

      let activeDocRow = null;
      let activeDocButton = null;
      let activeDocKey = null;
      const docCommentModal = document.getElementById("docCommentModal");
      const docCommentInput = document.getElementById("docCommentInput");
      const docCommentSave = document.getElementById("docCommentSave");

      docsTable.querySelectorAll(".doc-comment-btn").forEach(btn=>{
        btn.addEventListener("click", ()=>{
          activeDocKey = btn.getAttribute("data-doc-key");
          activeDocButton = btn;
          activeDocRow = btn.closest("tr");
          const existing = btn.getAttribute("data-comment") || "";
          if(docCommentInput) docCommentInput.value = existing;
          openModal("docCommentModal");
          docCommentInput?.focus();
        });
      });

      const professionalSheetStatus = docsTable.querySelector(".professional-sheet-status");
      if(professionalSheetStatus){
        professionalSheetStatus.setAttribute("data-prev-value", professionalSheetStatus.value);
        professionalSheetStatus.addEventListener("change", async ()=>{
          const previousValue = professionalSheetStatus.getAttribute("data-prev-value") || "A CONTRÔLER";
          professionalSheetStatus.disabled = true;
          try{
            const response = await fetch(professionalSheetStatus.dataset.updateUrl, {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({status: professionalSheetStatus.value})
            });
            const result = await response.json().catch(()=> ({}));
            if(!response.ok || !result.ok) throw new Error(result.error || "save_failed");
            professionalSheetStatus.setAttribute("data-prev-value", professionalSheetStatus.value);
            const feedback = docsTable.querySelector(".professional-sheet-status-feedback");
            if(feedback) feedback.textContent = `Statut enregistré : ${result.status_label}`;
            const badge = docsTable.querySelector(".professional-sheet-status-badge");
            if(badge){
              badge.textContent = result.status_label;
              badge.classList.remove("pill-yellow", "pill-green", "pill-red");
              badge.classList.add(result.status === "CONFORME" ? "pill-green" : result.status === "NON CONFORME" ? "pill-red" : "pill-yellow");
            }
          }catch(error){
            professionalSheetStatus.value = previousValue;
            alert("Erreur lors de l’enregistrement du statut de la fiche.");
          }finally{
            professionalSheetStatus.disabled = false;
          }
        });
      }

      updateDocumentsHeaderButtonState();

      if(docCommentSave){
        docCommentSave.addEventListener("click", async ()=>{
          if(!activeDocKey) return;
          const value = (docCommentInput?.value || "").toString();
          await saveDoc(activeDocKey, "comment", value);
          if(activeDocButton) activeDocButton.setAttribute("data-comment", value);
          if(activeDocRow){
            const preview = activeDocRow.querySelector(".doc-comment-preview");
            if(preview){
              preview.textContent = value.trim().length ? "Commentaire enregistré" : "Aucun commentaire";
            }
          }
          closeModal("docCommentModal");
        });
      }
    }
  });

  // Refresh CNAPS
  async function cnapsLookup(nom, prenom){
    const r = await fetch(`/api/cnaps_lookup?nom=${encodeURIComponent(nom)}&prenom=${encodeURIComponent(prenom)}`);
    return await r.json();
  }

  document.getElementById("btnRefreshCnaps")?.addEventListener("click", async ()=>{
    const nom = (sheetContext.lastName).trim();
    const prenom = (sheetContext.firstName).trim();
    if(!nom || !prenom){ alert("Nom / prénom introuvables"); return; }

    try{
      const res = await cnapsLookup(nom, prenom);
      const statut = (res.statut_cnaps || "INCONNU").toUpperCase();
      const statutHistory = Array.isArray(res.statut_cnaps_history) ? res.statut_cnaps_history : [];

      await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          cnaps: statut,
          statut_cnaps_history: statutHistory,
        })
      });

      window.location.reload();
    }catch(e){
      alert("Erreur CNAPS");
    }
  });

  const cnapsContactBtn = document.getElementById("btnCnapsContact");
  if(cnapsContactBtn){
    const canWrite = sheetContext.canWrite;
    cnapsContactBtn.addEventListener("click", ()=>{
      if(!canWrite) return;
      const sessionId = cnapsContactBtn.getAttribute("data-session-id");
      const traineeId = cnapsContactBtn.getAttribute("data-trainee-id");
      if(!sessionId || !traineeId) return;
      const payload = JSON.stringify({
        items: [{ session_id: sessionId, trainee_id: traineeId }]
      });
      if(navigator.sendBeacon){
        navigator.sendBeacon(
          "/api/cnaps/pre_request",
          new Blob([payload], { type: "application/json" })
        );
        return;
      }
      fetch("/api/cnaps/pre_request", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: payload,
        keepalive: true,
      }).catch(()=>{});
    });
  }

  document.querySelectorAll('form[data-mail-sms-confirm="true"]').forEach((form)=>{
    form.addEventListener("submit", async (e)=>{
      if(form.dataset.confirmedMailSms === "true") return;
      e.preventDefault();
      const ok = await window.confirmMailSmsSend?.();
      let sendNotificationsInput = form.querySelector('input[name="send_notifications"]');
      if(!sendNotificationsInput){
        sendNotificationsInput = document.createElement('input');
        sendNotificationsInput.type = 'hidden';
        sendNotificationsInput.name = 'send_notifications';
        form.appendChild(sendNotificationsInput);
      }
      sendNotificationsInput.value = ok ? '1' : '0';
      form.dataset.confirmedMailSms = "true";
      form.requestSubmit?.();
      setTimeout(()=>{ delete form.dataset.confirmedMailSms; }, 0);
    });
  });

  const cnapsPreRelanceBtn = document.getElementById("btnCnapsPreRelance");
  if(cnapsPreRelanceBtn){
    cnapsPreRelanceBtn.addEventListener("click", async ()=>{
      if(!await window.confirmMailSmsSend?.()) return;
      try{
        cnapsPreRelanceBtn.disabled = true;
        const r = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/cnaps-pre-relance/send`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({})
        });
        const data = await r.json();
        if(!r.ok || !data.ok){
          throw new Error(data.error || "send_failed");
        }
        alert(`Relance PRE envoyée. Mail: ${data.email_ok ? "oui" : "non"} / SMS: ${data.sms_ok ? "oui" : "non"}`);
      }catch(e){
        console.error(e);
        alert("Erreur lors de l'envoi de la relance PRE.");
      }finally{
        cnapsPreRelanceBtn.disabled = false;
      }
    });
  }

  const chkCnapsOk = document.getElementById("chkCnapsOk");
  if(chkCnapsOk){
    chkCnapsOk.addEventListener("change", async ()=>{
      const newVal = chkCnapsOk.checked ? "CARTE PROFESSIONNELLE OK" : "INCONNU";
      try{
        await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
          method:"POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ cnaps: newVal })
        });
        window.location.reload();
      }catch(e){
        alert("Erreur sauvegarde CNAPS");
      }
    });
  }

  // VAE relances manuelles
  document.querySelectorAll('[data-vae-relance-send]').forEach((btn)=>{
    btn.addEventListener('click', async ()=>{
      const relanceKey = btn.getAttribute('data-vae-relance-send');
      if(!relanceKey) return;

      let confirmed = true;
      if(typeof window.confirmMailSmsSend === 'function'){
        confirmed = await window.confirmMailSmsSend();
      }else{
        confirmed = window.confirm('Voulez-vous envoyer le mail / SMS ?');
      }
      if(!confirmed) return;

      btn.disabled = true;
      try{
        const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/vae-relance/${relanceKey}/send`, {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({}),
        });
        const data = await res.json().catch(()=>({}));
        if(!res.ok || data.ok === false){
          const serverError = (data && (data.error || data.message)) ? ` (${data.error || data.message})` : '';
          throw new Error(`send_failed${serverError}`);
        }
        alert(`Relance envoyée. Mail: ${data.email_ok ? 'oui' : 'non'} / SMS: ${data.sms_ok ? 'oui' : 'non'}`);
        window.location.reload();
      }catch(e){
        console.error(e);
        alert(`Erreur lors de l'envoi de la relance VAE${e?.message ? ` : ${e.message}` : '.'}`);
        btn.disabled = false;
      }
    });
  });



  const vaeConventionConfig = {
    financingUrl: sheetContext.financingUrl,
    signatureUrl: sheetContext.signatureUrl,
    previewUrl: sheetContext.conventionPreviewUrl,
    isVae: sheetContext.isVae,
    trainingType: sheetContext.trainingType,
    defaults: {
      ssiap_pathway: sheetContext.pathway,
      training_price: sheetContext.price,
      cpf_amount: sheetContext.cpfAmount,
      personal_amount: sheetContext.personalAmount,
      other_amount: sheetContext.otherAmount
    }
  };

  async function saveVaeConventionFinancing(payload){
    const response = await fetch(vaeConventionConfig.financingUrl, {
      method: "POST",
      headers: {"Content-Type":"application/json", "Accept":"application/json"},
      body: JSON.stringify(payload || {})
    });
    const data = await response.json().catch(()=>({}));
    if(!response.ok || data.ok === false){
      throw new Error(data.error || "Impossible de sauvegarder les montants de financement.");
    }
  }

  async function requestVaeConventionTransmission(){
    if(sheetContext.afcEnabled){
    await window.openConventionPreview?.(vaeConventionConfig.previewUrl, {
      title: "Convention AFC France Travail",
      description: "APS + SSIAP 1 + SST + Habilitation électrique. Aucun frais de formation à la charge du stagiaire.",
      frameTitle: "Aperçu de la convention AFC"
    });
    const send = window.AppModal
      ? await window.AppModal.confirm({type:"info", title:"Convention AFC France Travail", message:"Envoyer cette convention au stagiaire pour signature ? Formation financée dans le cadre du marché France Travail, reste à charge : 0 €.", primaryText:"Envoyer pour signature", secondaryText:"Annuler"})
      : window.confirm("Envoyer la convention AFC France Travail pour signature ? Reste à charge stagiaire : 0 €.");
    return send ? {send_convention:true} : null;
    }
    return await window.openConventionTransmission?.({
      companyUrl: sheetContext.companyConventionUrl || "",
      defaults: vaeConventionConfig.defaults,
      trainingType: vaeConventionConfig.trainingType,
      previewUrl: vaeConventionConfig.previewUrl,
      onPreview: async (payload)=>{
        await saveVaeConventionFinancing(payload);
        await window.openConventionPreview?.(vaeConventionConfig.previewUrl, {
          title: vaeConventionConfig.isVae ? "Convention VAE" : "Convention",
          description: vaeConventionConfig.isVae ? "Vérifiez la convention VAE avant l’envoi pour signature électronique." : "Vérifiez la convention avant l’envoi pour signature électronique.",
          frameTitle: vaeConventionConfig.isVae ? "Aperçu de la convention VAE" : "Aperçu de la convention"
        });
      }
    });
  }

  async function sendVaeConventionSignature(payload, options = {}){
    try{
      await saveVaeConventionFinancing(payload);
      window.showConventionTransmissionProgress?.();
      const response = await fetch(vaeConventionConfig.signatureUrl, {
        method: "POST",
        headers: {"Content-Type":"application/json", "Accept":"application/json"},
        body: JSON.stringify({...payload, force_new: !!options.forceNew})
      });
      const data = await response.json().catch(()=>({}));
      if(!response.ok || data.ok === false){
        throw new Error(data.error || "Envoi Yousign impossible.");
      }
      window.hideConventionTransmissionProgress?.();
      await (window.showConventionResult?.({
        title: vaeConventionConfig.isVae ? "Convention VAE envoyée" : "Convention envoyée",
        message: data.email_ok === false ? "La demande Yousign a été créée, mais l’e-mail n’a pas pu être envoyé automatiquement." : (vaeConventionConfig.isVae ? "La convention VAE a été envoyée au stagiaire pour signature électronique." : "La convention a été envoyée au stagiaire pour signature électronique."),
        type: data.email_ok === false ? "warning" : "success"
      }) || Promise.resolve(window.alert(vaeConventionConfig.isVae ? "Convention VAE envoyée." : "Convention envoyée.")));
      window.location.reload();
      return true;
    }catch(error){
      window.hideConventionTransmissionProgress?.();
      await (window.showConventionResult?.({type:"error", title: vaeConventionConfig.isVae ? "Convention VAE non envoyée" : "Convention non envoyée", message:error.message || (vaeConventionConfig.isVae ? "Impossible d’envoyer la convention VAE." : "Impossible d’envoyer la convention."), buttonText:"Compris"}) || Promise.resolve(window.alert(error.message || (vaeConventionConfig.isVae ? "Impossible d’envoyer la convention VAE." : "Impossible d’envoyer la convention."))));
      return false;
    }
  }

  // VAE (actions dédiées DIRIGEANT VAE)
  let vaeActionRequestInFlight = false;
  window.setVaeAction = async function setVaeAction(actionKey){
    if(vaeActionRequestInFlight){
      return;
    }
    const payload = {};
    const currentVaeActionDates = sheetContext.vaeDates;
    const isReset = !!currentVaeActionDates[actionKey];
    const now = new Date();
    const clickedAt = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")}/${now.getFullYear()}`;
    const statusesSendingMail = ["livret_1_analysis", "livret_1_validated", "livret_2_todo", "livret_2_analysis", "livret_2_validated", "jury", "certified"];
    const actionStatusMap = {
      livret_1_received: "livret_1_analysis",
      livret_1_validated: "livret_1_validated",
      financement_validated: "livret_2_todo",
      livret_2_received: "livret_2_analysis",
      livret_2_validated: "livret_2_validated",
      financement_l2_validated: "financement_l2_validated",
      jury_date: "jury",
      diplome_obtenu: "certified",
    };
    const orderedActions = [
      "diplome_obtenu",
      "jury_date",
      "financement_l2_validated",
      "livret_2_validated",
      "livret_2_received",
      "financement_validated",
      "livret_1_validated",
      "livret_1_received",
    ];

    if(isReset){
      const nextActionDates = { ...currentVaeActionDates };
      delete nextActionDates[actionKey];
      payload.vae_action_dates = nextActionDates;

      if(actionKey === "jury_date"){
        payload.vae_jury_date = "";
      }

      const latestDoneAction = orderedActions.find((key) => !!nextActionDates[key]);
      payload.vae_status = latestDoneAction ? actionStatusMap[latestDoneAction] : "livret_1_todo";
    }else{

      if(actionKey === "livret_1_received"){
        payload.vae_status = "livret_1_analysis";
      }else if(actionKey === "livret_1_validated"){
        payload.vae_status = "livret_1_validated";
      }else if(actionKey === "financement_validated"){
        payload.vae_status = "livret_2_todo";
      }else if(actionKey === "livret_2_received"){
        payload.vae_status = "livret_2_analysis";
      }else if(actionKey === "livret_2_validated"){
        payload.vae_status = "livret_2_validated";
      }else if(actionKey === "financement_l2_validated"){
        payload.vae_status = "financement_l2_validated";
      }else if(actionKey === "jury_date"){
        const raw = window.prompt("Indiquez la date d'examen (JJ/MM/AAAA)");
        if(raw === null) return;
        const value = (raw || "").trim();
        const m = value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if(!m){
          alert("Format attendu : JJ/MM/AAAA");
          return;
        }
        payload.vae_status = "jury";
        payload.vae_jury_date = `${m[3]}-${m[2]}-${m[1]}`;
      }else if(actionKey === "diplome_obtenu"){
        payload.vae_status = "certified";
      }else if(actionKey === "livret_1_transmitted_scotia"){
        // date only
      }else if(actionKey === "livret_2_transmitted_scotia"){
        // date only
      }else{
        return;
      }

      payload.vae_action_dates = {
        ...currentVaeActionDates,
        [actionKey]: clickedAt,
      };
    }

    let vaeConventionPayload = null;
    if(!isReset && actionKey === "financement_validated" && sheetContext.noCompanyConvention){
      vaeConventionPayload = await requestVaeConventionTransmission();
      if(!vaeConventionPayload) return;
    }

    vaeActionRequestInFlight = true;

    let sendVaeNotification = !isReset;
    if(statusesSendingMail.includes(payload.vae_status)){
      sendVaeNotification = await window.confirmMailSmsSend?.();
    }

    try{
      const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          ...payload,
          send_vae_notification: !!sendVaeNotification,
        })
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok || data.ok === false){
        throw new Error('save_failed');
      }
      if(vaeConventionPayload){
        if(vaeConventionPayload.send_convention === false){
          await saveVaeConventionFinancing(vaeConventionPayload);
        }else{
          const sent = await sendVaeConventionSignature(vaeConventionPayload);
          if(sent) return;
        }
      }
      if(!isReset && (actionKey === "livret_1_transmitted_scotia" || actionKey === "livret_2_transmitted_scotia")){
        window.location.href = "/scotia";
        return;
      }
      window.location.reload();
    }catch(e){
      vaeActionRequestInFlight = false;
      alert("Erreur mise à jour statut VAE");
    }
  }

  window.propulseScotia = async function propulseScotia(){
    try{
      const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          scotia_force_visible: true,
          send_vae_notification: false,
        })
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok || data.ok === false){
        throw new Error("save_failed");
      }
      window.location.href = "/scotia";
    }catch(e){
      alert("Erreur lors de la propulsion vers SCOTIA");
    }
  }

    // ✅ Checkbox "Test validé" -> test_fr_status = validated / in_progress
  const chk = document.getElementById("chkTestFrValidated");
  if(chk){
    chk.addEventListener("change", async ()=>{
      const newVal = chk.checked ? "validated" : "in_progress";

      try{
        await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
          method:"POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ test_fr_status: newVal })
        });
        window.location.reload();
      }catch(e){
        alert("Erreur sauvegarde test de français");
      }
    });
  }

  // =========================
// Facturation Qonto centralisée
(function(){
  const card = document.getElementById("qontoInvoiceCard");
  if(!card) return;
  const sessionId = card.dataset.sessionId;
  const traineeId = card.dataset.traineeId;
  const readOnly = card.dataset.readOnly === "1";
  const box = document.getElementById("qontoInvoiceHistory");
  const syncBtn = document.getElementById("btnSyncQontoTrainee");
  const resetFinancialTrackingBtn = document.getElementById("btnResetFinancialTracking");
  const quickGenerateBtn = document.getElementById("btnQuickGenerateInvoice");
  const financeNotificationsBtn = document.getElementById("btnToggleFinanceNotifications");
  const financeNotificationsCount = document.getElementById("financeNotificationsCount");
  let financeNotificationsOpen = false;
  const financeValidationWrap = document.querySelector('.finance-validation-admin');
  const financeValidationStatus = document.getElementById('financeValidationStatus');
  const financeValidationForceForm = document.getElementById('financeForceValidatedForm');
  const financeValidationForceBtn = document.getElementById('btnForceFinanceValidated');
  const financeValidationAutoBtn = document.getElementById('btnFinanceAutoMode');
  let financeValidationManualMode = financeValidationWrap?.dataset.manualMode === 'manual';
  let financeValidationManualStatus = financeValidationWrap?.dataset.manualStatus || '';
  let currentFinancementStatus = sheetContext.financingStatus;
  let financeStatusSyncInFlight = false;
  let currentLines = [];
  let currentFinancialSummary = null;
  let currentCpfWedofInvoice = null;
  let currentLine = null;
  let modalLoading = false;
  let installmentDraftActive = false;
  let installmentEditBusy = false;
  let installmentDraftContainer = null;
  const esc = v => String(v ?? "").replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const CPF_QONTO_CLIENT={type:'company',displayType:'Société',name:'CAISSE DES DEPOTS',email:'',addressLine1:'56 rue de Lille',addressLine2:'Mon Compte Formation',zipCode:'75356',city:'PARIS 07 SP',country:'FR',taxIdentificationNumber:'18002002600019',vatNumber:''};
  function isCpfQontoLine(line){const blob=[line?.financingType,line?.financeur,line?.financeurName,line?.financingLabel,line?.typeFinanceur].join(' ').toLowerCase();return /\bcpf\b|mon compte formation|caisse des d[ée]p[ôo]ts/.test(blob);}
  function getCpfQontoClientDefaults(){return {...CPF_QONTO_CLIENT};}
  const fmtMoney = n => new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format(Number(n||0));
  const cpfAmount = document.getElementById('cpfAmount');
  const personalAmount = document.getElementById('personalAmount');
  const otherAmount = document.getElementById('otherAmount');
  const trainingPrice = document.getElementById('trainingPrice');
  const salesTrackingAmount = document.getElementById('salesTrackingAmount');
  const cashPaymentEnabled = document.getElementById('cashPaymentEnabled');
  const cashPaymentSettled = document.getElementById('cashPaymentSettled');
  let cpfValidated = sheetContext.cpfValidated;
  const cpfFranceTravail = sheetContext.franceTravail;
  const cpfFranceTravailHtml = sheetContext.franceTravailHtml;
  const cashPaymentAmount = document.getElementById('cashPaymentAmount');
  const label = s => ({paid:'Payée',sent:'Envoyée',finalized:'Facture finalisée',draft:'Brouillon créé',cancelled:'Non facturé',deleted:'Non facturé',not_invoiced:'Non facturé',not_generated:'Non facturé'}[s]||'Non facturé');
  const cls = s => s==='paid'?'green':(['sent','finalized'].includes(s)?'blue':(s==='draft'?'orange':'gray'));
  async function parseJsonResponse(response, fallbackMessage){
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    if(contentType.includes('application/json')){
      try{return raw ? JSON.parse(raw) : {};}
      catch(err){throw new Error('Réponse API invalide : JSON illisible.');}
    }
    const title = raw.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim();
    const isLoginPage = response.redirected || response.url.includes('/admin/login') || /Connexion|login/i.test(title||'');
    if(isLoginPage) throw new Error('Votre session administrateur a expiré. Rechargez la page puis reconnectez-vous.');
    throw new Error(title || fallbackMessage || 'Réponse serveur invalide : HTML reçu au lieu de JSON.');
  }
  async function billingApi(url, body){
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body||{})});
    const j=await parseJsonResponse(r,'Action impossible');
    if(!r.ok||!j.ok) throw new Error(j.error||j.message||'Action impossible');
    return j;
  }
  let billingLoadPromise = null;
  function load(){
    if(billingLoadPromise) return billingLoadPromise;
    billingLoadPromise = loadLocalBilling().finally(()=>{ billingLoadPromise = null; });
    return billingLoadPromise;
  }
  async function loadLocalBilling(){
    // The scheduled Qonto job/webhooks update the stored state. Reading an
    // open tab must not trigger another bank synchronization every 30 seconds.
    const r = await fetch(`/api/billing/trainee/${encodeURIComponent(traineeId)}/session/${encodeURIComponent(sessionId)}?local=1`,{headers:{'Accept':'application/json'}});
    const j = await parseJsonResponse(r,'Chargement impossible');
    if(!r.ok||!j.ok) throw new Error(j.error||'Chargement impossible');
    currentLines = j.lines || [];
    currentFinancialSummary = j.financial_summary || null;
    currentCpfWedofInvoice = j.cpf_wedof_invoice || null;
    render(currentLines);
    if (scheduleSection?.open) readBankSchedule();
    updateQuickInvoiceAction();
  }
  const billingSection = document.getElementById('conventionFinancementSection');
  let localTraineePollTimer;
  function scheduleLocalTraineePoll(immediate=false){
    clearTimeout(localTraineePollTimer);
    if(document.hidden || !billingSection?.open) return;
    if(immediate) load().catch(e=>{ box.textContent = e.message || 'Impossible de charger la facturation.'; });
    localTraineePollTimer=setTimeout(async()=>{try{if(!document.hidden && billingSection?.open) await load();}catch(e){/* retain current finance display */}scheduleLocalTraineePoll();},30000);
  }
  document.addEventListener('visibilitychange',()=>scheduleLocalTraineePoll(!document.hidden));
  window.refreshQontoInvoiceHistory = () => load().catch(e=>{ box.innerHTML = `<div class="qonto-error">${esc(e.message)}</div>`; });
  window.addEventListener('qonto-billing-refresh', window.refreshQontoInvoiceHistory);
  function paymentStatusLabel(status){return ({partially_paid:'Partiellement payé',paid:'Payé',partial:'Paiement partiel',failed:'Rejeté',unpaid:'Non payé',draft:'Brouillon',canceled:'Annulée',cancelled:'Annulée',unknown:'Inconnu',pending:'En attente'}[String(status||'').toLowerCase()]||status||'Inconnu');}

  function mandateState(lines){
    const signedStatuses = new Set(['accepted','approved','signed','validated','active','completed','success','succeeded']);
    const pendingStatuses = new Set(['pending','sent','created','waiting','waiting_signature','processing','in_progress']);
    const personalLines = lines.filter(l=>String([l.financingType,l.financingLabel,l.financeurName,l.financeur].join(' ')).toLowerCase().includes('personnel') || l.paymentMode === 'sepa_direct_debit');
    const statuses = personalLines.map(l=>String(l.qonto_mandate_status || l.qontoMandateStatus || l.mandateStatus || l.qontoPaymentGlobalStatus || '').toLowerCase());
    const hasSigned = personalLines.some(l=>l.qonto_mandate_signed_at || l.mandateSignedAt || signedStatuses.has(String(l.qonto_mandate_status || l.qontoMandateStatus || l.mandateStatus || '').toLowerCase()));
    const hasSent = hasSigned || personalLines.some(l=>{const status=String(l.qonto_mandate_status || l.qontoMandateStatus || l.mandateStatus || '').toLowerCase();return !['failed','rejected','cancelled','canceled','expired'].includes(status)&&(l.qonto_direct_debit_mandate_id || l.qontoMandateId || l.mandateId || (l.directDebitInstallments || []).length || pendingStatuses.has(status));});
    return {hasSent, hasSigned, statuses};
  }
  function lineHasValidatedMandate(line){
    const signedStatuses = new Set(['accepted','approved','signed','validated','active','completed','success','succeeded']);
    const status = String(line.qonto_mandate_status || line.qontoMandateStatus || line.mandateStatus || '').toLowerCase();
    return Boolean(line.qonto_mandate_signed_at || line.mandateSignedAt || signedStatuses.has(status));
  }
  function lineHasPendingMandate(line){
    const pendingStatuses = new Set(['pending','pending_signature','sent','created','waiting','waiting_signature','processing','in_progress']);
    const status = String(line.qonto_mandate_status || line.qontoMandateStatus || line.mandateStatus || '').toLowerCase();
    const hasMandate = Boolean(line.qonto_direct_debit_mandate_id || line.qontoMandateId || line.mandateId);
    const hasSignUrl = Boolean(line.sign_url || line.qonto_mandate_sign_url);
    return hasMandate && hasSignUrl && pendingStatuses.has(status) && !lineHasValidatedMandate(line);
  }
  function qontoScheduleState(lines){
    const sepaLines = lines.filter(l=>l.paymentMode === 'sepa_direct_debit' && lineHasValidatedMandate(l));
    const schedules = sepaLines
      .map(l=>Array.isArray(l.directDebitInstallments) ? l.directDebitInstallments : [])
      .filter(installments=>installments.length);
    const hasScheduledInQonto=schedules.length>0 && schedules.every(installments=>installments.every(installment=>Boolean(installment.qonto_direct_debit_subscription_id)));
    const needsQontoScheduling=sepaLines.some(line=>!line.financial_tracking_override?.enabled && logicalInstallmentsForLine(line).some(row=>!row.qonto_direct_debit_subscription_id && !['completed','paid','succeeded','success'].includes(String(row.status||'').toLowerCase())));
    return {hasScheduledInQonto, needsQontoScheduling};
  }
  function generatedCashPersonalInvoiceAmount(lines){
    return lines
      .filter(l=>{
        const label = String([l.financingType,l.financingLabel,l.financeurName,l.financeur].join(' ')).toLowerCase();
        const isPersonal = label.includes('personnel') || String(l.financingType || '').toUpperCase().includes('PERSONNEL');
        const isCash = l.paymentMode !== 'sepa_direct_debit';
        const hasInvoice = !!(l.qontoInvoiceId || l.qontoDraftId || l.invoiceGeneratedAt || ['draft','finalized','sent','paid'].includes(String(l.invoiceStatus || '').toLowerCase()));
        const isActive = !['cancelled','deleted'].includes(String(l.invoiceStatus || '').toLowerCase());
        return isPersonal && isCash && hasInvoice && isActive;
      })
      .reduce((total, line)=>total + lineAmount(line), 0);
  }
  function financingValidationFrom(c, lines){
    if(financeValidationManualMode && financeValidationManualStatus === 'validated') return {label:'Financement validé', tone:'green', icon:'✓', manual:true};
    const epsilon = 0.01;
    if(c.montantCpf <= epsilon && c.montantPersonnel <= epsilon && c.montantAutre <= epsilon) return {label:'Financement à valider', tone:'gray', icon:'⌛'};
    const fullyFunded = c.prixFormation > epsilon && c.totalFinancement + epsilon >= c.prixFormation;
    const trackedAmountFullyPaid = c.objectifFacturation > epsilon && c.totalPaye + epsilon >= c.objectifFacturation;
    if(c.montantAutre > epsilon && fullyFunded && trackedAmountFullyPaid) return {label:'Financement validé', tone:'green', icon:'✓'};
    if(c.montantPersonnel > epsilon){
      if(generatedCashPersonalInvoiceAmount(lines) + epsilon >= c.montantPersonnel) return {label:'Financement validé', tone:'green', icon:'✓'};
      const mandate = mandateState(lines);
      if(mandate.hasSigned) return {label:'Financement validé', tone:'green', icon:'✓'};
      if(mandate.hasSent) return {label:'Mandat de prélèvement en cours de validation', tone:'orange', icon:'⚠'};
      return {label:'Financement à valider', tone:'gray', icon:'⌛'};
    }
    if(c.prixFormation > epsilon && c.montantCpf + epsilon >= c.prixFormation && c.montantPersonnel <= epsilon && c.montantAutre <= epsilon) return {label:'Financement validé', tone:'green', icon:'✓'};
    return {label:'Financement à valider', tone:'gray', icon:'⌛'};
  }
  function syncFinancementStatusIfValidated(state){
    if(state.tone !== 'green' || currentFinancementStatus === 'validated' || financeStatusSyncInFlight) return;
    financeStatusSyncInFlight = true;
    updateTrainee({financement_status:'validated'})
      .then(()=>{ currentFinancementStatus = 'validated'; })
      .catch((error)=>{ console.error('Synchronisation statut financement impossible', error); })
      .finally(()=>{ financeStatusSyncInFlight = false; });
  }
  function applyFinancingValidationState(state){
    if(!financeValidationStatus) return;
    financeValidationStatus.className = `finance-validation-status finance-validation-status--${state.tone}`;
    financeValidationStatus.innerHTML = `<span class="finance-validation-status__icon">${esc(state.icon)}</span><span class="finance-validation-status__label">${esc(state.label)}</span>${state.manual?'<span class="finance-validation-status__manual">manuel</span>':''}`;
    financeValidationForceBtn?.toggleAttribute('disabled', state.manual);
    if(financeValidationAutoBtn) financeValidationAutoBtn.style.display = state.manual ? '' : 'none';
  }
  function renderFinancingValidation(c, lines){
    const state = financingValidationFrom(c, lines);
    applyFinancingValidationState(state);
    syncFinancementStatusIfValidated(state);
  }
  const isoToday=()=>{const d=new Date();d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,10);};
  function addDays(date,days){const d=new Date(date+'T00:00:00');d.setDate(d.getDate()+days);return d.toISOString().slice(0,10);}
  function addMonths(date, months){const d=new Date(date+'T00:00:00'); const day=d.getDate(); d.setMonth(d.getMonth()+months); if(d.getDate()!==day)d.setDate(0); return d.toISOString().slice(0,10);}
  function debitCutoffDate(line=currentLine){const limit=line?.examDate||line?.dateEnd||line?.dateStart||''; return limit ? addDays(String(limit).slice(0,10),-3) : '';}
  function maxInstallmentsFor(first,line=currentLine){const cutoff=debitCutoffDate(line); if(!first||!cutoff||first>cutoff)return 0; let count=0,next=first; while(next<=cutoff&&count<60){count++; next=addMonths(first,count);} return count;}
  function defaultFirstDebitDate(line=currentLine){const recommended=addDays(isoToday(),7), cutoff=debitCutoffDate(line); return cutoff&&recommended>cutoff?cutoff:recommended;}
  function splitInstallments(total,count){count=Math.max(1,Number(count||1)); const cents=Math.round(Number(total||0)*100), base=Math.floor(cents/count); return Array.from({length:count},(_,i)=>(base+(i===count-1?cents-base*count:0))/100);}
  function scheduleRows(total,count,first){return splitInstallments(total,count).map((amount,i)=>({date:addMonths(first,i),amount,status:'scheduled'}));}
  function currentScheduleRows(){return [...document.querySelectorAll('[data-installment-row]')].map(row=>({date:row.querySelector('[data-installment-date]')?.value||'',amount:Number(String(row.querySelector('[data-installment-amount]')?.value||0).replace(',','.')),status:'scheduled'})).filter(r=>r.date&&r.amount>0);}
  function rebalanceScheduleAmounts(){const rows=[...document.querySelectorAll('[data-installment-row]')], amounts=splitInstallments(currentLine?.amountTTC||currentLine?.amount||0,rows.length); rows.forEach((row,i)=>{const input=row.querySelector('[data-installment-amount]'); if(input)input.value=amounts[i].toFixed(2);});}
  function rebuildInstallmentOptions(selected){const select=document.getElementById('installments'); if(!select)return; const first=document.getElementById('firstDebitDate')?.value||defaultFirstDebitDate(); const max=maxInstallmentsFor(first); select.innerHTML=''; if(max<1){select.append(new Option('0', '0', true, true)); return;} for(let i=1;i<=max;i++)select.append(new Option(String(i),String(i),false,i===Math.min(Number(selected||max),max)));}
  function renderSchedulePreview(){const box=document.getElementById('installmentPreview'); if(!box||!currentLine)return; const mode=document.querySelector('input[name=paymentMode]:checked')?.value||'cash'; const sepaFields=document.getElementById('sepaPaymentFields'); if(sepaFields)sepaFields.style.display=mode==='cash'?'none':''; if(mode==='cash'){box.innerHTML='<div class="hint">Paiement comptant : aucune échéance SEPA.</div>'; return;} const first=document.getElementById('firstDebitDate')?.value||defaultFirstDebitDate(); const count=Number(document.getElementById('installments')?.value||0); const cutoff=debitCutoffDate(); if(!count){box.innerHTML=`<div class="billing-modal-error">Aucune échéance possible${cutoff?` avant le ${esc(formatIsoDateFr(cutoff))}`:''}. Passez en comptant ou modifiez la date de premier prélèvement.</div>`; return;} box.innerHTML=scheduleRows(currentLine.amountTTC||currentLine.amount,count,first).map((r,i)=>`<div class="kv" data-installment-row><div style="display:flex;justify-content:space-between;gap:8px;align-items:center;"><b>Échéance ${i+1}</b><button type="button" class="btn btn-outline" data-remove-installment style="padding:4px 8px;">Supprimer</button></div><div class="label">Date</div><input type="date" data-installment-date value="${esc(r.date)}" max="${esc(cutoff)}"><div class="label">Montant</div><input type="number" data-installment-amount min="0" step="0.01" value="${r.amount.toFixed(2)}"></div>`).join('')+`<div class="hint">Échéances calculées automatiquement jusqu’à 3 jours avant la date limite (examen ou fin de session)${cutoff?` (${esc(formatIsoDateFr(cutoff))})`:''}. Les dates et montants restent modifiables.</div>`; box.querySelectorAll('[data-remove-installment]').forEach(btn=>btn.onclick=()=>{btn.closest('[data-installment-row]')?.remove(); const rows=box.querySelectorAll('[data-installment-row]').length; const select=document.getElementById('installments'); if(select){rebuildInstallmentOptions(rows); select.value=String(rows);} rebalanceScheduleAmounts();});}
  function getPaymentPlanPayload(){const mode=document.querySelector('input[name=paymentMode]:checked')?.value||'cash'; if(mode==='cash')return {paymentMode:mode,installments:1,firstDebitDate:null,frequency:null,schedule:[]}; const schedule=currentScheduleRows(); return {paymentMode:mode,installments:schedule.length,firstDebitDate:schedule[0]?.date||null,frequency:'monthly',schedule};}
  function installmentDate(installment){return String(installment?.date||installment?.due_date||'').slice(0,10);}
  function installmentIsRejected(installment){return ['failed','returned','rejected','refunded','declined'].includes(String(installment?.status||'').toLowerCase());}
  function installmentRejectionTreated(installment){return Boolean(installment?.rejection_treated||installment?.rejection_treated_at);}
  function installmentCountsTowardSchedule(installment){return !installment?.tracking_removed_at&&!installment?.excluded_from_schedule_totals&&!installmentRejectionTreated(installment);}
  function installmentSchedulePosition(installment,fallback=1){const value=Number(installment?.schedule_index||installment?.index||fallback);return Number.isFinite(value)&&value>0?value:fallback;}
  function installmentAttemptTime(installment){return String(installment?.created_at||installment?.reprogrammed_at||installment?.updated_at||'');}
  function installmentAttemptAuthority(installment){const status=String(installment?.status||'').toLowerCase();if(['completed','paid','succeeded','success'].includes(status))return 4;if(installmentIsRejected(installment))return 3;if(['cancelled','canceled'].includes(status))return 2;return 1;}
  function installmentRankAfter(candidate,current){for(let i=0;i<candidate.length;i++){if(candidate[i]===current[i])continue;return candidate[i]>current[i];}return false;}
  function currentInstallmentForSlot(candidates){const attempts=new Map();candidates.forEach(({item,order})=>{const subscription=String(item?.qonto_direct_debit_subscription_id||''),key=subscription?`qonto:${subscription}`:`row:${order}`,current=attempts.get(key),candidateRank=[installmentAttemptAuthority(item),Number(Boolean(item?.qonto_direct_debit_collection_id)),String(item?.updated_at||''),order],currentRank=current?[installmentAttemptAuthority(current.item),Number(Boolean(current.item?.qonto_direct_debit_collection_id)),String(current.item?.updated_at||''),current.order]:null;if(!current||installmentRankAfter(candidateRank,currentRank))attempts.set(key,{item,order});});const rows=[...attempts.values()],paid=rows.filter(({item})=>['completed','paid','succeeded','success'].includes(String(item?.status||'').toLowerCase())),pool=paid.length?paid:rows;return pool.sort((a,b)=>installmentAttemptTime(a.item).localeCompare(installmentAttemptTime(b.item))||a.order-b.order).at(-1)?.item;}
  function logicalInstallmentsForLine(line){const items=Array.isArray(line?.directDebitInstallments)?line.directDebitInstallments:[],slots=new Map();items.forEach((item,index)=>{if(!installmentCountsTowardSchedule(item))return;const position=installmentSchedulePosition(item,index+1);if(!slots.has(position))slots.set(position,[]);slots.get(position).push({item,order:index+1});});return [...slots.entries()].sort((a,b)=>a[0]-b[0]).map(([,candidates])=>currentInstallmentForSlot(candidates)).filter(Boolean);}
  function installmentScheduleTotal(line,items=Array.isArray(line?.directDebitInstallments)?line.directDebitInstallments:[]){if(line?.financial_tracking_override?.source==='inline_schedule')return logicalInstallmentsForLine(line).length;const paymentPlan=line?.paymentPlan||{},paymentSchedule=Array.isArray(paymentPlan.schedule)?paymentPlan.schedule:[],normalized=paymentSchedule.length||Number(paymentPlan.installments||0),frequencies=new Map();items.forEach(item=>{let total=Number(item?.schedule_total||0);if(!total){const match=String(item?.reference||'').match(/[ée]ch[ée]ance\s+\d+\s*\/\s*(\d+)/i);total=Number(match?.[1]||0);}if(total>0)frequencies.set(total,(frequencies.get(total)||0)+1);});const explicit=[...frequencies.entries()].sort((a,b)=>b[1]-a[1]||a[0]-b[0])[0]?.[0]||0,stored=Number(line?.sepa_payment_plan?.total_installments||0),base=Math.max(0,...items.map((item,index)=>item?.is_rejection_retry?0:installmentSchedulePosition(item,index+1))),effective=logicalInstallmentsForLine(line).length;return normalized||base||explicit||stored||effective;}
  function installmentScheduleContext(line){const items=Array.isArray(line?.directDebitInstallments)?line.directDebitInstallments:[],effective=logicalInstallmentsForLine(line);return {items,effective,current:new Set(effective),total:installmentScheduleTotal(line,items)};}
  function installmentStatusLabel(installment){if(installment?.tracking_removed_at)return 'Supprimée du suivi';const value=String(installment?.status||'scheduled').toLowerCase();if(installmentIsRejected(installment)&&installmentRejectionTreated(installment))return 'Rejet traité';if(['completed','paid','succeeded','success'].includes(value))return 'Payé';if(installmentIsRejected(installment))return 'Rejeté';if(installment?.tracking_pending_qonto)return 'À mettre à jour dans Qonto';if(value==='scheduled'&&installment?.manual_tracking_entry)return 'Programmé';return installment?.qonto_direct_debit_subscription_id?'Programmé':'À venir';}
  function installmentFailureReasonLabel(reason){const value=String(reason||'').trim().toLowerCase();const labels={blocked_account:'Compte bancaire bloqué',insufficient_funds:'Solde insuffisant',closed_account:'Compte bancaire clôturé',invalid_account:'Coordonnées bancaires invalides',bank_account_closed:'Compte bancaire clôturé',revoked_mandate:'Mandat de prélèvement révoqué',no_mandate:'Mandat de prélèvement absent',mandate_not_found:'Mandat de prélèvement introuvable',refused_by_bank:'Prélèvement refusé par la banque',debtor_dispute:'Prélèvement contesté par le titulaire',duplicate:'Prélèvement en double',regulatory_reason:'Rejet pour raison réglementaire',technical_error:'Erreur technique bancaire'};return labels[value]||(value?'Motif bancaire non répertorié':'');}
  function renderScheduleModal(line){
    const items=(line.initialDebitSchedule || []).map(row=>({...row,line}));
    return `<div class="billing-modal-head"><h2>Échéancier initial</h2><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div>${initialTable(items)}<div class="billing-modal-actions"><button class="btn btn-outline" data-modal-close>Fermer</button></div>`;
  }
  function closeBillingModal(){document.querySelectorAll('.billing-modal-overlay').forEach(m=>m.remove());currentLine=null;modalLoading=false;}
  function qontoInfoCompletionUrl(line=currentLine){const sid=line?.sessionId||sheetContext.sessionId,tid=line?.traineeId||line?.studentId||sheetContext.traineeId;return sid&&tid?`/admin/sessions/${encodeURIComponent(sid)}/stagiaires/${encodeURIComponent(tid)}#conventionFinancementSection`:'';}
function isQontoIncompleteClientError(text){return /informations client incomplètes/i.test(String(text||''));}
function modalMessage(text,type='error'){const msg=document.getElementById('modalMsg');if(!msg)return;msg.className=type==='success'?'billing-modal-success':'billing-modal-error';if(type==='error'&&isQontoIncompleteClientError(text)){const url=qontoInfoCompletionUrl();const action=url?`<div class="billing-modal-actions" style="justify-content:flex-start;margin-top:12px;"><a class="btn btn-primary" href="${esc(url)}" data-qonto-info-completion>Compléter les informations</a></div>`:'';msg.innerHTML=`<div>${esc(text)}</div>${action}`;return;}msg.textContent=text;}
  function isOtherFinancingLine(line){return String(line?.financingType||line?.typeFinanceur||'').toUpperCase().includes('AUTRE');}
  function invoiceRecipientFields(line){
    if(!isOtherFinancingLine(line))return '';
    return `<div class="qonto-invoice-card" id="otherInvoiceRecipient" style="margin-top:14px;"><div class="qonto-title">Entreprise à facturer</div><div class="muted" style="margin-bottom:12px;">La facture et le mandat de prélèvement seront établis au nom de cette entreprise, et non du stagiaire.</div><div class="billing-modal-grid"><label><span class="label">Nom de l’entreprise *</span><input id="invoiceCompanyName" required value="${esc(line.companyName||line.clientName||'')}"></label><label><span class="label">Email de facturation (facultatif)</span><input id="invoiceCompanyEmail" type="email" value="${esc(line.clientEmail||'')}"><span class="invoice-notes-hint">Sans email, la facture pourra être téléchargée puis envoyée manuellement.</span></label><label><span class="label">Adresse *</span><input id="invoiceCompanyAddress" required value="${esc(line.clientAddress||'')}"></label><label><span class="label">Code postal *</span><input id="invoiceCompanyZipCode" required value="${esc(line.clientZipCode||'')}"></label><label><span class="label">Ville *</span><input id="invoiceCompanyCity" required value="${esc(line.clientCity||'')}"></label><label><span class="label">SIRET *</span><input id="invoiceCompanySiret" inputmode="numeric" required value="${esc(line.siret||'')}"></label></div><label class="invoice-notes-field" for="invoiceNotes"><span class="label">Informations à faire apparaître sur la facture</span><span class="invoice-notes-hint">Ajoutez les références utiles qui seront visibles sur le document.</span><textarea id="invoiceNotes" rows="3" placeholder="Ex. : numéro de dossier, référence de commande…">${esc(line.invoiceNotes||'')}</textarea></label></div>`;
  }
  function getInvoiceRecipientPayload(){
    if(!isOtherFinancingLine(currentLine))return null;
    const value=id=>String(document.getElementById(id)?.value||'').trim();
    const recipient={companyName:value('invoiceCompanyName'),email:value('invoiceCompanyEmail'),address:value('invoiceCompanyAddress'),zipCode:value('invoiceCompanyZipCode'),city:value('invoiceCompanyCity'),siret:value('invoiceCompanySiret'),invoiceNotes:value('invoiceNotes')};
    if(!recipient.companyName||!recipient.address||!recipient.zipCode||!recipient.city||!recipient.siret){modalMessage('Renseignez le nom, le SIRET et l’adresse complète de l’entreprise à facturer.','error');return false;}
    if(!/^\d{14}$/.test(recipient.siret.replace(/[\s.-]/g,''))){modalMessage('Le SIRET de l’entreprise doit contenir exactement 14 chiffres.','error');return false;}
    return recipient;
  }
  function hasSepaPaymentPlan(line, paymentPlan){return String(paymentPlan?.paymentMode||paymentPlan?.mode||line?.paymentMode||'cash')==='sepa'||String(line?.paymentMode||'')==='sepa_direct_debit'||(Array.isArray(line?.directDebitInstallments)&&line.directDebitInstallments.length>0);}
  function createdInvoiceMessage(line, paymentPlan){const isFinal=['finalized','sent','paid'].includes(String(line.invoiceStatus||'').toLowerCase());const sepa=hasSepaPaymentPlan(line,paymentPlan);if(sepa)return isFinal?'Facture définitive générée et mandat de prélèvement créé.':'Brouillon créé et mandat de prélèvement créé. Vous pouvez maintenant consulter la facture ou synchroniser le paiement.';return isFinal?'Facture définitive générée avec paiement comptant. Vous pouvez maintenant consulter la facture ou synchroniser le paiement.':'Brouillon créé avec paiement comptant. Vous pouvez maintenant consulter la facture ou synchroniser le paiement.';}
  function renderInvoiceModalContent(line, created=false, paymentPlan=null){
    if(lineHasExternalInvoice(line))return `<div class="billing-modal-head"><h2>Facture générée ailleurs</h2><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div><div class="billing-modal-existing">Cette facture est déjà enregistrée comme générée ailleurs. Aucune nouvelle facture n’est nécessaire.</div><p>Le téléchargement sera disponible après rattachement de la facture Qonto.</p><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button></div>`;
    const vat=Number(line.vatRate||0), totalTtc=Number(line.amountTTC||line.amount||0), totalHt=vat?totalTtc/(1+vat/100):totalTtc, totalTva=totalTtc-totalHt, hasInvoice=!!(line.qontoInvoiceId||line.qontoDraftId), completionUrl=qontoInfoCompletionUrl(line), completionButton=completionUrl?`<a class="btn btn-outline" href="${esc(completionUrl)}" data-qonto-info-completion>Compléter les informations</a>`:'';
    return `<div class="billing-modal-head"><div><h2>Vérification avant création Qonto</h2><div class="muted">Contrôlez les informations, puis confirmez simplement la création de la facture définitive avec le mode de paiement sélectionné.</div><span class="billing-modal-step">Étape 1 · Récapitulatif</span></div><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div>${hasInvoice?'<div class="billing-modal-existing">Une facture existe déjà pour cette ligne.</div>':''}<div class="billing-modal-summary"><p><strong>Stagiaire :</strong> ${esc(line.traineeFirstName)} ${esc(line.traineeLastName)}</p><p><strong>Formation :</strong> ${esc(line.formationName)}</p><p><strong>Session / nom pédagogique :</strong> ${esc(line.sessionName||line.formationName)}</p><p><strong>Dates :</strong> ${esc(line.dateLabel)}</p><p><strong>Financeur :</strong> ${esc(line.financeurName||line.financingLabel||line.financingType)}</p><p><strong>Montant exact de la ligne :</strong> ${fmtMoney(totalTtc)}</p><p><strong>Numéro facture :</strong> ${esc(line.qontoInvoiceNumber||line.qontoInvoiceId||line.qontoDraftId||'En attente')}</p><p><strong>Statut facture :</strong> ${label(line.invoiceStatus)}</p><p><strong>Statut paiement :</strong> ${paymentStatusLabel(line.paymentStatus)}</p></div>${isCpfQontoLine(line)?'<div class="billing-modal-success">Client CPF pré-rempli automatiquement</div>':''}<div class="billing-modal-grid"><div class="kv"><b>Total HT</b><br>${fmtMoney(totalHt)}</div><div class="kv"><b>TVA / exonération</b><br>${vat}% · ${fmtMoney(totalTva)}</div><div class="kv"><b>Total TTC</b><br>${fmtMoney(totalTtc)}</div><div class="kv"><b>Client</b><br>${esc(line.clientName||'')}</div></div>${invoiceRecipientFields(line)}<div class="qonto-invoice-card" style="margin-top:14px;"><div class="qonto-title">Mode de paiement</div><label><input type="radio" name="paymentMode" value="cash" checked> Comptant</label><br><label><input type="radio" name="paymentMode" value="sepa"> Prélèvement SEPA en plusieurs fois</label><div id="sepaPaymentFields" class="billing-modal-grid"><div><div class="label">Nombre d’échéances possibles</div><select id="installments"></select></div><div><div class="label">Date du premier prélèvement</div><input id="firstDebitDate" type="date" value="${esc(defaultFirstDebitDate(line))}" max="${esc(debitCutoffDate(line))}"></div><div><div class="label">Fréquence</div><input value="Mensuelle" disabled></div></div><div id="installmentPreview" class="billing-modal-grid"></div></div><div id="modalMsg" class="${created?'billing-modal-success':''}">${created?(['finalized','sent','paid'].includes(String(line.invoiceStatus||'').toLowerCase())?'Facture définitive générée et mandat de prélèvement créé.':'Brouillon créé et mandat de prélèvement créé. Vous pouvez maintenant consulter la facture ou synchroniser le paiement.'):''}</div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button>${!hasInvoice?completionButton:''}${hasInvoice?`<a class="btn btn-outline" href="/admin/qonto/invoices/${encodeURIComponent(line.qontoInvoiceId||line.qontoDraftId||"")}/pdf" target="_blank" rel="noopener">Voir la facture</a>`:`<button type="button" class="btn btn-primary" id="openInvoiceDecision">Continuer</button>`}</div>`;
  }
  function bindModalCloseButtons(){document.querySelectorAll('[data-modal-close]').forEach(btn=>btn.onclick=closeBillingModal);}
  function renderQontoTransmission(kind){const title=kind==='mandate'?'Mandat de prélèvement en cours de transmission':(kind==='reschedule'?'Nouveau prélèvement en cours de transmission':'Facture en cours de transmission');return `<div class="qonto-result qonto-result--loading" role="status" aria-live="polite"><div class="qonto-result__brand">QONTO</div><div class="qonto-result__loader" aria-hidden="true"><span></span><span></span><span></span></div><div class="qonto-result__eyebrow">Transmission sécurisée</div><h2>${title}</h2><p>Nous envoyons les informations à Qonto et attendons sa confirmation. Ne fermez pas cette fenêtre.</p><div class="qonto-result__progress"><span></span></div></div>`;}
  function renderQontoSuccess(kind, reference, line){const mandate=kind==='mandate',rum=String(line?.qonto_mandate_rum||'').trim(),invoiceWithMandate=!mandate&&line?.paymentMode==='sepa_direct_debit'&&rum,title=mandate?'Mandat de prélèvement créé avec succès':(invoiceWithMandate?'Facture et mandat créés avec succès':'Facture créée avec succès'),label=mandate?'Numéro RUM':'Numéro de facture',safeReference=esc(reference||'Confirmation Qonto reçue'),invoiceReference=`<div class="qonto-result__reference"><span>${label}</span><strong>${safeReference}</strong></div>`,mandateReference=invoiceWithMandate?`<div class="qonto-result__reference"><span>Numéro RUM du mandat</span><strong>${esc(rum)}</strong></div>`:'',message=invoiceWithMandate?'Qonto a confirmé la création de la facture et du mandat de prélèvement. Le RUM a été ajouté automatiquement à la stratégie de financement.':'Qonto a confirmé la création. Cette référence est enregistrée automatiquement dans le dossier du stagiaire.',pdf=!mandate&&line?.qontoInvoiceId?`<a class="btn btn-outline" href="/admin/qonto/invoices/${encodeURIComponent(line.qontoInvoiceId)}/pdf" target="_blank" rel="noopener">Voir la facture</a>`:'';return `<div class="qonto-result qonto-result--success" role="status" aria-live="polite"><button class="billing-modal-close qonto-result__close" type="button" data-modal-close aria-label="Fermer">✕</button><div class="qonto-result__brand">QONTO</div><div class="qonto-result__check" aria-hidden="true">✓</div><div class="qonto-result__eyebrow">Confirmation reçue</div><h2>${title}</h2><p>${message}</p>${invoiceReference}${mandateReference}<div class="billing-modal-actions">${pdf}<button type="button" class="btn btn-primary" data-modal-close>Terminer</button></div></div>`;}
  function renderQontoRescheduleSuccess(result){const count=Number(result?.count||1),dates=(Array.isArray(result?.collectionDates)?result.collectionDates:[result?.collectionDate]).filter(Boolean).map(formatIsoDateFr),ids=Array.isArray(result?.subscriptionIds)?result.subscriptionIds.filter(Boolean):[],title=count>1?'Nouveaux prélèvements mis en place avec succès':'Nouveau prélèvement mis en place avec succès';return `<div class="qonto-result qonto-result--success" role="status" aria-live="polite"><button class="billing-modal-close qonto-result__close" type="button" data-modal-close aria-label="Fermer">✕</button><div class="qonto-result__brand">QONTO</div><div class="qonto-result__check" aria-hidden="true">✓</div><div class="qonto-result__eyebrow">Confirmation reçue</div><h2>${title}</h2><p>Qonto a confirmé la programmation. Le rejet initial est maintenant marqué comme traité et le nouveau prélèvement apparaît dans l’échéancier.</p><div class="qonto-result__reference"><span>Date${dates.length>1?'s':''} des nouveaux prélèvements</span><strong>${esc(dates.join(' · ')||'Confirmée par Qonto')}</strong></div>${ids.length?`<div class="qonto-result__reference"><span>Référence${ids.length>1?'s':''} Qonto</span><strong>${esc(ids.join(' · '))}</strong></div>`:''}<div class="billing-modal-actions"><button type="button" class="btn btn-primary" data-modal-close>Terminer</button></div></div>`;}
  function renderQontoRescheduleError(message){return `<div class="qonto-result qonto-result--error" role="alert"><button class="billing-modal-close qonto-result__close" type="button" data-modal-close aria-label="Fermer">✕</button><div class="qonto-result__brand">QONTO</div><div class="qonto-result__error" aria-hidden="true">!</div><div class="qonto-result__eyebrow">Transmission interrompue</div><h2>Le nouveau prélèvement n’a pas pu être confirmé</h2><p>${esc(message||'Reprogrammation impossible pour le moment.')}</p><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button></div></div>`;}
  function bindInvoiceModalControls(){bindModalCloseButtons();const decision=document.getElementById('openInvoiceDecision');if(decision)decision.onclick=showFinalDecision;rebuildInstallmentOptions();const first=document.getElementById('firstDebitDate');if(first)first.addEventListener('change',()=>{rebuildInstallmentOptions();renderSchedulePreview();});const select=document.getElementById('installments');if(select)select.addEventListener('change',renderSchedulePreview);document.querySelectorAll('input[name=paymentMode]').forEach(el=>el.addEventListener('change',renderSchedulePreview));renderSchedulePreview();}
  function decisionCard(question, yesId, noId, help){return `<div class="qonto-invoice-card" style="margin-top:16px;background:linear-gradient(135deg,#eef6ff,#ffffff);border:1px solid #bfdbfe;box-shadow:0 18px 45px rgba(37,99,235,.12);"><div class="qonto-title" style="font-size:20px;margin-bottom:8px;">${esc(question)}</div>${help?`<div class="muted" style="margin-bottom:16px;">${esc(help)}</div>`:''}<div class="billing-modal-actions" style="justify-content:flex-start;margin-top:10px;"><button type="button" class="btn btn-primary" id="${yesId}">Oui</button><button type="button" class="btn btn-outline" id="${noId}">Non</button></div></div>`;}
  function showFinalDecision(){const msg=document.getElementById('modalMsg');if(!msg)return;msg.className='';msg.innerHTML=decisionCard('Voulez-vous générer la facture ?', 'confirmFinalYes', 'confirmFinalNo', 'Oui : crée la facture puis la finalise dans Qonto avec le mode de paiement sélectionné.');document.getElementById('confirmFinalYes').onclick=createCurrentInvoice;document.getElementById('confirmFinalNo').onclick=()=>{msg.innerHTML='';};}
  function openGenerateInvoiceModal(line){if(lineHasExternalInvoice(line)){showQontoFeedback('Cette facture est déjà générée ailleurs. Aucune nouvelle facture n’est nécessaire.');return;}currentLine=line;document.body.insertAdjacentHTML('beforeend',`<div class="billing-modal-overlay no-print" role="dialog" aria-modal="true"><div class="billing-modal">${renderInvoiceModalContent(line)}</div></div>`);bindInvoiceModalControls();}
  function openCreateMandateModal(line){currentLine=line;document.body.insertAdjacentHTML('beforeend',`<div class="billing-modal-overlay no-print" role="dialog" aria-modal="true"><div class="billing-modal"><div class="billing-modal-head"><div><h2>Créer un mandat de prélèvement</h2><div class="muted">Crée le client Qonto si nécessaire, le mandat SEPA et son lien de signature, sans créer de facture.</div></div><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div>${invoiceRecipientFields(line)}<div class="billing-modal-grid"><div><div class="label">Nombre d’échéances</div><select id="installments"></select></div><div><div class="label">Date du premier prélèvement</div><input id="firstDebitDate" type="date" value="${esc(defaultFirstDebitDate(line))}" max="${esc(debitCutoffDate(line))}"></div></div><input type="radio" name="paymentMode" value="sepa" checked hidden><div id="installmentPreview" class="billing-modal-grid"></div><div id="modalMsg"></div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button><button type="button" class="btn btn-primary" id="confirmCreateMandate">Créer le mandat de prélèvement</button></div></div></div></div>`);bindModalCloseButtons();rebuildInstallmentOptions((line.directDebitInstallments||[]).length||undefined);document.getElementById('firstDebitDate')?.addEventListener('change',()=>{rebuildInstallmentOptions();renderSchedulePreview();});document.getElementById('installments')?.addEventListener('change',renderSchedulePreview);renderSchedulePreview();document.getElementById('confirmCreateMandate').onclick=createCurrentMandate;}
  function rejectedInstallments(){
    return currentLines.flatMap(line=>(line.directDebitInstallments||[]).map((installment,index)=>({line,installment,index})))
      .filter(({line,installment,index})=>installmentIsRejected(installment) && !installmentRejectionTreated(installment) && !line.debitRejectionReview?.treatedIndices?.includes(index));
  }
  function openRescheduleRejectedDebitModal(){
    const rejected=rejectedInstallments();
    if(!rejected.length)return;
    const minDate=new Date();minDate.setDate(minDate.getDate()+1);
    const minIso=minDate.toISOString().slice(0,10);
    const rows=rejected.map((item,i)=>`<div class="kv" data-rejected-debit-row="${i}" style="display:grid;grid-template-columns:auto minmax(180px,1fr) minmax(130px,.45fr) minmax(150px,.5fr);gap:12px;align-items:center"><input type="checkbox" data-rejected-debit-check checked aria-label="Sélectionner le prélèvement du ${esc(formatIsoDateFr(installmentDate(item.installment)))}"><div><b>${esc(formatIsoDateFr(installmentDate(item.installment)))}</b><div class="muted">Montant rejeté : ${fmtMoney(item.installment.amount)}</div></div><label><span class="label">Montant à prélever</span><input type="number" data-rejected-debit-amount min="0.01" step="0.01" value="${Number(item.installment.amount||0).toFixed(2)}" required></label><label><span class="label">Nouvelle date</span><input type="date" data-rejected-debit-date min="${minIso}" value="${minIso}" required></label></div>`).join('');
    document.body.insertAdjacentHTML('beforeend',`<div class="billing-modal-overlay no-print" role="dialog" aria-modal="true"><div class="billing-modal"><div class="billing-modal-head"><div><h2>Reprogrammer des prélèvements</h2><div class="muted">Sélectionnez les prélèvements rejetés, puis indiquez une date et un montant pour chacun.</div></div><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div><div style="display:grid;gap:10px;margin-top:16px">${rows}</div><div id="modalMsg"></div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Annuler</button><button type="button" class="btn btn-primary" id="confirmRescheduleRejectedDebit">Reprogrammer la sélection</button></div></div></div>`);
    bindModalCloseButtons();
    document.querySelectorAll('[data-rejected-debit-check]').forEach(check=>check.addEventListener('change',()=>{check.closest('[data-rejected-debit-row]')?.querySelectorAll('[data-rejected-debit-amount],[data-rejected-debit-date]').forEach(input=>input.disabled=!check.checked);}));
    document.getElementById('confirmRescheduleRejectedDebit').onclick=async()=>{
      const items=[...document.querySelectorAll('[data-rejected-debit-row]')].filter(row=>row.querySelector('[data-rejected-debit-check]')?.checked).map(row=>{const selected=rejected[Number(row.dataset.rejectedDebitRow)],installment=selected.installment;return {lineId:selected.line.id,installmentIndex:selected.index,subscriptionId:installment.qonto_direct_debit_subscription_id||'',collectionId:installment.qonto_direct_debit_collection_id||'',dueDate:installmentDate(installment),amount:Number(row.querySelector('[data-rejected-debit-amount]')?.value),collectionDate:row.querySelector('[data-rejected-debit-date]')?.value||''};});
      if(!items.length){modalMessage('Sélectionnez au moins un prélèvement rejeté.','error');return;}
      if(items.some(item=>!Number.isFinite(item.amount)||item.amount<=0)){modalMessage('Indiquez un montant supérieur à zéro pour chaque prélèvement sélectionné.','error');return;}
      if(items.some(item=>!item.collectionDate)){modalMessage('Choisissez une nouvelle date pour chaque prélèvement sélectionné.','error');return;}
      const button=document.getElementById('confirmRescheduleRejectedDebit');button.disabled=true;button.textContent='Reprogrammation…';
      const modal=document.querySelector('.billing-modal');modalLoading=true;modal.innerHTML=renderQontoTransmission('reschedule');
      try{const result=await billingApi('/api/billing/reschedule-rejected-debit',{items,source:'admin_trainee'});await load();modal.innerHTML=renderQontoRescheduleSuccess(result);bindModalCloseButtons();}
      catch(error){modal.innerHTML=renderQontoRescheduleError(error.message||'Reprogrammation impossible');bindModalCloseButtons();}
      finally{modalLoading=false;}
    };
  }
  async function createCurrentMandate(){if(!currentLine||modalLoading)return;const paymentPlan=getPaymentPlanPayload();const invoiceRecipient=getInvoiceRecipientPayload();if(invoiceRecipient===false)return;if(!paymentPlan.schedule.length){modalMessage('Aucune échéance SEPA possible avant la date limite.','error');return;}modalLoading=true;const modal=document.querySelector('.billing-modal');modal.innerHTML=renderQontoTransmission('mandate');try{const result=await billingApi('/api/billing/create-mandate',{lineId:currentLine.id,source:'admin_trainee',paymentPlan,invoiceRecipient});const updated=result.line||currentLine;const rum=updated.qonto_mandate_rum||result.rum||'';currentLine=updated;currentLines=currentLines.map(line=>line.id===updated.id?updated:line);const rumInput=document.getElementById('qontoMandateNumber');if(rumInput&&rum)rumInput.value=rum;await load();modal.innerHTML=renderQontoSuccess('mandate',rum,updated);bindModalCloseButtons();}catch(err){modal.innerHTML=renderQontoTransmission('mandate')+`<div id="modalMsg" class="billing-modal-error">${esc(err.message||'Création du mandat impossible')}</div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button></div>`;bindModalCloseButtons();}finally{modalLoading=false;}}
  async function createCurrentInvoice(){if(!currentLine||modalLoading)return;if(lineHasGeneratedInvoice(currentLine)){modalMessage('Une facture existe déjà pour ce financement. Aucune nouvelle facture ne sera créée.');return;}const paymentPlan=getPaymentPlanPayload();const invoiceRecipient=getInvoiceRecipientPayload();if(invoiceRecipient===false)return;if(paymentPlan.paymentMode!=='cash'&&!paymentPlan.schedule.length){modalMessage('Aucune échéance SEPA possible avant la date limite.','error');return;}modalLoading=true;const modal=document.querySelector('.billing-modal');modal.innerHTML=renderQontoTransmission('invoice');try{const draftData=await billingApi('/api/billing/create-draft',{lineId:currentLine.id,source:'admin_trainee',paymentPlan,invoiceRecipient});let updated=draftData.line||draftData;const finalData=await billingApi('/api/billing/finalize',{lineId:updated.id,source:'admin_trainee'});updated=finalData.line||updated;currentLine=updated;currentLines=currentLines.map(line=>line.id===updated.id?updated:line);render(currentLines);const rumInput=document.getElementById('qontoMandateNumber');if(rumInput&&updated.qonto_mandate_rum)rumInput.value=updated.qonto_mandate_rum;modal.innerHTML=renderQontoSuccess('invoice',updated.qontoInvoiceNumber||updated.qontoInvoiceId,updated);bindModalCloseButtons();}catch(err){modal.innerHTML=renderQontoTransmission('invoice')+`<div id="modalMsg" class="billing-modal-error">${esc(err.message||'Erreur inconnue')}</div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Fermer</button></div>`;bindModalCloseButtons();}finally{modalLoading=false;}}
  function pct(value,total){return total>0?Math.max(0,Math.min(150,(Number(value||0)/total)*100)):0;}
  function invoiceStatusLabel(line){if(lineHasExternalInvoice(line))return 'Facture générée ailleurs';const has=!!(line.qontoInvoiceId||line.qontoDraftId);if(!has)return 'Facture non générée';if(line.paymentStatus==='paid'||line.invoiceStatus==='paid')return 'Facture payée';if(line.paymentStatus==='unpaid'&&['sent','finalized'].includes(line.invoiceStatus))return 'Facture impayée';return ({sent:'Facture envoyée',finalized:'Facture générée',draft:'Brouillon',cancelled:'Annulée',control:'À contrôler'}[line.invoiceStatus]||'Facture générée');}
  function invoiceBadge(line){if(lineHasExternalInvoice(line))return linePaymentStatus(line)==='paid'?'green':'purple';const has=!!(line.qontoInvoiceId||line.qontoDraftId);if(!has)return 'red';if(line.invoiceStatus==='paid'||line.paymentStatus==='paid')return 'green';if(line.paymentStatus==='unpaid'&&['sent','finalized'].includes(line.invoiceStatus))return 'orange';if(['sent','finalized'].includes(line.invoiceStatus))return 'blue';if(line.invoiceStatus==='draft')return 'orange';return 'gray';}
  function badge(text,tone){return `<span class="finance-badge finance-badge--${tone||'gray'}">${esc(text)}</span>`;}
  function canonicalInvoiceEntry(l){return l?.qonto_invoice || null;}
  function lineHasExternalInvoice(l){return !(l.qontoInvoiceId||l.qontoDraftId)&&['external_generated','external','generated_externally'].includes(String(l.invoiceStatus||'').toLowerCase());}
  function lineHasGeneratedInvoice(l){return !!(l.qontoInvoiceId||l.qontoDraftId)||['external_generated','external','generated_externally'].includes(String(l.invoiceStatus||'').toLowerCase());}
  function invoiceOriginBadges(lines){
    const generated=(lines||[]).filter(l=>!isCpfQontoLine(l)&&lineHasGeneratedInvoice(l));
    const hasQonto=generated.some(l=>!!(l.qontoInvoiceId||l.qontoDraftId));
    const hasExternal=generated.some(l=>['external_generated','external','generated_externally'].includes(String(l.invoiceStatus||'').toLowerCase())&&!(l.qontoInvoiceId||l.qontoDraftId));
    return `${hasQonto?badge('QONTO','black'):''}${hasExternal?badge('Générée ailleurs','purple'):''}`;
  }
  function lineAmount(l){const e=canonicalInvoiceEntry(l);return e?Number(e.total_amount_cents ?? 0)/100:Number(l.amountTTC||l.amount||0)}
  function linePaid(l){
    const e=canonicalInvoiceEntry(l),rawInstallments=Array.isArray(l?.directDebitInstallments)?l.directDebitInstallments:[],installments=logicalInstallmentsForLine(l),paidStatuses=new Set(['completed','paid','succeeded','success']),terminalStatuses=new Set([...paidStatuses,'failed','returned','rejected','refunded','declined']);
    const installmentPaid=installments.filter(i=>paidStatuses.has(String(i.status||'').toLowerCase())).reduce((total,i)=>total+Number(i.amount||0),0);
    // Once Qonto has reported a terminal collection, the SEPA history is the
    // authority. This also covers collections completed before the invoice.
    if(Array.isArray(l.qontoBankTransfers)&&l.qontoBankTransfers.length)return Math.max(Number(l.qontoBankTransferPaidCents||0)/100,Number(e?.paid_amount_cents||0)/100);
    if(rawInstallments.some(i=>terminalStatuses.has(String(i.status||'').toLowerCase())))return l.qontoCollectedAmountCents!=null?Number(l.qontoCollectedAmountCents)/100:installmentPaid;
    return e?Number(e.paid_amount_cents ?? 0)/100:installmentPaid;
  }
  function lineRemaining(l){return Math.max(lineAmount(l)-linePaid(l),0)}
  function linePaymentStatus(l){const e=canonicalInvoiceEntry(l),amount=lineAmount(l),paid=linePaid(l),raw=String(e?.payment_status||'unpaid').toLowerCase();if(['canceled','cancelled','control'].includes(raw))return raw;if(amount>0&&paid>=amount)return 'paid';if(paid>0)return 'partially_paid';return raw;}
  // The payment plan is persisted while the mandate is awaiting signature so
  // subscriptions can be created afterwards.  It must not be presented as a
  // programmed debit schedule until Qonto confirms the mandate.
  function allInstallments(lines){return lines.flatMap(l=>{if(!lineHasValidatedMandate(l)&&l?.financial_tracking_override?.source!=='inline_schedule')return [];const context=installmentScheduleContext(l);return context.items.map((it,i)=>({...it,line:l,sourceIndex:i,index:installmentSchedulePosition(it,i+1),total:context.total,isCurrentScheduleAttempt:context.current.has(it)}));});}
  function statusFromRatio(value,total,labels){if(total<=0)return [labels.none,'gray'];if(value<=0)return [labels.zero,'gray'];if(value<total)return [labels.partial,'orange'];if(value===total)return [labels.done,'green'];return [labels.over,'red'];}
  function computeFinance(lines){
    const parseMoneyValue=(value)=>{const n=parseFloat(String(value||'').replace(',','.').trim());return Number.isNaN(n)?0:n;};
    const defaultPrice=()=>{const details=document.getElementById('financementDetails');const dataDefault=parseMoneyValue(details?.dataset.defaultPrice);if(dataDefault>0)return dataDefault;const type=String(details?.dataset.trainingType||'').toUpperCase();if(type==='A3P')return 4200;if(type==='APS')return 1650;if(type==='DIRIGEANT INITIAL')return 4300;if(type==='DIRIGEANT VAE')return 3800;if(type.includes('VTC'))return 1500;if(type.includes('SSIAP'))return 980;return 0;};
    const prixFormation=parseMoneyValue(trainingPrice?.value)||defaultPrice();
    const montantCpf=parseMoneyValue(cpfAmount?.value), montantPersonnel=parseMoneyValue(personalAmount?.value), montantAutre=parseMoneyValue(otherAmount?.value);
    const totalFinancement=montantCpf+montantPersonnel+montantAutre;
    const objectifFacturation=(montantPersonnel+montantAutre)>0?(montantPersonnel+montantAutre):(totalFinancement>0?0:prixFormation);
    const active=lines.filter(l=>!['cancelled','deleted'].includes(String(l.invoiceStatus||'')));
    const billable=active.filter(l=>!isCpfQontoLine(l));
    const invoiced=billable.filter(lineHasGeneratedInvoice);
    const totalFacture=invoiced.reduce((a,l)=>a+lineAmount(l),0);
    const qontoPaid=billable.reduce((a,l)=>a+linePaid(l),0);
    const cashInstallmentsTotal=window.getFinanceCashInstallmentsTotal?window.getFinanceCashInstallmentsTotal():0;
    const cashPaid=(cashPaymentEnabled?.checked&&cashPaymentSettled?.checked)?parseMoneyValue(cashPaymentAmount?.value):cashInstallmentsTotal;
    const cashInstallments=window.getFinanceCashInstallments?window.getFinanceCashInstallments():[];
    const cashPaymentCount=cashInstallments.filter(item=>parseMoneyValue(item?.amount)>0).length||(cashPaid>0?1:0);
    const totalPaye=qontoPaid+cashPaid;
    const installments=allInstallments(lines),effectiveInstallments=installments.filter(i=>i.isCurrentScheduleAttempt);const paidStatuses=new Set(['completed','paid','succeeded','success']);const rejectStatuses=new Set(['failed','returned','rejected','refunded','declined']);
    const mensualitesPayees=effectiveInstallments.filter(i=>paidStatuses.has(String(i.status||'').toLowerCase())).length;
    const nombreRejets=Object.values(reviewSelection(lines)).reduce((sum,keys)=>sum+keys.length,0);
    const nombreRejetsTraites=lines.reduce((sum,line)=>sum+(line.debitRejectionReview?.treated.length ??
      installments.filter(it=>it.line===line && installmentRejectionTreated(it)).length),0);
    const today=isoToday();
    const upcoming=effectiveInstallments.filter(i=>!paidStatuses.has(String(i.status||'').toLowerCase())&&!rejectStatuses.has(String(i.status||'').toLowerCase())&&installmentDate(i)>=today).sort((a,b)=>installmentDate(a).localeCompare(installmentDate(b)))[0];
    const computed={prixFormation,montantCpf,montantPersonnel,montantAutre,totalFinancement,objectifFacturation,totalFacture,totalPaye,resteAFacturer:objectifFacturation-totalFacture,resteAPayer:objectifFacturation-totalPaye,differenceFinancement:totalFinancement-prixFormation,progressFacturation:pct(totalFacture,objectifFacturation),progressPaiement:pct(totalPaye,objectifFacturation),cashPaymentEnabled:Boolean(cashPaymentEnabled?.checked),cashPlanned:parseMoneyValue(cashPaymentAmount?.value),cashPaid,cashPaymentCount,installments,effectiveInstallments,montantTotalEcheancier:effectiveInstallments.reduce((total,item)=>total+Number(item.amount||0),0),totalMensualites:effectiveInstallments.length,mensualitesPayees,mensualitesRestantes:Math.max(effectiveInstallments.length-mensualitesPayees,0),montantPreleve:effectiveInstallments.filter(i=>paidStatuses.has(String(i.status||'').toLowerCase())).reduce((a,i)=>a+Number(i.amount||0),0),montantRestantAPrelever:effectiveInstallments.filter(i=>!paidStatuses.has(String(i.status||'').toLowerCase())).reduce((a,i)=>a+Number(i.amount||0),0),prochaineEcheance:upcoming,nombreRejets,nombreRejetsTraites,qontoPaymentEntries:[]};
    if(currentFinancialSummary){
      computed.objectifFacturation=Number(currentFinancialSummary.planned_total_cents||0)/100||computed.objectifFacturation;
      computed.totalFacture=Number(currentFinancialSummary.invoiced_total_cents||0)/100;
      computed.totalPaye=Number(currentFinancialSummary.paid_total_cents||0)/100;
      computed.resteAFacturer=computed.objectifFacturation-computed.totalFacture;
      computed.resteAPayer=Number(currentFinancialSummary.remaining_total_cents||0)/100;
      computed.progressFacturation=Number(currentFinancialSummary.invoicing_percentage||0);
      computed.progressPaiement=Number(currentFinancialSummary.payment_percentage||0);
      computed.qontoPaymentEntries=currentFinancialSummary.qonto_payment_entries||[];
    }
    const fundingMetrics=(key,fallbackPlanned)=>{
      const bucket=currentFinancialSummary?.by_financer?.[key];
      const relatedLines=invoiced.filter(line=>{
        const type=[line.financingType,line.financingLabel,line.financeurName].filter(Boolean).join(' ').toUpperCase();
        return key==='PERSONNEL'?type.includes('PERSONNEL'):(type.includes('AUTRE')||type.includes('OTHER'));
      });
      const planned=bucket?Number(bucket.planned_amount_cents||0)/100:fallbackPlanned;
      const invoicedAmount=bucket?Number(bucket.invoiced_amount_cents||0)/100:relatedLines.reduce((total,line)=>total+lineAmount(line),0);
      return {planned,invoiced:invoicedAmount,remainingToInvoice:Math.max(planned-invoicedAmount,0)};
    };
    const personalFunding=fundingMetrics('PERSONNEL',montantPersonnel);
    const otherFunding=fundingMetrics('AUTRE',montantAutre);
    computed.personalFundingPlanned=personalFunding.planned;
    computed.personalFundingInvoiced=personalFunding.invoiced;
    computed.personalFundingRemainingToInvoice=personalFunding.remainingToInvoice;
    computed.otherFundingPlanned=otherFunding.planned;
    computed.otherFundingInvoiced=otherFunding.invoiced;
    computed.otherFundingRemainingToInvoice=otherFunding.remainingToInvoice;
    return computed;
  }
  function cashCoversEntirePersonalFunding(c){const personalFunding=Number(c?.personalFundingPlanned||0),cashPlanned=Number(c?.cashPlanned||0);return Boolean(c?.cashPaymentEnabled)&&personalFunding>0&&cashPlanned+0.01>=personalFunding;}
  function renderSummary(c){
    updateAccordionSummaries(currentLines,c);
    const personalFundingFact=statusFromRatio(c.personalFundingInvoiced,c.personalFundingPlanned,{none:'Non facturé',zero:'Non facturé',partial:'Partiellement facturé',done:'Facturé',over:'Surfacturé'});
    const otherFundingFact=statusFromRatio(c.otherFundingInvoiced,c.otherFundingPlanned,{none:'Non facturé',zero:'Non facturé',partial:'Partiellement facturé',done:'Facturé',over:'Surfacturé'});
    const pay=statusFromRatio(c.totalPaye,c.objectifFacturation,{none:'Non payé',zero:'Non payé',partial:'Paiement partiel',done:'Payé',over:'Trop-perçu'});
    const mandate=mandateState(currentLines);
    const qontoSchedule=qontoScheduleState(currentLines);
    const inst=c.totalMensualites===0&&!c.nombreRejets&&!c.nombreRejetsTraites?['Aucun échéancier','gray']:(c.nombreRejets?['Rejet à traiter','red']:(c.totalMensualites>0&&c.mensualitesPayees===c.totalMensualites?['Terminé','green']:(c.nombreRejetsTraites?['Rejet traité','blue']:(mandate.hasSigned||c.prochaineEcheance?['Prélèvements programmés','green']:(c.mensualitesPayees?['En cours','orange']:['Mandat en attente','orange'])))));
    const adjusted=(parseFloat(String(salesTrackingAmount?.value||'').replace(',','.'))||0)>0;
    const cpfTone=cpfValidated?'green':'orange';
    const cpfValue=cpfValidated?c.montantCpf:0;
    const hasCpfAmount=c.montantCpf>0;
    const hasPersonalFundingAmount=c.personalFundingPlanned>0;
    const hasOtherFundingAmount=c.otherFundingPlanned>0;
    const cpfLine=currentLines.find(line=>isCpfQontoLine(line)&&!!(line.qontoInvoiceId||line.qontoDraftId));
    const cpfBucket=currentFinancialSummary?.by_financer?.CPF;
    const cpfInvoice=canonicalInvoiceEntry(cpfLine);
    const cpfInvoiceId=String(cpfLine?.qontoInvoiceId||cpfLine?.qontoDraftId||'');
    const cpfWedofInvoiceNumber=String(currentCpfWedofInvoice?.invoice_number||'');
    const cpfWedofBillingState=String(currentCpfWedofInvoice?.billing_state||'').toLowerCase();
    const cpfWedofUrl=String(currentCpfWedofInvoice?.wedof_url||'');
    const cpfInvoiceNumber=String(cpfInvoice?.invoice_number||cpfLine?.qontoInvoiceNumber||cpfWedofInvoiceNumber||cpfInvoiceId);
    const cpfInvoiceTotal=cpfBucket?.qonto_tracked?Number(cpfBucket.invoiced_amount_cents||0)/100:(cpfLine?lineAmount(cpfLine):c.montantCpf);
    const cpfInvoicePaid=cpfBucket?.qonto_tracked?Number(cpfBucket.paid_amount_cents||0)/100:(cpfLine?linePaid(cpfLine):0);
    const cpfPaymentStatus=String(cpfBucket?.payment_status||cpfInvoice?.payment_status||cpfLine?.paymentStatus||'unpaid').toLowerCase();
    const cpfInvoiceStatus=String(cpfLine?.invoiceStatus||cpfInvoice?.status||'').toLowerCase();
    const cpfInvoiceState=cpfInvoiceId?(cpfPaymentStatus==='paid'?['Facture payée','green']:(['partially_paid','partial'].includes(cpfPaymentStatus)?['Paiement partiel','orange']:(cpfInvoiceStatus==='draft'?['Brouillon Qonto','blue']:(['canceled','cancelled'].includes(cpfInvoiceStatus)?['Facture annulée','red']:(cpfInvoiceStatus==='control'?['À contrôler','red']:['En attente de paiement','orange']))))):(cpfWedofBillingState==='paid'?['Payée dans WEDOF','green']:['Facturée dans WEDOF','green']);
    const cpfInvoicePaidAt=String(cpfInvoice?.paid_at||cpfLine?.paidAt||'');
    const hasCpfInvoice=Boolean(cpfInvoiceId||cpfWedofInvoiceNumber||['billed','paid'].includes(cpfWedofBillingState));
    const cpfInvoiceAmountHtml=cpfInvoiceId?`${fmtMoney(cpfInvoicePaid)} encaissé sur ${fmtMoney(cpfInvoiceTotal)}${cpfPaymentStatus==='paid'&&cpfInvoicePaidAt?` · Payée le ${formatIsoDateFr(cpfInvoicePaidAt.slice(0,10))}`:''}`:`Montant facturé : ${fmtMoney(cpfInvoiceTotal)}${cpfWedofBillingState==='paid'?' · Paiement confirmé par WEDOF':' · Paiement géré hors plateforme'}`;
    const cpfInvoiceLink=cpfInvoiceId?`<a class="finance-summary-card__cpf-invoice-link" href="/admin/qonto/invoices/${encodeURIComponent(cpfInvoiceId)}/pdf" target="_blank" rel="noopener"><span aria-hidden="true">👁</span> Visualiser la facture</a>`:(cpfWedofUrl?`<a class="finance-summary-card__cpf-invoice-link" href="${esc(cpfWedofUrl)}" target="_blank" rel="noopener"><span aria-hidden="true">↗</span> Ouvrir dans WEDOF</a>`:'');
    const cpfInvoiceHtml=hasCpfInvoice?`<div class="finance-summary-card__cpf-invoice"><div class="finance-summary-card__cpf-invoice-head"><strong>Facture CPF</strong>${badge(cpfInvoiceState[0],cpfInvoiceState[1])}</div><div class="finance-summary-card__cpf-invoice-number">${esc(cpfInvoiceNumber||'Référence non communiquée')}</div><div class="finance-summary-card__cpf-invoice-amount">${cpfInvoiceAmountHtml}</div>${cpfInvoiceLink}</div>`:'';
    const cashStatus=statusFromRatio(c.cashPaid,c.cashPlanned,{none:'Montant à préciser',zero:'À encaisser',partial:'Espèces partielles',done:'Espèces réglées',over:'Trop-perçu espèces'});
    const showDirectDebitKpi=!cashCoversEntirePersonalFunding(c);
    const personalFundingLines=currentLines.filter(line=>[line.financingType,line.financingLabel,line.financeurName].filter(Boolean).join(' ').toUpperCase().includes('PERSONNEL'));
    const otherFundingLines=currentLines.filter(line=>{const type=[line.financingType,line.financingLabel,line.financeurName].filter(Boolean).join(' ').toUpperCase();return type.includes('AUTRE')||type.includes('OTHER');});
    const fundingCards=[
      {label:'Prix formation',icon:'€',value:fmtMoney(c.prixFormation),badge:adjusted?badge('Tarif ajusté','blue'):badge('Tarif standard','gray'),tone:adjusted?'blue':'gray',meta:'Montant de référence'},
      ...(hasCpfAmount?[{label:'CPF',icon:'<img class="finance-summary-card__cpf-logo" src="/templates/cpf.jpg" alt="Logo CPF">',value:`${fmtMoney(cpfValue)} / ${fmtMoney(c.montantCpf)}`,badge:badge(cpfValidated?'CPF validé':'CPF non validé',cpfTone),tone:cpfTone,meta:cpfValidated?'Montant CPF confirmé':'Cliquez quand le CPF est confirmé',cpf:true,cpfInvoiceHtml}]:[]),
      ...(hasPersonalFundingAmount?[{label:'Financement personnel',icon:'👤',value:`${fmtMoney(c.personalFundingInvoiced)} / ${fmtMoney(c.personalFundingPlanned)}`,badge:badge(personalFundingFact[0],personalFundingFact[1])+invoiceOriginBadges(personalFundingLines),tone:(c.personalFundingPlanned>0&&c.personalFundingInvoiced<c.personalFundingPlanned)?'orange':personalFundingFact[1],meta:`Reste à facturer : ${fmtMoney(c.personalFundingRemainingToInvoice)}`}]:[]),
      ...(hasOtherFundingAmount?[{label:'Autres financements',icon:'🏢',value:`${fmtMoney(c.otherFundingInvoiced)} / ${fmtMoney(c.otherFundingPlanned)}`,badge:badge(otherFundingFact[0],otherFundingFact[1])+invoiceOriginBadges(otherFundingLines),tone:(c.otherFundingPlanned>0&&c.otherFundingInvoiced<c.otherFundingPlanned)?'orange':otherFundingFact[1],meta:`Reste à facturer : ${fmtMoney(c.otherFundingRemainingToInvoice)}`}]:[])
    ];
    const paymentCards=[
      ...(c.cashPaymentEnabled?[{label:'Espèces',icon:'💶',value:`${fmtMoney(c.cashPaid)} / ${fmtMoney(c.cashPlanned)}`,badge:badge(`${fmtMoney(c.cashPaid)} réglés en espèces`,cashStatus[1]),tone:cashStatus[1],meta:`${c.cashPaymentCount} versement${c.cashPaymentCount===1?'':'s'} enregistré${c.cashPaymentCount===1?'':'s'} · Reste en espèces : ${fmtMoney(Math.max(c.cashPlanned-c.cashPaid,0))}`}]:[]),
      ...(showDirectDebitKpi?[{label:'Prélèvements',icon:'↻',value:`${c.mensualitesPayees}/${c.totalMensualites}`,badge:[badge(inst[0],inst[1]),mandate.hasSigned?badge('✅ Mandat OK','green'):(mandate.hasSent?badge('⚠ Mandat de prélèvement en cours de validation','orange'):''),bankSnapshot?.upcoming?.length?badge(`${bankSnapshot.upcoming.length} programmation(s) Qonto`,'blue'):(qontoSchedule.needsQontoScheduling?badge('⚠ Échéancier à programmer dans Qonto','orange'):'')].filter(Boolean).join(''),tone:qontoSchedule.needsQontoScheduling?'orange':inst[1],meta:qontoSchedule.needsQontoScheduling?'Le mandat est validé, mais les échéances ne sont pas encore créées dans Qonto. Cliquez sur Programmer les échéances.':(c.prochaineEcheance?`Consulter l’échéancier actualisé`:'Aucune prochaine échéance au plan'),mandateAction:!mandate.hasSent,scheduleAction:qontoSchedule.needsQontoScheduling,rescheduleAction:c.nombreRejets>0}]:[]),
      {label:'Payé',icon:(pay[1]==='green'?'✓':'✕'),iconTone:pay[1]==='green'?'green':'red',value:`${fmtMoney(c.totalPaye)} / ${fmtMoney(c.objectifFacturation)}`,badge:badge(pay[0],pay[1]),tone:(c.objectifFacturation>0&&c.totalPaye<c.objectifFacturation)?'orange':pay[1],meta:`Reste à payer : ${fmtMoney(Math.max(c.resteAPayer,0))}`}
    ];
    const renderCard=card=>`<div class="finance-summary-card ${card.cpf?'finance-summary-card--cpf ':''}is-${card.tone}"><div class="finance-summary-card__top"><span>${card.label}</span><span class="finance-summary-card__icon ${card.iconTone?`finance-summary-card__icon--${card.iconTone}`:''}">${card.icon}</span></div><div class="finance-summary-card__value">${card.value}</div>${card.cpf?`<div class="finance-summary-card__cpf-meter"><span style="width:${cpfValidated?100:0}%"></span></div>`:''}<div class="finance-summary-card__cpf-actions"><span>${card.badge}</span>${card.cpf&&!readOnly?`<button class="finance-summary-card__cpf-btn ${cpfValidated?'finance-summary-card__cpf-btn--undo':''}" type="button" data-cpf-toggle="${cpfValidated?'0':'1'}" title="${cpfValidated?'Annuler validation CPF':'Valider le CPF'}" aria-label="${cpfValidated?'Annuler validation CPF':'Valider le CPF'}">${cpfValidated?'✕':'✅'}</button>`:''}</div><div class="finance-summary-card__meta">${card.meta}</div>${card.cpf?cpfFranceTravailHtml:''}${card.cpfInvoiceHtml||''}${card.rescheduleAction&&!readOnly?'<button type="button" class="qonto-action-btn qonto-action-btn--primary" data-reschedule-rejected-debit style="margin-top:8px;width:100%;justify-content:center">Reprogrammer un prélèvement</button>':''}${card.mandateAction&&!readOnly?'<button type="button" class="qonto-action-btn qonto-action-btn--primary" data-create-mandate style="margin-top:8px;width:100%;justify-content:center">Créer un mandat de prélèvement</button>':''}${card.scheduleAction&&!readOnly?'<button type="button" class="qonto-action-btn qonto-action-btn--primary" data-schedule-qonto style="margin-top:8px;width:100%;justify-content:center">Programmer les échéances</button>':''}</div>`;
    document.getElementById('financeSummaryCards').innerHTML=`<section class="finance-kpi-group finance-kpi-group--funding" aria-labelledby="financeFundingKpisTitle"><div class="finance-kpi-group__head"><div><span class="finance-kpi-group__eyebrow">Origine des fonds</span><h3 id="financeFundingKpisTitle">Financement</h3></div><span class="finance-kpi-group__count">${fundingCards.length} indicateur${fundingCards.length===1?'':'s'}</span></div><div class="finance-summary-grid" style="--finance-kpi-count:${fundingCards.length}">${fundingCards.map(renderCard).join('')}</div></section><section class="finance-kpi-group finance-kpi-group--payment" aria-labelledby="financePaymentKpisTitle"><div class="finance-kpi-group__head"><div><span class="finance-kpi-group__eyebrow">Encaissements</span><h3 id="financePaymentKpisTitle">Paiement</h3></div><span class="finance-kpi-group__count">${paymentCards.length} indicateur${paymentCards.length===1?'':'s'}</span></div><div class="finance-summary-grid" style="--finance-kpi-count:${paymentCards.length}">${paymentCards.map(renderCard).join('')}</div></section>`;
    document.querySelector('[data-reschedule-rejected-debit]')?.addEventListener('click',openRescheduleRejectedDebitModal);
    document.querySelector('[data-create-mandate]')?.addEventListener('click',()=>{const line=currentLines.find(l=>String(l.financingType||l.financingLabel||'').toLowerCase().includes('personnel'))||currentLines.find(l=>!isCpfQontoLine(l));if(line)openCreateMandateModal(line);else alert('Aucune ligne de financement compatible.');});
    document.querySelector('[data-schedule-qonto]')?.addEventListener('click',()=>syncBtn?.click());
    document.querySelector('[data-cpf-toggle]')?.addEventListener('click', async (event)=>{const btn=event.currentTarget;const next=btn.dataset.cpfToggle==='1';btn.disabled=true;btn.textContent=next?'…':'…';try{await updateTrainee({cpf_validated:next});cpfValidated=next;renderSummary(computeFinance(currentLines));}catch(e){btn.disabled=false;btn.textContent=next?'✅':'✕';alert(next?'Erreur sauvegarde CPF validé':'Erreur annulation CPF validé');}});
    const validatedCpfAmount=cpfValidated?c.montantCpf:0;
    const fundingTotal=c.totalFacture+validatedCpfAmount;
    const fundingDiff=fundingTotal-c.prixFormation;
    const fundingTone=c.prixFormation<=0?'orange':(Math.abs(fundingDiff)<=0.01?'green':(fundingDiff<0?'orange':'red'));
    const fundingTitle=fundingTone==='green'?'Financement OK':(fundingDiff<0?'Attention, financement incomplet':'Trop financé');
    const fundingIcon=fundingTone==='green'?'✅':(fundingDiff<0?'⚠️':'⚠️');
    const nonCpfFundingDetails=[c.personalFundingPlanned>0?`Financement personnel ${fmtMoney(c.personalFundingInvoiced)}`:'',c.otherFundingPlanned>0?`Autres financements ${fmtMoney(c.otherFundingInvoiced)}`:''].filter(Boolean).join(' + ')||`Financements hors CPF ${fmtMoney(c.totalFacture)}`;
    document.getElementById('financeAlerts').style.display='block';
    document.getElementById('financeAlerts').innerHTML=`<div class="finance-funding-check finance-funding-check--${fundingTone}"><div class="finance-funding-check__icon">${fundingIcon}</div><div><div class="finance-funding-check__title">${fundingTitle}</div><div class="finance-funding-check__detail">${nonCpfFundingDetails} + CPF ${cpfValidated?'validé':'non validé'} ${fmtMoney(validatedCpfAmount)} = ${fmtMoney(fundingTotal)} / prix formation ${fmtMoney(c.prixFormation)}${Math.abs(fundingDiff)>0.01?` · Écart : ${fmtMoney(Math.abs(fundingDiff))}`:''}</div></div></div>`;
    document.getElementById('financeProgressPanel').innerHTML=`<div class="finance-progress-row"><strong>Facturation</strong><div class="finance-progress-track"><div class="finance-progress-fill" style="width:${Math.min(c.progressFacturation,100)}%"></div></div><strong>${Math.round(c.progressFacturation)}%</strong></div><div class="finance-progress-row"><strong>Paiement</strong><div class="finance-progress-track"><div class="finance-progress-fill ${c.progressPaiement>=100?'finance-progress-fill--green':'finance-progress-fill--orange'}" style="width:${Math.min(c.progressPaiement,100)}%"></div></div><strong>${Math.round(c.progressPaiement)}%</strong></div>`;
  }
  function setAccordionHint(id,text,tone='blue'){const el=document.getElementById(id);if(!el)return;el.textContent=text;el.className=`finance-accordion-hint finance-badge--${tone}`;}
  function updateAccordionSummaries(lines,c){const invoiceCount=lines.filter(lineHasGeneratedInvoice).length;setAccordionHint('financeSettingsSummary',`CPF ${fmtMoney(c.montantCpf)} · Personnel ${fmtMoney(c.montantPersonnel)}`,'blue');setAccordionHint('financeInvoicesSummary',`${invoiceCount}/${lines.length} factures générées`,invoiceCount===lines.length&&lines.length?'green':(invoiceCount?'orange':'red'));setAccordionHint('financePaymentsSummary',`${fmtMoney(c.totalPaye)} encaissé · reste ${fmtMoney(Math.max(c.resteAPayer,0))}`,c.resteAPayer<=0.01&&c.objectifFacturation>0?'green':(c.totalPaye>0?'orange':'red'));const installmentHint=c.totalMensualites?`${c.mensualitesPayees} mensualités payées sur ${c.totalMensualites}${c.nombreRejets?' · rejet à traiter':(c.nombreRejetsTraites?' · rejet traité':'')}`:'Aucun échéancier';setAccordionHint('financeInstallmentsSummary',installmentHint,c.nombreRejets?'red':(c.totalMensualites&&c.mensualitesPayees===c.totalMensualites?'green':(c.nombreRejetsTraites?'blue':(c.totalMensualites?'orange':'gray'))));}
  function renderBreakdown(lines,c){
    const defs=[['CPF',c.montantCpf,'finance-line--cpf'],['Personnel',c.montantPersonnel,'finance-line--personal'],['Autre financement',c.montantAutre,'finance-line--other']];
    document.getElementById('financeBreakdown').innerHTML=defs.map(([name,planned,typeClass])=>{
      const related=lines.filter(l=>(l.financeurName||l.financingLabel||l.financingType||'').toLowerCase().includes(name.split(' ')[0].toLowerCase())||(name==='Personnel'&&String(l.financingType).includes('PERSONNEL'))||(name==='CPF'&&isCpfQontoLine(l))||(name.startsWith('Autre')&&String(l.financingType).includes('AUTRE')));
      const bucket=currentFinancialSummary?.by_financer?.[name==='CPF'?'CPF':(name==='Personnel'?'PERSONNEL':'AUTRE')];
      const inv=bucket?Number(bucket.invoiced_amount_cents||0)/100:related.filter(lineHasGeneratedInvoice).reduce((a,l)=>a+lineAmount(l),0);
      const paid=bucket?Number(bucket.paid_amount_cents||0)/100:related.reduce((a,l)=>a+linePaid(l),0);
      const external=Boolean(bucket?.externally_managed);
      const qontoTracked=external&&Boolean(bucket?.qonto_tracked);
      const wedofBilled=name==='CPF'&&['billed','paid'].includes(String(currentCpfWedofInvoice?.billing_state||'').toLowerCase());
      const remaining=qontoTracked&&bucket?.remaining_amount_cents!=null?Number(bucket.remaining_amount_cents)/100:Math.max(planned-paid,0);
      const paymentStatus=String(bucket?.payment_status||'').toLowerCase();
      const trackedState=paymentStatus==='paid'?['Facture payée','green']:(['partially_paid','partial'].includes(paymentStatus)?['Paiement partiel','orange']:(paymentStatus==='draft'?['Brouillon Qonto','blue']:(['canceled','cancelled'].includes(paymentStatus)?['Facture annulée','red']:(paymentStatus==='control'?['À contrôler','red']:['En attente de paiement','orange']))));
      const st=qontoTracked?trackedState:(external?[wedofBilled?'Facturée dans WEDOF':'Géré hors plateforme','green']:statusFromRatio(paid,planned,{none:'Non prévu',zero:'Non payé',partial:'Paiement partiel',done:'Payé',over:'Trop-perçu'}));
      return `<div class="finance-line ${typeClass}"><strong>${esc(name)}${name==='CPF'&&cpfFranceTravail?.status==='validated'?`<small class="finance-line__cpf-funding">Dont France Travail : ${esc(cpfFranceTravail.amount_label)}</small>`:''}</strong><div><span class="finance-mini-label">Prévu</span>${fmtMoney(planned)}</div><div><span class="finance-mini-label">Facturé</span>${fmtMoney(inv)}</div>${external&&!qontoTracked?'<div><span class="finance-mini-label">Paiement</span>Géré hors plateforme</div><div><span class="finance-mini-label">À encaisser ici</span>0,00 €</div>':`<div><span class="finance-mini-label">Payé</span>${fmtMoney(paid)}</div><div><span class="finance-mini-label">Reste à payer</span>${fmtMoney(Math.max(remaining,0))}</div>`}${badge(st[0],st[1])}</div>`;
    }).join('');
  }
  function firstInvoiceToGenerate(){return currentLines.find(line=>!isCpfQontoLine(line)&&!lineHasGeneratedInvoice(line));}
  function updateQuickInvoiceAction(){
    if(!quickGenerateBtn) return;
    const line=firstInvoiceToGenerate();
    const remainingToInvoice=Number(computeFinance(currentLines).resteAFacturer||0);
    const hasUnrepresentedInvoice=remainingToInvoice>0.01;
    quickGenerateBtn.disabled=readOnly||!line;
    if(line){
      quickGenerateBtn.textContent=`🧾 Générer une facture ${line.financeurName||line.financingLabel||line.financingType||''}`.trim();
      quickGenerateBtn.title='Ouvrir directement la génération de la prochaine facture manquante';
    }else if(hasUnrepresentedInvoice){
      // Never claim that every invoice has been generated when the financial
      // total still has an amount to invoice. This can happen temporarily if
      // the financing line has not yet been returned by the billing API.
      quickGenerateBtn.textContent='⚠ Facture à générer : actualiser les financements';
      quickGenerateBtn.title='Un montant reste à facturer, mais aucune ligne de facturation correspondante n’est disponible. Actualisez les financements puis rechargez la page.';
    }else{
      quickGenerateBtn.textContent='✅ Toutes les factures sont générées';
      quickGenerateBtn.title='Aucune facture à générer';
    }
  }
  function renderAlerts(lines,c){const alerts=[];lines.filter(l=>l.qontoBankTransferSyncWarning).forEach(l=>alerts.push([esc(l.qontoBankTransferSyncWarning),'orange','⚠️']));lines.filter(l=>l.qontoDirectDebitSyncWarning).forEach(l=>alerts.push([esc(l.qontoDirectDebitSyncWarning),'red','⚠️']));if(c.nombreRejets)alerts.push(['Un prélèvement a été rejeté. Action requise.','red','⚠️']);if(c.resteAFacturer>0.01)alerts.push([`Reste ${fmtMoney(c.resteAFacturer)} à facturer.`,'orange','💳']);lines.filter(l=>!isCpfQontoLine(l)&&!lineHasGeneratedInvoice(l)).forEach(l=>alerts.push([`Facture à générer pour ${esc(l.financeurName||l.financingLabel||l.financingType)}.`,'orange','🧾']));if(Math.abs(c.differenceFinancement)>=0.01)alerts.push([`Total financé ${c.differenceFinancement<0?'inférieur':'supérieur'} au prix formation de ${fmtMoney(Math.abs(c.differenceFinancement))}.`,'orange','ℹ️']);if(c.resteAPayer<-0.01)alerts.push([`Trop-perçu : ${fmtMoney(Math.abs(c.resteAPayer))}.`,'red','⚠️']);const box=document.getElementById('financeAlerts');if(financeNotificationsCount) financeNotificationsCount.textContent=String(alerts.length);financeNotificationsBtn?.classList.toggle('has-alerts', alerts.length>0);financeNotificationsBtn?.toggleAttribute('disabled', alerts.length===0);financeNotificationsBtn?.setAttribute('aria-expanded', financeNotificationsOpen&&alerts.length?'true':'false');box.style.display=alerts.length&&financeNotificationsOpen?'':'none';box.innerHTML=alerts.length?`<div class="finance-notifications__head"><div class="finance-notifications__title"><span aria-hidden="true">🔔</span><span>Notifications</span></div><span class="finance-notifications__count">${alerts.length}</span></div><div class="finance-notifications__list">${alerts.map(a=>`<div class="finance-alert finance-alert--${a[1]}"><strong>${a[2]}</strong><span>${a[0]}</span></div>`).join('')}</div>`:'';}
  function financePaymentRows(lines,c){
    const rows=[];
    const representedTransfers=new Set();
    (c.qontoPaymentEntries||[]).forEach(entry=>{
      if(Array.isArray(entry.transactions)&&entry.transactions.length){
        let representedAmount=0;
        entry.transactions.forEach(transfer=>{
          if(String(transfer.status||'').toLowerCase()!=='completed'||Number(transfer.amount_cents||0)<=0||representedTransfers.has(String(transfer.id)))return;
          representedTransfers.add(String(transfer.id));
          representedAmount+=Number(transfer.amount_cents);
          rows.push({date:transfer.paid_at||entry.paid_at||'',dateLabel:'Reçu le',amount:Number(transfer.amount_cents)/100,mode:'Virement bancaire',status:'Encaissé',invoice:entry.invoice_number||'',remaining:null,note:[transfer.payer_name||transfer.label,transfer.reference||entry.reference].filter(Boolean).join(' · ')});
        });
        if(Number(entry.paid_amount_cents)>representedAmount)rows.push({date:entry.last_synced_at||'',dateLabel:'Dernière synchronisation',amount:(Number(entry.paid_amount_cents)-representedAmount)/100,mode:'Qonto',status:paymentStatusLabel(entry.payment_status),invoice:entry.invoice_number||entry.invoice_id,remaining:Number(entry.remaining_amount_cents||0)/100,note:'Autres encaissements remontés par Qonto'});
      }else if(Number(entry.paid_amount_cents||0)>0){
        rows.push({date:entry.last_synced_at||'',dateLabel:'Dernière synchronisation',amount:Number(entry.paid_amount_cents)/100,mode:'Qonto',status:paymentStatusLabel(entry.payment_status),invoice:entry.invoice_number||entry.invoice_id,remaining:Number(entry.remaining_amount_cents||0)/100,note:'Montant encaissé remonté par Qonto'});
      }
    });
    lines.forEach(line=>{
      if(line.qontoInvoiceId||line.qontoDraftId||linePaid(line)<=0)return;
      if(Array.isArray(line.qontoBankTransfers)&&line.qontoBankTransfers.length){
        line.qontoBankTransfers.forEach(transfer=>{
          if(String(transfer.status||'').toLowerCase()!=='completed'||Number(transfer.amount_cents||0)<=0||representedTransfers.has(String(transfer.id)))return;
          representedTransfers.add(String(transfer.id));
          rows.push({date:transfer.paid_at||'',dateLabel:'Reçu le',amount:Number(transfer.amount_cents)/100,mode:'Virement bancaire',status:'Encaissé',invoice:'',remaining:null,note:transfer.reference||transfer.label||''});
        });
      }else{
        rows.push({date:line.paidAt||line.updatedAt||'',dateLabel:'Date du paiement',amount:linePaid(line),mode:line.paymentMode==='sepa_direct_debit'?'Prélèvement':'Virement',status:'Encaissé',invoice:'',remaining:null});
      }
    });
    return rows;
  }
  function renderPayments(lines,c){
    const rows=financePaymentRows(lines,c);
    const cashItems=window.getFinanceCashInstallments?window.getFinanceCashInstallments():[];
    const cashTotal=window.getFinanceCashInstallmentsTotal?window.getFinanceCashInstallmentsTotal():0;
    if(cashPaymentEnabled?.checked&&cashTotal>0)cashItems.forEach(item=>rows.push({date:item.date,dateLabel:'Reçu le',amount:item.amount,mode:'Espèces',status:'Encaissé',invoice:'',remaining:null}));
    document.getElementById('financePayments').innerHTML=`<div class="finance-line ${c.resteAPayer<=0.01&&c.objectifFacturation>0?'finance-line--paid':'finance-line--unpaid'}"><strong>Total encaissé</strong><div>${fmtMoney(c.totalPaye)}</div><div><span class="finance-mini-label">Reste à payer</span>${fmtMoney(Math.max(c.resteAPayer,0))}</div><div><span class="finance-mini-label">Taux de paiement</span>${Math.round(c.progressPaiement)}%</div></div>`+(Number(c.totalPaye||0)>0?rows.map(row=>`<div class="finance-line"><strong>${esc(row.mode)}</strong><div><span class="finance-mini-label">Facture</span>${esc(row.invoice||'—')}</div><div><span class="finance-mini-label">Montant encaissé</span>${fmtMoney(row.amount)}</div><div><span class="finance-mini-label">Reste sur la facture</span>${row.remaining==null?'—':fmtMoney(Math.max(row.remaining,0))}</div><div>${badge(row.status,row.status==='Partiellement payé'?'orange':'green')}</div><div><span class="finance-mini-label">${esc(row.dateLabel)}</span>${formatIsoDateFr(String(row.date).slice(0,10))||'—'}${row.note?` · ${esc(row.note)}`:''}</div></div>`).join(''):'<div class="finance-empty">Aucun paiement enregistré pour le moment.</div>');
  }
  function installmentEditSnapshot(line){
    return installmentScheduleContext(line).items.map((item,index)=>[
      installmentDate(item),Math.round(Number(item.amount||0)*100),String(item.status||''),
      String(item.qonto_direct_debit_subscription_id||''),String(item.qonto_direct_debit_collection_id||''),
      installmentSchedulePosition(item,index+1),Boolean(item.excluded_from_schedule_totals),
      installmentRejectionTreated(item),String(item.tracking_removed_at||'')
    ]);
  }
  function installmentEditFeedback(message,error=false){
    const feedback=document.getElementById('installmentEditFeedback');
    if(!feedback)return;
    feedback.className=`qonto-feedback qonto-feedback--${error?'error':'success'}`;
    feedback.textContent=message;
    feedback.hidden=false;
  }
  function lockInstallmentDraft(container){
    installmentDraftContainer=container;
    document.getElementById('financeInstallments').querySelectorAll('button,input,select').forEach(control=>{
      control.disabled=Boolean(container&&!container.contains(control));
    });
  }
  async function saveInstallmentEdit(line,action,details={}){
    if(readOnly||installmentEditBusy)return;
    installmentEditBusy=true;
    const container=document.getElementById('financeInstallments');
    container.querySelectorAll('button,input,select').forEach(control=>control.disabled=true);
    installmentEditFeedback('Enregistrement du suivi…');
    let result;
    try{
      result=await billingApi('/api/billing/installments',{
        scope:'tracking',action,lineId:line.id,sessionId,traineeId,
        expectedSchedule:installmentEditSnapshot(line),...details
      });
    }catch(error){
      lockInstallmentDraft(installmentDraftContainer);
      installmentEditFeedback(error.message||'Enregistrement impossible.',true);
      installmentEditBusy=false;
      return;
    }
    installmentDraftActive=false;
    installmentDraftContainer=null;
    installmentEditBusy=false;
    try{await load();installmentEditFeedback(result.message);}
    catch(error){
      // The save already succeeded: prevent a second addition if the refresh
      // fails, and explain how to recover without submitting it again.
      installmentEditFeedback('Modification enregistrée. Rechargez la page pour afficher le nouvel échéancier.',true);
    }
  }
  const scheduleSection = document.getElementById('financeScheduleSection');
  let scheduleView = 'plan';
  let editingSchedule = false;
  let reviewBusy = false;
  let bankSnapshot = null;
  let bankLoading = false;
  let bankError = '';
  let bankChecked = 0;
  const bankStates = {
    scheduled:['Programmé','blue'], in_progress:['En cours','blue'],
    pending_mandate_signature:['Mandat à signer','orange'], on_hold:['En attente','orange'],
    completed:['Encaissé','green'], paid:['Encaissé','green'], succeeded:['Encaissé','green'],
    failed:['Rejeté','red'], declined:['Rejeté','red'], rejected:['Rejeté','red'],
    returned:['Retourné','red'], refunded:['Remboursé','red'],
    canceled:['Annulé','gray'], cancelled:['Annulé','gray']
  };
  const frequencies = {one_off:'Une fois', daily:'Quotidienne', weekly:'Hebdomadaire', monthly:'Mensuelle',
    quarterly:'Trimestrielle', yearly:'Annuelle', custom:'Personnalisée'};
  function hasBankSchedule() {
    return currentLines.some(line => !isCpfQontoLine(line) && (line.qonto_direct_debit_mandate_id ||
      line.qonto_direct_debit_subscription_id || line.directDebitInstallments?.some(it => it.qonto_direct_debit_collection_id || it.qonto_direct_debit_subscription_id)));
  }
  async function readBankSchedule(force=false) {
    if (!scheduleSection?.open || !hasBankSchedule() || bankLoading || (!force && Date.now()-bankChecked < 300000)) return;
    bankLoading = true;
    bankError = '';
    bankChecked = Date.now();
    renderInstallments(computeFinance(currentLines));
    try {
      const url = `/api/billing/trainee/${encodeURIComponent(traineeId)}/session/${encodeURIComponent(sessionId)}/bank-schedule`;
      const response = await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});
      const data = await parseJsonResponse(response,'Lecture Qonto impossible.');
      if (!response.ok || !data.ok) throw new Error(data.error || 'Lecture Qonto impossible.');
      bankSnapshot = data;
    } catch (error) {
      bankError = error.message;
    } finally {
      bankLoading = false;
      render(currentLines);
    }
  }
  scheduleSection?.addEventListener('toggle', () => { if (scheduleSection.open) readBankSchedule(); });

  function scheduleDate(date) {
    return esc(formatIsoDateFr(date) || 'Date inconnue');
  }
  function scheduleTable(headings, rows, empty) {
    if (!rows.length) return `<p class="schedule-empty">${esc(empty)}</p>`;
    return `<table class="schedule-table"><thead><tr>${headings.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }
  function sameDayNotices(upcoming) {
    const groups = new Map();
    for (const sub of upcoming) {
      if (!sub.date || !['scheduled','in_progress'].includes(sub.status)) continue;
      const day = groups.get(sub.date) || {count:0,cents:0};
      day.count++;
      day.cents+=sub.amount_cents;
      groups.set(sub.date,day);
    }
    return [...groups].filter(([,d])=>d.count>1).map(([date,d]) =>
      `<div class="schedule-notice"><span><strong>${scheduleDate(date)}</strong> · ${d.count} prélèvements programmés, soit <strong>${fmtMoney(d.cents/100)}</strong></span></div>`
    ).join('');
  }
  function operationTable(records,history) {
    const rows = records.map(row => {
      const subscriptionStarted=!history && row.status==='in_progress' && row.date;
      const [label,tone]=subscriptionStarted?bankStates.scheduled:(bankStates[row.status] || ['À vérifier','orange']);
      const detail = [
        history && row.date && row.transaction_date && row.date!==row.transaction_date && `<span>Date de présentation · ${scheduleDate(row.date)}</span>`,
        row.reference && `<span>Libellé · ${esc(row.reference)}</span>`,
        row.reason && `<span>Motif · ${esc(installmentFailureReasonLabel(row.reason)==='Motif bancaire non répertorié'?row.reason:installmentFailureReasonLabel(row.reason))}</span>`,
        row.reason_code && `<span>Code bancaire · ${esc(row.reason_code)}</span>`,
        `<span>Référence Qonto · ${esc(row.id)}</span>`
      ].filter(Boolean).join('');
      const amount = fmtMoney(row.amount_cents/100);
      return `<tr><td><details data-operation-id="${esc(row.id)}"><summary>${scheduleDate(row.transaction_date || row.date)}${history && !row.transaction_date?'<small>Date de présentation</small>':''}</summary><div class="schedule-operation">${detail}</div></details></td>
        ${history?'':`<td>${esc(frequencies[row.frequency] || 'Non renseignée')}</td>`}<td>${badge(label,tone)}</td><td>${tone==='red'||label==='Annulé'?`<del>${amount}</del>`:amount}</td></tr>`;
    });
    return scheduleTable(history?['Date','Statut','Montant présenté']:['Prochaine date','Fréquence','Statut','Montant'],rows,
      history?'Aucune opération bancaire rattachée à ce dossier.':'Aucun prélèvement à encaisser rattaché à ce dossier.');
  }
  function localHistory(items) {
    const rows=items.filter(it=>it.tracking_removed_at || installmentIsRejected(it) || ['paid','completed','succeeded','success','cancelled','canceled'].includes(it.status))
      .sort((a,b)=>installmentDate(b).localeCompare(installmentDate(a))).map(it=>
        `<tr><td>${scheduleDate(installmentDate(it))}</td><td>${esc(installmentStatusLabel(it))}</td><td>${fmtMoney(it.amount)}</td></tr>`);
    return scheduleTable(['Date du suivi','Situation enregistrée','Montant'],rows,'Aucun événement enregistré dans le suivi local.');
  }
  function initialTable(items, multipleLines=false) {
    const rows = [...items].sort((a,b)=>a.date.localeCompare(b.date)).map(item=>{
      const date=new Date(item.date+'T12:00:00Z');
      const month=Number.isFinite(date.getTime())?date.toLocaleString('fr-FR',{month:'long',timeZone:'UTC'}):'Échéance';
      return `<tr><td><strong class="schedule-month">${esc(month)}</strong>${multipleLines?`<small>${esc(item.line.financeurName || item.line.financingType)}</small>`:''}</td><td>${scheduleDate(item.date)}</td><td>${fmtMoney(item.amount)}</td></tr>`;
    });
    return scheduleTable(['Mensualité','Date initialement prévue','Montant prévu'],rows,'Aucun échéancier initial enregistré.');
}

  function reviewSelection(lines) {
    const result={};
    for(const line of lines) {
      const treated=new Set(line.debitRejectionReview?.treated || []);
      const keys=new Set([...(line.debitRejectionReview?.pending || []), ...(bankSnapshot?.rejectionKeys?.[line.id] || [])]);
      const pending=[...keys].filter(key=>!treated.has(key));
      if(pending.length) result[line.id]=pending;
    }
    return result;
}

  function scheduleReadView(c, canEdit) {
    const initial=currentLines.filter(line=>!isCpfQontoLine(line)).flatMap(line=>
      (line.initialDebitSchedule || []).map(row=>({...row,line})));
    const upcoming=bankSnapshot?.upcoming || [];
    const programmed=upcoming.filter(sub=>['scheduled','in_progress'].includes(sub.status));
    const totalCents=programmed.reduce((sum,sub)=>sum+sub.amount_cents,0);
    const dates=programmed.map(sub=>sub.date).filter(Boolean).sort();
    const tabs=[['plan','Échéancier initial'],['bank','Échéancier actualisé'],['history','Historique']].map(([key,title])=>`<button type="button" aria-pressed="${key===scheduleView}" data-schedule-view="${key}">${title}</button>`).join('');
    const stats=entries=>`<div class="schedule-totals">${entries.map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>`;
    const stamp=bankSnapshot?new Date(bankSnapshot.checked_at).toLocaleString('fr-FR',{timeZone:'Europe/Paris',dateStyle:'short',timeStyle:'short'}):'';
    const source=bankLoading?'Lecture de Qonto…':[bankError,stamp?`Lecture Qonto du ${stamp}`:''].filter(Boolean).join(' ');
    let content;
    if (scheduleView==='plan') {
      const amount=initial.reduce((sum,row)=>sum+Math.round(Number(row.amount)*100),0);
      content=stats([['Total initialement prévu',fmtMoney(amount/100)],['Échéances prévues',initial.length]])+
        initialTable(initial,new Set(initial.map(row=>row.line.id)).size>1);
    } else if (scheduleView==='bank') {
      content=stats([['Total des prélèvements programmés',bankSnapshot?fmtMoney(totalCents/100):'—'],
        ['Prélèvements programmés',bankSnapshot?programmed.length:'—'],['Prochaine date',dates.length?scheduleDate(dates[0]):'—']]);
      if (bankSnapshot) {
        content+=sameDayNotices(upcoming)+operationTable(upcoming,false);
        if (programmed.some(sub=>sub.frequency && sub.frequency!=='one_off')) content+='<p class="schedule-help">Pour un prélèvement récurrent, le total inclut la prochaine échéance affichée par Qonto.</p>';
      } else content+=`<p class="schedule-empty">${bankLoading?'Chargement des programmations Qonto…':hasBankSchedule()?'Les programmations Qonto ne sont pas disponibles.':'Aucune programmation Qonto rattachée à cette fiche.'}</p>`;
    } else if (bankSnapshot) {
      content=operationTable(bankSnapshot.history,true);
      const remoteIds=new Set(bankSnapshot.history.map(row=>row.id));
      const local=c.installments.filter(it=>it.tracking_removed_at ||
        (!remoteIds.has(it.qonto_direct_debit_collection_id) && (installmentIsRejected(it) || ['completed','paid','succeeded','success','canceled','cancelled'].includes(it.status))));
      if (local.length) content+=`<details class="schedule-local"><summary>Historique du suivi local</summary>${localHistory(local)}</details>`;
    } else content=localHistory(c.installments);
    const reviews=c.nombreRejets?`<div class="schedule-notice"><span>${c.nombreRejets===1?'1 rejet à traiter':`${c.nombreRejets} rejets à traiter`}</span>${!readOnly?`<button type="button" data-ack-rejections ${reviewBusy?'disabled':''}>Rejet traité</button>`:''}</div>`:
      c.nombreRejetsTraites?'<div class="schedule-review-done">✓ Rejet traité</div>':'';
    return `<div class="schedule-nav" role="group" aria-label="Vues de l’échéancier">${tabs}</div><div class="schedule-content">${content}</div>${reviews}<div class="schedule-actions">
      ${scheduleView!=='plan'?`<small role="status">${esc(source)}</small>`:''}
      ${scheduleView!=='plan' && hasBankSchedule()?`<button type="button" data-bank-refresh ${bankLoading?'disabled':''}>Actualiser Qonto</button>`:''}
      ${canEdit && scheduleView==='bank'?'<button type="button" data-edit-schedule>Modifier le suivi local</button>':''}</div>`;
}

  function bindRejectionReview(container) {
    const button=container.querySelector('[data-ack-rejections]');
    if (!button || readOnly) return;
    const selection=reviewSelection(currentLines);
    const bankProof=bankSnapshot?.rejectionProof || '';
    button.onclick=async ()=>{
      if (reviewBusy) return;
      reviewBusy=true;
      button.disabled=true;
      try {
        await billingApi(`/api/billing/trainee/${encodeURIComponent(traineeId)}/session/${encodeURIComponent(sessionId)}/acknowledge-rejections`,{rejections:selection,bankProof});
        if (billingLoadPromise) await billingLoadPromise;
        await load();
        installmentEditFeedback('Le traitement des rejets affichés est enregistré.');
      } catch(error) {
        installmentEditFeedback(error.message || 'Enregistrement impossible.',true);
      } finally {
        reviewBusy=false;
        const current=container.querySelector('[data-ack-rejections]');
        if(current) current.disabled=false;
      }
    };
}

  function renderInstallments(c){
    if (installmentDraftActive || installmentEditBusy) return;
    const items=[...c.effectiveInstallments].sort((a,b)=>installmentDate(a).localeCompare(installmentDate(b)));
    const candidates=currentLines.filter(line=>!isCpfQontoLine(line) && line.paymentMode==='sepa_direct_debit'
      && !line.registrationCancelled && !['cancelled','deleted'].includes(line.invoiceStatus));
    const container=document.getElementById('financeInstallments');
    if (!container) return;
    const feedback='<div id="installmentEditFeedback" role="status" aria-live="polite" hidden></div>';
    if (!editingSchedule || readOnly) {
      const expanded = new Set([...container.querySelectorAll('[data-operation-id][open]')].map(el=>el.dataset.operationId));
      container.innerHTML=feedback+scheduleReadView(c,!readOnly && candidates.length>0);
      bindRejectionReview(container);
      container.querySelectorAll('[data-operation-id]').forEach(el=>{ el.open=expanded.has(el.dataset.operationId); });
      container.querySelectorAll('[data-schedule-view]').forEach(button=>button.onclick=()=>{
        scheduleView=button.dataset.scheduleView;
        renderInstallments(c);
        container.querySelector('.schedule-nav [aria-pressed="true"]')?.focus();
      });
      container.querySelector('[data-edit-schedule]')?.addEventListener('click',()=>{
        editingSchedule=true;
        renderInstallments(c);
        container.querySelector('[data-close-editor]')?.focus();
      });
      container.querySelector('[data-bank-refresh]')?.addEventListener('click',()=>readBankSchedule(true));
      return;
    }
    const rows=items.map((it,i)=>{
      const paid=['completed','paid','succeeded','success'].includes(it.status);
      const canRemove=!paid && !['processing','in_progress','submitted','on_hold'].includes(it.qonto_collection_status_raw || it.status) && candidates.includes(it.line);
      const canEdit=canRemove && !installmentIsRejected(it);
      const date=canEdit?`<input type="date" data-edit-installment-date="${i}" value="${esc(installmentDate(it))}" aria-label="Date de l’échéance">`:scheduleDate(installmentDate(it));
      const amount=canEdit?`<input type="number" data-edit-installment-amount="${i}" value="${Number(it.amount||0).toFixed(2)}" min="0.01" max="1000000" step="0.01" required aria-label="Montant de l’échéance en euros">`:fmtMoney(it.amount);
      const actions=canRemove?`<div class="finance-actions"><button type="button" class="btn btn-primary" data-save-installment="${i}" hidden>Enregistrer</button><button type="button" class="btn btn-outline" data-cancel-installment="${i}" hidden>Annuler</button><button type="button" class="qonto-action-btn qonto-action-btn--danger" data-delete-installment="${i}">Retirer du suivi</button></div>`:'';
      return `<div class="finance-installment-row schedule-edit-row"><label>Date du suivi${date}</label><label>Montant (€)${amount}</label><span>${esc(installmentStatusLabel(it))}</span>${actions}</div>`;
    }).join('');
    const add=!readOnly&&candidates.length?`<div><button type="button" class="btn btn-outline" id="addTrackedInstallment">+ Ajouter une échéance</button><form id="newTrackedInstallment" class="finance-installment-add" hidden><label${candidates.length===1?' hidden':''}>Financement<select name="lineId">${candidates.map(line=>`<option value="${esc(line.id)}">${esc(line.financeurName||line.financingType)} · ${fmtMoney(line.amountTTC||line.amount)}</option>`).join('')}</select></label><label>Date<input name="date" type="date" required></label><label>Montant (€)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required inputmode="decimal"></label><div class="finance-actions"><button class="btn btn-primary" type="submit">Ajouter au suivi</button><button class="btn btn-outline" type="button" id="cancelNewInstallment">Annuler</button></div></form></div>`:'';
    container.innerHTML=feedback+'<div class="schedule-editor-head"><strong>Modifier l’échéancier de la fiche</strong><button type="button" class="btn btn-outline" data-close-editor>Terminer</button></div><p class="schedule-help">Ces modifications concernent le suivi local. Pour modifier ou annuler un prélèvement bancaire, utilisez Qonto.</p>'+rows+add;
    container.querySelector('[data-close-editor]').onclick=()=>{
      editingSchedule=false;
      renderInstallments(c);
      container.querySelector('[data-edit-schedule]')?.focus();
    };
    container.querySelectorAll('[data-edit-installment-date],[data-edit-installment-amount]').forEach(input=>input.addEventListener('input',()=>{
      installmentDraftActive=true;
      const row=input.closest('.finance-installment-row');
      lockInstallmentDraft(row);
      row.querySelector('[data-save-installment]').hidden=false;
      row.querySelector('[data-cancel-installment]').hidden=false;
    }));
    container.querySelectorAll('[data-cancel-installment]').forEach(button=>button.onclick=()=>{installmentDraftActive=false;installmentDraftContainer=null;renderInstallments(computeFinance(currentLines));});
    container.querySelectorAll('[data-save-installment]').forEach(button=>button.onclick=()=>{
      const item=items[Number(button.dataset.saveInstallment)],row=button.closest('.finance-installment-row');
      const date=row.querySelector('[data-edit-installment-date]'),amount=row.querySelector('[data-edit-installment-amount]');
      if(!date.value||!date.reportValidity()){installmentEditFeedback('Choisissez une date valide.',true);return;}
      if(!amount.reportValidity()){installmentEditFeedback('Indiquez un montant positif avec deux décimales maximum.',true);return;}
      saveInstallmentEdit(item.line,'update',{installmentIndex:item.sourceIndex,date:date.value,amount:Number(amount.value)});
    });
    container.querySelectorAll('[data-delete-installment]').forEach(button=>button.onclick=()=>{
      const item=items[Number(button.dataset.deleteInstallment)];
      if(!confirm(`Supprimer du suivi l’échéance du ${formatIsoDateFr(installmentDate(item))} de ${fmtMoney(item.amount)} ?\n\nLe prélèvement bancaire reste inchangé : son annulation doit être faite dans Qonto. L’historique est conservé.`))return;
      saveInstallmentEdit(item.line,'delete',{installmentIndex:item.sourceIndex});
    });
    const addButton=document.getElementById('addTrackedInstallment'),form=document.getElementById('newTrackedInstallment');
    if(addButton)addButton.onclick=()=>{installmentDraftActive=true;form.hidden=false;addButton.hidden=true;lockInstallmentDraft(form);form.elements.date.focus();};
    document.getElementById('cancelNewInstallment')?.addEventListener('click',()=>{installmentDraftActive=false;installmentDraftContainer=null;renderInstallments(computeFinance(currentLines));});
    if(form)form.onsubmit=event=>{
      event.preventDefault();if(!form.reportValidity())return;
      const line=candidates.find(item=>String(item.id)===form.elements.lineId.value);
      if(line)saveInstallmentEdit(line,'add',{date:form.elements.date.value,amount:Number(form.elements.amount.value)});
    };
  }
  function render(lines){
    const c=computeFinance(lines); renderFinancingValidation(c, lines); renderSummary(c); renderBreakdown(lines,c); renderAlerts(lines,c); renderPayments(lines,c); renderInstallments(c);
    if(!lines.length){ box.innerHTML = '<div class="finance-empty">Aucune ligne de facturation disponible. Vérifiez les montants de financement.</div>'; return; }
    box.innerHTML = lines.map(l=>{
      const has = !!(l.qontoInvoiceId || l.qontoDraftId);
      const cpfTrackingOnly = isCpfQontoLine(l);
      const external = lineHasExternalInvoice(l);
      const rowTone = invoiceBadge(l)==='green'?'finance-line--paid':(invoiceBadge(l)==='orange'?'finance-line--unpaid':(invoiceBadge(l)==='red'?'finance-line--danger':'finance-line--info'));
      const id = esc(l.id);
      const view = has ? `<a class="qonto-action-btn qonto-action-btn--secondary" href="/admin/qonto/invoices/${encodeURIComponent(l.qontoInvoiceId||l.qontoDraftId||"")}/pdf" target="_blank" rel="noopener" data-action-control><span aria-hidden="true">👁</span> Voir</a>` : '';
      const create = !cpfTrackingOnly && !lineHasGeneratedInvoice(l) && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--primary" data-create="${id}" data-action-control><span aria-hidden="true">🧾</span> Générer facture</button>` : '';
      const sync = has && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--secondary qonto-desktop-secondary" data-sync-line="${id}" data-action-control><span aria-hidden="true">↻</span> Synchroniser</button>` : '';
      const finalize = !cpfTrackingOnly && has && l.invoiceStatus==='draft' && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--primary" data-finalize="${id}" data-action-control><span aria-hidden="true">✓</span> Finaliser le brouillon</button>` : '';
      const reset = !cpfTrackingOnly && has && l.invoiceStatus==='draft' && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--danger qonto-desktop-secondary" data-reset="${id}" data-action-control><span aria-hidden="true">✕</span> Annuler le brouillon</button>` : '';
      const send = !cpfTrackingOnly && has && ['finalized'].includes(l.invoiceStatus) && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--secondary qonto-desktop-secondary" data-send="${id}" data-action-control><span aria-hidden="true">✉</span> Envoyer par Qonto</button>` : '';
      const resendMandate = !cpfTrackingOnly && lineHasPendingMandate(l) && !readOnly ? `<button class="qonto-action-btn qonto-action-btn--primary qonto-desktop-secondary" data-mandate="${id}" data-action-control><span aria-hidden="true">✉</span> Renvoyer le mandat de prélèvement</button>` : '';
      const schedule = !cpfTrackingOnly && l.paymentMode==='sepa_direct_debit' ? `<button class="qonto-action-btn qonto-action-btn--secondary qonto-desktop-secondary" data-schedule="${id}" data-action-control><span aria-hidden="true">📅</span> Échéancier</button>` : '';
      const mobileActions = (sync || reset || send || resendMandate || schedule) ? `<details class="qonto-mobile-actions"><summary class="qonto-action-btn qonto-action-btn--secondary" aria-label="Actions secondaires">•••</summary><div class="qonto-mobile-actions__menu">${sync.replace(' qonto-desktop-secondary','')}${send.replace(' qonto-desktop-secondary','')}${resendMandate.replace(' qonto-desktop-secondary','')}${schedule.replace(' qonto-desktop-secondary','')}${reset.replace(' qonto-desktop-secondary','')}</div></details>` : '';
      return `<div class="qonto-invoice-row ${rowTone}"><div class="qonto-invoice-row__type"><span class="qonto-invoice-row__icon" aria-hidden="true">💳</span><strong>${esc(l.financeurName||l.financingLabel||l.financingType)}</strong></div><div class="qonto-invoice-row__content"><div class="qonto-invoice-row__value"><span class="finance-mini-label">Facture</span>${esc(canonicalInvoiceEntry(l)?.invoice_number||l.qontoInvoiceNumber||(external?'Générée ailleurs':'—'))}${external?`<div style="margin-top:6px">${badge('Facture générée ailleurs','purple')}</div>`:''}</div><div class="qonto-invoice-row__value"><span class="finance-mini-label">Montant TTC</span>${fmtMoney(lineAmount(l))}</div><div class="qonto-invoice-row__value"><span class="finance-mini-label">Encaissé</span><span class="${linePaid(l)>0?'text-green':''}">${fmtMoney(linePaid(l))}</span></div><div class="qonto-invoice-row__value"><span class="finance-mini-label">Reste à payer</span><span class="${lineRemaining(l)>0?'text-orange':''}">${lineRemaining(l)>0?fmtMoney(lineRemaining(l)):(lineAmount(l)>0&&linePaid(l)>=lineAmount(l)?'Soldé':fmtMoney(0))}</span></div><div class="qonto-invoice-row__value"><span class="finance-mini-label">Créée le</span>${formatIsoDateFr(String(l.invoiceGeneratedAt||l.createdAt||'').slice(0,10))||'—'}</div><div class="qonto-invoice-row__value"><span class="finance-mini-label">Échéance</span>${formatIsoDateFr(String(l.dueDate||l.due_date||'').slice(0,10))||'—'}</div>${badge(paymentStatusLabel(linePaymentStatus(l)),linePaymentStatus(l)==='paid'?'green':(linePaymentStatus(l)==='partially_paid'?'orange':invoiceBadge(l)))}</div><div class="qonto-invoice-actions">${create}${view}${sync}${finalize}${send}${resendMandate}${schedule}${mobileActions}</div>${external?'<div class="muted" style="grid-column:1/-1">Facture déjà générée ailleurs : aucune nouvelle facture à créer. Le téléchargement sera disponible après rattachement de la facture Qonto.</div>':''}${l.syncWarning?`<div class="qonto-error" style="grid-column:1/-1">${esc(l.syncWarning)}</div>`:''}</div>`;
    }).join('');
  }
  window.refreshFinanceDashboard=()=>render(currentLines);
  function showQontoFeedback(message,type='success'){
    const html = `<div class="qonto-feedback qonto-feedback--${type}" role="${type==='error'?'alert':'status'}">${esc(message)}</div>`;
    box.insertAdjacentHTML('afterbegin', html);
  }
  function showQontoSyncModal(title='Synchronisation Qonto en cours', description='Nous récupérons les factures, paiements et échéances à jour. Cela ne prendra que quelques instants.'){
    document.getElementById('qontoSyncProgressModal')?.remove();
    document.body.insertAdjacentHTML('beforeend', `<div class="qonto-sync-overlay no-print" id="qontoSyncProgressModal" role="dialog" aria-modal="true" aria-labelledby="qontoSyncProgressTitle" aria-describedby="qontoSyncProgressDescription"><div class="qonto-sync-dialog"><div class="qonto-sync-brand">Connexion sécurisée</div><div class="qonto-sync-visual" aria-hidden="true"><span class="qonto-sync-ring"></span><span class="qonto-sync-icon">↻</span></div><h2 id="qontoSyncProgressTitle">${esc(title)}</h2><p id="qontoSyncProgressDescription">${esc(description)}</p><div class="qonto-sync-progress" aria-hidden="true"><span></span></div><div class="qonto-sync-safe"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>Vous pouvez laisser cette fenêtre ouverte</div></div></div>`);
  }
  function hideQontoSyncModal(){ document.getElementById('qontoSyncProgressModal')?.remove(); }
  function bankTransferLines(lines){
    return lines.filter(item=>['PERSONNEL','AUTRE'].includes(String(item.financingType||'').toUpperCase()) && !isCpfQontoLine(item) && !['cancelled','canceled','deleted'].includes(String(item.invoiceStatus||'').toLowerCase()));
  }
  function bankTransferLabel(line){
    return String(line.financingType||'').toUpperCase()==='PERSONNEL'?'Financement personnel':(line.financeurName||line.financingLabel||'Autre financement');
  }
  async function openBankTransferModal(){
    if(readOnly || document.getElementById('bankTransferModal'))return;
    const overlay=document.createElement('div');
    overlay.id='bankTransferModal';overlay.className='billing-modal-overlay no-print';
    overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-labelledby','bankTransferTitle');
    overlay.innerHTML=`<div class="billing-modal"><div class="billing-modal-head"><div><h2 id="bankTransferTitle">Affecter un virement reçu</h2><p>Recherchez le payeur, même si son nom est différent de celui du stagiaire.</p></div><button type="button" class="billing-modal-close" data-bank-close aria-label="Fermer">✕</button></div><div data-bank-body role="status" aria-live="polite">Chargement des financements…</div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-bank-close>Fermer</button></div></div>`;
    document.body.appendChild(overlay);
    let busy=false;
    function close(){if(!busy){overlay.remove();document.getElementById('btnAssignBankTransfer')?.focus();}}
    overlay.querySelectorAll('[data-bank-close]').forEach(button=>button.onclick=close);
    overlay.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
    overlay.querySelector('[data-bank-close]').focus();
    const content=overlay.querySelector('[data-bank-body]');
    try{await load();}catch(error){content.className='qonto-error';content.textContent=error.message||'Chargement des financements impossible. Fermez puis réessayez.';return;}
    if(!overlay.isConnected)return;
    const lines=bankTransferLines(currentLines);
    if(!lines.length){content.textContent='Aucun financement personnel ou autre financement hors CPF renseigné pour ce dossier. Renseignez le financement dans les paramètres avant d’affecter un virement.';return;}
    let line=lines.find(item=>lineRemaining(item)>0)||lines[0];
    const start=new Date((line.dateStart||new Date().toISOString().slice(0,10))+'T12:00:00');
    start.setDate(start.getDate()-180);
    const since=Number.isNaN(start.getTime())?'':start.toISOString().slice(0,10);
    const name=`${line.traineeFirstName||''} ${line.traineeLastName||''}`.trim();
    content.removeAttribute('role');content.removeAttribute('aria-live');
    content.innerHTML=`<div class="billing-modal-summary" data-bank-summary></div><form data-bank-search>${lines.length>1?`<label>Financement à créditer<select name="lineId">${lines.map(item=>`<option value="${esc(item.id)}" ${item.id===line.id?'selected':''}>${esc(bankTransferLabel(item))} · ${esc(item.qontoInvoiceNumber||'Sans numéro de facture')} · ${fmtMoney(lineRemaining(item))} restant</option>`).join('')}</select></label>`:''}<div class="billing-modal-grid"><label>Nom du payeur ou libellé<input name="query" type="search" placeholder="Ex. : nom du parent, du conjoint ou de l’entreprise" minlength="2" maxlength="100" required></label><label>Virements reçus depuis le<input name="dateFrom" type="date" value="${esc(since)}" max="${new Date().toISOString().slice(0,10)}"></label></div><div class="billing-modal-actions"><button class="btn btn-primary" type="submit">Rechercher les virements</button></div></form><div data-bank-feedback role="status" aria-live="polite"></div><div data-bank-results></div>`;
    const form=overlay.querySelector('form'),feedback=overlay.querySelector('[data-bank-feedback]'),results=overlay.querySelector('[data-bank-results]');
    function updateSummary(){overlay.querySelector('[data-bank-summary]').innerHTML=`<strong>Dossier : ${esc(name)}</strong><p>${esc(bankTransferLabel(line))} · ${esc(line.qontoInvoiceNumber||'Sans numéro de facture')} · Reste à payer : ${fmtMoney(lineRemaining(line))}</p>`;}
    updateSummary();
    if(form.elements.lineId)form.elements.lineId.onchange=()=>{
      if(busy){form.elements.lineId.value=line.id;return;}
      line=lines.find(item=>item.id===form.elements.lineId.value)||line;
      results.replaceChildren();feedback.textContent='';updateSummary();
    };
    form.elements.query.focus();
    form.onsubmit=async event=>{
      event.preventDefault();if(busy||!form.reportValidity())return;
      busy=true;form.querySelector('button').disabled=true;results.replaceChildren();
      feedback.className='muted';feedback.textContent='Recherche des virements reçus dans Qonto…';
      try{
        const response=await billingApi('/api/billing/bank-transfers/search',{lineId:line.id,query:form.elements.query.value,dateFrom:form.elements.dateFrom.value});
        const transfers=response.transactions||[];
        feedback.textContent=transfers.length?`${transfers.length} virement(s) trouvé(s). Vérifiez le payeur, la date et le montant avant de confirmer.${response.truncated?' Précisez la recherche pour voir les autres résultats.':''}`:'Aucun virement trouvé. Essayez un autre nom ou une date de début plus ancienne.';
        results.innerHTML=transfers.map((transfer,index)=>`<div class="qonto-invoice-card" style="margin-top:12px"><strong>${esc(transfer.payer_name||transfer.label||'Payeur non renseigné')}</strong><p>${fmtMoney(transfer.amount_cents/100)} · Reçu le ${formatIsoDateFr(String(transfer.paid_at).slice(0,10))}</p><p class="muted">${esc(transfer.reference||transfer.label||'Sans libellé')}</p>${transfer.blocked_reason?`<p>${esc(transfer.blocked_reason)}</p>`:`<button type="button" class="btn btn-primary" data-bank-assign="${index}">Affecter à ce dossier</button>`}</div>`).join('');
        results.querySelectorAll('[data-bank-assign]').forEach(button=>button.onclick=async()=>{
          if(busy)return;
          const transfer=transfers[Number(button.dataset.bankAssign)];
          if(!confirm(`Affecter le virement de ${fmtMoney(transfer.amount_cents/100)} reçu de ${transfer.payer_name||transfer.label} le ${formatIsoDateFr(String(transfer.paid_at).slice(0,10))} au dossier de ${name} (${bankTransferLabel(line)}) ?\n\nReste à payer après affectation : ${fmtMoney((response.remaining_cents-transfer.amount_cents)/100)}.`))return;
          busy=true;overlay.querySelectorAll('button').forEach(item=>item.disabled=true);
          feedback.className='muted';feedback.textContent='Vérification du virement et affectation au dossier…';
          try{
            const assigned=await billingApi('/api/billing/bank-transfers/assign',{selectionToken:transfer.selection_token});
            await load();overlay.remove();
            const payments=document.getElementById('financePayments');if(payments?.closest('details'))payments.closest('details').open=true;
            showQontoFeedback(`${assigned.message} ${assigned.remaining_cents===0?'Financement soldé.':`Reste à payer : ${fmtMoney(assigned.remaining_cents/100)}.`}`);
          }catch(error){feedback.className='qonto-error';feedback.textContent=error.message||'Affectation impossible.';results.replaceChildren();}
          finally{busy=false;overlay.querySelectorAll('button').forEach(item=>item.disabled=false);}
        });
      }catch(error){feedback.className='qonto-error';feedback.textContent=error.message||'Recherche impossible.';}
      finally{busy=false;form.querySelector('button').disabled=false;}
    };
  }
  document.getElementById('btnAssignBankTransfer')?.addEventListener('click',openBankTransferModal);
  document.getElementById('btnAttachQontoDebit')?.addEventListener('click',async()=>{
    if(readOnly)return;
    const overlay=document.createElement('div');
    overlay.className='billing-modal-overlay no-print';
    overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');
    overlay.setAttribute('aria-label','Rattacher un prélèvement Qonto');
    overlay.innerHTML='<div class="billing-modal"><div class="billing-modal-header"><div><h2>Rattacher un prélèvement Qonto</h2><p>Sélectionnez un prélèvement déjà encaissé sur le mandat de ce dossier.</p></div><button type="button" class="billing-modal-close" data-close aria-label="Fermer">✕</button></div><div data-content role="status" aria-live="polite">Chargement…</div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-close>Fermer</button></div></div>';
    document.body.appendChild(overlay);
    let busy=false;
    function close(){if(!busy){overlay.remove();document.getElementById('btnAttachQontoDebit')?.focus();}}
    overlay.querySelectorAll('[data-close]').forEach(button=>button.onclick=close);
    overlay.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
    overlay.querySelector('[data-close]').focus();
    const content=overlay.querySelector('[data-content]');
    try{
      await load();if(!overlay.isConnected)return;
      const lines=currentLines.filter(line=>!isCpfQontoLine(line)&&line.paymentMode==='sepa_direct_debit'&&!line.registrationCancelled);
      if(!lines.length){content.textContent='Aucun financement par prélèvement sur ce dossier. Renseignez d’abord son mandat Qonto.';return;}
      content.innerHTML=`<label>Financement<select data-line>${lines.map(line=>`<option value="${esc(line.id)}">${esc(line.financeurName||line.financingType)} · ${esc(line.qontoInvoiceNumber||'Sans facture')} · ${fmtMoney(lineAmount(line))}</option>`).join('')}</select></label><div class="billing-modal-actions"><button class="btn btn-primary" type="button" data-search>Rechercher dans Qonto</button></div><p data-feedback></p><div data-results></div>`;
      const selector=content.querySelector('[data-line]'),search=content.querySelector('[data-search]'),feedback=content.querySelector('[data-feedback]'),results=content.querySelector('[data-results]');
      selector.onchange=()=>{results.replaceChildren();feedback.textContent='';};
      search.onclick=async()=>{
        if(busy)return;busy=true;search.disabled=true;selector.disabled=true;results.replaceChildren();
        feedback.className='muted';feedback.textContent='Recherche des prélèvements encaissés dans Qonto…';
        try{
          const line=lines.find(item=>item.id===selector.value);
          const response=await billingApi('/api/billing/direct-debits/search',{lineId:line.id});
          const records=response.collections||[];
          feedback.textContent=records.length?'Vérifiez la date, le montant et le libellé avant le rattachement.':'Aucun prélèvement encaissé non rattaché trouvé sur ce mandat.';
          results.innerHTML=records.map((record,index)=>`<div class="qonto-invoice-card" style="margin-top:12px"><strong>${fmtMoney(record.amount)} · ${formatIsoDateFr(record.date)}</strong><p>${esc(record.reference||'Sans libellé')}</p>${record.already_entered?'<p>Ce paiement est déjà saisi : seul son lien Qonto sera ajouté.</p>':''}<small>Prélèvement ${esc(record.id)}</small><p>${record.blocked_reason?esc(record.blocked_reason):`<button type="button" class="btn btn-primary" data-attach="${index}">Rattacher à ce dossier</button>`}</p></div>`).join('');
          results.querySelectorAll('[data-attach]').forEach(button=>button.onclick=async()=>{
            if(busy)return;const record=records[Number(button.dataset.attach)];
            if(!confirm(`Rattacher le prélèvement de ${fmtMoney(record.amount)} du ${formatIsoDateFr(record.date)} à ce dossier ?\n\nCette action met à jour le suivi local. Les prélèvements programmés dans Qonto restent à vérifier séparément.`))return;
            busy=true;overlay.querySelectorAll('button,select').forEach(item=>item.disabled=true);
            feedback.className='muted';feedback.textContent='Vérification du paiement et rattachement…';
            try{
              const attached=await billingApi('/api/billing/direct-debits/attach',{selectionToken:record.selection_token});
              await load();overlay.remove();showQontoFeedback(`${attached.message} Reste à payer : ${fmtMoney(attached.remaining_cents/100)}.`);
            }catch(error){feedback.className='qonto-error';feedback.textContent=error.message||'Rattachement impossible.';results.replaceChildren();}
            finally{busy=false;overlay.querySelectorAll('button,select').forEach(item=>item.disabled=false);}
          });
        }catch(error){feedback.className='qonto-error';feedback.textContent=error.message||'Recherche impossible.';}
        finally{busy=false;search.disabled=false;selector.disabled=false;}
      };
      search.click();
    }catch(error){content.textContent=error.message||'Chargement impossible.';}
  });
  function setRowBusy(btn,busy){
    const row = btn.closest('.qonto-invoice-row');
    row?.querySelectorAll('[data-action-control]').forEach(control=>{ if('disabled' in control) control.disabled=busy; else control.setAttribute('aria-disabled', busy?'true':'false'); });
  }
  box.addEventListener('click', async e=>{
    const action = e.target.closest('[data-create],[data-finalize],[data-send],[data-reset],[data-mandate],[data-schedule],[data-sync-line]');
    if(!action) return;
    const id = action.dataset.create || action.dataset.finalize || action.dataset.send || action.dataset.reset || action.dataset.mandate || action.dataset.schedule || action.dataset.syncLine;
    if(!id) return;
    try{
      if(action.dataset.create){ const line = currentLines.find(l=>l.id===id); if(line) openGenerateInvoiceModal(line); return; }
      if(action.dataset.schedule){ const line=currentLines.find(l=>l.id===id); if(line){document.body.insertAdjacentHTML('beforeend',`<div class="billing-modal-overlay no-print" role="dialog" aria-modal="true"><div class="billing-modal">${renderScheduleModal(line)}</div></div>`); document.querySelectorAll('[data-modal-close]').forEach(btn=>btn.onclick=closeBillingModal);} return; }
      if(action.dataset.reset && !confirm('Voulez-vous vraiment annuler ce brouillon Qonto ? Cette action est irréversible.')) return;
      const original = action.innerHTML;
      setRowBusy(action,true);
      action.innerHTML = '<span aria-hidden="true">⏳</span> Traitement…';
      let successMessage = 'Action Qonto terminée.';
      if(action.dataset.mandate){ await billingApi('/api/billing/resend-mandate',{lineId:id,source:'admin_trainee'}); successMessage = 'Lien de mandat renvoyé.'; }
      if(action.dataset.syncLine){ const syncData=await billingApi('/api/billing/sync-qonto',{lineId:id,source:'admin_trainee'}); const paid=syncData?.invoice?.paid_amount_cents ?? syncData?.invoice?.amount_paid_cents; successMessage = paid!=null ? `Facture Qonto synchronisée — ${fmtMoney(paid/100)} encaissés` : 'Facture Qonto synchronisée.'; }
      if(action.dataset.finalize){ await billingApi('/api/billing/finalize',{lineId:id,source:'admin_trainee'}); successMessage = 'Brouillon Qonto finalisé.'; }
      if(action.dataset.send){ await billingApi('/api/billing/send',{lineId:id,source:'admin_trainee'}); successMessage = 'Facture envoyée par Qonto.'; }
      if(action.dataset.reset){ await billingApi('/api/billing/cancel-or-reset',{lineId:id,source:'admin_trainee'}); successMessage = 'Brouillon Qonto annulé.'; }
      action.innerHTML = original;
      await load();
      showQontoFeedback(successMessage);
    }catch(err){ showQontoFeedback(err.message||'Action impossible','error'); setRowBusy(action,false); }
  });
  financeNotificationsBtn?.addEventListener('click', ()=>{ financeNotificationsOpen = !financeNotificationsOpen; render(currentLines); });
  quickGenerateBtn?.addEventListener('click', ()=>{ const line=firstInvoiceToGenerate(); if(line) openGenerateInvoiceModal(line); });
  syncBtn?.addEventListener('click', async ()=>{ syncBtn.disabled=true; showQontoSyncModal(); try{ const j=await billingApi('/api/billing/sync-qonto',{traineeId,sessionId,source:'admin_trainee',refreshWedof:true}); await load(); if(j.failed_count){const detail=j.errors?.[0]?.message||'Qonto a refusé la programmation des échéances.';throw new Error(`Échéancier non programmé : ${detail}`);} hideQontoSyncModal(); alert(j.message||'Synchronisation terminée'); }catch(e){ hideQontoSyncModal(); alert(e.message||'Synchronisation Qonto impossible pour le moment'); } finally{ hideQontoSyncModal(); syncBtn.disabled=false; }});
  function financialResetStatusLabel(status){
    const value=String(status||'').toLowerCase();
    if(['completed','paid','succeeded','success'].includes(value))return 'Réglé';
    if(['scheduled','pending','active','in_progress','on_hold'].includes(value))return 'Programmé';
    if(['failed','rejected','declined'].includes(value))return 'Rejeté';
    return value||'Inconnu';
  }
  let financialResetDraftRows=[];
  function financialResetLineIsPersonal(line){
    return [line?.financingType,line?.typeFinanceur,line?.financingLabel,line?.financeurName]
      .some(value=>['PERSONNEL','PERSONAL'].includes(String(value||'').trim().toUpperCase()));
  }
  function financialResetRawRows(line){
    const direct=Array.isArray(line?.directDebitInstallments)?line.directDebitInstallments.filter(item=>item&&typeof item==='object'):[];
    if(direct.length)return direct;
    const sepa=Array.isArray(line?.sepa_payment_plan?.installments)?line.sepa_payment_plan.installments.filter(item=>item&&typeof item==='object'):[];
    if(sepa.length)return sepa;
    return Array.isArray(line?.paymentPlan?.schedule)?line.paymentPlan.schedule.filter(item=>item&&typeof item==='object'):[];
  }
  function financialResetLineHasTracking(line){
    const paymentMode=String(line?.paymentMode||'').trim().toLowerCase();
    const planMode=String(line?.paymentPlan?.mode||line?.paymentPlan?.paymentMode||'').trim().toLowerCase();
    return financialResetRawRows(line).length>0
      || ['sepa','direct_debit','sepa_direct_debit'].includes(paymentMode)
      || ['sepa','direct_debit','sepa_direct_debit'].includes(planMode)
      || Boolean(line?.qonto_direct_debit_mandate_id||line?.qonto_direct_debit_subscription_id||line?.qonto_mandate_rum);
  }
  function financialResetTargetLine(){
    const personal=currentLines.filter(financialResetLineIsPersonal);
    const pool=personal.length?personal:currentLines.filter(financialResetLineHasTracking);
    const withRows=pool.filter(line=>financialResetRawRows(line).length>0);
    const tracked=pool.filter(financialResetLineHasTracking);
    const matches=withRows.length?withRows:(tracked.length?tracked:personal);
    return matches.length===1?matches[0]:null;
  }
  function financialResetNormalizedStatus(status){
    const value=String(status||'scheduled').toLowerCase();
    if(['completed','paid','succeeded','success'].includes(value))return 'completed';
    if(['failed','returned','rejected','refunded','declined'].includes(value))return 'failed';
    return 'scheduled';
  }
  function financialResetRowsFromLine(line){
    const direct=Array.isArray(line?.directDebitInstallments)&&line.directDebitInstallments.length?logicalInstallmentsForLine(line):[];
    const source=direct.length?direct:financialResetRawRows(line);
    return [...source]
      .sort((a,b)=>installmentDate(a).localeCompare(installmentDate(b)))
      .map(item=>({
        date:installmentDate(item),
        amount_cents:Number.isInteger(item?.amount_cents)?Number(item.amount_cents):Math.round(Number(item?.amount||0)*100),
        status:financialResetNormalizedStatus(item?.status)
      }));
  }
  function financialResetRowHtml(row,index){
    const amount=(Number(row?.amount_cents||0)/100).toFixed(2);
    const status=financialResetNormalizedStatus(row?.status);
    return `<div class="kv" data-financial-reset-row style="display:grid;grid-template-columns:minmax(145px,1fr) minmax(125px,.8fr) minmax(150px,1fr) auto;gap:10px;align-items:end;">
      <label><span class="label">Date</span><input type="date" data-financial-reset-date value="${esc(row?.date||'')}"></label>
      <label><span class="label">Montant</span><input type="number" min="0.01" step="0.01" data-financial-reset-amount value="${esc(amount)}"></label>
      <label><span class="label">Statut</span><select data-financial-reset-status><option value="completed"${status==='completed'?' selected':''}>Réglé</option><option value="scheduled"${status==='scheduled'?' selected':''}>Programmé</option><option value="failed"${status==='failed'?' selected':''}>Rejeté</option></select></label>
      <button type="button" class="btn btn-outline" data-financial-reset-remove="${index}" aria-label="Supprimer cette échéance">Supprimer</button>
    </div>`;
  }
  function collectFinancialResetRows(){
    return [...document.querySelectorAll('[data-financial-reset-row]')].map(row=>({
      date:String(row.querySelector('[data-financial-reset-date]')?.value||'').trim(),
      amount_cents:Math.round(Number(String(row.querySelector('[data-financial-reset-amount]')?.value||0).replace(',','.'))*100),
      status:String(row.querySelector('[data-financial-reset-status]')?.value||'scheduled')
    }));
  }
  function updateFinancialResetTotals(line){
    const rows=collectFinancialResetRows();
    const total=rows.reduce((sum,row)=>sum+Number(row.amount_cents||0),0);
    const paid=rows.filter(row=>row.status==='completed').reduce((sum,row)=>sum+Number(row.amount_cents||0),0);
    const expected=Math.round(Number(lineAmount(line)||0)*100);
    const gap=expected-total;
    const totalNode=document.getElementById('financialResetDraftTotal');
    const paidNode=document.getElementById('financialResetDraftPaid');
    const gapNode=document.getElementById('financialResetDraftGap');
    if(totalNode)totalNode.textContent=fmtMoney(total/100);
    if(paidNode)paidNode.textContent=fmtMoney(paid/100);
    if(gapNode){
      gapNode.textContent=Math.abs(gap)<=1?(gap===0?'Total conforme':'Écart d’arrondi de 0,01 € accepté'):`Écart de ${fmtMoney(Math.abs(gap)/100)}`;
      gapNode.style.color=Math.abs(gap)<=1?'#15803d':'#b91c1c';
    }
  }
  function renderFinancialResetEditor(line){
    const expected=Math.round(Number(lineAmount(line)||0)*100);
    return `<div class="billing-modal-head"><div><h2>Corriger le suivi financier</h2><div class="muted">Renseignez ici l’échéancier réel de cette fiche.</div><span class="billing-modal-step">Étape 1 · Saisie</span></div><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div>
      <div class="billing-modal-error" style="margin:14px 0;">L’ancien historique Qonto peut contenir plusieurs plans. Les lignes ci-dessous sont donc modifiables : vérifiez chaque date, montant et statut.</div>
      <div id="financialResetRows" style="display:grid;gap:10px;">${financialResetDraftRows.map(financialResetRowHtml).join('')}</div>
      <div class="billing-modal-actions" style="justify-content:flex-start;"><button type="button" class="btn btn-outline" id="addFinancialResetRow">+ Ajouter une échéance</button></div>
      <div class="billing-modal-grid" style="margin-top:14px;"><div class="kv"><b>Montant personnel attendu</b><br>${fmtMoney(expected/100)}</div><div class="kv"><b>Total saisi</b><br><span id="financialResetDraftTotal">—</span></div><div class="kv"><b>Déjà réglé</b><br><span id="financialResetDraftPaid">—</span></div><div class="kv"><b>Contrôle</b><br><span id="financialResetDraftGap">—</span></div></div>
      <div class="hint" style="margin-top:12px;">Cette action modifie uniquement le suivi de cette fiche : elle ne crée, ne modifie et n’annule aucun prélèvement dans Qonto. Une sauvegarde automatique sera conservée.</div>
      <div id="modalMsg"></div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" data-modal-close>Annuler</button><button type="button" class="btn btn-primary" id="verifyFinancialReset">Vérifier l’échéancier</button></div>`;
  }
  function bindFinancialResetEditor(line){
    bindModalCloseButtons();
    document.querySelectorAll('[data-financial-reset-date],[data-financial-reset-amount],[data-financial-reset-status]').forEach(input=>input.addEventListener('input',()=>updateFinancialResetTotals(line)));
    document.querySelectorAll('[data-financial-reset-remove]').forEach(button=>button.onclick=()=>{
      financialResetDraftRows=collectFinancialResetRows().filter((row,index)=>index!==Number(button.dataset.financialResetRemove));
      const modal=document.querySelector('.billing-modal');
      if(modal)modal.innerHTML=renderFinancialResetEditor(line);
      bindFinancialResetEditor(line);
    });
    const add=document.getElementById('addFinancialResetRow');
    if(add)add.onclick=()=>{
      financialResetDraftRows=collectFinancialResetRows();
      financialResetDraftRows.push({date:'',amount_cents:0,status:'scheduled'});
      const modal=document.querySelector('.billing-modal');
      if(modal)modal.innerHTML=renderFinancialResetEditor(line);
      bindFinancialResetEditor(line);
    };
    const verify=document.getElementById('verifyFinancialReset');
    if(verify)verify.onclick=()=>verifyFinancialReset(line);
    updateFinancialResetTotals(line);
  }
  function renderFinancialResetReview(preview){
    const rows=(preview.installments||[]).map((item,index)=>`<div class="kv"><b>${index+1}/${preview.installments.length} · ${esc(formatIsoDateFr(item.date)||item.date)}</b><br>${fmtMoney(Number(item.amount_cents||0)/100)} · ${esc(financialResetStatusLabel(item.status))}</div>`).join('');
    const gap=Math.abs(Number(preview.expected_amount_cents||0)-Number(preview.detected_amount_cents||0));
    return `<div class="billing-modal-head"><div><h2>Vérifiez avant d’appliquer</h2><div class="muted">Voici exactement ce qui apparaîtra sur cette fiche.</div><span class="billing-modal-step">Étape 2 · Confirmation</span></div><button class="billing-modal-close" type="button" data-modal-close aria-label="Fermer">✕</button></div>
      <div class="billing-modal-grid" style="margin-top:14px;">${rows}</div>
      <div class="billing-modal-grid" style="margin-top:14px;"><div class="kv"><b>Total de l’échéancier</b><br>${fmtMoney(Number(preview.detected_amount_cents||0)/100)}</div><div class="kv"><b>Déjà réglé</b><br>${fmtMoney(Number(preview.paid_amount_cents||0)/100)}</div><div class="kv"><b>Reste contractuel</b><br>${fmtMoney(Number(preview.remaining_amount_cents||0)/100)}</div><div class="kv"><b>Contrôle</b><br>${gap===1?'Écart d’arrondi de 0,01 € accepté':'Total conforme'}</div></div>
      <div class="billing-modal-success" style="margin-top:14px;">Seule cette fiche sera mise à jour. Qonto et les autres stagiaires resteront inchangés.</div>
      <div id="modalMsg"></div><div class="billing-modal-actions"><button type="button" class="btn btn-outline" id="editFinancialReset">Retour à la modification</button><button type="button" class="btn btn-primary" id="applyFinancialReset">Confirmer et appliquer</button></div>`;
  }
  async function verifyFinancialReset(line){
    const rows=collectFinancialResetRows();
    financialResetDraftRows=rows;
    const verify=document.getElementById('verifyFinancialReset');
    if(verify){verify.disabled=true;verify.textContent='Vérification…';}
    try{
      const result=await billingApi('/api/billing/reset-financial-tracking',{traineeId,sessionId,preview:true,manualInstallments:rows,source:'admin_trainee'});
      const preview=result.preview||{};
      financialResetDraftRows=(preview.installments||[]).map(row=>({...row}));
      const modal=document.querySelector('.billing-modal');
      if(!modal)return;
      modal.innerHTML=renderFinancialResetReview(preview);
      bindModalCloseButtons();
      document.getElementById('editFinancialReset').onclick=()=>{modal.innerHTML=renderFinancialResetEditor(line);bindFinancialResetEditor(line);};
      document.getElementById('applyFinancialReset').onclick=()=>applyFinancialReset(line,preview);
    }catch(error){
      modalMessage(error.message||'L’échéancier n’est pas valide.','error');
      if(verify){verify.disabled=false;verify.textContent='Vérifier l’échéancier';}
    }
  }
  async function applyFinancialReset(line,preview){
    const apply=document.getElementById('applyFinancialReset');
    if(apply){apply.disabled=true;apply.textContent='Application…';}
    try{
      const result=await billingApi('/api/billing/reset-financial-tracking',{traineeId,sessionId,confirm:true,manualInstallments:financialResetDraftRows,previewFingerprint:preview.fingerprint,source:'admin_trainee'});
      await load();
      const updatedPreview=result.preview||preview;
      const modal=document.querySelector('.billing-modal');
      if(!modal)return;
      modal.innerHTML=`<div class="qonto-result qonto-result--success" role="status"><button class="billing-modal-close qonto-result__close" type="button" data-modal-close aria-label="Fermer">✕</button><div class="qonto-result__check" aria-hidden="true">✓</div><div class="qonto-result__eyebrow">Correction enregistrée</div><h2>Le suivi financier est maintenant à jour</h2><p>${esc(result.message||'La correction a été appliquée uniquement à cette fiche.')}</p><div class="qonto-result__reference"><span>Déjà réglé</span><strong>${fmtMoney(Number(updatedPreview.paid_amount_cents||0)/100)}</strong></div><div class="qonto-result__reference"><span>Reste contractuel</span><strong>${fmtMoney(Number(updatedPreview.remaining_amount_cents||0)/100)}</strong></div><div class="billing-modal-actions"><button type="button" class="btn btn-primary" data-modal-close>Terminer</button></div></div>`;
      bindModalCloseButtons();
    }catch(error){
      modalMessage(error.message||'La correction a été annulée sans modification.','error');
      if(apply){apply.disabled=false;apply.textContent='Confirmer et appliquer';}
    }
  }
  resetFinancialTrackingBtn?.addEventListener('click', ()=>{
    const line=financialResetTargetLine();
    if(!line){alert('Aucun échéancier personnel unique n’a été trouvé sur cette fiche.');return;}
    currentLine=line;
    financialResetDraftRows=financialResetRowsFromLine(line);
    if(!financialResetDraftRows.length)financialResetDraftRows=[{date:'',amount_cents:0,status:'scheduled'}];
    document.body.insertAdjacentHTML('beforeend',`<div class="billing-modal-overlay no-print" role="dialog" aria-modal="true"><div class="billing-modal">${renderFinancialResetEditor(line)}</div></div>`);
    bindFinancialResetEditor(line);
  });
  const mandateSearchBtn=document.getElementById('btnSearchQontoMandate');
  const mandateNumberInput=document.getElementById('qontoMandateNumber');
  const mandateSearchFeedback=document.getElementById('qontoMandateSearchFeedback');
  mandateSearchBtn?.addEventListener('click', async ()=>{
    const mandateRum=String(mandateNumberInput?.value||'').trim();
    mandateSearchFeedback.className='qonto-mandate-search__feedback';
    if(!mandateRum){ mandateSearchFeedback.textContent='Saisissez un numéro RUM de mandat.'; mandateSearchFeedback.classList.add('is-error'); mandateNumberInput?.focus(); return; }
    const original=mandateSearchBtn.innerHTML;
    mandateSearchBtn.disabled=true; mandateSearchBtn.textContent='Recherche…';
    try{
      const response=await fetch(`/api/admin/trainees/${encodeURIComponent(traineeId)}/qonto-mandate/search`,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({rum:mandateRum})});
      const result=await parseJsonResponse(response,'Recherche du mandat impossible');
      if(!response.ok||!result.ok) throw new Error(result.error||'Aucun mandat Qonto trouvé avec ce RUM');
      const status=result.mandate?.status||'inconnu';
      mandateSearchFeedback.textContent=`Mandat RUM ${result.mandate?.rum||mandateRum} retrouvé — statut : ${status}.`;
      mandateSearchFeedback.classList.add('is-success');
      await load();
    }catch(error){ mandateSearchFeedback.textContent=error.message||'Recherche du mandat impossible.'; mandateSearchFeedback.classList.add('is-error'); }
    finally{ mandateSearchBtn.disabled=false; mandateSearchBtn.innerHTML=original; }
  });
  [cpfAmount, personalAmount, otherAmount, trainingPrice].forEach(input=>input?.addEventListener('input', ()=>{ const c=computeFinance(currentLines); renderFinancingValidation(c, currentLines); }));
  async function saveFinanceValidationOverride(payload){
    if(typeof updateTrainee === 'function') return updateTrainee(payload);
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/stagiaires/${encodeURIComponent(traineeId)}/update`,{
      method:'POST',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify(payload)
    });
    const result = await parseJsonResponse(response,'Sauvegarde du statut financement impossible');
    if(!response.ok || !result.ok) throw new Error(result.error || result.message || 'Sauvegarde du statut financement impossible');
    return result;
  }
  function setFinanceSaveIndicator(message, tone='saved'){
    const indicator = document.getElementById('financeSaveIndicator');
    if(!indicator) return;
    indicator.textContent = message;
    indicator.className = `finance-save-indicator is-${tone}`;
  }
  financeValidationForceForm?.addEventListener('submit', async (event)=>{
    event.preventDefault();
    if(financeValidationForceBtn.disabled) return;
    financeValidationForceBtn.disabled = true;
    const originalLabel = financeValidationForceBtn.textContent;
    financeValidationForceBtn.textContent = 'Validation…';
    setFinanceSaveIndicator('Validation du financement…','saving');
    try{
      if(financeValidationForceForm?.action){
        const response = await fetch(financeValidationForceForm.action,{method:'POST',headers:{'Accept':'application/json'}});
        const result = await parseJsonResponse(response,'Forçage du statut impossible');
        if(!response.ok || !result.ok) throw new Error(result.error || result.message || 'Forçage du statut impossible');
      }else{
        await saveFinanceValidationOverride({financing_validation_manual_mode:'manual', financing_validation_manual_status:'validated', financement_status:'validated'});
      }
      financeValidationManualMode = true;
      financeValidationManualStatus = 'validated';
      if(financeValidationWrap){
        financeValidationWrap.dataset.manualMode = 'manual';
        financeValidationWrap.dataset.manualStatus = 'validated';
      }
      currentFinancementStatus = 'validated';
      applyFinancingValidationState({label:'Financement validé', tone:'green', icon:'✓', manual:true});
      setFinanceSaveIndicator('Financement validé','saved');
    }catch(e){
      alert(e.message || 'Forçage du statut impossible');
      setFinanceSaveIndicator('Erreur de validation','error');
      financeValidationForceBtn.disabled = false;
    }finally{
      financeValidationForceBtn.textContent = originalLabel;
    }
  });
  financeValidationAutoBtn?.addEventListener('click', async ()=>{
    financeValidationAutoBtn.disabled = true;
    try{
      await updateTrainee({financing_validation_manual_mode:'', financing_validation_manual_status:''});
      financeValidationManualMode = false;
      financeValidationManualStatus = '';
      if(financeValidationWrap){
        financeValidationWrap.dataset.manualMode = '';
        financeValidationWrap.dataset.manualStatus = '';
      }
      renderFinancingValidation(computeFinance(currentLines), currentLines);
    }catch(e){ alert(e.message || 'Retour au calcul automatique impossible'); }
    finally{ financeValidationAutoBtn.disabled = false; renderFinancingValidation(computeFinance(currentLines), currentLines); }
  });
  billingSection?.addEventListener('toggle', () => scheduleLocalTraineePoll(billingSection.open));
  scheduleLocalTraineePoll(billingSection?.open);
})();

// Financement status update
// =========================
const financementSelect = document.getElementById("financementSelect");

if(financementSelect){
  applyStatusPill(financementSelect); // ✅ couleur au chargement

  financementSelect.addEventListener("change", async ()=>{
    applyStatusPill(financementSelect); // ✅ couleur immédiate

    const value = financementSelect.value;

    try{
      await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ financement_status: value })
      });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde financement");
    }
  });
}

const financementNewDateIndicator = document.getElementById("financementNewDateIndicator");
if(financementNewDateIndicator){
  financementNewDateIndicator.addEventListener("click", async ()=>{
    if(financementNewDateIndicator.getAttribute("data-seen") === "1"){
      return;
    }
    try{
      await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ financement_new_date_seen: true })
      });
      financementNewDateIndicator.textContent = "🟢";
      financementNewDateIndicator.setAttribute("data-seen", "1");
    }catch(e){
      alert("Erreur sauvegarde prélèvement");
    }
  });
}
  
// ✅ Checkbox "Pas de permis" (A3P) -> no_permis = true/false
const chkNoPermis = document.getElementById("chkNoPermis");
if(chkNoPermis){
  chkNoPermis.addEventListener("change", async ()=>{
    try{
      await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ no_permis: chkNoPermis.checked })
      });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde permis");
    }
  });
}

const chkNoBacDiploma = document.getElementById("chkNoBacDiploma");
if(chkNoBacDiploma){
  chkNoBacDiploma.addEventListener("change", async ()=>{
    try{
      await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ no_bac_diploma: chkNoBacDiploma.checked })
      });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde diplôme");
    }
  });
}


  // =========================
// Commentaire stagiaire autosave
// =========================
const traineeComment = document.getElementById("traineeComment");
if(traineeComment){
  let t=null;
  traineeComment.addEventListener("input", ()=>{
    if(t) clearTimeout(t);
    t = setTimeout(async ()=>{
      try{
        await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
          method:"POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ comment: traineeComment.value })
        });
      }catch(e){
        console.log("Erreur sauvegarde commentaire stagiaire");
      }
    }, 450);
  });
}


  // ===== RELANCE TELEPHONIQUE (UI only) =====
  const btnOpenPhoneRelance = document.getElementById("btnOpenPhoneRelance");
  const phoneRelanceForm = document.getElementById("phoneRelanceForm");
  const phoneRelanceMissingPreview = document.getElementById("phoneRelanceMissingPreview");
  const btnOpenVtcBookModal = document.getElementById("btnOpenVtcBookModal");
  const btnConfirmVtcBookSent = document.getElementById("btnConfirmVtcBookSent");
  const vtcBookSentLine = document.getElementById("vtcBookSentLine");
  const vtcBookSentDate = document.getElementById("vtcBookSentDate");

  // 1) Calcul des docs manquants / non conformes depuis le tableau docs
  function computeMissingDocsFromTable(){
    const out = [];
    const table = document.getElementById("docsTable");
    if(!table) return out;

    table.querySelectorAll("tr[data-doc-key]").forEach(tr=>{
      const docLabel = tr.querySelector("td")?.innerText?.trim() || "Document";
      const sel = tr.querySelector("select.sel-doc");
      // si pas de select => on saute
      if(!sel) return;

      const status = (sel.value || "").toUpperCase().trim();
      // non déposé / à contrôler / non conforme => incomplet
      if(status === "NON DÉPOSÉ" || status === "A CONTRÔLER" || status === "A CONTROLER" || status === "NON CONFORME"){
        out.push(`- ${docLabel} : ${status}`);
      }
    });

    return out;
  }

  // 2) Calcul des infos manquantes via les champs connus (fallback)
  // On ne peut pas lire directement les infos du public space ici, donc on utilise les valeurs du stagiaire injectées par Jinja.
  let traineePreNumber = sheetContext.preNumber;
  function computeMissingInfosFromTrainee(){
    const missing = [];

    const birth_date = (sheetContext.birthDate).trim();
    const birth_city = (sheetContext.birthCity).trim();
    const birth_country = (sheetContext.birthCountry).trim();
    const nationality = (sheetContext.nationality).trim();
    const address = (sheetContext.address).trim();
    const zip_code = (sheetContext.zipCode).trim();
    const city = (sheetContext.city).trim();

    const carte_vitale_raw = (sheetContext.carteVitale).trim();
    const pre_number_raw = (traineePreNumber || "").trim();

    if(!birth_date) missing.push("- Date de naissance");
    if(!birth_city) missing.push("- Ville de naissance");
    if(!birth_country) missing.push("- Pays de naissance");
    if(!nationality) missing.push("- Nationalité");
    if(!address) missing.push("- Adresse postale");
    if(!zip_code) missing.push("- Code postal");
    if(!city) missing.push("- Ville");

    // sécu : 15 chiffres
    if(!carte_vitale_raw){
      missing.push("- Numéro de sécurité sociale");
    } else {
      const digits = carte_vitale_raw.replace(/\D+/g,"");
      if(digits.length !== 15) missing.push("- Numéro de sécurité sociale (15 chiffres)");
    }

    // PRE/CAR format (on reste simple côté front)
    if(!pre_number_raw){
      missing.push("- Numéro PRE / CAR");
    } else {
      const pre = pre_number_raw.toUpperCase().replace(/\s+/g,"");
      const ok = /^(?:(PRE|CAR)-(?:\d{3}-)?\d{4}-\d{2}-\d{2}-\d{11,}|\d{4}-\d{7}-(PRE|CAR)-[A-Z0-9]{2}-\d{7})$/.test(pre);
      if(!ok) missing.push("- Numéro PRE / CAR (format invalide)");
    }

    return missing;
  }

  function buildMissingPreviewText(){
    const docs = computeMissingDocsFromTable();
    const infos = computeMissingInfosFromTrainee();

    let txt = "";
    txt += "📄 Documents incomplets :\n";
    txt += (docs.length ? docs.join("\n") : "- Aucun (selon les statuts actuels)") + "\n\n";
    txt += "🧾 Informations à compléter :\n";
    txt += (infos.length ? infos.join("\n") : "- Aucune") + "\n";
    return txt;
  }

  // OUVERTURE MODALE + remplissage preview
  btnOpenPhoneRelance?.addEventListener("click", ()=>{
    if(phoneRelanceMissingPreview){
      phoneRelanceMissingPreview.textContent = buildMissingPreviewText();
    }
    openModal("phoneRelanceModal");
  });

  // Pour l’instant : on empêche l’envoi (pas encore branché backend)
phoneRelanceForm?.addEventListener("submit", async (e)=>{
  e.preventDefault();
  if(!await window.confirmMailSmsSend?.()) return;

  const btn = document.getElementById("btnSendPhoneRelance");
  const commentEl = document.getElementById("phoneRelanceComment");
  const comment = (commentEl?.value || "").trim();

  if(btn){
    btn.disabled = true;
    btn.textContent = "Envoi...";
  }

  try{
    const r = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/phone-relance/send`, {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ comment })
    });

    const res = await r.json();

    if(!res.ok){
      alert("Erreur envoi relance : " + (res.error || "unknown"));
      return;
    }

    // ✅ ferme la modale + refresh pour voir l’historique
    closeModal("phoneRelanceModal");
    window.location.reload();

  }catch(err){
    alert("Erreur réseau / serveur (relance téléphonique).");
  }finally{
    if(btn){
      btn.disabled = false;
      btn.textContent = "ENVOYER";
    }
  }
});

  btnOpenVtcBookModal?.addEventListener("click", ()=>{
    openModal("vtcBookModal");
  });

  btnConfirmVtcBookSent?.addEventListener("click", async ()=>{
    const now = new Date();
    const sentAt = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")}/${now.getFullYear()}`;

    try{
      btnConfirmVtcBookSent.disabled = true;
      const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ vtc_book_sent_at: sentAt })
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok || data.ok === false){
        throw new Error("save_failed");
      }

      if(vtcBookSentDate) vtcBookSentDate.textContent = sentAt;
      if(vtcBookSentLine) vtcBookSentLine.style.display = "block";
      btnConfirmVtcBookSent.classList.remove("btn-primary");
      btnConfirmVtcBookSent.classList.add("btn-disabled-muted");
      if(btnOpenVtcBookModal){
        btnOpenVtcBookModal.disabled = true;
        btnOpenVtcBookModal.classList.remove("btn-blue");
        btnOpenVtcBookModal.classList.add("btn-disabled-muted");
      }
      closeModal("vtcBookModal");
    }catch(e){
      alert("Erreur lors de la sauvegarde de l'envoi du livre.");
      btnConfirmVtcBookSent.disabled = false;
    }
  });

  const financeSection = document.getElementById("conventionFinancementSection");
  function resetFinanceSection(){
    if(!financeSection) return;
    financeSection.open = false;
    financeSection.classList.add("is-hidden");
  }
  resetFinanceSection();
  window.addEventListener("pageshow", () => { if(location.hash !== "#conventionFinancementSection") resetFinanceSection(); });

  function openAdminDetailsSection(targetId, options = {}){
    if(!targetId) return false;
    const target = document.getElementById(targetId);
    if(!target) return false;
    target.classList.remove("is-hidden");
    target.open = true;
    target.scrollIntoView({ behavior: options.behavior || "smooth", block: "start" });
    return true;
  }

  document.querySelectorAll("[data-finance-close]").forEach((btn)=>{
    btn.addEventListener("click", ()=>{
      resetFinanceSection();
      financeSection?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  document.querySelectorAll("[data-open-section]").forEach((btn)=>{
    btn.addEventListener("click", ()=>{
      openAdminDetailsSection(btn.getAttribute("data-open-section"));
    });
  });
  document.addEventListener("click", (event)=>{
    const link = event.target.closest("[data-qonto-info-completion]");
    if(!link) return;
    const href = link.getAttribute("href") || "";
    const hash = href.includes("#") ? href.slice(href.indexOf("#") + 1) : "conventionFinancementSection";
    const samePage = !href || href.startsWith("#") || href.split("#")[0] === window.location.pathname;
    if(!samePage) return;
    event.preventDefault();
    document.querySelectorAll(".billing-modal-overlay").forEach((modal)=>modal.remove());
    currentLine = null;
    modalLoading = false;
    openAdminDetailsSection(hash || "conventionFinancementSection");
    if(hash) history.replaceState(null, "", `#${hash}`);
  });

  async function updateTrainee(payload){
  const saveIndicator = document.getElementById("financeSaveIndicator");
  if(saveIndicator){ saveIndicator.textContent = "Sauvegarde en cours…"; saveIndicator.className = "finance-save-indicator is-saving"; }
  try{
    const res = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/update`, {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    if(!res.ok || json.ok === false) throw new Error(json.error || json.message || "Erreur de sauvegarde");
    if(saveIndicator){ saveIndicator.textContent = "Sauvegardé"; saveIndicator.className = "finance-save-indicator is-saved"; }
    return json;
  }catch(error){
    if(saveIndicator){ saveIndicator.textContent = "Erreur de sauvegarde"; saveIndicator.className = "finance-save-indicator is-error"; }
    throw error;
  }
}

  const registrationCancelledCheckbox = document.getElementById("registrationCancelledCheckbox");
  const registrationCancelledControl = document.getElementById("registrationCancelledControl");
  const registrationCancelledBanner = document.getElementById("registrationCancelledBanner");
  const cancellationCalculatorButton = document.getElementById("btnCancellationCalculator");
  const cancellationCalculatorModal = document.getElementById("cancellationIndemnityModal");
  const cancellationCalculatorDate = document.getElementById("cancellationCalculatorDate");
  const cancellationCalculatorPrice = document.getElementById("cancellationCalculatorPrice");
  const cancellationCalculatorPaid = document.getElementById("cancellationCalculatorPaid");
  const cancellationCalculatorHours = document.getElementById("cancellationCalculatorHours");
  const cancellationCalculatorTotalHours = document.getElementById("cancellationCalculatorTotalHours");
  const cancellationCalculatorDeliveredHours = document.getElementById("cancellationCalculatorDeliveredHours");
  const cancellationCalculatorLoading = document.getElementById("cancellationCalculatorLoading");
  const cancellationCalculatorError = document.getElementById("cancellationCalculatorError");
  const cancellationCalculatorResult = document.getElementById("cancellationCalculatorResult");
  const copyCancellationCalculationButton = document.getElementById("btnCopyCancellationCalculation");
  const prepareCancellationEmailButton = document.getElementById("btnPrepareCancellationEmail");
  const cancellationEmailModal = document.getElementById("cancellationEmailModal");
  const cancellationEmailRecipient = document.getElementById("cancellationEmailRecipient");
  const cancellationEmailSubject = document.getElementById("cancellationEmailSubject");
  const cancellationEmailLoading = document.getElementById("cancellationEmailLoading");
  const cancellationEmailError = document.getElementById("cancellationEmailError");
  const cancellationEmailWarning = document.getElementById("cancellationEmailWarning");
  const cancellationEmailPreview = document.getElementById("cancellationEmailPreview");
  const cancellationEmailFrame = document.getElementById("cancellationEmailFrame");
  const backToCancellationCalculationButton = document.getElementById("btnBackToCancellationCalculation");
  const sendCancellationEmailButton = document.getElementById("btnSendCancellationEmail");
  const cancellationCalculatorEndpoint = sheetContext.cancellationUrl;
  const cancellationEmailPreviewEndpoint = sheetContext.cancellationPreviewUrl;
  const cancellationEmailSendEndpoint = sheetContext.cancellationSendUrl;
  const adminTraineeHero = document.getElementById("adminTraineeHero");
  const registrationCancellationReadOnly = sheetContext.readOnly;
  const cancellationMoneyFormatter = new Intl.NumberFormat("fr-FR", {style:"currency", currency:"EUR"});
  let currentCancellationCalculation = null;
  let currentCancellationEmailPreview = null;
  let cancellationCalculationTimer = null;
  let cancellationCalculationRequest = 0;

  function cancellationLocalIsoDate(){
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
  }

  function cancellationFormatMoney(cents){
    return cancellationMoneyFormatter.format(Number(cents || 0) / 100);
  }

  function cancellationFormatDate(isoDate){
    if(!isoDate) return "—";
    const parsed = new Date(`${isoDate}T12:00:00`);
    return Number.isNaN(parsed.getTime()) ? isoDate : parsed.toLocaleDateString("fr-FR");
  }

  function cancellationSetText(id, value){
    const node = document.getElementById(id);
    if(node) node.textContent = value;
  }

  function cancellationSetError(message){
    if(!cancellationCalculatorError) return;
    cancellationCalculatorError.textContent = message || "Le calcul est momentanément indisponible.";
    cancellationCalculatorError.hidden = false;
    if(cancellationCalculatorResult) cancellationCalculatorResult.hidden = true;
    if(copyCancellationCalculationButton) copyCancellationCalculationButton.disabled = true;
    if(prepareCancellationEmailButton) prepareCancellationEmailButton.disabled = true;
  }

  function renderCancellationCalculation(calculation){
    currentCancellationCalculation = calculation;
    if(cancellationCalculatorError) cancellationCalculatorError.hidden = true;
    if(cancellationCalculatorResult) cancellationCalculatorResult.hidden = false;
    if(cancellationCalculatorHours) cancellationCalculatorHours.hidden = !calculation.during_training;

    if(cancellationCalculatorPaid && cancellationCalculatorPaid.value === ""){
      cancellationCalculatorPaid.value = (Number(calculation.deductible_paid_cents || 0) / 100).toFixed(2);
    }
    if(cancellationCalculatorPrice && cancellationCalculatorPrice.value === ""){
      cancellationCalculatorPrice.value = (Number(calculation.training_price_cents || 0) / 100).toFixed(2);
    }
    if(cancellationCalculatorTotalHours && cancellationCalculatorTotalHours.value === "" && calculation.total_training_hours != null){
      cancellationCalculatorTotalHours.value = String(calculation.total_training_hours);
    }

    cancellationSetText("cancellationCalculatorRule", calculation.rule_label || "Règle contractuelle");
    const daysBefore = Number(calculation.days_before_start || 0);
    const timing = calculation.during_training
      ? (daysBefore === 0 ? "Le jour du démarrage" : `${Math.abs(daysBefore)} jour${Math.abs(daysBefore) > 1 ? "s" : ""} après le début`)
      : `${daysBefore} jour${daysBefore > 1 ? "s" : ""} avant le début`;
    cancellationSetText("cancellationCalculatorTiming", timing);
    cancellationSetText("cancellationCalculatorTrainingPrice", cancellationFormatMoney(calculation.training_price_cents));
    cancellationSetText("cancellationCalculatorCpf", cancellationFormatMoney(calculation.cpf_amount_cents));
    cancellationSetText("cancellationCalculatorPersonal", cancellationFormatMoney(calculation.personal_amount_cents));
    cancellationSetText("cancellationCalculatorOther", cancellationFormatMoney(calculation.other_amount_cents));
    cancellationSetText(
      "cancellationCalculatorCpfMeta",
      calculation.cpf_paid_cents > 0
        ? `${cancellationFormatMoney(calculation.cpf_paid_cents)} encaissé côté CPF · non déduit`
        : "Non déduit automatiquement"
    );
    cancellationSetText("cancellationCalculatorPersonalMeta", `${cancellationFormatMoney(calculation.personal_paid_cents)} déjà encaissé`);
    cancellationSetText(
      "cancellationCalculatorOtherMeta",
      calculation.other_paid_cents > 0
        ? `${cancellationFormatMoney(calculation.other_paid_cents)} encaissé · non déduit`
        : "Aucun encaissement détecté"
    );
    cancellationSetText("cancellationCalculatorPenaltyLabel", `Pénalité contractuelle (${Number(calculation.penalty_rate || 0)} %)`);
    cancellationSetText("cancellationCalculatorPenalty", cancellationFormatMoney(calculation.penalty_cents));
    const prorataRow = document.getElementById("cancellationCalculatorProrataRow");
    if(prorataRow) prorataRow.hidden = !calculation.during_training;
    cancellationSetText("cancellationCalculatorProrata", cancellationFormatMoney(calculation.prorata_cents));
    cancellationSetText("cancellationCalculatorTotalDue", cancellationFormatMoney(calculation.total_due_cents));
    cancellationSetText("cancellationCalculatorDeducted", `− ${cancellationFormatMoney(calculation.deductible_paid_cents)}`);

    const balance = document.getElementById("cancellationCalculatorBalance");
    balance?.classList.remove("is-settled", "is-refund");
    if(!calculation.calculation_complete){
      cancellationSetText("cancellationCalculatorBalanceLabel", "Minimum provisoire à réclamer");
      cancellationSetText("cancellationCalculatorBalanceAmount", cancellationFormatMoney(calculation.balance_due_cents));
    }else if(calculation.balance_status === "refund_due"){
      balance?.classList.add("is-refund");
      cancellationSetText("cancellationCalculatorBalanceLabel", "Somme à rembourser au stagiaire");
      cancellationSetText("cancellationCalculatorBalanceAmount", cancellationFormatMoney(calculation.refund_due_cents));
    }else if(calculation.balance_status === "settled"){
      balance?.classList.add("is-settled");
      cancellationSetText("cancellationCalculatorBalanceLabel", "Dossier soldé");
      cancellationSetText("cancellationCalculatorBalanceAmount", cancellationFormatMoney(0));
    }else{
      cancellationSetText("cancellationCalculatorBalanceLabel", "Solde à réclamer au stagiaire");
      cancellationSetText("cancellationCalculatorBalanceAmount", cancellationFormatMoney(calculation.balance_due_cents));
    }

    const warnings = [];
    if(!calculation.calculation_complete){
      warnings.push("Renseignez la durée totale et les heures effectivement dispensées pour intégrer le prorata de formation. Le montant affiché est seulement un minimum provisoire.");
    }
    if(Math.abs(Number(calculation.financing_gap_cents || 0)) > 1){
      warnings.push(`Les financements renseignés diffèrent du coût initial de ${cancellationFormatMoney(Math.abs(calculation.financing_gap_cents))}. Vérifiez les montants avant d’utiliser le résultat.`);
    }
    if(["financing", "default"].includes(calculation.training_price_source)){
      warnings.push("Le coût initial n’était pas enregistré sur le dossier : il a été prérempli automatiquement. Vérifiez-le dans le champ prévu avant d’utiliser le résultat.");
    }
    if(Number(calculation.cpf_paid_cents || 0) > 0 || Number(calculation.other_paid_cents || 0) > 0){
      warnings.push("Un encaissement CPF ou autre financeur a été détecté. Il est affiché mais n’est pas déduit automatiquement du solde dû par le stagiaire.");
    }
    if(calculation.cancellation_after_training){
      warnings.push("La date choisie est postérieure à la fin de formation : vérifiez manuellement la situation avant toute demande de paiement.");
    }
    const warningNode = document.getElementById("cancellationCalculatorWarning");
    if(warningNode){
      warningNode.textContent = warnings.join(" ");
      warningNode.hidden = warnings.length === 0;
    }
    if(copyCancellationCalculationButton) copyCancellationCalculationButton.disabled = !calculation.calculation_complete;
    if(prepareCancellationEmailButton){
      const recipient = String(document.getElementById("editEmail")?.value || cancellationEmailRecipient?.value || "").trim();
      prepareCancellationEmailButton.disabled = !calculation.calculation_complete || !recipient || registrationCancellationReadOnly;
      prepareCancellationEmailButton.title = recipient ? "Prévisualiser le mail avant envoi" : "Ajoutez d’abord l’adresse e-mail du stagiaire";
    }
  }

  async function refreshCancellationCalculation(){
    if(!cancellationCalculatorDate?.value) return;
    const requestNumber = ++cancellationCalculationRequest;
    if(cancellationCalculatorLoading) cancellationCalculatorLoading.hidden = !!currentCancellationCalculation;
    const params = new URLSearchParams({cancellation_date:cancellationCalculatorDate.value});
    if(cancellationCalculatorPrice?.value !== "") params.set("training_price_amount", cancellationCalculatorPrice.value);
    if(cancellationCalculatorPaid?.value !== "") params.set("deductible_paid_amount", cancellationCalculatorPaid.value);
    if(cancellationCalculatorTotalHours?.value !== "") params.set("total_training_hours", cancellationCalculatorTotalHours.value);
    if(cancellationCalculatorDeliveredHours?.value !== "") params.set("delivered_hours", cancellationCalculatorDeliveredHours.value);
    try{
      const response = await fetch(`${cancellationCalculatorEndpoint}?${params.toString()}`, {headers:{"Accept":"application/json"}});
      const payload = await response.json().catch(()=>({}));
      if(requestNumber !== cancellationCalculationRequest) return;
      if(!response.ok || payload.ok === false) throw new Error(payload.error || "Calcul impossible.");
      renderCancellationCalculation(payload.calculation || {});
    }catch(error){
      if(requestNumber !== cancellationCalculationRequest) return;
      cancellationSetError(error.message || "Calcul impossible.");
    }finally{
      if(requestNumber === cancellationCalculationRequest && cancellationCalculatorLoading) cancellationCalculatorLoading.hidden = true;
    }
  }

  function scheduleCancellationCalculation(){
    clearTimeout(cancellationCalculationTimer);
    cancellationCalculationTimer = setTimeout(refreshCancellationCalculation, 220);
  }

  function cancellationCalculationPayload(){
    const payload = {cancellation_date:cancellationCalculatorDate?.value || ""};
    if(cancellationCalculatorPrice?.value !== "") payload.training_price_amount = cancellationCalculatorPrice.value;
    if(cancellationCalculatorPaid?.value !== "") payload.deductible_paid_amount = cancellationCalculatorPaid.value;
    if(cancellationCalculatorTotalHours?.value !== "") payload.total_training_hours = cancellationCalculatorTotalHours.value;
    if(cancellationCalculatorDeliveredHours?.value !== "") payload.delivered_hours = cancellationCalculatorDeliveredHours.value;
    return payload;
  }

  cancellationCalculatorButton?.addEventListener("click", ()=>{
    if(cancellationCalculatorDate && !cancellationCalculatorDate.value){
      cancellationCalculatorDate.value = cancellationLocalIsoDate();
    }
    openModal("cancellationIndemnityModal");
    refreshCancellationCalculation();
  });
  if(window.location.hash === "#cancellationIndemnityModal" && cancellationCalculatorButton && !cancellationCalculatorButton.hidden){
    window.setTimeout(() => cancellationCalculatorButton.click(), 0);
  }
  [cancellationCalculatorDate, cancellationCalculatorPrice, cancellationCalculatorPaid, cancellationCalculatorTotalHours, cancellationCalculatorDeliveredHours].forEach((input)=>{
    input?.addEventListener("input", scheduleCancellationCalculation);
    input?.addEventListener("change", scheduleCancellationCalculation);
  });

  copyCancellationCalculationButton?.addEventListener("click", async ()=>{
    const calculation = currentCancellationCalculation;
    if(!calculation || !calculation.calculation_complete) return;
    const summary = [
      `Date d’annulation : ${cancellationFormatDate(calculation.cancellation_date)}`,
      `Coût total initial de la formation : ${cancellationFormatMoney(calculation.training_price_cents)}`,
      `Financement Compte Personnel de Formation (CPF) : ${cancellationFormatMoney(calculation.cpf_amount_cents)}`,
      `Financement personnel prévu : ${cancellationFormatMoney(calculation.personal_amount_cents)}`,
      `Somme déjà versée retenue : ${cancellationFormatMoney(calculation.deductible_paid_cents)}`,
      `Pénalité financière appliquée : ${cancellationFormatMoney(calculation.penalty_cents)} (${Number(calculation.penalty_rate || 0)} % du coût initial)`,
      ...(calculation.during_training ? [`Prestations effectivement dispensées : ${cancellationFormatMoney(calculation.prorata_cents)} (${calculation.delivered_hours || 0} h sur ${calculation.total_training_hours || 0} h)`] : []),
      calculation.balance_status === "refund_due"
        ? `Somme à rembourser : ${cancellationFormatMoney(calculation.refund_due_cents)}`
        : `Solde à régler : ${cancellationFormatMoney(calculation.balance_due_cents)}`,
    ].join("\n");
    try{
      await navigator.clipboard.writeText(summary);
    }catch(error){
      const textarea = document.createElement("textarea");
      textarea.value = summary;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    const original = copyCancellationCalculationButton.textContent;
    copyCancellationCalculationButton.textContent = "Récapitulatif copié ✓";
    setTimeout(()=>{ copyCancellationCalculationButton.textContent = original; }, 1800);
  });

  function resetCancellationEmailPreview(){
    currentCancellationEmailPreview = null;
    if(cancellationEmailLoading) cancellationEmailLoading.hidden = false;
    if(cancellationEmailError){
      cancellationEmailError.hidden = true;
      cancellationEmailError.textContent = "";
    }
    if(cancellationEmailWarning){
      cancellationEmailWarning.hidden = true;
      cancellationEmailWarning.textContent = "";
    }
    if(cancellationEmailPreview) cancellationEmailPreview.hidden = true;
    if(cancellationEmailFrame) cancellationEmailFrame.srcdoc = "";
    if(cancellationEmailSubject) cancellationEmailSubject.value = "";
    if(sendCancellationEmailButton) sendCancellationEmailButton.disabled = true;
  }

  function showCancellationEmailError(message){
    if(cancellationEmailLoading) cancellationEmailLoading.hidden = true;
    if(cancellationEmailPreview) cancellationEmailPreview.hidden = true;
    if(cancellationEmailError){
      cancellationEmailError.textContent = message || "Le mail n’a pas pu être préparé.";
      cancellationEmailError.hidden = false;
    }
    if(sendCancellationEmailButton) sendCancellationEmailButton.disabled = true;
  }

  prepareCancellationEmailButton?.addEventListener("click", async ()=>{
    if(!currentCancellationCalculation?.calculation_complete) return;
    resetCancellationEmailPreview();
    const currentRecipient = String(document.getElementById("editEmail")?.value || cancellationEmailRecipient?.value || "").trim();
    if(cancellationEmailRecipient) cancellationEmailRecipient.value = currentRecipient;
    closeModal("cancellationIndemnityModal");
    openModal("cancellationEmailModal");
    try{
      const response = await fetch(cancellationEmailPreviewEndpoint, {
        method:"POST",
        headers:{"Accept":"application/json", "Content-Type":"application/json"},
        body:JSON.stringify(cancellationCalculationPayload()),
      });
      const payload = await response.json().catch(()=>({}));
      if(!response.ok || payload.ok === false) throw new Error(payload.error || "Le mail n’a pas pu être préparé.");
      currentCancellationEmailPreview = payload;
      if(cancellationEmailRecipient) cancellationEmailRecipient.value = payload.recipient || currentRecipient;
      if(cancellationEmailSubject) cancellationEmailSubject.value = payload.subject || "";
      if(cancellationEmailFrame) cancellationEmailFrame.srcdoc = payload.html || "";
      const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
      if(cancellationEmailWarning){
        cancellationEmailWarning.textContent = warnings.join(" ");
        cancellationEmailWarning.hidden = warnings.length === 0;
      }
      if(cancellationEmailLoading) cancellationEmailLoading.hidden = true;
      if(cancellationEmailPreview) cancellationEmailPreview.hidden = false;
      if(sendCancellationEmailButton) sendCancellationEmailButton.disabled = registrationCancellationReadOnly;
    }catch(error){
      showCancellationEmailError(error.message || "Le mail n’a pas pu être préparé.");
    }
  });

  backToCancellationCalculationButton?.addEventListener("click", ()=>{
    closeModal("cancellationEmailModal");
    openModal("cancellationIndemnityModal");
  });

  sendCancellationEmailButton?.addEventListener("click", async ()=>{
    if(!currentCancellationEmailPreview || registrationCancellationReadOnly) return;
    const originalLabel = sendCancellationEmailButton.textContent;
    sendCancellationEmailButton.disabled = true;
    sendCancellationEmailButton.textContent = "Envoi en cours…";
    if(cancellationEmailError) cancellationEmailError.hidden = true;
    try{
      const response = await fetch(cancellationEmailSendEndpoint, {
        method:"POST",
        headers:{"Accept":"application/json", "Content-Type":"application/json"},
        body:JSON.stringify(cancellationCalculationPayload()),
      });
      const payload = await response.json().catch(()=>({}));
      if(!response.ok || payload.ok === false) throw new Error(payload.error || "Le mail n’a pas pu être envoyé.");
      closeModal("cancellationEmailModal");
      window.showMailSentBadge?.();
      const successMessage = `Le mail d’annulation a bien été envoyé à ${payload.recipient || cancellationEmailRecipient?.value || "la personne"}.`;
      if(window.AppModal){
        await window.AppModal.alert(successMessage, {type:"success", title:"Mail envoyé", primaryText:"Fermer"});
      }else{
        window.alert(successMessage);
      }
      window.location.reload();
    }catch(error){
      if(cancellationEmailError){
        cancellationEmailError.textContent = error.message || "Le mail n’a pas pu être envoyé.";
        cancellationEmailError.hidden = false;
      }
      sendCancellationEmailButton.disabled = false;
    }finally{
      sendCancellationEmailButton.textContent = originalLabel;
    }
  });

  function renderRegistrationCancellation(cancelled){
    if(registrationCancelledCheckbox) registrationCancelledCheckbox.checked = cancelled;
    registrationCancelledControl?.classList.toggle("is-cancelled", cancelled);
    adminTraineeHero?.classList.toggle("is-registration-cancelled", cancelled);
    if(registrationCancelledBanner) registrationCancelledBanner.hidden = !cancelled;
    if(cancellationCalculatorButton) cancellationCalculatorButton.hidden = !cancelled;
    if(!cancelled && cancellationCalculatorModal?.classList.contains("show")){
      closeModal("cancellationIndemnityModal");
    }
    if(!cancelled && cancellationEmailModal?.classList.contains("show")){
      closeModal("cancellationEmailModal");
    }
  }

  registrationCancelledCheckbox?.addEventListener("change", async ()=>{
    const previous = !registrationCancelledCheckbox.checked;
    const next = registrationCancelledCheckbox.checked;
    const message = next
      ? "Confirmer l’annulation de cette inscription ? Le dossier sera conservé, la personne ne comptera plus dans les indicateurs et toutes les automatisations seront désactivées."
      : "Réactiver cette inscription ? La personne sera de nouveau comptabilisée dans les effectifs, les ventes et les KPI.";
    if(!window.confirm(message)){
      renderRegistrationCancellation(previous);
      return;
    }

    registrationCancelledCheckbox.disabled = true;
    try{
      const result = await updateTrainee({ registration_cancelled: next });
      renderRegistrationCancellation(Boolean(result.registration_cancelled));
      window.location.reload();
    }catch(error){
      renderRegistrationCancellation(previous);
      window.alert("La modification du statut d’inscription n’a pas pu être enregistrée.");
    }finally{
      registrationCancelledCheckbox.disabled = registrationCancellationReadOnly;
    }
  });

  const contactDebounce = {};

  function setupContactAutosave({ inputId, field }){
    const input = document.getElementById(inputId);
    if(!input) return;

    input.addEventListener("input", ()=>{
      const value = input.value;

      if(contactDebounce[field]) clearTimeout(contactDebounce[field]);
      contactDebounce[field] = setTimeout(async ()=>{
        try{
          await updateTrainee({ [field]: value });
        }catch(e){
          console.error("Erreur sauvegarde contact", field);
        }
      }, 450);
    });
  }

  setupContactAutosave({
    inputId: "editLastName",
    field: "last_name"
  });
  setupContactAutosave({
    inputId: "editFirstName",
    field: "first_name"
  });
  setupContactAutosave({
    inputId: "editEmail",
    field: "email"
  });
  setupContactAutosave({
    inputId: "editPhone",
    field: "phone"
  });
  setupContactAutosave({
    inputId: "editSsiapExamDate",
    field: "ssiap_exam_date"
  });
  setupContactAutosave({
    inputId: "editVtcCmarId",
    field: "vtc_cmar_id"
  });
  setupContactAutosave({
    inputId: "editVtcRealTrainingDates",
    field: "vtc_real_training_dates"
  });
  setupContactAutosave({
    inputId: "editApsElearningLogin",
    field: "aps_elearning_login"
  });
  setupContactAutosave({
    inputId: "editApsElearningPassword",
    field: "aps_elearning_password"
  });

  const elearningInput = document.getElementById("editElearningLink");
  const elearningSaveHint = document.getElementById("elearningSaveHint");
  if(elearningInput){
    elearningInput.addEventListener("change", async ()=>{
      try{
        const linkValue = (elearningInput.value || "").trim();
        let sendElearningNotification = false;
        if(linkValue){
          sendElearningNotification = await window.confirmMailSmsSend?.();
        }
        const result = await updateTrainee({
          elearning_link: linkValue,
          send_elearning_notification: !!sendElearningNotification,
        });
        if(!elearningSaveHint) return;
        const sentAt = (result && result.elearning_link_sent_at) ? result.elearning_link_sent_at : "";
        if(!sentAt){
          elearningSaveHint.style.display = "none";
          elearningSaveHint.innerHTML = "";
          return;
        }
        const flags = [];
        if(result.elearning_link_email_ok) flags.push("📧 Email envoyé");
        if(result.elearning_link_sms_ok) flags.push("📱 SMS envoyé");
        elearningSaveHint.style.display = "block";
        elearningSaveHint.innerHTML = `✅ Notification e-learning envoyée (${flags.join(" • ") || "envoi en cours"})`;
      }catch(e){
        console.error("Erreur sauvegarde lien e-learning");
      }
    });
  }

  const editVtcCmLogin = document.getElementById("editVtcCmLogin");
  const editVtcCmPassword = document.getElementById("editVtcCmPassword");
  const vtcCredentialsAdminHint = document.getElementById("vtcCredentialsAdminHint");

  const showVtcAdminHint = (text, isError=false) => {
    if(!vtcCredentialsAdminHint) return;
    vtcCredentialsAdminHint.style.display = "block";
    vtcCredentialsAdminHint.style.color = isError ? "#b91c1c" : "#15803d";
    vtcCredentialsAdminHint.textContent = text;
  };

  const saveVtcCredentialsFromAdmin = () => {
    if(contactDebounce.vtc_credentials) clearTimeout(contactDebounce.vtc_credentials);
    contactDebounce.vtc_credentials = setTimeout(async ()=>{
      try{
        const login = (editVtcCmLogin?.value || "").trim();
        const password = (editVtcCmPassword?.value || "").trim();
        const payload = {
          vtc_cm_login: login,
          vtc_cm_password: password,
        };
        if(login && password){
          payload.vtc_cm_submitted_at = new Date().toISOString();
        }
        await updateTrainee(payload);
        showVtcAdminHint("✅ Identifiants Chambre des métiers enregistrés.");
      }catch(e){
        showVtcAdminHint("Erreur sauvegarde identifiants Chambre des métiers.", true);
      }
    }, 450);
  };

  [editVtcCmLogin, editVtcCmPassword].forEach((input)=>{
    if(!input) return;
    input.addEventListener("input", saveVtcCredentialsFromAdmin);
  });

  const btnOpenBookModal = document.getElementById("btnOpenBookModal");
  const btnBookSent = document.getElementById("btnBookSent");
  const bookSentHint = document.getElementById("bookSentHint");
  const bookSentInlineHint = document.getElementById("bookSentInlineHint");
  if(btnOpenBookModal){
    btnOpenBookModal.addEventListener("click", ()=>openModal("bookSentModal"));
  }
  if(btnBookSent){
    btnBookSent.addEventListener("click", async ()=>{
      if(btnBookSent.disabled) return;
      btnBookSent.disabled = true;
      btnBookSent.textContent = "Enregistrement...";
      try{
        const nowIso = new Date().toISOString();
        await updateTrainee({ vtc_book_sent_at: nowIso });
        const nowFr = new Date(nowIso).toLocaleDateString("fr-FR");
        if(bookSentHint){
          bookSentHint.style.display = "block";
          bookSentHint.innerHTML = `✅ Livre VTC envoyé le ${nowFr}`;
        }
        if(bookSentInlineHint){
          bookSentInlineHint.style.display = "block";
          bookSentInlineHint.innerHTML = `✅ Livre VTC envoyé le <strong>${nowFr}</strong>`;
        }
        if(!bookSentInlineHint){
          const host = btnOpenBookModal?.parentElement;
          if(host){
            const line = document.createElement("div");
            line.id = "bookSentInlineHint";
            line.className = "hint";
            line.style.marginTop = "8px";
            line.innerHTML = `✅ Livre VTC envoyé le <strong>${nowFr}</strong>`;
            host.insertAdjacentElement("afterend", line);
          }
        }
        btnBookSent.classList.remove("btn-primary");
        btnBookSent.classList.add("btn-disabled-muted");
        btnBookSent.textContent = "Livre envoyé";
        if(btnOpenBookModal){
          btnOpenBookModal.disabled = true;
          btnOpenBookModal.classList.remove("btn-orange", "btn-vtc-book-ready");
          btnOpenBookModal.classList.add("btn-disabled-muted");
        }
      }catch(e){
        btnBookSent.disabled = false;
        btnBookSent.textContent = "Livre envoyé";
        alert("Erreur lors de l'enregistrement de l'envoi du livre.");
      }
    });
  }

const chkHideInfos = document.getElementById("chkHideInfos");
if(chkHideInfos){
  chkHideInfos.addEventListener("change", async ()=>{
    try{
      await updateTrainee({ public_hide_infos: chkHideInfos.checked });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde visibilité infos");
    }
  });
}

const chkHideDocs = document.getElementById("chkHideDocs");
if(chkHideDocs){
  chkHideDocs.addEventListener("change", async ()=>{
    try{
      await updateTrainee({ public_hide_docs: chkHideDocs.checked });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde visibilité documents");
    }
  });
}

const chkScotiaForceVisible = document.getElementById("chkScotiaForceVisible");
if(chkScotiaForceVisible){
  chkScotiaForceVisible.addEventListener("change", async ()=>{
    try{
      await updateTrainee({ scotia_force_visible: chkScotiaForceVisible.checked });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde visibilité page Scotia");
    }
  });
}


  const chkHideSuivi = document.getElementById("public_hide_suivi");
  if(chkHideSuivi){
  chkHideSuivi.addEventListener("change", async ()=>{
    try{
      await updateTrainee({ public_hide_suivi: chkHideSuivi.checked });
      window.location.reload();
    }catch(e){
      alert("Erreur sauvegarde visibilité suivi dossier");
    }
  });
}

const chkExamFeesPaid = document.getElementById("chkExamFeesPaid");
const examFeesPaidHint = document.getElementById("examFeesPaidHint");
const formatDateFr = (d) => {
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}/${mm}/${yyyy}`;
};

if(chkExamFeesPaid){
  chkExamFeesPaid.addEventListener("change", async ()=>{
    try{
      let sendExamFeesNotification = false;
      const isDirigeantVae = sheetContext.showVae;
      if(chkExamFeesPaid.checked){
        if(isDirigeantVae){
          const currentCmarId = (document.getElementById("editVtcCmarId")?.value || "").trim();
          const providedCmarId = window.prompt("Paiement des frais d'examen coché. Merci de saisir l'identifiant CMAR :", currentCmarId);
          if(providedCmarId === null){
            chkExamFeesPaid.checked = false;
            return;
          }
          const normalizedCmarId = providedCmarId.trim();
          if(!normalizedCmarId){
            window.alert("L'identifiant CMAR est obligatoire pour valider le paiement des frais d'examen.");
            chkExamFeesPaid.checked = false;
            return;
          }
          const cmarInput = document.getElementById("editVtcCmarId");
          if(cmarInput) cmarInput.value = normalizedCmarId;
          await updateTrainee({ vtc_cmar_id: normalizedCmarId });
        }
        sendExamFeesNotification = await window.confirmMailSmsSend?.();
      }
      await updateTrainee({
        exam_fees_paid: chkExamFeesPaid.checked,
        send_exam_fees_notification: !!sendExamFeesNotification,
      });
      if(examFeesPaidHint){
        if(chkExamFeesPaid.checked){
          examFeesPaidHint.style.display = "block";
          examFeesPaidHint.innerHTML = `Frais d'examen réglés le <strong>${formatDateFr(new Date())}</strong>`;
        }else{
          examFeesPaidHint.style.display = "none";
          examFeesPaidHint.innerHTML = "";
        }
      }
    }catch(e){
      alert("Erreur sauvegarde paiement frais d'examen");
    }
  });
}

const btnVtcTheoryExam = document.getElementById("btnVtcTheoryExam");
const btnVtcTheoryRetake = document.getElementById("btnVtcTheoryRetake");
const btnVtcTheoryExamUndo = document.getElementById("btnVtcTheoryExamUndo");
const btnVtcPracticeConvocation = document.getElementById("btnVtcPracticeConvocation");
const btnVtcPracticeConvocationUndo = document.getElementById("btnVtcPracticeConvocationUndo");
const btnVtcPracticeExamSuccess = document.getElementById("btnVtcPracticeExamSuccess");
const btnVtcPracticeExamSuccessUndo = document.getElementById("btnVtcPracticeExamSuccessUndo");
const vtcStatusHint = document.getElementById("vtcStatusHint");

const vtcStatusState = {
  theory: {
    sentAt: sheetContext.theorySent,
    emailOk: sheetContext.theoryEmailOk,
    smsOk: sheetContext.theorySmsOk,
  },
  practiceConvocation: {
    sentAt: sheetContext.practiceConvocationSent,
  },
  practiceExam: {
    sentAt: sheetContext.practiceSent,
    emailOk: sheetContext.practiceEmailOk,
    smsOk: sheetContext.practiceSmsOk,
  },
  failures: {
    theory: sheetContext.theoryFailed,
    practice: sheetContext.practiceFailed,
  },
  retakeTheory: sheetContext.retakingTheory,
};

const setStepValidatedUi = (btn, undoBtn, isValidated) => {
  if(btn){
    btn.classList.toggle("btn-primary", isValidated);
    btn.classList.toggle("btn-outline", !isValidated);
    btn.disabled = isValidated;
  }
  if(undoBtn){
    undoBtn.style.display = isValidated ? "" : "none";
  }
};

const renderVtcStatus = () => {
  setStepValidatedUi(btnVtcTheoryExam, btnVtcTheoryExamUndo, vtcStatusState.theory.sentAt);
  setStepValidatedUi(btnVtcPracticeConvocation, btnVtcPracticeConvocationUndo, vtcStatusState.practiceConvocation.sentAt);
  setStepValidatedUi(btnVtcPracticeExamSuccess, btnVtcPracticeExamSuccessUndo, vtcStatusState.practiceExam.sentAt);
  if(btnVtcTheoryRetake){
    btnVtcTheoryRetake.style.display = vtcStatusState.failures.theory ? "" : "none";
  }

  if(!vtcStatusHint) return;

  const lines = [];
  if(vtcStatusState.failures.theory) lines.push("<div>❌ Échec examen théorique</div>");
  else if(vtcStatusState.retakeTheory) lines.push("<div>🟡 Repassage examen théorique</div>");

  if(vtcStatusState.theory.sentAt){
    const emailFlag = vtcStatusState.theory.emailOk ? '<span style="margin-left:8px;">📧 Email envoyé</span>' : '<span style="margin-left:8px;">📧 Email non envoyé</span>';

const smsFlag = vtcStatusState.theory.smsOk ? '<span style="margin-left:8px;">📱 SMS envoyé</span>' : '<span style="margin-left:8px;">📱 SMS non envoyé</span>';
    lines.push(`✅ Examen théorique validé ${emailFlag}${smsFlag}`);
  }

  if(vtcStatusState.practiceConvocation.sentAt){
    lines.push("<div>✅ Convocation formation pratique validée</div>");
  }

  if(vtcStatusState.practiceExam.sentAt){
    const emailFlag = vtcStatusState.practiceExam.emailOk ? '<span style="margin-left:8px;">📧 Email envoyé</span>' : '<span style="margin-left:8px;">📧 Email non envoyé</span>';
    const smsFlag = vtcStatusState.practiceExam.smsOk ? '<span style="margin-left:8px;">📱 SMS envoyé</span>' : '<span style="margin-left:8px;">📱 SMS non envoyé</span>';
    lines.push(`<div>✅ Examen pratique validé ${emailFlag}${smsFlag}</div>`);
  }

  if(vtcStatusState.failures.practice) lines.push("<div>❌ Échec examen pratique</div>");

  if(lines.length){
    vtcStatusHint.style.display = "block";
    vtcStatusHint.innerHTML = lines.join("<br>");
  }else{
    vtcStatusHint.style.display = "none";
    vtcStatusHint.innerHTML = "";
  }
};

if(btnVtcTheoryExam){
  btnVtcTheoryExam.addEventListener("click", async ()=>{
    if(btnVtcTheoryExam.disabled) return;
    const sendMail = await window.confirmMailSmsSend?.();
    try{
      btnVtcTheoryExam.disabled = true;
      const r = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/vtc-theory-exam/send`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ send_notifications: !!sendMail }),
      });
      const data = await r.json();
      if(!r.ok || !data.ok){
        throw new Error(data.error || "send_failed");
      }

      vtcStatusState.theory.sentAt = true;
      vtcStatusState.theory.emailOk = !!data.email_ok;
      vtcStatusState.theory.smsOk = !!data.sms_ok;
      vtcStatusState.retakeTheory = false;
      renderVtcStatus();
    }catch(e){
      btnVtcTheoryExam.disabled = false;
      alert("Erreur lors de l'envoi de la convocation formation pratique.");
    }
  });
}

if(btnVtcTheoryRetake){
  btnVtcTheoryRetake.addEventListener("click", async ()=>{
    const ok = window.confirm("Passer en statut \"Repassage examen théorique\" ?");
    if(!ok) return;
    try{
      btnVtcTheoryRetake.disabled = true;
      const res = await updateTrainee({
        vtc_theory_result: "",
        vtc_theory_result_label: "repassage examen théorique",
      });
      if(!res || res.ok === false) throw new Error("save_failed");
      vtcStatusState.failures.theory = false;
      vtcStatusState.retakeTheory = true;
      renderVtcStatus();
    }catch(e){
      alert("Erreur lors du passage en repassage théorie.");
    }finally{
      btnVtcTheoryRetake.disabled = false;
    }
  });
}

if(btnVtcTheoryExamUndo){
  btnVtcTheoryExamUndo.addEventListener("click", async ()=>{
    const ok = window.confirm("Dévalider l'étape \"Examen théorique\" ?");
    if(!ok) return;
    try{
      btnVtcTheoryExamUndo.disabled = true;
      const res = await updateTrainee({
        vtc_theory_exam_sent_at: "",
        vtc_theory_exam_email_ok: false,
        vtc_theory_exam_sms_ok: false,
      });
      if(!res || res.ok === false) throw new Error("save_failed");
      vtcStatusState.theory.sentAt = false;
      vtcStatusState.theory.emailOk = false;
      vtcStatusState.theory.smsOk = false;
      renderVtcStatus();
    }catch(e){
      alert("Erreur lors de la dévalidation de l'examen théorique.");
    }finally{
      btnVtcTheoryExamUndo.disabled = false;
    }
  });
}

if(btnVtcPracticeConvocation){
  btnVtcPracticeConvocation.addEventListener("click", async ()=>{
    if(btnVtcPracticeConvocation.disabled) return;
    try{
      btnVtcPracticeConvocation.disabled = true;
      const res = await updateTrainee({ vtc_practice_convocation_sent_at: new Date().toISOString() });
      if(!res || res.ok === false){
        throw new Error("save_failed");
      }
      vtcStatusState.practiceConvocation.sentAt = true;
      renderVtcStatus();
    }catch(e){
      btnVtcPracticeConvocation.disabled = false;
      alert("Erreur lors de la sauvegarde du statut VTC.");
    }
  });
}

if(btnVtcPracticeConvocationUndo){
  btnVtcPracticeConvocationUndo.addEventListener("click", async ()=>{
    const ok = window.confirm("Dévalider l'étape \"Convocation formation pratique\" ?");
    if(!ok) return;
    try{
      btnVtcPracticeConvocationUndo.disabled = true;
      const res = await updateTrainee({ vtc_practice_convocation_sent_at: "" });
      if(!res || res.ok === false) throw new Error("save_failed");
      vtcStatusState.practiceConvocation.sentAt = false;
      renderVtcStatus();
    }catch(e){
      alert("Erreur lors de la dévalidation de la convocation formation pratique.");
    }finally{
      btnVtcPracticeConvocationUndo.disabled = false;
    }
  });
}

if(btnVtcPracticeExamSuccess){
  btnVtcPracticeExamSuccess.addEventListener("click", async ()=>{
    if(btnVtcPracticeExamSuccess.disabled) return;
    try{
      btnVtcPracticeExamSuccess.disabled = true;
      const r = await fetch(`/api/sessions/${sheetContext.sessionId}/stagiaires/${sheetContext.traineeId}/vtc-practice-exam-success/send`, {
        method: "POST",
        headers: {"Content-Type": "application/json"}
      });
      const data = await r.json();
      if(!r.ok || !data.ok){
        throw new Error(data.error || "send_failed");
      }
      vtcStatusState.practiceExam.sentAt = true;
      vtcStatusState.practiceExam.emailOk = !!data.email_ok;
      vtcStatusState.practiceExam.smsOk = !!data.sms_ok;
      renderVtcStatus();
    }catch(e){
      btnVtcPracticeExamSuccess.disabled = false;
      alert("Erreur lors de l'envoi de la notification examen pratique.");
    }
  });
}

if(btnVtcPracticeExamSuccessUndo){
  btnVtcPracticeExamSuccessUndo.addEventListener("click", async ()=>{
    const ok = window.confirm("Dévalider l'étape \"Examen pratique\" ?");
    if(!ok) return;
    try{
      btnVtcPracticeExamSuccessUndo.disabled = true;
      const res = await updateTrainee({
        vtc_practice_exam_sent_at: "",
        vtc_practice_exam_email_ok: false,
        vtc_practice_exam_sms_ok: false,
        vtc_practice_result: "",
        vtc_practice_result_label: "",
      });
      if(!res || res.ok === false) throw new Error("save_failed");
      vtcStatusState.practiceExam.sentAt = false;
      vtcStatusState.practiceExam.emailOk = false;
      vtcStatusState.practiceExam.smsOk = false;
      renderVtcStatus();
    }catch(e){
      alert("Erreur lors de la dévalidation de l'examen pratique.");
    }finally{
      btnVtcPracticeExamSuccessUndo.disabled = false;
    }
  });
}

renderVtcStatus();

const btnEtiquetteWord = document.getElementById("btnEtiquetteWord");
if(btnEtiquetteWord){
  btnEtiquetteWord.addEventListener("click", (e)=>{
    if(btnEtiquetteWord.dataset.downloaded !== "1") return;
    const ok = window.confirm("Vous avez déjà ouvert l'étiquette WORD, voulez-vous continuer ?");
    if(!ok){
      e.preventDefault();
    }
  });
}
document.querySelectorAll("[data-learning-summary]").forEach(section => {
  let loaded = false, pending = false;
  section.addEventListener("toggle", async () => {
    if (!section.open || loaded || pending) return;
    const content = section.querySelector("[data-summary-content]");
    content.textContent = "Chargement du suivi…";
    pending = true;
    try {
      const response = await fetch(section.dataset.learningSummary, {headers: {Accept: "text/html"}});
      if (!response.ok || response.redirected) throw new Error();
      content.innerHTML = await response.text();
      loaded = true;
    } catch {
      content.textContent = "Le suivi est indisponible. Rouvrez la rubrique pour réessayer.";
    } finally {
      pending = false;
    }
  });
});

// All convention entry points use the same type, finance and signature flow.
if(new URLSearchParams(window.location.search).get("preparer_convention") === "1"){
  const prepareConvention = ()=>{
    const url = new URL(window.location.href);
    url.searchParams.delete("preparer_convention");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    const form = document.querySelector('form[data-convention-transmission-form="true"]');
    const submit = form?.querySelector('button[type="submit"]');
    if(form && submit && !submit.disabled){
      for(let parent = form.parentElement; parent; parent = parent.parentElement){
        if(parent.tagName === "DETAILS") parent.open = true;
      }
      requestAnimationFrame(()=>form.requestSubmit());
    }
  };
  // The shared dialogs/functions are rendered later by base.html.
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", prepareConvention, {once:true});
  else prepareConvention();
}
