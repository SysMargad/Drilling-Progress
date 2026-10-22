const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const model=require('./dist/map-model.js'),project=require('./dist/vendor/proj4.js'),data=require('./dist/data.json');
const points=model.points(data.collar);
assert.equal(points.length,data.collar.filter(h=>Number.isFinite(h.e)&&Number.isFinite(h.n)).length);
for(const point of points){
 assert.ok(point.lat>49&&point.lat<50&&point.lng>113&&point.lng<114);
 const [e,n]=project('EPSG:4326',model.CRS,[point.lng,point.lat]);
 assert.ok(Math.abs(e-point.hole.e)<0.001&&Math.abs(n-point.hole.n)<0.001);
}
const origin=model.point({id:'equator',e:500000,n:0});
assert.ok(Math.abs(origin.lng-111)<1e-10&&Math.abs(origin.lat)<1e-10);
for(const [e,n] of [[null,5450000],[686000,null],[NaN,5450000],[0,0],[686000,-10],[686000,Infinity]])assert.equal(model.point({e,n}),null);
assert.ok(model.point({id:'planned',e:686280,n:5453249,z:null}));
let area='',rig='';
const context=vm.createContext({DrillingMap:model,document:{addEventListener:()=>{},querySelector:s=>({value:s==='#site'?'Нэргүй Өндөр':s==='#area'?area:s==='#rig'?rig:''})},fixture:data});
const app=fs.readFileSync('dist/app.js','utf8');
vm.runInContext(app.split('function kpis()')[0]+app.slice(app.indexOf('let mappingMap='),app.indexOf('function render(){')),context);
vm.runInContext('D=fixture',context);
let html=vm.runInContext('renderMapping()',context);
assert.equal((html.match(/data-map-hole=/g)||[]).length,points.length);
for(const h of data.collar.filter(h=>!model.point(h)))assert.ok(html.includes(`data-hole="${h.id}"`));
area='Замт Хөндий';html=vm.runInContext('renderMapping()',context);assert.ok(!html.includes('data-map-hole="DTDH'));
area='';rig='C-1800';html=vm.runInContext('renderMapping()',context);
for(const point of points){
 const hasRig=data.shifts.some(s=>s.hole===point.id&&s.rig===rig);
 assert.equal(html.includes(`data-map-hole="${point.id}"`),hasRig);
}
console.log('Mapping verified: UTM 49N placement, round trips, missing coordinates, planned holes and filters.');

