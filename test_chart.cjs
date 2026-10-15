const assert=require('node:assert/strict');
const {aggregate,title}=require('./dist/chart-model.js');
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
assert.throws(()=>aggregate(rows,'year'));
console.log('Chart verified: totals, 4 periods, per-rig norms, year/week boundary, leap-year month, filters.');
