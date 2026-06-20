(() => {
  const modal = document.getElementById("professionalExperienceModal");
  const form = document.getElementById("professionalExperienceForm");
  if (!modal || !form) return;
  const experiences = document.getElementById("professionalExperiences");
  const template = document.getElementById("professionalExperienceTemplate");
  const addButton = document.getElementById("addProfessionalExperience");
  const limit = document.getElementById("professionalExperienceLimit");
  const message = document.getElementById("professionalExperienceMessage");
  const signature = document.getElementById("professionalSignaturePreview");
  const syncProgress = document.getElementById("professionalExperienceSyncProgress");
  let previouslyFocused = null;

  const open = () => {
    previouslyFocused = document.activeElement;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("pro-sheet-open");
    modal.querySelector(".pro-sheet-close")?.focus();
  };
  const setSyncProgress = visible => {
    syncProgress?.classList.toggle("is-visible", visible);
    syncProgress?.setAttribute("aria-hidden", visible ? "false" : "true");
    modal.classList.toggle("is-transmitting", visible);
  };
  const close = () => {
    setSyncProgress(false);
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("pro-sheet-open");
    previouslyFocused?.focus?.();
  };
  document.querySelectorAll("[data-pro-sheet-open]").forEach(button => button.addEventListener("click", open));
  modal.querySelectorAll("[data-pro-sheet-close]").forEach(button => button.addEventListener("click", close));
  document.addEventListener("keydown", event => { if (event.key === "Escape" && modal.classList.contains("is-open")) close(); });

  const selected = name => form.querySelector(`input[name="${name}"]:checked`)?.value || "";
  const updateConditionals = () => {
    form.querySelectorAll("[data-show-when]").forEach(field => {
      const [name, value] = field.dataset.showWhen.split(":");
      const visible = selected(name) === value;
      field.classList.toggle("is-visible", visible);
      const input = field.querySelector("input");
      if (input) input.required = visible;
    });
    experiences.querySelectorAll(".pro-sheet-experience").forEach(card => {
      const contract = card.querySelector('[data-field="contract_type"]:checked')?.value || "";
      const field = card.querySelector("[data-experience-show-when]");
      field?.classList.toggle("is-visible", contract === "other");
      const otherInput = field?.querySelector('[data-field="contract_other"]');
      if (otherInput) otherInput.required = contract === "other";
    });
  };

  const renumber = () => {
    [...experiences.children].forEach((card, index) => {
      card.dataset.experienceIndex = index;
      card.querySelector("h4 span").textContent = index + 1;
      card.querySelectorAll('[data-field="contract_type"]').forEach(input => input.name = `contract_type_${index}`);
      card.querySelectorAll('[data-field="executive_status"]').forEach(input => input.name = `executive_status_${index}`);
    });
    const full = experiences.children.length >= 5;
    addButton.disabled = full;
    limit.hidden = !full;
  };

  addButton.addEventListener("click", () => {
    if (experiences.children.length >= 5) return;
    experiences.appendChild(template.content.cloneNode(true));
    renumber();
    experiences.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  experiences.addEventListener("click", event => {
    const remove = event.target.closest(".pro-sheet-remove");
    if (!remove || experiences.children.length === 1) return;
    remove.closest(".pro-sheet-experience").remove();
    renumber();
  });
  form.addEventListener("change", updateConditionals);
  form.querySelector('[name="validation_name"]')?.addEventListener("input", event => { signature.textContent = event.target.value.trim() || "Votre signature"; });

  const clearErrors = () => {
    form.querySelectorAll(".has-error").forEach(element => element.classList.remove("has-error"));
    form.querySelectorAll(".pro-sheet-error").forEach(element => element.textContent = "");
    message.className = "pro-sheet-message";
    message.textContent = "";
  };
  const setError = (element, text) => {
    const wrapper = element?.closest(".pro-sheet-field, .pro-sheet-fieldset");
    wrapper?.classList.add("has-error");
    const error = wrapper?.querySelector(".pro-sheet-error");
    if (error) error.textContent = text;
  };
  const validate = () => {
    clearErrors();
    let valid = true;
    [["current_situation", "Sélectionnez votre situation actuelle."], ["qualification_level", "Sélectionnez votre niveau de qualification."]].forEach(([name, text]) => {
      if (!selected(name)) { setError(form.querySelector(`[name="${name}"]`), text); valid = false; }
    });
    form.querySelectorAll("input[required]").forEach(input => {
      if ((input.type === "checkbox" && !input.checked) || (input.type !== "radio" && !input.value.trim())) {
        if (input.name === "certified") {
          const error = form.querySelector('[data-error-for="certified"]');
          if (error) error.textContent = "Vous devez certifier l’exactitude des informations.";
        } else setError(input, "Ce champ est obligatoire.");
        valid = false;
      }
    });
    experiences.querySelectorAll('[data-field="work_time_percent"]').forEach(input => {
      if (input.value && (+input.value < 0 || +input.value > 100)) { setError(input, "Indiquez une valeur entre 0 et 100."); valid = false; }
    });
    experiences.querySelectorAll(".pro-sheet-experience").forEach(card => {
      const contractField = card.querySelector('[data-field="contract_type"]');
      const executiveField = card.querySelector('[data-field="executive_status"]');
      if (!card.querySelector('[data-field="contract_type"]:checked')) {
        setError(contractField, "Sélectionnez le type de contrat.");
        valid = false;
      }
      if (!card.querySelector('[data-field="executive_status"]:checked')) {
        setError(executiveField, "Sélectionnez le statut cadre.");
        valid = false;
      }
      if (card.querySelector('[data-field="contract_type"]:checked')?.value === "other") {
        const other = card.querySelector('[data-field="contract_other"]');
        if (!other.value.trim()) { setError(other, "Précisez le type de contrat."); valid = false; }
      }
    });
    if (!valid) form.querySelector(".has-error, [data-error-for='certified']")?.scrollIntoView({ behavior: "smooth", block: "center" });
    return valid;
  };
  const experiencePayload = card => {
    const value = field => card.querySelector(`[data-field="${field}"]`)?.value?.trim() || "";
    return {
      job_title: value("job_title"), company_name: value("company_name"), start_date: value("start_date"), end_date: value("end_date"),
      work_time_percent: value("work_time_percent"), contract_type: card.querySelector('[data-field="contract_type"]:checked')?.value || "",
      contract_other: value("contract_other"), executive_status: card.querySelector('[data-field="executive_status"]:checked')?.value || ""
    };
  };

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!validate()) return;
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    setSyncProgress(true);
    const payload = {
      current_situation: selected("current_situation"), current_situation_other: form.current_situation_other.value.trim(),
      qualification_level: selected("qualification_level"), qualification_other: form.qualification_other.value.trim(),
      qualification_since: form.qualification_since.value, last_certification: form.last_certification.value.trim(),
      experiences: [...experiences.children].map(experiencePayload), validation_name: form.validation_name.value.trim(),
      validation_date: form.validation_date.value, certified: form.certified.checked
    };
    try {
      const response = await fetch(form.dataset.submitUrl, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(payload) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.message || "L’envoi de votre fiche a échoué. Veuillez réessayer.");
      message.className = "pro-sheet-message is-success";
      message.textContent = result.message;
      const launch = document.querySelector(".pro-sheet-launch");
      const launchCopy = launch?.querySelector(".pro-sheet-launch-copy");
      launch?.classList.remove("needs-attention");
      launch?.classList.add("is-sent");
      launch?.removeAttribute("data-pro-sheet-open");
      if (launch) {
        launch.disabled = true;
        launch.setAttribute("aria-disabled", "true");
      }
      const status = launchCopy?.querySelector(".pro-sheet-launch-status");
      if (status) {
        status.className = "pro-sheet-launch-status sent";
        status.textContent = "Fichier envoyé";
      }
      const launchHint = launchCopy?.querySelector("small");
      if (launchHint) launchHint.textContent = "Votre fiche a bien été transmise. Elle ne peut plus être modifiée.";
      const launchArrow = launch?.querySelector(".pro-sheet-launch-arrow");
      if (launchArrow) launchArrow.textContent = "✓";
      window.setTimeout(close, 650);
    } catch (error) {
      message.className = "pro-sheet-message is-error";
      message.textContent = error.message || "L’envoi de votre fiche a échoué. Veuillez réessayer.";
      setSyncProgress(false);
      message.scrollIntoView({ behavior: "smooth", block: "center" });
    } finally { submit.disabled = false; }
  });

  if (!form.validation_date.value) form.validation_date.value = new Date().toISOString().slice(0, 10);
  renumber(); updateConditionals();
})();
