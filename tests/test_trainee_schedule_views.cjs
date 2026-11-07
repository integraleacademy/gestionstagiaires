const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/trainee-sheet.js'),'utf8');
function ui(){
  const ctx=vm.createContext({scheduleView:'plan',bankSnapshot:null,bankLoading:false,bankError:'',readOnly:false,reviewBusy:false,
    esc:String,fmtMoney:n=>Number(n).toFixed(2),scheduleDate:String,isCpfQontoLine:line=>line.financingType==='CPF',hasBankSchedule:()=>true,
    linePaid:line=>line.paid || 0,installmentIsRejected:row=>['refunded','rejected','failed','returned','declined'].includes(row.status),
    operationTable:rows=>rows.map(r=>r.date).join(' '),sameDayNotices:()=>'',scheduleTable:(heads,rows)=>heads.join(' ')+rows.join(' ')});
  for(const name of ['initialTable','scheduleStats','scheduleBalances','initialScheduleSummary','updatedScheduleSummary','reviewSelection','scheduleReadView']){
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
  assert.match(html,/Au moins 1470.00 \/ 1470.00/);assert.doesNotMatch(html,/2026-12-30/);
  assert.equal((html.match(/2026-11-10/g)||[]).length,4);
  ctx.bankSnapshot=null;
  assert.match(ctx.scheduleReadView({},true),/Reste à programmer<\/span><strong>—/);
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

test('planned, paid, scheduled and uncovered amounts stay distinct',()=>{
  const ctx=ui();
  const line = {id:'L',initialDebitSchedule:[{date:'2026-11-04',amount:539.5},{date:'2026-12-04',amount:539.5}]};
  ctx.currentLines=[line,{id:'CPF',financingType:'CPF',paid:3221},{id:'cash',paymentMode:'cash',paid:500}];
  ctx.bankSnapshot={checked_at:'2026-11-07',history:[{id:'reject',status:'declined',amount_cents:53950}],
    upcoming:[{date:'2026-12-04',frequency:'one_off',status:'scheduled',amount_cents:53950,remaining_count:1,remaining_cents:53950}]};
  ctx.scheduleView='bank';
  let html=ctx.scheduleReadView({},true);
  assert.match(html,/539.50 \/ 1079.00/);
  assert.match(html,/Déjà payé<\/span><strong>0.00/);
  assert.match(html,/539.50 à programmer/);
  line.paid=100;
  html=ctx.scheduleReadView({},true);
  assert.match(html,/Reste à payer<\/span><strong>979.00/);
  assert.match(html,/439.50 à programmer/);
  ctx.scheduleView='plan';
  assert.match(ctx.scheduleReadView({},true),/Déjà payé<\/span><strong>100.00/);
  ctx.scheduleView='bank';
  line.paid=539.5;
  assert.match(ctx.scheduleReadView({},true),/Reste à programmer<\/span><strong>0.00/);
  line.paid=1079;
  assert.match(ctx.scheduleReadView({},true),/dépassent le reste à payer de <strong>539.50/);
  ctx.bankError='Lecture Qonto indisponible';
  assert.match(ctx.scheduleReadView({},true),/Reste à programmer<\/span><strong>—/);
});
