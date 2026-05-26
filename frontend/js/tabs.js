// === Tab 切換 ===
let _rendered=new Set(['home']);

function showTab(t){
  ['home','trend','rank','diff','anomaly','search','predict','dma','map'].forEach(p=>{
    var el=document.getElementById('page-'+p);
    if(el)el.classList.toggle('hidden',p!==t&&!(p==='dma'&&t==='dma'));
  });
  document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active')});
  var idx=['home','trend','rank','diff','anomaly','search','predict','map'].indexOf(t);
  if(idx>=0)document.querySelectorAll('.tab')[idx].classList.add('active');
  if(_rendered.has(t)){Object.values(charts).forEach(function(c){if(c)c.resize()});return;}
  _rendered.add(t);
  if(t==='trend')renderTrend();
  else if(t==='rank')renderRank();
  else if(t==='diff')renderDiff();
  else if(t==='anomaly')renderAnomaly();
  else if(t==='search')renderSearch();
  else if(t==='predict')renderPredict();
  else if(t==='map')renderMap();
  else Object.values(charts).forEach(function(c){if(c)c.resize()});
}

function pickDate(d){if(D.dates.includes(d)){selDate=d;renderHome()}}
function changeDate(d){var i=D.dates.indexOf(selDate);if(i+d>=0&&i+d<D.dates.length)pickDate(D.dates[i+d])}
function pickDma(d){selDma=d;renderDma();showTab('dma')}

// === 刷新資料 ===
function refreshData(){
  var btn=document.querySelector('.refresh-btn');
  if(btn)btn.classList.add('spinning');
  _rendered=new Set(['home']);
  Object.keys(charts).forEach(function(k){disposeChart(k)});
  loadData().then(function(){
    var cotaiKey2=D.dates.length?Object.keys(D.dma[0].dmas).find(k=>k.charCodeAt(1)===0xebf3):'';
    if(cotaiKey2)DC[cotaiKey2]='#f472b6';
    selDate=D.dates[D.dates.length-1];
    renderHome();
    if(btn){btn.classList.remove('spinning');}
  }).catch(function(e){
    alert('刷新失敗: '+e.message);
    if(btn)btn.classList.remove('spinning');
  });
}

window.addEventListener('resize',function(){Object.values(charts).forEach(function(c){if(c)c.resize()})});
