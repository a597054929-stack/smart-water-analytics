// === KPI 計算 ===
function renderKPI(){
  var dma=findD(D.dma,selDate);
  if(!dma)return '';
  var dateIdx=D.dates.indexOf(selDate);
  var prevDma=dateIdx>0?findD(D.dma,D.dates[dateIdx-1]):null;

  // 總用水量
  var totalToday=0,totalPrev=0,totalRes=0,totalNonRes=0,resCnt=0,nonResCnt=0;
  for(var k in dma.dmas){
    var v=dma.dmas[k];
    if(k==='未分類')continue;
    totalToday+=v.total;totalRes+=v.residential;totalNonRes+=v.nonResidential;
    resCnt+=v.resCount;nonResCnt+=v.nonResCount;
  }
  if(prevDma)for(var k in prevDma.dmas){if(k!=='未分類')totalPrev+=prevDma.dmas[k].total;}

  // 環比變化
  var changePct=totalPrev>0?((totalToday-totalPrev)/totalPrev*100).toFixed(1):null;
  var changeClass=changePct>0?'up':'down';
  var changeIcon=changePct>0?'↑':'↓';

  // NRW率（最新月份）
  var nrwPct='-';
  if(D.diff&&D.diff.length){
    var lastMonth=D.diff[D.diff.length-1];
    var mt=0,st=0;
    lastMonth.diffs.forEach(function(m){mt+=m.mainMonthTotal;st+=m.subMonthTotal;});
    nrwPct=mt>0?((mt-st)/mt*100).toFixed(1)+'%':'-';
  }

  // 今日異常數
  var anomToday=D.anomalies.filter(function(a){return a.date===selDate;}).length;

  // 住宅占比
  var resPct=totalToday>0?(totalRes/totalToday*100).toFixed(1):0;

  var nrwSub=D.diff&&D.diff.length?D.diff[D.diff.length-1].month:'';
  return '<div class="kpi-grid">'
    +'<div class="kpi"><div class="label">今日總用水</div><div class="value">'+fmt(totalToday)+'</div><div class="sub">m³</div>'+(changePct!==null?'<div class="change '+changeClass+'">'+changeIcon+Math.abs(changePct)+'% 較昨日</div>':'')+'</div>'
    +'<div class="kpi"><div class="label">NRW率</div><div class="value">'+nrwPct+'</div><div class="sub">'+nrwSub+'</div></div>'
    +'<div class="kpi"><div class="label">住宅占比</div><div class="value">'+resPct+'%</div><div class="sub">'+fmt(totalRes)+' m³</div></div>'
    +'<div class="kpi"><div class="label">今日異常</div><div class="value" style="'+(anomToday>0?'color:var(--red)':'')+'">'+anomToday+'</div><div class="sub">條告警</div></div>'
    +'<div class="kpi"><div class="label">降雨量</div><div class="value">'+(dma.rain||0)+'</div><div class="sub">mm</div></div>'
    +'</div>';
}

// === 首頁概覽 ===
function renderHome(){
  var dma=findD(D.dma,selDate),top=findD(D.top20,selDate),rain=dma?dma.rain||0:0;
  var h='<section class="card"><h2>📅 選擇日期</h2><div class="dc"><input type="date" class="di" min="'+D.dates[0]+'" max="'+D.dates[D.dates.length-1]+'" value="'+selDate+'" onchange="pickDate(this.value)"><div class="dn"><button class="nb" onclick="changeDate(-1)" '+(D.dates.indexOf(selDate)<=0?'disabled':'')+'>◀ 前一天</button><span class="dd">'+selDate+(rain?' 🌧️'+rain+'mm':'')+'</span><button class="nb" onclick="changeDate(1)" '+(D.dates.indexOf(selDate)>=D.dates.length-1?'disabled':'')+'>後一天 ▶</button></div><div class="qd"><button class="qb" onclick="pickDate(D.dates[D.dates.length-1])">最新</button><button class="qb" onclick="pickDate(D.dates[0])">最早</button></div></div></section>';
  h+=renderKPI();
  h+='<section class="card"><h2>🏚️ DMA分區概覽 <span class="hint">（點擊進入詳情）</span></h2><div class="dg">';
  if(dma)for(var k in dma.dmas){var v=dma.dmas[k];var ds=calcDmaStats(k);h+='<div class="dc2" style="border-left-color:'+(DC[k]||'#666')+'" onclick="pickDma(\''+esc(k)+'\')"><div class="dn2">'+esc(k)+' →</div><div class="dv">'+fmt(v.total)+' m³</div><div class="ds"><span>🏠 住宅: '+fmt(v.residential)+' m³ ('+v.resCount+'表)</span><span>🏢 非住宅: '+fmt(v.nonResidential)+' m³ ('+v.nonResCount+'表)</span><span>📊 日均: '+fmt(ds.avgDaily)+' m³</span><span>⚠ 異常: '+ds.anomalyCount+'條</span><span>💧 NRW: '+ds.nrwPct+'</span></div></div>';}
  h+='</div></section>';

  // DMA 對比分析
  var dmaNames2=D.dma.length?Object.keys(D.dma[0].dmas).filter(function(k2){return k2!=='未分類'}):[];
  h+='<section class="card"><h2>📊 DMA 對比分析</h2>';
  h+='<div class="ms" style="margin-bottom:6px"><button class="mb active" onclick="drawDmaCompare(\'trend\',this)">用水趨勢</button><button class="mb" onclick="drawDmaCompare(\'nrw\',this)">NRW 對比</button><button class="mb" onclick="drawDmaCompare(\'anomaly\',this)">異常分布</button><button class="mb" onclick="drawDmaCompare(\'residential\',this)">住宅/非住宅</button></div>';
  h+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'dmaCompare\',\'DMA對比\')">匯出 PNG</button></div>';
  h+='<div id="dmaCompareChart" class="chart" style="height:400px"></div></section>';
  h+='<section class="card"><h2>📊 全域 Top 50</h2><div class="chart-actions"><button class="export-btn" onclick="exportChart(\'g\',\'全域Top50\')">匯出 PNG</button></div><div id="gChart" class="chart"></div></section>';
  h+='<section class="card"><h2>報告生成</h2><div class="qd"><button class="qb" onclick="generateReport(\'weekly\')">週報</button><button class="qb" onclick="generateReport(\'monthly\')">月報</button></div></section>';
  document.getElementById('page-home').innerHTML=h;
  if(top){
    disposeChart('g');
    var c=initChart(document.getElementById('gChart'),'g');
    var items=top.top20.slice().reverse();
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(p){var m=items[p[0].dataIndex];return '<b>'+mask(m.contractId||m.meterId)+'</b><br/>'+esc(m.propertyType)+'<br/>'+esc(m.dma)+'<br/>'+fmt(m.total)+' m³'}},grid:{left:150,right:60,top:10,bottom:30},xAxis:{type:'value',axisLabel:{formatter:function(v){return(v/1000).toFixed(0)+'k'}}},yAxis:{type:'category',data:items.map(function(i){return mask(i.contractId||i.meterId)}),axisLabel:{fontSize:10}},series:[{type:'bar',data:items.map(function(i){return{value:i.total,itemStyle:{color:DC[i.dma]||'#666'}}}),label:{show:true,position:'right',formatter:function(p){return fmt(p.value)},fontSize:10}}]});
  }
  setTimeout(function(){drawDmaCompare('trend');},100);
}

// === DMA 詳情 ===
function renderDma(){
  var t20=findD(D.top20dma,selDate),dma=findD(D.dma,selDate);
  var info=dma&&dma.dmas&&dma.dmas[selDma];
  var items=t20&&t20.byDma&&t20.byDma[selDma]?t20.byDma[selDma]:[];
  var h='<section class="card"><div class="breadcrumb"><span onclick="showTab(\'home\')">概覽</span><span class="sep">›</span><span class="current" style="color:'+(DC[selDma]||'#38bdf8')+'">'+esc(selDma)+'</span><span class="sep">›</span><span class="current">'+selDate+'</span></div>';
  if(info)h+='<div class="sr"><div class="si"><div class="sl">總用水量</div><div class="sv">'+fmt(info.total)+' m³</div></div><div class="si res"><div class="sl">🏠 住宅</div><div class="sv">'+fmt(info.residential)+' m³</div><div class="ss">'+info.resCount+' 個水表</div></div><div class="si nonres"><div class="sl">🏢 非住宅</div><div class="sv">'+fmt(info.nonResidential)+' m³</div><div class="ss">'+info.nonResCount+' 個水表</div></div></div>';
  h+='</section><section class="card"><h2>📊 Top 50</h2><div class="chart-actions"><button class="export-btn" onclick="exportChart(\'d\',\''+esc(selDma)+'Top50\')">匯出 PNG</button></div><div id="dChart" class="chart"></div></section>';
  h+='<section class="card"><h2>📋 Top 50 明細</h2><table><thead><tr><th>#</th><th>合同編號</th><th>物業類型</th><th>建築物</th><th class="num">用水量</th></tr></thead><tbody>';
  items.forEach(function(m,i){h+='<tr><td>'+(i+1)+'</td><td class="contract">'+mask(m.contractId)+'</td><td><span class="ptag '+(m.propertyType==='001:住宅'?'res':'')+'">'+esc(m.propertyType)+'</span></td><td class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(m.buildingName)+'</td><td class="num">'+fmt(m.total)+'</td></tr>';});
  h+='</tbody></table></section>';
  document.getElementById('page-dma').innerHTML=h;
  if(items.length){
    disposeChart('d');
    var c=initChart(document.getElementById('dChart'),'d');
    var rev=items.slice().reverse();
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(p){var m=rev[p[0].dataIndex];return '<b>'+mask(m.contractId||m.meterId)+'</b><br/>'+esc(m.propertyType)+'<br/>'+fmt(m.total)+' m³'}},grid:{left:140,right:60,top:10,bottom:30},xAxis:{type:'value',axisLabel:{formatter:function(v){return(v/1000).toFixed(0)+'k'}}},yAxis:{type:'category',data:rev.map(function(i){return mask(i.contractId||i.meterId)}),axisLabel:{fontSize:10}},series:[{type:'bar',data:rev.map(function(i){return{value:i.total,itemStyle:{color:DC[selDma]||'#38bdf8'}}}),label:{show:true,position:'right',formatter:function(p){return fmt(p.value)},fontSize:10}}]});
  }
}

// === 週報/月報 ===
function generateReport(type){
  var dates=D.dates;var startDate,endDate,title;
  if(type==='weekly'){endDate=dates[dates.length-1];startDate=dates[Math.max(0,dates.length-7)];title='週報 ('+startDate+' ~ '+endDate+')';}
  else{endDate=dates[dates.length-1];startDate=dates[Math.max(0,dates.length-30)];title='月報 ('+startDate+' ~ '+endDate+')';}
  var periodDates=dates.filter(d=>d>=startDate&&d<=endDate);
  var dmaStats={};
  for(var dmaName of Object.keys(D.dma[0].dmas)){dmaStats[dmaName]={total:0,count:0,residential:0,nonResidential:0};}
  for(var d of periodDates){var dayData2=D.dma.find(x=>x.date===d);if(!dayData2)continue;for(var[dmaName,info]of Object.entries(dayData2.dmas)){if(dmaStats[dmaName]){dmaStats[dmaName].total+=info.total;dmaStats[dmaName].residential+=info.residential;dmaStats[dmaName].nonResidential+=info.nonResidential;dmaStats[dmaName].count++;}}}
  var html='<section class="card"><h2>'+title+'</h2>';
  html+='<table><thead><tr><th>DMA</th><th class="num">總用水(m³)</th><th class="num">日均(m³)</th></tr></thead><tbody>';
  for(var[dmaName,stats]of Object.entries(dmaStats)){if(stats.count===0)continue;var avg=stats.total/stats.count;html+='<tr><td>'+dmaName+'</td><td class="num">'+Math.round(stats.total).toLocaleString()+'</td><td class="num">'+Math.round(avg).toLocaleString()+'</td></tr>';}
  html+='</tbody></table></section>';
  document.getElementById('reportContent').innerHTML=html;
  document.getElementById('reportModal').style.display='flex';
}
function closeReport(){document.getElementById('reportModal').style.display='none';}

function calcDmaStats(dma){
  var total=0,count=0,res=0,nonRes=0,anomalyCount=0;
  D.dma.forEach(function(d){
    var info=d.dmas[dma];
    if(info){total+=info.total;count++;res+=info.residential;nonRes+=info.nonResidential;}
  });
  anomalyCount=D.anomalies.filter(function(a){return a.dma===dma}).length;
  var avgDaily=count>0?Math.round(total/count):0;
  var resPct=total>0?Math.round(res/total*100):0;
  var nrwPct='-';
  if(D.diff&&D.diff.length){
    var lastMonth=D.diff[D.diff.length-1];
    var mt=0,st=0;
    lastMonth.diffs.forEach(function(m){if(m.dma===dma){mt+=m.mainMonthTotal;st+=m.subMonthTotal;}});
    nrwPct=mt>0?((mt-st)/mt*100).toFixed(1)+'%':'-';
  }
  return{avgDaily:avgDaily,resPct:resPct,anomalyCount:anomalyCount,nrwPct:nrwPct};
}

function drawDmaCompare(view,btn){
  if(btn){
    document.querySelectorAll('#page-home .ms .mb').forEach(function(b){b.classList.remove('active')});
    btn.classList.add('active');
  }
  disposeChart('dmaCompare');
  var el=document.getElementById('dmaCompareChart');
  if(!el)return;
  var c=initChart(el,'dmaCompare');
  var dates=D.dma.map(function(d){return d.date});
  var dmaNames=D.dma.length?Object.keys(D.dma[0].dmas).filter(function(k){return k!=='未分類'}):[];

  if(view==='trend'){
    var series=dmaNames.map(function(dma){
      return{name:dma,type:'line',smooth:true,showSymbol:false,
        data:D.dma.map(function(d){return d.dmas[dma]?Math.round(d.dmas[dma].total):0}),
        itemStyle:{color:DC[dma]||'#6b6b80'},lineStyle:{width:2}};
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:dmaNames,textStyle:{color:'#94a3b8'}},
      grid:{left:60,right:40,top:40,bottom:30},
      xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45}},
      yAxis:{type:'value',name:'m³',axisLabel:{formatter:function(v){return(v/1000).toFixed(0)+'k'}}},
      series:series});
  }
  else if(view==='nrw'){
    if(!D.diff||!D.diff.length)return;
    var months=D.diff.map(function(d){return d.month});
    var series=dmaNames.map(function(dma){
      return{name:dma,type:'bar',
        data:D.diff.map(function(m){
          var mt=0,st=0;
          m.diffs.forEach(function(d){if(d.dma===dma){mt+=d.mainMonthTotal;st+=d.subMonthTotal;}});
          return mt>0?Math.round((mt-st)/mt*1000)/10:0;
        }),
        itemStyle:{color:DC[dma]||'#6b6b80'}};
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',formatter:function(p){var r=p[0].axisValue+'<br/>';p.forEach(function(i){r+=i.marker+' '+i.seriesName+': '+i.value+'%<br/>';});return r;}},legend:{data:dmaNames,textStyle:{color:'#94a3b8'}},
      grid:{left:60,right:40,top:40,bottom:30},
      xAxis:{type:'category',data:months},
      yAxis:{type:'value',name:'NRW%',axisLabel:{formatter:'{value}%'}},
      series:series});
  }
  else if(view==='anomaly'){
    var types=['spike','drop','zero','watch'];
    var colors=['#f87171','#fb923c','#facc15','#818cf8'];
    var series=types.map(function(type,idx){
      return{name:type,type:'bar',stack:'total',
        data:dmaNames.map(function(dma){
          return D.anomalies.filter(function(a){return a.dma===dma&&a.type===type}).length;
        }),
        itemStyle:{color:colors[idx]}};
    });
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},legend:{data:types,textStyle:{color:'#94a3b8'}},
      grid:{left:80,right:40,top:40,bottom:30},
      xAxis:{type:'value'},
      yAxis:{type:'category',data:dmaNames},
      series:series});
  }
  else if(view==='residential'){
    var resData=dmaNames.map(function(dma){
      var total=0,res=0;
      D.dma.forEach(function(d){if(d.dmas[dma]){total+=d.dmas[dma].total;res+=d.dmas[dma].residential;}});
      return total>0?Math.round(res/total*1000)/10:0;
    });
    var nonResData=resData.map(function(v){return Math.round((100-v)*10)/10});
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(p){return p[0].axisValue+'<br/>'+p[0].marker+' 住宅: '+p[0].value+'%<br/>'+p[1].marker+' 非住宅: '+p[1].value+'%';}},legend:{data:['住宅','非住宅'],textStyle:{color:'#94a3b8'}},
      grid:{left:80,right:40,top:40,bottom:30},
      xAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
      yAxis:{type:'category',data:dmaNames},
      series:[
        {name:'住宅',type:'bar',stack:'total',data:resData,itemStyle:{color:'#34d399'}},
        {name:'非住宅',type:'bar',stack:'total',data:nonResData,itemStyle:{color:'#f472b6'}}
      ]});
  }
}
