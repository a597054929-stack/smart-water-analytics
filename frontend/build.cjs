const fs=require('fs'),path=require('path');

const outDir=path.resolve(__dirname,'./dist');
const dataDir=path.resolve(__dirname,'../backend/data/output');
const publicDir=path.resolve(__dirname,'../public/data');
fs.mkdirSync(outDir,{recursive:true});
fs.mkdirSync(path.join(outDir,'data'),{recursive:true});

// Clean dist/data/ before writing. Mock build leaves all_data.json;
// real build leaves 12 individual JSONs. If both coexist, the loader's
// "try bundle first" branch picks up the stale mock file silently.
const distDataDir = path.join(outDir, 'data');
for (const f of fs.readdirSync(distDataDir)) {
  fs.unlinkSync(path.join(distDataDir, f));
}

// Data files. Real data uses individual JSONs (no all_data.json — too big).
// Mock data uses the bundle. Both are supported.
const dataDirReal = path.resolve(__dirname, '../backend/data/output_real');
const useRealData = process.env.USE_REAL_DATA === '1' && fs.existsSync(dataDirReal);
const activeDataDir = useRealData ? dataDirReal : dataDir;

const dataFiles = useRealData ? [
  // Real data: 13 individual JSONs
  {name:'meter_info.json', src:activeDataDir},
  {name:'available_dates.json', src:activeDataDir},
  {name:'daily_dma.json', src:activeDataDir},
  {name:'weekly.json', src:activeDataDir},
  {name:'daily_top20.json', src:activeDataDir},
  {name:'rank_changes.json', src:activeDataDir},
  {name:'monthly_main_sub_diff.json', src:activeDataDir},
  {name:'search_index.json', src:activeDataDir},
  {name:'cotai_calendar.json', src:activeDataDir},
  {name:'anomalies.json', src:activeDataDir},
  {name:'predictions.json', src:activeDataDir},
  {name:'predictions_fitted.json', src:activeDataDir},
  {name:'predictions_by_building.json', src:activeDataDir},
  {name:'dma_zones.geojson', src:publicDir}
] : [
  // Mock data: all_data.json bundle
  {name:'all_data.json', src:dataDir},
  {name:'predictions.json', src:dataDir},
  {name:'predictions_by_building.json', src:dataDir},
  {name:'dma_zones.geojson', src:publicDir}
];

for(const f of dataFiles){
  const srcPath=path.join(f.src, f.name);
  const dstPath=path.join(outDir,'data',f.name);
  if(fs.existsSync(srcPath)){
    fs.copyFileSync(srcPath,dstPath);
    console.log('copied:',f.name,`(${(fs.statSync(dstPath).size/1024/1024).toFixed(2)}MB)`);
  }else{
    console.warn('missing:',srcPath);
  }
}

// Real data path writes 12 individual JSONs but no all_data.json bundle.
// _loadBundle tries all_data.json first as a "find the mock bundle" probe
// and falls through to _loadIndividual on 404. To silence the 404 in the
// browser console (and any 404-monitor tooling), write a stub all_data.json
// containing the JSON literal `null` so the fetch returns 200 + null.
if(useRealData){
  const stubPath=path.join(outDir,'data','all_data.json');
  fs.writeFileSync(stubPath,'null');
  console.log('stubbed: all_data.json (null) — silence 404 in real-data mode');
}

// Read template
const templatePath=path.resolve(__dirname,'./template.html');
let template=fs.readFileSync(templatePath,'utf8');

// Read and inline CSS
const cssPath=path.resolve(__dirname,'./css/styles.css');
const css=fs.readFileSync(cssPath,'utf8');
template=template.replace(
  /<link rel="stylesheet" href="css\/styles\.css" \/>/,
  '<style>\n'+css+'\n</style>'
);

// Read and inline JS modules (in order)
const jsFiles=[
  'utils.js','tabs.js','home.js','trend.js','rank.js',
  'diff.js','anomaly.js','search.js','predict.js','map.js','calendar.js','chat.js'
];
const jsDir=path.resolve(__dirname,'./js');
let allJs='';
for(const f of jsFiles){
  const fp=path.join(jsDir,f);
  if(fs.existsSync(fp)){
    allJs+='// === '+f+' ===\n'+fs.readFileSync(fp,'utf8')+'\n';
  }else{
    console.warn('missing js:',fp);
  }
}

// Replace script tags with inline JS
template=template.replace(
  /<!-- JS Modules -->[\s\S]*?<!-- Data & Init -->/,
  '<script>\n'+allJs+'\n</script>\n\n<!-- Data & Init -->'
);

// Replace data placeholders with fetch-based loading
// Two paths supported:
//   - Mock data: load all_data.json (single big file, ~3.8MB)
//   - Real data: load individual JSONs in parallel (~2MB total, no 180MB bundle)
const fetchCode=`
let D,PRED,PRED_BLD;

// Helper: try a fetch, return null on 404
const _safeFetch=(u)=>fetch(u).then(r=>r.ok?r.json():null).catch(()=>null);

async function _loadIndividual(){
  // Real data: 12 individual JSONs loaded in parallel
  const[dma,top20,rank,anomalies,monthlyDiff,searchIdx,cotai,weekly,dates,pred,predBld,predFitted]=await Promise.all([
    _safeFetch('data/daily_dma.json'),
    _safeFetch('data/daily_top20.json'),
    _safeFetch('data/rank_changes.json'),
    _safeFetch('data/anomalies.json'),
    _safeFetch('data/monthly_main_sub_diff.json'),
    _safeFetch('data/search_index.json'),
    _safeFetch('data/cotai_calendar.json'),
    _safeFetch('data/weekly.json'),
    _safeFetch('data/available_dates.json'),
    _safeFetch('data/predictions.json'),
    _safeFetch('data/predictions_by_building.json'),
    _safeFetch('data/predictions_fitted.json'),
  ]);
  // Real converter emits mainTotal/subsTotal/diffPercent and no
  // subCount; the JS expects mainMonthTotal/subMonthTotal/diffPct/
  // subCount (legacy mock-data shape). Map once here so every renderer
  // can stay schema-blind.
  const diff = (monthlyDiff || []).map(m => ({
    ...m,
    diffs: (m.diffs || []).map(d => ({
      ...d,
      mainMonthTotal: d.mainTotal ?? 0,
      subMonthTotal:  d.subsTotal ?? 0,
      diffPct:        d.diffPercent ?? 0,
      subCount:       Array.isArray(d.subs) ? d.subs.length : 0,
    })),
  }));
  return {
    dma:dma||[],
    top:top20?top20.map(d=>({date:d.date,top20:d.top20})):[],
    top20dma:[],  // not generated; computed on demand if needed
    diff,
    dates:dates||[],
    rank:rank||[],
    anomalies:anomalies||[],
    cotai:cotai||[],
    trend:dma||[],  // trend is the daily_dma array
    search:searchIdx||[],
    meterMonthly:{},  // not generated for real data
    meterDaily:{},    // not generated for real data
    weekly:weekly||[],
    predictions:pred&&pred.predictions?pred.predictions:[],
    generatedAt:pred?pred.generatedAt:null,
    historicalRange:pred?pred.historicalRange:null,
    totalMeters:pred?pred.totalMeters:0,
    _predFitted:predFitted?predFitted.fitted:[]
  };
}

async function _loadBundle(){
  // Mock data: single all_data.json bundle + predictions files
  const[dp,pp,pbp]=await Promise.all([
    _safeFetch('data/all_data.json'),
    _safeFetch('data/predictions.json'),
    _safeFetch('data/predictions_by_building.json')
  ]);
  if(!dp)throw new Error('all_data.json not found');
  return Object.assign({},dp,{predictions:pp&&pp.predictions?pp.predictions:[]});
}

async function loadData(){
  // Try bundle first; fall back to individual files.
  let bundle;
  try{bundle=await _loadBundle();}catch(e){bundle=null;}
  if(bundle){
    D=bundle;
    const[pp,pbp]=await Promise.all([_safeFetch('data/predictions.json'),_safeFetch('data/predictions_by_building.json')]);
    PRED=pp;PRED_BLD=pbp;
    return;
  }
  // Real data path
  D=await _loadIndividual();
  PRED=await _safeFetch('data/predictions.json');
  PRED_BLD=await _safeFetch('data/predictions_by_building.json');
}

// Initialize after data loads
loadData().then(()=>{
  const cotaiKey=D.dates.length?Object.keys(D.dma[0].dmas).find(k=>k.charCodeAt(1)===0xebf3):'';
  if(cotaiKey)DC[cotaiKey]='#f472b6';
  selDate=D.dates[D.dates.length-1];

  // Hide loading screen
  const loadingEl=document.getElementById('globalLoading');
  if(loadingEl){loadingEl.classList.add('fade-out');setTimeout(()=>loadingEl.remove(),300);}

  renderHome();
}).catch(e=>{
  const loadingEl=document.getElementById('globalLoading');
  if(loadingEl)loadingEl.innerHTML='<div style="color:#ef4444;font-size:16px">数据加载失败</div><p style="color:#6b6b80">'+e.message+'</p>';
});
`;

template=template.replace(
  /<script>\s*const D=ALLDATA_PLACEHOLDER;[\s\S]*?<\/script>/,
  '<script>'+fetchCode+'</script>'
);

// Write output
const outPath=path.join(outDir,'dashboard.html');
fs.writeFileSync(outPath,template);
console.log('OK:',(fs.statSync(outPath).size/1024).toFixed(0)+'KB');
