const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({document:{querySelector:selector=>({value:selector==='#site'?'Нэргүй Өндөр':''})},DrillingCosts:require('./dist/financial-costs.js')});
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
