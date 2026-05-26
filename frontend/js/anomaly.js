// === 異常檢測頁 ===
function renderAnomaly(){
  var h='<section class="card"><h2>⚠ 異常用水檢測 <span class="hint">(滾動14天視窗基準)</span></h2>';
  h+='<span class="cf-toggle" onclick="_anomCfgOpen=!_anomCfgOpen;renderAnomaly()">'+(_anomCfgOpen?'▼ 隱藏設定':'▶ 過濾設定')+'</span>';
  h+='<div class="cf '+(_anomCfgOpen?'open':'')+'"><div class="cf-inner">';
  h+='<div class="cf-row"><label>暴增倍數</label><input type="range" min="2" max="8" step="0.5" value="'+_anomCfg.spikeMult+'" oninput="_anomCfg.spikeMult=parseFloat(this.value);renderAnomaly()"><span class="val">'+_anomCfg.spikeMult.toFixed(1)+'×</span></div>';
  h+='<div class="cf-row"><label>最小分數</label><input type="range" min="0.1" max="0.8" step="0.05" value="'+_anomCfg.minScore+'" oninput="_anomCfg.minScore=parseFloat(this.value);renderAnomaly()"><span class="val">'+_anomCfg.minScore.toFixed(2)+'</span></div>';
  h+='</div></div>';
  var ts='display:inline-block;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;margin-right:4px;';
  var aOn=ts+'background:#38bdf8;color:#0f172a;font-weight:600;';
  var aOff=ts+'background:#334155;color:#cbd5e1;';
  if(!window._anomType)window._anomType='all';
  h+='<div class="dc" style="margin-bottom:10px">';
  h+='<input type="date" class="di" min="'+D.dates[0]+'" max="'+D.dates[D.dates.length-1]+'" value="'+(window._anomDate||D.dates[D.dates.length-1])+'" onchange="window._anomDate=this.value;renderAnomaly()">';
  h+='<button class="nb" onclick="var d=D.dates,i=d.indexOf(window._anomDate||d[d.length-1]);if(i>0){window._anomDate=d[i-1];renderAnomaly()}">&#9664;</button>';
  h+='<span class="dd">'+(window._anomDate||D.dates[D.dates.length-1])+'</span>';
  h+='<button class="nb" onclick="var d=D.dates,i=d.indexOf(window._anomDate||d[d.length-1]);if(i<d.length-1){window._anomDate=d[i+1];renderAnomaly()}">&#9654;</button>';
  h+='</div>';
  h+='<div style="margin-bottom:10px">';
  h+='<span style="'+(window._anomType==='all'?aOn:aOff)+'" onclick="window._anomType=&quot;all&quot;;renderAnomaly()">全部</span>';
  h+='<span style="'+(window._anomType==='spike'?aOn:aOff)+'" onclick="window._anomType=&quot;spike&quot;;renderAnomaly()">暴增</span>';
  h+='<span style="'+(window._anomType==='drop'?aOn:aOff)+'" onclick="window._anomType=&quot;drop&quot;;renderAnomaly()">暴跌</span>';
  h+='<span style="'+(window._anomType==='zero'?aOn:aOff)+'" onclick="window._anomType=&quot;zero&quot;;renderAnomaly()">歸零</span>';
  h+='<span style="'+(window._anomType==='watch'?aOn:aOff)+'" onclick="window._anomType=&quot;watch&quot;;renderAnomaly()">關注</span>';
  h+='<span style="'+aOff+'margin-left:6px" onclick="exportAnomalyCsv()">💾 匯出CSV</span>';
  h+='</div>';
  var byType={'spike':0,'drop':0,'zero':0,'watch':0};
  D.anomalies.forEach(function(a){if(byType.hasOwnProperty(a.type))byType[a.type]++;});
  h+='<p style="color:#64748b;font-size:11px;margin-bottom:8px">暴增'+byType.spike+' | 暴跌'+byType.drop+' | 歸零'+byType.zero+' | 關注'+byType.watch+' (共'+D.anomalies.length+'條)</p>';
  var dateFilter=window._anomDate;
  var filtered=dateFilter?D.anomalies.filter(function(a){return a.date===dateFilter}):D.anomalies.slice(0,200);
  if(window._anomType!=='all')filtered=filtered.filter(function(a){return a.type===window._anomType;});
  filtered=filtered.filter(function(a){return a.anomalyScore>=_anomCfg.minScore;});
  if(_anomCfg.spikeMult<4)filtered=filtered.filter(function(a){return a.type!=='spike'||a.total/a.pastMean>=_anomCfg.spikeMult;});
  if(filtered.length){
    h+='<table><thead><tr><th>日期</th><th>類型</th><th>表位編號</th><th>建築物</th><th>DMA</th><th class="num">當日</th><th class="num">14天均值</th><th class="num">分數</th><th>原因</th></tr></thead><tbody>';
    filtered.forEach(function(a){
      var tc2={'spike':'#f87171','drop':'#fb923c','zero':'#a78bfa','watch':'#fbbf24'};
      var tn={'spike':'暴增','drop':'暴跌','zero':'歸零','watch':'關注'};
      h+='<tr class="warn" style="cursor:pointer" onclick="window._anomTarget={meterId:'+JSON.stringify(esc(a.meterId)).replace(/"/g,'&quot;')+',contractId:'+JSON.stringify(mask(a.contractId||a.meterId)).replace(/"/g,'&quot;')+',anomalyDate:'+JSON.stringify(a.date).replace(/"/g,'&quot;')+',anomalyType:'+JSON.stringify(a.type).replace(/"/g,'&quot;')+'};showAnomCurve()">';
      h+='<td>'+a.date+'</td>';
      h+='<td><span class="tag" style="background:'+(tc2[a.type]||'#666')+'">'+tn[a.type]+'</span></td>';
      h+='<td>'+esc(a.meterId)+'</td>';
      h+='<td class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(a.buildingName)+'</td>';
      h+='<td><span class="tag" style="background:'+(DC[a.dma]||'#666')+'">'+esc(a.dma)+'</span></td>';
      h+='<td class="num">'+fmt(a.total)+'</td>';
      h+='<td class="num">'+(a.pastMean?fmt(a.pastMean):'-')+'</td>';
      h+='<td class="num '+(a.anomalyScore>=0.7?'neg':'')+'">'+(a.anomalyScore!=null?a.anomalyScore.toFixed(2):'-')+'</td>';
      h+='<td style="font-size:11px">'+a.reason+'</td></tr>';
    });
    h+='</tbody></table>';
    if(!dateFilter)h+='<p style="color:#64748b;font-size:11px;margin-top:8px">顯示最近200條 · 選擇日期查看單日全部</p>';
    else h+='<p style="color:#64748b;font-size:11px;margin-top:8px">'+filtered.length+'條 - '+dateFilter+'</p>';
  }else{
    h+='<p style="color:#64748b">'+(dateFilter?dateFilter+' 無異常':'無異常')+'</p>';
  }
  h+='<span class="cf-toggle" style="margin-top:12px" onclick="var s=this.nextElementSibling;s.style.maxHeight=s.style.maxHeight?\'\':\'300px\';setTimeout(function(){Object.values(charts).forEach(function(c){if(c)c.resize()})},350)">▶ 異常統計分析</span>';
  h+='<div style="max-height:0;overflow:hidden;transition:max-height .3s"><div class="cf-inner" style="margin-top:8px"><div style="display:flex;gap:12px;flex-wrap:wrap">';
  h+='<div id="anomStatsDMA" class="chart" style="height:200px;flex:1;min-width:200px"></div>';
  h+='<div id="anomStatsMonth" class="chart" style="height:200px;flex:1;min-width:200px"></div>';
  h+='<div id="anomStatsType" class="chart" style="height:200px;flex:1;min-width:180px"></div></div>';
  var anomFreq={};D.anomalies.forEach(function(a){anomFreq[a.meterId]=(anomFreq[a.meterId]||0)+1});
  var freqList=Object.keys(anomFreq).sort(function(a,b){return anomFreq[b]-anomFreq[a]}).slice(0,10);
  h+='<div style="margin-top:10px"><span style="font-size:11px;color:var(--muted)">異常頻發水表 Top10: </span>';
  freqList.forEach(function(id,i){h+='<span style="font-size:11px;color:var(--text);margin-right:8px">'+id+' ('+anomFreq[id]+')次</span>'});
  h+='</div></div></div>';

  // 異常統計概覽卡片
  var uniqueMeters={};
  D.anomalies.forEach(function(a){uniqueMeters[a.meterId]=1;});
  h+='<div class="kpi-grid" style="margin-top:12px">';
  h+='<div class="kpi"><div class="label">總異常數</div><div class="value">'+D.anomalies.length+'</div><div class="sub">條</div></div>';
  h+='<div class="kpi"><div class="label">涉及水表</div><div class="value">'+Object.keys(uniqueMeters).length+'</div><div class="sub">個</div></div>';
  h+='<div class="kpi"><div class="label">暴增</div><div class="value" style="color:#f87171">'+byType.spike+'</div><div class="sub">條</div></div>';
  h+='<div class="kpi"><div class="label">暴跌</div><div class="value" style="color:#fb923c">'+byType.drop+'</div><div class="sub">條</div></div>';
  h+='<div class="kpi"><div class="label">歸零</div><div class="value" style="color:#facc15">'+byType.zero+'</div><div class="sub">條</div></div>';
  h+='<div class="kpi"><div class="label">關注</div><div class="value" style="color:#818cf8">'+byType.watch+'</div><div class="sub">條</div></div>';
  h+='</div>';

  // 趨勢分析可摺疊區域
  h+='<span class="cf-toggle" style="margin-top:12px" onclick="var s=this.nextElementSibling;s.style.maxHeight=s.style.maxHeight?\'\':\'500px\';setTimeout(function(){if(!window._anomTrendInited){drawAnomTrendChart(\'daily\');window._anomTrendInited=true;}Object.values(charts).forEach(function(c){if(c)c.resize()})},350)">▶ 異常趨勢分析</span>';
  h+='<div style="max-height:0;overflow:hidden;transition:max-height .3s"><div style="margin-top:8px">';
  h+='<div class="ms" style="margin-bottom:6px"><button class="mb active" onclick="drawAnomTrendChart(\'daily\',this)">每日異常數</button><button class="mb" onclick="drawAnomTrendChart(\'type\',this)">按類型分布</button><button class="mb" onclick="drawAnomTrendChart(\'score\',this)">評分分布</button><button class="mb" onclick="drawAnomTrendChart(\'weekday\',this)">週幾分布</button></div>';
  h+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'anomTrend\',\'異常趨勢\')">匯出 PNG</button></div>';
  h+='<div id="anomTrendChart" class="chart" style="height:350px"></div>';
  h+='</div></div>';

  h+='<div id="anomOverlay" class="ov" style="display:none"><div class="ov-bg" onclick="closeAnomOverlay()"></div><div class="ov-box"><span class="ov-close" onclick="closeAnomOverlay()">✕</span><span id="anomOverlayTitle" style="font-weight:600;color:var(--text);margin-bottom:8px;display:block"></span><div class="anom-nav"><button id="anomPrevBtn" onclick="navAnomDate(-1)">◀ 上一條</button><span style="font-size:11px;color:var(--muted)" id="anomNavInfo"></span><button id="anomNextBtn" onclick="navAnomDate(1)">下一條 ▶</button></div><div id="anomCurve" style="width:100%;height:320px"></div></div></div>';
  h+='</section>';
  document.getElementById('page-anomaly').innerHTML=h;
  if(!window._anomDate)window._anomDate=D.dates[D.dates.length-1];
  setTimeout(function(){renderAnomStats();},100);
}

function renderAnomStats(){
  var anoms=D.anomalies;
  var dmaDist={};anoms.forEach(function(a){var d=a.dma||'未分類';dmaDist[d]=(dmaDist[d]||0)+1});
  var dmaPie=Object.keys(dmaDist).map(function(k){return{name:k,value:dmaDist[k]}});
  disposeChart('ad');
  var cAd=initChart(document.getElementById('anomStatsDMA'),'ad');
  cAd.setOption({backgroundColor:'transparent',title:{text:'異常 DMA 分布',textStyle:{color:'var(--muted)',fontSize:12},left:'center'},tooltip:{trigger:'item'},series:[{type:'pie',radius:'60%',data:dmaPie,label:{fontSize:10},itemStyle:{borderColor:'var(--bg)',borderWidth:1}}]});
  var monthDist={};anoms.forEach(function(a){var m=a.date.slice(0,7);monthDist[m]=(monthDist[m]||0)+1});
  var months=Object.keys(monthDist).sort();
  var monthVals=months.map(function(m){return monthDist[m]});
  disposeChart('am');
  var cAm=initChart(document.getElementById('anomStatsMonth'),'am');
  cAm.setOption({backgroundColor:'transparent',title:{text:'異常月份趨勢',textStyle:{color:'var(--muted)',fontSize:12},left:'center'},grid:{left:40,right:10,top:30,bottom:30},xAxis:{type:'category',data:months,axisLabel:{rotate:45,fontSize:9}},yAxis:{type:'value'},series:[{type:'bar',data:monthVals,itemStyle:{color:'#818cf8',borderRadius:[3,3,0,0]}}]});
  var types={spike:0,drop:0,zero:0,watch:0};anoms.forEach(function(a){if(types.hasOwnProperty(a.type))types[a.type]++});
  var typePie=[{name:'暴增',value:types.spike,itemStyle:{color:'#f87171'}},{name:'暴跌',value:types.drop,itemStyle:{color:'#fb923c'}},{name:'歸零',value:types.zero,itemStyle:{color:'#a78bfa'}},{name:'關注',value:types.watch,itemStyle:{color:'#fbbf24'}}];
  disposeChart('at');
  var cAt=initChart(document.getElementById('anomStatsType'),'at');
  cAt.setOption({backgroundColor:'transparent',title:{text:'異常類型分布',textStyle:{color:'var(--muted)',fontSize:12},left:'center'},tooltip:{trigger:'item'},series:[{type:'pie',radius:['40%','65%'],data:typePie,label:{fontSize:10,formatter:'{b}: {c}'},itemStyle:{borderColor:'var(--bg)',borderWidth:1}}]});
}

function exportAnomalyCsv(){
  var anoms=D.anomalies;
  if(window._anomType&&window._anomType!=='all')anoms=anoms.filter(function(a){return a.type===window._anomType});
  var rows=[['日期','類型','水表ID','建築物','DMA','當日','14天均值','分數','原因']];
  anoms.forEach(function(a){rows.push([a.date,a.type,a.meterId,a.buildingName||'',a.dma||'',a.total,a.pastMean||'',a.anomalyScore!=null?a.anomalyScore.toFixed(3):'',a.reason||''])});
  exportCsv(rows,'anomalies.csv');
}

function showAnomCurve(){
  var t=window._anomTarget;if(!t)return;
  var meterId=t.meterId,contractId=t.contractId,anomalyDate=t.anomalyDate,anomalyType=t.anomalyType||'spike';
  var md=D.meterDaily[meterId];
  if(!md){alert('無歷史資料');return;}
  var ad=new Date(anomalyDate);
  var rangeDates=[],rangeVals=[];
  for(var i=-14;i<=7;i++){var d=new Date(ad);d.setDate(ad.getDate()+i);var ds=d.toISOString().slice(0,10);rangeDates.push(ds);rangeVals.push(md.hasOwnProperty(ds)?md[ds]:null);}
  var firstData=-1,lastData=-1;
  for(var i=0;i<rangeVals.length;i++){if(rangeVals[i]!==null){if(firstData===-1)firstData=i;lastData=i;}}
  if(firstData===-1){alert('無歷史資料');return;}
  rangeDates=rangeDates.slice(firstData,lastData+1);
  rangeVals=rangeVals.slice(firstData,lastData+1);
  var validVals=rangeVals.filter(function(v){return v!==null});
  var avg=validVals.reduce(function(s,v){return s+v},0)/validVals.length;
  var anomalyIdx=rangeDates.indexOf(anomalyDate);
  document.getElementById('anomOverlayTitle').textContent='表位:'+(contractId||meterId)+' | 異常日:'+anomalyDate+' | 視窗均值:'+avg.toFixed(0)+'m³';
  document.getElementById('anomOverlay').style.display='flex';
  window._anomNavList=D.anomalies.filter(function(a){return a.meterId===meterId;}).map(function(a){return a.date;}).sort();
  var navIdx=window._anomNavList.indexOf(anomalyDate);
  document.getElementById('anomNavInfo').textContent=(navIdx+1)+'/'+window._anomNavList.length;
  document.getElementById('anomPrevBtn').disabled=navIdx<=0;
  document.getElementById('anomNextBtn').disabled=navIdx>=window._anomNavList.length-1;
  window._anomNavIdx=navIdx;
  window._anomNavMeter=meterId;
  disposeChart('anomC');
  var c=initChart(document.getElementById('anomCurve'),'anomC');
  c.setOption({tooltip:{trigger:'axis'},grid:{left:60,right:20,top:20,bottom:40},xAxis:{type:'category',data:rangeDates,axisLabel:{rotate:45,fontSize:10}},yAxis:{type:'value'},series:[{type:'line',data:rangeVals,connectNulls:false,smooth:false,symbol:'circle',symbolSize:6,areaStyle:{opacity:0.08},markLine:{silent:true,data:[{yAxis:avg,name:'均值',label:{formatter:'{c}m³'}}],lineStyle:{color:'#fbbf24',type:'dashed'}},markPoint:{silent:true,symbol:'pin',symbolSize:40,data:anomalyIdx>=0?[{name:anomalyDate,coord:[anomalyIdx,rangeVals[anomalyIdx]],itemStyle:{color:anomalyType==='spike'?'#ef4444':anomalyType==='drop'?'#f97316':anomalyType==='zero'?'#8b5cf6':'#eab308'},label:{show:true,formatter:anomalyDate+'\n'+rangeVals[anomalyIdx].toFixed(0)+'m³',color:'#fff',fontSize:11,fontWeight:'bold',position:'top',distance:8}}]:[],animation:false}}]});
}

function navAnomDate(dir){
  var list=window._anomNavList;if(!list||!list.length)return;
  var newIdx=window._anomNavIdx+dir;
  if(newIdx<0||newIdx>=list.length)return;
  var a=D.anomalies.find(function(x){return x.meterId===window._anomNavMeter&&x.date===list[newIdx];});
  if(a){window._anomTarget={meterId:a.meterId,contractId:a.contractId||a.meterId,anomalyDate:a.date,anomalyType:a.type};showAnomCurve();}
}

function closeAnomOverlay(){
  document.getElementById('anomOverlay').style.display='none';
  disposeChart('anomC');
}

function drawAnomTrendChart(view,btn){
  if(btn){
    document.querySelectorAll('#page-anomaly .ms .mb').forEach(function(b){b.classList.remove('active')});
    btn.classList.add('active');
  }
  disposeChart('anomTrend');
  var el=document.getElementById('anomTrendChart');
  if(!el)return;
  var c=initChart(el,'anomTrend');

  if(view==='daily'){
    var dateMap={};
    D.anomalies.forEach(function(a){dateMap[a.date]=(dateMap[a.date]||0)+1;});
    var dates=D.dates.slice();
    var counts=dates.map(function(d){return dateMap[d]||0});
    var ma=[];
    for(var i=0;i<counts.length;i++){
      if(i<6){ma.push(null);continue;}
      var s=0;for(var j=i-6;j<=i;j++)s+=counts[j];
      ma.push(Math.round(s/7*10)/10);
    }
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
      legend:{data:['每日異常數','7天均值'],textStyle:{color:'#94a3b8'}},
      grid:{left:60,right:40,top:40,bottom:30},
      xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45}},
      yAxis:{type:'value',name:'異常數'},
      series:[
        {name:'每日異常數',type:'bar',data:counts,itemStyle:{color:'rgba(248,113,113,0.6)'},barMaxWidth:8},
        {name:'7天均值',type:'line',data:ma,smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2},showSymbol:false}
      ]});
  }
  else if(view==='type'){
    var types=['spike','drop','zero','watch'];
    var colors=['#f87171','#fb923c','#facc15','#818cf8'];
    var dateMap={};
    D.anomalies.forEach(function(a){
      if(!dateMap[a.date])dateMap[a.date]={};
      dateMap[a.date][a.type]=(dateMap[a.date][a.type]||0)+1;
    });
    var dates=D.dates.slice();
    var series=types.map(function(type,idx){
      return{
        name:type,type:'bar',stack:'total',
        data:dates.map(function(d){return dateMap[d]&&dateMap[d][type]?dateMap[d][type]:0}),
        itemStyle:{color:colors[idx]}
      };
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      legend:{data:types,textStyle:{color:'#94a3b8'}},
      grid:{left:60,right:40,top:40,bottom:30},
      xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45}},
      yAxis:{type:'value',name:'異常數'},
      series:series});
  }
  else if(view==='score'){
    var scoreRanges=['0-0.1','0.1-0.2','0.2-0.3','0.3-0.4','0.4-0.5','0.5-0.6','0.6-0.7','0.7-0.8','0.8-0.9','0.9-1.0'];
    var scoreCounts=new Array(10).fill(0);
    D.anomalies.forEach(function(a){
      var idx=Math.min(Math.floor(a.anomalyScore*10),9);
      scoreCounts[idx]++;
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
      grid:{left:60,right:40,top:40,bottom:30},
      xAxis:{type:'category',data:scoreRanges,axisLabel:{fontSize:10}},
      yAxis:{type:'value',name:'異常數'},
      series:[{type:'bar',data:scoreCounts,itemStyle:{color:function(p){
        var clrs=['#34d399','#a78bfa','#818cf8','#f472b6','#fb923c','#f87171','#ef4444','#dc2626','#b91c1c','#991b1b'];
        return clrs[p.dataIndex];
      }},barWidth:'60%'}]});
  }
  else if(view==='weekday'){
    var weekDays=['週日','週一','週二','週三','週四','週五','週六'];
    var dayCounts=new Array(7).fill(0);
    D.anomalies.forEach(function(a){
      var d=new Date(a.date);
      dayCounts[d.getDay()]++;
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',formatter:function(p){return weekDays[p[0].dataIndex]+': '+p[0].value+' 條異常';}},
      grid:{left:80,right:40,top:20,bottom:30},
      xAxis:{type:'category',data:weekDays},
      yAxis:{type:'value',name:'異常數'},
      series:[{type:'bar',data:dayCounts,itemStyle:{color:function(p){
        var max=Math.max.apply(null,dayCounts);
        var ratio=max>0?p.value/max:0;
        return 'rgba(248,113,113,'+(0.3+ratio*0.7)+')';
      }},barWidth:'50%'}]});
  }
}
