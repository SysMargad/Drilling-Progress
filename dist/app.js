'use strict';
let logRegister={},D,tab='overview',query='',grain='day',chartMonth=null,dataLog=[],logError='',selectedHole=null,chartBars=[];
const $=selector=>document.querySelector(selector);
const fmt=(n,d=1)=>n==null?'—':Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sum=(rows,key)=>rows.reduce((total,row)=>total+row[key],0),SITE='Нэргүй Өндөр';
// The two drilling rigs share the same identities across progress and finance.
const RIGS=['C-1800','CSD-1300'],FINANCE_RIGS=['C-1800','CSD-1300'],RIG_COLORS={'C-1800':'#dc8a3b','CSD-1300':'#128875'};
const selectedRigs=(list=RIGS)=>list.filter(rig=>!$('#rig').value||rig===$('#rig').value);
function knownHours(rows,key){const known=rows.filter(row=>Number.isFinite(row[key]));return known.length?(known.length<rows.length?'≥ ':'')+fmt(sum(known,key)):'—';}
function areaOf(h){const area=(h.targetArea||'').toLocaleLowerCase();if(h.id.startsWith('KHDH'))return 'Харгант';if(area==='дорнын төмөр'||(!area&&h.id.startsWith('DTDH')))return 'Дорнын Төмөр';if(area==='замт хөндий'||(!area&&h.id.startsWith('ZHDH')))return 'Замт Хөндий';return h.targetArea||'—';}
// New areas (from the collar sheet or a Drive area folder) join the filter and map without code changes.
const AREA_ORDER=['Дорнын Төмөр','Замт Хөндий','Уртын гол','Сант','Харгант'],AREA_COLORS={'Дорнын Төмөр':'#16b99a','Замт Хөндий':'#f29b44','Уртын гол':'#5b8def','Сант':'#c062d6','Харгант':'#e3bd4b'};
const areaColor=area=>AREA_COLORS[area]||'#9aa5ab';
function areaList(rows){return [...new Set(rows.map(areaOf))].filter(area=>area&&area!=='—').sort((a,b)=>((AREA_ORDER.indexOf(a)+1)||99)-((AREA_ORDER.indexOf(b)+1)||99)||a.localeCompare(b));}
function areaOptions(){const select=$('#area'),value=select.value,areas=areaList(D.collar);if(value&&!areas.includes(value))areas.push(value);if(select.dataset.areas===areas.join('|'))return;select.dataset.areas=areas.join('|');select.innerHTML='<option value="">Бүх участик</option>'+areas.map(area=>`<option${area===value?' selected':''}>${esc(area)}</option>`).join('');}
function holes(){return D.collar.filter(h=>(h.site||SITE)===$('#site').value&&(!$('#area').value||areaOf(h)===$('#area').value)&&(!$('#rig').value||D.shifts.some(s=>s.hole===h.id&&s.rig===$('#rig').value)));}
function shifts(){const ids=new Set(holes().map(h=>h.id));return D.shifts.filter(s=>ids.has(s.hole)&&(!$('#rig').value||s.rig===$('#rig').value));}
function depth(id){const rows=D.shifts.filter(s=>s.hole===id);return rows.length?Math.max(...rows.map(s=>s.to)):null;}
function status(h){if(h.finish)return ['Дууссан',''];if(D.shifts.some(s=>s.hole===h.id))return ['Өрөмдөж байна','active'];return ['Төлөвлөсөн','planned'];}
let financialGrain='shift',financialMonth='';
function financialMonths(){return [...new Set([...D.shifts.map(row=>row.date.slice(0,7)),D.finance?.period].filter(Boolean))].sort().reverse();}
// The latest month opens first, as on the overview chart.
function selectedFinancialMonth(){return financialMonth||financialMonths()[0]||'';}
// Each source covers its own dates: attendance (labour, food) one month, fuel and water their ledger days, the diamond
// estimate every metre. A month without attendance or fuel still shows its metres and the costs it has; ₮/м needs both.
function financialFinance(){
  const finance=D.finance,month=selectedFinancialMonth(),inMonth=row=>row.date.startsWith(month+'-'),fuel=finance?.fuel;
  if(!finance)return null;
  return {...finance,attendance:finance.period===month&&Array.isArray(finance.rigShifts),fuelMissing:!!fuel&&!(fuel.daily||[]).some(inMonth),
    fuel:fuel&&{...fuel,daily:(fuel.daily||[]).filter(inMonth),allocations:(fuel.allocations||[]).filter(inMonth),coverage:(fuel.coverage||[]).filter(inMonth)}};
}
const financialMissing=finance=>[finance.attendance?'':'ирц (цалин, хоол)',finance.fuelMissing?'түлшний бүртгэл':''].filter(Boolean);
function financialControls(){
  return `<div class="chart-controls"><label class="chart-month">Сар <select id="financial-month" aria-label="Санхүүгийн сар">${financialMonths().map(month=>`<option value="${month}"${month===selectedFinancialMonth()?' selected':''}>${month.slice(0,4)} оны ${Number(month.slice(5))}-р сар</option>`).join('')}</select></label><div class="chart-periods" role="group" aria-label="Санхүүгийн графикийн хугацаа">${[['shift','Ээлж'],['day','Өдөр'],['week','7 хоног'],['month','Сар']].map(([value,label])=>`<button class="chart-period-button ${financialGrain===value?'active':''}" data-financial-grain="${value}" aria-pressed="${financialGrain===value}">${label}</button>`).join('')}</div></div>`;
}
const financialGrainLabel=()=>({shift:'Ээлжийн',day:'Өдрийн',week:'7 хоногийн',month:'Сарын'}[financialGrain]);
const currency=(value,digits=0)=>value==null||Number.isNaN(Number(value))?'—':`₮ ${Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`;
function financialWater(){
  const finance=financialFinance();
  if(!finance?.water)return null;
  const area=$('#area').value,ids=new Set(holes().map(h=>h.id));
  return {...finance.water,records:finance.water.records.filter(r=>!area||ids.has(r.hole)),
    dailyRecords:(finance.water.dailyRecords||[]).filter(r=>!area||D.shifts.some(s=>s.date===r.date&&s.rig===r.rig&&ids.has(s.hole)))};
}
function financialRows(grain=financialGrain){
  const finance=financialFinance();
  if(!D||!D.shifts?.length)return [];
  const financeAvailable=Boolean(finance?.attendance),fuelMissing=Boolean(finance?.fuelMissing),costsComplete=financeAvailable&&!fuelMissing;
  const rigs=selectedRigs(FINANCE_RIGS);
  const operationRows=shifts().filter(row=>row.date.startsWith(selectedFinancialMonth()+'-'));
  const sourceRows=DrillingCosts.records(operationRows,rigs,finance?.mud,finance?.fuel,finance?.diamond,financialWater());
  const groupMap=new Map();
  const periodStart=date=>{
    const day=new Date(`${date}T00:00:00Z`);
    if(grain==='week')day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    if(grain==='month')day.setUTCDate(1);
    return day.toISOString().slice(0,10);
  };
  for(const row of sourceRows.filter(row=>row.date.startsWith(selectedFinancialMonth()+'-'))){
    const shiftKey=`${row.date}|${row.rig}|${row.shift}`;
    const period=grain==='shift'?row.date+'|'+row.shift:grain==='day'?row.date:periodStart(row.date);
    const periodDate=grain==='shift'?row.date:period.split('|')[0];
    const entry=groupMap.get(period)||{date:periodDate,endDate:periodDate,shiftOrder:row.shift==='Өдөр'?0:1,drilledMeters:0,fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,waterKnownRecords:0,waterKnownLitres:0,waterEstimated:false,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,rigs:new Set(),shifts:new Set(),shiftLabels:new Set(),holes:new Set()};
    const meters=Number(row.meters||0);
    entry.drilledMeters+=meters;
    // Every rig-shift of the period is a slot; one without a shift report is unreported, not 0 m.
    if(row.shift==='Өдөр'||row.shift==='Шөнө'){const slots=entry.slots||(entry.slots=new Map()),slot=`${row.date}|${row.rig}|${row.shift}`;slots.set(slot,slots.get(slot)||!!row.recorded);}
    if(row.recorded||row.waterRecorded){entry.waterUsageRecords++;if(row.waterUsageM3==null)entry.waterUsageKnown=false;else{entry.waterUsageM3+=Number(row.waterUsageM3);entry.waterKnownLitres+=Number(row.waterUsageM3)*1000;entry.waterKnownRecords++;entry.waterEstimated||=!!row.waterEstimated;}}
    entry.rigs.add(row.rig);
    if(row.recorded)entry.shifts.add(shiftKey);
    entry.shiftLabels.add(row.shift);
    if(row.hole)entry.holes.add(row.hole);
    entry.fuelCost+=row.fuelCost;
    entry.mudCost+=row.mudCost;
    entry.diamondCost+=row.diamondCost;
    entry.fuelUsageL+=row.fuelUsageL;
    if(row.fuelRecorded)entry.fuelRecords++;
    entry.mudUsageKg+=row.mudUsageKg;
    entry.mudUsageBags+=row.mudUsageBags;
    entry.endDate=row.date>entry.endDate?row.date:entry.endDate;
    groupMap.set(period,entry);
  }
  if(financeAvailable){
    for(const row of finance.rigShifts){
      if(!row.date.startsWith(selectedFinancialMonth()+'-'))continue;
      if($('#rig').value&&row.rig!==$('#rig').value)continue;
      const shiftKey=`${row.date}|${row.rig}|${row.shift}`;
      const period=grain==='shift'?`${row.date}|${row.shift}`:grain==='day'?row.date:periodStart(row.date);
      const entry=groupMap.get(period)||{
        date:grain==='shift'?row.date:period.split('|')[0],endDate:period.split('|')[0],
        shiftOrder:row.shift==='Өдөр'?0:1,drilledMeters:0,fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,waterKnownRecords:0,waterKnownLitres:0,waterEstimated:false,
        laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,rigs:new Set(),shifts:new Set(),shiftLabels:new Set(),holes:new Set(),
      };
      entry.laborCost+=Number(row.laborCost||0);
      entry.foodCost+=Number(row.foodCost||0);
      entry.bonusCost+=Number(row.bonusCost||0);
      entry.incentiveCost+=Number(row.incentiveCost||0);
      entry.rigs.add(row.rig);
      entry.shifts.add(shiftKey);
      entry.shiftLabels.add(row.shift);
      groupMap.set(period,entry);
    }
  }
  const rows=[];
  let runningCost=0,runningMeters=0;
  const sortedEntries=[...groupMap.entries()].sort(([,a],[,b])=>a.date.localeCompare(b.date)||(a.shiftOrder??0)-(b.shiftOrder??0));
  for(let i=0;i<sortedEntries.length;i++){
    const [date,entry]=sortedEntries[i];
    const totalCost=costsComplete?entry.fuelCost+entry.mudCost+entry.diamondCost+entry.laborCost+entry.foodCost+entry.bonusCost+entry.incentiveCost:null;
    const dailyCostPerMeter=totalCost!=null&&entry.drilledMeters>0?totalCost/entry.drilledMeters:null;
    if(totalCost!=null)runningCost += totalCost;
    runningMeters += entry.drilledMeters;
    rows.push({
      date:entry.date,
      period:date,
      periodEnd:entry.endDate,
      drilledMeters:entry.drilledMeters,
      fuelCost:fuelMissing?null:entry.fuelCost,
      mudCost:entry.mudCost,diamondCost:entry.diamondCost,
      fuelUsageL:entry.fuelUsageL,fuelRecords:entry.fuelRecords,mudUsageKg:entry.mudUsageKg,mudUsageBags:entry.mudUsageBags,
      waterUsageM3:entry.waterUsageKnown&&entry.waterUsageRecords>0?entry.waterUsageM3:null,waterKnownRecords:entry.waterKnownRecords,waterKnownLitres:entry.waterKnownLitres,waterPartial:!entry.waterUsageKnown,waterEstimated:entry.waterEstimated,
      laborCost:financeAvailable?entry.laborCost:null,
      foodCost:financeAvailable?entry.foodCost:null,
      bonusCost:financeAvailable?entry.bonusCost:null,
      incentiveCost:financeAvailable?entry.incentiveCost:null,
      totalCost,
      dailyCostPerMeter,
      cumulativeCostPerMeter:costsComplete&&runningMeters>0?runningCost/runningMeters:null,
      completion:costsComplete?'AGGREGATED':'MISSING',
      note:costsComplete?'':financialMissing(finance||{}).join(', ')+' синк хийгдээгүй',
      rigs:[...entry.rigs].join(', '),
      shifts:entry.shifts.size,
      reportedShifts:[...(entry.slots?.values()||[])].filter(Boolean).length,
      unreportedShifts:[...(entry.slots?.values()||[])].filter(recorded=>!recorded).length,
      shiftLabel:[...entry.shiftLabels].join(', '),
      holes:[...entry.holes].join(', '),
      allCosts: [{key:'fuelCost',label:'Түлш',value:fuelMissing?null:entry.fuelCost},{key:'mudCost',label:'Өрөмдлөгийн шавар',value:entry.mudCost},{key:'diamondCost',label:'Алмазан хошуу + reaming shell (тооцоот)',value:entry.diamondCost},{key:'laborCost',label:'Цалин',value:financeAvailable?entry.laborCost:null},{key:'foodCost',label:'Хоол',value:financeAvailable?entry.foodCost:null},{key:'bonusCost',label:'Метрийн бонус',value:financeAvailable?entry.bonusCost:null},{key:'incentiveCost',label:'Урамшуулал',value:financeAvailable?entry.incentiveCost:null}],
    });
  }
  let previous=null;
  for(const row of rows){
    const current=row.dailyCostPerMeter;
    row.dayOverDayPercent = current!=null && previous!=null && previous>0 ? ((current-previous)/previous)*100 : null;
    previous = current;
  }
  return rows;
}
function financialRigSeries(grain=financialGrain){
  const finance=financialFinance();
  const financeAvailable=Boolean(finance?.attendance),costsComplete=financeAvailable&&!finance?.fuelMissing;
  const rigs=selectedRigs(FINANCE_RIGS);
  const operationRows=shifts().filter(row=>row.date.startsWith(selectedFinancialMonth()+'-'));
  const sourceRows=DrillingCosts.records(operationRows,rigs,finance?.mud,finance?.fuel,finance?.diamond,financialWater()),groups=new Map();
  const periodStart=date=>{
    const day=new Date(`${date}T00:00:00Z`);
    if(grain==='week')day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    if(grain==='month')day.setUTCDate(1);
    return day.toISOString().slice(0,10);
  };
  for(const row of sourceRows.filter(row=>row.date.startsWith(selectedFinancialMonth()+'-'))){
    const start=grain==='shift'?row.date:grain==='day'?row.date:periodStart(row.date);
    const shiftOrder=row.shift==='Өдөр'?0:1;
    const key=grain==='shift'?`${start}|${shiftOrder}`:start;
    const groupKey=`${key}|${row.rig}`;
    const meters=Number(row.meters||0),entry=groups.get(groupKey)||{
      key,date:start,shiftOrder,shift:row.shift,rig:row.rig,meters:0,
      fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,waterKnownRecords:0,waterKnownLitres:0,waterEstimated:false,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,
      holes:new Set(),
    };
    entry.meters+=meters;
    entry.fuelCost+=row.fuelCost;
    entry.mudCost+=row.mudCost;
    entry.diamondCost+=row.diamondCost;
    entry.fuelUsageL+=row.fuelUsageL;
    if(row.fuelRecorded)entry.fuelRecords++;
    entry.mudUsageKg+=row.mudUsageKg;
    entry.mudUsageBags+=row.mudUsageBags;
    if(row.hole)entry.holes.add(row.hole);
    groups.set(groupKey,entry);
  }
  if(financeAvailable){
    for(const row of finance.rigShifts){
      if(!row.date.startsWith(selectedFinancialMonth()+'-'))continue;
      if($('#rig').value&&row.rig!==$('#rig').value)continue;
      const start=grain==='shift'?row.date:grain==='day'?row.date:periodStart(row.date);
      const shiftOrder=row.shift==='Өдөр'?0:1;
      const key=grain==='shift'?`${start}|${shiftOrder}`:start;
      const groupKey=`${key}|${row.rig}`;
      const entry=groups.get(groupKey)||{
        key,date:start,shiftOrder,shift:row.shift,rig:row.rig,meters:0,
        fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,waterKnownRecords:0,waterKnownLitres:0,waterEstimated:false,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,holes:new Set(),
      };
      entry.laborCost+=Number(row.laborCost||0);
      entry.foodCost+=Number(row.foodCost||0);
      entry.bonusCost+=Number(row.bonusCost||0);
      entry.incentiveCost+=Number(row.incentiveCost||0);
      groups.set(groupKey,entry);
    }
  }
  const periods=[...new Map([...groups.values()].map(row=>[row.key,row])).values()]
    .sort((a,b)=>a.date.localeCompare(b.date)||a.shiftOrder-b.shiftOrder);
  return rigs.map(rig=>{
    let runningCost=0,runningMeters=0;
    const points=periods.map(period=>{
      const row=groups.get(`${period.key}|${rig}`);
      if(!row)return {key:period.key,date:period.date,shift:period.shift,rig,value:null,cumulative:null,meters:0};
      const cost=row.fuelCost+row.mudCost+row.diamondCost+row.laborCost+row.foodCost+row.bonusCost+row.incentiveCost;
      if(costsComplete)runningCost+=cost;
      runningMeters+=row.meters;
      return {
        key:period.key,date:row.date,shift:row.shift,rig,value:costsComplete&&row.meters?cost/row.meters:null,
        cumulative:costsComplete&&runningMeters?runningCost/runningMeters:null,meters:row.meters,
        fuelCost:row.fuelCost,mudCost:row.mudCost,diamondCost:row.diamondCost,fuelUsageL:row.fuelUsageL,fuelRecords:row.fuelRecords,mudUsageKg:row.mudUsageKg,mudUsageBags:row.mudUsageBags,
        laborCost:row.laborCost,foodCost:row.foodCost,bonusCost:row.bonusCost,incentiveCost:row.incentiveCost,holes:[...row.holes].join(', '),
      };
    });
    return {rig,points};
  });
}
function renderFinancialChart(rows){
  const finance=financialFinance();
  if(!finance)return '<div class="empty">Санхүүгийн эх өгөгдөл синк хийгдээгүй байна.</div>';
  if(!rows.length)return '<div class="empty">Санхүүгийн өгөгдөл байхгүй.</div>';
  if(financialMissing(finance).length)return `<div class="empty">${selectedFinancialMonth()} сарын ${financialMissing(finance).join(', ')} Drive-д ороогүй тул ₮/м тооцох боломжгүй. Өрөмдсөн метр болон бүртгэлтэй зардлыг доор харуулав.</div>`;
  const series=financialRigSeries(),width=1200,height=350,left=82,right=30,top=28,bottom=58,plotHeight=height-top-bottom;
  const allPoints=series.flatMap(item=>item.points),maxValue=Math.max(...allPoints.map(point=>point.value||0),1);
  const xAt=(index,total)=>left+(index/(Math.max(total-1,1)))*(width-left-right);
  const yAt=(value)=>top+plotHeight-((value/maxValue)*plotHeight);
  const colors=RIG_COLORS;
  const pointSvg=(item)=>{
    const {rig,points}=item,color=colors[rig],label=rig;
    const paths=[];
    let segment=[];
    points.forEach((point,index)=>{
      const value=point.value;
      if(value==null||!Number.isFinite(value)){if(segment.length)paths.push(segment.join(' '));segment=[];return;}
      segment.push(`${xAt(index,points.length)},${yAt(value)}`);
    });
    if(segment.length)paths.push(segment.join(' '));
    return paths.map(pathPoints=>`<polyline class="rig-cost-line" data-rig="${rig}" points="${pathPoints}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`).join('') + points.map((point,index)=>point.value==null?'':`<circle cx="${xAt(index,points.length)}" cy="${yAt(point.value)}" r="4" fill="${color}"><title>${esc(point.date)}${financialGrain==='shift'?` · ${esc(point.shift)}`:''} · ${esc(rig)} · ${esc(point.holes||'—')} · Өрөмдсөн: ${fmt(point.meters)} м · Түлш: ${currency(point.fuelCost,0)} (${point.fuelRecords?fmt(point.fuelUsageL,2):'—'} л, олголт) · Шавар: ${currency(point.mudCost,0)} (${fmt(point.mudUsageKg,2)} кг, хуваарилсан) · Алмазан хошуу (тооцоот): ${currency(point.diamondCost,0)} · Үндсэн цалин: ${currency(point.laborCost,0)} · Хоол: ${currency(point.foodCost,0)} · Метрийн бонус: ${currency(point.bonusCost,0)} · Урамшуулал: ${currency(point.incentiveCost,0)} · 1 м зардал: ${currency(point.value,0)} · Хуримтлагдсан: ${currency(point.cumulative,0)} /м</title></circle>`).join('');
  };
  const axisTicks=[0,Math.ceil(maxValue/4),Math.ceil(maxValue/2),Math.ceil(maxValue*0.75),Math.ceil(maxValue)].filter((v,i,a)=>a.indexOf(v)===i);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Өрөмдлөгийн метрийн өртөг болон хуримтлагдсан өртгийн график">`;
  axisTicks.forEach(value=>{const y=yAt(value);svg+=`<line x1="${left}" x2="${width-right}" y1="${y}" y2="${y}" stroke="#3b3b3e"/><text x="${left-10}" y="${y+4}" text-anchor="end">${currency(value,0)}</text>`;});
  series.forEach(item=>{svg+=pointSvg(item);});
  const points=series[0]?.points||[];
  points.forEach((point,index)=>{const x=xAt(index,points.length),label=financialGrain==='shift'?`${point.date.slice(8)} ${point.shift==='Өдөр'?'Ө':'Ш'}`:financialGrain==='week'?`${point.date.slice(5)}-с`:financialGrain==='month'?point.date.slice(0,7):point.date.slice(5).replace('-','.');svg+=`<text x="${x}" y="${height-14}" text-anchor="middle" fill="#9aabb3">${esc(label)}</text>`;});
  svg += `</svg><div class="legend"><i class="rig-orange"></i>C-1800 <i class="rig-green"></i>CSD-1300 · ${financialGrainLabel()} зардал/м</div>`;
  return svg;
}
function renderFinancialTab(){
  const finance=financialFinance();
  const rows=financialRows(financialGrain);
  const chartPanel=`<section class="panel financial-panel"><div class="panel-head"><div><h2>Өрөм тус бүрийн 1 метрийн зардал (₮/м)</h2><span class="sub">C-1800 болон CSD-1300 · ${selectedFinancialMonth()}</span></div>${financialControls()}</div>${renderFinancialChart(rows)}</section>`;
  if(!rows.length||!finance)return `<div class="financial-wrap">${chartPanel}</div>`;
  const completed=rows.filter(row=>row.drilledMeters>0&&Number.isFinite(row.dailyCostPerMeter));
  const latest=completed.at(-1),previous=completed.at(-2),last=rows.at(-1),prior=rows.at(-2);
  const dailyValue=latest?.dailyCostPerMeter??null,previousValue=previous?.dailyCostPerMeter??null;
  const change=dailyValue!=null&&previousValue>0?(dailyValue-previousValue)/previousValue*100:null;
  const periodLabel=row=>row?row.date+(financialGrain==='shift'?' · '+row.shiftLabel:''):'';
  const tone=(current,before)=>current==null||before==null||current===before?'flat':current>before?'up':'down';
  const costTone=tone(dailyValue,previousValue);
  const comparisonNote=change!=null?`${periodLabel(latest)}: ${currency(dailyValue)} /м ↔ ${periodLabel(previous)}: ${currency(previousValue)} /м`:'Өмнөх хугацааны ₮/м бүртгэл алга';
  const missing=financialMissing(finance);
  const periodNote=latest?periodLabel(latest)+(change==null?'':` · ${change>0?'▲':change<0?'▼':'•'} ${fmt(Math.abs(change),1)}%`):missing.length?missing.join(', ')+' синк хийгдээгүй':'Өрөмдсөн метрийн бүртгэл алга';
  const totalMeters=rows.reduce((sum,r)=>sum+r.drilledMeters,0);
  const totalCost=rows.some(row=>row.totalCost==null)?null:rows.reduce((sum,r)=>sum+r.totalCost,0);
  const totalFuel=rows.reduce((sum,r)=>sum+r.fuelCost,0);
  const totalFuelUsage=rows.reduce((sum,r)=>sum+r.fuelUsageL,0),totalMudUsage=rows.reduce((sum,r)=>sum+r.mudUsageKg,0);
  const priorRows=rows.slice(0,-1),priorMeters=priorRows.reduce((total,row)=>total+row.drilledMeters,0);
  const fuelUnit=totalMeters&&!finance.fuelMissing?totalFuel/totalMeters:null,priorFuelUnit=priorMeters&&!finance.fuelMissing?priorRows.reduce((total,row)=>total+row.fuelCost,0)/priorMeters:null;
  const cumulativeNote=prior?.cumulativeCostPerMeter!=null?`${periodLabel(last)}: ${currency(last.cumulativeCostPerMeter)} /м ↔ ${periodLabel(prior)}: ${currency(prior.cumulativeCostPerMeter)} /м`:'';
  const fuelNote=priorFuelUnit!=null?`${periodLabel(last)}: ${currency(fuelUnit)} /м ↔ ${periodLabel(prior)}: ${currency(priorFuelUnit)} /м`:'';
  const kpis=[
    {label:`Сүүлийн ${financialGrainLabel().toLocaleLowerCase()} зардал (₮/м)`,value:dailyValue==null?'—':currency(dailyValue,0),note:periodNote,tone:costTone},
    {label:'Хуримтлагдсан зардал (₮/м)',value:currency(last.cumulativeCostPerMeter,0),tone:tone(last.cumulativeCostPerMeter,prior?.cumulativeCostPerMeter??null),note:cumulativeNote},
    {label:`Өмнөх ${financialGrain==='shift'?'ээлжтэй':financialGrain==='day'?'өдөртэй':financialGrain==='week'?'7 хоногтой':'сартай'} харьцуулсан өөрчлөлт (%)`,value:change==null?'—':`${fmt(change,1)}%`,note:comparisonNote,tone:costTone},
    {label:'Нийт зардал (₮)',value:currency(totalCost,0)},
    {label:'Нийт өрөмдсөн метр (м)',value:fmt(totalMeters,1)},
    {label:'Түлшний зардал (₮/м)',value:currency(fuelUnit,0),tone:tone(fuelUnit,priorFuelUnit),note:fuelNote},
    {label:'Нийт түлшний олголт (л)',value:finance.fuelMissing?'—':fmt(totalFuelUsage,2)},
    {label:'Нийт шаврын хэрэглээ (кг)',value:fmt(totalMudUsage,2)},
  ];
  const categories=[['fuelCost','Түлш'],['mudCost','Өрөмдлөгийн шавар'],['diamondCost','Алмазан хошуу + reaming shell (тооцоот)'],['laborCost','Үндсэн цалин'],['foodCost','Хоолны зардал'],['bonusCost','Метрийн бонус'],['incentiveCost','Урамшуулал']];
  const breakdown=categories.map(([key,label])=>({key,label,current:rows.some(row=>row[key]==null)?null:rows.reduce((total,row)=>total+row[key],0)}));
  const breakdownMax=Math.max(...breakdown.map(item=>item.current||0),1);
  const costRows=breakdown.map(item=>{
    if(item.current==null){
      const status='Эх сурвалж синк хийгдээгүй';
      return `<div class="cost-row"><div class="cost-label"><span>${item.label}</span><strong>${status}</strong></div></div>`;
    }
    const usage=item.key==='fuelCost'?`<div class="sub cost-usage">Өрөмд олгосон: ${fmt(totalFuelUsage,2)} л</div>`:item.key==='mudCost'?`<div class="sub cost-usage">Хуваарилсан хэрэглээ: ${fmt(totalMudUsage,2)} кг · ${fmt(rows.reduce((total,row)=>total+row.mudUsageBags,0),2)} шуудай (${fmt(finance?.mud?.bagKg||25,0)} кг)</div>`:'';
    return `<div class="cost-row"><div class="cost-label"><span>${item.label}</span><strong>${currency(item.current,0)}</strong></div>${usage}<div class="cost-bar"><span style="width:${((item.current||0)/breakdownMax)*100}%"></span></div></div>`;
  }).join('');
  return `<div class="financial-wrap">
    ${chartPanel}
    <div class="kpis">${kpis.map(item=>`<article class="kpi${item.tone?` financial-trend ${item.tone}`:''}"><div class="label">${item.label}</div><div class="value">${item.value}</div>${item.note?`<div class="note">${esc(item.note)}</div>`:''}</article>`).join('')}</div>
    <section class="panel">
      <h2>Зардлын задаргаа</h2>
      <div class="cost-breakdown">${costRows}</div>
      <p class="sub">Усны бүртгэлтэй хэмжээ: ${fmt(rows.reduce((n,r)=>n+r.waterKnownLitres,0),0)} л${rows.some(r=>r.waterEstimated)?' · рейсээс тооцсон таамаг':''}. ${finance?.water?'1 рейс = '+fmt(finance.water.litresPerTrip,0)+' л'+(finance.water.estimated?' (багтаамж баталгаажаагүй)':'')+'. ':''}Тайлангүй усны хэрэглээг 0 гэж үзээгүй. Усны машины түлшийг өртөгт оруулаагүй.</p>
      ${(finance?.fuel?.coverage||[]).some(r=>r.recordedShifts<r.expectedShifts)?'<p class="sub">Түлш: зарим өдөр ээлжийн олголт дутуу. Нийт нь зөвхөн бүртгэлтэй олголт; дутуу ээлжийг 0 гэж үзээгүй.</p>':''}
      ${finance?.diamond?`<p class="sub">Алмазан хошуу + reaming shell: ${currency(finance.diamond.ratePerMeter,0)}/м × бүртгэлтэй метр. ${fmt(finance.diamond.plannedMeters,0)} м төлөвлөгөөний ${currency(finance.diamond.totalBudget,0)} төсвийг хуваарилсан тооцоо; бодит солилт/элэгдэл биш. <a href="${esc(finance.diamond.sourceUrl)}" target="_blank" rel="noopener noreferrer">Эх тооцоо</a></p>`:''}
    </section>
    <section class="panel">
      <h2>Дэлгэрэнгүй бүртгэл</h2>
      <div class="table-scroll financial-details-scroll">
        <table class="financial-details-table">
          <thead><tr><th>Хугацаа</th><th>Өрөм</th><th>Ээлж</th><th>Цооног</th><th>Метр</th><th>Түлш (л, олголт)</th><th>Шавар (кг, хуваарилсан)</th><th>Усны хэрэглээ (л)</th><th>Алмазан хошуу ₮ (тооцоот)</th><th>Дүн ₮ </th><th>₮/м </th></tr></thead>
          <tbody>${[...rows].reverse().map(r=>`<tr>
            <td data-label="Хугацаа">${r.date}</td>
            <td data-label="Өрөм">${esc(r.rigs||'—')}</td>
            <td data-label="Ээлж">${esc(r.shiftLabel||'—')}</td>
            <td data-label="Цооног">${esc(r.holes||'—')}</td>
            <td data-label="Метр">${r.reportedShifts?fmt(r.drilledMeters,1)+' м':r.unreportedShifts?'Тайлангүй':'—'}${r.reportedShifts&&r.unreportedShifts?`<small class="unreported">${r.unreportedShifts} ээлж тайлангүй</small>`:''}</td>
            <td data-label="Түлш (л, олголт)">${r.fuelRecords?fmt(r.fuelUsageL,2):'—'}</td>
            <td data-label="Шавар (кг, хуваарилсан)">${fmt(r.mudUsageKg,2)}</td>
            <td data-label="Усны хэрэглээ (л)">${r.waterKnownRecords?(r.waterPartial?'≥ ':'')+fmt(r.waterKnownLitres,0)+' л'+(r.waterEstimated?' · таамаг':''):'—'}</td>
            <td data-label="Алмазан хошуу ₮ (тооцоот)">${currency(r.diamondCost,0)}</td>
            <td data-label="Нийт зардал">${currency(r.totalCost,0)}</td>
            <td data-label="₮/м">${r.dailyCostPerMeter==null?'N/A':currency(r.dailyCostPerMeter,0)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </section>
  </div>`;
}
function overviewMonths(){return [...new Set(D.shifts.map(row=>row.date.slice(0,7)))].sort().reverse();}
function overviewRows(){
  const months=overviewMonths();
  if(chartMonth===null||(chartMonth&&!months.includes(chartMonth)))chartMonth=months[0]||'';
  return shifts().filter(row=>!chartMonth||row.date.startsWith(chartMonth+'-'));
}
function overviewPeriodLabel(){return chartMonth?chartMonth.slice(0,4)+' оны '+Number(chartMonth.slice(5))+'-р сар':'Нийт хугацаа';}
function kpis(){
  const rows=['overview','rop','utilization'].includes(tab)?overviewRows():shifts(),dt=sum(rows,'dt'),hours=sum(rows,'hours');
  const cards=[['Тайлант хугацаанд өрөмдсөн',fmt(sum(rows,'meters')),'м','overview'],['Бүртгэлтэй цооног',holes().length,'ш','holes'],['Өрөмдлөгийн ашиглалт',hours?fmt(dt/hours*100):'—','%','utilization'],['Дундаж хурд · ROP',dt?fmt(sum(rows,'meters')/dt,2):'—','м/ц','rop']];
  return '<div class="kpis">'+cards.map(([label,value,unit,target])=>`<button class="kpi ${tab===target?'selected':''}" data-go="${target}" aria-pressed="${tab===target}"><span class="label">${label}</span><span class="value">${value} <small>${unit}</small></span></button>`).join('')+'</div>';
}
function barPeriod(bar){return (bar.group.start===bar.group.end?bar.group.start:bar.group.start+' – '+bar.group.end)+(grain==='shift'?' · '+(bar.group.secondary==='Ө'?'Өдөр':'Шөнө'):'');}
function barDifference(bar){const difference=bar.meters-bar.target;return difference<0?'Нормоос дутуу: '+fmt(-difference)+' м':difference>0?'Нормоос давсан: '+fmt(difference)+' м':'Норм биелсэн';}
function barSummary(bar){return `${barPeriod(bar)} · ${bar.rig}. Өрөмдсөн: ${fmt(bar.meters)} м. Норм: ${fmt(bar.target)} м. ${barDifference(bar)}.`;}
function hideBarTooltip(){const tooltip=$('#bar-tooltip');if(tooltip)tooltip.hidden=true;}
function showBarTooltip(element,event){
  const bar=chartBars[Number(element.dataset.barIndex)];if(!bar)return;
  const tooltip=$('#bar-tooltip'),notes=[...new Set(bar.rows.map(row=>row.notes).filter(Boolean))];
  tooltip.innerHTML=`<strong>${esc(barPeriod(bar))} · ${esc(bar.rig)}</strong><span>Өрөмдсөн: <b>${fmt(bar.meters)} м</b></span><span>Норм: ${fmt(bar.target)} м</span><span>${barDifference(bar)}</span>${bar.meters<bar.target&&notes.length?`<p>${notes.map(esc).join('<br>')}</p>`:''}<small>${bar.reports.length?'Тайлангийн зураг үзэх ↗':'Тайлангийн зураг холбогдоогүй'}</small>`;
  tooltip.hidden=false;const bounds=element.getBoundingClientRect(),x=event?.clientX??bounds.right,y=event?.clientY??bounds.top;
  tooltip.style.left=Math.max(8,Math.min(x+14,innerWidth-tooltip.offsetWidth-8))+'px';
  tooltip.style.top=Math.max(8,Math.min(y+14,innerHeight-tooltip.offsetHeight-8))+'px';
}
function openBarReports(bar){
  hideBarTooltip();
  $('#detail-body').innerHTML=`<h2>${esc(barPeriod(bar))} · ${esc(bar.rig)}</h2><p>Өрөмдсөн ${fmt(bar.meters)} м · ${barDifference(bar)}</p><div class="report-list">${bar.rows.map(row=>`<section><h3>${esc(row.date)} · ${esc(row.shift)} · ${esc(row.hole)} · ${fmt(row.meters)} м</h3>${row.reports?.length?row.reports.map(report=>`<a href="${esc(report.url)}" target="_blank" rel="noopener">Тайлангийн зураг ↗</a>`).join(''):'<span>Тайлангийн зураг холбогдоогүй.</span>'}</section>`).join('')}</div>`;
  $('#detail').showModal();
}
document.addEventListener('pointermove',event=>{const bar=event.target.closest('[data-bar-index]');if(bar)showBarTooltip(bar,event);else hideBarTooltip();});
document.addEventListener('focusin',event=>{const bar=event.target.closest('[data-bar-index]');if(bar)showBarTooltip(bar);else hideBarTooltip();});
document.addEventListener('focusout',hideBarTooltip);
document.addEventListener('pointerout',event=>{if(!event.relatedTarget)hideBarTooltip();});
document.addEventListener('scroll',hideBarTooltip,true);
window.addEventListener('blur',hideBarTooltip);
document.addEventListener('keydown',event=>{const bar=event.target.closest('g[data-bar-index]');if(bar&&['Enter',' '].includes(event.key)){event.preventDefault();openBarReports(chartBars[Number(bar.dataset.barIndex)]);}});
function chart(){
  hideBarTooltip();chartBars=[];
  const rows=overviewRows(),months=overviewMonths(),rigs=selectedRigs();
  const groups=DrillingChart.fill(DrillingChart.aggregate(rows,grain,chartMonth),grain,chartMonth,D.shiftAudit?.through||D.asOf);
  // Unreported shifts are marked from the shift audit (! missing report, ? unverified); an area filter hides other areas' shifts, so no marks then.
  const auditIndex=AuditModel.index(D.shiftAudit),markShifts=!$('#area').value&&['shift','day'].includes(grain);
  const controls=`<div class="chart-controls"><label class="chart-month">Сар <select id="chart-month" aria-label="Гүйцэтгэлийн сар"><option value=""${chartMonth===''?' selected':''}>Нийт хугацаа</option>${months.map(month=>`<option value="${month}"${month===chartMonth?' selected':''}>${month.slice(0,4)} оны ${Number(month.slice(5))}-р сар</option>`).join('')}</select></label><div class="chart-periods" role="group" aria-label="Графикийн хугацаа">${[['shift','Ээлж'],['day','Өдөр'],['week','7 хоног'],['month','Сар']].map(([value,label])=>`<button data-grain="${value}" aria-pressed="${grain===value}">${label}</button>`).join('')}</div></div>`;
  const targetLabels={shift:'30 м / ээлж / өрөм',day:'60 м / өдөр / өрөм',week:'420 м / 7 хоног / өрөм',month:'60 м × сарын хоног / өрөм'};
  let html=`<div class="panel-head"><h2>Гүйцэтгэл · ${overviewPeriodLabel()}</h2>${controls}</div>`;
  if(!groups.length)return html+'<div class="empty">Ээлжийн өгөгдөл байхгүй.</div>';
  const W=Math.max(600,groups.length*(grain==='shift'?44:48)+90),H=280,left=45,right=18,top=30,bottom=grain==='shift'?58:40,plotH=H-top-bottom,step=(W-left-right)/groups.length;
  const high=Math.max(...groups.map(g=>Math.max(g.target,...Object.values(g.amounts)))),unit=high>600?300:high>180?60:30,max=Math.ceil(high*1.12/unit)*unit;
  const y=value=>top+plotH-value/max*plotH;
  let svg=`<svg viewBox="0 0 ${W} ${H}" style="min-width:${W}px" role="group" aria-label="Гүйцэтгэл, ${targetLabels[grain]}"><text x="6" y="14">м</text>`;
  const tick=Math.max(unit,Math.ceil(max/5/unit)*unit);
  for(let n=0;n<=max;n+=tick)svg+=`<line x1="${left}" x2="${W-right}" y1="${y(n)}" y2="${y(n)}" stroke="#e8eded"/><text x="${left-8}" y="${y(n)+4}" text-anchor="end">${fmt(n,0)}</text>`;
  const barWidth=Math.min(17,(step-14)/rigs.length),colors=RIG_COLORS;
  groups.forEach((group,i)=>{
    const x=left+(i+0.5)*step;
    rigs.forEach((rig,j)=>{const value=group.amounts[rig]||0,recorded=group.counts[rig]||0,bx=x+(j-rigs.length/2)*barWidth;
      const audited=markShifts?(grain==='shift'?[group.secondary==='Ө'?'Өдөр':'Шөнө']:['Өдөр','Шөнө']).map(shift=>auditIndex.get(rig+'|'+group.start+'|'+shift)).filter(Boolean):[];
      const gap=audited.find(slot=>slot.status==='MISSING_REPORT')||(!recorded&&audited.find(slot=>slot.status==='UNVERIFIED'));
      if(gap)svg+=`<text class="audit-mark ${auditClass(gap.status)}" x="${bx+barWidth/2-1}" y="${recorded?y(value)-6:y(0)-4}" text-anchor="middle"><title>${esc(auditTitle(gap))}</title>${gap.status==='MISSING_REPORT'?'!':'?'}</text>`;
      if(!recorded)return;
      const records=group.rows.filter(row=>row.rig===rig).sort((a,b)=>a.date.localeCompare(b.date)||(a.shift==='Өдөр'?0:1)-(b.shift==='Өдөр'?0:1)),reports=[...new Map(records.flatMap(row=>row.reports||[]).map(report=>[report.url,report])).values()];
      const bar={rig,group,rows:records,reports,meters:value,target:group.target},index=chartBars.push(bar)-1;
      const label=barSummary(bar),single=reports.length===1&&records.every(row=>row.reports?.length);
      const attrs=`data-bar-index="${index}" aria-label="${esc(label)}" aria-describedby="bar-tooltip"`;
      svg+=single?`<a ${attrs} href="${esc(reports[0].url)}" target="_blank" rel="noopener">`:`<g ${attrs} role="button" tabindex="0" aria-haspopup="dialog">`;
      const height=Math.max(value/max*plotH,3);
      svg+=`<rect x="${bx-2}" y="${y(value)-3}" width="${barWidth+2}" height="${Math.max(height+6,12)}" fill="transparent"/><rect class="bar-fill" x="${bx}" y="${y(0)-height}" width="${barWidth-2}" height="${height}" rx="2" fill="${colors[rig]}"/>`;
      svg+=single?'</a>':'</g>';
    });
    svg+=`<text x="${x}" y="${H-bottom+22}" text-anchor="middle">${group.label}</text>`;
    if(group.secondary)svg+=`<text x="${x}" y="${H-bottom+39}" text-anchor="middle">${group.secondary}</text>`;
  });
  const points=[];groups.forEach((g,i)=>{const x1=left+i*step;points.push(x1+','+y(g.target),(x1+step)+','+y(g.target));});
  svg+=`<polyline data-target-line="${grain}" points="${points.join(' ')}" fill="none" stroke="#ba5264" stroke-width="1.8" stroke-dasharray="6 4"/>`;
  const last=groups.at(-1);svg+=`<text class="target-label" x="${W-right-3}" y="${y(last.target)-7}" text-anchor="end">Норм ${fmt(last.target)} м</text></svg>`;
  return html+`<div class="chart-canvas" tabindex="0" aria-label="Графикийг хэвтээ гүйлгэж үзэх">${svg}</div>`;
}
function rigs(){return selectedRigs().map(rig=>{const rows=overviewRows().filter(x=>x.rig===rig),dt=sum(rows,'dt'),hours=sum(rows,'hours');return `<div class="rig-card"><div class="rig-title"><span>${rig}</span><span>${fmt(sum(rows,'meters'))} м</span></div><div class="rig-stats"><span>${rows.length} ээлж</span><span>ROP ${dt?fmt(sum(rows,'meters')/dt,2):'—'} м/ц</span></div><div class="track"><span style="width:${hours?dt/hours*100:0}%;background:${RIG_COLORS[rig]}"></span></div><div class="rig-stats"><span>Ашиглалт ${hours?fmt(dt/hours*100):'—'}%</span><span>ST ${knownHours(rows,'st')} цаг</span></div></div>`;}).join('');}
function holeTable(){
  const list=holes().filter(h=>h.id.toLowerCase().includes(query.toLowerCase()));
  return '<div class="table-scroll"><table><thead><tr><th>Цооног</th><th>Талбай</th><th>Участик</th><th>Өрөм</th><th>Төлөв</th><th>Төлөвлөсөн</th><th>Ээлжийн гүн</th><th>Collar гүн</th><th>Ахиц</th></tr></thead><tbody>'+list.map(h=>{
    const d=depth(h.id),state=status(h),rig=D.shifts.find(s=>s.hole===h.id)?.rig,percent=d!=null&&h.plan?d/h.plan*100:null,expanded=selectedHole===h.id;
    let row='<tr class="'+(expanded?'selected-hole':'')+'"><td><button class="hole-link" data-depth-hole="'+esc(h.id)+'" aria-expanded="'+expanded+'">'+esc(h.id)+' '+(expanded?'▾':'▸')+'</button></td><td>'+SITE+'</td><td>'+esc(areaOf(h))+'</td><td>'+esc(rig||'—')+'</td><td><span class="badge '+state[1]+'">'+state[0]+'</span></td><td>'+fmt(h.plan)+' м</td><td>'+fmt(d)+' м</td><td>'+fmt(h.collarDepth)+' м</td><td><div class="mini"><div class="track"><span style="width:'+Math.min(percent||0,100)+'%"></span></div>'+(percent==null?'—':fmt(percent)+'%')+'</div></td></tr>';
    if(expanded)row+='<tr class="depth-row"><td colspan="9"><section class="hole-depth-panel" aria-label="'+h.id+' гүний график">'+holeDepthChart(h)+'</section></td></tr>';
    return row;
  }).join('')+'</tbody></table></div>'+(list.length?'':'<div class="empty">Цооног олдсонгүй.</div>');
}
function holeDepthChart(h){
  const segments=DrillingChart.depthSeries(shifts(),h.id),points=segments.flat();
  let html='<h3>'+esc(h.id)+' · Гүний явц</h3>';
  if(!points.length)return html+'<div class="empty">Энэ цооногийн ээлжийн гүний өгөгдөл байхгүй.</div>';
  const W=760,H=300,left=65,right=22,top=22,bottom=50,start=Math.min(...points.map(p=>p.time)),end=Math.max(...points.map(p=>p.time)),deepest=Math.max(...points.map(p=>-p.depth)),tick=deepest>300?100:deepest>100?50:20,limit=Math.max(tick,Math.ceil(deepest/tick)*tick);
  const x=time=>left+(time-start)/Math.max(end-start,1)*(W-left-right),y=depth=>top+(-depth)/limit*(H-top-bottom);
  let svg='<svg data-depth-chart="'+h.id+'" viewBox="0 0 '+W+' '+H+'" style="min-width:600px" role="img" aria-label="'+h.id+' хугацаа ба хасах гүний шугаман график"><text x="8" y="13">Гүн (м)</text>';
  for(let n=0;n<=limit;n+=tick)svg+='<line x1="'+left+'" x2="'+(W-right)+'" y1="'+y(-n)+'" y2="'+y(-n)+'" stroke="#e1e9e6"/><text x="'+(left-10)+'" y="'+(y(-n)+4)+'" text-anchor="end">'+(n?'−':'')+fmt(n,0)+'</text>';
  const DAY=86400000,step=Math.max(1,Math.ceil((end-start)/DAY/8))*DAY,times=[start];
  for(let t=Math.ceil(start/DAY)*DAY;t<end;t+=step)if(t>start)times.push(t);times.push(end);
  let previous=-Infinity;
  for(const t of times){const px=x(t);if(px-previous<45&&t!==end)continue;if(t===end&&px-previous<45)continue;previous=px;svg+='<text x="'+px+'" y="'+(H-bottom+22)+'" text-anchor="middle">'+new Date(t).toISOString().slice(5,10).replace('-','.')+'</text>';}
  for(const segment of segments)svg+='<polyline points="'+segment.map(p=>x(p.time)+','+y(p.depth)).join(' ')+'" fill="none" stroke="#128875" stroke-width="2.5"/>';
  for(const p of points)svg+='<circle cx="'+x(p.time)+'" cy="'+y(p.depth)+'" r="3.2" fill="#128875"><title>'+p.date+' · '+p.shift+' · '+(p.edge==='start'?'Эхлэл':'Төгсгөл')+': '+(p.depth?'−':'')+fmt(-p.depth)+' м</title></circle>';
  svg+='<text x="'+((W+left-right)/2)+'" y="'+(H-6)+'" text-anchor="middle">Хугацаа</text></svg>';
  return html+'<div class="chart-canvas">'+svg+'</div>';
}
function shiftTable(){const rows=shifts().filter(x=>(x.hole+' '+x.driller+' '+x.date).toLowerCase().includes(query.toLowerCase())).sort((a,b)=>b.date.localeCompare(a.date)||a.rig.localeCompare(b.rig));return `<div class="table-scroll"><table><thead><tr><th>Огноо / ээлж</th><th>Өрөм</th><th>Цооног</th><th>Өрөмдөгч</th><th>Гүний интервал</th><th>Метр</th><th>DT / ST цаг</th><th>ROP м/ц</th></tr></thead><tbody>${rows.map(s=>`<tr title="${esc(s.notes)}"><td>${s.date}<br><small>${esc(s.shift)}</small></td><td>${s.rig}</td><td><button class="hole-link" data-hole="${s.hole}">${s.hole}</button></td><td>${esc(s.driller)}</td><td>${fmt(s.from)} – ${fmt(s.to)}</td><td><strong>${fmt(s.meters)}</strong></td><td>${fmt(s.dt)} / ${fmt(s.st)}</td><td>${s.dt?fmt(s.meters/s.dt,2):'—'}</td></tr>`).join('')||'<tr><td colspan="8" class="empty">Ээлж олдсонгүй.</td></tr>'}</tbody></table></div>`;}
function performanceTable(){return `<section class="panel"><h2>${tab==='rop'?'Дундаж хурд · ROP':'Өрөмдлөгийн ашиглалт'}</h2><div class="table-scroll"><table><thead><tr><th>Өрөм</th><th>Өрөмдсөн</th><th>DT цаг</th><th>Нийт цаг</th><th>Ашиглалт</th><th>ROP м/ц</th></tr></thead><tbody>${selectedRigs().map(r=>{const rows=overviewRows().filter(s=>s.rig===r),dt=sum(rows,'dt'),hours=sum(rows,'hours'),m=sum(rows,'meters');return `<tr><td>${r}</td><td>${fmt(m)} м</td><td>${fmt(dt)}</td><td>${fmt(hours)}</td><td>${hours?fmt(dt/hours*100)+'%':'—'}</td><td>${dt?fmt(m/dt,2):'—'}</td></tr>`;}).join('')}</tbody></table></div></section>`;}
function dataRows(){const ids=new Set(holes().map(h=>h.id));return DrillingData.rows(D.collar.filter(h=>ids.has(h.id)),D.shifts,D.dataInventory,D.folderMap,logRegister).filter(r=>r.id.toLowerCase().includes(query.toLowerCase()));}
const dataLink=(url,html)=>url?`<a class="data-link" href="${esc(url)}" target="_blank" rel="noopener">${html}</a>`:html;
const dataCell=(html,note='',url='')=>dataLink(url,html)+(note?`<small>${note}</small>`:'');
const readinessClass=state=>({dual:'',ai:'',geologist:'',missing:'warn',drilling:'active'}[state]??'planned');
const loggedClass=(r)=>({done:'',partial:'active',none:r.hole.finish?'warn':'planned'}[r.logged.state]??'planned');
const registerText=value=>!value?'—':/complete/i.test(value)?'✓':esc(value);
// Geological / geotechnical logging is done once a file named as a log is in the hole's 04 / 07 folder.
const logStatus=done=>`<strong class="log-${done?'done':'missing'}">${done?'Хийгдсэн':'Хийгдээгүй'}</strong>`;
const logFileNote=log=>dataLink(log.file.url,'✓ '+esc(log.format))+(log.files.length>1?' · + '+(log.files.length-1)+' файл':'')
  +(log.registered?' · бүртгэсэн '+esc(log.registered.date):'');
function dataTable(){
  if(!D.dataInventory)return '<div class="empty">Drive дээрх файлын жагсаалт хараахан уншигдаагүй. Дараагийн Drive синкээр орно.</div>';
  const list=dataRows();
  return '<div class="table-scroll"><table class="data-table"><thead><tr><th>Цооног</th><th>Участик</th><th>Өрөмдлөг</th><th>Collar</th><th>Кернийн зураг</th><th>pXRF</th><th>Хазайлтын хэмжилт</th><th>Геологийн лог</th><th>Геотехникийн лог</th></tr></thead><tbody>'+list.map(r=>{
    const h=r.hole,state=status(h),g=r.geology,t=r.geotech,p=r.photos;
    const formats=Object.entries(p.formats).map(([format,count])=>format+' '+count).join(' · ');
    const geology=logStatus(g.done)+(g.done?'<small>'+logFileNote(g)+'</small>':g.state==='handwritten'?'<small>'+dataLink(g.url,'Гар бичмэл')+' · '+g.handwritten+' зураг/PDF</small>':g.state==='other'?'<small>'+dataLink(g.url,g.files.length+' файл')+'</small>':'');
    const geotech=logStatus(t.done)+(t.done?'<small>'+logFileNote(t)+'</small>':t.state==='technical'?'<small>'+dataLink(t.file.url,'Technical Data')+' · загварт хөрвүүлэх</small>':'');
    return '<tr><td><button class="hole-link" data-data-hole="'+esc(r.id)+'">'+esc(r.id)+'</button></td><td>'+esc(areaOf(h))+'</td>'
      +'<td><span class="badge '+state[1]+'">'+state[0]+'</span><small>'+esc(h.start||'—')+' – '+esc(h.finish||'…')+'</small></td>'
      +'<td>'+(r.collar.depth==null?'—':fmt(r.collar.depth)+' м')+'<small>'+(r.collar.registered?'E/N '+(r.collar.coordinates?'✓':'—')+' · Z '+(r.collar.elevation?'✓':'—'):'Collar-д мөргүй · Drive хавтаснаас бүртгэсэн')+'</small></td>'
      +'<td>'+(p.count?dataCell(p.count+' зураг',esc(formats)+(p.boxes==null?'':' · '+fmt(p.boxes,0)+' хайрцаг'),p.url):dataCell('—',p.boxes==null?'':fmt(p.boxes,0)+' хайрцаг'))+'</td>'
      +'<td>'+(r.pxrf.count?dataCell(r.pxrf.count+' файл','',r.pxrf.url):'—')+'</td>'
      +'<td>'+(r.surveys.count?dataCell(r.surveys.count+' файл','',r.surveys.url):'—')+'</td>'
      +'<td>'+geology+'</td><td>'+geotech+'</td></tr>';
  }).join('')+'</tbody></table></div>'+(list.length?'':'<div class="empty">Цооног олдсонгүй.</div>');
}
function drillingData(){
  const all=D.dataInventory?dataRows():[],finished=all.filter(r=>r.hole.finish);
  const summary=finished.length?[['geology','Геологи'],['geotech','Геотехник']].map(([key,title])=>{const done=finished.filter(r=>r[key].done).length;
    return [['done','хийгдсэн',done],['missing','хийгдээгүй',finished.length-done]].filter(([,,count])=>count).map(([style,label,count])=>`<span class="badge log-${style}">${title} ${label}: ${count}</span>`).join('');}).join('<span class="data-summary-gap"></span>'):'';
  return `<section class="panel"><div class="panel-head"><div><h2>Drilling Data</h2><span class="sub">Лог хийхэд хэрэгтэй дата · бүртгэлтэй ${D.collar.length} цооног</span></div><input class="search" aria-label="Цооног хайх" placeholder="Цооног хайх…" value="${esc(query)}"></div>${summary?`<div class="data-summary">${summary}</div>`:''}<div id="table">${dataTable()}</div>
    <p class="sub data-note">Drive дээрх цооногийн хавтсуудын (03 хэмжилт, 04 геологи, 05 зураг, 07 геотехник, 10 pXRF) файлын нэрээр тодорхойлсон; файлын агуулгыг шалгаагүй. Зураг нэг нэрээр нэг тоологдоно (CR2 ба JPG хуулбар нэг зураг). 04 / 07 хавтсанд нэрэнд нь Log, logging гэх мэт үг орсон файл байвал геологи / геотехник хийгдсэн (ногоон), үгүй бол хийгдээгүй (улаан); дээрх «хийгдсэн / хийгдээгүй» тоо дууссан цооногоор. Drive-д шинээр үүссэн цооногийн хавтас collar-д мөргүй байсан ч автоматаар бүртгэгдэнэ (12 цаг тутам). Цооног дээр дарж файлуудыг харна.</p></section>`;
}
function openHoleData(id){
  const h=D.collar.find(x=>x.id===id),r=DrillingData.row(h,D.dataInventory,D.shifts.filter(s=>s.hole===id).length,D.folderMap,logRegister),own=D.dataInventory?.[id]||{};
  const list=(key,title)=>{const entry=own[key],files=entry?.files||[];
    const items=key==='photos'?(entry?.count?`<p>${entry.count} зураг · ${esc(Object.entries(entry.formats||{}).map(([f,n])=>f+' '+n).join(' · '))}${entry.latest?' · сүүлд '+esc(entry.latest.slice(0,10)):''}</p>`:'<p class="sub">Зураг алга.</p>')
      :files.length?`<ul>${files.map(f=>`<li><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name)}</a>${f.modified?` <small>${esc(f.modified.slice(0,10))}</small>`:''}</li>`).join('')}</ul>${entry.count>files.length?`<p class="sub">… бусад ${entry.count-files.length} файл</p>`:''}`:'<p class="sub">Файл алга.</p>';
    return `<section class="data-files"><h3>${entry?.url?dataLink(entry.url,esc(title)+' ↗'):esc(title)}</h3>${items}</section>`;};
  $('#detail-body').innerHTML=`<h2 style="font-size:25px">${esc(id)}</h2><p>${esc(areaOf(h))} · <span class="badge ${readinessClass(r.readiness.state)}">${esc(r.readiness.label)}</span>${r.readiness.missing.length?' · Дутуу: '+r.readiness.missing.map(esc).join(', '):''}</p><p>Лог: <span class="badge ${loggedClass(r)}">${esc(r.logged.label)}</span>${r.logged.state==='unknown'?'':` · Геологи ${registerText(r.logged.geology)} · Геотехник ${registerText(r.logged.geotech)} · XRF ${registerText(r.logged.pxrf)}`}</p><p>Геологи (04 хавтас): ${logStatus(r.geology.done)} · Геотехник (07 хавтас): ${logStatus(r.geotech.done)}</p>${r.folderUrl?`<p>${dataLink(r.folderUrl,'Цооногийн Drive хавтас ↗')}</p>`:''}`
    +list('photos','05 · Кернийн зураг')+list('geological','04 · Геологийн лог')+list('geotechnical','07 · Геотехникийн лог')+list('pxrf','10 · pXRF')+list('surveys','03 · Хазайлтын хэмжилт');
  $('#detail').showModal();
}
function logTime(value){const d=new Date(value);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Ulaanbaatar',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(d);}
function logTable(){
  const labels={updated:'Шинэ өгөгдөл',unchanged:'Өөрчлөлтгүй',failed:'Алдаатай'},entries=[...dataLog].reverse();
  return `<section class="panel"><div class="panel-head"><h2>Data Log</h2><button class="button" id="refresh-log">Дахин унших ↻</button></div><p class="sub">Дата татсан түүх · Улаанбаатарын цагаар</p>${logError?`<p role="status">${esc(logError)}</p>`:''}<div class="table-scroll"><table><thead><tr><th>Татсан огноо / цаг</th><th>Эх үүсвэр</th><th>Төлөв</th><th>Файл</th><th>Цооног</th><th>Ээлж</th><th>Өрөмдсөн</th><th>Тайлбар</th></tr></thead><tbody>${entries.map(entry=>`<tr><td>${logTime(entry.startedAt)}</td><td>${entry.source==='drive'?'Google Drive':'Local CSV / XLSX'}</td><td><span class="badge ${entry.status==='failed'?'warn':''}">${labels[entry.status]||esc(entry.status)}</span></td><td>${fmt(entry.files,0)}</td><td>${fmt(entry.holes,0)}</td><td>${fmt(entry.shifts,0)}</td><td>${entry.meters==null?'—':fmt(entry.meters)+' м'}</td><td>${esc(entry.error||entry.note||'')}</td></tr>`).join('')||'<tr><td colspan="8" class="empty">Дата татсан түүх бүртгэгдээгүй.</td></tr>'}</tbody></table></div></section>`;
}
let auditMonth='';
const auditClass=status=>'audit-'+status.toLowerCase().replace(/_/g,'-');
const auditTitle=slot=>`${slot.date} ${slot.shift} · ${slot.rig} · ${AuditModel.LABELS[slot.status]}${slot.meters==null?' · тайлангүй':' · '+fmt(slot.meters)+' м'}${slot.issues.length?' — '+slot.issues.map(i=>i.text).join('; '):''}`;
function auditCell(slot){
  if(!slot)return '<td></td>';
  // A slot without a report shows ! (missing) or ? (unverified), never 0; * marks metres in conflict.
  const value=slot.meters==null?({MISSING_REPORT:'!',UNVERIFIED:'?'}[slot.status]||'·'):fmt(slot.meters,1)+(slot.status==='SOURCE_CONFLICT'?'*':'');
  return `<td><button class="audit-cell ${auditClass(slot.status)}" data-audit-slot="${esc(AuditModel.key(slot))}" title="${esc(auditTitle(slot))}" aria-label="${esc(auditTitle(slot))}">${esc(value)}</button></td>`;
}
function auditLinks(slot){
  const reports=[...slot.records.flatMap(r=>r.reports),...(slot.driveReports||[])];
  return [...reports.map(r=>dataLink(r.url,esc(r.name||'Тайлан')+' ↗')),slot.folderUrl?dataLink(slot.folderUrl,'02 фолдер ↗'):''].filter(Boolean).join('<br>')||'—';
}
function auditView(){
  const A=D.shiftAudit,head='<h2>QA/QC · Ээлжийн аудит</h2>';
  if(!A?.slots?.length)return `<section class="panel">${head}<div class="empty">Ээлжийн аудит Drive-ийн дараагийн sync-ээр тооцоологдоно.</div></section>`;
  const months=AuditModel.months(A);if(!months.includes(auditMonth))auditMonth=months.at(-1);
  const rig=$('#rig').value,rigs=A.rigs.filter(r=>!rig||r===rig),summary=AuditModel.summary(A,auditMonth,rig),sync=AuditModel.lastSync(dataLog),index=AuditModel.index(A);
  const list=AuditModel.slots(A,auditMonth,rig),dates=[...new Set(list.map(slot=>slot.date))].sort();
  const fresh=AuditModel.freshness(D.shifts,rigs).map(f=>`${f.rig}: ${f.date?f.date.slice(5)+' '+f.shift:'—'}`).join(' · ');
  const failed=sync.status==='failed';
  const cards=[['Нийт хүлээгдэж буй ээлж',fmt(summary.expected,0),`${summary.days} өдөр × 2 ээлж × ${rigs.length} өрөм`,''],
    ...AuditModel.STATUSES.map(status=>[AuditModel.LABELS[status],fmt(summary.counts[status],0),
      status==='MISSING_REPORT'&&summary.missingMeters?fmt(summary.missingMeters)+' м тайлангүй':summary.meters[status]?fmt(summary.meters[status])+' м':'',auditClass(status)]),
    ['Сүүлийн амжилттай sync',sync.success?logTime(sync.success):'—',failed?'Сүүлийн оролдлого алдаатай'+(sync.validation?': '+sync.validation:''):'Аудит '+A.through+' хүртэл',failed?'audit-source-conflict':''],
    ['Эх өгөгдлийн шинэлэг байдал',fresh||'—','Өрөм тус бүрийн сүүлийн тайлан','']];
  const grid=`<div class="table-scroll audit-scroll"><table class="audit-grid"><thead><tr><th>Өрөм · ээлж</th>${dates.map(d=>`<th>${d.slice(8)}</th>`).join('')}</tr></thead><tbody>`
    +rigs.flatMap(r=>['Өдөр','Шөнө'].map(shift=>`<tr><th>${esc(r)} · ${shift}</th>${dates.map(d=>auditCell(index.get(r+'|'+d+'|'+shift))).join('')}</tr>`)).join('')+'</tbody></table></div>';
  const legend='<div class="audit-legend">'+AuditModel.STATUSES.map(status=>`<span><i class="${auditClass(status)}"></i>${AuditModel.LABELS[status]}</span>`).join('')+'<span>! тайлан дутуу · ? баталгаажаагүй · * зөрчилтэй метр</span></div>';
  const order=s=>s.date+(s.shift==='Өдөр'?0:1)+s.rig;
  const rows=list.filter(slot=>slot.status!=='VERIFIED_DRILLING').sort((a,b)=>order(a).localeCompare(order(b)));
  const issues=`<div class="table-scroll"><table class="audit-issues"><thead><tr><th>Огноо · ээлж</th><th>Өрөм</th><th>Төлөв</th><th>Метр</th><th>Тайлбар</th><th>Эх сурвалж</th></tr></thead><tbody>${rows.map(slot=>`<tr><td><button class="hole-link" data-audit-slot="${esc(AuditModel.key(slot))}">${slot.date} ${slot.shift}</button></td><td>${esc(slot.rig)}</td><td><span class="badge ${auditClass(slot.status)}">${AuditModel.LABELS[slot.status]}</span></td><td>${slot.meters==null?'Тайлангүй':fmt(slot.meters)+' м'}</td><td>${slot.issues.map(i=>esc(i.text)).join('<br>')||'—'}</td><td>${auditLinks(slot)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">Энэ сард бүх ээлж баталгаажсан.</td></tr>'}</tbody></table></div>`;
  const inMonth=row=>String(row.date||'').startsWith(auditMonth+'-');
  const extra=[
    ['Өрөм нь тодорхойгүй мөр',(D.unassignedShifts||[]).filter(inMonth),r=>`${r.date} ${r.shift} · «${esc(r.rigText||'хоосон')}» · ${esc(r.hole)} ${fmt(r.from)}–${fmt(r.to)} м · ${esc(r.source)} · ${dataLink(r.url,esc(r.sheet)+' / '+esc(r.tab)+' мөр '+r.row+' ↗')}`],
    ['Validation-д тэнцээгүй мөр',(D.rejectedShifts||[]).filter(inMonth),r=>`${r.date||'—'} ${esc(r.shift)} · ${esc(r.rig)} · ${esc(r.hole)} · ${esc(r.reason)} · ${dataLink(r.url,esc(r.sheet)+' / '+esc(r.tab)+' мөр '+r.row+' ↗')}`],
    ['Эх хүснэгтүүдийн тоон зөрүү',(D.sourceConflicts||[]).filter(inMonth),r=>`${r.date} ${r.shift} · ${esc(r.rig)} · ${esc(r.hole)} · ${Object.entries(r.fields).map(([k,v])=>esc(k)+': '+v.map(x=>fmt(x)).join(' / ')).join(', ')} · авсан: ${esc(r.kept)}`],
    ['Ээлжид холбогдоогүй Drive тайлан',(D.unlinkedReports||[]).filter(r=>!r.date||inMonth(r)),r=>`${esc(r.hole)} · ${dataLink(r.url,esc(r.name)+' ↗')}${r.date?' · '+r.date+' '+esc(r.shift):''}`],
  ].map(([label,items,line])=>`<details class="audit-extra"><summary>${label}: ${items.length}</summary>${items.length?'<ul>'+items.map(item=>'<li>'+line(item)+'</li>').join('')+'</ul>':'<p class="sub">Алга.</p>'}</details>`).join('');
  return `<section class="panel"><div class="panel-head"><div>${head}<span class="sub">${rig?esc(rig):'Хоёр өрөм'} · ${auditMonth}</span></div><div class="chart-controls"><label class="chart-month">Сар <select id="audit-month" aria-label="Аудитын сар">${months.map(m=>`<option value="${m}"${m===auditMonth?' selected':''}>${m.slice(0,4)} оны ${Number(m.slice(5))}-р сар</option>`).join('')}</select></label></div></div>
    <div class="kpis audit-kpis">${cards.map(([label,value,note,cls])=>`<article class="kpi ${cls}"><div class="label">${label}</div><div class="value${/^[\d,.]+$/.test(value)?'':' audit-text'}">${esc(value)}</div>${note?`<div class="note">${esc(note)}</div>`:''}</article>`).join('')}</div>
    ${legend}${grid}</section>
    <section class="panel"><h2>Баталгаажаагүй, дутуу, зөрчилтэй ээлж</h2>${issues}${extra}
    <p class="sub data-note">Сарын өдөр бүр × өдөр/шөнө × өрөм нэг ээлж. Тайлангүй ээлжийг 0 м гэж үзэхгүй: цооногийн гүн тасарсан эсвэл өрөм дуусаагүй цооног дээр байсан бол «Тайлан дутуу», бусад тохиолдолд эх баримт ирэх хүртэл «Баталгаажаагүй». Ээлжийн мөр Drive-ийн эх тайлантай (зураг) холбогдсон бол баталгаажсан; гүний давхцал, буруу цооног, collar-ын гүнгийн зөрүү, хүснэгтүүдийн тоон зөрүү нь «Эх сурвалжийн зөрчил». Өрөм нүүсэн, зогссон ээлжийг эзэмшигч input/shift-audit.json-д нотолгоотой нь бүртгэвэл «Баталгаажсан, өрөмдөөгүй» болно.</p></section>`;
}
function openAuditSlot(key){
  const slot=AuditModel.index(D.shiftAudit).get(key);if(!slot)return;
  const records=slot.records.map(r=>`<li><strong>${esc(r.hole)}</strong> ${fmt(r.from)}–${fmt(r.to)} м (${fmt(r.meters)} м)${r.source?' · эх файл: '+esc(r.source):''}${r.sheet?' · '+dataLink(r.sheet.url,esc(r.sheet.name)+' / '+esc(r.sheet.tab)+' мөр '+r.sheet.row+' ↗'):''}${r.reports.length?' · '+r.reports.map(x=>dataLink(x.url,esc(x.name||'тайлан')+' ↗')).join(', '):' · <em>Drive тайлан холбогдоогүй</em>'}</li>`).join('');
  $('#detail-body').innerHTML=`<h2 style="font-size:23px">${esc(slot.rig)} · ${slot.date} ${slot.shift}</h2><p><span class="badge ${auditClass(slot.status)}">${AuditModel.LABELS[slot.status]}</span> · ${slot.meters==null?'Тайлангүй (0 м гэж тооцохгүй)':fmt(slot.meters)+' м'}</p>`
    +`<section class="data-files"><h3>Ээлжийн мөр</h3>${records?'<ul>'+records+'</ul>':'<p class="sub">Энэ ээлжийн мөр хүснэгтэд алга.</p>'}</section>`
    +`<section class="data-files"><h3>Шалгалт</h3>${slot.issues.length?'<ul>'+slot.issues.map(i=>'<li>'+esc(i.text)+'</li>').join('')+'</ul>':'<p class="sub">Зөрчилгүй.</p>'}</section>`
    +`<section class="data-files"><h3>Эх сурвалж</h3><p>${auditLinks(slot)}</p></section>`;
  $('#detail').showModal();
}
function sources(){return `<section class="panel"><h2>Өгөгдлийн эх сурвалж</h2><div class="source-list"><div class="source-row"><a class="source-link" href="${esc(D.collarUrl)}" target="_blank" rel="noopener">Collar бүртгэл ↗</a></div><div class="source-row"><a class="source-link" href="${esc(D.shiftUrl)}" target="_blank" rel="noopener">Ээлжийн тайлан ↗</a></div></div></section><section class="panel"><h2>Тооцоолол</h2><p>Ашиглалт = DT / нийт цаг. ROP = өрөмдсөн метр / DT. Цооногийн ахиц = сүүлийн ээлжийн гүн / төлөвлөсөн гүн.</p><p>Нормыг өрөм тус бүрээр 30 м/ээлж, 60 м/өдөр, 420 м/7 хоног гэж тооцно. Сарын норм = 60 м × тухайн сарын календарийн хоног. Дутуу тайлант 7 хоног, сарыг бүтэн календарийн үеийн нормтой харьцуулна.</p></section>`;}
let mappingMap=null,mappingMarkers=new Map();
function renderMapping(){
  const selected=holes(),points=DrillingMap.points(selected),known=new Set(points.map(point=>point.id));
  const missing=selected.filter(hole=>!known.has(hole.id));
  return `<section class="panel mapping-panel"><div class="panel-head"><div><h2>Mapping</h2><span class="sub">Газрын зурагт ${points.length} · Координатгүй ${missing.length}</span></div><button class="button" id="map-fit">Бүгдийг багтаах</button></div>
    <div class="mapping-layout"><div id="mapping-map" aria-label="Цооногуудын газрын зураг"></div><div class="mapping-list"><h3>Координаттай цооногууд</h3>
      ${points.map(point=>`<button class="mapping-hole" data-map-hole="${esc(point.id)}"><span class="map-dot" style="background:${areaColor(areaOf(point.hole))}"></span><span><strong>${esc(point.id)}</strong><small>${esc(areaOf(point.hole))} · ${status(point.hole)[0]}</small></span></button>`).join('')||'<p class="sub">Шүүлтүүрт тохирох координаттай цооног алга.</p>'}
      ${missing.length?`<h3>Координатгүй</h3>${missing.map(hole=>`<button class="mapping-hole missing" data-hole="${esc(hole.id)}"><span><strong>${esc(hole.id)}</strong><small>E / N бүртгэгдээгүй</small></span></button>`).join('')}`:''}
    </div></div><div class="map-legend">${areaList(selected).map(area=>`<span><i class="map-dot" style="background:${areaColor(area)}"></i>${esc(area)}</span>`).join('')}</div><p id="map-tile-status" class="sub" role="status" hidden>Суурь зургийг ачаалж чадсангүй. Цооногийн цэгүүд харагдаж байна.</p></section>`;
}
function fitMapping(){
  if(!mappingMap)return;
  const markers=[...mappingMarkers.values()];
  if(markers.length)mappingMap.fitBounds(L.featureGroup(markers).getBounds(),{padding:[48,48],maxZoom:17});
}
function initMapping(){
  const points=DrillingMap.points(holes());
  mappingMap=L.map('mapping-map',{zoomControl:false,scrollWheelZoom:true}).setView([49.18,113.55],12);
  L.control.zoom({zoomInTitle:'Ойртуулах',zoomOutTitle:'Холдуулах'}).addTo(mappingMap);
  const streets=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
  const satellite=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community'});
  for(const layer of [streets,satellite]){layer.on('tileerror',()=>{const notice=$('#map-tile-status');if(notice)notice.hidden=false;});layer.on('load',()=>{const notice=$('#map-tile-status');if(notice)notice.hidden=true;});}
  satellite.addTo(mappingMap);
  L.control.layers({'Газрын зураг':streets,'Сансрын зураг':satellite},null,{collapsed:false}).addTo(mappingMap);
  L.control.scale({imperial:false,position:'bottomleft'}).addTo(mappingMap);
  mappingMarkers=new Map();
  for(const point of points){
    const h=point.hole,color=areaColor(areaOf(h));
    const marker=L.circleMarker([point.lat,point.lng],{radius:8,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).addTo(mappingMap);
    marker.bindTooltip(esc(h.id),{permanent:true,direction:h.id==='DTDH2602'?'right':'top',offset:[0,-8],className:'map-hole-label'});
    marker.bindPopup(`<div class="map-popup"><h3>${esc(h.id)}</h3><p>${esc(areaOf(h))} · ${status(h)[0]}</p><dl><dt>Ээлжийн гүн</dt><dd>${fmt(depth(h.id))} м</dd><dt>Төлөвлөсөн</dt><dd>${fmt(h.plan)} м</dd><dt>E / N</dt><dd>${fmt(h.e,3)} / ${fmt(h.n,3)}</dd><dt>Өргөрөг / уртраг</dt><dd>${fmt(point.lat,6)} / ${fmt(point.lng,6)}</dd></dl><button class="button" data-popup-hole="${esc(h.id)}">Цооногийн мэдээлэл</button></div>`);
    marker.on('popupopen',event=>{event.popup.getElement().querySelector('[data-popup-hole]')?.addEventListener('click',()=>openHole(h.id));});
    const element=marker.getElement();if(element){element.setAttribute('role','button');element.setAttribute('tabindex','0');element.setAttribute('aria-label',h.id);element.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();marker.openPopup();}});}
    mappingMarkers.set(h.id,marker);
  }
  fitMapping();
  $('#map-fit').addEventListener('click',fitMapping);
}
function focusMappingHole(id){const marker=mappingMarkers.get(id);if(marker&&mappingMap){mappingMap.setView(marker.getLatLng(),Math.max(mappingMap.getZoom(),16));marker.openPopup();}}
function render(){
  hideBarTooltip();
  if(mappingMap){mappingMap.remove();mappingMap=null;mappingMarkers.clear();}
  if(!D)return;let content=['financial','mapping','drilling-data','audit'].includes(tab)?'':kpis();
  if(tab==='financial')content+=renderFinancialTab();
  if(tab==='mapping')content+=renderMapping();
  if(tab==='drilling-data')content+=drillingData();
  if(tab==='audit')content+=auditView();
  if(tab==='overview')content+='<div class="grid"><section class="panel" id="chart-panel">'+chart()+'</section><section class="panel"><h2>Өрмийн гүйцэтгэл · '+overviewPeriodLabel()+'</h2>'+rigs()+'</section></div>';
  if(tab==='holes')content+='<section class="panel"><div class="panel-head"><h2>Цооногийн ахиц</h2><input class="search" aria-label="Цооног хайх" placeholder="Цооног хайх…" value="'+esc(query)+'"></div><div id="table">'+holeTable()+'</div></section>';
  if(tab==='shifts')content+='<section class="panel"><div class="panel-head"><h2>Ээлжийн бүртгэл</h2><input class="search" aria-label="Ээлж хайх" placeholder="Цооног, нэр, огноо…" value="'+esc(query)+'"></div><div id="table">'+shiftTable()+'</div></section>';
  if(tab==='rop'||tab==='utilization')content+=performanceTable();if(tab==='sources')content+=sources();if(tab==='data-log')content+=logTable();
  $('#app').innerHTML=content;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  if(tab==='mapping')initMapping();
  $('.search')?.addEventListener('input',e=>{query=e.target.value;$('#table').innerHTML=tab==='holes'?holeTable():tab==='drilling-data'?dataTable():shiftTable();});
}
function openHole(id){const h=D.collar.find(x=>x.id===id),folder=D.folderMap?.[id],state=status(h);$('#detail-body').innerHTML=`<h2 style="font-size:25px">${esc(h.id)}</h2><p>${SITE} · ${esc(areaOf(h))} · <span class="badge ${state[1]}">${state[0]}</span></p><div class="detail-grid">${[['Төлөвлөсөн гүн',fmt(h.plan)+' м'],['Ээлжийн сүүлийн гүн',fmt(depth(id))+' м'],['Collar эцсийн гүн',fmt(h.collarDepth)+' м'],['Эхэлсэн / дууссан',`${h.start||'—'} / ${h.finish||'—'}`],['E / N / Z',`${fmt(h.e,3)} / ${fmt(h.n,3)} / ${fmt(h.z,3)}`],['Азимут / хазайлт',`${fmt(h.az)}° / ${fmt(h.dip)}°`],['Керний гарц',h.recovery==null?'—':fmt(h.recovery)+'%'],['Керний хайрцаг',fmt(h.boxes,0)]].map(([label,value])=>`<div><small>${label}</small><strong>${esc(value)}</strong></div>`).join('')}</div><h3>Эх баримтууд</h3><div class="folder-links">${folder?folder.folders.map(f=>`<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name)} ↗</a>`).join(''):'Энэ цооногийн хавтас олдоогүй.'}</div>`;$('#detail').showModal();}
function savedTheme(){try{const theme=localStorage.getItem('drilling-theme');return theme==='light'||theme==='dark'?theme:null;}catch{return null;}}
function setTheme(theme,save){document.documentElement.dataset.theme=theme;$('#dark-theme').media=theme==='dark'?'all':'not all';document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.themeChoice===theme));if(save)try{localStorage.setItem('drilling-theme',theme);}catch{}}
document.addEventListener('click',e=>{
  const themeChoice=e.target.closest('[data-theme-choice]');if(themeChoice)setTheme(themeChoice.dataset.themeChoice,true);
  const mapHole=e.target.closest('[data-map-hole]');if(mapHole)focusMappingHole(mapHole.dataset.mapHole);
  const bar=e.target.closest('g[data-bar-index]');if(bar)openBarReports(chartBars[Number(bar.dataset.barIndex)]);
  const financialPeriod=e.target.closest('[data-financial-grain]');if(financialPeriod){financialGrain=financialPeriod.dataset.financialGrain;render();}
  const target=e.target.closest('[data-tab],[data-go]');if(target){e.preventDefault();tab=target.dataset.tab||target.dataset.go;query='';render();}
  const period=e.target.closest('[data-grain]');if(period){grain=period.dataset.grain;$('#chart-panel').innerHTML=chart();}
  const depthButton=e.target.closest('[data-depth-hole]');if(depthButton){selectedHole=selectedHole===depthButton.dataset.depthHole?null:depthButton.dataset.depthHole;$('#table').innerHTML=holeTable();}
  const hole=e.target.closest('[data-hole]');if(hole)openHole(hole.dataset.hole);if(e.target.closest('#refresh-log'))refreshLog();
  const dataHole=e.target.closest('[data-data-hole]');if(dataHole)openHoleData(dataHole.dataset.dataHole);
  const auditSlot=e.target.closest('[data-audit-slot]');if(auditSlot)openAuditSlot(auditSlot.dataset.auditSlot);
});
document.addEventListener('change',event=>{if(event.target.id==='chart-month'){chartMonth=event.target.value;render();}if(event.target.id==='financial-month'){financialMonth=event.target.value;render();}if(event.target.id==='audit-month'){auditMonth=event.target.value;render();}});
for(const selector of ['#site','#area','#rig'])$(selector).addEventListener('change',()=>{selectedHole=null;render();});$('.close').addEventListener('click',()=>$('#detail').close());
$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('#export').addEventListener('click',()=>{
  const records=tab==='data-log'?dataLog:tab==='audit'?AuditModel.slots(D.shiftAudit,auditMonth,$('#rig').value).map(s=>({date:s.date,shift:s.shift,rig:s.rig,status:s.status,statusLabel:AuditModel.LABELS[s.status],
    meters:s.meters,holes:s.records.map(r=>r.hole).join(' '),issues:s.issues.map(i=>i.text).join('; '),reports:[...s.records.flatMap(r=>r.reports),...(s.driveReports||[])],folder:s.folderUrl})):tab==='drilling-data'?(D.dataInventory?dataRows():[]).map(r=>({hole:r.id,area:areaOf(r.hole),status:status(r.hole)[0],collarDepth:r.collar.depth,coordinates:r.collar.coordinates,elevation:r.collar.elevation,
    photos:r.photos.count,photoFormats:Object.entries(r.photos.formats).map(([f,n])=>f+' '+n).join(' '),boxes:r.photos.boxes,geologicalLog:r.geology.state,geologicalFile:r.geology.file?.name||'',geologicalDone:r.geology.done?'Хийгдсэн':'Хийгдээгүй',geologicalFiles:r.geology.files.length,
    geotechnicalLog:r.geotech.state,geotechnicalFile:r.geotech.file?.name||'',geotechnicalDone:r.geotech.done?'Хийгдсэн':'Хийгдээгүй',pxrfFiles:r.pxrf.count,surveyFiles:r.surveys.count,readiness:r.readiness.label,missing:r.readiness.missing.join('; '),
    logged:r.logged.label,geologyLog:r.logged.geology,geotechLog:r.logged.geotech,pxrfLog:r.logged.pxrf})):tab==='shifts'?shifts().filter(x=>(x.hole+' '+x.driller+' '+x.date).toLowerCase().includes(query.toLowerCase())):holes().filter(x=>x.id.toLowerCase().includes(query.toLowerCase())).map(h=>({...h,site:SITE,shiftDepth:depth(h.id),status:status(h)[0]}));
  if(!records.length){alert('Татах бүртгэл байхгүй.');return;}
  const keys=[...new Set(records.flatMap(r=>Object.keys(r)))],cell=value=>'"'+String(value??'').replace(/"/g,'""')+'"',csv='\uFEFF'+[keys,...records.map(r=>keys.map(k=>k==='reports'?(r[k]||[]).map(report=>report.url).join(' | '):r[k]))].map(r=>r.map(cell).join(',')).join('\r\n'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');
  a.href=url;a.download=`drilling-${tab}-${D.asOf}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function refreshLog(){try{const r=await fetch('data-log.json',{cache:'no-store'});if(!r.ok)throw Error();const log=await r.json();dataLog=log.entries||[];logError='';}catch{logError='Дата татсан түүхийг ачаалж чадсангүй.';}if(D&&(tab==='data-log'||tab==='audit'))render();}
async function refreshRegister(){try{const r=await fetch('log-register.json',{cache:'no-store'});if(!r.ok)return false;const holes=(await r.json()).holes||{};const changed=JSON.stringify(holes)!==JSON.stringify(logRegister);logRegister=holes;return changed;}catch{return false;}}
async function refreshData(){try{const registerChanged=await refreshRegister();const r=await fetch('data.json',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const data=await r.json(),changed=registerChanged||JSON.stringify(data)!==JSON.stringify(D);D=data;areaOptions();$('.period strong').textContent=D.period;$('#load-error').hidden=true;if(changed)render();}catch(e){$('#load-error').hidden=false;$('#load-error').textContent=D?'Өгөгдөл ачаалж чадсангүй. Өмнөх өгөгдлийг харуулж байна.':'Өгөгдөл ачаалж чадсангүй.';}}
setTheme(document.documentElement.dataset.theme);matchMedia('(prefers-color-scheme: light)').addEventListener('change',e=>{if(!savedTheme())setTheme(e.matches?'light':'dark');});
refreshData();refreshLog();setInterval(()=>{refreshData();refreshLog();},60000);
