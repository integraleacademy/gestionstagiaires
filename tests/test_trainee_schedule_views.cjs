const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/trainee-sheet.js'),'utf8');
function ui(){
  const ctx=vm.createContext({scheduleView:'plan',bankSnapshot:null,bankLoading:false,bankError:'',readOnly:false,reviewBusy:false,
    currentFinancialSummary:null,window:{},document:{getElementById:()=>null},formatIsoDateFr:String,installmentDate:r=>r.date || r.due_date || '',
    installmentFailureReasonLabel:()=>'',bankTransferLabel:()=> 'Personnel',badge:(s)=>s,
    bankStates:{declined:['Rejeté','red'],scheduled:['Programmé','blue'],completed:['Encaissé','green'],canceled:['Annulé','gray']},
    Date:class extends Date{constructor(...args){super(...(args.length?args:['2026-11-07T12:00:00Z']));}},
    esc:String,fmtMoney:n=>Number(n).toFixed(2),scheduleDate:String,isCpfQontoLine:line=>line.financingType==='CPF',hasBankSchedule:()=>true,
    linePaid:line=>line.paid || 0,installmentIsRejected:row=>['refunded','rejected','failed','returned','declined'].includes(row.status),
    operationTable:rows=>rows.map(r=>r.date).join(' '),sameDayNotices:()=>'',scheduleTable:(heads,rows)=>heads.join(' ')+rows.join(' ')});
  for(const name of ['paymentMethodTotals','initialTable','scheduleStats','scheduleBalances','initialScheduleSummary','updatedScheduleSummary','reviewSelection','dossierBalance','scheduleEventsTable','transferEvents','cashScheduleEvents','debitActivity','scheduleAuditEvents','financialScheduleSummary','scheduleReadView']){
    const start=source.indexOf('  function '+name+'(');assert.notEqual(start,-1);
    const end=source.indexOf('\n  function ',start+1);
    vm.runInContext(source.slice(start,end),ctx);
  }
  return ctx;
}
function finance(ctx){
  const sepa=ctx.currentLines[0], totals=ctx.scheduleBalances([sepa]);
  return {objectifFacturation:totals.planned/100,totalPaye:totals.paid/100,resteAPayer:totals.outstanding/100,
    progressPaiement:totals.planned?100*totals.paid/totals.planned:0,cashPaid:0};
}
test('four original months stay independent from the bank next occurrences and its total',()=>{
  const ctx=ui();
  ctx.currentLines=[{id:'L',initialDebitSchedule:['09','10','11','12'].map(m=>({date:'2026-'+m+'-30',amount:367.5}))}];
  ctx.bankSnapshot={checked_at:'2026-11-07T04:00:00Z',upcoming:['10','10','10','30'].map(d=>({date:'2026-11-'+d,amount_cents:36750,status:'scheduled',frequency:d==='30'?'monthly':'one_off'}))};
  let html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/Échéancier initial/);assert.match(html,/2026-12-30/);assert.doesNotMatch(html,/Prévue au plan|Impayée|2026-11-10/);
  ctx.scheduleView='next';html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/Au moins 1470.00 \/ 1470.00/);assert.doesNotMatch(html,/2026-12-30/);
  assert.equal((html.match(/2026-11-10/g)||[]).length,4);
  ctx.bankSnapshot=null;
  assert.match(ctx.scheduleReadView(finance(ctx),true),/Reste à programmer<\/span><strong>—/);
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
  ctx.scheduleView='next';
  let html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/539.50 \/ 1079.00/);
  assert.match(html,/Déjà payé<\/span><strong>0.00/);
  assert.match(html,/539.50 à programmer/);
  line.paid=100;
  html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/Reste à payer<\/span><strong>979.00/);
  assert.match(html,/439.50 à programmer/);
  ctx.scheduleView='plan';
  assert.match(ctx.scheduleReadView(finance(ctx),true),/Déjà payé<\/span><strong>100.00/);
  ctx.scheduleView='next';
  line.paid=539.5;
  assert.match(ctx.scheduleReadView(finance(ctx),true),/Reste à programmer<\/span><strong>0.00/);
  line.paid=1079;
  assert.match(ctx.scheduleReadView(finance(ctx),true),/dépassent le reste à payer de <strong>539.50/);
  ctx.bankError='Lecture Qonto indisponible';
  assert.match(ctx.scheduleReadView(finance(ctx),true),/Reste à programmer<\/span><strong>—/);
});

test('six tabs share the hors-CPF balance, including cash and transfers without a SEPA plan',()=>{
  const ctx=ui();
  ctx.currentLines=[{id:'L',financingType:'PERSONNEL',qontoBankTransferPaidCents:10000,qontoBankTransfers:[
    {id:'TR',amount_cents:10000,paid_at:'2026-11-04',status:'completed',payer_name:'Payeur A'},
    {id:'TR',amount_cents:10000,paid_at:'2026-11-04',status:'completed',payer_name:'Payeur A'},
    {id:'REV',amount_cents:30000,paid_at:'2026-11-02',status:'reversed',payer_name:'Payeur B'}]}];
  const c={objectifFacturation:1000,totalPaye:150,resteAPayer:850,progressPaiement:15,
    prixFormation:4000,montantCpf:3000,personalFundingPlanned:1000,otherFundingPlanned:0,
    totalFacture:1000,resteAFacturer:0,cashPaid:50,qontoPaymentEntries:[{source:'qonto_bank_transfer',paid_amount_cents:10000}]};
  const keys=['plan','past','next','history','transfers','summary'];
  for(const key of keys){
    ctx.scheduleView=key;
    const html=ctx.scheduleReadView(c,true);
    assert.deepEqual([...html.matchAll(/data-schedule-view="([^"]+)"/g)].map(m=>m[1]),keys);
    assert.match(html,/Total prévu<\/span><strong>1000.00/);
    assert.match(html,/Déjà payé<\/span><strong>150.00/);
    assert.match(html,/Reste à payer<\/span><strong>850.00/);
    if(key==='transfers'||key==='history'){
      assert.equal((html.match(/Payeur A/g)||[]).length,1);
      assert.match(html,/Contrepassé/);
    }
    if(key==='history')assert.match(html,/Règlement en espèces/);
    if(key==='transfers')assert.match(html,/Rattacher un virement/);
    if(key==='summary')assert.match(html,/Espèces<\/span><strong>50.00/);
  }
  ctx.scheduleView='transfers'; ctx.readOnly=true;
  assert.doesNotMatch(ctx.scheduleReadView(c,false),/data-schedule-transfer/);
});

test('past, due today, upcoming and cancelled records remain distinct and matched local rows do not repeat',()=>{
  const ctx=ui();
  ctx.currentLines=[{id:'L',financingType:'PERSONNEL',initialDebitSchedule:[{date:'2026-11-04',amount:100}],
    directDebitInstallments:[{date:'2026-11-04',amount:100,status:'declined',qonto_direct_debit_collection_id:'collection-A'}]}];
  ctx.bankSnapshot={checked_at:'2026-11-07',history:[{id:'collection-A',date:'2026-11-04',status:'declined',amount_cents:10000}],
    changes:[{id:'cancel',kind:'subscription',date:'2026-11-05',planned_date:'2026-12-12',amount_cents:10000}],
    upcoming:[{id:'today',date:'2026-11-07',status:'scheduled',amount_cents:2000},
      {id:'future',date:'2026-11-15',status:'scheduled',amount_cents:3000,open_collections:[
        {id:'in-flight',subscription_id:'future',date:'2026-11-03',status:'processing',amount_cents:3000}]}]};
  ctx.scheduleView='past';
  let html=ctx.scheduleReadView(finance(ctx),true);
  assert.equal((html.match(/collection-A<\/span>/g)||[]).length,1);
  assert.match(html,/2026-11-03/);
  assert.doesNotMatch(html,/2026-11-15|2026-12-12|Programmation annulée/);
  ctx.scheduleView='next';html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/2026-11-07/);assert.match(html,/2026-11-15/);assert.doesNotMatch(html,/collection-A|in-flight/);
  ctx.scheduleView='history';html=ctx.scheduleReadView(finance(ctx),true);
  assert.match(html,/Programmation annulée/);assert.match(html,/2026-12-12/);
});
