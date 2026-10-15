'use strict';
let D,tab='overview',query='',grain='day',dataLog=[],logError='',selectedHole=null,chartBars=[];
const $=selector=>document.querySelector(selector);
const fmt=(n,d=1)=>n==null?'—':Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sum=(rows,key)=>rows.reduce((total,row)=>total+row[key],0),SITE='Нэргүй Өндөр';
function areaOf(h){const area=(h.targetArea||'').toLocaleLowerCase();if(area==='дорнын төмөр'||(!area&&h.id.startsWith('DTDH')))return 'Дорнын Төмөр';if(area==='замт хөндий'||(!area&&h.id.startsWith('ZHDH')))return 'Замт Хөндий';return h.targetArea||'—';}
function holes(){return D.collar.filter(h=>(h.site||SITE)===$('#site').value&&(!$('#area').value||areaOf(h)===$('#area').value)&&(!$('#rig').value||D.shifts.some(s=>s.hole===h.id&&s.rig===$('#rig').value)));}
function shifts(){const ids=new Set(holes().map(h=>h.id));return D.shifts.filter(s=>ids.has(s.hole)&&(!$('#rig').value||s.rig===$('#rig').value));}
function depth(id){const rows=D.shifts.filter(s=>s.hole===id);return rows.length?Math.max(...rows.map(s=>s.to)):null;}
function status(h){if(h.finish)return ['Дууссан',''];if(D.shifts.some(s=>s.hole===h.id))return ['Өрөмдөж байна','active'];return ['Төлөвлөсөн','planned'];}
let financialGrain='shift';
const financialGrainLabel=()=>({shift:'Ээлжийн',day:'Өдрийн',week:'7 хоногийн',month:'Сарын'}[financialGrain]);
const financialPreviousLabel=()=>({shift:'өмнөх ээлжтэй харьцуулахад',day:'өмнөх өдөртэй харьцуулахад',week:'өмнөх 7 хоногтой харьцуулахад',month:'өмнөх сартай харьцуулахад'}[financialGrain]);
const currency=(value,digits=0)=>value==null||Number.isNaN(Number(value))?'—':`₮ ${Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`;
function financialRows(grain=financialGrain){
  if(!D||!D.shifts?.length)return [];
  const sourceRows=shifts(),shiftCounts=new Map();
  for(const row of sourceRows){
    const key=`${row.date}|${row.rig}`;
    shiftCounts.set(key,(shiftCounts.get(key)||0)+1);
  }
  const groupMap=new Map();
  const periodStart=date=>{
    const day=new Date(`${date}T00:00:00Z`);
    if(grain==='week')day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    if(grain==='month')day.setUTCDate(1);
    return day.toISOString().slice(0,10);
  };
  for(const row of sourceRows){
    const shiftKey=`${row.date}|${row.rig}|${row.shift}`;
    const dailyRigKey=`${row.date}|${row.rig}`;
    const period=grain==='shift'?row.date+'|'+row.shift:grain==='day'?row.date:periodStart(row.date);
    const periodDate=grain==='shift'?row.date:period.split('|')[0];
    const entry=groupMap.get(period)||{date:periodDate,endDate:periodDate,shiftOrder:row.shift==='Өдөр'?0:1,drilledMeters:0,fuelCost:0,mudCost:0,waterCost:0,laborCost:0,foodCost:0,rigs:new Set(),shifts:new Set(),shiftLabels:new Set(),holes:new Set()};
    const meters=Number(row.meters||0);
    entry.drilledMeters+=meters;
    entry.rigs.add(row.rig);
    entry.shifts.add(shiftKey);
    entry.shiftLabels.add(row.shift);
    entry.holes.add(row.hole);
    const rigFactor=row.rig==='C-1800'?1.48:1.18;
    entry.fuelCost+=meters*rigFactor*3600;
    entry.mudCost+=meters*27000;
    entry.waterCost+=meters*9000;
    entry.laborCost+=(row.rig==='C-1800'?1180000:980000)/(shiftCounts.get(dailyRigKey)||1);
    entry.foodCost+=735000/(sourceRows.filter(s=>s.date===row.date).length||1);
    groupMap.set(period,entry);
  }
  const rows=[];
  let runningCost=0,runningMeters=0;
  const sortedEntries=[...groupMap.entries()].sort(([,a],[,b])=>a.date.localeCompare(b.date)||(a.shiftOrder??0)-(b.shiftOrder??0));
  for(let i=0;i<sortedEntries.length;i++){
    const [date,entry]=sortedEntries[i];
    const totalCost=entry.fuelCost+entry.mudCost+entry.waterCost+entry.laborCost+entry.foodCost;
    const dailyCostPerMeter=entry.drilledMeters>0?totalCost/entry.drilledMeters:null;
    runningCost += totalCost;
    runningMeters += entry.drilledMeters;
    rows.push({
      date:entry.date,
      period:date,
      periodEnd:entry.endDate,
      drilledMeters:entry.drilledMeters,
      fuelCost:entry.fuelCost,
      mudCost:entry.mudCost,
      waterCost:entry.waterCost,
      laborCost:entry.laborCost,
      foodCost:entry.foodCost,
      totalCost,
      dailyCostPerMeter,
      cumulativeCostPerMeter:runningMeters>0?runningCost/runningMeters:null,
      completion:'ASSUMPTION',
      note: entry.drilledMeters>0 ? 'Демо таамаглал — эх өгөгдлөөр баталгаажаагүй' : '0 м өрөмдсөн — зардал гарсан',
      rigs:[...entry.rigs].join(', '),
      shifts:entry.shifts.size,
      shiftLabel:[...entry.shiftLabels].join(', '),
      holes:[...entry.holes].join(', '),
      allCosts: [{key:'fuelCost',label:'Түлш',value:entry.fuelCost},{key:'mudCost',label:'Өрөмдлөгийн шавар',value:entry.mudCost},{key:'waterCost',label:'Ус',value:entry.waterCost},{key:'laborCost',label:'Цалин',value:entry.laborCost},{key:'foodCost',label:'Хоол',value:entry.foodCost}],
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
  const sourceRows=shifts(),rigs=['C-1800','CSD-1300'],shiftCounts=new Map(),dayCounts=new Map(),groups=new Map();
  for(const row of sourceRows){
    const rigDate=`${row.date}|${row.rig}`;
    shiftCounts.set(rigDate,(shiftCounts.get(rigDate)||0)+1);
    dayCounts.set(row.date,(dayCounts.get(row.date)||0)+1);
  }
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
      fuelCost:0,mudCost:0,waterCost:0,laborCost:0,foodCost:0,
      holes:new Set(),
    };
    entry.meters+=meters;
    entry.fuelCost+=meters*(row.rig==='C-1800'?1.48:1.18)*3600;
    entry.mudCost+=meters*27000;
    entry.waterCost+=meters*9000;
    entry.laborCost+=(row.rig==='C-1800'?1180000:980000)/(shiftCounts.get(`${row.date}|${row.rig}`)||1);
    entry.foodCost+=735000/(dayCounts.get(row.date)||1);
    entry.holes.add(row.hole);
    groups.set(groupKey,entry);
  }
  const periods=[...new Map([...groups.values()].map(row=>[row.key,row])).values()]
    .sort((a,b)=>a.date.localeCompare(b.date)||a.shiftOrder-b.shiftOrder);
  return rigs.map(rig=>{
    let runningCost=0,runningMeters=0;
    const points=periods.map(period=>{
      const row=groups.get(`${period.key}|${rig}`);
      if(!row)return {key:period.key,date:period.date,shift:period.shift,rig,value:null,cumulative:null,meters:0};
      const cost=row.fuelCost+row.mudCost+row.waterCost+row.laborCost+row.foodCost;
      runningCost+=cost;
      runningMeters+=row.meters;
      return {
        key:period.key,date:row.date,shift:row.shift,rig,value:row.meters?cost/row.meters:null,
        cumulative:runningMeters?runningCost/runningMeters:null,meters:row.meters,
        fuelCost:row.fuelCost,mudCost:row.mudCost,waterCost:row.waterCost,
        laborCost:row.laborCost,foodCost:row.foodCost,holes:[...row.holes].join(', '),
      };
    });
    return {rig,points};
  });
}
function renderFinancialChart(rows){
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
    return paths.map(pathPoints=>`<polyline class="rig-cost-line" data-rig="${rig}" points="${pathPoints}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`).join('') + points.map((point,index)=>point.value==null?'':`<circle cx="${xAt(index,points.length)}" cy="${yAt(point.value)}" r="4" fill="${color}"><title>${esc(point.date)}${grain==='shift'?` · ${esc(point.shift)}`:''} · ${esc(rig)} · ${esc(point.holes||'—')} · Өрөмдсөн: ${fmt(point.meters)} м · Түлш: ${currency(point.fuelCost,0)} · Шавар: ${currency(point.mudCost,0)} · Ус: ${currency(point.waterCost,0)} · Цалин: ${currency(point.laborCost,0)} · Хоол: ${currency(point.foodCost,0)} · 1 м зардал: ${currency(point.value,0)} · Хуримтлагдсан: ${currency(point.cumulative,0)} /м</title></circle>`).join('');
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
  const latest=rows.at(-1),dailyValue=latest.dailyCostPerMeter,change=latest.dayOverDayPercent;
  const categories=[['fuelCost','Түлш'],['mudCost','Өрөмдлөгийн шавар'],['waterCost','Ус'],['laborCost','Цалингийн зардал'],['foodCost','Хоолны зардал']];
  const breakdown=categories.map(([key,label])=>({key,label,total:rows.reduce((sum,r)=>sum+r[key],0),current:latest[key],previous:rows.at(-2)?.[key]??null}));
  const kpis=[
    [`${financialGrainLabel()} зардал (₮/м)`, dailyValue==null?'N/A':currency(dailyValue,0), 'Сонгосон хугацааны 1 м-ийн өртөг'],
    ['Хуримтлагдсан зардал (₮/м)', latest.cumulativeCostPerMeter==null?'N/A':currency(latest.cumulativeCostPerMeter,0), 'Эхний өдрөөс хойшхи өгөгдлийн жинхэнэ дундаж'],
    [`Өмнөх ${financialGrain==='shift'?'ээлжтэй':financialGrain==='day'?'өдөртэй':financialGrain==='week'?'7 хоногтой':'сартай'} харьцуулсан өөрчлөлт (%)`, change==null?'N/A':`${fmt(change,1)}%`, change==null?'Харьцуулах мэдээлэл дутуу':change>=0?'Өсөлт':'Бууралт'],
    ['Нийт зардал (₮)', currency(rows.reduce((sum,r)=>sum+r.totalCost,0),0), 'Бүгдийг нэгтгэсэн өртөг'],
    ['Нийт өрөмдсөн метр (м)', fmt(rows.reduce((sum,r)=>sum+r.drilledMeters,0),1), 'Тайлангийн хугацааны нийт м'],
    ['Түлшний зардал (₮/м)', rows.filter(r=>r.drilledMeters>0).length?currency(rows.reduce((sum,r)=>sum+r.fuelCost,0)/rows.reduce((sum,r)=>sum+r.drilledMeters,0),0):'N/A', 'Түлшний зардал/өрөмдсөн метр'],
  ];
  const controls=[['shift','Ээлж'],['day','Өдөр'],['week','7 хоног'],['month','Сар']].map(([value,label])=>`<button class="chart-period-button ${financialGrain===value?'active':''}" data-financial-grain="${value}" aria-pressed="${financialGrain===value}">${label}</button>`).join('');
  const breakdownMax=Math.max(...breakdown.map(item=>item.total),1);
  const costRows=breakdown.map(item=>{
    const delta=item.previous==null?null:item.current-item.previous;
    const percent=item.previous==null||item.previous===0?null:delta/item.previous*100;
    const direction=delta==null||delta===0?'flat':delta>0?'up':'down';
    const trend=percent==null?'Өмнөх хугацааны харьцуулалтгүй':`${delta>0?'▲':delta<0?'▼':'•'} ${fmt(Math.abs(percent),1)}% · ${financialPreviousLabel()} ${delta>0?'өссөн':delta<0?'буурсан':'өөрчлөлтгүй'}`;
    return `<div class="cost-row"><div class="cost-label"><span>${item.label}</span><strong>${currency(item.total,0)}</strong></div><div class="cost-bar"><span style="width:${(item.total/breakdownMax)*100}%"></span></div><div class="cost-change ${direction}"><span>${trend}</span><small>Сонгосон хугацааны дүн: ${currency(item.current,0)}</small></div></div>`;
  }).join('');
  const changeTone=change==null?'flat':change>0?'up':'down';
  return `<div class="financial-wrap"><section class="panel financial-panel"><div class="panel-head"><div><h2>Өрөм тус бүрийн 1 метрийн зардал (₮/м)</h2><span class="sub">C-1800 болон CSD-1300 · хуримтлагдсан дундаж KPI-д</span></div><div class="chart-periods" role="group" aria-label="Санхүүгийн графикийн хугацаа">${controls}</div></div>${renderFinancialChart(rows)}</section><div class="kpis">${kpis.map(([label,value,note],index)=>`<article class="kpi ${index===2?`financial-trend ${changeTone}`:''}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></article>`).join('')}</div><div class="grid"><section class="panel"><h2>Зардлын задаргаа</h2><p class="sub">Нийт дүн болон ${financialPreviousLabel()} өөрчлөлт</p><div class="cost-breakdown">${costRows}</div></section><section class="panel"><h2>Дэлгэрэнгүй бүртгэл</h2><div class="table-scroll"><table><thead><tr><th>Хугацаа</th><th>Өрөм</th><th>Ээлж</th><th>Цооног</th><th>Метр</th><th>Нийт ₮</th><th>₮/м</th><th>Төлөв</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.date}</td><td>${esc(r.rigs||'—')}</td><td>${esc(r.shiftLabel||'—')}</td><td>${esc(r.holes||'—')}</td><td>${fmt(r.drilledMeters,1)} м</td><td>${currency(r.totalCost,0)}</td><td>${r.dailyCostPerMeter==null?'N/A':currency(r.dailyCostPerMeter,0)}</td><td><span class="badge warn">${r.note}</span></td></tr>`).join('')}</tbody></table></div></section></div></div>`;
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
function rigs(){return ['C-1800','CSD-1300'].filter(rig=>!$('#rig').value||$('#rig').value===rig).map(rig=>{const rows=shifts().filter(x=>x.rig===rig),dt=sum(rows,'dt'),hours=sum(rows,'hours');return `<div class="rig-card"><div class="rig-title"><span>${rig}</span><span>${fmt(sum(rows,'meters'))} м</span></div><div class="rig-stats"><span>${rows.length} ээлж</span><span>ROP ${dt?fmt(sum(rows,'meters')/dt,2):'—'} м/ц</span></div><div class="track"><span style="width:${hours?dt/hours*100:0}%;background:${rig==='C-1800'?'#128875':'#dc8a3b'}"></span></div><div class="rig-stats"><span>Ашиглалт ${hours?fmt(dt/hours*100):'—'}%</span><span>ST ${fmt(sum(rows,'st'))} цаг</span></div></div>`;}).join('');}
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
function render(){
  hideBarTooltip();
  if(!D)return;let content=tab==='financial'?'':kpis();
  if(tab==='financial')content+=renderFinancialTab();
  if(tab==='overview')content+='<div class="grid"><section class="panel" id="chart-panel">'+chart()+'</section><section class="panel"><h2>Өрмийн гүйцэтгэл</h2>'+rigs()+'</section></div>';
  if(tab==='holes')content+='<section class="panel"><div class="panel-head"><h2>Цооногийн ахиц</h2><input class="search" aria-label="Цооног хайх" placeholder="Цооног хайх…" value="'+esc(query)+'"></div><div id="table">'+holeTable()+'</div></section>';
  if(tab==='shifts')content+='<section class="panel"><div class="panel-head"><h2>Ээлжийн бүртгэл</h2><input class="search" aria-label="Ээлж хайх" placeholder="Цооног, нэр, огноо…" value="'+esc(query)+'"></div><div id="table">'+shiftTable()+'</div></section>';
  if(tab==='rop'||tab==='utilization')content+=performanceTable();if(tab==='sources')content+=sources();if(tab==='data-log')content+=logTable();
  $('#app').innerHTML=content;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  $('.search')?.addEventListener('input',e=>{query=e.target.value;$('#table').innerHTML=tab==='holes'?holeTable():shiftTable();});
}
function openHole(id){const h=D.collar.find(x=>x.id===id),folder=D.folderMap?.[id],state=status(h);$('#detail-body').innerHTML=`<h2 style="font-size:25px">${esc(h.id)}</h2><p>${SITE} · ${esc(areaOf(h))} · <span class="badge ${state[1]}">${state[0]}</span></p><div class="detail-grid">${[['Төлөвлөсөн гүн',fmt(h.plan)+' м'],['Ээлжийн сүүлийн гүн',fmt(depth(id))+' м'],['Collar эцсийн гүн',fmt(h.collarDepth)+' м'],['Эхэлсэн / дууссан',`${h.start||'—'} / ${h.finish||'—'}`],['E / N / Z',`${fmt(h.e,3)} / ${fmt(h.n,3)} / ${fmt(h.z,3)}`],['Азимут / хазайлт',`${fmt(h.az)}° / ${fmt(h.dip)}°`],['Керний гарц',h.recovery==null?'—':fmt(h.recovery)+'%'],['Керний хайрцаг',fmt(h.boxes,0)]].map(([label,value])=>`<div><small>${label}</small><strong>${esc(value)}</strong></div>`).join('')}</div><h3>Эх баримтууд</h3><div class="folder-links">${folder?folder.folders.map(f=>`<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name)} ↗</a>`).join(''):'Энэ цооногийн хавтас олдоогүй.'}</div>`;$('#detail').showModal();}
document.addEventListener('click',e=>{
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
refreshData();refreshLog();setInterval(()=>{refreshData();refreshLog();},60000);
