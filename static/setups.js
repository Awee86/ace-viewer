/* Setup: selezione (max 2, stessa auto) + confronto/diff parametri */
const cache={};
const picks=[];

async function getSetup(id){
  if(cache[id])return cache[id];
  const r=await fetch(`/api/setup/${id}`); cache[id]=await r.json(); return cache[id];
}

function groupName(g){return {generale:"Generale",molla:"Molle",ammo:"Ammortizzatori",alza:"Assetto / Gomme"}[g]||g;}

async function render(){
  const box=document.getElementById("setup-compare");
  if(picks.length===0){ box.hidden=true; return; }
  box.hidden=false; box.innerHTML='<p style="color:var(--dim)">Carico...</p>';
  const data=await Promise.all(picks.map(cb=>getSetup(cb.value)));
  const A=data[0], B=data[1];
  // mappa key->param
  const mapA={}; A.params.forEach(p=>mapA[p.key]=p);
  const mapB=B?Object.fromEntries(B.params.map(p=>[p.key,p])):null;
  const keys=A.params.map(p=>p.key).concat(B?B.params.filter(p=>!mapA[p.key]).map(p=>p.key):[]);
  let rows="", lastg=null;
  keys.forEach(k=>{
    const a=mapA[k]||(mapB?mapB[k]:null); if(!a)return;
    const pa=mapA[k], pb=mapB?mapB[k]:null;
    const g=(pa||pb).group;
    if(g!==lastg){ rows+=`<tr class="grp"><td colspan="4">${groupName(g)}</td></tr>`; lastg=g; }
    const va=pa?pa.value:"–", vb=pb?pb.value:"–";
    const diff=B && pa && pb && pa.value!==pb.value;
    rows+=`<tr class="${diff?'diff':''}">
      <td class="sp-corner">${(pa||pb).corner||""}</td>
      <td class="sp-label">${(pa||pb).label}</td>
      <td class="num">${va}</td>
      ${B?`<td class="num">${vb}</td>`:""}</tr>`;
  });
  const head=`<div class="sp-head"><span class="sp-a">${A.name} · ${A.uploader}</span>`+
    (B?`<span class="sp-vs">vs</span><span class="sp-b">${B.name} · ${B.uploader}</span>`:"")+`</div>`;
  box.innerHTML=head+`<table class="sp-table"><thead><tr><th></th><th>Parametro</th><th>${A.uploader}</th>${B?`<th>${B.uploader}</th>`:""}</tr></thead><tbody>${rows}</tbody></table>`;
}

document.querySelectorAll(".setup-pick").forEach(cb=>{
  cb.onchange=()=>{
    if(cb.checked){
      if(picks.length>=2){ cb.checked=false; alert("Massimo due setup alla volta."); return; }
      if(picks.length && picks[0].dataset.car!==cb.dataset.car){ cb.checked=false; alert("Confronta setup della stessa auto."); return; }
      picks.push(cb);
    } else { const i=picks.indexOf(cb); if(i>=0)picks.splice(i,1); }
    render();
  };
});
