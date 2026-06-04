let corners=(window.CORNERS||[]).map(c=>({...c}));
const tb=document.querySelector("#clist tbody");
function renumber(){corners.sort((a,b)=>a.dist_frac-b.dist_frac);corners.forEach((c,i)=>c.n=i+1);}
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
  tb.querySelectorAll(".xbtn").forEach(b=>b.onclick=()=>{corners.splice(+b.dataset.i,1);renumber();renderList();drawMap();});
}
let _tf=null;
function svgXY(){const pts=window.REF.points,xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
  const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
  const w=maxx-minx||1,h=maxy-miny||1,pad=8;
  return {sx:v=>pad+(1-(v-minx)/w)*(100-2*pad), sy:v=>pad+(1-(v-miny)/h)*(100-2*pad), minx,maxx,miny,maxy,w,h,pad};}
function drawMap(){
  const svg=document.getElementById("cmap"); if(!svg||!window.REF)return;
  const T=svgXY(),pts=window.REF.points; _tf=T;
  let d="M"+pts.map(p=>T.sx(p[0]).toFixed(1)+","+T.sy(p[1]).toFixed(1)).join(" L");
  let dots="";
  corners.forEach((c,i)=>{
    let ap=(window.REF.apexes||[]).find(a=>Math.abs((a.n)-(c.n))<0.01);
    // se non c'è un apice memorizzato (curva aggiunta), proietta dal frac sul tracciato
    let X,Y;
    if(ap){X=ap.x;Y=ap.y;}
    else{const p=pts.reduce((b,p)=>Math.abs(p[2]-c.dist_frac)<Math.abs(b[2]-c.dist_frac)?p:b,pts[0]);X=p[0];Y=p[1];}
    dots+=`<circle cx="${T.sx(X).toFixed(1)}" cy="${T.sy(Y).toFixed(1)}" r="2.6" class="apx"/>
           <text x="${T.sx(X).toFixed(1)}" y="${(T.sy(Y)-3.5).toFixed(1)}" class="apxn">${i+1}</text>`;
  });
  svg.innerHTML=`<path d="${d}" class="track"/>${dots}`;
  svg.onclick=(e)=>{
    const r=svg.getBoundingClientRect();
    const px=(e.clientX-r.left)/r.width*100, py=(e.clientY-r.top)/r.height*100;
    // trova il punto del tracciato piu' vicino in coord SVG
    let best=null,bd=1e9;
    pts.forEach(p=>{const dx=T.sx(p[0])-px,dy=T.sy(p[1])-py,dd=dx*dx+dy*dy;if(dd<bd){bd=dd;best=p;}});
    if(best && bd<30){corners.push({n:0,name:"Curva",dist_frac:best[2]});renumber();renderList();drawMap();}
  };
}
document.getElementById("save").onclick=async()=>{
  renumber();
  const r=await fetch("/api/corners",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({track:window.TRACK,corners})});
  const j=await r.json(); if(j.ok){corners=j.corners;renderList();drawMap();alert("Salvato.");}
};
document.getElementById("rebuild").onclick=async()=>{
  if(!confirm("Ricostruire dalla telemetria? Le modifiche manuali andranno perse."))return;
  const r=await fetch("/api/corners/rebuild",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({track:window.TRACK})});
  const j=await r.json(); if(j.ok){corners=j.corners.map(c=>({...c}));location.reload();}
};
renumber(); renderList(); drawMap();
