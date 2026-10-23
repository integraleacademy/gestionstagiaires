(() => {
  const root = document.querySelector('[data-afc-picker]');
  if (!root) return;
  const panel = root.querySelector('[data-afc-search-panel]');
  const search = root.querySelector('input[type=search]');
  const results = root.querySelector('[data-afc-results]');
  const feedback = root.querySelector('[data-afc-feedback]');
  const selected = document.getElementById('afcSelectedCandidateId');
  const clear = root.querySelector('[data-afc-clear]');
  const map = {last_name:'tLastName', first_name:'tFirstName', email:'tEmail', phone:'tPhone',
    birth_date:'tBirthDate', birth_city:'tBirthPlace', address:'tAddress', zip_code:'tZipCode', city:'tCity'};
  let timer, sequence = 0, before = null;
  async function load() {
    const current = ++sequence;
    results.textContent = 'Chargement…';
    try {
      const response = await fetch(root.dataset.url + '?q=' + encodeURIComponent(search.value), {headers:{Accept:'application/json'}});
      const data = await response.json();
      if (current !== sequence) return;
      if (!response.ok || !data.ok) throw new Error('La liste AFC est indisponible. Réessayez.');
      results.replaceChildren();
      for (const candidate of data.candidates) {
        const row = document.createElement('div'); row.className = 'afc-picker-row';
        const info = document.createElement('div');
        const name = document.createElement('strong'); name.textContent = candidate.last_name + ' ' + candidate.first_name;
        const details = document.createElement('span'); details.textContent = [candidate.email, candidate.phone, candidate.identifiant_ft ? 'FT : ' + candidate.identifiant_ft : '', candidate.decision].filter(Boolean).join(' · ');
        info.append(name, details);
        const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-outline';
        button.textContent = candidate.already_enrolled ? 'Déjà inscrit' : 'Sélectionner'; button.disabled = candidate.already_enrolled;
        button.addEventListener('click', () => {
          if (!before) before = Object.fromEntries(Object.values(map).map(id => [id, document.getElementById(id).value]));
          Object.entries(map).forEach(([key,id]) => { document.getElementById(id).value = candidate[key] || ''; });
          selected.value = candidate.id; clear.hidden = false; panel.hidden = true;
          feedback.textContent = candidate.first_name + ' ' + candidate.last_name + ' sélectionné. Vérifiez les informations, puis cliquez sur Sauvegarder.';
        });
        row.append(info, button); results.append(row);
      }
      if (!data.candidates.length) results.textContent = 'Aucun candidat AFC trouvé.';
      if (data.total > data.candidates.length) feedback.textContent = 'Les 100 premiers résultats sont affichés. Précisez votre recherche.';
    } catch (error) { if (current === sequence) results.textContent = error.message; }
  }
  root.querySelector('[data-afc-open]').addEventListener('click', () => {panel.hidden = false; search.focus(); load();});
  search.addEventListener('input', () => {clearTimeout(timer); sequence++; timer = setTimeout(load, 200);});
  clear.addEventListener('click', () => {
    if (before) Object.entries(before).forEach(([id,value]) => {document.getElementById(id).value = value;});
    before = null; selected.value = ''; clear.hidden = true; feedback.textContent = 'Sélection annulée.';
  });
})();
