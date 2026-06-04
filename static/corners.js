let corners=(window.CORNERS||[]).map(c=>({...c}));
const tb=document.querySelector("#clist tbody");
function renderList(){
  tb.innerHTML="";
  corners.forEach((c,i)=>{
    const tr=document.createElement("tr");
    tr.innerHTML=`<td class="num">${i+1}</td>
      <td><input class="cname" value="${(c.name||'').replace(/"/g,'&quot;')}"></td>
      <td style="text-align:right"><button class="xbtn" data-i="${i}">✕</button></td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll(".cname").forEach((inp,i)=>inp.oninput=()=>corners[i].name=inp.value);
  tb.querySelectorAll(".xbtn").forEach(b=>b.onclick=()=>{corners.splice(+b.dataset.i,1);renderList();drawMap();});
}
function drawMap(){
  const svg=document.getElementById("cmap"); if(!svg||!window.REF)return;
  const pts=window.REF.points, xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]);
  const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
  const w=maxx-minx||1,h=maxy-miny||1,pad=8;
  // specchio orizzontale (come nelle sessioni) e fit in 0..100
  const sx=v=>pad+(1-(v-minx)/w)*(100-2*pad), sy=v=>pad+(1-(v-miny)/h)*(100-2*pad);
  let d="M"+pts.map(p=>sx(p[0]).toFixed(1)+","+sy(p[1]).toFixed(1)).join(" L");
  let dots="";
  corners.forEach((c,i)=>{
    const ap=(window.REF.apexes||[]).find(a=>a.n===c.n)||window.REF.apexes[i];
    if(!ap)return;
    dots+=`<circle cx="${sx(ap.x).toFixed(1)}" cy="${sy(ap.y).toFixed(1)}" r="2.6" class="apx"/>
           <text x="${sx(ap.x).toFixed(1)}" y="${(sy(ap.y)-3.5).toFixed(1)}" class="apxn">${i+1}</text>`;
  });
  svg.innerHTML=`<path d="${d}" class="track"/>${dots}`;
}
document.getElementById("save").onclick=async()=>{
  const r=await fetch("/api/corners",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({track:window.TRACK,corners})});
  const j=await r.json(); if(j.ok){corners=j.corners;renderList();drawMap();alert("Salvato.");}
};
document.getElementById("rebuild").onclick=async()=>{
  if(!confirm("Ricostruire le curve dalla telemetria? Le modifiche manuali andranno perse."))return;
  const r=await fetch("/api/corners/rebuild",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({track:window.TRACK})});
  const j=await r.json(); if(j.ok){corners=j.corners.map(c=>({...c}));renderList();drawMap();}
};
renderList(); drawMap();
