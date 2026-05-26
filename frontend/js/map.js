// === 地圖頁 ===
let _leafletMap=null;

async function renderMap(){
  const container=document.getElementById('page-map');
  if(!container)return;
  if(_leafletMap){_leafletMap.remove();_leafletMap=null;}
  container.innerHTML='<div id="mapLayout"><div id="mapContainer"></div><div id="mapDetail" class="card"></div></div>';
  try{
    const geoResp=await fetch('data/dma_zones.geojson?v='+Date.now());
    const geoData=await geoResp.json();
    const dmaData=findD(D.dma,selDate);
    if(!dmaData){container.innerHTML='<div class="card"><h2>無資料</h2></div>';return;}

    // 計算各 DMA 資料（處理私用區字符）
    var dmaInfo={};
    var dataKeys=Object.keys(dmaData.dmas);
    geoData.features.forEach(function(f){
      var code=f.properties.dma;
      var zhName=getDmaName(code)||f.properties.name_zh||code;
      var info=dmaData.dmas[zhName];
      if(!info){
        for(var ki=0;ki<dataKeys.length;ki++){
          if(dataKeys[ki]!==zhName&&dataKeys[ki].slice(0,1)===zhName.slice(0,1)&&dataKeys[ki].slice(2)===zhName.slice(2)){
            zhName=dataKeys[ki];info=dmaData.dmas[zhName];break;
          }
        }
      }
      dmaInfo[code]={zhName:zhName,info:info};
    });

    var maxVal=1;
    for(var k in dmaInfo){if(dmaInfo[k].info&&dmaInfo[k].info.total>maxVal)maxVal=dmaInfo[k].info.total;}

    // 更精細的顏色漸變
    function getColor(val){
      var r=Math.min(val/maxVal,1);
      // 從綠到紫的漸變
      var colors=[
        [52,211,153],  // 綠
        [251,191,36],  // 黃
        [244,114,182], // 粉
        [167,139,250], // 紫
        [129,140,248]  // 藍紫
      ];
      var idx=r*(colors.length-1);
      var lo=Math.floor(idx),hi=Math.ceil(idx),t=idx-lo;
      if(lo===hi)return 'rgb('+colors[lo].join(',')+')';
      var c=colors[lo].map(function(v,i){return Math.round(v+(colors[hi][i]-v)*t)});
      return 'rgb('+c.join(',')+')';
    }

    document.getElementById('mapDetail').innerHTML='<div class="map-placeholder"><div>點擊地圖上的 DMA 區域<br>查看用水詳情</div></div>';

    _leafletMap=L.map('mapContainer',{zoomControl:true,attributionControl:false,minZoom:12,maxZoom:16}).setView([22.15,113.55],14);
    // 使用暗色地圖瓦片
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
      attribution:'© OpenStreetMap · CARTO',maxZoom:18
    }).addTo(_leafletMap);

    var selectedLayer=null;

    const geoLayer=L.geoJSON(geoData,{
      style:function(feature){
        var d=dmaInfo[feature.properties.dma];
        var val=d&&d.info?d.info.total:0;
        return{
          fillColor:getColor(val),
          fillOpacity:0.45,
          color:'rgba(255,255,255,0.3)',
          weight:1.5,
          opacity:0.8
        };
      },
      onEachFeature:function(feature,layer){
        var d=dmaInfo[feature.properties.dma];
        if(!d||!d.info)return;
        var zhName=d.zhName,info=d.info;

        // Hover 效果
        layer.on('mouseover',function(e){
          this.setStyle({fillOpacity:0.7,weight:2.5,color:'#fff'});
          this.bringToFront();
        });
        layer.on('mouseout',function(e){
          if(selectedLayer!==this){
            geoLayer.resetStyle(this);
          }
        });

        // 富文本 Tooltip
        var pct=info.total>0?Math.round(info.residential/info.total*100):0;
        layer.bindTooltip(
          '<div style="font-size:14px;font-weight:700;margin-bottom:4px">'+zhName+'</div>'
          +'<div style="color:#94a3b8;font-size:12px">總用水: <b style="color:#e4e4ed">'+Math.round(info.total).toLocaleString()+'</b> m³</div>'
          +'<div style="color:#94a3b8;font-size:12px">住宅: <span style="color:#34d399">'+pct+'%</span> · 非住宅: <span style="color:#f472b6">'+(100-pct)+'%</span></div>'
          +'<div style="color:#6b6b80;font-size:11px;margin-top:4px">'+info.resCount+'+'+info.nonResCount+' 表</div>',
          {sticky:true,className:'dma-tooltip',direction:'top'}
        );

        // 點擊詳情
        layer.on('click',function(){
          // 高亮選中
          if(selectedLayer)geoLayer.resetStyle(selectedLayer);
          selectedLayer=this;
          this.setStyle({fillOpacity:0.85,weight:3,color:'#818cf8'});

          var dayTop20=D.top20dma&&D.top20dma.length>0?D.top20dma[D.top20dma.length-1]:null;
          var top20m=dayTop20&&dayTop20.byDma&&dayTop20.byDma[zhName]?dayTop20.byDma[zhName].slice(0,20):[];
          var dmaColor=getDmaColor(zhName)||'#818cf8';

          var detail='<h2 style="display:flex;align-items:center;gap:8px"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:'+dmaColor+'"></span>'+zhName+'<span class="hint">'+selDate+'</span></h2>'
            +'<div class="sr">'
            +'<div class="si"><div class="sl">總用水</div><div class="sv">'+Math.round(info.total).toLocaleString()+'</div><div class="ss">m³</div></div>'
            +'<div class="si res"><div class="sl">住宅</div><div class="sv">'+Math.round(info.residential).toLocaleString()+'</div><div class="ss">'+info.resCount+'表 | '+pct+'%</div></div>'
            +'<div class="si nonres"><div class="sl">非住宅</div><div class="sv">'+Math.round(info.nonResidential).toLocaleString()+'</div><div class="ss">'+info.nonResCount+'表 | '+(100-pct)+'%</div></div>'
            +'</div>';
          if(top20m.length>0){
            detail+='<div class="chart-actions"><button class="export-btn" onclick="exportChart(\'mapDma\',\''+zhName+'Top50\')">匯出 PNG</button></div><div id="mapDmaChart" class="chart" style="height:320px"></div>';
          }
          document.getElementById('mapDetail').innerHTML=detail;

          if(top20m.length>0){
            var chartDom=document.getElementById('mapDmaChart');
            if(chartDom){
              disposeChart('mapDma');
              var c=initChart(chartDom,'mapDma');
              var revItems=top20m.slice().reverse();
              c.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(p){var m=revItems[p[0].dataIndex];return '<b>'+mask(m.contractId||m.meterId)+'</b><br/>'+esc(m.propertyType||'')+'<br/>'+fmt(m.total)+' m³';}},grid:{left:100,right:50,top:10,bottom:20},xAxis:{type:'value',axisLabel:{formatter:function(v){return(v/1000).toFixed(0)+'k'},fontSize:10}},yAxis:{type:'category',data:revItems.map(function(i){return mask(i.contractId||i.meterId)}),axisLabel:{fontSize:9}},series:[{type:'bar',data:revItems.map(function(i){return{value:i.total,itemStyle:{color:dmaColor}}}),label:{show:true,position:'right',formatter:function(p){return fmt(p.value)},fontSize:9}}]});
            }
          }
        });
      }
    }).addTo(_leafletMap);

    // 在每個 DMA 區域中心添加標籤
    geoLayer.eachLayer(function(layer){
      if(layer.feature&&layer.feature.properties){
        var d=dmaInfo[layer.feature.properties.dma];
        if(!d||!d.info)return;
        var center=layer.getBounds().getCenter();
        var label=L.marker(center,{
          icon:L.divIcon({
            className:'',
            html:'<div style="text-align:center;pointer-events:none;text-shadow:0 1px 4px rgba(0,0,0,0.8)"><div style="font-size:13px;font-weight:700;color:#e4e4ed;white-space:nowrap">'+d.zhName+'</div><div style="font-size:11px;color:#94a3b8;white-space:nowrap">'+Math.round(d.info.total).toLocaleString()+' m³</div></div>',
            iconSize:[120,40],
            iconAnchor:[60,20]
          })
        }).addTo(_leafletMap);
      }
    });

    _leafletMap.fitBounds(geoLayer.getBounds(),{padding:[20,15]});
    setTimeout(function(){_leafletMap.invalidateSize();},100);

    // 圖例
    const legend=L.control({position:'bottomright'});
    legend.onAdd=function(){
      const div=L.DomUtil.create('div','info legend');
      div.style.cssText='background:rgba(19,19,26,0.92);padding:12px 14px;border-radius:10px;border:1px solid #252532;color:#e4e4ed;font-size:12px;backdrop-filter:blur(8px)';
      div.innerHTML='<div style="font-weight:700;margin-bottom:8px">用水量</div>'
        +'<div style="display:flex;align-items:center;gap:6px;margin:4px 0"><span style="background:#818cf8;width:14px;height:10px;border-radius:2px;display:inline-block"></span> 高</div>'
        +'<div style="display:flex;align-items:center;gap:6px;margin:4px 0"><span style="background:#a78bfa;width:14px;height:10px;border-radius:2px;display:inline-block"></span> 中高</div>'
        +'<div style="display:flex;align-items:center;gap:6px;margin:4px 0"><span style="background:#f472b6;width:14px;height:10px;border-radius:2px;display:inline-block"></span> 中低</div>'
        +'<div style="display:flex;align-items:center;gap:6px;margin:4px 0"><span style="background:#34d399;width:14px;height:10px;border-radius:2px;display:inline-block"></span> 低</div>'
        +'<div style="color:#6b6b80;font-size:10px;margin-top:8px;border-top:1px solid #252532;padding-top:6px">'+selDate+'</div>';
      return div;
    };
    legend.addTo(_leafletMap);
  }catch(e){
    container.innerHTML='<div class="card"><h2>地圖載入失敗</h2><p>'+e.message+'</p></div>';
  }
}
