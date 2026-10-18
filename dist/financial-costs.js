(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DrillingCosts=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Existing daily assumptions; water volume is carried separately from costs.
  const DAILY_LABOR=Object.freeze({'C-1800':1180000,'CSD-1300':980000}),DAILY_FOOD=735000;
  const FUEL_PRICE_PER_LITRE=3600,MUD_BAG_KG=25,MUD_PRICE_PER_BAG=330000,MUD_COST_PER_METRE=27000;
  function records(rows,rigs=Object.keys(DAILY_LABOR)){
    if(!rows.length)return [];
    const dates=rows.map(row=>row.date).sort(),end=Date.parse(dates.at(-1)+'T00:00:00Z'),groups=new Map(),result=[];
    for(const row of rows){const key=[row.date,row.rig,row.shift].join('|');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
    for(let time=Date.parse(dates[0]+'T00:00:00Z');time<=end;time+=86400000){
      const date=new Date(time).toISOString().slice(0,10);
      for(const rig of rigs)for(const shift of ['Өдөр','Шөнө']){
        const actual=groups.get([date,rig,shift].join('|'))||[],slots=actual.length?actual:[{date,rig,shift,meters:0,hole:'',hours:0}],hours=slots.reduce((sum,row)=>sum+(row.hours||0),0);
        for(const row of slots){
          const fraction=hours>0?(row.hours||0)/hours:1/slots.length,meters=Number(row.meters||0);
          const fuelUsageL=meters*(rig==='C-1800'?1.48:1.18),mudUsageKg=meters*MUD_COST_PER_METRE/MUD_PRICE_PER_BAG*MUD_BAG_KG;
          result.push({...row,recorded:!!actual.length,fuelUsageL,mudUsageKg,mudUsageBags:mudUsageKg/MUD_BAG_KG,
            fuelCost:fuelUsageL*FUEL_PRICE_PER_LITRE,mudCost:meters*MUD_COST_PER_METRE,waterUsageM3:row.waterUsageM3??null,
            laborCost:DAILY_LABOR[rig]/2*fraction,foodCost:DAILY_FOOD/Object.keys(DAILY_LABOR).length/2*fraction});
        }
      }
    }
    return result;
  }
  return {records,DAILY_LABOR,DAILY_FOOD,FUEL_PRICE_PER_LITRE,MUD_BAG_KG,MUD_PRICE_PER_BAG};
});
