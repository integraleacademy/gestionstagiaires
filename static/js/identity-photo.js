/* Shared with the BTS workflow: reversible zoom, drag, rotation and straightening. */
(() => {
  'use strict';
  const dialog = document.getElementById('identityPhotoDialog');
  if (!dialog) return;
  const $ = name => dialog.querySelector(`[data-photo-${name}]`);
  const canvas = dialog.querySelector('canvas'), context = canvas.getContext('2d');
  const zoom = $('zoom'), angle = $('angle'), source = new Image();
  let active, meta, hash = '', rotation = 0, scale = 1, fit = 1, cx = 0, cy = 0;
  let loaded = false, busy = false, drag = null, objectURL = null, version = 0;
  const radians = () => (rotation + Number(angle.value)) * Math.PI / 180;
  function report(message = '', error = false) { $('status').textContent = message; $('status').classList.toggle('is-error', error); }
  function controls(value) {
    busy = value;
    dialog.querySelectorAll('button,input').forEach(el => { el.disabled = value || !!meta?.read_only; });
    dialog.querySelectorAll('[data-photo-close]').forEach(el => { el.disabled = value; });
    for (const name of ['save','reset','zoom','angle','zoom-in','zoom-out','rotate','center']) $(name).disabled ||= !loaded;
  }
  function minimumScale() {
    const c = Math.abs(Math.cos(radians())), s = Math.abs(Math.sin(radians()));
    return Math.max((c*canvas.width+s*canvas.height)/source.naturalWidth,
                    (s*canvas.width+c*canvas.height)/source.naturalHeight);
  }
  function draw() {
    if (!loaded) return;
    fit = minimumScale(); scale = Math.max(fit, Math.min(fit*10, scale));
    const c = Math.abs(Math.cos(radians())), s = Math.abs(Math.sin(radians()));
    const halfW = (c*canvas.width+s*canvas.height)/scale/2, halfH = (s*canvas.width+c*canvas.height)/scale/2;
    cx = Math.max(halfW, Math.min(source.naturalWidth-halfW, cx));
    cy = Math.max(halfH, Math.min(source.naturalHeight-halfH, cy));
    context.setTransform(1,0,0,1,0,0); context.clearRect(0,0,canvas.width,canvas.height);
    context.translate(canvas.width/2,canvas.height/2); context.scale(scale,scale); context.rotate(radians());
    context.drawImage(source,-cx,-cy);
    zoom.value = String(scale/fit);
    $('zoom-value').textContent = Math.round(scale/fit*100)+' %';
    $('angle-value').textContent = Number(angle.value).toLocaleString('fr-FR')+'°';
  }
  function zoomTo(value) { if (loaded && !busy) {scale = fit * Math.max(1,Math.min(10,value)); draw();} }
  function move(dx,dy) {
    const c = Math.cos(radians()), s = Math.sin(radians());
    cx -= (c*dx+s*dy)/scale; cy -= (-s*dx+c*dy)/scale; draw();
  }
  async function response(url, options = {}) {
    const result = await fetch(url, {credentials:'same-origin',cache:'no-store',...options});
    if (!result.ok || (result.headers.get('Content-Type') || '').includes('text/html')) {
      let message;
      try {message = (await result.json()).error;} catch {}
      throw Error(message || 'La photo ne peut pas être chargée. Vérifiez votre connexion ou reconnectez-vous.');
    }
    return result;
  }
  async function load() {
    const current = version;
    loaded = false;
    context.setTransform(1,0,0,1,0,0); context.clearRect(0,0,canvas.width,canvas.height);
    meta = await (await response(active.api)).json();
    if (current !== version) return;
    $('empty').hidden = meta.photo_available;
    if (!meta.photo_available) {report('Ajoutez une photo pour commencer.'); return;}
    const result = await response(active.api + '/image?original=1');
    if (current !== version) return;
    hash = result.headers.get('X-Photo-Source');
    meta.revision = result.headers.get('X-Photo-Revision');
    const saved = JSON.parse(result.headers.get('X-Photo-Crop') || 'null');
    const blob = await result.blob();
    if (current !== version) return;
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = URL.createObjectURL(blob);
    await new Promise((resolve,reject) => {source.onload=resolve;source.onerror=()=>reject(Error('Photo illisible.'));source.src=objectURL;});
    if (current !== version) return;
    loaded = true; rotation = saved?.rotation || 0; angle.value = String(saved?.straighten || 0);
    cx = source.naturalWidth/2; cy = source.naturalHeight/2; scale = minimumScale();
    if (saved?.version === 2) {cx=saved.cx*source.naturalWidth;cy=saved.cy*source.naturalHeight;scale=canvas.width/(saved.width*source.naturalWidth);}
    draw(); report();
  }
  function updated(result) {
    document.querySelectorAll('[data-identity-photo-view]').forEach(view => {
      if (view.dataset.photoId !== result.id) return;
      const image = document.createElement('img'); image.src = result.photo_url; image.alt = 'Photo d’identité';
      image.className = view.dataset.photoClass || '';
      view.replaceChildren(image);
    });
    document.dispatchEvent(new CustomEvent('identity-photo-updated',{detail:result}));
  }
  document.addEventListener('click', async event => {
    const opener = event.target.closest('[data-identity-photo-edit]');
    if (!opener || opener.disabled || busy) return;
    active = {opener,api:opener.dataset.photoApi,id:opener.dataset.photoId};
    version++; meta = null; loaded = false; hash = '';
    $('person').textContent = opener.dataset.photoName || '';
    $('empty').hidden = true; report('Chargement de la photo…'); controls(true); dialog.showModal();
    try {await load();} catch (error) {report(error.message,true);} finally {controls(false);}
  });
  zoom.addEventListener('input',()=>zoomTo(Number(zoom.value)));
  angle.addEventListener('input',()=>{if(loaded&&!busy)draw();});
  $('zoom-in').addEventListener('click',()=>zoomTo(scale/fit*1.25));
  $('zoom-out').addEventListener('click',()=>zoomTo(scale/fit/1.25));
  $('rotate').addEventListener('click',()=>{if(loaded&&!busy){rotation=(rotation+90)%360;draw();}});
  $('center').addEventListener('click',()=>{if(loaded&&!busy){cx=source.naturalWidth/2;cy=source.naturalHeight/2;draw();}});
  canvas.addEventListener('wheel',event=>{if(loaded&&!busy){event.preventDefault();zoomTo(scale/fit*(event.deltaY<0?1.08:1/1.08));}},{passive:false});
  canvas.addEventListener('pointerdown',event=>{if(!loaded||busy)return;canvas.setPointerCapture(event.pointerId);drag={x:event.clientX,y:event.clientY};canvas.focus();});
  canvas.addEventListener('pointermove',event=>{
    if(!drag||busy)return;const bounds=canvas.getBoundingClientRect();
    move((event.clientX-drag.x)*canvas.width/bounds.width,(event.clientY-drag.y)*canvas.height/bounds.height);
    drag={x:event.clientX,y:event.clientY};
  });
  ['pointerup','pointercancel','lostpointercapture'].forEach(type=>canvas.addEventListener(type,()=>{drag=null;}));
  canvas.addEventListener('keydown',event=>{
    const offsets={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]};
    if(!offsets[event.key]||!loaded||busy)return;event.preventDefault();move(...offsets[event.key]);
  });
  async function persist(reset) {
    if (!loaded || busy || meta?.read_only) return;
    controls(true); report('Enregistrement du cadrage…');
    const data = reset ? {reset:true} : {version:2,rotation,straighten:Number(angle.value),cx:cx/source.naturalWidth,cy:cy/source.naturalHeight,
      width:canvas.width/(scale*source.naturalWidth),height:canvas.height/(scale*source.naturalHeight)};
    try {
      const result = await (await response(active.api+'/crop',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':meta.csrf},
        body:JSON.stringify({...data,revision:meta.revision,source_hash:hash})})).json();
      updated(result); dialog.close();
    } catch (error) {report(error.message,true);} finally {controls(false);}
  }
  $('save').addEventListener('click',()=>persist(false)); $('reset').addEventListener('click',()=>persist(true));
  $('upload').addEventListener('click',()=>{if(meta&&!busy&&!meta.read_only)$('file').click();});
  $('file').addEventListener('change',async()=>{
    const file = $('file').files[0];
    if (!file || busy || !meta || meta.read_only) return;
    if (file.size > 10*1024*1024) {report('La photo ne doit pas dépasser 10 Mo.',true);$('file').value='';return;}
    controls(true); report('Enregistrement de la photo…');
    const form = new FormData(); form.append('photo',file); form.append('revision',meta.revision);
    try {
      const result = await (await response(active.api+'/upload',{method:'POST',headers:{'X-CSRF-Token':meta.csrf},body:form})).json();
      updated(result); await load(); report('Photo enregistrée. Ajustez le cadrage si nécessaire.');
    } catch (error) {report(error.message,true);} finally {$('file').value='';controls(false);}
  });
  dialog.querySelectorAll('[data-photo-close]').forEach(button=>button.addEventListener('click',()=>{if(!busy)dialog.close();}));
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{version++;drag=null;active?.opener.focus();if(objectURL){URL.revokeObjectURL(objectURL);objectURL=null;}});
})();
