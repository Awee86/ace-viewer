/* ACE Viewer - sessione/confronto (v1.9.0) */
let SYNC=null, SESSION=null, CORNERS=[];
const lapCache={}, rows=[], selectedKeys=new Set();
let selected=[], charts=[];
let mapMode="speed";
const extra=new Set();
let SERIES=null;
const BASE_CHARTS=["SPEED","THROTTLE","BRAKE"];   // sterzo NON di default
const PALETTE=["#19e6c8","#ff7ad9","#ffb020","#3d9bff","#b07bff","#33d17a","#9be15d"];
const GREY="#3a4250";
const key=(sid,n)=>`${sid}:${n}`;

function hx(h){h=h.replace('#','');if(h.length===3)h=h.split('').map(c=>c+c).join('');
  return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
function mix(c1,c2,t){const a=hx(c1),b=hx(c2);return `rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*t)).join(',')})`;}
function turbo(t){t=Math.max(0,Math.min(1,t));
  const r=Math.round(255*Math.max(0,Math.min(1,(34.61+t*(1172.33-t*(10793.56-t*(33300.12-t*(38394.49-t*14825.05)))))/255)));
  const g=Math.round(255*Math.max(0,Math.min(1,(23.31+t*(557.33+t*(1225.33-t*(3574.96-t*(1073.77+t*707.56)))))/255)));
  const b=Math.round(255*Math.max(0,Math.min(1,(27.2+t*(3211.1-t*(15327.97-t*(27814-t*(22569.18-t*6838.66)))))/255)));
  return `rgb(${r},${g},${b})`;}
function fmtDelta(s){return (s>=0?"+":"")+s.toFixed(3);}
function category(car){const m=(car||"").match(/GT\s?3|GT\s?4|GT\s?2|GTE|GT1|LMP\s?[123]|HYPERCAR|TCR|CUP|TROPHY/i);
  return m?m[0].toUpperCase().replace(/\s+/g,""):"";}
function wx(a,r){return (a!=null)?`${a}°/${r}°`:"";}

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
  selected.forEach((l,i)=>l.color=i===0?"#ffffff":PALETTE[(i-1)%PALETTE.length]);}
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
      <td>${r.driver}${r.fromCurrent?"":' <span class="tag">altra</span>'}</td>
      <td>#${r.lapn}</td><td class="num">${r.time_str}</td>
      <td class="num" style="color:${r.time===best?'var(--accent2)':'var(--muted)'}">${r.time===best?'best':fmtDelta(r.time-best)}</td>
      <td class="num">${r.vmax??'-'}</td><td class="num" style="color:var(--amber)">${wx(r.air,r.road)}</td>`;
    if(col)tr.style.boxShadow=`inset 4px 0 0 ${col}`;
    tr.querySelector("input").onchange=(e)=>toggle(r.sid,r.lapn,e.target.checked);
    body.appendChild(tr);});}

function renderStats(){const ref=refLap();const el=document.getElementById("stats-body");
  if(!ref){el.innerHTML='<span class="dcol-empty">Nessun giro selezionato.</span>';renderOptimal();return;}
  const s=ref.stats;
  el.innerHTML=[["Pilota",ref.driver],["Giro","#"+ref.lapn+(selected.length>1?" (rif.)":"")],
    ["Tempo",ref.time_str],["V max",(s.v_max??'-')+" km/h"],["V min",(s.v_min??'-')+" km/h"],
    ["V media",(s.v_avg??'-')+" km/h"],["RPM max",s.rpm_max??'-'],["Pieno gas",(s.full_throttle_pct??'-')+" %"]
  ].map(([k,v])=>`<div class="si"><span class="sk">${k}</span><span class="sv">${v}</span></div>`).join("");
  renderOptimal();}

function renderOptimal(){const el=document.getElementById("optimal-line");if(!el)return;
  const o=SESSION&&SESSION.optimal;
  if(!o){el.innerHTML="";return;}
  const best=SESSION.best_lap_str;
  const gap=(SESSION.laps.find(l=>l.n===SESSION.best_lap)||{}).time;
  const delta=(gap!=null)?` <span class="opt-gap">(−${(gap-o.time).toFixed(3)} sul best ${best})</span>`:"";
  const secs=o.sectors.map(s=>`<span class="opt-sec">S${s.i} <b>${s.time_str.replace(/^0:/,'')}</b> <span class="opt-from">giro ${s.lap}</span></span>`).join("");
  el.innerHTML=`<span class="opt-lbl">Giro ottimale</span><span class="opt-time">${o.time_str}</span>${delta}<span class="opt-secs">${secs}</span>`;}

// ---------------- mappa ----------------
const cv=document.getElementById("map"),ctx=cv.getContext("2d");
let mapZoom=1, mapPanX=0, mapPanY=0;
let mapBase=[];          // punti schermo (non zoomati) della geometria di riferimento
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

function computeMap(){mapBase=[];const ref=refLap();if(!ref)return;
  // bounds su tutti i giri allineati, ma disegniamo sulla geometria del riferimento
  const coords=selected.map((l,i)=> i===0 ? {x:l.data.x,y:l.data.y} : alignPoints(ref.data,l.data));
  let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
  coords.forEach(co=>{for(let i=0;i<co.x.length;i++){
    if(co.x[i]<xmin)xmin=co.x[i];if(co.x[i]>xmax)xmax=co.x[i];
    if(co.y[i]<ymin)ymin=co.y[i];if(co.y[i]>ymax)ymax=co.y[i];}});
  const pad=46,w=cv.width,h=cv.height;
  const s=Math.min((w-2*pad)/((xmax-xmin)||1),(h-2*pad)/((ymax-ymin)||1));
  const ox=(w-(xmax-xmin)*s)/2,oy=(h-(ymax-ymin)*s)/2;
  const bx=(x)=>w-(ox+(x-xmin)*s), by=(y)=>h-(oy+(y-ymin)*s);
  const rc=coords[0];
  for(let i=0;i<rc.x.length;i++)mapBase.push({X:bx(rc.x[i]),Y:by(rc.y[i])});
  let vmin=Infinity,vmax=-Infinity;
  selected.forEach(l=>{const c=l.data.channels.SPEED;for(let i=0;i<c.length;i++){
    if(c[i]<vmin)vmin=c[i];if(c[i]>vmax)vmax=c[i];}});
  mapMeta={vmin,vmax,span:(vmax-vmin)||1};}

function zp(p){const cx=cv.width/2,cy=cv.height/2;
  return {X:(p.X-cx)*mapZoom+cx+mapPanX, Y:(p.Y-cy)*mapZoom+cy+mapPanY};}

function colorAt(i){
  const multi=selected.length>1;
  if(!multi){
    const d=refLap().data;
    if(mapMode==="speed")return turbo((d.channels.SPEED[i]-mapMeta.vmin)/mapMeta.span);
    const br=d.channels.BRAKE[i],th=d.channels.THROTTLE[i];
    if(br>3)return mix("#ff5252","#7a0000",Math.min(br,100)/100);
    if(th>90)return "#1ee65a"; if(th>3)return "#9bd24a"; return "#5a6472";
  }
  // due (o piu') giri: SERIES allineato su X del riferimento
  if(!SERIES)return "#888";
  const A=0,B=1;
  if(mapMode==="speed"){
    const dv=SERIES.SPEED[A][i]-SERIES.SPEED[B][i];
    const faster=dv>=0?selected[A].color:selected[B].color;
    const t=Math.min(Math.abs(dv)/15,1)*0.8+0.2;
    return mix(GREY,faster,t);
  }else{
    const brA=SERIES.BRAKE[A][i]>5, brB=SERIES.BRAKE[B][i]>5;
    if(brA&&!brB)return selected[A].color;     // A frena, B no
    if(brB&&!brA)return selected[B].color;     // B frena, A no
    if(brA&&brB)return "#8a3030";              // entrambi in frenata
    const thA=SERIES.THROTTLE[A][i]>90, thB=SERIES.THROTTLE[B][i]>90;
    if(thA&&thB)return "#1ee65a";              // entrambi pieno gas
    return "#39414f";
  }
}

function drawMap(){ctx.clearRect(0,0,cv.width,cv.height);const ref=refLap();if(!ref||!mapBase.length)return;
  ctx.lineCap="round";ctx.lineJoin="round";
  const multi=selected.length>1;
  // ombra/base scura per pulizia
  ctx.strokeStyle="#0c0f14";ctx.lineWidth=(multi?9:8)*Math.min(mapZoom,2)/Math.max(1,mapZoom*0+1);
  ctx.lineWidth=Math.max(6,9);
  ctx.beginPath();let p=zp(mapBase[0]);ctx.moveTo(p.X,p.Y);
  for(let i=1;i<mapBase.length;i++){p=zp(mapBase[i]);ctx.lineTo(p.X,p.Y);}ctx.stroke();
  // linea colorata, segmento per segmento
  const lw=Math.max(3.5,6*Math.min(mapZoom,1.6));
  ctx.lineWidth=lw;
  for(let i=1;i<mapBase.length;i++){ctx.strokeStyle=colorAt(i);
    const a=zp(mapBase[i-1]),b=zp(mapBase[i]);ctx.beginPath();ctx.moveTo(a.X,a.Y);ctx.lineTo(b.X,b.Y);ctx.stroke();}
  // traguardo
  const sf=zp(mapBase[0]);ctx.fillStyle="#fff";ctx.strokeStyle="#000";ctx.lineWidth=1.5;
  ctx.beginPath();ctx.arc(sf.X,sf.Y,6,0,7);ctx.fill();ctx.stroke();
  ctx.fillStyle="#fff";ctx.font="bold 12px system-ui";ctx.fillText("S/F",sf.X+8,sf.Y-6);
  // numeri curva
  if(CORNERS&&CORNERS.length){ctx.font="bold 11px system-ui";
    CORNERS.forEach(c=>{const idx=Math.max(0,Math.min(mapBase.length-1,Math.round(c.dist_frac*(mapBase.length-1))));
      const q=zp(mapBase[idx]);
      ctx.beginPath();ctx.arc(q.X,q.Y,8,0,7);ctx.fillStyle="#11151c";ctx.fill();
      ctx.strokeStyle="#ffb020";ctx.lineWidth=1.2;ctx.stroke();
      ctx.fillStyle="#ffb020";ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(c.n,q.X,q.Y);});
    ctx.textAlign="start";ctx.textBaseline="alphabetic";}
  renderLegend();}

function renderLegend(){const leg=document.getElementById("map-legend");const multi=selected.length>1;
  if(!multi){leg.textContent= mapMode==="speed"
    ? `velocità ${mapMeta.vmin.toFixed(0)}–${mapMeta.vmax.toFixed(0)} km/h (blu→rosso)`
    : "rosso = frenata · verde = pieno gas · grigio = rilascio · giallo = curve";return;}
  const A=selected[0],B=selected[1];
  if(mapMode==="speed"){
    leg.innerHTML=`Più veloce: <span style="color:${A.color}">▬ ${A.driver} #${A.lapn}</span> &nbsp; `+
      `<span style="color:${B.color}">▬ ${B.driver} #${B.lapn}</span> &nbsp;·&nbsp; <span style="color:var(--dim)">colore = chi va più forte in quel punto</span>`;
  }else{
    leg.innerHTML=`<span style="color:${A.color}">▬ frena ${A.driver}</span> &nbsp; `+
      `<span style="color:${B.color}">▬ frena ${B.driver}</span> &nbsp; (l'altro è ancora in gas) · `+
      `<span style="color:#8a3030">▬ entrambi frenano</span> · <span style="color:#1ee65a">▬ entrambi gas</span>`;
  }}

function drawDot(i){drawMap();if(i==null||!mapBase.length)return;
  const p=zp(mapBase[Math.max(0,Math.min(i,mapBase.length-1))]);
  ctx.beginPath();ctx.arc(p.X,p.Y,7,0,7);ctx.fillStyle="#fff";ctx.fill();
  ctx.lineWidth=2;ctx.strokeStyle="#000";ctx.stroke();}

cv.addEventListener("wheel",e=>{e.preventDefault();
  const r=cv.getBoundingClientRect();
  const mx=(e.clientX-r.left)*cv.width/r.width, my=(e.clientY-r.top)*cv.height/r.height;
  const f=e.deltaY<0?1.15:1/1.15, nz=Math.max(1,Math.min(10,mapZoom*f)), af=nz/mapZoom;
  const cx=cv.width/2,cy=cv.height/2;
  mapPanX=mx-cx-(mx-cx-mapPanX)*af; mapPanY=my-cy-(my-cy-mapPanY)*af; mapZoom=nz;
  if(mapZoom===1){mapPanX=0;mapPanY=0;} drawMap();},{passive:false});
(function panMap(){let d=null;
  cv.addEventListener("mousedown",e=>{d={x:e.clientX,y:e.clientY,px:mapPanX,py:mapPanY};});
  window.addEventListener("mousemove",e=>{if(!d)return;const r=cv.getBoundingClientRect();
    mapPanX=d.px+(e.clientX-d.x)*cv.width/r.width; mapPanY=d.py+(e.clientY-d.y)*cv.height/r.height; drawMap();});
  window.addEventListener("mouseup",()=>d=null);})();
function zoomBy(f){const nz=Math.max(1,Math.min(10,mapZoom*f));mapPanX*=nz/mapZoom;mapPanY*=nz/mapZoom;mapZoom=nz;
  if(mapZoom===1){mapPanX=0;mapPanY=0;}drawMap();}

// box valori trascinabile
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

// grafici
function mkChart(cont,title,arrays,X,opts){opts=opts||{};
  const box=document.createElement("div");box.className="chart-box";
  const ttl=document.createElement("div");ttl.className="ttl";ttl.innerHTML=`<span>${title}</span>`;
  box.appendChild(ttl);cont.appendChild(box);
  const refk=refLap().key;
  const uSeries=[{}].concat(selected.map(l=>({label:l.label,stroke:l.color,
    width:l.key===refk?2:1.4,value:(u,v)=>v==null?"--":v.toFixed(opts.dp??1)})));
  const u=new uPlot({width:box.clientWidth-24,height:opts.h||180,
    scales:{x:{time:false},y:opts.range?{range:opts.range}:{}},series:uSeries,legend:{show:false},
    axes:[{stroke:"#8b95a3",grid:{stroke:"#1c222b"},values:(u,v)=>v.map(x=>x+"m")},
          {stroke:"#8b95a3",grid:{stroke:"#161b22"}}],
    cursor:{sync:{key:"ace",setSeries:true},points:{size:5}},
    hooks:{setCursor:[u=>{const i=u.cursor.idx;if(i==null){drawDot(null);return;}drawDot(i);updateValbox(i);}]},
  },[X].concat(arrays),box);
  if(SYNC)SYNC.sub(u);charts.push(u);}

function prepareSeries(){const ref=refLap();if(!ref)return;
  const X=ref.data.dist;
  const chan=name=>selected.map(l=>interpOnto(l.data.dist,l.data.channels[name],X));
  const refT=ref.data.time;
  const delta=selected.map(l=>{const tOn=interpOnto(l.data.dist,l.data.time,X);return X.map((_,i)=>tOn[i]-refT[i]);});
  SERIES={X,SPEED:chan("SPEED"),THROTTLE:chan("THROTTLE"),BRAKE:chan("BRAKE"),delta};}

async function buildCharts(){const cont=document.getElementById("charts");
  cont.querySelectorAll(".chart-box").forEach(b=>b.remove());charts.length=0;
  const ref=refLap();if(!ref||!window.uPlot||!SERIES)return;
  if(!SYNC){try{SYNC=uPlot.sync("ace");}catch(e){}}
  const X=SERIES.X;
  for(const name of extra) for(const l of selected) await ensureChannel(l,name);
  const chan=name=>selected.map(l=>interpOnto(l.data.dist,l.data.channels[name],X));
  try{
    mkChart(cont,"Velocità (km/h)",SERIES.SPEED,X,{h:200});
    mkChart(cont,"Δ tempo vs riferimento (s)",SERIES.delta,X,{dp:3,h:180});
    mkChart(cont,"Gas (%)",SERIES.THROTTLE,X,{range:[0,100],h:170});
    mkChart(cont,"Freno (%)",SERIES.BRAKE,X,{range:[0,100],h:170});
    for(const name of extra) mkChart(cont,name,chan(name),X,{h:160});
  }catch(e){console.error("Grafici:",e);}}

// modali
function openModal(id){document.getElementById(id).hidden=false;}
function closeModal(id){document.getElementById(id).hidden=true;}
function renderChanPick(){const el=document.getElementById("chanpick");
  const names=(SESSION.meta.channel_names||[]).filter(n=>!BASE_CHARTS.includes(n));
  if(!names.length){el.innerHTML='<p style="color:var(--dim)">Nessun canale extra disponibile.</p>';return;}
  el.innerHTML=names.map(n=>`<label><input type="checkbox" value="${n}" ${extra.has(n)?"checked":""}>${n}</label>`).join("");
  el.querySelectorAll("input").forEach(inp=>inp.onchange=async(e)=>{
    if(e.target.checked)extra.add(e.target.value);else extra.delete(e.target.value);
    await buildCharts();});}

// confronto: stessa pista + stessa categoria, evidenzia il piu' veloce, mostra meteo, chiude dopo la scelta
async function openCompare(){
  const body=document.getElementById("compare-body");
  body.innerHTML='<p style="color:var(--dim)">Carico...</p>';openModal("compare-modal");
  const r=await fetch(`/api/track/${encodeURIComponent(SESSION.track)}`);const j=await r.json();
  const cat=category(SESSION.car);
  let others=j.sessions.filter(s=>s.id!==SID);
  if(cat) others=others.filter(s=>category(s.car)===cat);
  if(!others.length){body.innerHTML=`<p style="color:var(--dim)">Nessun altro giro ${cat?'di categoria '+cat+' ':''}su questa pista.</p>`;return;}
  let fastest=Infinity; others.forEach(s=>s.laps.forEach(l=>{if(l.time<fastest)fastest=l.time;}));
  body.innerHTML=others.map(s=>`<div class="cmp-sess"><div class="cmp-h"><b>${s.driver}</b> · ${s.car}`+
      (cat?` <span class="tag">${category(s.car)}</span>`:"")+
      ` <span class="cmp-d">${s.date}${(s.air_temp!=null)?' · '+wx(s.air_temp,s.road_temp):''}</span></div><div class="cmp-laps">`+
      s.laps.map(l=>`<button class="chip cmp-lap${l.time===fastest?' fastest':''}" data-sid="${s.id}" data-lap="${l.n}" data-air="${s.air_temp??''}" data-road="${s.road_temp??''}">#${l.n} · ${l.time_str}${l.time===fastest?' ⚡':''}</button>`).join("")+`</div></div>`).join("");
  body.querySelectorAll(".cmp-lap").forEach(b=>{b.onclick=async()=>{
    const sid=b.dataset.sid,lapn=parseInt(b.dataset.lap);
    if(!rows.find(r=>r.sid===sid&&r.lapn===lapn)){await ensureLoaded(sid,lapn);const c=lapCache[key(sid,lapn)];
      rows.push({sid,lapn,driver:c.driver,time_str:c.time_str,time:c.time,vmax:c.stats.v_max,fromCurrent:false,
                 air:b.dataset.air!==''?+b.dataset.air:null,road:b.dataset.road!==''?+b.dataset.road:null});}
    selectedKeys.add(key(sid,lapn));
    closeModal("compare-modal");
    await renderAll();};});}

async function renderAll(){rebuildSelected();
  selected.forEach(l=>l.label=`${l.driver} #${l.lapn} ${l.time_str}`);
  try{computeMap();}catch(e){console.error("mappa:",e);mapBase=[];}
  prepareSeries();
  renderLapTable();renderStats();drawMap();await buildCharts();}

async function init(){const r=await fetch(`/api/session/${SID}`);SESSION=await r.json();
  document.getElementById("track-name").textContent="· "+SESSION.track;
  const w=SESSION.meta.weather||{};
  document.getElementById("weather").textContent=(w.air_temp!=null)?`Aria ${w.air_temp}° · Asfalto ${w.road_temp}°`:"";
  document.getElementById("laps-note").textContent=
    SESSION.best_lap?'Spunta 2 giri per confrontarli: sulla mappa la linea mostra le differenze tra i due. Rotella per zoomare, trascina per spostare.'
                    :"Nessun giro completo in questa sessione.";
  SESSION.laps.filter(l=>l.complete).forEach(l=>rows.push(
    {sid:SID,lapn:l.n,driver:SESSION.driver,time_str:l.time_str,time:l.time,vmax:l.v_max,fromCurrent:true,
     air:w.air_temp??null,road:w.road_temp??null}));
  try{const cr=await fetch(`/api/cornermap?track=${encodeURIComponent(SESSION.track)}`);CORNERS=(await cr.json()).corners||[];}catch(e){CORNERS=[];}
  if(SESSION.best_lap){await ensureLoaded(SID,SESSION.best_lap);selectedKeys.add(key(SID,SESSION.best_lap));}
  document.getElementById("add-compare").onclick=openCompare;
  document.getElementById("compare-close").onclick=()=>closeModal("compare-modal");
  document.getElementById("chan-open").onclick=()=>{renderChanPick();openModal("chan-modal");};
  document.getElementById("chan-close").onclick=()=>closeModal("chan-modal");
  document.querySelectorAll(".modal").forEach(m=>m.addEventListener("click",e=>{if(e.target===m)m.hidden=true;}));
  document.querySelectorAll(".mode-btn").forEach(b=>b.onclick=()=>{
    mapMode=b.dataset.mode;
    document.querySelectorAll(".mode-btn").forEach(x=>x.classList.toggle("active",x===b));drawMap();});
  document.getElementById("zoom-in").onclick=()=>zoomBy(1.3);
  document.getElementById("zoom-out").onclick=()=>zoomBy(1/1.3);
  document.getElementById("zoom-reset").onclick=()=>{mapZoom=1;mapPanX=0;mapPanY=0;drawMap();};
  await renderAll();}
init();
