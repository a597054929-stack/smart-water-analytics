// === 趨勢頁 ===
function renderTrend(){
  var h='<section class="card"><h2>📈 用水趨勢 + 降雨量</h2>';
  h+='<div class="ms" style="margin-bottom:6px"><button class="mb active" id="btnRA7" onclick="toggleRA(7,this)">7天均值</button><button class="mb" id="btnRA14" onclick="toggleRA(14,this)">14天均值</button><button class="mb" id="btnPred" onclick="togglePred(this)">7天預測</button><button class="mb" id="btnMoM" onclick="toggleMoM(this)">月環比</button><button class="mb" id="btnRes" onclick="switchTrendView(\'residential\',this)">住宅趨勢</button><button class="mb" id="btnWeekly" onclick="switchTrendView(\'weekly\',this)">週度趨勢</button></div>';
  h+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'trend\',\'用水趨勢\')">匯出 PNG</button></div>';
  h+='<div id="trendChart" class="chart" style="height:450px"></div>';
  h+='<div id="trendResChart" class="chart" style="height:450px;display:none"></div>';
  h+='<div id="trendWeeklyChart" class="chart" style="height:450px;display:none"></div>';
  h+='</section>';
  var dmaNames=D.trend.length?Object.keys(D.trend[0].dmas).filter(function(k){return k!=='未分類'}):[];
  h+='<section class="card"><h2>🏚️ 分DMA趨勢</h2><div class="ms">';
  dmaNames.forEach(function(d){h+='<button class="mb" onclick="renderDmaTrend(\''+esc(d)+'\')">'+esc(d)+'</button>';});
  h+='</div><div class="chart-actions"><button class="export-btn" onclick="exportChart(\'dt\',\'DMA趨勢\')">匯出 PNG</button></div><div id="dmaTrendChart" class="chart" style="height:400px"></div></section>';
  document.getElementById('page-trend').innerHTML=h;
  window._raWin=7; window._showPred=false; window._showMoM=false;
  drawTrendChart();
}

function toggleMoM(btn){
  window._showMoM=!window._showMoM;
  window._trendView='main';
  btn.classList.toggle('active',window._showMoM);
  showMainTrend();
  drawTrendChart();
}

function calcMA(data,win){
  var r=[];for(var i=0;i<data.length;i++){if(i<win-1){r.push(null);continue;}var s=0;for(var j=i-win+1;j<=i;j++)s+=data[j];r.push(Math.round(s/win));}return r;
}

function hwForecast(data,horizon,alpha,beta,gamma){
  alpha=alpha||0.3;beta=beta||0.1;gamma=gamma||0.3;
  var n=data.length,period=7;
  if(n<period*2)return holtForecast(data,horizon,alpha,beta);
  var seasonAvg1=0,seasonAvg2=0;
  for(var i=0;i<period;i++){seasonAvg1+=data[i];seasonAvg2+=data[period+i];}
  seasonAvg1/=period;seasonAvg2/=period;
  var trend2=(seasonAvg2-seasonAvg1)/period;
  var season=[];
  for(var i=0;i<period;i++)season.push(data[i]-seasonAvg1);
  var level=seasonAvg1;
  for(var i=period;i<n;i++){
    var si=i%period;
    var prevLevel=level;
    level=alpha*(data[i]-season[si])+(1-alpha)*(level+trend2);
    trend2=beta*(level-prevLevel)+(1-beta)*trend2;
    season[si]=gamma*(data[i]-level)+(1-gamma)*season[si];
  }
  var preds=[];
  for(var h=1;h<=horizon;h++){
    var si=(n+h-1)%period;
    preds.push(Math.round(Math.max(0,level+trend2*h+season[si])));
  }
  return preds;
}

function hwFitted(data,alpha,beta,gamma){
  alpha=alpha||0.3;beta=beta||0.1;gamma=gamma||0.3;
  var n=data.length,period=7;
  if(n<period*2)return calcMA(data,7);
  var seasonAvg1=0;for(var i=0;i<period;i++)seasonAvg1+=data[i];seasonAvg1/=period;
  var seasonAvg2=0;for(var i=period;i<period*2&&i<n;i++)seasonAvg2+=data[i];seasonAvg2/=Math.min(period,n-period);
  var trend2=(seasonAvg2-seasonAvg1)/period;
  var season=[];for(var i=0;i<period;i++)season.push(data[i]-seasonAvg1);
  var level=seasonAvg1;
  var fitted=new Array(period).fill(null);
  for(var i=period;i<n;i++){
    var si=i%period;
    var prevLevel=level;
    level=alpha*(data[i]-season[si])+(1-alpha)*(level+trend2);
    trend2=beta*(level-prevLevel)+(1-beta)*trend2;
    season[si]=gamma*(data[i]-level)+(1-gamma)*season[si];
    fitted.push(Math.round(Math.max(0,level+trend2+season[(i+1)%period])));
  }
  return fitted;
}

function toggleRA(w,btn){
  window._raWin=w;
  window._trendView='main';
  document.querySelectorAll('#page-trend .ms .mb').forEach(function(b){if(b.id&&b.id.indexOf('btnRA')===0)b.classList.remove('active')});
  btn.classList.add('active');
  showMainTrend();
  drawTrendChart();
}

function togglePred(btn){
  window._showPred=!window._showPred;
  window._trendView='main';
  btn.classList.toggle('active',window._showPred);
  showMainTrend();
  drawTrendChart();
}

function showMainTrend(){
  var main=document.getElementById('trendChart');
  var res=document.getElementById('trendResChart');
  var weekly=document.getElementById('trendWeeklyChart');
  if(main)main.style.display='';
  if(res)res.style.display='none';
  if(weekly)weekly.style.display='none';
}

function switchTrendView(view,btn){
  window._trendView=view;
  document.querySelectorAll('#page-trend .ms .mb').forEach(function(b){b.classList.remove('active')});
  btn.classList.add('active');
  var main=document.getElementById('trendChart');
  var res=document.getElementById('trendResChart');
  var weekly=document.getElementById('trendWeeklyChart');
  if(view==='residential'){
    if(main)main.style.display='none';
    if(weekly)weekly.style.display='none';
    if(res)res.style.display='';
    drawResTrendChart();
  }else if(view==='weekly'){
    if(main)main.style.display='none';
    if(res)res.style.display='none';
    if(weekly)weekly.style.display='';
    drawWeeklyTrendChart();
  }
}

function drawResTrendChart(){
  disposeChart('trendRes');
  var el=document.getElementById('trendResChart');
  if(!el)return;
  var c=initChart(el,'trendRes');
  var dates=D.dma.map(function(d){return d.date});
  var resData=D.dma.map(function(d){
    var t=0;for(var k in d.dmas){if(k!=='未分類')t+=d.dmas[k].residential;}return Math.round(t);
  });
  var nonResData=D.dma.map(function(d){
    var t=0;for(var k in d.dmas){if(k!=='未分類')t+=d.dmas[k].nonResidential;}return Math.round(t);
  });
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
    legend:{data:['住宅','非住宅'],textStyle:{color:'#94a3b8'}},
    grid:{left:60,right:40,top:40,bottom:30},
    xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45}},
    yAxis:{type:'value',name:'m³',axisLabel:{formatter:function(v){return(v/1000000).toFixed(1)+'M'}}},
    series:[
      {name:'住宅',type:'line',stack:'total',areaStyle:{opacity:0.3},data:resData,itemStyle:{color:'#34d399'},showSymbol:false},
      {name:'非住宅',type:'line',stack:'total',areaStyle:{opacity:0.3},data:nonResData,itemStyle:{color:'#f472b6'},showSymbol:false}
    ]});
}

function drawWeeklyTrendChart(){
  disposeChart('trendWeekly');
  var el=document.getElementById('trendWeeklyChart');
  if(!el)return;
  var c=initChart(el,'trendWeekly');
  // 計算週度匯總
  var weeklyData=[];
  var dates=D.dma.map(function(d){return d.date});
  var weekStart=0;
  for(var i=0;i<dates.length;i++){
    var d=new Date(dates[i]);
    if(d.getDay()===1&&i>0){
      var weekDates=dates.slice(weekStart,i);
      var wdTotal=0,wdCount=0,weTotal=0,weCount=0;
      for(var j=weekStart;j<i;j++){
        var dd=new Date(dates[j]);
        var day=dd.getDay();
        var total=0;
        for(var k in D.dma[j].dmas){if(k!=='未分類')total+=D.dma[j].dmas[k].total;}
        if(day===0||day===6){weTotal+=total;weCount++;}
        else{wdTotal+=total;wdCount++;}
      }
      weeklyData.push({
        label:dates[weekStart].slice(5)+'~'+dates[i-1].slice(5),
        weekdayAvg:wdCount>0?Math.round(wdTotal/wdCount):0,
        weekendAvg:weCount>0?Math.round(weTotal/weCount):0
      });
      weekStart=i;
    }
  }
  // 最後一週
  if(weekStart<dates.length){
    var wdTotal=0,wdCount=0,weTotal=0,weCount=0;
    for(var j=weekStart;j<dates.length;j++){
      var dd=new Date(dates[j]);
      var day=dd.getDay();
      var total=0;
      for(var k in D.dma[j].dmas){if(k!=='未分類')total+=D.dma[j].dmas[k].total;}
      if(day===0||day===6){weTotal+=total;weCount++;}
      else{wdTotal+=total;wdCount++;}
    }
    weeklyData.push({
      label:dates[weekStart].slice(5)+'~'+dates[dates.length-1].slice(5),
      weekdayAvg:wdCount>0?Math.round(wdTotal/wdCount):0,
      weekendAvg:weCount>0?Math.round(weTotal/weCount):0
    });
  }

  if(!weeklyData.length)return;
  var labels=weeklyData.map(function(w){return w.label});
  var weekdayAvgs=weeklyData.map(function(w){return w.weekdayAvg});
  var weekendAvgs=weeklyData.map(function(w){return w.weekendAvg});
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
    legend:{data:['工作日均','週末均'],textStyle:{color:'#94a3b8'}},
    grid:{left:60,right:40,top:40,bottom:30},
    xAxis:{type:'category',data:labels,axisLabel:{fontSize:10,rotate:45}},
    yAxis:{type:'value',name:'m³',axisLabel:{formatter:function(v){return(v/1000).toFixed(0)+'k'}}},
    series:[
      {name:'工作日均',type:'bar',data:weekdayAvgs,itemStyle:{color:'#38bdf8'},barWidth:'30%'},
      {name:'週末均',type:'bar',data:weekendAvgs,itemStyle:{color:'#f472b6'},barWidth:'30%'}
    ]});
}

function drawTrendChart(){
  disposeChart('trend');
  var c=initChart(document.getElementById('trendChart'),'trend');
  var dates=D.trend.map(function(d){return d.date}),totals=D.trend.map(function(d){var t=0;for(var v in d.dmas)t+=d.dmas[v];return t}),rain=D.trend.map(function(d){return d.rain||0});
  var win=window._raWin||7;var ma=calcMA(totals,win);

  // 月環比：按月份著色 + 月均值參考線
  var barColors=totals.map(function(){return 'rgba(56,189,248,0.35)'});
  var momLines=[];
  if(window._showMoM){
    var monthColors=['rgba(56,189,248,0.5)','rgba(167,139,250,0.5)','rgba(244,114,182,0.5)','rgba(52,211,153,0.5)','rgba(251,191,36,0.5)','rgba(248,113,113,0.5)'];
    var monthStats={};
    dates.forEach(function(d,i){
      var m=d.slice(0,7);
      if(!monthStats[m])monthStats[m]={sum:0,count:0,idx:Object.keys(monthStats).length};
      monthStats[m].sum+=totals[i];monthStats[m].count++;
      barColors[i]=monthColors[monthStats[m].idx%monthColors.length];
    });
    // 月均值參考線
    var markData=[];
    for(var m in monthStats){
      var avg=Math.round(monthStats[m].sum/monthStats[m].count);
      markData.push({yAxis:avg,label:{formatter:m+' 均:'+fmt(avg),fontSize:10,color:'#94a3b8'}});
    }
    momLines=[{silent:true,data:markData,lineStyle:{color:'#fbbf24',type:'dashed',width:1.5,opacity:0.6},symbol:'none'}];

    // 月環比變化率
    var months=Object.keys(monthStats).sort();
    var momLabels=[];
    for(var i=1;i<months.length;i++){
      var prev=monthStats[months[i-1]],curr=monthStats[months[i]];
      var pAvg=prev.sum/prev.count,cAvg=curr.sum/curr.count;
      var pct=((cAvg-pAvg)/pAvg*100).toFixed(1);
      momLabels.push(months[i]+' 環比 '+(pct>0?'+':'')+pct+'%');
    }
    if(momLabels.length){
      // 不額外添加series，改用title顯示
    }
  }

  var series=[
    {name:'總用水量',type:'bar',data:totals.map(function(v,i){return{value:v,itemStyle:{color:barColors[i]}}}),barMaxWidth:6,z:1,
     markLine:window._showMoM?momLines[0]:undefined},
    {name:win+'天均值',type:'line',data:ma,smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2.5},showSymbol:false,z:2}
  ];
  var legend=['總用水量',win+'天均值'];
  if(window._showPred&&totals.length>=14){
    var n=totals.length;
    var preds=hwForecast(totals,7);
    var predDates=dates.slice(),predVals=new Array(n).fill(null);
    var fitted=hwFitted(totals);
    for(var i=Math.max(0,n-14);i<n;i++)predVals[i]=fitted[i];
    for(var i=0;i<7;i++){predDates.push('+'+(i+1)+'天');predVals.push(preds[i]);}
    series[0].data=predDates.map(function(_,i){return i<n?totals[i]:null});
    series[1].data=predDates.map(function(_,i){return i<n?ma[i]:null});
    series.push({name:'預測(Holt-Winters)',type:'line',data:predVals,smooth:true,itemStyle:{color:'#f472b6'},lineStyle:{type:'dotted',width:2.5},showSymbol:false,z:3});
    legend.push('預測(Holt-Winters)');
    var rainFull=predDates.map(function(_,i){return i<n?rain[i]:0});
    series.push({name:'降雨量',type:'bar',data:rainFull,yAxisIndex:1,itemStyle:{color:'rgba(59,130,246,0.4)'},barMaxWidth:6,z:0});
    legend.push('降雨量');
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:legend,textStyle:{color:'#94a3b8'}},grid:{left:60,right:60,top:40,bottom:30},xAxis:{type:'category',data:predDates,axisLabel:{fontSize:10,rotate:45}},yAxis:[{type:'value',name:'m³',axisLabel:{formatter:function(v){return(v/1000000).toFixed(1)+'M'}}},{type:'value',name:'mm',max:15}],series:series});
    return;
  }
  series.push({name:'降雨量',type:'bar',data:rain,yAxisIndex:1,itemStyle:{color:'rgba(59,130,246,0.4)'},barMaxWidth:6,z:0});
  legend.push('降雨量');
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:legend,textStyle:{color:'#94a3b8'}},grid:{left:60,right:60,top:40,bottom:30},xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45}},yAxis:[{type:'value',name:'m³',axisLabel:{formatter:function(v){return(v/1000000).toFixed(1)+'M'}}},{type:'value',name:'mm',max:15}],series:series});
}

function renderDmaTrend(dma){
  disposeChart('dt');
  var c=initChart(document.getElementById('dmaTrendChart'),'dt');
  var dates=D.trend.map(function(d){return d.date});
  var vals=D.trend.map(function(d){return d.dmas[dma]||0});
  var ma=calcMA(vals,7);
  var preds=hwForecast(vals,7);
  var predDates=dates.slice(),predVals=new Array(vals.length).fill(null);
  var fitted=hwFitted(vals);
  for(var i=Math.max(0,vals.length-14);i<vals.length;i++)predVals[i]=fitted[i];
  for(var i=0;i<7;i++){predDates.push('+'+(i+1)+'天');predVals.push(preds[i]);}
  var color=DC[dma]||'#38bdf8';
  var series=[
    {name:dma,type:'bar',data:predDates.map(function(_,i){return i<vals.length?vals[i]:null}),itemStyle:{color:color,opacity:0.4},barMaxWidth:6},
    {name:'7天均值',type:'line',data:predDates.map(function(_,i){return i<vals.length?ma[i]:null}),smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2},showSymbol:false},
    {name:'預測(Holt-Winters)',type:'line',data:predVals,smooth:true,itemStyle:{color:'#f472b6'},lineStyle:{type:'dotted',width:2},showSymbol:false}
  ];
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:series.map(function(s){return s.name}),textStyle:{color:'#94a3b8'}},grid:{left:60,right:40,top:40,bottom:30},xAxis:{type:'category',data:predDates,axisLabel:{fontSize:10,rotate:45}},yAxis:{type:'value',name:'m³'},series:series});
}
