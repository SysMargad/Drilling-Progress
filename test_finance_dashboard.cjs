const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
let selectedRig='';
const context=vm.createContext({document:{querySelector:selector=>({value:selector==='#site'?'Нэргүй Өндөр':selector==='#rig'?selectedRig:''})},DrillingCosts:require('./dist/financial-costs.js')});
vm.runInContext(fs.readFileSync('dist/app.js','utf8').split('function kpis()')[0],context);
const data={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10}],finance:{period:'2026-10',rigShifts:[]}};
for(const day of ['01','02'])for(const rig of ['C-1800','CSD-1300'])for(const shift of ['Өдөр','Шөнө'])data.finance.rigShifts.push({date:`2026-10-${day}`,rig,shift,laborCost:100,foodCost:50,incentiveCost:25,bonusCost:day==='01'&&rig==='C-1800'&&shift==='Өдөр'?200:0});
context.fixture=data;
vm.runInContext('D=fixture;financialMonth=D.finance.period',context);
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
// Sources reconcile within the finance month; the page itself opens on the latest month.
context.fixture=JSON.parse(fs.readFileSync('dist/data.json','utf8'));
vm.runInContext('D=fixture;financialMonth=D.finance.period',context);
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
  vm.runInContext('D=fixture;financialMonth=D.finance.period',context);
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
vm.runInContext('D=fixture;financialMonth=D.finance.period',context);
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

context.fixture=JSON.parse(fs.readFileSync('dist/data.json','utf8'));
vm.runInContext('D=fixture;financialMonth=D.finance.period',context);
for(const rig of ['', 'C-1800','CSD-1300']){
 selectedRig=rig;
 const expectedWater=[...context.fixture.finance.water.records,...(context.fixture.finance.water.dailyRecords||[])].filter(r=>!rig||r.rig===rig).reduce((n,r)=>n+r.litres,0);
 const expectedFuel=context.fixture.finance.fuel.allocations.filter(r=>!rig||r.rig===rig).reduce((n,r)=>n+r.litres,0);
 for(const period of ['shift','day','week','month']){
  context.grainUnderTest=period;
  const rows=vm.runInContext('financialRows(grainUnderTest)',context);
  near(rows.reduce((n,r)=>n+r.waterKnownLitres,0),expectedWater);
  near(rows.reduce((n,r)=>n+r.fuelUsageL,0),expectedFuel);
  const html=vm.runInContext('financialGrain=grainUnderTest;renderFinancialTab()',context);
  assert.ok(html.includes('Усны хэрэглээ (л)'));
  assert.ok(html.includes('Усны машины түлшийг өртөгт оруулаагүй'));
  assert.equal(html.includes('(багтаамж баталгаажаагүй)'),context.fixture.finance.water.estimated);
 }
}
selectedRig='';
console.log('New consumption data reconciles across grains and rig filters; water estimates remain separate from costs.');

// Month selection keeps October costs out of November and remains usable without source costs.
context.fixture={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[
 {date:'2026-10-31',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10,hours:12},
 {date:'2026-11-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:20,hours:12}
],finance:{period:'2026-10',rigShifts:[{date:'2026-10-31',rig:'C-1800',shift:'Өдөр',laborCost:100,foodCost:50}]}};
vm.runInContext("D=fixture;financialMonth='2026-11'",context);
let monthHtml=vm.runInContext('renderFinancialTab()',context);
assert.ok(monthHtml.includes('value="2026-10"'));
assert.ok(monthHtml.includes('value="2026-11" selected'));
assert.ok(monthHtml.includes('2026-11 сарын ирц (цалин, хоол) Drive-д ороогүй тул ₮/м тооцох боломжгүй'));
assert.ok(!monthHtml.includes('rig-cost-line'));
// The month without payroll still lists its drilling; the costs it lacks say so instead of ₮0.
assert.ok(monthHtml.includes('<div class="label">Нийт өрөмдсөн метр (м)</div><div class="value">20</div>'));
assert.ok(monthHtml.includes('<div class="label">Нийт зардал (₮)</div><div class="value">—</div>'));
assert.ok(monthHtml.includes('<span>Үндсэн цалин</span><strong>Эх сурвалж синк хийгдээгүй</strong>'));
assert.ok(monthHtml.includes('data-label="Хугацаа">2026-11-01'));
assert.ok(!monthHtml.includes('data-label="Хугацаа">2026-10-31'));
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const monthRows=vm.runInContext('financialRows(grainUnderTest)',context);
 near(monthRows.reduce((n,r)=>n+r.drilledMeters,0),20);
 assert.ok(monthRows.every(r=>r.totalCost===null));
}
vm.runInContext("financialMonth='2026-10'",context);
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const monthRows=vm.runInContext('financialRows(grainUnderTest)',context);
 near(monthRows.reduce((n,r)=>n+r.drilledMeters,0),10);
 near(monthRows.reduce((n,r)=>n+r.totalCost,0),150);
 const series=vm.runInContext('financialRigSeries(grainUnderTest)',context).flatMap(s=>s.points);
 near(series.reduce((n,r)=>n+r.meters,0),10);
}
context.fixture.finance={period:'2026-11',rigShifts:[{date:'2026-11-01',rig:'C-1800',shift:'Өдөр',laborCost:200,foodCost:75}]};
vm.runInContext("financialMonth='2026-11'",context);
for(const period of ['shift','day','week','month']){
 context.grainUnderTest=period;
 const monthRows=vm.runInContext('financialRows(grainUnderTest)',context);
 near(monthRows.reduce((n,r)=>n+r.drilledMeters,0),20);
 near(monthRows.reduce((n,r)=>n+r.totalCost,0),275);
}
// A month whose fuel ledger has no days yet: fuel is unknown, not ₮0, so ₮/м waits for it.
context.fixture.finance.fuel={daily:[{date:'2026-10-31',litres:10,cost:54000}],allocations:[{date:'2026-10-31',rig:'C-1800',shift:'Өдөр',hole:'X',litres:10,cost:54000}]};
assert.ok(vm.runInContext("financialRows('month')",context).every(r=>r.fuelCost===null&&r.totalCost===null));
monthHtml=vm.runInContext('renderFinancialTab()',context);
assert.ok(monthHtml.includes('2026-11 сарын түлшний бүртгэл Drive-д ороогүй'));
assert.ok(monthHtml.includes('<span>Түлш</span><strong>Эх сурвалж синк хийгдээгүй</strong>'));
vm.runInContext("financialMonth='2026-10'",context);
assert.ok(vm.runInContext("financialRows('month')",context).every(r=>r.fuelCost!==null));
delete context.fixture.finance.fuel;
// The page opens on the latest month, as the overview chart does.
vm.runInContext("financialMonth=''",context);
assert.equal(vm.runInContext('selectedFinancialMonth()',context),'2026-11');
vm.runInContext("financialMonth='2026-11'",context);
selectedRig='CSD-1300';
assert.ok(vm.runInContext('renderFinancialTab()',context).includes('id="financial-month"'));
selectedRig='';
console.log('Financial month selector verified: both months, four grains, no cross-month costs, missing sources and empty rig filters.');

// A rig-shift without a shift report is "Тайлангүй" in the details, never 0 m (checked on the published data,
// whatever shifts the sources add later).
selectedRig='';
context.fixture=JSON.parse(fs.readFileSync('dist/data.json','utf8'));
vm.runInContext("D=fixture;financialMonth='2026-10';financialGrain='shift'",context);
const unreportedRows=vm.runInContext("financialRows('shift')",context);
for(const row of unreportedRows)if(!row.reportedShifts)assert.equal(row.drilledMeters,0);
const detailMarkup=vm.runInContext('renderFinancialTab()',context);
assert.equal((detailMarkup.match(/<td data-label="Метр">Тайлангүй<\/td>/g)||[]).length,unreportedRows.filter(r=>!r.reportedShifts&&r.unreportedShifts).length);
// The daily water total is not a shift: no slots, so it reads — rather than Тайлангүй.
assert.ok(unreportedRows.filter(r=>r.shiftLabel==='Өдрийн нийт').every(r=>r.reportedShifts+r.unreportedShifts===0));
const october=vm.runInContext("financialRows('month')",context)[0];
assert.equal(october.reportedShifts+october.unreportedShifts,124,'October has 31 days × 2 shifts × 2 rigs');
assert.equal(october.reportedShifts,new Set(context.fixture.shifts.filter(s=>s.date.startsWith('2026-10-')).map(s=>s.date+s.rig+s.shift)).size);
// Synthetic month: day shift of 2 October unreported by C-1800.
context.fixture={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10,hours:12},{date:'2026-10-02',rig:'C-1800',shift:'Шөнө',hole:'X',meters:20,hours:12}],
  finance:{period:'2026-10',rigShifts:[]}};
selectedRig='C-1800';
vm.runInContext("D=fixture;financialGrain='shift'",context);
const synthetic=vm.runInContext('renderFinancialTab()',context);
assert.ok(synthetic.includes('<td data-label="Метр">Тайлангүй</td>'));
assert.equal(vm.runInContext("financialRows('day')",context).find(r=>r.date==='2026-10-02').unreportedShifts,1);
assert.ok(vm.runInContext("financialGrain='day';renderFinancialTab()",context).includes('1 ээлж тайлангүй</small>'));
selectedRig='';
console.log('Unreported rig-shifts read "Тайлангүй", not 0 m, and October holds 124 slots.');

// Pay periods read from the crew pay workbooks name their dates and the bonus source under the cost breakdown;
// the days they do not cover still come from attendance × rate.
context.fixture={collar:[{id:'X',site:'Нэргүй Өндөр'}],shifts:[{date:'2026-10-01',rig:'C-1800',shift:'Өдөр',hole:'X',meters:10,hours:12}],
  finance:{period:'2026-10',rigShifts:[],payPeriods:[{file:'Pay 2026.10.16-2026.10.31.xlsx',start:'2026-10-16',end:'2026-10-31',source:'snapshot',bonus:true}]}};
for(const rig of ['C-1800','CSD-1300'])for(const shift of ['Өдөр','Шөнө'])context.fixture.finance.rigShifts.push({date:'2026-10-01',rig,shift,laborCost:100,foodCost:50,bonusCost:0,incentiveCost:0});
vm.runInContext("D=fixture;financialMonth='2026-10';financialGrain='shift'",context);
let paid=vm.runInContext('renderFinancialTab()',context);
assert.equal((paid.match(/10-16 – 10-31: цалингийн хүснэгт \(бодит, өдөр бүр 4 ээлжид тэнцүү\); бусад өдөр: ирц × тариф/g)||[]).length,2,'labour and incentive');
assert.ok(paid.includes('Цалингийн хүснэгтийн бодит метрийн бонус (Pay 2026.10.16-2026.10.31.xlsx): сарын бүх ээлжид өрөмдсөн метрээр хуваарилсан'));
context.fixture.finance.payPeriods.unshift({file:'Pay 2026.10.01-2026.10.15.xlsx',start:'2026-10-01',end:'2026-10-15',source:'drive',bonus:false});
paid=vm.runInContext('renderFinancialTab()',context);
assert.ok(paid.includes('10-01 – 10-15: цалингийн хүснэгт (бодит, өдөр бүр 4 ээлжид тэнцүү); 10-16 – 10-31: цалингийн хүснэгт (бодит, өдөр бүр 4 ээлжид тэнцүү)</div>'),'whole month covered');
delete context.fixture.finance.payPeriods;
assert.ok(!vm.runInContext('renderFinancialTab()',context).includes('цалингийн хүснэгт'));
console.log('Pay-period sources named under the cost breakdown.');
