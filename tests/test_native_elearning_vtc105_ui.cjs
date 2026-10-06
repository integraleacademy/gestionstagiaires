const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/vtc-journey.js'),'utf8');

function fixture({preview=false,saved={},draft=null,adaptive=false}={}) {
  const config={courseVersion:'v3',activityId:'dossier',saved,completed:false,weakRefs:['A.02'],
    practice:{adaptive,exercises:[{id:'one',kind:'single',competency:'A.01'},{id:'two',kind:'single',competency:'A.02'}]}};
  const fields=['one','two'].map(id=>`<fieldset data-exercise-id="${id}" hidden><input type="radio" name="${id}" value="yes"><input type="radio" name="${id}" value="no"><div data-step-feedback hidden></div></fieldset>`).join('');
  const dom=new JSDOM(`<section data-vtc-journey><p data-vtc-priority hidden></p><progress max="2"></progress><strong data-vtc-step></strong><form>${fields}<button type="button" data-vtc-prev>previous</button><button type="submit" data-vtc-check>check</button><button type="button" data-vtc-next hidden>next</button></form><section data-vtc-review hidden><p data-vtc-summary></p><div data-vtc-weak></div><button data-vtc-retry>retry</button><button data-vtc-all>all</button><button data-vtc-verify hidden>verify</button></section><p data-vtc-message></p><section data-vtc-simulator data-config='{"cost_km":0.3}'><input type="range" data-sim-price min="20" max="200" value="100"><input type="range" data-sim-km min="10" max="150" value="50"><select data-sim-commission><option value="20">20</option></select><output data-sim-price-label></output><output data-sim-km-label></output><output data-sim-result></output></section></section><script type="application/json" id="vtcJourneyConfig">${JSON.stringify(config)}</script><script type="application/json" id="${preview?'nativePreviewConfig':'nativeElearningConfig'}">{"practiceUrl":"/practice","answerUrl":"/preview","csrfToken":"csrf","accessToken":"access"}</script>`,{url:'https://example.test/espace/alice/module',runScripts:'outside-only'});
  const {window}=dom,{document}=window,calls=[];let failure=false;
  const key='vtc-journey:/espace/alice/module:v3:dossier';
  if(draft)window.sessionStorage.setItem(key,JSON.stringify(draft));
  window.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);calls.push({url,options,body});
    if(failure)throw new Error('Connexion interrompue');
    const feedback=Object.entries(body.practice_answers).map(([id,v])=>({id,correct:v==='yes',explanation:'Explication <script>danger</script>',coaching:'Revoir le cours',correction:['Oui']}));
    return{ok:true,json:async()=>({ok:true,correct:feedback.every(f=>f.correct),feedback})};
  };
  window.eval(source);
  const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
  const q=s=>document.querySelector(s);
  const click=async s=>{q(s).click();await settle();};
  const choose=(id,value)=>{const input=q(`[data-exercise-id="${id}"] input[value="${value}"]`);input.checked=true;input.dispatchEvent(new window.Event('change',{bubbles:true}));};
  return{window,document,calls,key,q,click,choose,settle,fail:value=>{failure=value;},close:()=>window.close()};
}

test('sequential decisions, wrong-only revision, authoritative final check and changed answers',async()=>{
  const f=fixture({preview:true});try{
    assert.equal(f.q('[data-exercise-id=one]').hidden,false);
    await f.click('[data-vtc-check]');assert.equal(f.calls.length,0);
    f.choose('one','no');await f.click('[data-vtc-check]');
    assert.equal(f.calls[0].body.practice_step,'one');assert.equal(f.calls[0].url,'/preview');
    assert.equal(f.q('[data-step-feedback] script'),null);
    await f.click('[data-vtc-next]');f.choose('two','yes');await f.click('[data-vtc-check]');await f.click('[data-vtc-next]');
    assert.match(f.q('[data-vtc-summary]').textContent,/1 étapes réussies/);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion());
    await f.click('[data-vtc-retry]');assert.match(f.q('[data-vtc-step]').textContent,/sur 1/);
    f.choose('one','yes');await f.click('[data-vtc-check]');await f.click('[data-vtc-next]');
    assert.deepEqual(JSON.parse(JSON.stringify(f.window.aps62Practice.collectForCompletion())),{one:'yes',two:'yes'});
    assert.equal(f.calls.at(-1).body.practice_step,undefined);
    assert.equal(f.calls.at(-1).options.headers['X-Elearning-CSRF'],'csrf');
    assert.equal(f.window.sessionStorage.length,0);
    await f.click('[data-vtc-all]');f.choose('one','no');assert.throws(()=>f.window.aps62Practice.collectForCompletion());
  }finally{f.close();}
});

test('network errors preserve learner choices and offer a final verification retry',async()=>{
  const f=fixture();try{
    f.choose('one','yes');f.fail(true);await f.click('[data-vtc-check]');
    assert.match(f.q('[data-vtc-message]').textContent,/Connexion/);
    assert.equal(f.q('[data-vtc-check]').disabled,false);
    assert.equal(f.q('[data-exercise-id=one] input').disabled,false);
    assert.equal(JSON.parse(f.window.sessionStorage.getItem(f.key)).one,'yes');
    f.fail(false);await f.click('[data-vtc-check]');await f.click('[data-vtc-next]');
    f.choose('two','yes');await f.click('[data-vtc-check]');f.fail(true);await f.click('[data-vtc-next]');
    assert.equal(f.q('[data-vtc-verify]').hidden,false);assert.throws(()=>f.window.aps62Practice.collectForCompletion());
    f.fail(false);await f.click('[data-vtc-verify]');assert.equal(f.window.aps62Practice.collectForCompletion().two,'yes');
    f.window.aps62Practice.clearDraft();assert.equal(f.window.sessionStorage.length,0);
  }finally{f.close();}
});

test('resume trusts only matching server-marked answers; adaptive review prioritizes weak concepts',async()=>{
  const saved={practice_answers:{one:'yes',two:'yes'},practice_diagnostics:{one:{correct:true},two:{correct:true}}};
  const f=fixture({saved,draft:{one:'no'}});try{
    assert.equal(f.q('[data-exercise-id=one]').hidden,false);assert.equal(f.q('[data-vtc-next]').hidden,true);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion());
  }finally{f.close();}
  const g=fixture({adaptive:true});try{
    assert.equal(g.q('[data-exercise-id=two]').hidden,false);assert.equal(g.q('[data-vtc-priority]').hidden,false);
    assert.match(g.q('[data-sim-result]').textContent,/Contribution : 65.00/);
    g.q('[data-sim-price]').value='120';g.q('[data-sim-price]').dispatchEvent(new g.window.Event('input',{bubbles:true}));
    assert.match(g.q('[data-sim-result]').textContent,/Contribution : 81.00/);
  }finally{g.close();}
  const h=fixture({saved});try{await h.settle();assert.equal(h.q('[data-vtc-review]').hidden,false);assert.equal(h.window.aps62Practice.collectForCompletion().one,'yes');}finally{h.close();}
});
