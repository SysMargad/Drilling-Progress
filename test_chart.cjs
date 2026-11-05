const assert=require('node:assert/strict');
const {aggregate,fill,title,depthSeries}=require('./dist/chart-model.js');
const real=require('./dist/data.json');
for(const grain of ['shift','day','week','month']){
  const groups=aggregate(real.shifts,grain);
  assert.ok(groups.length);
  const total=real.shifts.reduce((a,s)=>a+s.meters,0);
  assert.ok(Math.abs(groups.reduce((a,g)=>a+Object.values(g.amounts).reduce((x,y)=>x+y,0),0)-total)<1e-6);
  assert.ok(groups.every(g=>g.target===(grain==='month'?new Date(g.end+'T00:00:00Z').getUTCDate()*60:{shift:30,day:60,week:420}[grain])));
}
assert.equal(aggregate(real.shifts,'shift').length,new Set(real.shifts.map(s=>s.date+'|'+s.shift)).size);
assert.equal(aggregate(real.shifts,'day').length,new Set(real.shifts.map(s=>s.date)).size);
const row=(date,shift,rig,meters)=>({date,shift,rig,meters});
const rows=[row('2026-12-31','Шөнө','C-1800',20),row('2027-01-01','Өдөр','CSD-1300',40)];
assert.equal(aggregate(rows,'week').length,1);
assert.equal(aggregate(rows,'month').length,2);
assert.ok(title(aggregate(rows,'day')).includes('2026.12 – 2027.01'));
const feb=aggregate([row('2028-02-29','Өдөр','C-1800',15)],'month')[0];
assert.equal(feb.target,1740);
assert.equal(feb.end,'2028-02-29');
const multi=aggregate([row('2026-10-01','Өдөр','C-1800',15),row('2026-10-01','Шөнө','C-1800',25),row('2026-10-01','Өдөр','CSD-1300',35)],'day')[0];
assert.equal(multi.amounts['C-1800'],40);assert.equal(multi.amounts['CSD-1300'],35);assert.equal(multi.target,60);
assert.equal(aggregate(rows.filter(r=>r.rig==='C-1800'),'day')[0].amounts['CSD-1300'],undefined);
assert.deepEqual(aggregate([],'day'),[]);
for(const month of [...new Set(real.shifts.map(s=>s.date.slice(0,7)))])for(const grain of ['shift','day','week','month']){
 const selected=aggregate(real.shifts,grain,month),expected=real.shifts.filter(s=>s.date.startsWith(month+'-'));
 assert.ok(Math.abs(selected.reduce((n,g)=>n+Object.values(g.amounts).reduce((a,b)=>a+b,0),0)-expected.reduce((n,s)=>n+s.meters,0))<1e-6);
 assert.ok(selected.every(g=>g.start.startsWith(month)&&g.end.startsWith(month)&&g.rows.every(s=>s.date.startsWith(month))));
}
const clipped=aggregate([row('2026-10-01','Өдөр','C-1800',20),row('2026-10-31','Шөнө','C-1800',30),row('2026-11-01','Өдөр','C-1800',40)],'week','2026-10');
assert.equal(clipped[0].start,'2026-10-01');assert.equal(clipped[0].target,240);
assert.equal(clipped.at(-1).end,'2026-10-31');assert.equal(clipped.at(-1).target,360);
assert.deepEqual(aggregate(real.shifts,'day','2020-01'),[]);
assert.throws(()=>aggregate(real.shifts,'day','2026-13'));
assert.throws(()=>aggregate(rows,'year'));
const hole=real.collar.find(h=>real.shifts.some(s=>s.hole===h.id));
const actualRows=real.shifts.filter(s=>s.hole===hole.id);
const profile=depthSeries(real.shifts,hole.id).flat();
assert.ok(profile.every(p=>p.depth<=0));
assert.equal(profile.at(-1).depth,-actualRows.sort((a,b)=>a.date.localeCompare(b.date)||(a.shift==='Өдөр'?0:1)-(b.shift==='Өдөр'?0:1)).at(-1).to);
assert.deepEqual(depthSeries(real.shifts,'UNKNOWN'),[]);
assert.deepEqual(depthSeries([...real.shifts].reverse(),hole.id),depthSeries(real.shifts,hole.id));
const gaps=[{hole:'X',rig:'C-1800',date:'2026-10-01',shift:'Өдөр',from:0,to:20},{hole:'X',rig:'C-1800',date:'2026-10-03',shift:'Өдөр',from:20,to:40}];
assert.equal(depthSeries(gaps,'X').length,2);
const connected=[gaps[0],{...gaps[1],date:'2026-10-01',shift:'Шөнө'}];
assert.equal(depthSeries(connected,'X').length,1);
assert.deepEqual(depthSeries(connected,'X')[0].map(p=>p.depth),[-0,-20,-40]);
console.log('Chart verified: totals, 4 periods, per-rig norms, year/week boundary, leap-year month, filters.');
console.log('Depth profile verified: negative depths, shift order, missing holes and unreported intervals.');
for(const grain of ['shift','day','week','month']){
 const groups=aggregate(real.shifts,grain);
 assert.equal(groups.flatMap(g=>g.rows).length,real.shifts.length);
 for(const group of groups)for(const row of group.rows){
  assert.ok(row.date>=group.start&&row.date<=group.end);
  assert.ok(row.reports.every(r=>r.rig===row.rig&&r.hole===row.hole&&r.date===row.date&&r.shift===row.shift));
 }
}
console.log('Report provenance preserved across all aggregation periods.');

// Overview chart, KPI cards and rig performance use the same month or all-time rows.
const fs=require('node:fs'),vm=require('node:vm');
let overviewRig='',overviewArea='';
const overviewContext=vm.createContext({DrillingChart:require('./dist/chart-model.js'),AuditModel:require('./dist/audit-model.js'),document:{
 addEventListener:()=>{},querySelector:s=>({value:s==='#site'?'Нэргүй Өндөр':s==='#rig'?overviewRig:s==='#area'?overviewArea:'',hidden:true})
},window:{addEventListener:()=>{}}});
const appSource=fs.readFileSync('dist/app.js','utf8');
vm.runInContext(appSource.split('function dataRows()')[0]+appSource.slice(appSource.indexOf('let auditMonth'),appSource.indexOf('function auditCell')),overviewContext);
overviewContext.fixture=real;
vm.runInContext('D=fixture',overviewContext);
for(const month of ['2026-10','2026-11','','2026-10','']){
 overviewContext.monthUnderTest=month;
 vm.runInContext('chartMonth=monthUnderTest',overviewContext);
 for(const rig of ['', 'C-1800','CSD-1300']){
  overviewRig=rig;
  const expected=real.shifts.filter(s=>(!month||s.date.startsWith(month+'-'))&&(!rig||s.rig===rig));
  const selected=vm.runInContext('overviewRows()',overviewContext);
  assert.equal(selected.length,expected.length);
  assert.equal(selected.reduce((n,r)=>n+r.meters,0),expected.reduce((n,r)=>n+r.meters,0));
  for(const period of ['shift','day','week','month']){
   overviewContext.periodUnderTest=period;
   const html=vm.runInContext('grain=periodUnderTest;chart()',overviewContext);
   const bars=vm.runInContext('chartBars',overviewContext);
   assert.ok(Math.abs(bars.reduce((n,r)=>n+r.meters,0)-expected.reduce((n,r)=>n+r.meters,0))<1e-6);
   assert.ok(html.includes('>Нийт хугацаа</option>'));
   assert.equal(vm.runInContext('chartMonth',overviewContext),month);
  }
  const cards=vm.runInContext('rigs()',overviewContext),kpis=vm.runInContext('kpis()',overviewContext);
  for(const name of rig?[rig]:['C-1800','CSD-1300']){
   const rows=expected.filter(s=>s.rig===name),meters=rows.reduce((n,r)=>n+r.meters,0);
   assert.ok(cards.includes(`<span>${meters.toLocaleString('en-US',{maximumFractionDigits:1})} м</span>`));
   assert.ok(cards.includes(`<span>${rows.length} ээлж</span>`));
  }
  assert.ok(kpis.includes(expected.reduce((n,r)=>n+r.meters,0).toLocaleString('en-US',{maximumFractionDigits:1})));
 }
}
overviewRig='';overviewArea='Харгант';
assert.ok(vm.runInContext('overviewRows()',overviewContext).every(s=>real.collar.some(h=>h.id===s.hole&&h.targetArea==='Харгант')));
console.log('Overview month filtering verified: chart, KPIs, rig performance, all-time reset, period grouping and rig/area filters.');

// A month's shift and day axes keep every period up to the audit date; an unreported shift is a gap with a mark, never a 0 m bar.
const sparse=[row('2026-10-01','Өдөр','C-1800',15),row('2026-10-03','Шөнө','C-1800',30)].map(r=>({...r,hole:'DTDH2603'}));
const filled=fill(aggregate(sparse,'shift','2026-10'),'shift','2026-10','2026-10-04');
assert.deepEqual(filled.map(g=>g.key),['2026-10-01|0','2026-10-01|1','2026-10-02|0','2026-10-02|1','2026-10-03|0','2026-10-03|1','2026-10-04|0','2026-10-04|1']);
assert.deepEqual(filled[1],{key:'2026-10-01|1',label:'01',secondary:'Ш',start:'2026-10-01',end:'2026-10-01',target:30,amounts:{},counts:{},rows:[]});
assert.equal(fill(aggregate(sparse,'day','2026-10'),'day','2026-10').length,31);
assert.equal(fill(aggregate(sparse,'week','2026-10'),'week','2026-10').length,aggregate(sparse,'week','2026-10').length);
assert.equal(fill(aggregate(sparse,'day'),'day','').length,2,'the all-time view is not filled');
const slot=(date,shift,status)=>({rig:'C-1800',date,shift,status,meters:null,records:[],issues:[{kind:'gap',text:'DTDH2603: 248–257 м (9 м) тайлангүй'}],folderUrl:''});
overviewContext.fixture={...real,shifts:sparse,shiftAudit:{through:'2026-10-04',rigs:['C-1800','CSD-1300'],months:[],slots:[slot('2026-10-01','Шөнө','MISSING_REPORT'),slot('2026-10-02','Өдөр','UNVERIFIED')]}};
overviewArea='';
vm.runInContext("D=fixture;chartMonth='2026-10';grain='shift'",overviewContext);
let marked=vm.runInContext('chart()',overviewContext);
assert.equal((marked.match(/class="audit-mark audit-missing-report"/g)||[]).length,1);
assert.equal((marked.match(/class="audit-mark audit-unverified"/g)||[]).length,1);
assert.ok(marked.includes('2026-10-01 Шөнө · C-1800 · Тайлан дутуу · тайлангүй — DTDH2603: 248–257 м (9 м) тайлангүй'));
assert.equal(vm.runInContext('chartBars.length',overviewContext),2,'unreported shifts get no bar');
overviewArea='Замт Хөндий';
assert.ok(!vm.runInContext('chart()',overviewContext).includes('audit-mark'),'an area filter hides other areas, so no marks');
overviewArea='';
console.log('Month axes keep unreported shifts in place, marked from the shift audit.');
