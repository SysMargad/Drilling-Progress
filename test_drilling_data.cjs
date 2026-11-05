const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const model=require('./dist/data-model.js');
const file=(name,modified='2026-10-28T02:00:00Z')=>({name,modified,url:'https://drive.google.com/file/d/'+encodeURIComponent(name)+'/view'});
const section=(files,url)=>({url:'https://drive.google.com/drive/folders/'+url,count:files.length,latest:'',files});
const photos=(count,formats)=>({url:'https://drive.google.com/drive/folders/p',count,latest:'2026-10-20T00:00:00Z',formats});
const done={finish:'2026-10-20',collarDepth:150,e:686000,n:5452000,z:970,boxes:46};
const collar=[
  {id:'DTDH2606',...done},
  {id:'DTDH2602',...done},
  {id:'ZHDH2603',...done,z:null},
  {id:'ZHDH2604',...done},
  {id:'ZHDH2605',...done,collarDepth:null},
  {id:'UGDH2601',finish:'',collarDepth:null,e:681440,n:5457495,z:null,boxes:null},
  {id:'ZHDH2612',finish:'',collarDepth:null,e:null,n:null,z:null,boxes:null},
  {id:'ZHDH2699',...done},
];
const inventory={
  DTDH2606:{photos:photos(49,{CR2:46,JPG:46}),geological:section([file('DTDH2606_Geological_Log.xlsx'),file('img1.jpg')],'g'),
    geotechnical:section([file('DTDH2606 Technical Data.xlsx'),file('DTDH2606_Geotechnical_Log.xlsx')],'t'),
    pxrf:section([file('DTDH2606_Drill_Hole_Log_Combined.pdf'),file('DTDH2606_pXRF_0-161.4m_3beam_Complete.xlsx'),file('DTDH2603_Vanta_pXRF_35-92m')],'x')},
  DTDH2602:{photos:photos(44,{CR2:3,JPG:41}),geological:section([file('img20261016.jpg')],'g'),geotechnical:section([file('DTDH2602 Technical Data.xlsx')],'t'),
    pxrf:section([file('delete'),file('delete.jpg')],'x'),surveys:section([],'s')},
  ZHDH2603:{photos:photos(0,{}),geological:section([file('20261031_224936.jpg'),file('ZHDH2603_Geological_Log.pdf')],'g'),
    geotechnical:section([file('ZHDH2603 GeoTechnical Data.xlsx')],'t'),pxrf:section([file('ZHDH2603_Vanta_pXRF_0.4-350.4.xlsx')],'x')},
  ZHDH2604:{geological:section([file('ZHDH2604_Geological_Log.xlsx')],'g'),geotechnical:section([file('ZHDH2604_geotech.md')],'t')},
  ZHDH2605:{photos:photos(12,{JPG:12}),geotechnical:section([file('ZHDH2505_Geochnical Data.xlsx')],'t')},
  UGDH2601:{pxrf:section([file('UGDH2601-177.4-196.4m.xlsx')],'x')},
  ZHDH2612:{geological:section([],'g')},
};
const shifts=[{hole:'UGDH2601'},{hole:'UGDH2601'},{hole:'DTDH2606'}];
const folders=Object.fromEntries([...Object.keys(inventory),'UGDH2602'].map(id=>[id,{url:'https://drive.google.com/drive/folders/'+id,folders:[]}]));
const rows=model.rows(collar,shifts,inventory,folders),by=Object.fromEntries(rows.map(r=>[r.id,r]));
assert.deepEqual(rows.map(r=>r.id),[...collar.map(h=>h.id)].sort());
const state=id=>by[id].readiness.state;
// Geologist's Excel log and photos: dual log; the geotechnical template wins over Technical Data.
assert.equal(state('DTDH2606'),'dual');
assert.equal(by.DTDH2606.geology.state,'log');
assert.equal(by.DTDH2606.geology.format,'Excel');
assert.equal(by.DTDH2606.geology.done,true);
assert.equal(by.DTDH2606.geotech.state,'log');
assert.equal(by.DTDH2606.geotech.done,true);
assert.equal(by.DTDH2606.geotech.file.name,'DTDH2606_Geotechnical_Log.xlsx');
assert.equal(by.DTDH2606.pxrf.count,2,'pXRF data files: xlsx and Google Sheets, not the PDF');
assert.equal(by.DTDH2606.folderUrl,'https://drive.google.com/drive/folders/DTDH2606');
// Photos without the geologist's Excel: AI log; field sheet scans alone are not an Excel log.
assert.equal(state('DTDH2602'),'ai');
assert.equal(by.DTDH2602.geology.state,'handwritten');
assert.equal(by.DTDH2602.geology.done,false,'field sheet scans are not a geological log');
assert.equal(by.DTDH2602.geotech.state,'technical');
assert.equal(by.DTDH2602.geotech.done,false,'Technical Data is not a geotechnical log');
assert.equal(by.DTDH2602.pxrf.count,0,'files named delete are not data');
// A file named as a log is the geologist's log in any format, next to field sheet scans too.
assert.equal(state('ZHDH2603'),'geologist');
assert.equal(by.ZHDH2603.geology.file.name,'ZHDH2603_Geological_Log.pdf');
assert.equal(by.ZHDH2603.geology.format,'PDF');
assert.equal(by.ZHDH2603.collar.elevation,false);
const geologyFolder=(...list)=>model.row(collar[2],{ZHDH2603:{...inventory.ZHDH2603,geological:section(list.map(f=>typeof f==='string'?file(f):f),'g')}});
for(const name of ['ZHDH2603 core logging.xlsx','ZHDH2603_Geolog20261005_14by_MT_EC.pdf','ZHDH2603_LOG_v2.pdf'])
  assert.equal(geologyFolder('img1.jpg',name).geology.file.name,name);
const docs={name:'ZHDH2603_Drill_Hole_Log_Combined',url:'https://docs.google.com/document/d/x/edit'};
assert.equal(geologyFolder(docs).geology.format,'Docs');
assert.equal(geologyFolder(docs,'ZHDH2603_Geolog20261005.pdf','ZHDH2603_Geological_Log.pdf').geology.file.name,'ZHDH2603_Geological_Log.pdf');
// No photos and only handwritten sheets: missing, and the message says the sheets need transcribing.
assert.equal(geologyFolder('20261031_224936.jpg','Field sheet 1.pdf').geology.state,'handwritten');
assert.deepEqual(geologyFolder('20261031_224936.jpg','Field sheet 1.pdf').readiness.missing,['Кернийн зураг эсвэл геологийн лог (гар бичмэлийг буулгах)']);
// Geologist's Excel log without photos needs geotechnical data (a Markdown note not named as a log is not).
assert.equal(state('ZHDH2604'),'missing');
assert.deepEqual(by.ZHDH2604.readiness.missing,['Геотехникийн лог эсвэл Technical Data']);
// A file named as a log in the geotechnical folder is the geotechnical log in any format: geotechnical logging done.
const geotechFolder=(...names)=>model.row(collar[3],{ZHDH2604:{...inventory.ZHDH2604,geotechnical:section(names.map(n=>file(n)),'t')}}).geotech;
for(const name of ['ZHDH2604_geotech_log.md','ZHDH2604 Geotechnical logging.pdf'])
  assert.deepEqual([geotechFolder('ZHDH2604 GeoTechnical Data.xlsx',name).state,geotechFolder(name).done],['log',true],name);
assert.equal(geotechFolder('ZHDH2604_Graphic_Log.pdf','ZHDH2604_Geotechnical_Log.pdf').file.name,'ZHDH2604_Geotechnical_Log.pdf');
assert.equal(geotechFolder('ZHDH2604_Geotechnical_Log.pdf').format,'PDF');
assert.equal(model.row(collar[3],{ZHDH2604:{...inventory.ZHDH2604,geotechnical:section([file('ZHDH2604_geotech_log.md')],'t')}}).readiness.state,'geologist');
assert.equal(model.row({...collar[3]},{ZHDH2604:{...inventory.ZHDH2604,geotechnical:section([file('ZHDH2604 GeoTechnical Data.xlsx')],'t')}}).readiness.state,'geologist');
// A misnamed Technical Data workbook still counts as geotechnical data; the collar's final depth is required.
assert.equal(by.ZHDH2605.geotech.state,'technical');
assert.deepEqual(by.ZHDH2605.readiness.missing,['Collar эцсийн гүн']);
// Unfinished holes are not judged; a hole without a Drive folder says so.
assert.equal(state('UGDH2601'),'drilling');
assert.equal(state('ZHDH2612'),'planned');
assert.equal(state('ZHDH2699'),'nodrive');
assert.equal(by.ZHDH2699.photos.count,0);
assert.ok(rows.every(r=>r.readiness.label===model.LABELS[r.readiness.state]));
assert.ok(rows.every(r=>r.readiness.missing.length===(r.readiness.state==='missing'?r.readiness.missing.length:0)));
// Logged or not: the collar sheet's log register; Drive-registered holes have no register columns.
const log=(geologyLog,geotechLog,pxrfLog='')=>model.logged({id:'X',geologyLog,geotechLog,pxrfLog});
assert.equal(log('Completed','Completed','Bruker complete').state,'done');
assert.equal(log(' completed','COMPLETED').state,'done');
assert.equal(log('completed','').state,'partial');
assert.equal(log('in progress','').state,'partial');
assert.equal(log('','').state,'none');
assert.equal(model.logged({id:'UGDH2602',registered:'drive'}).state,'unknown');
assert.equal(model.row({id:'UGDH2602',registered:'drive'},{}).collar.registered,false);
assert.equal(by.DTDH2606.collar.registered,true);

// The page: every registered hole is a row, with links to its files and the folders without a collar row.
let area='';
const context=vm.createContext({DrillingData:model,document:{addEventListener:()=>{},querySelector:s=>({value:s==='#site'?'Нэргүй Өндөр':s==='#area'?area:''})},
  fixture:{collar:[...collar.map(h=>({site:'Нэргүй Өндөр',geologyLog:'',geotechLog:'',...h})).map(h=>h.id==='DTDH2606'?{...h,geologyLog:'Completed',geotechLog:'Completed',pxrfLog:'in progress'}:h),
    {id:'STDH2601',site:'Нэргүй Өндөр',targetArea:'Сант',start:'2026-11-04',finish:''},
    {id:'UGDH2602',site:'Нэргүй Өндөр',targetArea:'Уртын гол',start:'',finish:'',registered:'drive'}],
    shifts:shifts.map(s=>({...s,rig:'C-1800'})),dataInventory:inventory,folderMap:folders}});
const app=fs.readFileSync('dist/app.js','utf8');
vm.runInContext(app.split('function kpis()')[0]+app.slice(app.indexOf('function dataRows()'),app.indexOf('function logTime(')),context);
vm.runInContext('D=fixture',context);
let page=vm.runInContext('drillingData()',context);
assert.equal((page.match(/data-data-hole=/g)||[]).length,collar.length+2);
for(const h of [...collar,{id:'STDH2601'},{id:'UGDH2602'}])assert.ok(page.includes(`data-data-hole="${h.id}"`));
// The table ends with the geological and geotechnical log columns; readiness and the collar register are not columns.
assert.ok(page.includes('<th>Хазайлтын хэмжилт</th><th>Геологийн лог</th><th>Геотехникийн лог</th></tr>'));
for(const removed of ['Лог хийх боломж','Лог хийгдсэн эсэх','Геологич + AI','Лог хийгдээгүй'])assert.ok(!page.includes(removed),removed);
// Logging counted over finished holes: geological logs on Drive for DTDH2606, ZHDH2603, ZHDH2604; geotechnical for DTDH2606 only.
assert.ok(page.includes('Геологи хийгдсэн: 3'));
assert.ok(page.includes('Геологи хийгдээгүй: 3'));
assert.ok(page.includes('Геотехник хийгдсэн: 1'));
assert.ok(page.includes('Геотехник хийгдээгүй: 5'));
const cells=id=>page.split(`data-data-hole="${id}"`)[1].split('</tr>')[0].split('<td>');
assert.equal(cells('DTDH2606').length,9);
assert.ok(cells('DTDH2606')[7].startsWith('<strong class="log-done">Хийгдсэн</strong>'));
assert.ok(cells('DTDH2602')[7].startsWith('<strong class="log-missing">Хийгдээгүй</strong>'));
assert.ok(cells('DTDH2602')[8].startsWith('<strong class="log-missing">Хийгдээгүй</strong>'));
assert.ok(page.includes('Drive хавтаснаас бүртгэсэн'));
assert.deepEqual([...vm.runInContext('areaList(D.collar)',context)],['Дорнын Төмөр','Замт Хөндий','Уртын гол','Сант']);
area='Сант';page=vm.runInContext('drillingData()',context);
assert.equal((page.match(/data-data-hole=/g)||[]).length,1);
area='';page=vm.runInContext('drillingData()',context);
assert.ok(page.includes('href="https://drive.google.com/file/d/DTDH2606_Geological_Log.xlsx/view"'));
assert.ok(page.includes('49 зураг'));
assert.ok(page.includes('загварт хөрвүүлэх'));
area='Замт Хөндий';page=vm.runInContext('drillingData()',context);
assert.ok(!page.includes('data-data-hole="DTDH'));
assert.ok(page.includes('data-data-hole="ZHDH2603"'));
vm.runInContext('query="2603"',context);area='';
assert.equal((vm.runInContext('dataTable()',context).match(/data-data-hole=/g)||[]).length,1);
vm.runInContext('query="";D={...D,dataInventory:undefined}',context);
assert.ok(vm.runInContext('dataTable()',context).includes('хараахан уншигдаагүй'));
console.log('Drilling Data verified: readiness per hole, file classification, filters, search and missing inventory.');
