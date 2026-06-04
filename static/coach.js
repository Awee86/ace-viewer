const chat=document.getElementById("chat"), q=document.getElementById("q"), send=document.getElementById("send");
function bubble(who,text,cls){const d=document.createElement("div");d.className="msg "+cls;
  d.innerHTML=`<span class="who">${who}</span><div class="txt"></div>`;d.querySelector(".txt").textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
async function ask(){
  const text=q.value.trim(); if(!text)return;
  bubble(window.COACH_DRIVER,text,"me"); q.value=""; send.disabled=true;
  const wait=bubble("Coach","sto analizzando i dati...","ai wait");
  try{
    const r=await fetch("/api/coach",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:text})});
    const j=await r.json(); wait.remove();
    if(j.error){bubble("Coach",j.error,"ai err");}
    else{const b=bubble("Coach",j.answer,"ai");
      if(j.pista){const m=document.createElement("div");m.className="meta";m.textContent=`${j.pista}${j.auto?' · '+j.auto:''}${j.curva?' · curva '+j.curva:''}`;b.appendChild(m);}}
  }catch(e){wait.remove();bubble("Coach","Errore: "+e,"ai err");}
  send.disabled=false; q.focus();
}
send.onclick=ask;
q.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}});
