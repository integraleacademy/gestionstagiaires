const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const source=readFileSync(join(__dirname,'../static/js/trainee-sheet.js'),'utf8');
function setup(snapshot={}) {
  const ctx=vm.createContext({bankSnapshot:snapshot,fmtMoney:n=>n+' EUR',formatIsoDateFr:s=>s,scheduleDate:s=>s,
    esc:s=>String(s).replaceAll('<','&lt;'),installmentDate:r=>r?.date || r?.due_date || '',
    installmentFailureReasonLabel:()=>'',badge:s=>s,bankStates:{returned:['Retourné','red'],scheduled:['Programmé','blue'],
      canceled:['Annulé','gray'],completed:['Encaissé','green']}});
  for (const name of ['scheduleTable','scheduleEventDate','scheduleEventsTable','scheduleAuditEvents','debitActivity']) {
    const start=source.indexOf('  function '+name+'('),end=source.indexOf('\n  function ',start+4);
    assert.notEqual(start,-1);
    vm.runInContext(source.slice(start,end),ctx);
  }
  return ctx;
}
test('a removal is shown once on its edit day, including when the edit log has been pruned',()=>{
  const ctx=setup();
  const row={index:2,date:'2026-12-04',amount:539.50,status:'scheduled'};
  const at='2026-11-06T23:22:03Z',after={...row,tracking_removed_at:at};
  const line={id:'L',directDebitInstallments:[after],financial_tracking_override:{edit_history:[
    {at,action:'delete',before:[row],after:[after],by:'Admin'}]}};
  assert.equal(ctx.debitActivity([line],'2026-11-07').history.length,0);
  for(const history of [line.financial_tracking_override.edit_history,[]]){
    line.financial_tracking_override.edit_history=history;
    const journal=ctx.scheduleAuditEvents([line]);
    assert.equal(journal.length,1);
    assert.equal(journal[0].date,at);
    const html=ctx.scheduleEventsTable(journal,'',false,'history');
    assert.match(html,/2026-11-07<\/time>/); assert.match(html,/00:22/);
    assert.match(html,/Échéance du 2026-12-04/); assert.doesNotMatch(html,/Enregistrée|2026-12-04<\/time>/);
  }
});
test('dated activity sorts by actual time in Paris, respecting offsets, day-only dates and invalid legacy dates',()=>{
  const ctx=setup(), template={state:['Encaissé','green'],source:'Qonto',amount:1};
  const records=[['first','2026-11-04T17:00:10+01:00'],['last','2026-11-04T16:00:12Z'],
    ['cross','2026-11-04T23:20:00Z'],['day','04/11/2026'],['invalid','31/02/2026']].map(([label,date])=>({...template,date,label,key:label}));
  const html=ctx.scheduleEventsTable(records,'',false,'history');
  const names=['cross','last','first','day','invalid'].map(label=>html.indexOf('<td>'+label+'<'));
  assert.ok(names.every(i=>i>=0));assert.deepEqual(names,[...names].sort((a,b)=>a-b));
  assert.match(html,/2026-11-05<\/time><small[^>]*>00:20/);
  assert.match(html,/Opérations sans date communiquée \(1\)/);
  assert.doesNotMatch(html,/31\/02|Date inconnue/);
});
test('two verified returns remain two distinct attempts; related undated one-off cancellations share one item',()=>{
  const ctx=setup({history:['collection-48123','collection-09201'].map(id=>({id,status:'returned',
    date:'2026-11-04',amount_cents:53950})),changes:[
    {kind:'subscription',id:'sub',status:'canceled',frequency:'one_off',amount_cents:53950,planned_date:'2026-12-04'},
    {kind:'collection',id:'col',subscription_id:'sub',status:'canceled',amount_cents:53950,planned_date:'2026-12-04'},
  ]});
  const journal=ctx.debitActivity([],'2026-11-07').history;
  assert.equal(journal.length,3);
  const html=ctx.scheduleEventsTable(journal,'',false,'history');
  assert.match(html,/Réf\. …on-48123/);assert.match(html,/Réf\. …on-09201/);
  assert.equal((html.match(/Retourné/g)||[]).length,2);
  assert.match(html,/Annulations sans date communiquée par Qonto \(1\)/);
  assert.match(html,/Prélèvement et programmation annulés/);
  assert.ok(html.indexOf('Annulations sans date')<html.indexOf('2026-12-04'));
  ctx.bankSnapshot.changes[0].date='2026-11-06';
  assert.equal(ctx.debitActivity([],'2026-11-07').history.length,4);
});
