/* Setup: colonne per pilota, tracciati richiudibili, click=espandi, spunta=confronta */
const cache={};
const picks=[];

async function getSetup(id){
  if(cache[id])return cache[id];
  const r=await fetch(`/api/setup/${id}`); cache[id]=await r.json(); return cache[id];
}
function gName(g){return {generale:"Generale",molla:"Molle",ammo:"Ammortizzatori",alza:"Assetto / Gomme"}[g]||g;}

function paramTable(params){
  let rows="",lastg=null;
  params.forEach(p=>{
    if(p.group!==lastg){rows+=`<tr class="grp"><td colspan="3">${gName(p.group)}</td></tr>`;lastg=p.group;}
    rows+=`<tr><td class="sp-corner">${p.corner||""}</td><td class="sp-label">${p.label}</td><td class="num">${p.value}</td></tr>`;
  });
  return `<table class="sp-table"><tbody>${rows}</tbody></table>`;
}

// --- espansione singolo setup ---
document.querySelectorAll(".set-row").forEach(row=>{
  row.addEventListener("click",async(e)=>{
    if(e.target.closest("input,a,button,form"))return;   // checkbox/azioni: non espandere
    const id=row.dataset.id, det=document.getElementById("det-"+id);
    if(!det.hidden){det.hidden=true;row.classList.remove("open");return;}
    if(!det.dataset.loaded){
      det.innerHTML='<p style="color:var(--dim);font-size:11px">Carico...</p>';
      const s=await getSetup(id);
      det.innerHTML=paramTable(s.params); det.dataset.loaded="1";
    }
    det.hidden=false; row.classList.add("open");
  });
});

// --- tracciati richiudibili ---
document.querySelectorAll(".trk-head").forEach(h=>{
  h.addEventListener("click",()=>h.parentElement.classList.toggle("collapsed"));
});

// --- confronto (spunta max 2, stessa auto) ---
async function renderCompare(){
  const box=document.getElementById("setup-compare");
  if(picks.length<2){box.hidden=true;return;}
  box.hidden=false; box.innerHTML='<p style="color:var(--dim)">Carico...</p>';
  const [A,B]=await Promise.all(picks.map(cb=>getSetup(cb.value)));
  const mapB=Object.fromEntries(B.params.map(p=>[p.key,p]));
  let rows="",lastg=null;
  A.params.forEach(pa=>{
    const pb=mapB[pa.key];
    if(pa.group!==lastg){rows+=`<tr class="grp"><td colspan="4">${gName(pa.group)}</td></tr>`;lastg=pa.group;}
    const diff=pb&&pa.value!==pb.value;
    rows+=`<tr class="${diff?'diff':''}"><td class="sp-corner">${pa.corner||""}</td><td class="sp-label">${pa.label}</td>
      <td class="num">${pa.value}</td><td class="num">${pb?pb.value:'–'}</td></tr>`;
  });
  box.innerHTML=`<div class="sp-head"><span class="sp-a">${A.name} · ${A.uploader}</span><span class="sp-vs">vs</span><span class="sp-b">${B.name} · ${B.uploader}</span></div>`+
    `<table class="sp-table"><thead><tr><th></th><th>Parametro</th><th>${A.uploader}</th><th>${B.uploader}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

document.querySelectorAll(".setup-pick").forEach(cb=>{
  cb.addEventListener("click",e=>e.stopPropagation());
  cb.onchange=()=>{
    if(cb.checked){
      if(picks.length>=2){cb.checked=false;alert("Massimo due setup alla volta.");return;}
      if(picks.length&&picks[0].dataset.car!==cb.dataset.car){cb.checked=false;alert("Confronta setup della stessa auto.");return;}
      picks.push(cb);
    }else{const i=picks.indexOf(cb);if(i>=0)picks.splice(i,1);}
    renderCompare();
  };
});
