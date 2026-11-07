const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const sheet=fs.readFileSync(path.join(__dirname,'../static/js/trainee-sheet.js'),'utf8');

function scheduleContext(){
  const ui=vm.createContext({isoToday:()=>'2026-11-07',bankSnapshot:null,scheduleView:'plan',
    scheduleDate:s=>s,fmtMoney:n=>Number(n).toFixed(2),installmentDate:r=>r?.date||''});
  for(const name of ['localBankRows','sameDayNotices','contractualDate']){
    const start=sheet.indexOf('  function '+name+'(');
    assert.notEqual(start,-1);
    const end=sheet.indexOf('\n  }',start)+4;
    vm.runInContext(sheet.slice(start,end),ui);
  }
  return ui;
}

test('three independent retries on the same day and one recurring subscription',()=>{
  const ui=scheduleContext();
  const row=(id,date,more={})=>({qonto_direct_debit_subscription_id:id,date,amount:367.5,status:'scheduled',...more});
  const future=[row('a','2026-11-10',{excluded_from_schedule_totals:true}),row('b','2026-11-10',{tracking_removed_at:'2026-11-01'}),
    row('c','2026-11-17',{tracking_pending_qonto:true,qonto_original_due_date:'2026-11-10',qonto_original_amount:367.5,amount:400}),
    row('a','2026-11-10'),row('monthly','2026-12-30'),row('monthly','2026-11-30'),
    row('stale','2026-11-10'),row('stale','2026-11-10',{status:'failed'}),
    row('', '2026-11-10',{manual_tracking_entry:true}),row('cancel','2026-11-10',{qonto_subscription_status:'canceled'})];
  const bank=ui.localBankRows(future);
  assert.deepEqual(Array.from(bank,x=>x.id),['a','b','c','monthly']);
  assert.match(ui.sameDayNotices(bank),/3 prélèvements.*1102\.50/);
  assert.equal(bank.at(-1).date,'2026-11-30');
});

test('original month survives a retry or a local date edit',()=>{
  const ui=scheduleContext();
  ui.installmentSchedulePosition=(item,fallback)=>item.schedule_index||fallback;
  const retry={date:'2026-11-10',index:1,is_rejection_retry:true,line:{directDebitInstallments:[{date:'2026-09-30',schedule_index:1}]}};
  assert.equal(ui.contractualDate(retry),'2026-09-30');
  assert.equal(ui.contractualDate({...retry,tracking_pending_qonto:true}),'2026-11-10');
});
