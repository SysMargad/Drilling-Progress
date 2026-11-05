const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const AuditModel=require('./dist/audit-model.js');
const report={name:'2026-10-14_d.jpg',url:'https://drive.google.com/file/d/r1/view'};
const slot=(rig,date,shift,status,meters,extra={})=>({rig,date,shift,status,meters,records:meters==null?[]:[{hole:'DTDH2603',from:203,to:203+meters,meters,source:'2026-10-14_d.jpg',evidence:'report',
  sheet:{name:'Drilling Shift Report Table',tab:'2_Ээлжийн_бүртгэл',row:45,url:'https://docs.google.com/spreadsheets/d/s'},reports:[report]}],issues:[],driveReports:[],folderUrl:'https://drive.google.com/drive/folders/f',...extra});
const slots=[];
for(const date of ['2026-10-14','2026-10-15'])for(const shift of ['Өдөр','Шөнө'])for(const rig of ['C-1800','CSD-1300'])slots.push(slot(rig,date,shift,'VERIFIED_DRILLING',45));
const replace=(rig,date,shift,value)=>{slots[slots.findIndex(s=>s.rig===rig&&s.date===date&&s.shift===shift)]=value;};
replace('C-1800','2026-10-14','Шөнө',slot('C-1800','2026-10-14','Шөнө','MISSING_REPORT',null,{issues:[{kind:'gap',text:'DTDH2603: 248–257 м (9 м) тайлангүй'}]}));
replace('C-1800','2026-10-15','Шөнө',slot('C-1800','2026-10-15','Шөнө','SOURCE_CONFLICT',9,{issues:[{kind:'overlap',text:'DTDH2603: 248–257 м нь өмнөх ...'}]}));
replace('CSD-1300','2026-10-14','Өдөр',slot('CSD-1300','2026-10-14','Өдөр','UNVERIFIED',null,{issues:[{kind:'noReport',text:'нүүлт байж болзошгүй'}]}));
replace('CSD-1300','2026-10-15','Өдөр',slot('CSD-1300','2026-10-15','Өдөр','VERIFIED_NON_DRILLING',0));
const audit={through:'2026-10-15',rigs:['C-1800','CSD-1300'],months:[{month:'2026-10',expected:8,counts:{},meters:{},missingMeters:9}],slots};
// The model counts per month and rig from the slots themselves.
const all=AuditModel.summary(audit,'2026-10'),c1800=AuditModel.summary(audit,'2026-10','C-1800');
assert.deepEqual([all.expected,all.days,all.counts.VERIFIED_DRILLING,all.counts.MISSING_REPORT,all.counts.SOURCE_CONFLICT,all.counts.UNVERIFIED,all.counts.VERIFIED_NON_DRILLING],[8,2,4,1,1,1,1]);
assert.equal(all.missingMeters,9);
assert.deepEqual([c1800.expected,c1800.counts.MISSING_REPORT,c1800.missingMeters],[4,1,null]);
assert.equal(Object.values(all.counts).reduce((n,v)=>n+v,0),all.expected);
assert.deepEqual(AuditModel.freshness([{rig:'C-1800',date:'2026-10-15',shift:'Өдөр'},{rig:'C-1800',date:'2026-10-15',shift:'Шөнө'},{rig:'C-1800',date:'2026-10-14',shift:'Шөнө'}],['C-1800','CSD-1300']),
  [{rig:'C-1800',date:'2026-10-15',shift:'Шөнө'},{rig:'CSD-1300',date:'',shift:''}]);
const log=[{status:'updated',completedAt:'2026-11-05T13:50:09+08:00'},{status:'failed',startedAt:'2026-11-05T15:00:00+08:00',completedAt:'2026-11-05T15:01:00+08:00',error:'ValueError',validation:'Missing/invalid dt for ZHDH2604 on 2026-10-30'}];
assert.deepEqual(AuditModel.lastSync(log),{success:'2026-11-05T13:50:09+08:00',attempt:'2026-11-05T15:01:00+08:00',status:'failed',validation:'Missing/invalid dt for ZHDH2604 on 2026-10-30'});

// The page: KPI cards, the calendar (no 0 m for a missing report), issue list, slot details and CSV rows.
let rig='',opened='';
const body={innerHTML:''};
const context=vm.createContext({AuditModel,document:{addEventListener:()=>{},querySelector:s=>s==='#detail-body'?body:s==='#detail'?{showModal:()=>{opened=body.innerHTML;}}:({value:s==='#rig'?rig:''})},
  fixture:{shifts:[{rig:'C-1800',date:'2026-10-15',shift:'Шөнө'}],shiftAudit:audit,unlinkedReports:[{hole:'ZHDH2612',rig:'C-1800',date:'2026-10-15',shift:'Өдөр',name:'2026-10-15_ZHDH2612_d.jpg',url:'https://drive.google.com/file/d/z/view',folderUrl:''}],
    unassignedShifts:[{rigText:'Баталгаажаагүй',date:'2026-10-15',shift:'Өдөр',hole:'ZHDH2612',from:0,to:74,source:'x.jpg',sheet:'Drilling Shift Report Table',tab:'2_Ээлжийн_бүртгэл',row:51,url:'https://docs.google.com/spreadsheets/d/s'}]},log});
const app=fs.readFileSync('dist/app.js','utf8');
vm.runInContext(app.split('function kpis()')[0]+app.slice(app.indexOf('const dataLink='),app.indexOf('const readinessClass='))+app.slice(app.indexOf('function logTime('),app.indexOf('function sources(')),context);
vm.runInContext('D=fixture;dataLog=log',context);
let page=vm.runInContext('auditView()',context);
assert.ok(page.includes('<div class="label">Нийт хүлээгдэж буй ээлж</div><div class="value">8</div><div class="note">2 өдөр × 2 ээлж × 2 өрөм</div>'));
assert.ok(page.includes('<div class="label">Тайлан дутуу</div><div class="value">1</div><div class="note">9 м тайлангүй</div>'));
assert.ok(page.includes('Сүүлийн оролдлого алдаатай: Missing/invalid dt for ZHDH2604 on 2026-10-30'));
assert.ok(page.includes('C-1800: 10-15 Шөнө'));
assert.equal((page.match(/class="audit-cell /g)||[]).length,8);
assert.ok(page.includes('class="audit-cell audit-missing-report" data-audit-slot="C-1800|2026-10-14|Шөнө"'));
assert.match(page,/data-audit-slot="C-1800\|2026-10-14\|Шөнө"[^>]*>!<\/button>/,'a missing report shows !, not 0');
assert.match(page,/data-audit-slot="CSD-1300\|2026-10-14\|Өдөр"[^>]*>\?<\/button>/);
assert.match(page,/data-audit-slot="CSD-1300\|2026-10-15\|Өдөр"[^>]*>0<\/button>/,'a verified non-drilling shift is 0 m');
assert.match(page,/data-audit-slot="C-1800\|2026-10-15\|Шөнө"[^>]*>9\*<\/button>/);
assert.ok(page.includes('<td>Тайлангүй</td>'));
assert.ok(page.includes('Өрөм нь тодорхойгүй мөр: 1'));
assert.ok(page.includes('Ээлжид холбогдоогүй Drive тайлан: 1'));
assert.ok(page.includes('2_Ээлжийн_бүртгэл мөр 51'));
rig='CSD-1300';page=vm.runInContext('auditView()',context);
assert.equal((page.match(/class="audit-cell /g)||[]).length,4);
assert.ok(!page.includes('C-1800 · Өдөр'));
rig='';
vm.runInContext("openAuditSlot('C-1800|2026-10-15|Шөнө')",context);
assert.ok(opened.includes('Эх сурвалжийн зөрчил'));
assert.ok(opened.includes('Drilling Shift Report Table / 2_Ээлжийн_бүртгэл мөр 45 ↗'));
assert.ok(opened.includes('href="https://drive.google.com/file/d/r1/view"'));
vm.runInContext("openAuditSlot('C-1800|2026-10-14|Шөнө')",context);
assert.ok(opened.includes('Тайлангүй (0 м гэж тооцохгүй)'));
assert.ok(opened.includes('href="https://drive.google.com/drive/folders/f"'));
vm.runInContext("D={...D,shiftAudit:undefined}",context);
assert.ok(vm.runInContext('auditView()',context).includes('дараагийн sync-ээр тооцоологдоно'));
console.log('Shift audit page verified: counts, calendar marks (no 0 m for missing reports), rig filter, issues, details and sync status.');
