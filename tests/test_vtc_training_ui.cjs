const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/vtc-journey.js'),'utf8');

function fixture({draft=null,readonly=false}={}) {
  const pathname='/espace/alice/elearning/vtc/entrainement/academy-vtc-a/dossier';
  const key=`vtc-journey:${pathname}:bank-v6:revision-1:dossier`;
  const config={courseVersion:'bank-v6:revision-1',activityId:'dossier',saved:{},completed:false,
    weakRefs:[],freePractice:true,practice:{adaptive:false,exercises:[{id:'one',kind:'single'}]}};
  const dom=new JSDOM(`<section data-vtc-journey><p data-vtc-priority hidden></p><progress max="1"></progress><strong data-vtc-step></strong>
    <form><fieldset data-exercise-id="one" hidden><legend>Décision</legend><h3>Quel choix ?</h3><input type="radio" name="one" value="yes"><input type="radio" name="one" value="no"><div data-step-feedback hidden></div></fieldset>
    <button type="button" data-vtc-prev>Précédent</button><button type="submit" data-vtc-check ${readonly?'disabled':''}>Vérifier</button><button type="button" data-vtc-next hidden>Suivant</button></form>
    <section data-vtc-review hidden><h3>Bilan</h3><p data-vtc-summary></p><div data-vtc-weak></div><button data-vtc-retry>Reprendre</button><button data-vtc-all>Revoir</button><button data-vtc-verify hidden>Réessayer</button></section><p data-vtc-message></p></section>
    <script id="vtcJourneyConfig" type="application/json">${JSON.stringify(config)}</script>
    <script id="nativePreviewConfig" type="application/json">{"answerUrl":"/free-answer?bank_version=v6&revision=1","csrfToken":"csrf"}</script>`,
    {url:`https://example.test${pathname}`,runScripts:'outside-only'});
  const {window}=dom, calls=[];
  if(draft)window.sessionStorage.setItem(key,JSON.stringify(draft));
  let failed=false;
  window.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);calls.push({url,body,options});
    if(failed)throw new Error('Connexion interrompue');
    const feedback=Object.entries(body.practice_answers).map(([id,value])=>({id,correct:value==='yes',explanation:'Consultez le document.',correction:['Oui']}));
    return {ok:true,json:async()=>({ok:true,correct:feedback.every(f=>f.correct),feedback})};
  };
  window.eval(source);
  const q=selector=>window.document.querySelector(selector);
  const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
  return {window,q,key,calls,close:()=>window.close(),fail:value=>{failed=value;},
    choose(value){const input=q(`input[value=${value}]`);input.checked=true;input.dispatchEvent(new window.Event('change',{bubbles:true}));},
    async click(selector){q(selector).click();await settle();}};
}

test('free practice restores only its choices and corrections stay authoritative after reload',async()=>{
  const f=fixture({draft:{one:'yes',removed_question:'yes'}});
  try {
    assert.equal(f.q('input[value=yes]').checked,true);
    assert.equal(f.q('[data-step-feedback]').hidden,true);
    assert.equal(f.q('[data-vtc-next]').hidden,true);
    assert.equal(f.calls.length,0);
    await f.click('[data-vtc-check]');await f.click('[data-vtc-next]');
    assert.equal(f.calls.length,2);
    assert.deepEqual(f.calls.at(-1).body.practice_answers,{one:'yes'});
    assert.match(f.q('[data-vtc-summary]').textContent,/Entraînement terminé/);
    assert.doesNotMatch(f.q('[data-vtc-summary]').textContent,/Terminer l’activité/);
    for(const call of f.calls){
      assert.equal(call.url,'/free-answer?bank_version=v6&revision=1');
      assert.equal(call.options.headers['X-Elearning-CSRF'],'csrf');
      assert.equal(call.options.credentials,'same-origin');
      assert.equal(call.body.access_token,undefined);
    }
    assert.equal(f.window.sessionStorage.length,1);
    assert.equal(f.window.document.activeElement,f.q('[data-vtc-review] h3'));
  } finally {f.close();}
});

test('free practice retains choices across failed corrections and never marks them successful locally',async()=>{
  const f=fixture();try {
    f.choose('yes');f.fail(true);await f.click('[data-vtc-check]');
    assert.equal(JSON.parse(f.window.sessionStorage.getItem(f.key)).one,'yes');
    assert.equal(f.q('[data-vtc-next]').hidden,true);
    assert.equal(f.q('[data-vtc-check]').disabled,false);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion());
    f.fail(false);await f.click('[data-vtc-check]');f.fail(true);await f.click('[data-vtc-next]');
    assert.equal(f.q('[data-vtc-verify]').hidden,false);
    f.fail(false);await f.click('[data-vtc-verify]');
    assert.match(f.q('[data-vtc-summary]').textContent,/Entraînement terminé/);
  } finally {f.close();}
});

test('viewer cannot check a free-practice draft or issue a background correction',async()=>{
  const f=fixture({readonly:true,draft:{one:'yes'}});try {
    await f.click('[data-vtc-check]');
    f.q('form').dispatchEvent(new f.window.Event('submit',{bubbles:true,cancelable:true}));
    assert.equal(f.calls.length,0);
    assert.equal(f.q('[data-vtc-check]').disabled,true);
    assert.equal(f.q('[data-step-feedback]').hidden,true);
  } finally {f.close();}
});
