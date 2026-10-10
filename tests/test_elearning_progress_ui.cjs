const test = require('node:test');
const assert = require('node:assert/strict');
const {createLiveProgress} = require('../static/js/elearning-progress.js');

class Node {
  constructor(name, attrs = {}, children = []) {
    this.nodeName = name.toUpperCase(); this.nodeType = name.toLowerCase() === '#text' ? 3 : 1;
    this.attrs = {...attrs}; this.dataset = {}; this.childNodes = []; this.parentNode = null;
    this.listeners = {}; this.nodeValue = ''; this.top = 60;
    children.forEach(child => this.insertBefore(typeof child === 'string' ? text(child) : child, null));
  }
  get attributes() { return Object.entries(this.attrs).map(([name,value]) => ({name,value})); }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { return this.parentNode ? this.parentNode.childNodes[this.parentNode.childNodes.indexOf(this)+1] || null : null; }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(child => child.textContent).join(''); }
  set textContent(value) { this.childNodes = [text(value)]; this.childNodes[0].parentNode = this; }
  get open() { return this.hasAttribute('open'); }
  set open(value) { if (value) this.setAttribute('open',''); else this.removeAttribute('open'); }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  hasAttribute(name) { return Object.hasOwn(this.attrs,name); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  removeAttribute(name) { delete this.attrs[name]; }
  insertBefore(child, before) {
    if (child.parentNode) child.parentNode.removeChild(child);
    const at = before ? this.childNodes.indexOf(before) : this.childNodes.length;
    this.childNodes.splice(at,0,child); child.parentNode=this; return child;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child),1); child.parentNode=null; }
  contains(node) { return node === this || this.childNodes.some(child => child.contains(node)); }
  cloneNode() { const result=new Node(this.nodeName,this.attrs,this.childNodes.map(child=>child.cloneNode(true))); result.nodeValue=this.nodeValue; return result; }
  querySelectorAll(selector) {
    const matches = node => selector.startsWith('[') ? node.hasAttribute(selector.slice(1,-1)) : node.nodeName === selector.toUpperCase();
    return this.childNodes.flatMap(child => [...(child.nodeType===1 && matches(child) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(name,callback) { (this.listeners[name] ||= []).push(callback); }
  removeEventListener(name,callback) { this.listeners[name] = (this.listeners[name]||[]).filter(fn=>fn!==callback); }
  dispatch(name,event={}) { (this.listeners[name]||[]).forEach(callback=>callback(event)); }
  getBoundingClientRect() { return {top:this.top}; }
}
const text = value => { const node=new Node('#text'); node.nodeValue=String(value); return node; };
const el = (name, attrs, ...children) => new Node(name,attrs,children);
function report(value='0') {
  return el('div',{'data-el-live-report':'order:learner','data-el-live-url':'/report'},
    el('div',{'data-el-live-status':''},el('span',{'data-el-live-message':''},'Actualisation automatique'),el('a',{'data-el-live-reload':''},'Recharger')),
    el('section',{'data-el-live-region':'metrics'},el('strong',{},value)),
    el('section',{'data-el-live-region':'modules'},
      el('details',{'data-el-live-key':'module-0'},el('summary',{},'Module'),
        el('details',{'data-el-live-key':'section-0'},el('summary',{},'Séquence'),
          el('details',{'data-el-live-key':'production-0'},el('summary',{},'Production'),el('p',{},'Réponse '+value))))),
    el('section',{'data-el-live-region':'exams'},el('p',{},'Score '+value)));
}
function setup(fetchImpl) {
  const root=report(), next=report('75');
  const header=el('header',{},'Navigation conservée');
  const doc=el('document',{},header,root); doc.hidden=false; doc.activeElement=el('body',{});
  const win=new Node('window'); win.navigator={onLine:true}; win.innerWidth=1000;win.innerHeight=600;
  let selection=false; win.getSelection=()=>({isCollapsed:!selection,rangeCount:selection?1:0,getRangeAt:()=>({intersectsNode:()=>true})});
  const timers=new Map();let tid=0;
  win.setTimeout=(callback,delay)=>{const id=++tid;timers.set(id,{callback,delay});return id;};win.clearTimeout=id=>timers.delete(id);
  win.scrollBy=(x,y)=>{win.scroll=[x,y];};doc.elementFromPoint=()=>root.querySelector('details');
  const calls=[];
  const fetchPage=(url,options)=>{calls.push({url,options});return fetchImpl ? fetchImpl(url,options) : Promise.resolve({ok:true,status:200,redirected:false,text:async()=> 'report'});};
  const page={querySelector:()=>next};
  class Parser { parseFromString() { return page; } }
  const controller=createLiveProgress({root,document:doc,window:win,fetch:fetchPage,DOMParser:Parser,AbortController});
  return {root,next,doc,win,timers,calls,header,page,controller,setSelection:value=>{selection=value;},runZero(){for(const [id,item] of [...timers])if(item.delay===0){timers.delete(id);item.callback();}}};
}
const flush = async () => { for(let i=0;i<8;i++)await Promise.resolve(); };

test('refresh updates values without replacing focused or open module/sequence/production nodes',async()=>{
  const ui=setup();
  assert.ok([...ui.timers.values()].some(item=>item.delay===15000));
  const details=ui.root.querySelectorAll('details');details.forEach(node=>node.open=true);
  const summary=details[2].querySelector('summary');ui.doc.activeElement=summary;
  const header=ui.header;await ui.controller.refresh();
  assert.equal(ui.root.querySelector('strong').textContent,'75');
  assert.deepEqual(ui.root.querySelectorAll('details'),details);
  assert.ok(details.every(node=>node.open));
  assert.equal(ui.doc.activeElement,summary);
  assert.equal(ui.header,header);assert.equal(header.textContent,'Navigation conservée');
  assert.equal(ui.win.scroll,undefined);
  assert.equal(ui.calls[0].options.credentials,'same-origin');assert.equal(ui.calls[0].options.cache,'no-store');
  ui.controller.destroy();
});

test('selected text defers updates until selection ends',async()=>{
  const ui=setup();ui.setSelection(true);await ui.controller.refresh();
  assert.equal(ui.root.querySelector('strong').textContent,'0');
  ui.setSelection(false);ui.doc.dispatch('selectionchange');ui.runZero();
  assert.equal(ui.root.querySelector('strong').textContent,'75');ui.controller.destroy();
});

test('a focused node missing in the new structure keeps its region until blur; other metrics update',async()=>{
  const ui=setup();ui.doc.activeElement=ui.root.querySelectorAll('details')[2].querySelector('summary');
  const modules=ui.next.querySelectorAll('[data-el-live-region]')[1];modules.textContent='Module temporairement indisponible';
  await ui.controller.refresh();
  assert.equal(ui.root.querySelector('strong').textContent,'75');assert.equal(ui.root.querySelectorAll('details').length,3);
  ui.doc.activeElement=el('body',{});ui.root.dispatch('focusout');ui.runZero();
  assert.equal(ui.root.querySelectorAll('details').length,0);ui.controller.destroy();
});

test('never overlaps requests; hidden tabs abort and visible/online events request immediately',async()=>{
  let resolve;
  const ui=setup((_url,{signal})=>new Promise((yes,no)=>{resolve=yes;signal.addEventListener('abort',()=>no(new Error('aborted')));}));
  const first=ui.controller.refresh();await ui.controller.refresh();assert.equal(ui.calls.length,1);
  ui.doc.hidden=true;ui.doc.dispatch('visibilitychange');assert.equal(ui.calls[0].options.signal.aborted,true);await first;
  assert.equal(ui.timers.size,0);
  ui.doc.hidden=false;ui.doc.dispatch('visibilitychange');assert.equal(ui.calls.length,2);
  resolve({ok:true,status:200,redirected:false,text:async()=> 'report'});await flush();
  ui.win.navigator.onLine=false;ui.win.dispatch('offline');assert.equal(ui.timers.size,0);
  ui.win.navigator.onLine=true;ui.win.dispatch('online');assert.equal(ui.calls.length,3);
  ui.controller.destroy();await flush();
});

test('timeout aborts a slow request and schedules an automatic network retry',async()=>{
  const ui=setup((_url,{signal})=>new Promise((_yes,no)=>signal.addEventListener('abort',()=>no(new Error('timeout')))));
  const pending=ui.controller.refresh();
  const timeout=[...ui.timers.values()].find(item=>item.delay===10000);assert.ok(timeout);timeout.callback();await pending;
  assert.equal(ui.calls[0].options.signal.aborted,true);
  assert.match(ui.root.querySelector('[data-el-live-message]').textContent,/Nouvelle tentative automatique/);
  assert.ok([...ui.timers.values()].some(item=>item.delay===15000));ui.controller.destroy();
});

test('authentication redirects and unavailable reports stop polling and keep the old content',async()=>{
  for(const response of [{ok:true,status:200,redirected:true},{ok:false,status:403},{ok:false,status:404},{ok:false,status:410}]){
    const ui=setup(async()=>response);await ui.controller.refresh();
    assert.equal(ui.root.querySelector('strong').textContent,'0');assert.equal(ui.timers.size,0);
    assert.equal(ui.root.querySelector('[data-el-live-reload]').hidden,false);
    ui.win.dispatch('online');await ui.controller.refresh();assert.equal(ui.calls.length,1);
    ui.controller.destroy();
  }
});

test('an unexpected report response cannot replace the current learner data',async()=>{
  const ui=setup();ui.next.setAttribute('data-el-live-report','different:learner');await ui.controller.refresh();
  assert.equal(ui.root.querySelector('strong').textContent,'0');assert.equal(ui.timers.size,0);
  assert.match(ui.root.querySelector('[data-el-live-message]').textContent,/vérifiée/);ui.controller.destroy();
});

test('forms added to a report region remain untouched',async()=>{
  const ui=setup();const region=ui.root.querySelectorAll('[data-el-live-region]')[2];const form=el('form',{},el('input',{'value':'brouillon'}));region.insertBefore(form,null);
  await ui.controller.refresh();assert.equal(region.querySelector('form'),form);assert.equal(region.textContent,'Score 0');
  assert.equal(ui.root.querySelector('strong').textContent,'75');ui.controller.destroy();
});


test('temporary server errors retry automatically with bounded backoff then recover',async()=>{
  let status=503;const ui=setup(async()=>status===200 ? {ok:true,status,redirected:false,text:async()=> 'report'} : {ok:false,status});
  for(const delay of [15000,30000,60000,60000]){
    await ui.controller.refresh();
    assert.equal(ui.root.querySelector('strong').textContent,'0');
    assert.ok([...ui.timers.values()].some(item=>item.delay===delay));
    assert.match(ui.root.querySelector('[data-el-live-message]').textContent,/Nouvelle tentative automatique/);
    status=429;
  }
  status=200;await ui.controller.refresh();
  assert.equal(ui.root.querySelector('strong').textContent,'75');
  assert.ok([...ui.timers.values()].some(item=>item.delay===15000));ui.controller.destroy();
});


test('a new item before an open production preserves the production and focused reading until blur',async()=>{
  const ui=setup();const production=ui.root.querySelectorAll('details')[2];production.open=true;ui.doc.activeElement=production.querySelector('summary');
  const freshProduction=ui.next.querySelectorAll('details')[2];freshProduction.parentNode.insertBefore(el('p',{},'Nouvelle information'),freshProduction);
  await ui.controller.refresh();assert.equal(production.open,true);assert.equal(ui.root.querySelectorAll('details')[2],production);
  assert.ok(!ui.root.textContent.includes('Nouvelle information'));
  ui.doc.activeElement=el('body',{});ui.root.dispatch('focusout');ui.runZero();
  assert.ok(ui.root.textContent.includes('Nouvelle information'));assert.equal(ui.root.querySelectorAll('details')[2],production);assert.equal(production.open,true);ui.controller.destroy();
});

test('the viewport anchor is retained when updated content above it changes height',async()=>{
  const ui=setup();const anchor=ui.root.querySelector('details');
  anchor.getBoundingClientRect=()=>({top:ui.root.querySelector('strong').textContent==='0'?60:90});
  await ui.controller.refresh();assert.deepEqual(ui.win.scroll,[0,30]);ui.controller.destroy();
});
