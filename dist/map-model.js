(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./vendor/proj4.js'):root.proj4);if(typeof module==='object'&&module.exports)module.exports=api;else root.DrillingMap=api;})(typeof globalThis!=='undefined'?globalThis:this,function(project){
  'use strict';
  // Nergui_undur_2026.gpkg and the project PRJ both identify EPSG:32649.
  const CRS='+proj=utm +zone=49 +datum=WGS84 +units=m +no_defs';
  function point(hole){
    if(!Number.isFinite(hole.e)||!Number.isFinite(hole.n)||hole.e<100000||hole.e>900000||hole.n<0||hole.n>10000000)return null;
    const [lng,lat]=project(CRS,'EPSG:4326',[hole.e,hole.n]);
    if(!Number.isFinite(lat)||!Number.isFinite(lng)||lat<0||lat>84||lng<105||lng>117)return null;
    return {id:hole.id,lat,lng,hole};
  }
  function points(holes){return holes.map(point).filter(Boolean);}
  return {CRS,point,points};
});
