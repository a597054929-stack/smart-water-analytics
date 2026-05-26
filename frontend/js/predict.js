// === 預測頁 ===
var _predView='building';

function renderPredict(){
  if(!PRED||!PRED.predictions||!PRED.predictions.length){
    document.getElementById('page-predict').innerHTML='<section class="card"><p style="color:#64748b">暫無預測資料</p></section>';
    return;
  }
  var h='<section class="card"><h2>🔮 用水預測</h2>';
  h+='<div class="ms" style="margin-bottom:16px">';
  h+='<button class="mb '+(_predView==='building'?'active':'')+'" onclick="_predView=\'building\';renderPredict()">🏢 按建築物（路氹城區）</button>';
  h+='<button class="mb '+(_predView==='meter'?'active':'')+'" onclick="_predView=\'meter\';renderPredict()">💧 按水表（Top50）</button>';
  h+='</div>';
  if(_predView==='building'){h+=renderBuildingPrediction();}else{h+=renderMeterPrediction();}
  h+='</section>';
  if(!document.getElementById('predictDlg')){
    var dlg=document.createElement('dialog');
    dlg.id='predictDlg';
    dlg.style.cssText='background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:12px;padding:16px;width:90vw;max-width:800px;';
    dlg.innerHTML='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span id="predictDlgTitle" style="font-weight:bold"></span><button id="predictDlgClose" style="background:none;border:none;color:#94a3b8;font-size:20px;cursor:pointer">✕</button></div><div id="predictDlgChart" style="width:100%;height:400px"></div><div id="predictDlgTable" style="margin-top:12px"></div>';
    document.body.appendChild(dlg);
    document.getElementById('predictDlgClose').onclick=function(){dlg.close();};
    dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close();});
  }
  document.getElementById('page-predict').innerHTML=h;
}

function renderBuildingPrediction(){
  if(!PRED_BLD||!PRED_BLD.predictions||!PRED_BLD.predictions.length){return '<p style="color:#64748b">暫無建築物預測資料</p>';}
  var h='<p class="hint" style="margin-bottom:12px">基於線性迴歸模型 · DMA: '+esc(PRED_BLD.dma)+'</p>';
  h+='<p class="hint" style="margin-bottom:12px">歷史資料: '+PRED_BLD.historicalRange.start+' ~ '+PRED_BLD.historicalRange.end+' ('+PRED_BLD.historicalRange.days+'天) · 生成時間: '+PRED_BLD.generatedAt+'</p>';
  h+='<input type="text" class="si2" placeholder="輸入建築物名稱搜尋..." oninput="filterBuildingPredict(this.value)">';
  var upCount=PRED_BLD.predictions.filter(function(p){return p.trend==='up'}).length;
  var downCount=PRED_BLD.predictions.filter(function(p){return p.trend==='down'}).length;
  h+='<div class="sr" style="margin-bottom:16px"><div class="si"><div class="sl">總建築數</div><div class="sv">'+PRED_BLD.totalBuildings+'</div></div><div class="si res"><div class="sl">📈 上升趨勢</div><div class="sv">'+upCount+'</div></div><div class="si nonres"><div class="sl">📉 下降趨勢</div><div class="sv">'+downCount+'</div></div></div>';
  h+='<div id="buildingPredictList">'+renderBuildingList(PRED_BLD.predictions)+'</div>';
  return h;
}

function renderBuildingList(predictions){
  var h='<table><thead><tr><th>#</th><th>建築物</th><th>物業類型</th><th class="num">水表數</th><th class="num">歷史均值</th><th class="num">預測均值</th><th class="num">模型分</th><th>趨勢</th><th></th></tr></thead><tbody>';
  predictions.forEach(function(p,i){
    var avgPred=p.predictions.reduce(function(s,v){return s+v.value},0)/p.predictions.length;
    var trendColor=p.trend==='up'?'#34d399':'#ef4444';
    var trendIcon=p.trend==='up'?'↑':'↓';
    h+='<tr><td>'+(i+1)+'</td><td class="contract">'+esc(p.building)+'</td><td><span class="ptag '+(p.propertyType.indexOf('001:')===0?'res':'')+'">'+esc(p.propertyType)+'</span></td><td class="num">'+p.meterCount+'</td><td class="num">'+fmt(p.avgHistorical)+'</td><td class="num">'+fmt(avgPred)+'</td><td class="num">'+p.modelScore.toFixed(2)+'</td><td style="color:'+trendColor+';font-weight:600">'+trendIcon+' '+p.trend+'</td><td><button class="nb" onclick="showBuildingDetail(\''+esc(p.building)+'\')">查看</button></td></tr>';
  });
  h+='</tbody></table>';
  return h;
}

function filterBuildingPredict(q){
  if(q.length<1){document.getElementById('buildingPredictList').innerHTML=renderBuildingList(PRED_BLD.predictions);return;}
  var ql=q.toLowerCase();
  var filtered=PRED_BLD.predictions.filter(function(p){return p.building.toLowerCase().includes(ql);});
  document.getElementById('buildingPredictList').innerHTML=renderBuildingList(filtered);
}

function showBuildingDetail(building){
  var pred=PRED_BLD.predictions.find(function(p){return p.building===building});
  if(!pred)return;
  var dlg=document.getElementById('predictDlg');
  document.getElementById('predictDlgTitle').textContent='🏢 '+pred.building+' 預測詳情';
  if(dlg.open)dlg.close();
  dlg.showModal();
  setTimeout(function(){
    var fittedDates=pred.fitted.map(function(f){return f.date});
    var fittedVals=pred.fitted.map(function(f){return f.fitted});
    var actualVals=pred.fitted.map(function(f){return f.actual});
    var predDates=pred.predictions.map(function(p){return p.date});
    var predVals=pred.predictions.map(function(p){return p.value});
    var allDates=fittedDates.concat(predDates);
    var allActual=actualVals.concat(predDates.map(function(){return null}));
    var allFitted=fittedVals.concat(predDates.map(function(){return null}));
    var allPred=new Array(fittedDates.length).fill(null).concat(predVals);
    disposeChart('pdc');
    var c=initChart(document.getElementById('predictDlgChart'),'pdc');
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:['實際用水','模型擬合','7天預測'],textStyle:{color:'#94a3b8'}},grid:{left:60,right:40,top:40,bottom:30},xAxis:{type:'category',data:allDates,axisLabel:{fontSize:9,rotate:45}},yAxis:{type:'value',name:'m³'},series:[{name:'實際用水',type:'bar',data:allActual,itemStyle:{color:'rgba(56,189,248,0.6)'},barMaxWidth:6},{name:'模型擬合',type:'line',data:allFitted,smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2},showSymbol:false},{name:'7天預測',type:'line',data:allPred,itemStyle:{color:'#f472b6'},lineStyle:{type:'dashed',width:3},symbol:'circle',symbolSize:8}]});
    var tableH='<table style="margin-top:12px"><thead><tr><th>日期</th><th>類型</th><th class="num">實際值</th><th class="num">擬合/預測值</th><th class="num">誤差</th></tr></thead><tbody>';
    pred.fitted.forEach(function(f){var err=f.actual>0?((f.fitted-f.actual)/f.actual*100).toFixed(1):0;var cls=parseFloat(err)>0?'neg':'up';tableH+='<tr><td>'+f.date+'</td><td><span class="tag" style="background:#fbbf24">擬合</span></td><td class="num">'+fmt(f.actual)+'</td><td class="num">'+fmt(f.fitted)+'</td><td class="num '+cls+'">'+err+'%</td></tr>';});
    pred.predictions.forEach(function(p){tableH+='<tr><td>'+p.date+'</td><td><span class="tag" style="background:#f472b6">預測</span></td><td class="num">-</td><td class="num">'+fmt(p.value)+'</td><td class="num">-</td></tr>';});
    tableH+='</tbody></table>';
    document.getElementById('predictDlgTable').innerHTML=tableH;
  },50);
}

function renderMeterPrediction(){
  if(!PRED||!PRED.predictions||!PRED.predictions.length){return '<p style="color:#64748b">暫無水表預測資料</p>';}
  var h='<p class="hint" style="margin-bottom:12px">基於線性迴歸模型 · 歷史資料: '+PRED.historicalRange.start+' ~ '+PRED.historicalRange.end+' ('+PRED.historicalRange.days+'天)</p>';
  h+='<p class="hint" style="margin-bottom:12px">生成時間: '+PRED.generatedAt+'</p>';
  h+='<input type="text" class="si2" placeholder="輸入水表編號搜尋..." oninput="filterPredict(this.value)">';
  var upCount=PRED.predictions.filter(function(p){return p.trend==='up'}).length;
  var downCount=PRED.predictions.filter(function(p){return p.trend==='down'}).length;
  h+='<div class="sr" style="margin-bottom:16px"><div class="si"><div class="sl">總水表數</div><div class="sv">'+PRED.totalMeters+'</div></div><div class="si res"><div class="sl">📈 上升趨勢</div><div class="sv">'+upCount+'</div></div><div class="si nonres"><div class="sl">📉 下降趨勢</div><div class="sv">'+downCount+'</div></div></div>';
  h+='<div id="predictList">'+renderPredictList(PRED.predictions)+'</div>';
  return h;
}

function renderPredictList(predictions){
  var h='<table><thead><tr><th>#</th><th>水表編號</th><th>DMA</th><th>物業類型</th><th>建築物</th><th class="num">歷史均值</th><th class="num">預測均值</th><th class="num">模型分</th><th>趨勢</th><th></th></tr></thead><tbody>';
  predictions.forEach(function(p,i){
    var avgPred=p.predictions.reduce(function(s,v){return s+v.value},0)/p.predictions.length;
    var trendColor=p.trend==='up'?'#34d399':'#ef4444';
    var trendIcon=p.trend==='up'?'↑':'↓';
    h+='<tr><td>'+(i+1)+'</td><td class="contract">'+esc(p.meterId)+'</td><td><span class="tag" style="background:'+(DC[p.info.dma]||'#666')+'">'+esc(p.info.dma)+'</span></td><td><span class="ptag '+(p.info.propertyType.indexOf('001:')===0?'res':'')+'">'+esc(p.info.propertyType)+'</span></td><td style="font-size:11px" class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(p.info.buildingName)+'</td><td class="num">'+fmt(p.avgHistorical)+'</td><td class="num">'+fmt(avgPred)+'</td><td class="num">'+p.modelScore.toFixed(2)+'</td><td style="color:'+trendColor+';font-weight:600">'+trendIcon+' '+p.trend+'</td><td><button class="nb" onclick="showPredictDetail(\''+esc(p.meterId)+'\')">查看</button></td></tr>';
  });
  h+='</tbody></table>';
  return h;
}

function filterPredict(q){
  if(q.length<1){document.getElementById('predictList').innerHTML=renderPredictList(PRED.predictions);return;}
  var ql=q.toLowerCase();
  var filtered=PRED.predictions.filter(function(p){return p.meterId.toLowerCase().includes(ql)||(p.info.buildingName||'').toLowerCase().includes(ql)||(p.info.contractId||'').toLowerCase().includes(ql);});
  document.getElementById('predictList').innerHTML=renderPredictList(filtered);
}

function showPredictDetail(meterId){
  var pred=PRED.predictions.find(function(p){return p.meterId===meterId});
  if(!pred)return;
  var dlg=document.getElementById('predictDlg');
  document.getElementById('predictDlgTitle').textContent='📊 '+pred.meterId+' 預測詳情';
  if(dlg.open)dlg.close();
  dlg.showModal();
  setTimeout(function(){
    var allDates=[],allActual=[],allFitted=[],allPred=[];
    if(pred.fitted){pred.fitted.forEach(function(f){allDates.push(f.date);allActual.push(f.actual);allFitted.push(f.fitted);allPred.push(null);});}
    pred.predictions.forEach(function(p){allDates.push(p.date);allActual.push(null);allFitted.push(null);allPred.push(p.value);});
    disposeChart('pdc');
    var c=initChart(document.getElementById('predictDlgChart'),'pdc');
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:['實際用水','模型擬合','7天預測'],textStyle:{color:'#94a3b8'}},grid:{left:60,right:40,top:40,bottom:30},xAxis:{type:'category',data:allDates,axisLabel:{fontSize:9,rotate:45}},yAxis:{type:'value',name:'m³'},series:[{name:'實際用水',type:'bar',data:allActual,itemStyle:{color:'rgba(56,189,248,0.6)'},barMaxWidth:6},{name:'模型擬合',type:'line',data:allFitted,smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2},showSymbol:false},{name:'7天預測',type:'line',data:allPred,itemStyle:{color:'#f472b6'},lineStyle:{type:'dashed',width:3},symbol:'circle',symbolSize:8}]});
    var tableH='<table style="margin-top:12px"><thead><tr><th>日期</th><th>類型</th><th class="num">實際值</th><th class="num">擬合/預測值</th><th class="num">誤差</th></tr></thead><tbody>';
    if(pred.fitted){pred.fitted.forEach(function(f){var err=f.actual>0?((f.fitted-f.actual)/f.actual*100).toFixed(1):0;var cls=parseFloat(err)>0?'neg':'up';tableH+='<tr><td>'+f.date+'</td><td><span class="tag" style="background:#fbbf24">擬合</span></td><td class="num">'+fmt(f.actual)+'</td><td class="num">'+fmt(f.fitted)+'</td><td class="num '+cls+'">'+err+'%</td></tr>';});}
    pred.predictions.forEach(function(p){tableH+='<tr><td>'+p.date+'</td><td><span class="tag" style="background:#f472b6">預測</span></td><td class="num">-</td><td class="num">'+fmt(p.value)+'</td><td class="num">-</td></tr>';});
    tableH+='</tbody></table>';
    document.getElementById('predictDlgTable').innerHTML=tableH;
  },50);
}
