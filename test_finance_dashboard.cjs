const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
let selectedRig='';
const context=vm.createContext({document:{querySelector:selector=>({value:selector==='#site'?'Нэргүй Өндөр':selector==='#rig'?selectedRig:''})},DrillingCosts:require('./dist/financial-costs.js')});
vm.runInContext(fs.readFileSync('dist/app.js','utf8').split('function kpis()')[0],context);
const data={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10}],finance:{period:'2026-10',rigShifts:[]}};
for(const day of ['01','02'])for(const rig of ['C-1800','CSD-1300'])for(const shift of ['Өдөр','Шөнө'])data.finance.rigShifts.push({date:`2026-10-${day}`,rig,shift,laborCost:100,foodCost:50,incentiveCost:25,bonusCost:day==='01'&&rig==='C-1800'&&shift==='Өдөр'?200:0});
context.fixture=data;
vm.runInContext('D=fixture',context);
for(const grain of ['shift','day','week','month']){
 context.grainUnderTest=grain;
 const rows=vm.runInContext('financialRows(grainUnderTest)',context);
 assert.equal(rows.reduce((n,r)=>n+r.laborCost,0),800);
 assert.equal(rows.reduce((n,r)=>n+r.foodCost,0),400);
 assert.equal(rows.reduce((n,r)=>n+r.bonusCost,0),200);
 assert.equal(rows.reduce((n,r)=>n+r.incentiveCost,0),200);
 for(const row of rows){assert.equal(row.waterUsageM3,null);assert.equal(row.totalCost,row.fuelCost+row.mudCost+row.laborCost+row.foodCost+row.bonusCost+row.incentiveCost);}
 const series=vm.runInContext('financialRigSeries(grainUnderTest)',context);
 assert.equal(series.flatMap(s=>s.points).reduce((n,p)=>n+(p.bonusCost||0),0),200);
 for(const point of series.flatMap(s=>s.points))if(point.value!=null)assert.equal(point.value*point.meters,point.fuelCost+point.mudCost+point.laborCost+point.foodCost+point.bonusCost+point.incentiveCost);
}
assert.ok(vm.runInContext('renderFinancialTab()',context).includes('Метрийн бонус'));
console.log('Finance dashboard verified: bonus included once, fixed calendar costs, water volume separate from costs, all four periods.');

assert.ok(vm.runInContext('renderFinancialTab()',context).includes('Усны хэрэглээ'));
assert.ok(!vm.runInContext('renderFinancialTab()',context).includes('ус ороогүй'));
context.fixture.shifts[0].waterUsageM3=2.5;
assert.equal(vm.runInContext("financialRows('month')[0].waterUsageM3",context),2.5);
context.fixture.shifts.push({...context.fixture.shifts[0],shift:'Шөнө',waterUsageM3:null});
assert.equal(vm.runInContext("financialRows('month')[0].waterUsageM3",context),null);

context.fixture.shifts.push({date:'2026-10-02',rig:'CSD-1300',shift:'Шөнө',hole:'X',meters:20});
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const rows=vm.runInContext('financialRows(grainUnderTest)',context);
 const points=vm.runInContext('financialRigSeries(grainUnderTest)',context).flatMap(s=>s.points);
 near(rows.reduce((n,r)=>n+r.fuelUsageL,0),0);
 near(points.reduce((n,p)=>n+(p.fuelUsageL||0),0),rows.reduce((n,r)=>n+r.fuelUsageL,0));
 near(points.reduce((n,p)=>n+(p.mudUsageKg||0),0),rows.reduce((n,r)=>n+r.mudUsageKg,0));
}
selectedRig='CSD-1300';
near(vm.runInContext("financialRows('month')[0].fuelUsageL",context),0);
const markup=vm.runInContext('renderFinancialTab()',context);
assert.ok(markup.includes('Өрөмд олгосон:'));
assert.ok(markup.includes('Түлш (л, олголт)'));
assert.ok(markup.includes('Шавар (кг, хуваарилсан)'));
const detailDates=[...markup.matchAll(/data-label="Хугацаа">([^<]+)</g)].map(match=>match[1]);
assert.ok(new Set(detailDates).size>1);
assert.deepEqual(detailDates,[...detailDates].sort().reverse(),'details table lists the latest period first');
console.log('Consumption dashboard verified: four periods, rig filter, details and chart consistency.');

selectedRig='';
context.fixture=JSON.parse(fs.readFileSync('dist/data.json','utf8'));
vm.runInContext('D=fixture',context);
const confirmed=context.fixture.finance.mud,confirmedKg=confirmed.totalBags*confirmed.bagKg,confirmedCost=confirmed.totalBags*confirmed.pricePerBag;
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const rows=vm.runInContext('financialRows(grainUnderTest)',context);
 near(rows.reduce((n,r)=>n+r.mudUsageKg,0),confirmedKg);
 near(rows.reduce((n,r)=>n+r.mudUsageBags,0),confirmed.totalBags);
 near(rows.reduce((n,r)=>n+r.mudCost,0),confirmedCost);
}
context.fixture.shifts.push({...context.fixture.shifts.at(-1),date:'2026-10-18',meters:1000});
near(vm.runInContext("financialRows('month').reduce((n,r)=>n+r.mudUsageKg,0)",context),confirmedKg);
console.log('Source mud totals and cost reconcile across periods; new drilling adds no mud.');

const fuelLedger=context.fixture.finance.fuel;
const litres=fuelLedger.daily.reduce((n,r)=>n+(r.litres||0),0),fuelCost=fuelLedger.daily.reduce((n,r)=>n+(r.cost||0),0);
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const rows=vm.runInContext('financialRows(grainUnderTest)',context);
 near(rows.reduce((n,r)=>n+r.fuelUsageL,0),litres);
 near(rows.reduce((n,r)=>n+r.fuelCost,0),fuelCost);
 const points=vm.runInContext('financialRigSeries(grainUnderTest)',context).flatMap(s=>s.points);
 near(points.reduce((n,p)=>n+(p.fuelUsageL||0),0),litres);
}
console.log('Actual drilling fuel ledger reconciles for every grain, including issues after the last drilling report.');

for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const html=vm.runInContext('financialGrain=grainUnderTest;renderFinancialTab()',context);
 assert.ok(!html.includes('Өмнөх хугацааны дүн:'));
 assert.ok(!html.includes('өөрчлөлтгүй'));
 assert.ok(html.includes(`Өрөмд олгосон: ${litres.toLocaleString('en-US',{maximumFractionDigits:2})} л`));
 assert.ok(html.includes(`Хуваарилсан хэрэглээ: ${confirmedKg.toLocaleString('en-US',{maximumFractionDigits:2})} кг`));
 const cards=[...html.matchAll(/<article class="kpi(?: financial-trend [a-z]+)?">([\s\S]*?)<\/article>/g)].map(m=>m[1]);
 assert.equal(cards.length,8);
 for(const index of [3,4,6,7])assert.ok(!cards[index].includes('class="note"'));
}
console.log('Totals have no period comparisons; breakdown uses consistent totals across all grains.');

context.fixture={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10},{date:'2026-10-01',rig:'C-1800',shift:'Шөнө',hole:'X',meters:20}],finance:{period:'2026-10',rigShifts:['Өдөр','Шөнө'].map(shift=>({date:'2026-10-01',rig:'C-1800',shift,laborCost:100,foodCost:0,bonusCost:0,incentiveCost:0}))}};
vm.runInContext("D=fixture;financialGrain='shift'",context);
const compared=vm.runInContext('renderFinancialTab()',context);
assert.ok(compared.includes('-50%'));
assert.ok(compared.includes('2026-10-01 · Шөнө: ₮ 5 /м ↔ 2026-10-01 · Өдөр: ₮ 10 /м'));

assert.ok(compared.includes('kpi financial-trend down'));
context.fixture.shifts.push({date:'2026-10-02',rig:'C-1800',shift:'Өдөр',hole:'X',meters:0});
context.fixture.finance.rigShifts.push({date:'2026-10-02',rig:'C-1800',shift:'Өдөр',laborCost:200,foodCost:0});
const noTrailingNA=vm.runInContext('renderFinancialTab()',context);
assert.ok(noTrailingNA.includes('Сүүлийн ээлжийн зардал (₮/м)'));
assert.ok(noTrailingNA.includes('2026-10-01 · Шөнө · ▼ 50%'));
const firstCard=noTrailingNA.match(/<article[^>]*>([\s\S]*?)<\/article>/)[1];
assert.ok(firstCard.includes('₮ 5'));
assert.ok(!firstCard.includes('N/A'));
context.fixture.shifts[1].meters=5;
const increased=vm.runInContext('renderFinancialTab()',context);
assert.ok(increased.includes('kpi financial-trend up'));
assert.ok(increased.includes('2026-10-01 · Шөнө · ▲ 100%'));
console.log('Cost trends verified: red increase, green decrease, last recorded drilling period and trailing zero-metre costs.');

context.fixture=JSON.parse(fs.readFileSync('dist/data.json','utf8'));
const diamond=context.fixture.finance.diamond;
assert.equal(diamond.ratePerMeter,diamond.totalBudget/diamond.plannedMeters);
const diamondMeters=context.fixture.shifts.filter(r=>r.date.startsWith(context.fixture.finance.period)).reduce((n,r)=>n+r.meters,0);
const diamondTotal=diamondMeters*diamond.ratePerMeter;
for(const rig of ['', 'C-1800', 'CSD-1300']){
 selectedRig=rig;
 const expected=context.fixture.shifts.filter(r=>r.date.startsWith(context.fixture.finance.period)&&(!rig||r.rig===rig)).reduce((n,r)=>n+r.meters*diamond.ratePerMeter,0);
 for(const period of ['shift','day','week','month']){
  context.grainUnderTest=period;
  vm.runInContext('D=fixture',context);
  const rows=vm.runInContext('financialRows(grainUnderTest)',context);
  near(rows.reduce((n,r)=>n+r.diamondCost,0),expected);
  for(const row of rows)near(row.totalCost,row.allCosts.reduce((n,c)=>n+c.value,0));
  const points=vm.runInContext('financialRigSeries(grainUnderTest)',context).flatMap(s=>s.points);
  near(points.reduce((n,p)=>n+(p.diamondCost||0),0),expected);
  const html=vm.runInContext('financialGrain=grainUnderTest;renderFinancialTab()',context);
  assert.ok(html.includes('Алмазан хошуу + reaming shell (тооцоот)'));
  assert.ok(html.includes('бодит солилт/элэгдэл биш'));
 }
}
selectedRig='';
vm.runInContext('D=fixture',context);
const withDiamond=vm.runInContext("financialRows('month').reduce((n,r)=>n+r.totalCost,0)",context);
delete context.fixture.finance.diamond;
const withoutDiamond=vm.runInContext("financialRows('month').reduce((n,r)=>n+r.totalCost,0)",context);
near(withDiamond-withoutDiamond,diamondTotal);
const split=require('./dist/financial-costs.js').records([
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'A',meters:10,hours:6},
 {date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'B',meters:20,hours:6},
 {date:'2026-10-02',rig:'C-1800',shift:'Өдөр',hole:'B',meters:0,hours:12}
],['C-1800'],null,null,diamond);
near(split.reduce((n,r)=>n+r.diamondCost,0),30*diamond.ratePerMeter);
assert.ok(split.filter(r=>!r.meters).every(r=>r.diamondCost===0));
console.log('Diamond estimates reconcile across four periods and both rigs; totals include them exactly once; split shifts and zero metres verified.');
