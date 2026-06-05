/* ACE Viewer - sessione/confronto (v1.8.0) */
let SYNC=null, SESSION=null;
const lapCache={}, rows=[], selectedKeys=new Set();
let selected=[], charts=[];
let mapMode="speed";
const extra=new Set();
let SERIES=null;
const BASE_CHARTS=["SPEED","THROTTLE","BRAKE","STEERANGLE"];

const PALETTE=["#19e6c8","#ff2e2e","#ffb020","#3d9bff","#b07bff","#33d17a","#ff7ad9","#9be15d"];
const key=(sid,n)=>`${sid}:${n}`;

function turbo(t){t=Math.max(0,Math.min(1,t));
  const r=Math.round(255*Math.max(0,Math.min(1,(34.61+t*(1172.33-t*(10793.56-t*(33300.12-t*(38394.49-t*14825.05)))))/255)));
  const g=Math.round(255*Math.max(0,Math.min(1,(23.31+t*(557.33+t*(1225.33-t*(3574.96-t*(1073.77+t*707.56)))))/255)));
  const b=Math.round(255*Math.max(0,Math.min(1,(27.2+t*(3211.1-t*(15327.97-t*(27814-t*(22569.18-t*6838.66)))))/255)));
  return `rgb(${r},${g},${b})`;}
function fmtDelta(s){return (s>=0?"+":"")+s.toFixed(3);}

function interpOnto(sx,sy,dx){const out=new Array(dx.length);let j=0;
  for(let i=0;i<dx.length;i++){const x=dx[i];
    while(j<sx.length-2&&sx[j+1]<x)j++;
    const x0=sx[j],x1=sx[j+1],y0=sy[j],y1=sy[j+1];
    out[i]=x1===x0?y0:y0+(y1-y0)*(x-x0)/(x1-x0);}
  return out;}

function rebuildSelected(){selected=[];
  rows.forEach(r=>{const k=key(r.sid,r.lapn);
    if(selectedKeys.has(k)&&lapCache[k])selected.push(Object.assign({key:k},r,lapCache[k]));});
  selected.sort((a,b)=>a.time-b.time);
  selected.forEach((l,i)=>l.color=i===0?"#ffffff":PALETTE[i%PALETTE.length]);}
function refLap(){return selected[0];}

async function ensureLoaded(sid,lapn){const k=key(sid,lapn);if(lapCache[k])return;
  if(sid===SID&&SESSION.lap_data[lapn]){const lap=SESSION.laps.find(l=>l.n===lapn)||{};
    lapCache[k]={data:SESSION.lap_data[lapn],time_str:lap.time_str,time:lap.time,driver:SESSION.driver,
      stats:{v_max:lap.v_max,v_min:lap.v_min,v_avg:lap.v_avg,rpm_max:lap.rpm_max,full_throttle_pct:lap.full_throttle_pct}};
  }else{const r=await fetch(`/api/lap/${sid}/${lapn}`);const j=await r.json();
    lapCache[k]={data:j.data,time_str:j.time_str,time:j.time,driver:j.driver,stats:j.stats};}}
async function ensureChannel(l,name){
  if(l.data.channels[name]!==undefined)return;
  const r=await fetch(`/api/lapchannel/${l.sid}/${l.lapn}/${encodeURIComponent(name)}`);
  const j=await r.json(); l.data.channels[name]=j.values; lapCache[l.key].data.channels[name]=j.values;}

async function toggle(sid,lapn,on){const k=key(sid,lapn);
  if(on){await ensureLoaded(sid,lapn);selectedKeys.add(k);}else selectedKeys.delete(k);
  await renderAll();}

function renderLapTable(){const body=document.getElementById("laps-body");body.innerHTML="";
  const best=Math.min(...rows.map(r=>r.time));
  rows.forEach(r=>{const k=key(r.sid,r.lapn);const sel=selectedKeys.has(k);
    const col=sel?(selected.find(s=>s.key===k)||{}).color:null;
    const tr=document.createElement("tr");if(sel)tr.classList.add("sel");
    tr.innerHTML=`<td><input type="checkbox" ${sel?"checked":""}></td>
      <td>${r.driver}${r.fromCurrent?"":' <span class="tag">altra sess.</span>'}</td>
      <td>#${r.lapn}</td><td class="num">${r.time_str}</td>
      <td class="num" style="color:${r.time===best?'var(--accent2)':'var(--muted)'}">${r.time===best?'best':fmtDelta(r.time-best)}</td>
      <td class="num">${r.vmax??'-'}</td>`;
    if(col)tr.style.boxShadow=`inset 4px 0 0 ${col}`;
    tr.querySelector("input").onchange=(e)=>toggle(r.sid,r.lapn,e.target.checked);
    body.appendChild(tr);});}

function renderStats(){const ref=refLap();const el=document.getElementById("stats-body");
  if(!ref){el.innerHTML='<p style="color:var(--dim)">Nessun giro selezionato.</p>';return;}
  const s=ref.stats;
  el.innerHTML=[["Pilota",ref.driver],["Giro","#"+ref.lapn+(selected.length>1?" (rif.)":"")],
    ["Tempo",ref.time_str],["V max",(s.v_max??'-')+" km/h"],["V min",(s.v_min??'-')+" km/h"],
    ["V media",(s.v_avg??'-')+" km/h"],["RPM max",s.rpm_max??'-'],["Pieno gas",(s.full_throttle_pct??'-')+" %"]
  ].map(([k,v])=>`<div class="srow"><span class="sk">${k}</span><span class="sv">${v}</span></div>`).join("");}

// ---- mappa: allineamento di piu' giri + zoom/pan ----
const cv=document.getElementById("map"),ctx=cv.getContext("2d");
let mapZoom=1, mapPanX=0, mapPanY=0;
let mapPaths=[];
let mapMeta=null;

function alignPoints(ref, oth){
  const n=Math.min(ref.x.length,oth.x.length);
  let ax=0,ay=0,bx=0,by=0;
  for(let i=0;i<n;i++){ax+=ref.x[i];ay+=ref.y[i];bx+=oth.x[i];by+=oth.y[i];}
  ax/=n;ay/=n;bx/=n;by/=n;
  let num=0,den=0;
  for(let i=0;i<n;i++){const rx=ref.x[i]-ax,ry=ref.y[i]-ay,ox=oth.x[i]-bx,oy=oth.y[i]-by;
    num+=ox*ry-oy*rx; den+=ox*rx+oy*ry;}
  const th=Math.atan2(num,den),c=Math.cos(th),s=Math.sin(th);
  const out={x:new Array(oth.x.length),y:new Array(oth.y.length)};
  for(let i=0;i<oth.x.length;i++){const ox=oth.x[i]-bx,oy=oth.y[i]-by;
    out.x[i]=ax+(c*ox-s*oy); out.y[i]=ay+(s*ox+c*oy);}
  return out;}

function computeMap(){mapPaths=[];const ref=refLap();if(!ref)return;
  const coords=selected.map((l,i)=> i===0 ? {x:l.data.x,y:l.data.y} : alignPoints(ref.data,l.data));
  let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
  coords.forEach(co=>{for(let i=0;i<co.x.length;i++){
    if(co.x[i]<xmin)xmin=co.x[i];if(co.x[i]>xmax)xmax=co.x[i];
    if(co.y[i]<ymin)ymin=co.y[i];if(co.y[i]>ymax)ymax=co.y[i];}});
  const pad=40,w=cv.width,h=cv.height;
  const s=Math.min((w-2*pad)/((xmax-xmin)||1),(h-2*pad)/((ymax-ymin)||1));
  const ox=(w-(xmax-xmin)*s)/2,oy=(h-(ymax-ymin)*s)/2;
  const bx=(x)=>w-(ox+(x-xmin)*s), by=(y)=>h-(oy+(y-ymin)*s);
  coords.forEach((co,k)=>{const base=new Array(co.x.length);
    for(let i=0;i<co.x.length;i++)base[i]={X:bx(co.x[i]),Y:by(co.y[i])};
    mapPaths.push({color:selected[k].color,isRef:k===0,base});});
  const c=ref.data.channels.SPEED;mapMeta={vmin:Math.min(...c),vmax:Math.max(...c)};
  mapMeta.span=(mapMeta.vmax-mapMeta.vmin)||1;}

function zp(p){const cx=cv.width/2,cy=cv.height/2;
  return {X:(p.X-cx)*mapZoom+cx+mapPanX, Y:(p.Y-cy)*mapZoom+cy+mapPanY};}
function segColor(ref,i){
  if(mapMode==="speed")return turbo((ref.data.channels.SPEED[i]-mapMeta.vmin)/mapMeta.span);
  const br=ref.data.channels.BRAKE[i],th=ref.data.channels.THROTTLE[i];
  if(br>3){const g=Math.round(120-Math.min(br,100)*1.1);return `rgb(255,${Math.max(20,g)},${Math.max(20,g)})`;}
  if(th>90)return "#1ee65a"; if(th>3)return "#9bd24a"; return "#566";}
function drawMap(){ctx.clearRect(0,0,cv.width,cv.height);const ref=refLap();if(!ref||!mapPaths.length)return;
  ctx.lineCap="round";ctx.lineJoin="round";
  const multi=selected.length>1;
  if(!multi&&(mapMode==="speed"||mapMode==="input")){
    const base=mapPaths[0].base;ctx.lineWidth=Math.max(2,5*Math.min(mapZoom,2));
    for(let i=1;i<base.length;i++){ctx.strokeStyle=segColor(ref,i);
      const a=zp(base[i-1]),b=zp(base[i]);ctx.beginPath();ctx.moveTo(a.X,a.Y);ctx.lineTo(b.X,b.Y);ctx.stroke();}
    document.getElementById("map-legend").textContent= mapMode==="speed"
      ? `velocità ${mapMeta.vmin.toFixed(0)}–${mapMeta.vmax.toFixed(0)} km/h (blu→rosso)`
      : "rosso = frenata · verde = pieno gas · grigio = rilascio";
  }else{
    mapPaths.forEach(P=>{ctx.strokeStyle=P.color;ctx.lineWidth=P.isRef?3.2:2.2;
      ctx.beginPath();const p0=zp(P.base[0]);ctx.moveTo(p0.X,p0.Y);
      for(let i=1;i<P.base.length;i++){const p=zp(P.base[i]);ctx.lineTo(p.X,p.Y);}ctx.stroke();});
    document.getElementById("map-legend").innerHTML=
      selected.map(l=>`<span style="color:${l.color}">&#9632;</span> ${l.driver} #${l.lapn}`).join(" &nbsp; ");
  }}
function drawDot(i){drawMap();if(i==null||!mapPaths.length)return;
  const p=zp(mapPaths[0].base[Math.max(0,Math.min(i,mapPaths[0].base.length-1))]);
  ctx.beginPath();ctx.arc(p.X,p.Y,7,0,7);ctx.fillStyle="#fff";ctx.fill();
  ctx.lineWidth=2;ctx.strokeStyle="#ff2e2e";ctx.stroke();}

cv.addEventListener("wheel",e=>{e.preventDefault();
  const r=cv.getBoundingClientRect();
  const mx=(e.clientX-r.left)*cv.width/r.width, my=(e.clientY-r.top)*cv.height/r.height;
  const f=e.deltaY<0?1.15:1/1.15, nz=Math.max(1,Math.min(8,mapZoom*f)), af=nz/mapZoom;
  const cx=cv.width/2,cy=cv.height/2;
  mapPanX=mx-cx-(mx-cx-mapPanX)*af; mapPanY=my-cy-(my-cy-mapPanY)*af; mapZoom=nz;
  if(mapZoom===1){mapPanX=0;mapPanY=0;} drawMap();},{passive:false});
(function panMap(){let d=null;
  cv.addEventListener("mousedown",e=>{d={x:e.clientX,y:e.clientY,px:mapPanX,py:mapPanY};});
  window.addEventListener("mousemove",e=>{if(!d)return;const r=cv.getBoundingClientRect();
    mapPanX=d.px+(e.clientX-d.x)*cv.width/r.width; mapPanY=d.py+(e.clientY-d.y)*cv.height/r.height; drawMap();});
  window.addEventListener("mouseup",()=>d=null);})();
function zoomBy(f){const nz=Math.max(1,Math.min(8,mapZoom*f));mapPanX*=nz/mapZoom;mapPanY*=nz/mapZoom;mapZoom=nz;
  if(mapZoom===1){mapPanX=0;mapPanY=0;}drawMap();}

// ---- box valori trascinabile ----
const vb=document.getElementById("valbox");
function updateValbox(idx){if(!SERIES||idx==null)return;
  let html=`<div class="vb-head">@ ${Math.round(SERIES.X[idx])} m</div>`;
  selected.forEach((l,k)=>{html+=`<div class="vb-row"><span class="vb-dot" style="background:${l.color}"></span>`+
    `<span class="vb-lbl">${l.driver} #${l.lapn}</span>`+
    `<span class="vb-vals">v ${SERIES.SPEED[k][idx].toFixed(0)} · gas ${SERIES.THROTTLE[k][idx].toFixed(0)} · fr ${SERIES.BRAKE[k][idx].toFixed(0)} · Δ ${fmtDelta(SERIES.delta[k][idx])}</span></div>`;});
  vb.innerHTML=html;vb.hidden=false;}
(function dragVb(){let d=null;
  vb.addEventListener("mousedown",e=>{d={x:e.clientX-vb.offsetLeft,y:e.clientY-vb.offsetTop};e.preventDefault();});
  window.addEventListener("mousemove",e=>{if(d){vb.style.left=(e.clientX-d.x)+"px";vb.style.top=(e.clientY-d.y)+"px";vb.style.right="auto";vb.style.bottom="auto";}});
  window.addEventListener("mouseup",()=>d=null);})();

// ---- grafici ----
function mkChart(cont,title,arrays,X,opts){opts=opts||{};
  const box=document.createElement("div");box.className="chart-box";
  const ttl=document.createElement("div");ttl.className="ttl";
  ttl.innerHTML=`<span>${title}</span><span class="readout"></span>`;
  box.appendChild(ttl);cont.appendChild(box);
  const refk=refLap().key;
  const uSeries=[{}].concat(selected.map(l=>({label:l.label,stroke:l.color,
    width:l.key===refk?2:1.3,value:(u,v)=>v==null?"--":v.toFixed(opts.dp??1)})));
  const u=new uPlot({width:box.clientWidth-24,height:opts.h||130,
    scales:{x:{time:false},y:opts.range?{range:opts.range}:{}},series:uSeries,legend:{show:false},
    axes:[{stroke:"#8b95a3",grid:{stroke:"#222"},values:(u,v)=>v.map(x=>x+"m")},
          {stroke:"#8b95a3",grid:{stroke:"#1a1f27"}}],
    cursor:{sync:{key:"ace",setSeries:true},points:{size:5}},
    hooks:{setCursor:[u=>{const i=u.cursor.idx;
      if(i==null){drawDot(null);return;}drawDot(i);updateValbox(i);}]},
  },[X].concat(arrays),box);
  if(SYNC)SYNC.sub(u);charts.push(u);}

async function buildCharts(){const cont=document.getElementById("charts");
  cont.querySelectorAll(".chart-box").forEach(b=>b.remove());charts.length=0;
  const ref=refLap();if(!ref||!window.uPlot)return;
  if(!SYNC){try{SYNC=uPlot.sync("ace");}catch(e){}}
  const X=ref.data.dist;
  for(const name of extra) for(const l of selected) await ensureChannel(l,name);
  const chan=name=>selected.map(l=>interpOnto(l.data.dist,l.data.channels[name],X));
  const refT=ref.data.time;
  const delta=selected.map(l=>{const tOn=interpOnto(l.data.dist,l.data.time,X);return X.map((_,i)=>tOn[i]-refT[i]);});
  SERIES={X,SPEED:chan("SPEED"),THROTTLE:chan("THROTTLE"),BRAKE:chan("BRAKE"),delta};
  try{
    mkChart(cont,"Velocità (km/h)",SERIES.SPEED,X);
    mkChart(cont,"Δ tempo vs riferimento (s)",delta,X,{dp:3,h:110});
    mkChart(cont,"Gas (%)",SERIES.THROTTLE,X,{range:[0,100]});
    mkChart(cont,"Freno (%)",SERIES.BRAKE,X,{range:[0,100]});
    mkChart(cont,"Sterzo (°)",chan("STEERANGLE"),X);
    for(const name of extra) mkChart(cont,name,chan(name),X);
  }catch(e){console.error("Grafici:",e);}}

// ---- modali ----
function openModal(id){document.getElementById(id).hidden=false;}
function closeModal(id){document.getElementById(id).hidden=true;}
function renderChanPick(){const el=document.getElementById("chanpick");
  const names=(SESSION.meta.channel_names||[]).filter(n=>!BASE_CHARTS.includes(n));
  if(!names.length){el.innerHTML='<p style="color:var(--dim)">Nessun canale extra disponibile.</p>';return;}
  el.innerHTML=names.map(n=>`<label><input type="checkbox" value="${n}" ${extra.has(n)?"checked":""}>${n}</label>`).join("");
  el.querySelectorAll("input").forEach(inp=>inp.onchange=async(e)=>{
    if(e.target.checked)extra.add(e.target.value);else extra.delete(e.target.value);
    await buildCharts();});}

// ---- confronto cross-sessione (modale, si chiude dopo la scelta) ----
async function openCompare(){
  const body=document.getElementById("compare-body");
  body.innerHTML='<p style="color:var(--dim)">Carico...</p>';openModal("compare-modal");
  const r=await fetch(`/api/track/${encodeURIComponent(SESSION.track)}`);const j=await r.json();
  const others=j.sessions.filter(s=>s.id!==SID);
  if(!others.length){body.innerHTML='<p style="color:var(--dim)">Nessun\'altra sessione su questa pista per ora.</p>';return;}
  body.innerHTML=others.map(s=>`<div class="cmp-sess"><div class="cmp-h"><b>${s.driver}</b> · ${s.car} <span class="cmp-d">${s.date}</span></div><div class="cmp-laps">`+
      s.laps.map(l=>`<button class="chip cmp-lap" data-sid="${s.id}" data-lap="${l.n}">#${l.n} · ${l.time_str}</button>`).join("")+`</div></div>`).join("");
  body.querySelectorAll(".cmp-lap").forEach(b=>{b.onclick=async()=>{
    const sid=b.dataset.sid,lapn=parseInt(b.dataset.lap);
    if(!rows.find(r=>r.sid===sid&&r.lapn===lapn)){await ensureLoaded(sid,lapn);const c=lapCache[key(sid,lapn)];
      rows.push({sid,lapn,driver:c.driver,time_str:c.time_str,time:c.time,vmax:c.stats.v_max,fromCurrent:false});}
    selectedKeys.add(key(sid,lapn));
    closeModal("compare-modal");
    await renderAll();};});}

async function renderAll(){rebuildSelected();
  selected.forEach(l=>l.label=`${l.driver} #${l.lapn} ${l.time_str}`);
  computeMap();renderLapTable();renderStats();drawMap();await buildCharts();}

async function init(){const r=await fetch(`/api/session/${SID}`);SESSION=await r.json();
  document.getElementById("track-name").textContent="· "+SESSION.track;
  const w=SESSION.meta.weather||{};
  document.getElementById("weather").textContent =
    (w.air_temp!=null)?`Aria ${w.air_temp}° · Asfalto ${w.road_temp}°`:"";
  document.getElementById("laps-note").textContent =
    SESSION.best_lap?'Spunta più giri per sovrapporli; sulla mappa vedi le traiettorie di tutti. Rotella per zoomare, trascina per spostare.'
                    :"Nessun giro completo in questa sessione.";
  SESSION.laps.filter(l=>l.complete).forEach(l=>rows.push(
    {sid:SID,lapn:l.n,driver:SESSION.driver,time_str:l.time_str,time:l.time,vmax:l.v_max,fromCurrent:true}));
  if(SESSION.best_lap){await ensureLoaded(SID,SESSION.best_lap);selectedKeys.add(key(SID,SESSION.best_lap));}
  document.getElementById("add-compare").onclick=openCompare;
  document.getElementById("compare-close").onclick=()=>closeModal("compare-modal");
  document.getElementById("chan-open").onclick=()=>{renderChanPick();openModal("chan-modal");};
  document.getElementById("chan-close").onclick=()=>closeModal("chan-modal");
  document.querySelectorAll(".modal").forEach(m=>m.addEventListener("click",e=>{if(e.target===m)m.hidden=true;}));
  document.querySelectorAll(".mode-btn").forEach(b=>b.onclick=()=>{
    mapMode=b.dataset.mode;
    document.querySelectorAll(".mode-btn").forEach(x=>x.classList.toggle("active",x===b));
    drawMap();});
  document.getElementById("zoom-in").onclick=()=>zoomBy(1.3);
  document.getElementById("zoom-out").onclick=()=>zoomBy(1/1.3);
  document.getElementById("zoom-reset").onclick=()=>{mapZoom=1;mapPanX=0;mapPanY=0;drawMap();};
  await renderAll();}
init();
