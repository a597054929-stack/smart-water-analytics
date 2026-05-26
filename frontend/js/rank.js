// === 排名頁 ===
function renderRank(){
  var h='<section class="card"><h2>📈 Top50 排名追蹤 <span class="hint">（進入Top50次數最多的水表）</span> <span style="float:right;cursor:pointer;color:var(--muted);font-size:11px" onclick="exportRankCsv()">💾 匯出CSV</span></h2><table><thead><tr><th>#</th><th>合同編號</th><th>建築物</th><th>DMA</th><th>天數</th><th>平均排名</th><th class="num">平均用水</th><th>趨勢</th></tr></thead><tbody>';
  D.rank.forEach(function(r,i){var tc=r.trend==='↑'?'up':r.trend==='↓'?'down':'';h+='<tr><td>'+(i+1)+'</td><td class="contract">'+mask(r.contractId)+'</td><td class="'+(isUnlocked?'':'masked')+'" onclick="clickMasked()">'+maskBuilding(r.buildingName)+'</td><td><span class="tag" style="background:'+(DC[r.dma]||'#666')+'">'+esc(r.dma)+'</span></td><td>'+r.daysInTop20+'/'+D.dates.length+'</td><td>'+r.avgRank+'</td><td class="num">'+fmt(r.avgTotal)+'</td><td class="'+tc+'">'+r.trend+'</td></tr>';});
  h+='</tbody></table></section>';
  document.getElementById('page-rank').innerHTML=h;
}

function exportRankCsv(){
  var rows=[['排名','合同編號','建築物','DMA','Top50天數','平均排名','平均用水']];
  D.rank.forEach(function(r,i){rows.push([i+1,r.contractId||'',r.buildingName||'',r.dma||'',r.daysInTop20,r.avgRank,Math.round(r.avgTotal||0)])});
  exportCsv(rows,'rank_top50.csv');
}
