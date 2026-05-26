// === 差額頁 ===
function renderDiff(){
  var h='<section class="card"><h2>💰 月度主分表差額</h2>';
  if(D.diff.length){h+='<div class="ms">';D.diff.forEach(function(d,i){h+='<button class="mb '+(i===D.diff.length-1?'active':'')+'" onclick="showMonthDiff(\''+d.month+'\',this)">'+d.month+'</button>';});h+='</div><div class="chart-actions"><button class="export-btn" onclick="exportChart(\'diff\',\'主分表差額\')">匯出 PNG</button></div><div id="mDiffChart" style="height:300px;margin:16px 0"></div><div id="mDiff"></div>';}
  h+='</section>';h+='<section class="card"><h2>NRW（無收益水）說明</h2><div class="dc"><p><b>NRW = 主表讀數 - Σ(分表讀數)</b></p><p>NRW率 = NRW / 主表讀數 × 100%</p><p class="hint">NRW 包含：漏損 + 計量誤差 + 未計費用水</p></div></section>';
  document.getElementById('page-diff').innerHTML=h;
  if(D.diff.length){renderDiffChart(selDiffMeter);showMonthDiff(D.diff[D.diff.length-1].month);}
}

function renderDiffChart(meterId){
  if(!D.diff||!D.diff.length)return;
  var months=[],mainTotals=[],subTotals=[],diffs=[],nrwPct=[];
  var title='月度匯總';
  D.diff.forEach(function(d){
    if(meterId){
      var m=d.diffs.find(function(x){return x.mainMeterId===meterId});
      if(m){months.push(d.month);mainTotals.push(m.mainMonthTotal);subTotals.push(m.subMonthTotal);diffs.push(m.mainMonthTotal-m.subMonthTotal);nrwPct.push(m.mainMonthTotal>0?Math.round((m.mainMonthTotal-m.subMonthTotal)/m.mainMonthTotal*1000)/10:0);}
    }else{
      var mt=0,st=0;
      d.diffs.forEach(function(m){mt+=m.mainMonthTotal;st+=m.subMonthTotal;});
      months.push(d.month);mainTotals.push(mt);subTotals.push(st);diffs.push(mt-st);nrwPct.push(mt>0?Math.round((mt-st)/mt*1000)/10:0);
    }
  });
  if(meterId){var info=D.search.find(function(s){return s.id===meterId});title=info?(mask(info.contract)+' '+maskBuilding(info.building)):meterId;}
  var chartDom=document.getElementById('mDiffChart');
  if(!chartDom)return;
  disposeChart('diff');
  var c=initChart(chartDom,'diff');
  c.setOption({
    backgroundColor:'transparent',
    title:{text:title,left:'center',textStyle:{color:'#e2e8f0',fontSize:13,fontWeight:'normal'}},
    tooltip:{trigger:'axis',formatter:function(p){var r=p[0].axisValue+'<br/>';p.forEach(function(i){r+=i.marker+' '+i.seriesName+': '+i.value.toLocaleString()+(i.seriesName.indexOf('%')>=0?'%':' m³')+'<br/>';});return r;}},
    legend:{data:['主表','分表合計','差額','NRW率%'],textStyle:{color:'#94a3b8'},top:22},
    grid:{left:70,right:70,top:55,bottom:30},
    xAxis:{type:'category',data:months,axisLabel:{color:'#94a3b8'}},
    yAxis:[{type:'value',name:'m³',axisLabel:{color:'#94a3b8'}},{type:'value',name:'%',axisLabel:{color:'#94a3b8',formatter:'{value}%' },splitLine:{show:false}}],
    series:[
      {name:'主表',type:'bar',data:mainTotals,itemStyle:{color:'#38bdf8'},barWidth:'25%'},
      {name:'分表合計',type:'bar',data:subTotals,itemStyle:{color:'#a78bfa'},barWidth:'25%'},
      {name:'差額',type:'bar',data:diffs,itemStyle:{color:function(p){return p.value<0?'#ef4444':'#fbbf24'}},barWidth:'25%'},
      {name:'NRW率%',type:'line',yAxisIndex:1,data:nrwPct,itemStyle:{color:'#34d399'},lineStyle:{width:3},symbol:'circle',symbolSize:8}
    ]
  });
}

function resetDiffSel(){selDiffMeter=null;renderDiffChart();var activeBtn=document.querySelector('#page-diff .mb.active');if(activeBtn)showMonthDiff(activeBtn.textContent,activeBtn);else showMonthDiff(D.diff[D.diff.length-1].month);}

function showMonthDiff(month,btn){
  if(btn){document.querySelectorAll('#page-diff .mb').forEach(function(b){b.classList.remove('active')});btn.classList.add('active');}
  var data=D.diff.find(function(d){return d.month===month});if(!data)return;
  var h='';if(selDiffMeter){h+='<div style="margin-bottom:10px"><button class="mb" onclick="resetDiffSel()" style="font-size:12px">← 返回匯總</button> <span class="hint">目前: '+selDiffMeter+'</span></div>';}
  h+='<table><thead><tr><th>#</th><th>合同編號</th><th>建築物</th><th>DMA</th><th>分表數</th><th class="num">主表月量</th><th class="num">分表月量</th><th class="num">差額</th><th class="num">NRW%</th></tr></thead><tbody>';
  data.diffs.slice(0,30).forEach(function(d,i){var c2=d.diffPct>20||d.diffPct<-20?'warn':'';h+='<tr class="'+c2+'" style="cursor:pointer" onclick="selDiffMeter=\''+esc(d.mainMeterId)+'\';renderDiffChart(selDiffMeter);showDailyDiff(\''+month+'\',\''+esc(d.mainMeterId)+'\',\''+mask(d.mainContractId)+'\',\''+maskBuilding(d.mainBuilding)+'\')"><td>'+(i+1)+'</td><td class="contract">'+mask(d.mainContractId)+'</td><td class="'+(isUnlocked?'':'masked')+'" onclick="event.stopPropagation();clickMasked()">'+maskBuilding(d.mainBuilding)+'</td><td><span class="tag" style="background:'+(DC[d.dma]||'#666')+'">'+esc(d.dma)+'</span></td><td>'+d.subCount+'</td><td class="num">'+fmt(d.mainMonthTotal)+'</td><td class="num">'+fmt(d.subMonthTotal)+'</td><td class="num '+(d.diff<0?'neg':'')+'">'+fmt(d.diff)+'</td><td class="num '+(d.diffPct<0?'neg':'')+'">'+d.diffPct+'%</td></tr>';});
  h+='</tbody></table><div id="dailyDiffDetail"></div>';
  document.getElementById('mDiff').innerHTML=h;
}

function showDailyDiff(month,mainMeterId,contract,building){
  var detailEl=document.getElementById('dailyDiffDetail');
  if(!detailEl)return;
  var monthData=D.diff.find(function(d){return d.month===month});
  if(!monthData){detailEl.innerHTML='<div class="card"><p style="color:#ef4444">未找到月份資料</p></div>';return;}
  var meterData=monthData.diffs.find(function(d){return d.mainMeterId===mainMeterId});
  if(!meterData){detailEl.innerHTML='<div class="card"><p style="color:#ef4444">未找到水表資料</p></div>';return;}
  var subMeterIds=Array.isArray(meterData.subs)?meterData.subs:Object.keys(meterData.subs||{});
  var dailyData=meterData.daily||{};
  var dates=Object.keys(dailyData).sort();
  var mainTotals=[],subTotals=[],dailyDiffs=[];
  dates.forEach(function(date){var d=dailyData[date]||{};mainTotals.push(d.main||0);subTotals.push(d.sub||0);dailyDiffs.push(d.diff||0);});

  // 組合完整 HTML（圖表 + 分表明細）
  var totalDiff=dailyDiffs.reduce(function(a,b){return a+b},0);
  var avgDiff=dates.length>0?Math.round(totalDiff/dates.length):0;
  var posDays=dailyDiffs.filter(function(d){return d>0}).length;
  var negDays=dailyDiffs.filter(function(d){return d<0}).length;
  var dataType=(meterData&&meterData.hasRealData)?'✅ 實際日資料':'📊 月總量按日均分';
  var h='<div class="card" style="margin-top:16px"><h2>📊 '+contract+' 每日差額詳情</h2>';
  if(building)h+='<p style="color:#94a3b8;font-size:13px;margin-bottom:12px">'+building+' · 主表: '+mainMeterId+' · 分表: '+subMeterIds.length+' 個 · '+dataType+'</p>';
  h+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'dd\',\'每日差額\')">匯出 PNG</button></div><div id="dailyDiffChart" class="chart" style="height:350px"></div>';
  h+='<div class="sr" style="margin-top:16px"><div class="si"><div class="sl">月總差額</div><div class="sv '+(totalDiff<0?'neg':'')+'">'+fmt(totalDiff)+' m³</div></div><div class="si"><div class="sl">日均差額</div><div class="sv '+(avgDiff<0?'neg':'')+'">'+fmt(avgDiff)+' m³</div></div><div class="si"><div class="sl">正/負天數</div><div class="sv">'+posDays+'/'+negDays+'</div></div></div></div>';

  // 渲染分表用水量明細
  h+='<div class="card"><h2>💧 分表用水量 ('+month+')</h2>';
  h+='<p class="hint">主表: '+mainMeterId+' | 合同: '+contract+' | 建築物: '+building+'</p>';
  h+='<p class="hint">分表數: '+subMeterIds.length+' | 主表月量: '+fmt(meterData.mainMonthTotal)+' | 分表月量: '+fmt(meterData.subMonthTotal)+' | 差額: '+fmt(meterData.diff)+'</p>';
  h+='<table><thead><tr><th>分表ID</th><th>合同編號</th><th class="num">月用水量</th></tr></thead><tbody>';
  var subMeterData=[];
  subMeterIds.forEach(function(subId){var monthly=D.meterMonthly[subId]||{};var monthTotal=monthly[month]||0;var info=D.search.find(function(s){return s.id===subId})||{};subMeterData.push({id:subId,total:monthTotal,contract:info.contract||''});});
  subMeterData.sort(function(a,b){return b.total-a.total});
  subMeterData.slice(0,20).forEach(function(m){h+='<tr><td>'+m.id+'</td><td>'+mask(m.contract)+'</td><td class="num">'+fmt(m.total)+'</td></tr>';});
  if(subMeterData.length>20){h+='<tr><td colspan="3" class="hint">... 還有 '+(subMeterData.length-20)+' 個分表</td></tr>';}
  h+='</tbody></table></div>';
  detailEl.innerHTML=h;

  // 渲染每日差額圖表（在 DOM 更新後）
  setTimeout(function(){
    var chartDom=document.getElementById('dailyDiffChart');
    if(!chartDom)return;
    disposeChart('dd');
    var c=initChart(chartDom,'dd');
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',formatter:function(params){var result=params[0].axisValue+'<br/>';params.forEach(function(p){result+=p.marker+' '+p.seriesName+': '+p.value.toLocaleString()+' m³<br/>';});return result;}},legend:{data:['主表','分表合計','差額'],textStyle:{color:'#94a3b8'},top:0},grid:{left:80,right:30,top:40,bottom:60},xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45,color:'#94a3b8'}},yAxis:{type:'value',name:'m³',axisLabel:{color:'#94a3b8'}},series:[{name:'主表',type:'bar',data:mainTotals,itemStyle:{color:'#38bdf8'},barWidth:'30%'},{name:'分表合計',type:'bar',data:subTotals,itemStyle:{color:'#a78bfa'},barWidth:'30%'},{name:'差額',type:'line',data:dailyDiffs,itemStyle:{color:'#fbbf24'},lineStyle:{width:3},symbol:'circle',symbolSize:8}]});
  },100);
}

function renderDailyDiffChart(dates,mainTotals,subTotals,dailyDiffs,contract,building,mainMeterId,subMeterIds,month,meterData){
  for(var i=0;i<dates.length;i++){if(mainTotals[i]===undefined)mainTotals[i]=0;if(subTotals[i]===undefined)subTotals[i]=0;if(dailyDiffs[i]===undefined)dailyDiffs[i]=0;}
  var totalDiff=dailyDiffs.reduce(function(a,b){return a+b},0);
  var avgDiff=dates.length>0?Math.round(totalDiff/dates.length):0;
  var posDays=dailyDiffs.filter(function(d){return d>0}).length;
  var negDays=dailyDiffs.filter(function(d){return d<0}).length;
  var dataType=(meterData&&meterData.hasRealData)?'✅ 實際日資料':'📊 月總量按日均分';
  var h='<div class="card" style="margin-top:16px"><h2>📊 '+contract+' 每日差額詳情</h2>';
  if(building)h+='<p style="color:#94a3b8;font-size:13px;margin-bottom:12px">'+building+' · 主表: '+mainMeterId+' · 分表: '+subMeterIds.length+' 個 · '+dataType+'</p>';
  h+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'dd\',\'每日差額\')">匯出 PNG</button></div><div id="dailyDiffChart" class="chart" style="height:350px"></div>';
  h+='<div class="sr" style="margin-top:16px"><div class="si"><div class="sl">月總差額</div><div class="sv '+(totalDiff<0?'neg':'')+'">'+fmt(totalDiff)+' m³</div></div><div class="si"><div class="sl">日均差額</div><div class="sv '+(avgDiff<0?'neg':'')+'">'+fmt(avgDiff)+' m³</div></div><div class="si"><div class="sl">正/負天數</div><div class="sv">'+posDays+'/'+negDays+'</div></div></div></div>';
  document.getElementById('dailyDiffDetail').innerHTML=h;
  setTimeout(function(){
    var chartDom=document.getElementById('dailyDiffChart');
    if(!chartDom)return;
    disposeChart('dd');
    var c=initChart(chartDom,'dd');
    c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',formatter:function(params){var result=params[0].axisValue+'<br/>';params.forEach(function(p){result+=p.marker+' '+p.seriesName+': '+p.value.toLocaleString()+' m³<br/>';});return result;}},legend:{data:['主表','分表合計','差額'],textStyle:{color:'#94a3b8'},top:0},grid:{left:80,right:30,top:40,bottom:60},xAxis:{type:'category',data:dates,axisLabel:{fontSize:10,rotate:45,color:'#94a3b8'}},yAxis:{type:'value',name:'m³',axisLabel:{color:'#94a3b8'}},series:[{name:'主表',type:'bar',data:mainTotals,itemStyle:{color:'#38bdf8'},barWidth:'30%'},{name:'分表合計',type:'bar',data:subTotals,itemStyle:{color:'#a78bfa'},barWidth:'30%'},{name:'差額',type:'line',data:dailyDiffs,itemStyle:{color:'#fbbf24'},lineStyle:{width:3},symbol:'circle',symbolSize:8}]});
  },100);
}
