/* Home: tracciati richiudibili + ordinamento sessioni per Data/Best (dentro la pista) */
document.querySelectorAll(".trk-head").forEach(h=>{
  h.addEventListener("click",()=>h.parentElement.classList.toggle("collapsed"));
});
document.querySelectorAll(".ts-table th[data-sort]").forEach(th=>{
  th.addEventListener("click",()=>{
    const table=th.closest("table"), tb=table.querySelector("tbody");
    const kind=th.dataset.sort, attr=kind==="lap"?"lapsec":"datekey";
    let asc;
    if(table.dataset.col===kind) asc=table.dataset.dir!=="asc";
    else asc = kind==="lap";                 // default: Best crescente, Data decrescente
    const rows=[...tb.querySelectorAll("tr")];
    rows.sort((a,b)=>{
      let va=a.dataset[attr], vb=b.dataset[attr];
      if(kind==="lap"){va=parseFloat(va);vb=parseFloat(vb);}
      return (va>vb?1:va<vb?-1:0)*(asc?1:-1);
    });
    rows.forEach(r=>tb.appendChild(r));
    table.dataset.col=kind; table.dataset.dir=asc?"asc":"desc";
    table.querySelectorAll("th[data-sort]").forEach(h=>{
      h.classList.remove("sorted");
      h.textContent=h.textContent.replace(/[ ▲▼]+$/,"");
    });
    th.classList.add("sorted");
    th.textContent=th.textContent.replace(/[ ▲▼]+$/,"")+(asc?" ▲":" ▼");
  });
});
