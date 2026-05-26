// === 搜尋頁 ===
function renderSearch(){
  _selMeters={};
  var h='<section class="card"><h2>🔍 水表月度用水查詢</h2><input type="text" class="si2" placeholder="輸入合同編號、水表編號或建築物名稱..." oninput="doSearch(this.value)"><div id="searchR"></div><div id="compareBar" class="compare-bar"><span class="sel" id="compareCount"></span><button class="mb active" onclick="showCompareMeters()">📊 對比用水曲線</button><button class="nb" onclick="_selMeters={};renderSearch()">取消</button></div><div id="meterD"></div></section>';
  document.getElementById('page-search').innerHTML=h;
}

function doSearch(q){
  if(q.length<2){document.getElementById('searchR').innerHTML='';document.getElementById('meterD').innerHTML='';document.getElementById('compareBar').style.display='none';return;}
  var ql=q.toLowerCase();var res=D.search.filter(function(s){return(s.contract||'').toLowerCase().includes(ql)||(s.id||'').toLowerCase().includes(ql)||(s.building||'').toLowerCase().includes(ql)}).slice(0,20);
  var h='<table><thead><tr><th></th><th>合同編號</th><th>水表編號</th><th>建築物</th><th>DMA</th><th>物業類型</th><th>Top50</th><th></th></tr></thead><tbody>';
  res.forEach(function(r){var tc=r.top20Count||0;var tcColor=tc>20?'#ef4444':tc>5?'#fbbf24':tc>0?'#34d399':'#64748b';var selId=esc(r.id);h+='<tr><td><input type="checkbox" class="ck" '+(_selMeters[selId]?'checked':'')+' onchange="toggleSelMeter(\''+selId+'\',\''+mask(r.contract)+'\',\''+maskBuilding(r.building)+'\',this.checked)" onclick="event.stopPropagation()"></td><td class="contract">'+mask(r.contract)+'</td><td>'+selId+'</td><td class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(r.building)+'</td><td><span class="tag" style="background:'+(DC[r.dma]||'#666')+'">'+esc(r.dma)+'</span></td><td><span class="ptag '+(r.type==='001:住宅'?'res':'')+'">'+esc(r.type)+'</span></td><td style="color:'+tcColor+';font-weight:600">'+(tc>0?tc+'天':'-')+'</td><td><button class="nb" onclick="showMeterDetail(\''+selId+'\',\''+mask(r.contract)+'\',\''+maskBuilding(r.building)+'\')">查看</button></td></tr>';});
  h+='</tbody></table><p style="color:#64748b;font-size:11px;margin-top:8px">共 '+res.length+' 條結果</p>';
  document.getElementById('searchR').innerHTML=h;
  updateCompareBar();
}

function toggleSelMeter(id,contract,building,checked){
  if(checked){if(Object.keys(_selMeters).length>=5){alert('最多選擇5個水表');return;}_selMeters[id]={contract:contract,building:building};}
  else delete _selMeters[id];
  updateCompareBar();
}

function updateCompareBar(){
  var keys=Object.keys(_selMeters),bar=document.getElementById('compareBar');
  if(!bar)return;
  if(keys.length>=2){bar.style.display='flex';document.getElementById('compareCount').textContent='已選 '+keys.length+' 個水表';}
  else bar.style.display='none';
}

function showCompareMeters(){
  var keys=Object.keys(_selMeters);if(keys.length<2)return;
  var allDates=D.dates;
  var series=[];var colors=['#818cf8','#f87171','#34d399','#fbbf24','#fb923c'];
  keys.forEach(function(id,i){
    var md=D.meterDaily[id];if(!md)return;
    var vals=allDates.map(function(d){return md.hasOwnProperty(d)?md[d]:null});
    series.push({name:_selMeters[id].contract+' ('+id+')',type:'line',data:vals,connectNulls:false,smooth:false,symbol:'none',lineStyle:{width:2,color:colors[i]},itemStyle:{color:colors[i]}});
  });
  if(series.length<2)return;
  var h='<div class="card"><h2>📊 水表日用水對比</h2><div id="compareChart" class="chart" style="height:400px"></div>';
  keys.forEach(function(id,i){h+='<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:'+colors[i]+';margin-right:4px"></span><span style="font-size:11px;color:var(--muted);margin-right:12px">'+_selMeters[id].contract+' ('+id+')</span>';});
  h+='</div>';
  document.getElementById('meterD').innerHTML=h;
  disposeChart('cmp');
  var c=initChart(document.getElementById('compareChart'),'cmp');
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:series.map(function(s){return s.name}),textStyle:{color:'var(--muted)'},bottom:0},grid:{left:60,right:20,top:10,bottom:40},xAxis:{type:'category',data:allDates,axisLabel:{fontSize:9,rotate:45}},yAxis:{type:'value',name:'m³'},series:series});
}

function showMeterDetail(mid,contract,building){
  var monthly=D.meterMonthly[mid];if(!monthly){document.getElementById('meterD').innerHTML='<div class="card"><p style="color:#64748b">該水表無月度資料</p></div>';return;}
  var months=Object.keys(monthly).sort(),vals=months.map(function(m){return Math.round(monthly[m])});
  var h='<div class="card"><h2>📊 '+esc(contract)+' 月度用水量</h2>';
  if(building)h+='<p style="color:#94a3b8;font-size:13px;margin-bottom:12px">'+esc(building)+' · '+mid+'</p>';
  h+='<div id="mChart" class="chart" style="height:300px"></div>';
  h+='<table style="margin-top:12px"><thead><tr><th>月份</th><th class="num">用水量 (m³)</th><th class="num">環比變化</th></tr></thead><tbody>';
  months.forEach(function(m,i){var prev=i>0?vals[i-1]:null;var ch=prev!==null&&prev>0?((vals[i]-prev)/prev*100).toFixed(1):null;var cls=ch!==null?(parseFloat(ch)>0?'neg':'up'):'';var arrow=ch!==null?(parseFloat(ch)>0?'↑':'↓'):'';h+='<tr><td>'+m+'</td><td class="num">'+fmt(vals[i])+'</td><td class="num '+cls+'">'+(ch!==null?arrow+Math.abs(ch)+'%':'-')+'</td></tr>';});
  h+='</tbody></table></div>';
  var daily=D.meterDaily&&D.meterDaily[mid];
  if(daily){
    h+='<div class="card"><h2>📈 日用水曲線</h2><div id="dailyChart" class="chart" style="height:300px"></div></div>';
  }
  document.getElementById('meterD').innerHTML=h;
  disposeChart('m');
  var c=initChart(document.getElementById('mChart'),'m');
  c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},grid:{left:60,right:40,top:20,bottom:30},xAxis:{type:'category',data:months},yAxis:{type:'value',name:'m³'},series:[{type:'bar',data:vals,itemStyle:{color:'#38bdf8',borderRadius:[4,4,0,0]},label:{show:true,position:'top',formatter:function(p){return fmt(p.value)},fontSize:11}}]});
  if(daily){
    var dDates=Object.keys(daily).sort(),dVals=dDates.map(function(d){return daily[d]});
    disposeChart('md');
    var cMd=initChart(document.getElementById('dailyChart'),'md');
    var dMa=calcMA(dVals,7);
    cMd.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{data:['日用水量','7天均值'],textStyle:{color:'#94a3b8'}},grid:{left:60,right:40,top:30,bottom:30},xAxis:{type:'category',data:dDates,axisLabel:{fontSize:9,rotate:45}},yAxis:{type:'value',name:'m³'},series:[{name:'日用水量',type:'bar',data:dVals,itemStyle:{color:'rgba(56,189,248,0.6)'},barMaxWidth:4},{name:'7天均值',type:'line',data:dMa,smooth:true,itemStyle:{color:'#fbbf24'},lineStyle:{width:2},showSymbol:false}]});
  }
}
