const fs=require('fs'),path=require('path');

const outDir=path.resolve(__dirname,'./dist');
const dataDir=path.resolve(__dirname,'../backend/data/output');
const publicDir=path.resolve(__dirname,'../public/data');
fs.mkdirSync(outDir,{recursive:true});
fs.mkdirSync(path.join(outDir,'data'),{recursive:true});

// Data files
const dataFiles=[
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
const fetchCode=`
let D,PRED,PRED_BLD;
async function loadData(){
  const[dp,pp,pbp]=await Promise.all([
    fetch('data/all_data.json').then(r=>r.json()),
    fetch('data/predictions.json').then(r=>r.json()),
    fetch('data/predictions_by_building.json').then(r=>r.json())
  ]);
  D=dp;PRED=pp;PRED_BLD=pbp;
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
