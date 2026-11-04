(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DrillingData=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Drilling Data: what each hole has on Drive for the NGM geological log system, judged by file names only
  // (contents are not opened). A log needs the collar's final depth, a geotechnical workbook (core box depths)
  // and either core box photos (AI log from photos) or the geologist's Excel log; with both it is a dual log.
  const DATA_FILE=/\.(xlsx|xls|csv)$/i,SHEET=/^[^.]+$/,HANDWRITTEN=/\.(jpe?g|png|heic|pdf)$/i;
  const LABELS={dual:'Геологич + AI',ai:'AI лог (зургаас)',geologist:'Геологичийн лог',missing:'Дата дутуу',
    drilling:'Өрөмдөж байна',planned:'Төлөвлөсөн',nodrive:'Drive хавтас олдсонгүй'};
  // Whether the hole has been logged: the team's register in the collar sheet ("Geology log",
  // "Geotechnical log" columns: Completed / in progress / blank). Absent columns (holes registered
  // from their Drive folder only) are unknown, not "not logged".
  const LOGGED={done:'Хийгдсэн',partial:'Хэсэгчлэн',none:'Хийгдээгүй',unknown:'Бүртгэлгүй'};
  const register=value=>{const text=String(value??'').trim();return !text?'none':/complete/i.test(text)?'done':'other';};
  function logged(hole){
    if(!('geologyLog' in hole)&&!('geotechLog' in hole))return {state:'unknown',label:LOGGED.unknown,geology:'',geotech:'',pxrf:''};
    const g=register(hole.geologyLog),t=register(hole.geotechLog);
    const state=g==='done'&&t==='done'?'done':g==='none'&&t==='none'?'none':'partial';
    return {state,label:LOGGED[state],geology:hole.geologyLog||'',geotech:hole.geotechLog||'',pxrf:hole.pxrfLog||''};
  }
  const files=(inventory,section)=>(inventory?.[section]?.files||[]).filter(f=>!/^\s*delete/i.test(f.name));
  const named=(list,name)=>list.find(f=>f.name.trim().toLowerCase()===name.toLowerCase())||null;
  function row(hole,inventory,shiftCount=0,folders={}){
    const own=inventory?.[hole.id]||null,section=key=>own?.[key]||null;
    const geologyFiles=files(own,'geological'),geotechFiles=files(own,'geotechnical');
    const geologyLog=named(geologyFiles,`${hole.id}_Geological_Log.xlsx`),geotechLog=named(geotechFiles,`${hole.id}_Geotechnical_Log.xlsx`);
    const technical=geotechLog?null:geotechFiles.find(f=>DATA_FILE.test(f.name))||null;
    const handwritten=geologyFiles.filter(f=>HANDWRITTEN.test(f.name));
    const geology={url:section('geological')?.url||'',files:geologyFiles,file:geologyLog,
      state:geologyLog?'template':handwritten.length?'handwritten':geologyFiles.length?'other':'none',handwritten:handwritten.length};
    const geotech={url:section('geotechnical')?.url||'',files:geotechFiles,file:geotechLog||technical,
      state:geotechLog?'template':technical?'technical':'none'};
    const photos={url:section('photos')?.url||'',count:section('photos')?.count||0,formats:section('photos')?.formats||{},
      latest:section('photos')?.latest||'',boxes:Number.isFinite(hole.boxes)?hole.boxes:null};
    const pxrfFiles=files(own,'pxrf').filter(f=>DATA_FILE.test(f.name)||SHEET.test(f.name.trim()));
    const pxrf={url:section('pxrf')?.url||'',files:pxrfFiles,count:pxrfFiles.length};
    const surveys={url:section('surveys')?.url||'',files:files(own,'surveys'),count:files(own,'surveys').length};
    const collar={depth:Number.isFinite(hole.collarDepth)?hole.collarDepth:null,registered:hole.registered!=='drive',
      coordinates:Number.isFinite(hole.e)&&Number.isFinite(hole.n),elevation:Number.isFinite(hole.z)};
    const missing=[];
    if(collar.depth==null)missing.push('Collar эцсийн гүн');
    if(geotech.state==='none')missing.push('Геотехникийн Excel');
    if(!photos.count&&geology.state!=='template')
      missing.push(geology.state==='handwritten'?'Кернийн зураг эсвэл геологийн Excel (гар бичмэлийг буулгах)':'Кернийн зураг эсвэл геологийн Excel');
    let state;
    if(!own&&!folders?.[hole.id])state='nodrive';
    else if(!hole.finish)state=shiftCount?'drilling':'planned';
    else if(missing.length)state='missing';
    else state=photos.count&&geology.state==='template'?'dual':photos.count?'ai':'geologist';
    return {id:hole.id,hole,folderUrl:folders?.[hole.id]?.url||'',collar,photos,geology,geotech,pxrf,surveys,logged:logged(hole),
      readiness:{state,label:LABELS[state],missing:state==='missing'?missing:[],ready:['dual','ai','geologist'].includes(state)}};
  }
  function rows(collar,shifts,inventory,folders={}){
    return collar.map(hole=>row(hole,inventory,shifts.filter(s=>s.hole===hole.id).length,folders)).sort((a,b)=>a.id.localeCompare(b.id));
  }
  return {LABELS,LOGGED,row,rows,logged};
});
