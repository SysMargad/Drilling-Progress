(function(root){
  'use strict';
  const DAY=86400000,utc=date=>new Date(date+'T00:00:00Z'),iso=date=>date.toISOString().slice(0,10),add=(date,days)=>new Date(date.getTime()+days*DAY);
  function aggregate(rows,grain='day'){
    if(!['shift','day','week','month'].includes(grain))throw Error('Unknown chart period');
    const groups=new Map();
    for(const row of rows){
      let start=utc(row.date),end=start,key=row.date,label=row.date.slice(8),secondary='';
      if(grain==='shift'){key+='|'+(row.shift==='Өдөр'?'0':'1');secondary=row.shift==='Өдөр'?'Ө':'Ш';}
      if(grain==='week'){start=add(start,-((start.getUTCDay()+6)%7));end=add(start,6);key=iso(start);label=iso(start).slice(8)+'–'+iso(end).slice(8);}
      if(grain==='month'){start=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth(),1));end=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth()+1,0));key=iso(start);label=String(start.getUTCMonth()+1).padStart(2,'0');}
      if(!groups.has(key))groups.set(key,{key,label,secondary,start:iso(start),end:iso(end),target:grain==='shift'?30:60*(Math.round((end-start)/DAY)+1),amounts:{},counts:{}});
      const group=groups.get(key);group.amounts[row.rig]=(group.amounts[row.rig]||0)+row.meters;group.counts[row.rig]=(group.counts[row.rig]||0)+1;
    }
    return [...groups.values()].sort((a,b)=>a.key.localeCompare(b.key));
  }
  function title(groups){if(!groups.length)return 'Гүйцэтгэл';const first=groups[0].start.slice(0,7),last=groups.at(-1).end.slice(0,7);return first===last?'Гүйцэтгэл · '+first.slice(0,4)+' оны '+Number(first.slice(5))+'-р сар':'Гүйцэтгэл · '+first.replace('-','.')+' – '+last.replace('-','.');}
  const api={aggregate,title};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.DrillingChart=api;
})(globalThis);
