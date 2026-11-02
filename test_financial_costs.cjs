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

const {MUD_PRICE_PER_BAG,MUD_BAG_KG}=require('./dist/financial-costs.js');
assert.equal(sum(all,'fuelUsageL'),0); // No inferred issues without a ledger.
for(const item of all){
 assert.equal(item.fuelCost,0);
 assert.ok(Math.abs(item.mudUsageBags*MUD_PRICE_PER_BAG-item.mudCost)<1e-6);
 assert.ok(Math.abs(item.mudUsageBags*MUD_BAG_KG-item.mudUsageKg)<1e-9);
}
assert.equal(sum(split,'fuelUsageL'),0);
assert.equal(sum(all.filter(r=>!r.recorded),'fuelUsageL'),0);
assert.equal(sum(all.filter(r=>!r.recorded),'mudUsageKg'),0);
console.log('Consumption verified: units reconcile with cost, both rigs, split rows and empty periods.');

const waterModel={litresPerTrip:5000,estimated:true,records:[
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',trips:1,litres:5000},
 {date:'2026-10-03',rig:'CSD-1300',shift:'Шөнө',hole:'NEW',trips:1,litres:5000}]};
const waterRows=records([
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',meters:10,hours:6,waterUsageM3:5,waterUsageEstimated:true},
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',meters:20,hours:6,waterUsageM3:5,waterUsageEstimated:true},
 {date:'2026-10-02',rig:'C-1800',shift:'Өдөр',hole:'A',meters:0,hours:12,waterUsageM3:null}
],['C-1800','CSD-1300'],null,null,null,waterModel);
assert.equal(waterRows.reduce((n,r)=>n+(r.waterUsageM3||0)*1000,0),10000);
assert.equal(waterRows.filter(r=>r.waterRecorded).length,3);
assert.ok(waterRows.some(r=>r.date==='2026-10-02'&&r.waterUsageM3===null));
assert.equal(waterRows.reduce((n,r)=>n+r.fuelCost,0),0);
assert.ok(waterRows.some(r=>r.hole==='NEW'&&!r.recorded&&r.waterEstimated));
console.log('Water estimates verified: litres, split records without duplicate deliveries, missing reports retained, no water-truck fuel.');
const dailyWater={estimated:false,records:[],dailyRecords:[{date:'2026-10-01',rig:'C-1800',trips:2,litres:10000}]};
const dailyRows=records([{...source[0],waterUsageM3:5}],['C-1800'],null,null,null,dailyWater);
assert.equal(dailyRows.reduce((n,r)=>n+(r.waterUsageM3||0)*1000,0),10000);
const journalRow=dailyRows.find(r=>r.shift==='Өдрийн нийт');
assert.ok(journalRow.waterRecorded&&!journalRow.recorded&&!journalRow.waterEstimated);
assert.equal(journalRow.laborCost+journalRow.foodCost+journalRow.fuelCost,0);

const mud={totalBags:17,bagKg:25,pricePerBag:330000,allocations:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',bags:17}]};
const divided=records([row('2026-10-01','C-1800','Өдөр',10,'A',6),row('2026-10-01','C-1800','Өдөр',20,'A',6),row('2026-10-02','C-1800','Өдөр',100,'B')],undefined,mud);
assert.ok(Math.abs(sum(divided,'mudUsageBags')-17)<1e-9);
assert.ok(Math.abs(sum(divided,'mudUsageKg')-425)<1e-9);
assert.ok(Math.abs(sum(divided,'mudCost')-5610000)<1e-6);
assert.equal(sum(divided.filter(r=>r.date==='2026-10-02'),'mudCost'),0);

const fuel={daily:[{date:'2026-10-01',litres:200,cost:1080000},{date:'2026-10-02',litres:600,cost:3240000}],allocations:[
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',litres:200,cost:1080000},
 ...['C-1800','CSD-1300'].flatMap(rig=>['Өдөр','Шөнө'].map(shift=>({date:'2026-10-02',rig,shift,hole:'',litres:150,cost:810000})))]};
const actualFuel=records([row('2026-10-01','C-1800','Өдөр',10,'A',4),row('2026-10-01','C-1800','Өдөр',30,'A',8)],undefined,null,fuel);
assert.ok(Math.abs(sum(actualFuel,'fuelUsageL')-800)<1e-9);
assert.ok(Math.abs(sum(actualFuel,'fuelCost')-4320000)<1e-6);
assert.equal(sum(actualFuel.filter(r=>r.date==='2026-10-02'),'fuelUsageL'),600);
assert.ok(Math.abs(actualFuel.filter(r=>r.recorded)[0].fuelUsageL-200/3)<1e-9);
