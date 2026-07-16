(function(){
  "use strict";

  const API_URL = "https://geo.api.gouv.fr/communes";
  const DEBOUNCE_MS = 300;
  const REQUEST_TIMEOUT_MS = 5000;
  const instances = [];

  function normalizeZip(value){ return (value || "").replace(/\D+/g, "").slice(0, 5); }

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
  window.initPostalCityLookups = initPostalCityLookups;
  window.__postalCityLookupInstances = instances;
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", ()=>initPostalCityLookups(document));
  else initPostalCityLookups(document);
})();
