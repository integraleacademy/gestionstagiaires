const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/trainee-sheet.js'),'utf8');
function ui(){
  const ctx=vm.createContext({scheduleView:'plan',bankSnapshot:null,bankLoading:false,bankError:'',readOnly:false,reviewBusy:false,
    esc:String,fmtMoney:n=>Number(n).toFixed(2),scheduleDate:String,isCpfQontoLine:()=>false,hasBankSchedule:()=>true,
    operationTable:rows=>rows.map(r=>r.date).join(' '),sameDayNotices:()=>'',scheduleTable:(heads,rows)=>heads.join(' ')+rows.join(' ')});
  for(const name of ['initialTable','reviewSelection','scheduleReadView']){
    const start=source.indexOf('  function '+name+'(');assert.notEqual(start,-1);
    const end=source.indexOf('\n  function ',start+1);
    vm.runInContext(source.slice(start,end),ctx);
  }
  return ctx;
}
test('four original months stay independent from the bank next occurrences and its total',()=>{
  const ctx=ui();
  ctx.currentLines=[{id:'L',initialDebitSchedule:['09','10','11','12'].map(m=>({date:'2026-'+m+'-30',amount:367.5}))}];
  ctx.bankSnapshot={checked_at:'2026-11-07T04:00:00Z',upcoming:['10','10','10','30'].map(d=>({date:'2026-11-'+d,amount_cents:36750,status:'scheduled',frequency:d==='30'?'monthly':'one_off'}))};
  let html=ctx.scheduleReadView({},true);
  assert.match(html,/Échéancier initial/);assert.match(html,/2026-12-30/);assert.doesNotMatch(html,/Prévue au plan|Impayée|2026-11-10/);
  ctx.scheduleView='bank';html=ctx.scheduleReadView({},true);
  assert.match(html,/Total des prélèvements programmés<\/span><strong>1470.00/);assert.doesNotMatch(html,/2026-12-30/);
  assert.equal((html.match(/2026-11-10/g)||[]).length,4);
  ctx.bankSnapshot=null;
  assert.doesNotMatch(ctx.scheduleReadView({},true),/1470.00|2026-12-30/);
});
test('review selects each visible rejection once and reopens only for a new collection',()=>{
  const ctx=ui(),lines=[{id:'L',debitRejectionReview:{pending:['collection:A'],treated:['collection:B']}}];
  ctx.bankSnapshot={rejectionKeys:{L:['collection:A','collection:B','collection:C']}};
  assert.deepEqual(Array.from(ctx.reviewSelection(lines).L),['collection:A','collection:C']);
  lines[0].debitRejectionReview={pending:[],treated:['collection:A','collection:B','collection:C']};
  assert.deepEqual(Object.keys(ctx.reviewSelection(lines)),[]);
  ctx.bankSnapshot.rejectionKeys.L.push('collection:D');
  assert.deepEqual(Array.from(ctx.reviewSelection(lines).L),['collection:D']);
});
