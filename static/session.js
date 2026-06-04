/* ACE Viewer - pagina sessione/confronto (v1.1.0) */
let SYNC = null;
let SESSION = null;
const lapCache = {};           // "sid:lapn" -> {data,stats,driver,time_str,time}
const rows = [];               // righe tabella
const selectedKeys = new Set();
let selected = [];
const charts = [];

const PALETTE = ["#19e6c8","#ff2e2e","#ffb020","#3d9bff","#b07bff","#33d17a","#ff7ad9","#9be15d"];
const key = (sid,n)=>`${sid}:${n}`;

function turbo(t){t=Math.max(0,Math.min(1,t));
  const r=Math.round(255*Math.max(0,Math.min(1,(34.61+t*(1172.33-t*(10793.56-t*(33300.12-t*(38394.49-t*14825.05)))))/255)));
  const g=Math.round(255*Math.max(0,Math.min(1,(23.31+t*(557.33+t*(1225.33-t*(3574.96-t*(1073.77+t*707.56)))))/255)));
  const b=Math.round(255*Math.max(0,Math.min(1,(27.2+t*(3211.1-t*(15327.97-t*(27814-t*(22569.18-t*6838.66)))))/255)));
  return `rgb(${r},${g},${b})`;}
function fmtDelta(s){return (s>=0?"+":"")+s.toFixed(3);}

function interpOnto(sx, sy, dx){
  const out=new Array(dx.length); let j=0;
  for(let i=0;i<dx.length;i++){
    const x=dx[i];
    while(j<sx.length-2 && sx[j+1]<x) j++;
    const x0=sx[j],x1=sx[j+1],y0=sy[j],y1=sy[j+1];
    out[i]= x1===x0 ? y0 : y0+(y1-y0)*(x-x0)/(x1-x0);
  }
  return out;
}

function rebuildSelected(){
  selected=[];
  rows.forEach(r=>{const k=key(r.sid,r.lapn);
    if(selectedKeys.has(k)&&lapCache[k]) selected.push(Object.assign({key:k},r,lapCache[k]));});
  selected.sort((a,b)=>a.time-b.time);
  selected.forEach((l,i)=> l.color = i===0 ? "#ffffff" : PALETTE[i%PALETTE.length]);
}
function refLap(){ return selected[0]; }

async function ensureLoaded(sid,lapn){
  const k=key(sid,lapn); if(lapCache[k]) return;
  if(sid===SID && SESSION.lap_data[lapn]){
    const lap=SESSION.laps.find(l=>l.n===lapn)||{};
    lapCache[k]={data:SESSION.lap_data[lapn],time_str:lap.time_str,time:lap.time,driver:SESSION.driver,
      stats:{v_max:lap.v_max,v_min:lap.v_min,v_avg:lap.v_avg,rpm_max:lap.rpm_max,full_throttle_pct:lap.full_throttle_pct}};
  } else {
    const r=await fetch(`/api/lap/${sid}/${lapn}`); const j=await r.json();
    lapCache[k]={data:j.data,time_str:j.time_str,time:j.time,driver:j.driver,stats:j.stats};
  }
}
async function toggle(sid,lapn,on){
  const k=key(sid,lapn);
  if(on){ await ensureLoaded(sid,lapn); selectedKeys.add(k); } else { selectedKeys.delete(k); }
  renderAll();
}

function renderLapTable(){
  const body=document.getElementById("laps-body"); body.innerHTML="";
  const best=Math.min(...rows.map(r=>r.time));
  rows.forEach(r=>{
    const k=key(r.sid,r.lapn); const sel=selectedKeys.has(k);
    const col= sel ? (selected.find(s=>s.key===k)||{}).color : null;
    const tr=document.createElement("tr"); if(sel) tr.classList.add("sel");
    tr.innerHTML=`<td><input type="checkbox" ${sel?"checked":""}></td>
      <td>${r.driver}${r.fromCurrent?"":' <span class="tag">altra sess.</span>'}</td>
      <td>#${r.lapn}</td><td class="num">${r.time_str}</td>
      <td class="num" style="color:${r.time===best?'var(--accent2)':'var(--muted)'}">${r.time===best?'best':fmtDelta(r.time-best)}</td>
      <td class="num">${r.vmax??'-'}</td>`;
    if(col) tr.style.boxShadow=`inset 4px 0 0 ${col}`;
    tr.querySelector("input").onchange=(e)=>toggle(r.sid,r.lapn,e.target.checked);
    body.appendChild(tr);
  });
}

function renderStats(){
  const ref=refLap(); const el=document.getElementById("stats-body");
  if(!ref){ el.innerHTML='<p style="color:var(--dim)">Nessun giro selezionato.</p>'; return; }
  const s=ref.stats;
  el.innerHTML=[
    ["Pilota",ref.driver],["Giro","#"+ref.lapn+(selected.length>1?" (rif.)":"")],
    ["Tempo",ref.time_str],["V max",(s.v_max??'-')+" km/h"],["V min",(s.v_min??'-')+" km/h"],
    ["V media",(s.v_avg??'-')+" km/h"],["RPM max",s.rpm_max??'-'],["Pieno gas",(s.full_throttle_pct??'-')+" %"],
  ].map(([k,v])=>`<div class="srow"><span class="sk">${k}</span><span class="sv">${v}</span></div>`).join("");
}

const cv=document.getElementById("map"), ctx=cv.getContext("2d");
let mapT=null;
function computeMapTransform(){
  const ref=refLap(); if(!ref) return;
  const X=ref.data.x,Y=ref.data.y,pad=36;
  const xmin=Math.min(...X),xmax=Math.max(...X),ymin=Math.min(...Y),ymax=Math.max(...Y);
  const w=cv.width,h=cv.height;
  const s=Math.min((w-2*pad)/((xmax-xmin)||1),(h-2*pad)/((ymax-ymin)||1));
  const ox=(w-(xmax-xmin)*s)/2,oy=(h-(ymax-ymin)*s)/2;
  // px invertito (mirror orizzontale) per orientare il tracciato come la pista reale
  mapT={px:i=>w-(ox+(X[i]-xmin)*s),py:i=>h-(oy+(Y[i]-ymin)*s)};
}
function drawMap(){
  const ref=refLap(); ctx.clearRect(0,0,cv.width,cv.height); if(!ref||!mapT) return;
  const c=ref.data.channels.SPEED,vmin=Math.min(...c),vmax=Math.max(...c),span=(vmax-vmin)||1;
  ctx.lineWidth=4; ctx.lineCap="round";
  for(let i=1;i<ref.data.x.length;i++){
    ctx.strokeStyle=turbo((c[i]-vmin)/span);
    ctx.beginPath(); ctx.moveTo(mapT.px(i-1),mapT.py(i-1)); ctx.lineTo(mapT.px(i),mapT.py(i)); ctx.stroke();
  }
}
function drawDot(i){
  drawMap(); if(i==null||!mapT) return;
  ctx.beginPath(); ctx.arc(mapT.px(i),mapT.py(i),6,0,7); ctx.fillStyle="#fff"; ctx.fill();
  ctx.lineWidth=2; ctx.strokeStyle="#ff2e2e"; ctx.stroke();
}

function mkChart(cont,title,seriesArrays,X,opts){
  opts=opts||{};
  const box=document.createElement("div"); box.className="chart-box";
  const ttl=document.createElement("div"); ttl.className="ttl";
  ttl.innerHTML=`<span>${title}</span><span class="readout"></span>`;
  box.appendChild(ttl); cont.appendChild(box);
  const readout=ttl.querySelector(".readout");
  const refk=refLap().key;
  const uSeries=[{}].concat(selected.map(l=>({label:l.label,stroke:l.color,
    width:l.key===refk?2:1.3, value:(u,v)=>v==null?"--":v.toFixed(opts.dp??1)})));
  const u=new uPlot({
    width:box.clientWidth-24,height:opts.h||140,
    scales:{x:{time:false},y:opts.range?{range:opts.range}:{}},
    series:uSeries,legend:{show:false},
    axes:[{stroke:"#8b95a3",grid:{stroke:"#222"},values:(u,v)=>v.map(x=>x+"m")},
          {stroke:"#8b95a3",grid:{stroke:"#1a1f27"}}],
    cursor:{sync:{key:"ace",setSeries:true},points:{size:5}},
    hooks:{setCursor:[u=>{const i=u.cursor.idx;
      if(i==null){drawDot(null);readout.textContent="";return;}
      drawDot(i);
      readout.textContent=selected.map((l,k)=>{const v=seriesArrays[k][i];
        return v==null?"":v.toFixed(opts.dp??1);}).filter(Boolean).join("  ·  ");
    }]},
  },[X].concat(seriesArrays),box);
  if(SYNC) SYNC.sub(u);
  charts.push(u);
}

function buildCharts(){
  const cont=document.getElementById("charts"); cont.innerHTML=""; charts.length=0;
  const ref=refLap(); if(!ref) return;
  if(!window.uPlot){ console.error("uPlot non caricato"); return; }
  if(!SYNC){ try{ SYNC=uPlot.sync("ace"); }catch(e){} }
  const X=ref.data.dist;
  const chan=name=>selected.map(l=>interpOnto(l.data.dist,l.data.channels[name],X));
  const refT=ref.data.time;
  const delta=selected.map(l=>{const tOn=interpOnto(l.data.dist,l.data.time,X);
    return X.map((_,i)=>tOn[i]-refT[i]);});
  try{
    mkChart(cont,"Velocità (km/h)",chan("SPEED"),X);
    mkChart(cont,"Δ tempo vs riferimento (s)",delta,X,{dp:3,h:120});
    mkChart(cont,"Gas (%)",chan("THROTTLE"),X,{range:[0,100]});
    mkChart(cont,"Freno (%)",chan("BRAKE"),X,{range:[0,100]});
    mkChart(cont,"Sterzo (°)",chan("STEERANGLE"),X);
  }catch(e){ console.error("Grafici:",e); }
}

async function openCompare(){
  const panel=document.getElementById("compare-panel");
  if(!panel.hidden){ panel.hidden=true; return; }
  panel.innerHTML='<p style="color:var(--dim)">Carico...</p>'; panel.hidden=false;
  const r=await fetch(`/api/track/${encodeURIComponent(SESSION.track)}`); const j=await r.json();
  const others=j.sessions.filter(s=>s.id!==SID);
  if(!others.length){ panel.innerHTML='<p style="color:var(--dim)">Nessun\'altra sessione su questa pista per ora. Caricane altre (tue o degli amici) e compariranno qui.</p>'; return; }
  panel.innerHTML='<div class="cmp-title">Aggiungi giri da altre sessioni sulla stessa pista:</div>'+
    others.map(s=>`<div class="cmp-sess"><b>${s.driver}</b> · ${s.car} · ${s.date} ${s.time}<div class="cmp-laps">`+
      s.laps.map(l=>`<button class="chip cmp-lap" data-sid="${s.id}" data-lap="${l.n}">#${l.n} ${l.time_str}</button>`).join("")+
      `</div></div>`).join("");
  panel.querySelectorAll(".cmp-lap").forEach(b=>{
    b.onclick=async()=>{
      const sid=b.dataset.sid, lapn=parseInt(b.dataset.lap);
      if(!rows.find(r=>r.sid===sid&&r.lapn===lapn)){
        await ensureLoaded(sid,lapn); const c=lapCache[key(sid,lapn)];
        rows.push({sid,lapn,driver:c.driver,time_str:c.time_str,time:c.time,vmax:c.stats.v_max,fromCurrent:false});
      }
      selectedKeys.add(key(sid,lapn)); renderAll();
    };
  });
}

function renderAll(){
  rebuildSelected();
  selected.forEach(l=> l.label=`${l.driver} #${l.lapn} ${l.time_str}`);
  computeMapTransform();
  renderLapTable(); renderStats(); drawMap(); buildCharts();
}

async function init(){
  const r=await fetch(`/api/session/${SID}`); SESSION=await r.json();
  document.getElementById("track-name").textContent="· "+SESSION.track;
  document.getElementById("laps-note").textContent =
    SESSION.best_lap ? 'Spunta più giri per sovrapporli. Usa "+ confronta altri piloti" per i giri di altre sessioni.'
                     : "Nessun giro completo in questa sessione (serve più di un passaggio sul traguardo).";
  SESSION.laps.filter(l=>l.complete).forEach(l=>{
    rows.push({sid:SID,lapn:l.n,driver:SESSION.driver,time_str:l.time_str,time:l.time,vmax:l.v_max,fromCurrent:true});
  });
  if(SESSION.best_lap){ await ensureLoaded(SID,SESSION.best_lap); selectedKeys.add(key(SID,SESSION.best_lap)); }
  document.getElementById("add-compare").onclick=openCompare;
  renderAll();
}
init();
