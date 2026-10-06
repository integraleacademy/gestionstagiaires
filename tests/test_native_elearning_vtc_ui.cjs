// Verify the VTC preset selects only its curriculum and stays local until Save.
const {JSDOM}=require('jsdom');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'..');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'elearning_native/vtc/manifest.json'),'utf8'));
const catalog=manifest.modules.map(m=>{
 const c=JSON.parse(fs.readFileSync(path.join(root,'elearning_native/vtc/courses',m.id,m.version+'.json'),'utf8'));
 return {course_id:c.id,course_version:c.version,title:c.title,vtc:true,planned_minutes:c.planned_minutes,sections:c.sections};
});
catalog.unshift({course_id:'academy-aps62-01',course_version:'aps-version',title:'APS',academy:true,planned_minutes:240,sections:[]});
const config={catalog,modules:[],revision:'initial',csrfToken:'csrf',saveUrl:'/save',readOnly:false};
const dom=new JSDOM(`<div id="nativeModuleLibrary"></div><div id="nativePathModules"></div><input id="nativeModuleSearch"><input id="nativePathTitle" value="Parcours VTC"><div id="nativePathTotals"></div><button id="vtcAddPath">Ajouter</button><button id="nativePathSave">Enregistrer</button><strong id="nativePathSaveState"></strong><script id="nativePathConfig" type="application/json">${JSON.stringify(config)}</script>`,{runScripts:'outside-only',url:'https://test.invalid/'});
let saved;
dom.window.fetch=async(url,opts)=>{assert.equal(url,'/save');saved=JSON.parse(opts.body);return {ok:true,json:async()=>({ok:true,modules:saved.modules,revision:'saved'})}};
dom.window.eval(fs.readFileSync(path.join(root,'static/js/native-elearning-path.js'),'utf8'));
const d=dom.window.document;
(async()=>{
 d.getElementById('vtcAddPath').click();
 assert.equal(d.querySelectorAll('#nativePathModules > details').length,8);
 assert.equal(saved,undefined);
 assert.match(d.getElementById('nativePathTotals').textContent,/208 activités60 h 00 min/);
 assert.equal(d.getElementById('nativePathTitle').value,'VTC · Le parcours illustré');
 d.getElementById('vtcAddPath').click();
 assert.equal(d.querySelectorAll('#nativePathModules > details').length,8);
 d.getElementById('nativePathSave').click();
 await new Promise(resolve=>setTimeout(resolve,0));
 assert.deepEqual(saved.modules.map(m=>m.course_id),manifest.modules.map(m=>m.id));
 assert.equal(saved.modules.reduce((sum,m)=>sum+m.required_minutes,0),3600);
 assert(saved.modules.every(m=>m.section_ids.length===13 && m.course_version===manifest.version));
 console.log('PASS: VTC only, stable order, full curriculum, durations, no duplicate, explicit save.');
 dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close()});
