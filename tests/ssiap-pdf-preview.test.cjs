const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup(t, width = 1000, height = 600, sizes = [[842.25,595.5],[595.5,842.25]]) {
  const dom = new JSDOM(fs.readFileSync('templates/_ssiap_exam_modal.html','utf8'), {runScripts:'outside-only'});
  t.after(() => dom.window.close());
  const w = dom.window, dialog = w.document.getElementById('ssiapDiplomaPreview'), area = dialog.querySelector('[data-pdf-area]');
  w.HTMLDialogElement.prototype.showModal = function() {this.open = true;};
  w.HTMLDialogElement.prototype.close = function() {this.open = false;this.dispatchEvent(new w.Event('close'));};
  w.HTMLCanvasElement.prototype.getContext = () => ({});
  w.ResizeObserver = class {constructor(callback) {this.callback = callback;} observe() {}};
  w.URL.createObjectURL = () => 'blob:test'; w.URL.revokeObjectURL = () => {};
  Object.defineProperties(area, {clientWidth:{get:() => width},clientHeight:{get:() => height}});
  const renders = [], pages = sizes.map(([a,b]) => ({getViewport:({scale}) => ({width:a*scale,height:b*scale}),
    render:options => {renders.push(options); return {cancel(){},promise:Promise.resolve()};}}));
  const pdf = {numPages:sizes.length,getPage:async n => pages[n-1]};
  const lib = {GlobalWorkerOptions:{},getDocument:() => ({promise:Promise.resolve(pdf),destroy:async () => {}})};
  w.eval(fs.readFileSync('static/js/ssiap-pdf-preview.js','utf8'));
  const viewer = new w.SsiapPdfPreview(dialog, async () => lib);
  return {w,dialog,area,pdf,lib,pages,renders,viewer,resize:(x,y) => {width=x;height=y;},blob:{arrayBuffer:async () => new ArrayBuffer(2)}};
}

test('whole-page fit handles landscape, portrait and narrow screens in both dimensions', async t => {
  const ui = setup(t);
  await ui.viewer.open(ui.blob);
  assert.equal(ui.dialog.open,true);
  const fit = () => {
    assert.ok(parseFloat(ui.viewer.canvas.style.width) <= ui.area.clientWidth - 32);
    assert.ok(parseFloat(ui.viewer.canvas.style.height) <= ui.area.clientHeight - 32);
    assert.equal(ui.viewer.status.hidden,true);
  };
  fit();
  await ui.viewer.go(1); fit();
  assert.equal(ui.viewer.pageLabel.textContent,'Page 2 / 2');
  assert.equal(ui.viewer.next.disabled,true);
  ui.resize(345,400); await ui.viewer.render(); fit();
  await ui.viewer.go(-1); fit();
  assert.equal(ui.viewer.previous.disabled,true);
});

test('zoom, page navigation and a new PDF reset correctly without closing on outside clicks', async t => {
  const ui = setup(t);
  await ui.viewer.open(ui.blob);
  const initial = parseFloat(ui.viewer.canvas.style.width);
  ui.viewer.zoom = 2; await ui.viewer.render();
  assert.ok(parseFloat(ui.viewer.canvas.style.width) > initial);
  await ui.viewer.go(1);
  assert.equal(ui.viewer.zoom,1);
  ui.dialog.dispatchEvent(new ui.w.MouseEvent('click'));
  assert.equal(ui.dialog.open,true);
  await ui.viewer.open(ui.blob, {filename:'courrier-SDIS.pdf',title:'Courrier SDIS'});
  assert.equal(ui.viewer.pageNumber,1);
  assert.equal(ui.dialog.querySelector('h2').textContent,'Courrier SDIS');
  assert.equal(ui.dialog.querySelector('[data-pdf-download]').download,'courrier-SDIS.pdf');
  ui.dialog.close();
  assert.equal(ui.viewer.pdf,null);
  assert.equal(ui.viewer.canvas.hidden,true);
});

test('a late page request cannot overwrite a newer resize or draw after closing', async t => {
  const ui = setup(t);
  await ui.viewer.open(ui.blob);
  let resolveOld;
  ui.pdf.getPage = () => new Promise(resolve => {resolveOld = resolve;});
  const old = ui.viewer.render();
  await tick();
  ui.pdf.getPage = async () => ui.pages[0];
  ui.resize(400,400); await ui.viewer.render();
  const count = ui.renders.length;
  resolveOld(ui.pages[0]); await old;
  assert.equal(ui.renders.length,count);
  ui.pdf.getPage = () => new Promise(resolve => {resolveOld = resolve;});
  const closing = ui.viewer.render(); await tick(); ui.dialog.close();
  resolveOld(ui.pages[0]); await closing;
  assert.equal(ui.renders.length,count);
});

test('loading errors retain usable PDF links and an explicit message', async t => {
  const ui = setup(t);
  ui.viewer.loader = async () => {throw new Error('unavailable');};
  await ui.viewer.open(ui.blob);
  assert.match(ui.viewer.status.textContent,/ouvrir ou télécharger/);
  assert.equal(ui.dialog.querySelector('[data-pdf-download]').getAttribute('href'),'blob:test');
});
