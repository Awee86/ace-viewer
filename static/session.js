/* ACE Viewer - logica pagina sessione */
let SYNC = null;       // creato in init() solo se uPlot e' disponibile
let DATA = null;       // payload API
let T = [];            // base temporale (s)
const CH = {};         // cache canali {name:{unit,values}}
let colorChan = "SPEED";
let lapRange = null;   // [i0,i1] indici del giro selezionato, o null
let curX = null;       // [tmin,tmax] zoom X corrente, o null
const charts = [];     // istanze uPlot

const COLORS = ["#19e6c8", "#ff2e2e", "#ffb020", "#3d9bff", "#b07bff", "#33d17a"];

// ---- turbo colormap (approssimazione) ----
function turbo(t) {
  t = Math.max(0, Math.min(1, t));
  const r = Math.round(255*Math.max(0,Math.min(1, 34.61 + t*(1172.33 - t*(10793.56 - t*(33300.12 - t*(38394.49 - t*14825.05)))) /255)));
  const g = Math.round(255*Math.max(0,Math.min(1, 23.31 + t*(557.33 + t*(1225.33 - t*(3574.96 - t*(1073.77 + t*707.56)))) /255)));
  const b = Math.round(255*Math.max(0,Math.min(1, 27.2 + t*(3211.1 - t*(15327.97 - t*(27814 - t*(22569.18 - t*6838.66)))) /255)));
  return `rgb(${r},${g},${b})`;
}

async function fetchChannel(name) {
  if (CH[name]) return CH[name];
  const r = await fetch(`/api/session/${SID}/channel/${encodeURIComponent(name)}`);
  const j = await r.json();
  CH[name] = j[name];
  return CH[name];
}

// =================================================================== MAPPA
const cv = document.getElementById("map");
const ctx = cv.getContext("2d");
let mapT = null;  // trasformazione

function computeMapTransform() {
  const x = DATA.x, y = DATA.y, pad = 40;
  const xmin = Math.min(...x), xmax = Math.max(...x);
  const ymin = Math.min(...y), ymax = Math.max(...y);
  const w = cv.width, h = cv.height;
  const s = Math.min((w-2*pad)/(xmax-xmin||1), (h-2*pad)/(ymax-ymin||1));
  const ox = (w-(xmax-xmin)*s)/2, oy = (h-(ymax-ymin)*s)/2;
  mapT = {
    px: i => ox + (DATA.x[i]-xmin)*s,
    py: i => h - (oy + (DATA.y[i]-ymin)*s),  // flip verticale
  };
}

function drawMap() {
  const c = CH[colorChan] ? CH[colorChan].values : DATA.channels[colorChan].values;
  const vmin = Math.min(...c), vmax = Math.max(...c), span = (vmax-vmin)||1;
  ctx.clearRect(0,0,cv.width,cv.height);
  ctx.lineWidth = 3; ctx.lineCap = "round";
  const n = DATA.x.length;
  for (let i=1;i<n;i++){
    const inLap = !lapRange || (i>=lapRange[0] && i<=lapRange[1]);
    const tcol = (c[i]-vmin)/span;
    ctx.strokeStyle = inLap ? turbo(tcol) : "#2a2f38";
    ctx.globalAlpha = inLap ? 1 : 0.5;
    ctx.beginPath();
    ctx.moveTo(mapT.px(i-1), mapT.py(i-1));
    ctx.lineTo(mapT.px(i), mapT.py(i));
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
  document.getElementById("map-legend").textContent =
    `${colorChan}  ${vmin.toFixed(1)} – ${vmax.toFixed(1)} ${(CH[colorChan]||DATA.channels[colorChan]).unit}`;
}

let dotIdx = null;
function drawDot(i){
  drawMap();
  if (i==null) return;
  ctx.beginPath();
  ctx.arc(mapT.px(i), mapT.py(i), 6, 0, 7);
  ctx.fillStyle = "#fff"; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = "#ff2e2e"; ctx.stroke();
}

// =================================================================== GRAFICI
function mkChart(container, title, series, scales) {
  const box = document.createElement("div");
  box.className = "chart-box";
  const ttl = document.createElement("div"); ttl.className = "ttl";
  ttl.innerHTML = `<span>${title}</span><span class="readout"></span>`;
  box.appendChild(ttl); container.appendChild(box);
  const readout = ttl.querySelector(".readout");

  const uSeries = [{}].concat(series.map((s,i)=>({
    label:s.label, stroke:s.color||COLORS[i%COLORS.length],
    width:1.3, scale:s.scale||"y",
    value:(u,v)=> v==null?"--":v.toFixed(s.dp??1),
  })));
  const uScales = Object.assign({x:{time:false}}, scales||{});
  const uAxes = [{stroke:"#8b95a3",grid:{stroke:"#222"},ticks:{stroke:"#333"}},
                 {stroke:"#8b95a3",grid:{stroke:"#1a1f27"},ticks:{stroke:"#333"},scale:"y"}];
  if (scales && scales.y2) uAxes.push({stroke:"#8b95a3",grid:{show:false},scale:"y2",side:1});

  const data = [T].concat(series.map(s=>{
    const ch = CH[s.key]||DATA.channels[s.key]; return ch?ch.values:T.map(()=>null);
  }));

  const opt = {
    width: box.clientWidth-24, height: 150,
    scales:uScales, series:uSeries, axes:uAxes,
    legend:{show:false},
    cursor:{ sync:{key:"ace", setSeries:true},
      points:{size:6}},
    hooks:{ setCursor:[u=>{
      const i = u.cursor.idx;
      if (i==null){drawDot(null);readout.textContent="";return;}
      drawDot(i);
      readout.textContent = series.map(s=>{
        const ch=CH[s.key]||DATA.channels[s.key];
        return `${s.label} ${ch.values[i].toFixed(s.dp??1)}`;
      }).join("  ·  ");
    }]},
  };
  const u = new uPlot(opt, data, box);
  if (SYNC) SYNC.sub(u);
  charts.push(u);
  return u;
}

function buildCharts() {
  const cont = document.getElementById("charts");
  cont.innerHTML = "";
  charts.length = 0;
  mkChart(cont,"Velocità (km/h)",[{key:"SPEED",label:"v",color:"#19e6c8"}]);
  mkChart(cont,"Pedali (%)",
    [{key:"THROTTLE",label:"gas",color:"#33d17a"},{key:"BRAKE",label:"freno",color:"#ff2e2e"}],
    {y:{range:[0,100]}});
  mkChart(cont,"Motore",
    [{key:"RPMS",label:"rpm",color:"#ffb020",dp:0},
     {key:"GEAR",label:"marcia",color:"#3d9bff",scale:"y2",dp:0}],
    {y2:{range:[0,7]}});
  mkChart(cont,"Sterzo (°)",[{key:"STEERANGLE",label:"sterzo",color:"#b07bff"}]);
  mkChart(cont,"Accelerazioni (m/s²)",
    [{key:"G_LAT",label:"lat",color:"#19e6c8"},{key:"G_LON",label:"lon",color:"#ffb020"}]);
}

// =================================================================== GIRI
function renderLaps() {
  const body = document.getElementById("laps-body");
  body.innerHTML = "";
  DATA.laps.forEach(l=>{
    const tr = document.createElement("tr");
    if (l.n===DATA.best_lap) tr.className="bestlap";
    tr.innerHTML = `<td>${l.complete?('#'+l.n):'sessione'}</td>
      <td>${l.time_str}</td><td>${l.v_max}</td><td>${l.v_avg}</td>`;
    tr.onclick = ()=>selectLap(l, tr);
    body.appendChild(tr);
  });
  const note = document.getElementById("laps-note");
  if (DATA.laps.length && !DATA.laps[0].complete)
    note.textContent = `Un solo passaggio sul traguardo (${DATA.meta.n_beacons} beacon): mostrata la sessione intera. Con ≥2 passaggi compaiono i tempi sul giro.`;
  else
    note.textContent = `${DATA.laps.length} giri · clicca per isolare un giro.`;
}

function selectLap(l, tr) {
  document.querySelectorAll("#laps tr").forEach(r=>r.classList.remove("sel"));
  const same = tr.classList.contains("sel");
  if (same){ lapRange=null; curX=null; resetZoom(); drawMap(); return; }
  tr.classList.add("sel");
  const i0 = T.findIndex(t=>t>=l.t0);
  let i1 = T.findIndex(t=>t>=l.t1); if(i1<0) i1=T.length-1;
  lapRange=[i0,i1]; curX=[l.t0,l.t1];
  charts.forEach(u=>u.setScale("x",{min:l.t0,max:l.t1}));
  drawMap();
}
function resetZoom(){ curX=null; charts.forEach(u=>u.setScale("x",{min:T[0],max:T[T.length-1]})); }

// =================================================================== INIT
async function init() {
  const r = await fetch(`/api/session/${SID}`);
  DATA = await r.json();
  Object.assign(CH, DATA.channels);
  const n = DATA.meta.n_samples, fs = DATA.meta.fs;
  T = new Array(n); for(let i=0;i<n;i++) T[i]=i/fs;

  computeMapTransform();
  drawMap();
  renderLaps();          // i giri PRIMA dei grafici: se i grafici falliscono, i giri restano

  // selettore colore mappa
  const sel = document.getElementById("color-chan");
  ["SPEED","THROTTLE","BRAKE","RPMS","G_LAT","G_LON","STEERANGLE"].forEach(c=>{
    if (DATA.channels[c]||DATA.meta.channel_names.includes(c)){
      const o=document.createElement("option"); o.value=c; o.textContent=c; sel.appendChild(o);
    }
  });
  sel.value="SPEED";
  sel.onchange = async ()=>{ colorChan=sel.value; await fetchChannel(colorChan); drawMap(); };

  // grafici (protetti: un problema con la libreria non deve nascondere i giri)
  if (window.uPlot) {
    try {
      SYNC = uPlot.sync("ace");
      buildCharts();
    } catch (e) {
      console.error("Grafici non disponibili:", e);
    }
  } else {
    console.error("Libreria grafici (uPlot) non caricata.");
  }

  // picker canali extra
  const pick = document.getElementById("chanpick");
  const core = new Set(["SPEED","THROTTLE","BRAKE","RPMS","GEAR","STEERANGLE","G_LAT","G_LON","FUEL"]);
  DATA.meta.channel_names.filter(c=>!core.has(c)).forEach(name=>{
    const lab=document.createElement("label");
    lab.innerHTML=`<input type="checkbox" value="${name}">${name}`;
    lab.querySelector("input").onchange = async (e)=>{
      if(e.target.checked){
        const ch=await fetchChannel(name);
        const u=mkChart(document.getElementById("charts"),`${name} (${ch.unit})`,
          [{key:name,label:name,color:"#19e6c8"}]);
        u._chanName=name;
        if(curX) u.setScale("x",{min:curX[0],max:curX[1]});
      } else {
        const idx=charts.findIndex(u=>u._chanName===name);
        if(idx>=0){ charts[idx].root.parentNode.removeChild(charts[idx].root); charts[idx].destroy(); charts.splice(idx,1); }
      }
    };
    pick.appendChild(lab);
  });
}

window.addEventListener("resize", ()=>{ /* uPlot gestisce via width fisso; redraw mappa */ drawMap(); });
init();
