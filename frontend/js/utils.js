// === 常量與顏色配置 ===
const DC={'澳門低區':'#818cf8','澳門填海A區':'#a78bfa','澳大橫琴區':'#34d399','未分類':'#6b6b80'};
const DMA_MAP={
  '澳門低區':['HIA','PHA','ANEXA','SPA'],
  '澳門填海A區':['THA'],
  '路氹城區':['TA'],
  '澳大橫琴區':['NA']
};
const DMA_COLORS={'澳門低區':'#818cf8','澳門填海A區':'#a78bfa','澳大橫琴區':'#34d399','路氹城區':'#f472b6'};
const DMA_REVERSE={};
for(const[zh,codes]of Object.entries(DMA_MAP)){
  for(const c of codes) DMA_REVERSE[c]=zh;
}
// 修復路氹城區的 Unicode 私用區字符問題：資料中氹=U+EBF3(60403)，正常氹=U+6C39(27705)
function getDmaName(code){
  var name=DMA_REVERSE[code];
  if(!name)return code;
  if(window.D&&D.dma&&D.dma[0]){
    var keys=Object.keys(D.dma[0].dmas);
    for(var i=0;i<keys.length;i++){
      if(keys[i].charCodeAt(1)===0xEBF3&&name.charCodeAt(1)===0x6C39){
        if(keys[i].slice(0,1)===name.slice(0,1)&&keys[i].slice(2)===name.slice(2))return keys[i];
      }
    }
  }
  return name;
}
function getDmaColor(name){
  if(DC[name])return DC[name];
  // 尝试用正常字符查找
  for(var k in DC){
    if(k.charCodeAt(1)===0x6C39&&name.charCodeAt(1)===0xEBF3){
      if(k.slice(0,1)===name.slice(0,1)&&k.slice(2)===name.slice(2))return DC[k];
    }
  }
  return DC['未分類'];
}

// === 全局状态 ===
let _selMeters={},_anomCfg={spikeMult:4,minScore:0.25},_anomCfgOpen=false;
let selDate,selDma='',charts={},selDiffMeter=null;

// === Demo mode: all data is fictional, no password needed ===
let isUnlocked = true;

function mask(text) { return text || ''; }
function maskBuilding(name) { return name || ''; }
function clickMasked() {}
function unlockSensitive() {}

// === 工具函數 ===
function fmt(n){return Math.round(n).toLocaleString()}
function findD(arr,d){return arr.find(x=>x.date===d)}
function esc(s){return String(s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// === ECharts 統一管理 ===
function disposeChart(name){
  if(charts[name]){charts[name].dispose();charts[name]=null;}
}
function initChart(dom,name){
  disposeChart(name);
  charts[name]=echarts.init(dom,'dark');
  return charts[name];
}

// === 圖表 PNG 匯出 ===
function exportChart(name,filename){
  var c=charts[name];
  if(!c)return;
  var url=c.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#0a0a0f'});
  var a=document.createElement('a');a.href=url;a.download=(filename||name)+'.png';a.click();
}

// === CSV 匯出 ===
function exportCsv(data,filename){
  var csv=data.map(function(row){return row.map(function(v){return'"'+String(v).replace(/"/g,'""')+'"'}).join(',')}).join('\n');
  var BOM='﻿';var blob=new Blob([BOM+csv],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=filename;a.click();
}
