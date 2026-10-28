const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(t, options = {}) {
  const html = '<button data-identity-photo-edit data-photo-id="T1" data-photo-api="/photo/T1" data-photo-name="Camille EXEMPLE"><span data-identity-photo-view data-photo-id="T1"></span></button>' + fs.readFileSync('templates/_identity_photo_editor.html','utf8');
  const dom = new JSDOM(html,{runScripts:'outside-only',url:'https://app.example/'});
  t.after(()=>dom.window.close());
  const w=dom.window, doc=w.document, dialog=doc.querySelector('dialog'), calls=[], changes=[];
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.HTMLCanvasElement.prototype.getContext=()=>({setTransform(){},clearRect(){},translate(){},scale(){},rotate(){},drawImage(){}});
  w.Image=class {constructor(){this.naturalWidth=1400;this.naturalHeight=1800;}set src(value){queueMicrotask(()=>this.onload?.());}};
  w.URL.createObjectURL=()=> 'blob:photo';w.URL.revokeObjectURL=()=>{};
  let available=!options.noPhoto;
  w.fetch=async(url, config={})=>{
    const body=config.body instanceof w.FormData ? {upload:true,revision:config.body.get('revision')} : config.body ? JSON.parse(config.body) : null;
    calls.push({url,body,headers:config.headers});
    if (url.endsWith('/crop') && options.conflict) return {ok:false,headers:new w.Headers(),json:async()=>({error:'La photo a changé. Rouvrez le recadrage.'})};
    if (url.includes('/image')) return {ok:true,headers:new w.Headers({'Content-Type':'image/jpeg','X-Photo-Source':'hash1','X-Photo-Revision':'r1','X-Photo-Crop':JSON.stringify(options.saved||null)}),blob:async()=>new w.Blob(['image'])};
    if (url.endsWith('/upload')) available=true;
    return {ok:true,headers:new w.Headers({'Content-Type':'application/json'}),json:async()=>({ok:true,id:'T1',csrf:'csrf1',revision:'r1',photo_available:available,photo_url:'/photo-new.jpg',read_only:!!options.readOnly})};
  };
  doc.addEventListener('identity-photo-updated',event=>changes.push(event.detail));
  w.eval(fs.readFileSync('static/js/identity-photo.js','utf8'));
  const $=name=>doc.querySelector(`[data-photo-${name}]`);
  const click=async(name)=>{$(name).click();await tick();await tick();};
  const input=(name,value)=>{$(name).value=value;$(name).dispatchEvent(new w.Event('input'));};
  doc.querySelector('[data-identity-photo-edit]').click();await tick();await tick();
  return {w,doc,dialog,calls,changes,$,click,input};
}

test('editor opens the original and sends the 35 x 45 crop with source and revision guards',async t=>{
  const ui=await setup(t);
  assert.equal(ui.dialog.open,true);
  assert.equal(ui.$('save').disabled,false);
  ui.input('zoom','2');
  assert.equal(ui.$('zoom-value').textContent,'200 %');
  ui.doc.querySelector('canvas').dispatchEvent(new ui.w.KeyboardEvent('keydown',{key:'ArrowRight'}));
  await ui.click('save');
  const request=ui.calls.find(call=>call.url.endsWith('/crop'));
  assert.equal(request.body.width,.5);
  assert.equal(request.body.height,.5);
  assert.ok(request.body.cx<.5);
  assert.equal(request.body.source_hash,'hash1');assert.equal(request.body.revision,'r1');
  assert.equal(request.headers['X-CSRF-Token'],'csrf1');
  assert.equal(ui.dialog.open,false);
  assert.equal(ui.changes.length,1);
  assert.equal(ui.doc.querySelector('[data-identity-photo-view] img').getAttribute('src'),'/photo-new.jpg');
});

test('rotation, straightening and repositioning keep the crop inside the source image',async t=>{
  const ui=await setup(t);
  ui.input('zoom','2');await ui.click('rotate');ui.input('angle','21.5');await ui.click('center');await ui.click('save');
  const crop=ui.calls.find(call=>call.url.endsWith('/crop')).body;
  assert.equal(crop.rotation,90);assert.equal(crop.straighten,21.5);
  const a=(crop.rotation+crop.straighten)*Math.PI/180,w=crop.width*1400,h=crop.height*1800;
  const hw=(Math.abs(Math.cos(a))*w+Math.abs(Math.sin(a))*h)/2;
  const hh=(Math.abs(Math.sin(a))*w+Math.abs(Math.cos(a))*h)/2;
  assert.ok(crop.cx*1400>=hw-.01 && crop.cx*1400<=1400-hw+.01);
  assert.ok(crop.cy*1800>=hh-.01 && crop.cy*1800<=1800-hh+.01);
  assert.ok(Math.abs(w/h-7/9)<.00001);
});

test('saved crop reopens unchanged; restore explicitly requests the original',async t=>{
  const ui=await setup(t,{saved:{version:2,rotation:0,straighten:0,cx:.3,cy:.4,width:.5,height:.5}});
  assert.equal(ui.$('zoom-value').textContent,'200 %');
  await ui.click('reset');
  const crop=ui.calls.find(call=>call.url.endsWith('/crop')).body;
  assert.equal(crop.reset,true);assert.equal(crop.source_hash,'hash1');assert.equal(crop.width,undefined);
});

test('outside clicks do not close the editor and cancel does not save',async t=>{
  const ui=await setup(t);ui.input('zoom','2');
  ui.dialog.dispatchEvent(new ui.w.MouseEvent('click',{bubbles:true}));assert.equal(ui.dialog.open,true);
  await ui.click('close');
  assert.equal(ui.dialog.open,false);assert.equal(ui.calls.filter(call=>call.body).length,0);
});

test('concurrent change leaves the crop open and displays a useful error',async t=>{
  const ui=await setup(t,{conflict:true});ui.input('zoom','2');await ui.click('save');
  assert.equal(ui.dialog.open,true);assert.match(ui.$('status').textContent,/a changé/);
  assert.equal(ui.$('zoom-value').textContent,'200 %');assert.equal(ui.changes.length,0);
});

test('missing photo can be uploaded and cropped without reloading the page',async t=>{
  const ui=await setup(t,{noPhoto:true});
  assert.equal(ui.$('empty').hidden,false);assert.equal(ui.$('save').disabled,true);
  const file=new ui.w.File(['photo'],'photo.png',{type:'image/png'});
  Object.defineProperty(ui.$('file'),'files',{value:[file],configurable:true});
  ui.$('file').dispatchEvent(new ui.w.Event('change'));await tick();await tick();
  assert.equal(ui.$('empty').hidden,true);assert.equal(ui.$('save').disabled,false);
  assert.equal(ui.calls.find(call=>call.body?.upload).body.revision,'r1');assert.equal(ui.changes.length,1);
});

test('read-only response never permits photo editing or upload',async t=>{
  const ui=await setup(t,{readOnly:true});
  assert.equal(ui.$('save').disabled,true);assert.equal(ui.$('upload').disabled,true);
  assert.equal(ui.$('reset').disabled,true);assert.equal(ui.$('close').disabled,false);
});
