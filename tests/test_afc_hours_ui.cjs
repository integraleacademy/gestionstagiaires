// Run with NODE_PATH pointing to an installation of jsdom.
const {JSDOM} = require('jsdom');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('static/js/afc-hours.js', 'utf8');
const dates = {'54':'2026-11-16','40':'2026-11-18','0':'2026-11-26'};
function fixture({saved = false, readOnly = false, missing = false} = {}) {
  const profiles = Object.fromEntries(Array.from({length:12}, (_, i) => [`T${i}`, i < 8 ? 54 : i < 10 ? 40 : 0]));
  const state = {read_only:readOnly, csrf:'test', revision:'before', target:{'54':8,'40':2,'0':2}, dates,
    rows:Object.keys(profiles).map(id => ({id,ran_hours:saved ? profiles[id] : null})),
    suggestion:{profiles:missing ? null : profiles, issue:missing ? 'Résultat manquant' : ''}};
  const html = `<div id="afcHours" data-save-url="/save" data-export-url="/export">
    ${['54','40','0'].map(h => `<div data-profile-card="${h}"><b data-count="${h}"></b><span data-profile-date="${h}"></span></div><input type="date" data-entry-date="${h}" value="${dates[h]}">`).join('')}
    <table>${state.rows.map(row => `<tr data-trainee="${row.id}"><td><select data-ran-choice><option value=""></option>${['54','40','0'].map(h=>`<option value="${h}" ${String(row.ran_hours)===h?'selected':''}>${h}</option>`).join('')}</select></td><td data-row-start></td><td data-row-total></td></tr>`).join('')}</table>
    <p id="afcHoursProgress"></p><p id="afcHoursMessage"></p><button id="afcHoursExport"></button><button id="afcHoursSave"></button><button id="afcHoursFill"></button><button id="afcHoursSuggest"></button>
    </div><script type="application/json" id="afcHoursState">${JSON.stringify(state)}</script>`;
  const dom = new JSDOM(html, {runScripts:'outside-only', url:'https://example.test'});
  const calls = [];
  dom.window.fetch = async (url, args) => {
    const sent = JSON.parse(args.body);
    calls.push(sent);
    return {ok:true,json:async()=>({ok:true,state:{...state, revision:'after',rows:state.rows.map(row=>({...row,ran_hours:sent.profiles[row.id]}))}})};
  };
  dom.window.eval(source);
  return {window:dom.window, doc:dom.window.document, calls};
}
(async () => {
  let {window,doc,calls} = fixture();
  assert.equal(doc.querySelector('[data-count="54"]').textContent,'8');
  assert.equal(doc.querySelector('[data-count="40"]').textContent,'2');
  assert.equal(doc.querySelector('[data-count="0"]').textContent,'2');
  assert.equal(doc.querySelector('[data-trainee="T10"] [data-row-total]').textContent,'339 h');
  assert.equal(doc.querySelector('[data-trainee="T8"] [data-row-start]').textContent,'18/11/2026');
  assert.equal(doc.getElementById('afcHoursExport').disabled,false);
  assert.equal(calls.length,0, 'Opening a proposal must not save it');
  const select=doc.querySelector('[data-trainee="T10"] select');
  select.value='54'; select.dispatchEvent(new window.Event('change'));
  assert.equal(doc.getElementById('afcHoursExport').disabled,true);
  doc.getElementById('afcHoursSuggest').click();
  assert.equal(select.value,'0');
  doc.getElementById('afcHoursSave').click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.length,1);
  assert.equal(calls[0].profiles.T10,0);
  assert.equal(calls[0].dates['0'],'2026-11-26');
  doc.getElementById('afcHoursSave').click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls[1].revision,'after','Subsequent saves use the returned revision');
  window.close();
  ({window,doc,calls}=fixture({missing:true}));
  assert.equal(doc.getElementById('afcHoursExport').disabled,true);
  assert.equal(doc.querySelector('[data-trainee="T0"] select').value,'');
  assert.equal(calls.length,0);
  window.close();
  ({window,doc,calls}=fixture({readOnly:true}));
  assert.equal(doc.querySelector('[data-trainee="T0"] select').value,'');
  assert.equal(doc.getElementById('afcHoursExport').disabled,true);
  assert.equal(calls.length,0);
  window.close();
  console.log('AFC UI: notes, 8/2/2 counters, 0 h, dates, saves and missing results verified.');
})().catch(error => {console.error(error);process.exitCode=1;});
