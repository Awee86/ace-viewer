const chat=document.getElementById("chat"), q=document.getElementById("q"), send=document.getElementById("send");
const useData=document.getElementById("usedata");
let history=[];   // {role, content}
function bubble(who,text,cls){const d=document.createElement("div");d.className="msg "+cls;
  d.innerHTML=`<span class="who">${who}</span><div class="txt"></div>`;
  d.querySelector(".txt").textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
async function ask(){
  const text=q.value.trim(); if(!text)return;
  bubble(window.COACH_DRIVER,text,"me");
  history.push({role:"user",content:text});
  q.value=""; send.disabled=true;
  const wait=bubble("Coach","...","ai wait");
  try{
    const r=await fetch("/api/coach",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({messages:history,use_data:useData&&useData.checked})});
    const j=await r.json(); wait.remove();
    if(j.error){bubble("Coach",j.error,"ai err");}
    else{bubble("Coach",j.answer,"ai");history.push({role:"assistant",content:j.answer});}
  }catch(e){wait.remove();bubble("Coach","Errore: "+e,"ai err");}
  send.disabled=false; q.focus();
}
send.onclick=ask;
q.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}});
