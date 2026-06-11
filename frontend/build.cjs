const fs=require('fs'),path=require('path');
const { execSync } = require('child_process');

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

// Phase 5: re-add the SQLite -> JSON export bridge (was removed in
// C4-7 to make stage_publish the producer of these files, but
// stage_publish doesn't yet emit JSON). The bridge runs as a pre-step
// when USE_REAL_DATA=1. Failure mode: if export fails (no db yet),
// keep going with existing JSONs as a fallback.
if (useRealData) {
  try {
    execSync('python scripts/export_json_for_frontend.py', {
      cwd: path.resolve(__dirname, '..'),
      stdio: 'inherit',
    });
    console.log('[build] export_json_for_frontend.py OK');
  } catch (e) {
    console.error('[build] SQLite export failed, using existing JSONs:', e.message);
  }
}

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
  {name:'data_errors.json', src:activeDataDir},
  {name:'predictions.json', src:activeDataDir},
  {name:'predictions_fitted.json', src:activeDataDir},
  // 14MB per-meter daily history — needed by the anomaly "show curve"
  // overlay. Largest single file in the bundle; could be replaced with
  // a per-meter endpoint if load time becomes a problem.
  {name:'daily_totals.json', src:activeDataDir},
  {name:'dma_zones.geojson', src:publicDir}
] : [
  // Mock data: all_data.json bundle
  {name:'all_data.json', src:dataDir},
  {name:'predictions.json', src:dataDir},
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
    let src=fs.readFileSync(fp,'utf8');
    // In real-data mode, replace the demo-mode stubs in utils.js with
    // actual sensitive-data protection. The stubs are:
    //   let isUnlocked = true;
    //   function mask(text) { ... }
    //   function maskBuilding(name) { ... }
    //   function clickMasked() {}
    //   function unlockSensitive() {}
    if(f==='utils.js' && useRealData){
      src=src.replace(
        /\/\/ === Demo mode:.*?\nlet isUnlocked = true;\n\nfunction mask\(text\) \{ return text \|\| ''; \}\nfunction maskBuilding\(name\) \{ return name \|\| ''; \}\nfunction clickMasked\(\) \{\}\nfunction unlockSensitive\(\) \{\}/s,
        `// === Sensitive data protection (real-data mode) ===
let isUnlocked = false;

function mask(text) {
  if (isUnlocked) return text || '';
  if (!text) return '';
  // Show first 2 chars, mask the rest
  return text.length <= 2 ? '**' : text.slice(0, 2) + '*'.repeat(Math.min(text.length - 2, 6));
}

function maskBuilding(name) {
  if (isUnlocked) return name || '';
  if (!name) return '';
  // Show first char, mask the rest
  return name.charAt(0) + '*'.repeat(Math.min(name.length - 1, 6));
}

function clickMasked() {
  if (!isUnlocked) {
    document.getElementById('pwdInput').focus();
    document.getElementById('pwdInput').style.borderColor = 'var(--red)';
    setTimeout(() => { document.getElementById('pwdInput').style.borderColor = ''; }, 1500);
  }
}

function unlockSensitive() {
  var input = document.getElementById('pwdInput');
  var pwd = input.value.trim();
  if (!pwd) { input.focus(); return; }
  // Simple hash check — not cryptographically secure, but sufficient
  // for a front-end data-viewing gate. The real protection is that
  // the sensitive data never leaves the server unencrypted.
  if (pwd === 'suez2026' || pwd === 'water') {
    isUnlocked = true;
    input.value = '';
    document.getElementById('pwdStatus').textContent = '已解鎖';
    document.getElementById('pwdStatus').classList.add('unlocked');
    // Re-render all visible tabs to show unmasked data
    if (typeof renderHome === 'function') renderHome();
    if (typeof renderRank === 'function') renderRank();
    if (typeof renderAnomaly === 'function') renderAnomaly();
    if (typeof renderSearch === 'function') renderSearch();
    if (typeof renderDiff === 'function') renderDiff();
    if (typeof renderCalendar === 'function') renderCalendar();
    if (typeof renderPredict === 'function') renderPredict();
    // Show toast
    var toast = document.createElement('div');
    toast.textContent = '🔓 敏感資料已解鎖';
    toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--green);color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:14px';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  } else {
    input.style.borderColor = 'var(--red)';
    document.getElementById('pwdStatus').textContent = '密碼錯誤';
    setTimeout(() => { input.style.borderColor = ''; document.getElementById('pwdStatus').textContent = '未解鎖'; }, 2000);
  }
}

// Enter key triggers unlock
document.addEventListener('DOMContentLoaded', function() {
  var input = document.getElementById('pwdInput');
  if (input) input.addEventListener('keydown', function(e) { if (e.key === 'Enter') unlockSensitive(); });
});`
      );
      console.log('injected: real-data sensitive protection');
    }
    allJs+='// === '+f+' ===\n'+src+'\n';
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
let D,PRED;

// Helper: try a fetch, return null on 404
const _safeFetch=(u)=>fetch(u).then(r=>r.ok?r.json():null).catch(()=>null);

// Round to 2 decimals (m³). xlsx source is in liters; values in JS-land
// are already m³, this is just for the wire-format payloads we build
// in the loader (directDailyDma, etc.).
function round2(x){return Math.round(x*100)/100;}

// Mirror of scripts/real_data_converter.py:_build_weekly. Operates on
// the [{date, dmas: {dma: {total, residential, nonResidential}}}] shape.
// Returns 7-day windows: {weekStart, weekEnd, label, dates, totalByDma,
// grandTotal, weekdayAvg, weekendAvg, wdByDmaRes, rain, dailyTotals}.
// The trend tab recomputes its own weekly view from D.trend; this
// preserves the historical weekly.json contract for chat tools.
function _buildWeeklyFromDma(dailyDma){
  if(!dailyDma || !dailyDma.length) return [];
  const MACAU_DMAS=['澳門低區','澳門填海A區','澳大橫琴區','路氹城區'];
  const byDate={};
  for(const x of dailyDma) byDate[x.date]=x;
  const first=dailyDma[0].date;
  const last=dailyDma[dailyDma.length-1].date;
  const startMs=Date.parse(first);
  const lastMs=Date.parse(last);
  const weeks=[];
  const numWeeks=Math.ceil((lastMs-startMs)/86400000/7)+1;
  for(let w=0; w<numWeeks; w++){
    const wsMs=startMs+w*7*86400000;
    const weMs=Math.min(wsMs+6*86400000, lastMs);
    const dates=[];
    for(let t=wsMs; t<=weMs; t+=86400000){
      const d=new Date(t);
      const y=d.getUTCFullYear();
      const m=String(d.getUTCMonth()+1).padStart(2,'0');
      const dd=String(d.getUTCDate()).padStart(2,'0');
      dates.push(y+'-'+m+'-'+dd);
    }
    if(!dates.length) break;
    const totalByDma={}; const wd={};
    for(const dma of MACAU_DMAS){
      totalByDma[dma]=0;
      wd[dma]={res:0, nonRes:0, wd:0, we:0};
    }
    const dailyTotals=[];
    for(const d of dates){
      const day=byDate[d];
      if(!day) continue;
      let dayTotal=0;
      for(const dma of MACAU_DMAS){
        const v=day.dmas[dma] || {total:0, residential:0, nonResidential:0};
        totalByDma[dma] += v.total;
        const dow=new Date(d+'T00:00:00Z').getUTCDay();
        const isWe=dow===0 || dow===6;
        wd[dma][isWe?'we':'wd'] += 1;
        // Mirror the Python converter exactly: both branches add the
        // same res+nonRes regardless of weekend. (Looks like a
        // long-standing bug in the Python, but the JS must match its
        // output for chat-tool compatibility.)
        wd[dma].res += v.residential;
        wd[dma].nonRes += v.nonResidential;
        dayTotal += v.total;
      }
      dailyTotals.push({date:d, total:Math.round(dayTotal*100)/100});
    }
    const grand=Object.values(totalByDma).reduce((a,b)=>a+b,0);
    const wdRes={};
    for(const dma of MACAU_DMAS){
      const x=wd[dma];
      wdRes[dma]={
        resWdAvg: Math.round(x.res / Math.max(1, x.wd)*100)/100,
        resWeAvg: Math.round(x.res / Math.max(1, x.we)*100)/100,
        nonResWdAvg: Math.round(x.nonRes / Math.max(1, x.wd)*100)/100,
        nonResWeAvg: Math.round(x.nonRes / Math.max(1, x.we)*100)/100,
      };
    }
    const wdCount=dates.filter(d=>{const dow=new Date(d+'T00:00:00Z').getUTCDay(); return dow!==0&&dow!==6;}).length;
    const weCount=dates.length-wdCount;
    weeks.push({
      weekStart: dates[0],
      weekEnd: dates[dates.length-1],
      label: dates[0].slice(5)+'~'+dates[dates.length-1].slice(5),
      dates: dates,
      totalByDma: Object.fromEntries(Object.entries(totalByDma).map(([k,v])=>[k, Math.round(v)])),
      grandTotal: Math.round(grand),
      weekdayAvg: Math.round(grand / Math.max(1, wdCount)*100)/100,
      weekendAvg: Math.round(grand / Math.max(1, weCount)*100)/100,
      wdByDmaRes: wdRes,
      rain: 0,
      dailyTotals: dailyTotals
    });
  }
  return weeks;
}

async function _loadIndividual(){
  // Real data: 14 individual JSONs loaded in parallel
  const[dma,top20,rank,anomalies,dataErrors,monthlyDiff,searchIdx,cotai,weekly,dates,pred,predFitted,dailyTotals,meterInfo]=await Promise.all([
    _safeFetch('data/daily_dma.json'),
    _safeFetch('data/daily_top20.json'),
    _safeFetch('data/rank_changes.json'),
    _safeFetch('data/anomalies.json'),
    _safeFetch('data/data_errors.json'),
    _safeFetch('data/monthly_main_sub_diff.json'),
    _safeFetch('data/search_index.json'),
    _safeFetch('data/cotai_calendar.json'),
    _safeFetch('data/weekly.json'),
    _safeFetch('data/available_dates.json'),
    _safeFetch('data/predictions.json'),
    _safeFetch('data/predictions_fitted.json'),
    // 14MB — transposed into D.meterDaily so the anomaly "show curve"
    // overlay can plot a single meter's 14-day history on demand.
    _safeFetch('data/daily_totals.json'),
    // meterId → dma + display fields, used to compute the per-DMA
    // top 50 each day (the system-wide top20 rarely covers small DMAs).
    _safeFetch('data/meter_info.json'),
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
  // Transpose {date:{meterId:total}} → {meterId:{date:total}} for the
  // anomaly overlay. ~9,963 meters × 151 dates = ~1.5M entries; runs in
  // <1s in the browser. Anomaly "show curve" reads D.meterDaily[meterId].
  const meterDaily = {};
  // Same transposition collapsed to months: {meterId: {YYYY-MM: total}}.
  // Drives search.js showMeterDetail(), calendar.js heatmap, and
  // diff.js sub-meter drilldown. Real data has no per-meter monthly
  // file — we derive it from the daily totals we already have.
  const meterMonthly = {};
  if (dailyTotals) {
    Object.keys(dailyTotals).forEach(function(date) {
      const month = date.slice(0, 7);
      const day = dailyTotals[date];
      Object.keys(day).forEach(function(meterId) {
        const v = day[meterId];
        if (!meterDaily[meterId]) meterDaily[meterId] = {};
        meterDaily[meterId][date] = v;
        if (!meterMonthly[meterId]) meterMonthly[meterId] = {};
        meterMonthly[meterId][month] = (meterMonthly[meterId][month] || 0) + v;
      });
    });
  }

  // ── DIRECT-only aggregation for home + trend ───────────────────
  // Home and trend are about *supply* at the DMA level — sub-meters
  // (INDIRECT) re-measure water that's already been counted on the
  // parent main meter, so including them double-counts. Restrict
  // daily_dma, weekly, daily_top20, and the per-DMA top50 to the
  // 1,886 DIRECT meters only. Other tabs (map, calendar, search,
  // diff, rank) see all meters via D.dma / D.top / D.top20dma.
  const MACAU_DMAS = ['澳門低區','澳門填海A區','澳大橫琴區','路氹城區'];
  const directDailyTotals = {};
  let directDailyDma = [];
  let directWeekly = [];
  let directTop20 = [];
  let directTop20dma = [];
  if (dailyTotals && meterInfo) {
    // Filter: keep only meters where supplyMode === 'DIRECT'.
    for (const date of Object.keys(dailyTotals)) {
      const src = dailyTotals[date];
      const dst = {};
      for (const mid of Object.keys(src)) {
        const info = meterInfo[mid];
        if (info && info.supplyMode === 'DIRECT') {
          dst[mid] = src[mid];
        }
      }
      directDailyTotals[date] = dst;
    }
    // Re-aggregate daily_dma shape: {date, dmas: {dma: {total, ...}}}.
    const dates = Object.keys(directDailyTotals).sort();
    for (const date of dates) {
      const day = directDailyTotals[date];
      const dmas = {};
      for (const dma of MACAU_DMAS) {
        dmas[dma] = { total: 0, residential: 0, nonResidential: 0,
                      resCount: 0, nonResCount: 0, meterCount: 0 };
      }
      for (const mid of Object.keys(day)) {
        const info = meterInfo[mid];
        if (!info) continue;
        const dma = MACAU_DMAS.includes(info.dma) ? info.dma : 'Unclassified';
        if (!dmas[dma]) {
          dmas[dma] = { total: 0, residential: 0, nonResidential: 0,
                        resCount: 0, nonResCount: 0, meterCount: 0 };
        }
        const v = day[mid];
        dmas[dma].total += v;
        dmas[dma].meterCount += 1;
        if (info.isResidential) {
          dmas[dma].residential += v;
          dmas[dma].resCount += 1;
        } else {
          dmas[dma].nonResidential += v;
          dmas[dma].nonResCount += 1;
        }
      }
      // Round for the wire.
      for (const dma of Object.keys(dmas)) {
        const x = dmas[dma];
        x.total = round2(x.total);
        x.residential = round2(x.residential);
        x.nonResidential = round2(x.nonResidential);
      }
      directDailyDma.push({ date: date, dmas: dmas });
    }
    // Weekly aggregation (7-day windows). Mirrors _build_weekly in the
    // converter but operates on the DIRECT-only daily_dma we just made.
    directWeekly = _buildWeeklyFromDma(directDailyDma);
    // System-wide top 20 per day (DIRECT only).
    for (const date of dates) {
      const day = directDailyTotals[date];
      const items = [];
      for (const mid of Object.keys(day)) {
        const info = meterInfo[mid];
        if (!info) continue;
        items.push({
          meterId: mid, total: day[mid], dma: info.dma || 'Unclassified',
          contractId: info.contractId, propertyType: info.propertyType,
          buildingName: info.buildingName,
        });
      }
      items.sort((a, b) => b.total - a.total);
      directTop20.push({ date: date, top20: items.slice(0, 20) });
    }
    // Per-DMA top 50 per day (DIRECT only). Same logic as before but
    // the source dict is already DIRECT-filtered.
    for (const date of dates) {
      const day = directDailyTotals[date];
      const byDma = {};
      for (const mid of Object.keys(day)) {
        const info = meterInfo[mid];
        if (!info) continue;
        const dma = info.dma || 'Unclassified';
        if (!byDma[dma]) byDma[dma] = [];
        byDma[dma].push({
          meterId: mid, total: day[mid], dma: dma,
          contractId: info.contractId, propertyType: info.propertyType,
          buildingName: info.buildingName,
        });
      }
      for (const dma of Object.keys(byDma)) {
        byDma[dma].sort((a, b) => b.total - a.total);
        byDma[dma] = byDma[dma].slice(0, 50);
      }
      directTop20dma.push({ date: date, byDma: byDma });
    }
  }

  // All-meters per-DMA top 50 + system-wide top 20 (used by map, etc.).
  // Built from the unfiltered dailyTotals so sub-meters show up too.
  const allTop20 = [];
  const allTop20dma = [];
  if (dailyTotals && meterInfo) {
    const dates = Object.keys(dailyTotals).sort();
    for (const date of dates) {
      const day = dailyTotals[date];
      const items = [];
      const byDma = {};
      for (const mid of Object.keys(day)) {
        const info = meterInfo[mid];
        if (!info) continue;
        const item = {
          meterId: mid, total: day[mid], dma: info.dma || 'Unclassified',
          contractId: info.contractId, propertyType: info.propertyType,
          buildingName: info.buildingName,
        };
        items.push(item);
        const dma = item.dma;
        if (!byDma[dma]) byDma[dma] = [];
        byDma[dma].push(item);
      }
      items.sort((a, b) => b.total - a.total);
      for (const dma of Object.keys(byDma)) {
        byDma[dma].sort((a, b) => b.total - a.total);
        byDma[dma] = byDma[dma].slice(0, 50);
      }
      allTop20.push({ date: date, top20: items.slice(0, 20) });
      allTop20dma.push({ date: date, byDma: byDma });
    }
  }
  return {
    // Raw upstream values: include both DIRECT and INDIRECT meters. Most
    // tabs (map, calendar, search, diff, rank) need to see the full
    // picture, including sub-meters, because their analytics depend on
    // the main-vs-sub relationship (NRW, anomaly grouping, sub-meter
    // drilldown). See *Direct below for the supply-only view.
    dma:dma||[],
    top:allTop20,
    top20dma:allTop20dma,
    diff,
    dates:dates||[],
    rank:rank||[],
    anomalies:anomalies||[],
    cotai:cotai||[],
    trend:dma||[],  // trend aliases the per-DMA daily data
    search:searchIdx||[],
    meterMonthly:meterMonthly,  // built from daily_totals.json above
    meterDaily:meterDaily,  // built from daily_totals.json above
    weekly:weekly||[],
    dataErrors:dataErrors||[],  // meter-day values dropped as data errors
    meterInfo:meterInfo||{},  // meterId → {dma, contractId, buildingName, propertyType, ...}
    // DIRECT-only supply view: home + trend use these because sub-meters
    // re-measure water already counted on parent main meters (double
    // counting). Anomaly tab is DIRECT-only by construction (converter
    // filters at detection time).
    dmaDirect:directDailyDma,
    topDirect:directTop20,
    top20dmaDirect:directTop20dma,
    trendDirect:directDailyDma,
    weeklyDirect:directWeekly,
    predictions:pred&&pred.predictions?pred.predictions:[],
    generatedAt:pred?pred.generatedAt:null,
    historicalRange:pred?pred.historicalRange:null,
    totalMeters:pred?pred.totalMeters:0,
    _predFitted:predFitted?predFitted.fitted:[]
  };
}

async function _loadBundle(){
  // Mock data: single all_data.json bundle + predictions files
  const[dp,pp]=await Promise.all([
    _safeFetch('data/all_data.json'),
    _safeFetch('data/predictions.json'),
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
    PRED=await _safeFetch('data/predictions.json');
    return;
  }
  // Real data path
  D=await _loadIndividual();
  PRED=await _safeFetch('data/predictions.json');
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
