// === 日曆頁 & 熱力圖 ===
function renderCalendar(){
  var byMonth={};D.cotai.forEach(function(d){var m=d.date.substring(0,7);if(!byMonth[m])byMonth[m]=[];byMonth[m].push(d);});
  var months=Object.keys(byMonth).sort();
  if(!months.length){document.getElementById('page-calendar').innerHTML='<section class="card"><p style="color:#64748b">暫無資料</p></section>';return;}
  if(!window._calMonth)window._calMonth=months[months.length-1];
  var years={};months.forEach(function(m){var y=m.substring(0,4);if(!years[y])years[y]=[];years[y].push(m);});
  var yearList=Object.keys(years).sort();
  if(!window._calYear)window._calYear=yearList[yearList.length-1];
  var curMonths=years[window._calYear]||[];
  var h='<section class="card"><h2>📅 路氹城非住宅用水日曆</h2>';
  h+='<div class="ms" style="margin-bottom:8px">';
  yearList.forEach(function(y){h+='<button class="mb '+(y===window._calYear?'active':'')+'" onclick="window._calYear=\''+y+'\';window._calMonth=\''+years[y][years[y].length-1]+'\';renderCalendar()">'+y+'年</button>';});
  h+='</div>';
  h+='<div class="ms">';
  for(var mi=1;mi<=12;mi++){
    var ms=window._calYear+'-'+(mi<10?'0':'')+mi;
    var has=curMonths.indexOf(ms)>=0;
    var active=ms===window._calMonth;
    h+='<button class="mb '+(active?'active':'')+'" style="'+(has?'':'opacity:0.3;cursor:default')+'" onclick="'+(has?'window._calMonth=\''+ms+'\';renderCalendar()':'')+'">'+mi+'月</button>';
  }
  h+='</div>';
  var month=window._calMonth;
  var days=byMonth[month];
  if(days){
    var maxT=0;days.forEach(function(d){var t=0;d.items.forEach(function(i){t+=i.total});if(t>maxT)maxT=t;});
    var fd=new Date(month+'-01').getDay(),dim=new Date(parseInt(month.split('-')[0]),parseInt(month.split('-')[1]),0).getDate();
    h+='<div class="cg">';
    ['日','一','二','三','四','五','六'].forEach(function(d){h+='<div class="ch">'+d+'</div>';});
    for(var i=0;i<fd;i++)h+='<div></div>';
    for(var dd=1;dd<=dim;dd++){
      var ds=month+'-'+(dd<10?'0':'')+dd;
      var dayD=days.find(function(x){return x.date===ds});
      var total=dayD?dayD.items.reduce(function(s,i){return s+i.total},0):0;
      var inten=maxT>0?total/maxT:0;
      var r=Math.round(239*inten),g=Math.round(68*inten),b=Math.round(68*inten);
      var bg=total>0?'rgb('+(r+20)+','+(g+20)+','+(b+20)+')':'#1e293b';
      var dayTotal=0;
      var tt=D.trend.find(function(x){return x.date===ds});
      if(tt){var dmas=tt.dmas;for(var dk in dmas)dayTotal+=dmas[dk];}
      var totalLabel=dayTotal>0?fmt(dayTotal)+'m³':'';
      h+='<div class="cc" style="background:'+bg+'" onclick="showCotaiDay(\''+ds+'\')" title="'+ds+': '+fmt(dayTotal)+' m³">'+dd+'<span class="cdt">'+totalLabel+'</span></div>';
    }
    h+='</div>';
  }else{
    h+='<p style="color:#64748b;text-align:center;padding:20px">'+month+' 無資料</p>';
  }
  h+='<div id="cotaiD" style="margin-top:12px"></div></section>';
  document.getElementById('page-calendar').innerHTML=h;
}

function showCotaiDay(date){
  var day=D.cotai.find(function(d){return d.date===date});
  if(!day){document.getElementById('cotaiD').innerHTML='<p style="color:#64748b">該日無資料</p>';return;}
  var h='<div class="card"><h2>'+date+' 路氹非住宅Top10</h2><table><thead><tr><th>#</th><th>合同編號</th><th>建築物</th><th class="num">用水量</th></tr></thead><tbody>';
  day.items.sort(function(a,b){return b.total-a.total}).slice(0,10).forEach(function(m,i){h+='<tr><td>'+(i+1)+'</td><td class="contract">'+mask(m.contractId)+'</td><td class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(m.buildingName)+'</td><td class="num">'+fmt(m.total)+'</td></tr>';});
  h+='</tbody></table></div>';
  document.getElementById('cotaiD').innerHTML=h;
}

function renderHeatmap(){
  var monthly=D.meterMonthly;
  var totals=[];
  Object.keys(monthly).forEach(function(id){var sum=0;Object.keys(monthly[id]).forEach(function(m){sum+=monthly[id][m]});totals.push({id:id,total:sum});});
  totals.sort(function(a,b){return b.total-a.total});
  var topIds=totals.slice(0,60).map(function(x){return x.id});
  var anomIds={};D.anomalies.forEach(function(a){anomIds[a.meterId]=true});
  Object.keys(anomIds).forEach(function(id){if(topIds.indexOf(id)<0&&topIds.length<80)topIds.push(id)});
  topIds=topIds.slice(0,70);
  var dates=D.dates;var data=[];
  topIds.forEach(function(mid,mi){var md=D.meterDaily[mid];if(!md)return;dates.forEach(function(d,di){var v=md[d];if(v!==undefined&&v>0){data.push([di,mi,Math.round(v)])}});});
  var searchMap={};D.search.forEach(function(s){searchMap[s.id]=s.contract||''});
  var meterLabels=topIds.map(function(id){return searchMap[id]?mask(searchMap[id]):id});
  var h='<section class="card"><h2>🔥 用水熱力圖 <span class="hint">(Top'+topIds.length+'水表)</span></h2><div id="hmChart" class="chart" style="height:'+(Math.max(400,topIds.length*20))+'px"></div></section>';
  document.getElementById('page-heatmap').innerHTML=h;
  disposeChart('hm');
  var c=initChart(document.getElementById('hmChart'),'hm');
  c.setOption({backgroundColor:'transparent',tooltip:{position:'top',formatter:function(p){return p.value[2]+'m³<br>'+dates[p.value[0]]+'<br>'+meterLabels[p.value[1]]}},grid:{left:120,right:20,top:20,bottom:60},xAxis:{type:'category',data:dates,axisLabel:{rotate:45,fontSize:9}},yAxis:{type:'category',data:meterLabels,axisLabel:{fontSize:10},inverse:true},visualMap:{min:0,max:500,calculable:true,orient:'vertical',left:'left',top:'center',inRange:{color:['#13131a','#1e3a5f','#2563eb','#818cf8','#fbbf24','#f87171']},text:['高','低']},series:[{type:'heatmap',data:data,label:{show:false},emphasis:{itemStyle:{shadowBlur:10,shadowColor:'rgba(0,0,0,.5)'}}}]});
}
