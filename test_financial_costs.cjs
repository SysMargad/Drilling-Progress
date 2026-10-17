const assert=require('node:assert/strict');
const {records,DAILY_LABOR,DAILY_FOOD}=require('./dist/financial-costs.js');
const row=(date,rig,shift,meters,hole='X',hours=12)=>({date,rig,shift,meters,hole,hours});
const source=[row('2026-10-01','C-1800','Өдөр',10),row('2026-10-03','CSD-1300','Өдөр',5)];
const sum=(rows,key)=>rows.reduce((n,row)=>n+row[key],0);
const all=records(source);
assert.equal(all.length,12);
for(const date of ['2026-10-01','2026-10-02','2026-10-03']){
 const day=all.filter(row=>row.date===date);
 assert.equal(sum(day,'laborCost'),DAILY_LABOR['C-1800']+DAILY_LABOR['CSD-1300']);
 assert.equal(sum(day,'foodCost'),DAILY_FOOD);
}
assert.equal(sum(all,'meters'),15);
assert.ok(all.every(row=>row.waterUsageM3===null));
const one=records(source,['C-1800']),two=records(source,['CSD-1300']);
assert.equal(sum(one,'foodCost')+sum(two,'foodCost'),sum(all,'foodCost'));
const changed=records(source.map(row=>({...row,meters:row.meters*10})));
assert.equal(sum(changed,'laborCost'),sum(all,'laborCost'));
assert.equal(sum(changed,'foodCost'),sum(all,'foodCost'));
const split=records([row('2026-10-01','C-1800','Өдөр',4,'A',4),row('2026-10-01','C-1800','Өдөр',8,'B',8)]);
assert.equal(sum(split,'laborCost'),DAILY_LABOR['C-1800']+DAILY_LABOR['CSD-1300']);
assert.equal(sum(split,'foodCost'),DAILY_FOOD);
assert.deepEqual(records([]),[]);
console.log('Financial costs verified: fixed calendar costs, missing reports, meter independence, rig filtering, split shifts, water volume separate from costs.');
