(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AuditModel=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Rig-shift audit published by the Drive sync (shift_audit.py): every day and night slot of each rig,
  // classified from evidence. A slot without a report is never shown as 0 m.
  const STATUSES=['VERIFIED_DRILLING','VERIFIED_NON_DRILLING','MISSING_REPORT','SOURCE_CONFLICT','UNVERIFIED'];
  const LABELS={VERIFIED_DRILLING:'Баталгаажсан өрөмдлөг',VERIFIED_NON_DRILLING:'Баталгаажсан, өрөмдөөгүй',
    MISSING_REPORT:'Тайлан дутуу',SOURCE_CONFLICT:'Эх сурвалжийн зөрчил',UNVERIFIED:'Баталгаажаагүй'};
  const months=audit=>(audit?.months||[]).map(month=>month.month);
  const slots=(audit,month,rig='')=>(audit?.slots||[]).filter(s=>s.date.startsWith(month+'-')&&(!rig||s.rig===rig));
  function summary(audit,month,rig=''){
    const list=slots(audit,month,rig),counts=Object.fromEntries(STATUSES.map(s=>[s,0])),meters=Object.fromEntries(STATUSES.map(s=>[s,0]));
    for(const slot of list){counts[slot.status]++;meters[slot.status]+=slot.meters||0;}
    // Unreported metres are counted per hole gap, which can span both rigs' slots; shown for all rigs only.
    const published=(audit?.months||[]).find(m=>m.month===month);
    return {expected:list.length,days:new Set(list.map(s=>s.date)).size,counts,meters,missingMeters:rig?null:published?.missingMeters??null};
  }
  const order=shift=>shift==='Өдөр'?0:1;
  // Freshness is the latest reported shift of each rig, not the time the sync last ran.
  const freshness=(shifts,rigs)=>rigs.map(rig=>{
    const last=shifts.filter(s=>s.rig===rig).sort((a,b)=>a.date.localeCompare(b.date)||order(a.shift)-order(b.shift)).at(-1);
    return {rig,date:last?.date||'',shift:last?.shift||''};
  });
  function lastSync(log){
    const success=[...log].reverse().find(e=>e.status==='updated'||e.status==='unchanged'),last=log.at(-1);
    return {success:success?.completedAt||'',attempt:last?.completedAt||last?.startedAt||'',status:last?.status||'',validation:last?.validation||last?.error||''};
  }
  const key=slot=>slot.rig+'|'+slot.date+'|'+slot.shift;
  const index=audit=>new Map((audit?.slots||[]).map(slot=>[key(slot),slot]));
  return {STATUSES,LABELS,months,slots,summary,freshness,lastSync,key,index};
});
