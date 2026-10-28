'use strict';
let D,tab='overview',query='',grain='day',dataLog=[],logError='',selectedHole=null,chartBars=[];
const $=selector=>document.querySelector(selector);
const fmt=(n,d=1)=>n==null?'—':Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sum=(rows,key)=>rows.reduce((total,row)=>total+row[key],0),SITE='Нэргүй Өндөр';
function knownHours(rows,key){const known=rows.filter(row=>Number.isFinite(row[key]));return known.length?(known.length<rows.length?'≥ ':'')+fmt(sum(known,key)):'—';}
function areaOf(h){const area=(h.targetArea||'').toLocaleLowerCase();if(area==='дорнын төмөр'||(!area&&h.id.startsWith('DTDH')))return 'Дорнын Төмөр';if(area==='замт хөндий'||(!area&&h.id.startsWith('ZHDH')))return 'Замт Хөндий';return h.targetArea||'—';}
function holes(){return D.collar.filter(h=>(h.site||SITE)===$('#site').value&&(!$('#area').value||areaOf(h)===$('#area').value)&&(!$('#rig').value||D.shifts.some(s=>s.hole===h.id&&s.rig===$('#rig').value)));}
function shifts(){const ids=new Set(holes().map(h=>h.id));return D.shifts.filter(s=>ids.has(s.hole)&&(!$('#rig').value||s.rig===$('#rig').value));}
function depth(id){const rows=D.shifts.filter(s=>s.hole===id);return rows.length?Math.max(...rows.map(s=>s.to)):null;}
function status(h){if(h.finish)return ['Дууссан',''];if(D.shifts.some(s=>s.hole===h.id))return ['Өрөмдөж байна','active'];return ['Төлөвлөсөн','planned'];}
let financialGrain='shift';
const financialGrainLabel=()=>({shift:'Ээлжийн',day:'Өдрийн',week:'7 хоногийн',month:'Сарын'}[financialGrain]);
const currency=(value,digits=0)=>value==null||Number.isNaN(Number(value))?'—':`₮ ${Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`;
function financialRows(grain=financialGrain){
  if(!D||!D.shifts?.length)return [];
  const financeAvailable=Boolean(D.finance?.period&&Array.isArray(D.finance.rigShifts));
  const rigs=$('#rig').value?[$('#rig').value]:['C-1800','CSD-1300'];
  const operationRows=shifts().filter(row=>!financeAvailable||row.date.startsWith(D.finance.period));
  const sourceRows=DrillingCosts.records(operationRows,rigs,D.finance?.mud,D.finance?.fuel,D.finance?.diamond);
  const groupMap=new Map();
  const periodStart=date=>{
    const day=new Date(`${date}T00:00:00Z`);
    if(grain==='week')day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    if(grain==='month')day.setUTCDate(1);
    return day.toISOString().slice(0,10);
  };
  for(const row of sourceRows){
    const shiftKey=`${row.date}|${row.rig}|${row.shift}`;
    const period=grain==='shift'?row.date+'|'+row.shift:grain==='day'?row.date:periodStart(row.date);
    const periodDate=grain==='shift'?row.date:period.split('|')[0];
    const entry=groupMap.get(period)||{date:periodDate,endDate:periodDate,shiftOrder:row.shift==='Өдөр'?0:1,drilledMeters:0,fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,rigs:new Set(),shifts:new Set(),shiftLabels:new Set(),holes:new Set()};
    const meters=Number(row.meters||0);
    entry.drilledMeters+=meters;
    if(row.recorded){entry.waterUsageRecords++;if(row.waterUsageM3==null)entry.waterUsageKnown=false;else entry.waterUsageM3+=Number(row.waterUsageM3);}
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
    for(const row of D.finance.rigShifts){
      if($('#rig').value&&row.rig!==$('#rig').value)continue;
      const shiftKey=`${row.date}|${row.rig}|${row.shift}`;
      const period=grain==='shift'?`${row.date}|${row.shift}`:grain==='day'?row.date:periodStart(row.date);
      const entry=groupMap.get(period)||{
        date:grain==='shift'?row.date:period.split('|')[0],endDate:period.split('|')[0],
        shiftOrder:row.shift==='Өдөр'?0:1,drilledMeters:0,fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,
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
    const totalCost=financeAvailable?entry.fuelCost+entry.mudCost+entry.diamondCost+entry.laborCost+entry.foodCost+entry.bonusCost+entry.incentiveCost:null;
    const dailyCostPerMeter=totalCost!=null&&entry.drilledMeters>0?totalCost/entry.drilledMeters:null;
    if(totalCost!=null)runningCost += totalCost;
    runningMeters += entry.drilledMeters;
    rows.push({
      date:entry.date,
      period:date,
      periodEnd:entry.endDate,
      drilledMeters:entry.drilledMeters,
      fuelCost:entry.fuelCost,
      mudCost:entry.mudCost,diamondCost:entry.diamondCost,
      fuelUsageL:entry.fuelUsageL,fuelRecords:entry.fuelRecords,mudUsageKg:entry.mudUsageKg,mudUsageBags:entry.mudUsageBags,
      waterUsageM3:entry.waterUsageKnown&&entry.waterUsageRecords>0?entry.waterUsageM3:null,
      laborCost:financeAvailable?entry.laborCost:null,
      foodCost:financeAvailable?entry.foodCost:null,
      bonusCost:financeAvailable?entry.bonusCost:null,
      incentiveCost:financeAvailable?entry.incentiveCost:null,
      totalCost,
      dailyCostPerMeter,
      cumulativeCostPerMeter:financeAvailable&&runningMeters>0?runningCost/runningMeters:null,
      completion:financeAvailable?'AGGREGATED':'MISSING',
      note:financeAvailable?'':'Цалин, хоолны эх сурвалж синк хийгдээгүй',
      rigs:[...entry.rigs].join(', '),
      shifts:entry.shifts.size,
      shiftLabel:[...entry.shiftLabels].join(', '),
      holes:[...entry.holes].join(', '),
      allCosts: [{key:'fuelCost',label:'Түлш',value:entry.fuelCost},{key:'mudCost',label:'Өрөмдлөгийн шавар',value:entry.mudCost},{key:'diamondCost',label:'Алмазан хошуу + reaming shell (тооцоот)',value:entry.diamondCost},{key:'laborCost',label:'Цалин',value:financeAvailable?entry.laborCost:null},{key:'foodCost',label:'Хоол',value:financeAvailable?entry.foodCost:null},{key:'bonusCost',label:'Метрийн бонус',value:financeAvailable?entry.bonusCost:null},{key:'incentiveCost',label:'Урамшуулал',value:financeAvailable?entry.incentiveCost:null}],
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
  const financeAvailable=Boolean(D.finance?.period&&Array.isArray(D.finance.rigShifts));
  const rigs=$('#rig').value?[$('#rig').value]:['C-1800','CSD-1300'];
  const operationRows=shifts().filter(row=>!financeAvailable||row.date.startsWith(D.finance.period));
  const sourceRows=DrillingCosts.records(operationRows,rigs,D.finance?.mud,D.finance?.fuel,D.finance?.diamond),groups=new Map();
  const periodStart=date=>{
    const day=new Date(`${date}T00:00:00Z`);
    if(grain==='week')day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    if(grain==='month')day.setUTCDate(1);
    return day.toISOString().slice(0,10);
  };
  for(const row of sourceRows){
    const start=grain==='shift'?row.date:grain==='day'?row.date:periodStart(row.date);
    const shiftOrder=row.shift==='Өдөр'?0:1;
    const key=grain==='shift'?`${start}|${shiftOrder}`:start;
    const groupKey=`${key}|${row.rig}`;
    const meters=Number(row.meters||0),entry=groups.get(groupKey)||{
      key,date:start,shiftOrder,shift:row.shift,rig:row.rig,meters:0,
      fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,
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
    for(const row of D.finance.rigShifts){
      if($('#rig').value&&row.rig!==$('#rig').value)continue;
      const start=grain==='shift'?row.date:grain==='day'?row.date:periodStart(row.date);
      const shiftOrder=row.shift==='Өдөр'?0:1;
      const key=grain==='shift'?`${start}|${shiftOrder}`:start;
      const groupKey=`${key}|${row.rig}`;
      const entry=groups.get(groupKey)||{
        key,date:start,shiftOrder,shift:row.shift,rig:row.rig,meters:0,
        fuelCost:0,mudCost:0,diamondCost:0,fuelUsageL:0,fuelRecords:0,mudUsageKg:0,mudUsageBags:0,waterUsageM3:0,waterUsageKnown:true,waterUsageRecords:0,laborCost:0,foodCost:0,bonusCost:0,incentiveCost:0,holes:new Set(),
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
      if(financeAvailable)runningCost+=cost;
      runningMeters+=row.meters;
      return {
        key:period.key,date:row.date,shift:row.shift,rig,value:financeAvailable&&row.meters?cost/row.meters:null,
        cumulative:financeAvailable&&runningMeters?runningCost/runningMeters:null,meters:row.meters,
        fuelCost:row.fuelCost,mudCost:row.mudCost,diamondCost:row.diamondCost,fuelUsageL:row.fuelUsageL,fuelRecords:row.fuelRecords,mudUsageKg:row.mudUsageKg,mudUsageBags:row.mudUsageBags,
        laborCost:row.laborCost,foodCost:row.foodCost,bonusCost:row.bonusCost,incentiveCost:row.incentiveCost,holes:[...row.holes].join(', '),
      };
    });
    return {rig,points};
  });
}
function renderFinancialChart(rows){
  if(!D.finance?.period)return '<div class="empty">Цалин, хоолны эх сурвалж синк хийгдээгүй байна.</div>';
  if(!rows.length)return '<div class="empty">Санхүүгийн өгөгдөл байхгүй.</div>';
  const series=financialRigSeries(),width=1200,height=350,left=82,right=30,top=28,bottom=58,plotHeight=height-top-bottom;
  const allPoints=series.flatMap(item=>item.points),maxValue=Math.max(...allPoints.map(point=>point.value||0),1);
  const xAt=(index,total)=>left+(index/(Math.max(total-1,1)))*(width-left-right);
  const yAt=(value)=>top+plotHeight-((value/maxValue)*plotHeight);
  const colors={'C-1800':'#dc8a3b','CSD-1300':'#128875'};
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
  const rows=financialRows(financialGrain);
  if(!rows.length)return '<div class="empty">Шүүлтүүрт тохирох санхүүгийн өгөгдөл байхгүй.</div>';
  const completed=rows.filter(row=>row.drilledMeters>0&&Number.isFinite(row.dailyCostPerMeter));
  const latest=completed.at(-1),previous=completed.at(-2),last=rows.at(-1),prior=rows.at(-2);
  const dailyValue=latest?.dailyCostPerMeter??null,previousValue=previous?.dailyCostPerMeter??null;
  const change=dailyValue!=null&&previousValue>0?(dailyValue-previousValue)/previousValue*100:null;
  const periodLabel=row=>row?row.date+(financialGrain==='shift'?' · '+row.shiftLabel:''):'';
  const tone=(current,before)=>current==null||before==null||current===before?'flat':current>before?'up':'down';
  const costTone=tone(dailyValue,previousValue);
  const comparisonNote=change!=null?`${periodLabel(latest)}: ${currency(dailyValue)} /м ↔ ${periodLabel(previous)}: ${currency(previousValue)} /м`:'Өмнөх хугацааны ₮/м бүртгэл алга';
  const periodNote=latest?periodLabel(latest)+(change==null?'':` · ${change>0?'▲':change<0?'▼':'•'} ${fmt(Math.abs(change),1)}%`):'Өрөмдсөн метрийн бүртгэл алга';
  const totalMeters=rows.reduce((sum,r)=>sum+r.drilledMeters,0);
  const totalCost=rows.some(row=>row.totalCost==null)?null:rows.reduce((sum,r)=>sum+r.totalCost,0);
  const totalFuel=rows.reduce((sum,r)=>sum+r.fuelCost,0);
  const totalFuelUsage=rows.reduce((sum,r)=>sum+r.fuelUsageL,0),totalMudUsage=rows.reduce((sum,r)=>sum+r.mudUsageKg,0);
  const priorRows=rows.slice(0,-1),priorMeters=priorRows.reduce((total,row)=>total+row.drilledMeters,0);
  const fuelUnit=totalMeters?totalFuel/totalMeters:null,priorFuelUnit=priorMeters?priorRows.reduce((total,row)=>total+row.fuelCost,0)/priorMeters:null;
  const cumulativeNote=prior?.cumulativeCostPerMeter!=null?`${periodLabel(last)}: ${currency(last.cumulativeCostPerMeter)} /м ↔ ${periodLabel(prior)}: ${currency(prior.cumulativeCostPerMeter)} /м`:'';
  const fuelNote=priorFuelUnit!=null?`${periodLabel(last)}: ${currency(fuelUnit)} /м ↔ ${periodLabel(prior)}: ${currency(priorFuelUnit)} /м`:'';
  const kpis=[
    {label:`Сүүлийн ${financialGrainLabel().toLocaleLowerCase()} зардал (₮/м)`,value:dailyValue==null?'—':currency(dailyValue,0),note:periodNote,tone:costTone},
    {label:'Хуримтлагдсан зардал (₮/м)',value:currency(last.cumulativeCostPerMeter,0),tone:tone(last.cumulativeCostPerMeter,prior?.cumulativeCostPerMeter??null),note:cumulativeNote},
    {label:`Өмнөх ${financialGrain==='shift'?'ээлжтэй':financialGrain==='day'?'өдөртэй':financialGrain==='week'?'7 хоногтой':'сартай'} харьцуулсан өөрчлөлт (%)`,value:change==null?'—':`${fmt(change,1)}%`,note:comparisonNote,tone:costTone},
    {label:'Нийт зардал (₮)',value:currency(totalCost,0)},
    {label:'Нийт өрөмдсөн метр (м)',value:fmt(totalMeters,1)},
    {label:'Түлшний зардал (₮/м)',value:currency(fuelUnit,0),tone:tone(fuelUnit,priorFuelUnit),note:fuelNote},
    {label:'Нийт түлшний олголт (л)',value:fmt(totalFuelUsage,2)},
    {label:'Нийт шаврын хэрэглээ (кг)',value:fmt(totalMudUsage,2)},
  ];
  const categories=[['fuelCost','Түлш'],['mudCost','Өрөмдлөгийн шавар'],['diamondCost','Алмазан хошуу + reaming shell (тооцоот)'],['laborCost','Үндсэн цалин'],['foodCost','Хоолны зардал'],['bonusCost','Метрийн бонус'],['incentiveCost','Урамшуулал']];
  const breakdown=categories.map(([key,label])=>({key,label,current:rows.some(row=>row[key]==null)?null:rows.reduce((total,row)=>total+row[key],0)}));
  const controls=[['shift','Ээлж'],['day','Өдөр'],['week','7 хоног'],['month','Сар']].map(([value,label])=>`<button class="chart-period-button ${financialGrain===value?'active':''}" data-financial-grain="${value}" aria-pressed="${financialGrain===value}">${label}</button>`).join('');
  const breakdownMax=Math.max(...breakdown.map(item=>item.current||0),1);
  const costRows=breakdown.map(item=>{
    if(item.current==null){
      const status='Эх сурвалж синк хийгдээгүй';
      return `<div class="cost-row"><div class="cost-label"><span>${item.label}</span><strong>${status}</strong></div></div>`;
    }
    const usage=item.key==='fuelCost'?`<div class="sub cost-usage">Өрөмд олгосон: ${fmt(totalFuelUsage,2)} л</div>`:item.key==='mudCost'?`<div class="sub cost-usage">Хуваарилсан хэрэглээ: ${fmt(totalMudUsage,2)} кг · ${fmt(rows.reduce((total,row)=>total+row.mudUsageBags,0),2)} шуудай (${fmt(D.finance?.mud?.bagKg||25,0)} кг)</div>`:'';
    return `<div class="cost-row"><div class="cost-label"><span>${item.label}</span><strong>${currency(item.current,0)}</strong></div>${usage}<div class="cost-bar"><span style="width:${((item.current||0)/breakdownMax)*100}%"></span></div></div>`;
  }).join('');
  return `<div class="financial-wrap">
    <section class="panel financial-panel">
      <div class="panel-head">
        <div><h2>Өрөм тус бүрийн 1 метрийн зардал (₮/м)</h2><span class="sub">C-1800 болон CSD-1300</span></div>
        <div class="chart-periods" role="group" aria-label="Санхүүгийн графикийн хугацаа">${controls}</div>
      </div>
      ${renderFinancialChart(rows)}
    </section>
    <div class="kpis">${kpis.map(item=>`<article class="kpi${item.tone?` financial-trend ${item.tone}`:''}"><div class="label">${item.label}</div><div class="value">${item.value}</div>${item.note?`<div class="note">${esc(item.note)}</div>`:''}</article>`).join('')}</div>
    <section class="panel">
      <h2>Зардлын задаргаа</h2>
      <div class="cost-breakdown">${costRows}</div>
      ${D.finance?.diamond?`<p class="sub">Алмазан хошуу + reaming shell: ${currency(D.finance.diamond.ratePerMeter,0)}/м × бүртгэлтэй метр. ${fmt(D.finance.diamond.plannedMeters,0)} м төлөвлөгөөний ${currency(D.finance.diamond.totalBudget,0)} төсвийг хуваарилсан тооцоо; бодит солилт/элэгдэл биш. <a href="${esc(D.finance.diamond.sourceUrl)}" target="_blank" rel="noopener noreferrer">Эх тооцоо</a></p>`:''}
    </section>
    <section class="panel">
      <h2>Дэлгэрэнгүй бүртгэл</h2>
      <div class="table-scroll financial-details-scroll">
        <table class="financial-details-table">
          <thead><tr><th>Хугацаа</th><th>Өрөм</th><th>Ээлж</th><th>Цооног</th><th>Метр</th><th>Түлш (л, олголт)</th><th>Шавар (кг, хуваарилсан)</th><th>Усны хэрэглээ</th><th>Алмазан хошуу ₮ (тооцоот)</th><th>Дүн ₮ </th><th>₮/м </th></tr></thead>
          <tbody>${[...rows].reverse().map(r=>`<tr>
            <td data-label="Хугацаа">${r.date}</td>
            <td data-label="Өрөм">${esc(r.rigs||'—')}</td>
            <td data-label="Ээлж">${esc(r.shiftLabel||'—')}</td>
            <td data-label="Цооног">${esc(r.holes||'—')}</td>
            <td data-label="Метр">${fmt(r.drilledMeters,1)} м</td>
            <td data-label="Түлш (л, олголт)">${r.fuelRecords?fmt(r.fuelUsageL,2):'—'}</td>
            <td data-label="Шавар (кг, хуваарилсан)">${fmt(r.mudUsageKg,2)}</td>
            <td data-label="Усны хэрэглээ">${r.waterUsageM3==null?'—':fmt(r.waterUsageM3,2)+' м³'}</td>
            <td data-label="Алмазан хошуу ₮ (тооцоот)">${currency(r.diamondCost,0)}</td>
            <td data-label="Нийт зардал">${currency(r.totalCost,0)}</td>
            <td data-label="₮/м">${r.dailyCostPerMeter==null?'N/A':currency(r.dailyCostPerMeter,0)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </section>
  </div>`;
}
function kpis(){
  const rows=shifts(),dt=sum(rows,'dt'),hours=sum(rows,'hours');
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
  const rows=shifts(),groups=DrillingChart.aggregate(rows,grain),rigs=$('#rig').value?[$('#rig').value]:['C-1800','CSD-1300'];
  const controls=`<div class="chart-periods" role="group" aria-label="Графикийн хугацаа">${[['shift','Ээлж'],['day','Өдөр'],['week','7 хоног'],['month','Сар']].map(([value,label])=>`<button data-grain="${value}" aria-pressed="${grain===value}">${label}</button>`).join('')}</div>`;
  const targetLabels={shift:'30 м / ээлж / өрөм',day:'60 м / өдөр / өрөм',week:'420 м / 7 хоног / өрөм',month:'60 м × сарын хоног / өрөм'};
  let html=`<div class="panel-head"><h2>${DrillingChart.title(groups)}</h2>${controls}</div>`;
  if(!groups.length)return html+'<div class="empty">Ээлжийн өгөгдөл байхгүй.</div>';
  const W=Math.max(600,groups.length*(grain==='shift'?44:48)+90),H=280,left=45,right=18,top=30,bottom=grain==='shift'?58:40,plotH=H-top-bottom,step=(W-left-right)/groups.length;
  const high=Math.max(...groups.map(g=>Math.max(g.target,...Object.values(g.amounts)))),unit=high>600?300:high>180?60:30,max=Math.ceil(high*1.12/unit)*unit;
  const y=value=>top+plotH-value/max*plotH;
  let svg=`<svg viewBox="0 0 ${W} ${H}" style="min-width:${W}px" role="group" aria-label="Гүйцэтгэл, ${targetLabels[grain]}"><text x="6" y="14">м</text>`;
  const tick=Math.max(unit,Math.ceil(max/5/unit)*unit);
  for(let n=0;n<=max;n+=tick)svg+=`<line x1="${left}" x2="${W-right}" y1="${y(n)}" y2="${y(n)}" stroke="#e8eded"/><text x="${left-8}" y="${y(n)+4}" text-anchor="end">${fmt(n,0)}</text>`;
  const barWidth=Math.min(17,(step-14)/rigs.length),colors={'C-1800':'#dc8a3b','CSD-1300':'#128875'};
  groups.forEach((group,i)=>{
    const x=left+(i+0.5)*step;
    rigs.forEach((rig,j)=>{const value=group.amounts[rig]||0,recorded=group.counts[rig]||0,bx=x+(j-rigs.length/2)*barWidth;
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
function rigs(){return ['C-1800','CSD-1300'].filter(rig=>!$('#rig').value||$('#rig').value===rig).map(rig=>{const rows=shifts().filter(x=>x.rig===rig),dt=sum(rows,'dt'),hours=sum(rows,'hours');return `<div class="rig-card"><div class="rig-title"><span>${rig}</span><span>${fmt(sum(rows,'meters'))} м</span></div><div class="rig-stats"><span>${rows.length} ээлж</span><span>ROP ${dt?fmt(sum(rows,'meters')/dt,2):'—'} м/ц</span></div><div class="track"><span style="width:${hours?dt/hours*100:0}%;background:${rig==='C-1800'?'#128875':'#dc8a3b'}"></span></div><div class="rig-stats"><span>Ашиглалт ${hours?fmt(dt/hours*100):'—'}%</span><span>ST ${knownHours(rows,'st')} цаг</span></div></div>`;}).join('');}
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
function performanceTable(){return `<section class="panel"><h2>${tab==='rop'?'Дундаж хурд · ROP':'Өрөмдлөгийн ашиглалт'}</h2><div class="table-scroll"><table><thead><tr><th>Өрөм</th><th>Өрөмдсөн</th><th>DT цаг</th><th>Нийт цаг</th><th>Ашиглалт</th><th>ROP м/ц</th></tr></thead><tbody>${['C-1800','CSD-1300'].filter(r=>!$('#rig').value||r===$('#rig').value).map(r=>{const rows=shifts().filter(s=>s.rig===r),dt=sum(rows,'dt'),hours=sum(rows,'hours'),m=sum(rows,'meters');return `<tr><td>${r}</td><td>${fmt(m)} м</td><td>${fmt(dt)}</td><td>${fmt(hours)}</td><td>${hours?fmt(dt/hours*100)+'%':'—'}</td><td>${dt?fmt(m/dt,2):'—'}</td></tr>`;}).join('')}</tbody></table></div></section>`;}
function logTime(value){const d=new Date(value);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(d);}
function logTable(){
  const labels={updated:'Шинэ өгөгдөл',unchanged:'Өөрчлөлтгүй',failed:'Алдаатай'},entries=[...dataLog].reverse();
  return `<section class="panel"><div class="panel-head"><h2>Data Log</h2><button class="button" id="refresh-log">Дахин унших ↻</button></div><p class="sub">Дата татсан түүх · Улаанбаатарын цагаар</p>${logError?`<p role="status">${esc(logError)}</p>`:''}<div class="table-scroll"><table><thead><tr><th>Татсан огноо / цаг</th><th>Эх үүсвэр</th><th>Төлөв</th><th>Файл</th><th>Цооног</th><th>Ээлж</th><th>Өрөмдсөн</th><th>Тайлбар</th></tr></thead><tbody>${entries.map(entry=>`<tr><td>${logTime(entry.startedAt)}</td><td>${entry.source==='drive'?'Google Drive':'Local CSV / XLSX'}</td><td><span class="badge ${entry.status==='failed'?'warn':''}">${labels[entry.status]||esc(entry.status)}</span></td><td>${fmt(entry.files,0)}</td><td>${fmt(entry.holes,0)}</td><td>${fmt(entry.shifts,0)}</td><td>${entry.meters==null?'—':fmt(entry.meters)+' м'}</td><td>${esc(entry.error||entry.note||'')}</td></tr>`).join('')||'<tr><td colspan="8" class="empty">Дата татсан түүх бүртгэгдээгүй.</td></tr>'}</tbody></table></div></section>`;
}
function sources(){return `<section class="panel"><h2>Өгөгдлийн эх сурвалж</h2><div class="source-list"><div class="source-row"><a class="source-link" href="${esc(D.collarUrl)}" target="_blank" rel="noopener">Collar бүртгэл ↗</a></div><div class="source-row"><a class="source-link" href="${esc(D.shiftUrl)}" target="_blank" rel="noopener">Ээлжийн тайлан ↗</a></div></div></section><section class="panel"><h2>Тооцоолол</h2><p>Ашиглалт = DT / нийт цаг. ROP = өрөмдсөн метр / DT. Цооногийн ахиц = сүүлийн ээлжийн гүн / төлөвлөсөн гүн.</p><p>Нормыг өрөм тус бүрээр 30 м/ээлж, 60 м/өдөр, 420 м/7 хоног гэж тооцно. Сарын норм = 60 м × тухайн сарын календарийн хоног. Дутуу тайлант 7 хоног, сарыг бүтэн календарийн үеийн нормтой харьцуулна.</p></section>`;}
let mappingMap=null,mappingMarkers=new Map();
function renderMapping(){
  const selected=holes(),points=DrillingMap.points(selected),known=new Set(points.map(point=>point.id));
  const missing=selected.filter(hole=>!known.has(hole.id));
  return `<section class="panel mapping-panel"><div class="panel-head"><div><h2>Mapping</h2><span class="sub">Газрын зурагт ${points.length} · Координатгүй ${missing.length}</span></div><button class="button" id="map-fit">Бүгдийг багтаах</button></div>
    <div class="mapping-layout"><div id="mapping-map" aria-label="Цооногуудын газрын зураг"></div><div class="mapping-list"><h3>Координаттай цооногууд</h3>
      ${points.map(point=>`<button class="mapping-hole" data-map-hole="${esc(point.id)}"><span class="map-dot ${areaOf(point.hole)==='Дорнын Төмөр'?'east':'west'}"></span><span><strong>${esc(point.id)}</strong><small>${esc(areaOf(point.hole))} · ${status(point.hole)[0]}</small></span></button>`).join('')||'<p class="sub">Шүүлтүүрт тохирох координаттай цооног алга.</p>'}
      ${missing.length?`<h3>Координатгүй</h3>${missing.map(hole=>`<button class="mapping-hole missing" data-hole="${esc(hole.id)}"><span><strong>${esc(hole.id)}</strong><small>E / N бүртгэгдээгүй</small></span></button>`).join('')}`:''}
    </div></div><div class="map-legend"><span><i class="map-dot east"></i>Дорнын Төмөр</span><span><i class="map-dot west"></i>Замт Хөндий</span></div><p id="map-tile-status" class="sub" role="status" hidden>Суурь зургийг ачаалж чадсангүй. Цооногийн цэгүүд харагдаж байна.</p></section>`;
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
    const h=point.hole,color=areaOf(h)==='Дорнын Төмөр'?'#16b99a':'#f29b44';
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
  if(!D)return;let content=['financial','mapping'].includes(tab)?'':kpis();
  if(tab==='financial')content+=renderFinancialTab();
  if(tab==='mapping')content+=renderMapping();
  if(tab==='overview')content+='<div class="grid"><section class="panel" id="chart-panel">'+chart()+'</section><section class="panel"><h2>Өрмийн гүйцэтгэл</h2>'+rigs()+'</section></div>';
  if(tab==='holes')content+='<section class="panel"><div class="panel-head"><h2>Цооногийн ахиц</h2><input class="search" aria-label="Цооног хайх" placeholder="Цооног хайх…" value="'+esc(query)+'"></div><div id="table">'+holeTable()+'</div></section>';
  if(tab==='shifts')content+='<section class="panel"><div class="panel-head"><h2>Ээлжийн бүртгэл</h2><input class="search" aria-label="Ээлж хайх" placeholder="Цооног, нэр, огноо…" value="'+esc(query)+'"></div><div id="table">'+shiftTable()+'</div></section>';
  if(tab==='rop'||tab==='utilization')content+=performanceTable();if(tab==='sources')content+=sources();if(tab==='data-log')content+=logTable();
  $('#app').innerHTML=content;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  if(tab==='mapping')initMapping();
  $('.search')?.addEventListener('input',e=>{query=e.target.value;$('#table').innerHTML=tab==='holes'?holeTable():shiftTable();});
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
});
for(const selector of ['#site','#area','#rig'])$(selector).addEventListener('change',()=>{selectedHole=null;render();});$('.close').addEventListener('click',()=>$('#detail').close());
$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('#export').addEventListener('click',()=>{
  const records=tab==='data-log'?dataLog:tab==='shifts'?shifts().filter(x=>(x.hole+' '+x.driller+' '+x.date).toLowerCase().includes(query.toLowerCase())):holes().filter(x=>x.id.toLowerCase().includes(query.toLowerCase())).map(h=>({...h,site:SITE,shiftDepth:depth(h.id),status:status(h)[0]}));
  if(!records.length){alert('Татах бүртгэл байхгүй.');return;}
  const keys=[...new Set(records.flatMap(r=>Object.keys(r)))],cell=value=>'"'+String(value??'').replace(/"/g,'""')+'"',csv='\uFEFF'+[keys,...records.map(r=>keys.map(k=>k==='reports'?(r[k]||[]).map(report=>report.url).join(' | '):r[k]))].map(r=>r.map(cell).join(',')).join('\r\n'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');
  a.href=url;a.download=`drilling-${tab}-${D.asOf}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function refreshLog(){try{const r=await fetch('data-log.json',{cache:'no-store'});if(!r.ok)throw Error();const log=await r.json();dataLog=log.entries||[];logError='';}catch{logError='Дата татсан түүхийг ачаалж чадсангүй.';}if(D&&tab==='data-log')render();}
async function refreshData(){try{const r=await fetch('data.json',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const data=await r.json(),changed=JSON.stringify(data)!==JSON.stringify(D);D=data;$('.period strong').textContent=D.period;$('#load-error').hidden=true;if(changed)render();}catch(e){$('#load-error').hidden=false;$('#load-error').textContent=D?'Өгөгдөл ачаалж чадсангүй. Өмнөх өгөгдлийг харуулж байна.':'Өгөгдөл ачаалж чадсангүй.';}}
setTheme(document.documentElement.dataset.theme);matchMedia('(prefers-color-scheme: light)').addEventListener('change',e=>{if(!savedTheme())setTheme(e.matches?'light':'dark');});
refreshData();refreshLog();setInterval(()=>{refreshData();refreshLog();},60000);
