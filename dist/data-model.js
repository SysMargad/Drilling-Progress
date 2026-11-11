(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DrillingData=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Drilling Data: what each hole has on Drive for the NGM geological log system, judged by file names only
  // (contents are not opened). A log needs the collar's final depth, the geotechnical log or Technical Data
  // workbook (core box depths) and either core box photos (AI log from photos) or the geologist's log; with both it is a dual log.
  // Any file in the geological or geotechnical folder named as a log (Log, log, logging, Geolog…) is that log, in any format;
  // a geotechnical log on Drive means the hole's geotechnical logging is done.
  const DATA_FILE=/\.(xlsx|xls|csv)$/i,SHEET=/^[^.]+$/,HANDWRITTEN=/\.(jpe?g|png|heic|pdf)$/i,LOG=/log/i;
  // Google Docs and Sheets have no extension; their link tells them apart.
  const format=f=>DATA_FILE.test(f.name)?'Excel':/\.(\w+)$/.exec(f.name)?.[1].toUpperCase()||(/\/spreadsheets\//.test(f.url)?'Sheets':'Docs');
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
  // The link goes to the template workbook, else a spreadsheet, else a file titled as that log ("Geological Log").
  function logFile(list,template,title){
    const rank=f=>(DATA_FILE.test(f.name)?0:2)+(title.test(f.name)?0:1);
    return named(list,template)||list.filter(f=>LOG.test(f.name)).sort((a,b)=>rank(a)-rank(b))[0]||null;
  }
  // The log register (dist/log-register.json): logs the NGM geological log system made and uploaded to the hole's
  // 04 / 07 folder. A registered log counts as done at once, before the next Drive sync lists its file.
  function registered(entry,files){
    if(!entry)return null;
    const file={name:entry.name||'',url:entry.url||'',modified:entry.date||''};
    return {file,date:entry.date||'',by:entry.by||'',provisional:entry.provisional||'',files:files.some(f=>f.url===file.url)?files:[file,...files]};
  }
  function row(hole,inventory,shiftCount=0,folders={},register={}){
    const own=inventory?.[hole.id]||null,section=key=>own?.[key]||null,entry=register?.[hole.id]||{};
    const geologyFiles=files(own,'geological'),geotechFiles=files(own,'geotechnical');
    const geologyLog=logFile(geologyFiles,`${hole.id}_Geological_Log.xlsx`,/geological[\s_-]*log/i);
    const geotechLog=logFile(geotechFiles,`${hole.id}_Geotechnical_Log.xlsx`,/geotechnical[\s_-]*log/i);
    const technical=geotechLog?null:geotechFiles.find(f=>DATA_FILE.test(f.name))||null;
    const handwritten=geologyFiles.filter(f=>HANDWRITTEN.test(f.name));
    const geoReg=registered(entry.geological,geologyFiles),techReg=registered(entry.geotechnical,geotechFiles);
    const geologyDone=geologyLog||geoReg?.file,geotechDone=geotechLog||techReg?.file;
    const geology={url:section('geological')?.url||'',files:geoReg?.files||geologyFiles,file:geologyDone,format:geologyDone?format(geologyDone):'',
      state:geologyDone?'log':handwritten.length?'handwritten':geologyFiles.length?'other':'none',handwritten:handwritten.length,
      done:!!geologyDone,registered:geoReg?{date:geoReg.date,by:geoReg.by}:null,
      provisional:!geologyLog&&geoReg?.provisional||''};
    const geotech={url:section('geotechnical')?.url||'',files:techReg?.files||geotechFiles,file:geotechDone||technical,format:geotechDone?format(geotechDone):'',
      state:geotechDone?'log':technical?'technical':'none',done:!!geotechDone,registered:techReg?{date:techReg.date,by:techReg.by}:null,
      provisional:!geotechLog&&techReg?.provisional||''};
    const photos={url:section('photos')?.url||'',count:section('photos')?.count||0,formats:section('photos')?.formats||{},
      latest:section('photos')?.latest||'',boxes:Number.isFinite(hole.boxes)?hole.boxes:null};
    const pxrfFiles=files(own,'pxrf').filter(f=>DATA_FILE.test(f.name)||SHEET.test(f.name.trim()));
    const pxrf={url:section('pxrf')?.url||'',files:pxrfFiles,count:pxrfFiles.length};
    const surveys={url:section('surveys')?.url||'',files:files(own,'surveys'),count:files(own,'surveys').length};
    const collar={depth:Number.isFinite(hole.collarDepth)?hole.collarDepth:null,registered:hole.registered!=='drive',
      coordinates:Number.isFinite(hole.e)&&Number.isFinite(hole.n),elevation:Number.isFinite(hole.z)};
    const missing=[];
    if(collar.depth==null)missing.push('Collar эцсийн гүн');
    if(geotech.state==='none')missing.push('Геотехникийн лог эсвэл Technical Data');
    if(!photos.count&&geology.state!=='log')
      missing.push(geology.state==='handwritten'?'Кернийн зураг эсвэл геологийн лог (гар бичмэлийг буулгах)':'Кернийн зураг эсвэл геологийн лог');
    let state;
    if(!own&&!folders?.[hole.id])state='nodrive';
    else if(!hole.finish)state=shiftCount?'drilling':'planned';
    else if(missing.length)state='missing';
    else state=photos.count&&geology.state==='log'?'dual':photos.count?'ai':'geologist';
    return {id:hole.id,hole,folderUrl:folders?.[hole.id]?.url||'',collar,photos,geology,geotech,pxrf,surveys,logged:logged(hole),
      readiness:{state,label:LABELS[state],missing:state==='missing'?missing:[],ready:['dual','ai','geologist'].includes(state)}};
  }
  function rows(collar,shifts,inventory,folders={},register={}){
    return collar.map(hole=>row(hole,inventory,shifts.filter(s=>s.hole===hole.id).length,folders,register)).sort((a,b)=>a.id.localeCompare(b.id));
  }
  return {LABELS,LOGGED,row,rows,logged};
});
