(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DrillingCosts=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Existing daily assumptions; water volume is carried separately from costs.
  const DAILY_LABOR=Object.freeze({'C-1800':1180000,'CSD-1300':980000}),DAILY_FOOD=735000;
  const MUD_BAG_KG=25,MUD_PRICE_PER_BAG=330000;
  function records(rows,rigs=Object.keys(DAILY_LABOR),mud=null,fuel=null,diamond=null,water=null){
    if(!rows.length)return [];
    const dates=[...rows.map(row=>row.date),...(fuel?.daily||[]).map(row=>row.date),...(water?.records||[]).map(row=>row.date)].sort(),end=Date.parse(dates.at(-1)+'T00:00:00Z'),groups=new Map(),result=[];
    const mudByKey=new Map(),fuelByKey=new Map();
    for(const entry of fuel?.allocations||[]){const key=[entry.date,entry.rig,entry.shift,entry.hole].join('|');fuelByKey.set(key,entry);}
    for(const entry of mud?.allocations||[]){const key=[entry.date,entry.rig,entry.shift,entry.hole].join('|');mudByKey.set(key,(mudByKey.get(key)||0)+entry.bags);}
    for(const row of rows){const key=[row.date,row.rig,row.shift].join('|');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
    for(let time=Date.parse(dates[0]+'T00:00:00Z');time<=end;time+=86400000){
      const date=new Date(time).toISOString().slice(0,10);
      for(const rig of rigs)for(const shift of ['Өдөр','Шөнө']){
        const actual=groups.get([date,rig,shift].join('|'))||[],delivery=water?.records?.find(r=>r.date===date&&r.rig===rig&&r.shift===shift);
        const slots=actual.length?[...actual]:[{date,rig,shift,meters:0,hole:delivery?.hole||'',hours:0}];
        if(actual.length&&delivery&&!actual.some(r=>r.hole===delivery.hole))slots.push({date,rig,shift,meters:0,hole:delivery.hole,hours:0,waterOnly:true});
        const hours=slots.reduce((sum,row)=>sum+(row.hours||0),0);
        for(const row of slots){
          const fraction=hours>0?(row.hours||0)/hours:1/slots.length,meters=Number(row.meters||0);
          const matching=slots.filter(item=>item.hole===row.hole),weight=item=>Number(item.meters||0)>0?Number(item.meters):Number(item.hours||0)>0?Number(item.hours):1;
          const exactFuel=fuelByKey.get([date,rig,shift,row.hole].join('|')),fuelEntry=exactFuel||fuelByKey.get([date,rig,shift,''].join('|')),fuelSlots=exactFuel?matching:slots,fuelWeight=item=>Number(item.hours||0)>0?Number(item.hours):1;
          const eligibleFuelSlots=fuelSlots.filter(item=>!item.waterOnly);
          const fuelFraction=row.waterOnly?0:fuelWeight(row)/eligibleFuelSlots.reduce((n,item)=>n+fuelWeight(item),0);
          const fuelUsageL=(fuelEntry?.litres||0)*fuelFraction,fuelCost=(fuelEntry?.cost||0)*fuelFraction;
          const mudUsageBags=(mudByKey.get([date,rig,shift,row.hole].join('|'))||0)*weight(row)/matching.reduce((n,item)=>n+weight(item),0);
          const mudUsageKg=mudUsageBags*(mud?.bagKg||MUD_BAG_KG);
          const waterEntry=delivery?.hole===row.hole?delivery:null;
          const waterFraction=fuelWeight(row)/matching.reduce((n,item)=>n+fuelWeight(item),0);
          const measuredWater=row.waterUsageM3!=null&&!row.waterUsageEstimated;
          const dailyWater=(water?.dailyRecords||[]).some(r=>r.date===date&&r.rig===rig);
          const waterUsageM3=dailyWater?null:measuredWater?row.waterUsageM3:waterEntry?waterEntry.litres/1000*waterFraction:row.waterUsageM3??null;
          result.push({...row,recorded:actual.includes(row),fuelRecorded:!!fuelEntry&&!row.waterOnly,fuelUsageL,mudUsageKg,mudUsageBags,
            fuelCost,mudCost:mudUsageBags*(mud?.pricePerBag||MUD_PRICE_PER_BAG),diamondCost:diamond?meters*diamond.ratePerMeter:0,waterUsageM3,
            waterRecorded:!dailyWater&&!!waterEntry,waterEstimated:!dailyWater&&!!water?.estimated&&!measuredWater&&!!waterEntry,
            laborCost:DAILY_LABOR[rig]/2*fraction,foodCost:DAILY_FOOD/Object.keys(DAILY_LABOR).length/2*fraction});
        }
      }
    }
    for(const r of water?.dailyRecords||[]){
      if(!rigs.includes(r.rig))continue;
      result.push({date:r.date,rig:r.rig,shift:'Өдрийн нийт',hole:'',meters:0,hours:0,recorded:false,
        fuelRecorded:false,fuelUsageL:0,fuelCost:0,mudUsageKg:0,mudUsageBags:0,mudCost:0,diamondCost:0,
        laborCost:0,foodCost:0,waterUsageM3:r.litres/1000,waterRecorded:true,waterEstimated:!!water.estimated});
    }
    return result;
  }
  return {records,DAILY_LABOR,DAILY_FOOD,MUD_BAG_KG,MUD_PRICE_PER_BAG};
});
