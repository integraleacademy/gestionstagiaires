(function(){
  "use strict";

  const API_URL = "https://geo.api.gouv.fr/communes";
  const ADDRESS_API_URL = "https://data.geopf.fr/geocodage/completion/";
  const DEBOUNCE_MS = 300;
  const REQUEST_TIMEOUT_MS = 5000;
  const instances = [];
  const addressInstances = [];
  let isApplyingSelectedAddress = false;

  function normalizeZip(value){ return (value || "").replace(/\D+/g, "").slice(0, 5); }
  function usefulLength(value){ return (value || "").replace(/[\s,.;:!?\-\'’]+/g, "").length; }
  function dispatchValueEvents(input){
    if(!input) return;
    input.dispatchEvent(new Event("input", {bubbles:true}));
    input.dispatchEvent(new Event("change", {bubbles:true}));
  }

  function createStatus(){
    const el = document.createElement("div");
    el.className = "postal-city-status";
    el.setAttribute("aria-live", "polite");
    return el;
  }

  function createList(zipInput){
    const el = document.createElement("div");
    el.className = "postal-city-list";
    el.setAttribute("role", "listbox");
    el.hidden = true;
    if(zipInput.id) el.setAttribute("aria-labelledby", zipInput.id);
    return el;
  }

  function setupPostalCityLookup(zipInput, cityInput){
    if(!zipInput || !cityInput || zipInput.dataset.postalCityLookup === "1") return null;
    zipInput.dataset.postalCityLookup = "1";
    zipInput.setAttribute("inputmode", "numeric");
    zipInput.setAttribute("maxlength", "5");
    zipInput.setAttribute("autocomplete", "postal-code");
    cityInput.setAttribute("autocomplete", "address-level2");
    cityInput.setAttribute("aria-autocomplete", "list");

    const zipWrapper = zipInput.closest("label") || zipInput.parentElement;
    if(zipWrapper) zipWrapper.classList.add("postal-city-field");
    const status = createStatus();
    const list = createList(zipInput);
    (zipWrapper || zipInput).appendChild(status);
    (zipWrapper || zipInput).appendChild(list);

    const state = { timer:null, controller:null, requestId:0, cities:[], activeIndex:-1, autoCity:"" };

    function setStatus(message, loading){
      status.textContent = message || "";
      status.classList.toggle("is-loading", !!loading);
    }
    function closeList(){ list.hidden = true; state.activeIndex = -1; cityInput.removeAttribute("aria-activedescendant"); }
    function clearAutoCityForChangedZip(){
      if(state.autoCity && cityInput.value.trim() === state.autoCity){ cityInput.value = ""; }
      state.autoCity = "";
    }
    function abortPending(){
      state.requestId += 1;
      if(state.timer) window.clearTimeout(state.timer);
      state.timer = null;
      if(state.controller) state.controller.abort();
      state.controller = null;
    }
    function setActive(index){
      const options = Array.from(list.querySelectorAll(".postal-city-option"));
      if(!options.length) return;
      state.activeIndex = (index + options.length) % options.length;
      options.forEach((opt, i)=> opt.classList.toggle("is-active", i === state.activeIndex));
      const active = options[state.activeIndex];
      if(active){
        cityInput.setAttribute("aria-activedescendant", active.id);
        active.scrollIntoView({block:"nearest"});
      }
    }
    function selectCity(name){
      cityInput.value = name;
      state.autoCity = name;
      closeList();
      setStatus("", false);
      cityInput.dispatchEvent(new Event("input", {bubbles:true}));
    }
    function renderCities(cities){
      list.textContent = "";
      cities.forEach((city, index)=>{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "postal-city-option";
        button.id = `${cityInput.id || "postal-city"}-option-${index}`;
        button.setAttribute("role", "option");
        button.textContent = city.nom || "";
        button.addEventListener("click", ()=>selectCity(city.nom || ""));
        list.appendChild(button);
      });
      list.hidden = cities.length === 0;
      state.activeIndex = -1;
    }
    async function fetchCities(zip, requestId){
      const controller = new AbortController();
      state.controller = controller;
      const timeout = window.setTimeout(()=>controller.abort(), REQUEST_TIMEOUT_MS);
      setStatus("Recherche de ville…", true);
      closeList();
      try{
        const url = `${API_URL}?codePostal=${encodeURIComponent(zip)}&fields=nom,code,codesPostaux&format=json`;
        const response = await fetch(url, {signal: controller.signal, headers:{"Accept":"application/json"}});
        if(!response.ok) throw new Error("geo_api_error");
        const data = await response.json();
        if(requestId !== state.requestId || zipInput.value !== zip) return;
        const cities = Array.isArray(data) ? data.filter(c=>c && typeof c.nom === "string") : [];
        state.cities = cities;
        if(cities.length === 1){ selectCity(cities[0].nom); return; }
        if(cities.length > 1){ renderCities(cities); setStatus("Sélectionnez une commune.", false); return; }
        setStatus("Aucune commune trouvée pour ce code postal", false);
      }catch(error){
        if(error && error.name === "AbortError") return;
        if(requestId === state.requestId) setStatus("Recherche de ville indisponible, saisie manuelle possible", false);
      }finally{
        window.clearTimeout(timeout);
        if(state.controller === controller) state.controller = null;
        status.classList.remove("is-loading");
      }
    }
    function onZipInput(){
      if(isApplyingSelectedAddress) return;
      const cleaned = normalizeZip(zipInput.value);
      if(zipInput.value !== cleaned) zipInput.value = cleaned;
      clearAutoCityForChangedZip();
      abortPending();
      closeList();
      setStatus("", false);
      if(cleaned.length !== 5) return;
      const requestId = state.requestId;
      state.timer = window.setTimeout(()=>fetchCities(cleaned, requestId), DEBOUNCE_MS);
    }
    zipInput.addEventListener("input", onZipInput);
    cityInput.addEventListener("input", ()=>{ if(cityInput.value.trim() !== state.autoCity) state.autoCity = ""; });
    cityInput.addEventListener("keydown", event=>{
      if(list.hidden) return;
      if(event.key === "ArrowDown"){ event.preventDefault(); setActive(state.activeIndex + 1); }
      else if(event.key === "ArrowUp"){ event.preventDefault(); setActive(state.activeIndex - 1); }
      else if(event.key === "Enter" && state.activeIndex >= 0){ event.preventDefault(); const city = state.cities[state.activeIndex]; if(city) selectCity(city.nom); }
      else if(event.key === "Escape"){ event.preventDefault(); closeList(); }
    });
    document.addEventListener("click", event=>{ if(!list.hidden && !list.contains(event.target) && event.target !== cityInput && event.target !== zipInput) closeList(); });
    instances.push({zipInput, cityInput, state});
    return state;
  }

  function mapAddressCompletionResult(result){
    const fulltext = (result && result.fulltext || "").trim();
    const street = (result && result.street || "").trim();
    const zipcode = (result && result.zipcode || "").trim();
    const city = (result && result.city || "").trim();
    const kind = (result && result.kind || "").trim();
    const address = street || fulltext.replace(new RegExp(`\\s+${zipcode}\\s+${city}$`, "i"), "").trim();
    const label = fulltext || [address, zipcode, city].filter(Boolean).join(" ").trim();
    return {address, postcode: zipcode, city, label, kind};
  }

  function initFrenchAddressAutocomplete(options){
    const addressInput = options && options.addressInput;
    const postalCodeInput = options && options.postalCodeInput;
    const cityInput = options && options.cityInput;
    if(!addressInput || !postalCodeInput || !cityInput || addressInput.dataset.addressAutocompleteInitialized === "true") return null;
    addressInput.dataset.addressAutocompleteInitialized = "true";
    addressInput.dataset.frenchAddressAutocomplete = "1";
    addressInput.setAttribute("role", "combobox");
    addressInput.setAttribute("aria-autocomplete", "list");
    addressInput.setAttribute("aria-expanded", "false");
    addressInput.setAttribute("autocomplete", "street-address");

    const wrapper = addressInput.closest("label") || addressInput.parentElement;
    if(wrapper) wrapper.classList.add("french-address-field", "address-field-wrapper");
    const status = document.createElement("div");
    status.className = "french-address-status";
    status.setAttribute("aria-live", "polite");
    const list = options.addressResultsContainer || document.createElement("div");
    list.className = "french-address-list address-suggestions";
    list.id = list.id || `${addressInput.id || "french-address"}-results`;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    addressInput.setAttribute("aria-controls", list.id);
    (wrapper || addressInput).appendChild(status);
    if(!list.parentElement) (wrapper || addressInput).appendChild(list);

    const state = {timer:null, controller:null, requestId:0, suggestions:[], activeIndex:-1, selectedAddress:""};
    function setStatus(message, loading){ status.textContent = message || ""; status.classList.toggle("is-loading", !!loading); }
    function closeList(){ list.hidden = true; state.activeIndex = -1; addressInput.setAttribute("aria-expanded", "false"); addressInput.removeAttribute("aria-activedescendant"); }
    function abortPending(){ state.requestId += 1; if(state.timer) window.clearTimeout(state.timer); state.timer = null; if(state.controller) state.controller.abort(); state.controller = null; }
    function setActive(index){
      const options = Array.from(list.querySelectorAll(".french-address-option"));
      if(!options.length) return;
      state.activeIndex = (index + options.length) % options.length;
      options.forEach((opt, i)=>{ opt.classList.toggle("is-active", i === state.activeIndex); opt.setAttribute("aria-selected", i === state.activeIndex ? "true" : "false"); });
      const active = options[state.activeIndex];
      if(active){ addressInput.setAttribute("aria-activedescendant", active.id); active.scrollIntoView({block:"nearest"}); }
    }
    function renderSuggestions(items){
      list.textContent = "";
      items.slice(0, 6).forEach((item, index)=>{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "french-address-option";
        button.id = `${addressInput.id || "french-address"}-option-${index}`;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        const main = document.createElement("span");
        main.className = "french-address-option__main";
        main.textContent = item.label || item.address || "Adresse";
        const meta = document.createElement("span");
        meta.className = "french-address-option__meta";
        meta.textContent = [item.postcode, item.city].filter(Boolean).join(" ");
        button.appendChild(main);
        button.appendChild(meta);
        button.addEventListener("click", ()=>selectAddress(item));
        list.appendChild(button);
      });
      list.hidden = items.length === 0;
      addressInput.setAttribute("aria-expanded", items.length ? "true" : "false");
      state.activeIndex = -1;
    }
    function selectAddress(item){
      isApplyingSelectedAddress = true;
      addressInput.value = item.address || item.label || "";
      postalCodeInput.value = item.postcode || "";
      cityInput.value = item.city || "";
      state.selectedAddress = addressInput.value.trim();
      closeList();
      setStatus("", false);
      dispatchValueEvents(addressInput);
      dispatchValueEvents(postalCodeInput);
      dispatchValueEvents(cityInput);
      window.setTimeout(()=>{ isApplyingSelectedAddress = false; }, 0);
    }
    async function fetchAddresses(query, requestId){
      const controller = new AbortController();
      state.controller = controller;
      const timeout = window.setTimeout(()=>controller.abort(), REQUEST_TIMEOUT_MS);
      setStatus("Recherche d’adresse…", true);
      closeList();
      try{
        const params = new URLSearchParams({
          text: query,
          type: "StreetAddress",
          maximumResponses: "6"
        });
        const url = `${ADDRESS_API_URL}?${params.toString()}`;
        console.debug("[ADDRESS] input", query);
        console.debug("[ADDRESS] request", url);
        const response = await fetch(url, {signal: controller.signal, headers:{"Accept":"application/json"}});
        console.debug("[ADDRESS] status", response.status);
        if(!response.ok) throw new Error(response.status === 429 ? "address_rate_limited" : "address_api_error");
        const data = await response.json();
        if(requestId !== state.requestId || addressInput.value.trim() !== query) return;
        const results = Array.isArray(data.results) ? data.results : [];
        const suggestions = results.map(mapAddressCompletionResult).filter(item=>item.label && item.postcode && item.city).slice(0, 6);
        console.debug("[ADDRESS] result count", suggestions.length);
        state.suggestions = suggestions;
        if(suggestions.length){ renderSuggestions(suggestions); setStatus("", false); }
        else { closeList(); setStatus("", false); }
      }catch(error){
        if(error && error.name === "AbortError") return;
        console.error("[ADDRESS] autocomplete failed", error);
        if(requestId === state.requestId){ closeList(); setStatus("Recherche d’adresse indisponible, saisie manuelle possible.", false); }
      }finally{
        window.clearTimeout(timeout);
        if(state.controller === controller) state.controller = null;
        status.classList.remove("is-loading");
      }
    }
    function onAddressInput(){
      if(addressInput.value.trim() !== state.selectedAddress) state.selectedAddress = "";
      abortPending(); closeList(); setStatus("", false);
      const query = addressInput.value.trim();
      if(usefulLength(query) < 3) return;
      const requestId = state.requestId;
      state.timer = window.setTimeout(()=>fetchAddresses(query, requestId), DEBOUNCE_MS);
    }
    addressInput.addEventListener("input", onAddressInput);
    addressInput.addEventListener("keydown", event=>{
      if(event.key === "Escape"){ if(!list.hidden){ event.preventDefault(); closeList(); } return; }
      if(list.hidden) return;
      if(event.key === "ArrowDown"){ event.preventDefault(); setActive(state.activeIndex + 1); }
      else if(event.key === "ArrowUp"){ event.preventDefault(); setActive(state.activeIndex - 1); }
      else if(event.key === "Enter" && state.activeIndex >= 0){ event.preventDefault(); const item = state.suggestions[state.activeIndex]; if(item) selectAddress(item); }
    });
    document.addEventListener("click", event=>{ if(!list.hidden && !list.contains(event.target) && event.target !== addressInput) closeList(); });
    addressInstances.push({addressInput, postalCodeInput, cityInput, state});
    return state;
  }

  function initFrenchAddressAutocompletes(root){
    const scope = root || document;
    [
      ["tAddress", "tZipCode", "tCity"],
      ["sessionTAddress", "sessionTZipCode", "sessionTCity"]
    ].forEach(([addressId, zipId, cityId])=>initFrenchAddressAutocomplete({
      addressInput: scope.getElementById ? scope.getElementById(addressId) : document.getElementById(addressId),
      postalCodeInput: scope.getElementById ? scope.getElementById(zipId) : document.getElementById(zipId),
      cityInput: scope.getElementById ? scope.getElementById(cityId) : document.getElementById(cityId)
    }));
  }

  function initPostalCityLookups(root){
    const scope = root || document;
    [
      ["tZipCode", "tCity"],
      ["sessionTZipCode", "sessionTCity"],
      ["enrollZipCode", "enrollCity"],
      ["zip_code", "city"]
    ].forEach(([zipId, cityId])=>setupPostalCityLookup(scope.getElementById ? scope.getElementById(zipId) : document.getElementById(zipId), scope.getElementById ? scope.getElementById(cityId) : document.getElementById(cityId)));
  }

  window.setupPostalCityLookup = setupPostalCityLookup;
  window.initFrenchAddressAutocomplete = initFrenchAddressAutocomplete;
  window.initFrenchAddressAutocompletes = initFrenchAddressAutocompletes;
  window.initPostalCityLookups = initPostalCityLookups;
  window.__postalCityLookupInstances = instances;
  function initLookups(root){
    initPostalCityLookups(root || document);
    initFrenchAddressAutocompletes(root || document);
  }

  function observeDynamicAddressFields(){
    if(!document.body || window.__addressAutocompleteObserver) return;
    const observer = new MutationObserver(mutations=>{
      for(const mutation of mutations){
        if(mutation.type === "childList"){
          mutation.addedNodes.forEach(node=>{
            if(node && node.nodeType === 1) initLookups(node);
          });
        }else if(mutation.type === "attributes" && mutation.target && mutation.target.nodeType === 1){
          initLookups(mutation.target);
        }
      }
    });
    observer.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:["class", "aria-hidden", "style"]});
    window.__addressAutocompleteObserver = observer;
  }

  window.addEventListener("modal:opened", event=>{ initLookups(event.detail && event.detail.modal ? event.detail.modal : document); });

  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", ()=>{ initLookups(document); observeDynamicAddressFields(); });
  else { initLookups(document); observeDynamicAddressFields(); }
})();
