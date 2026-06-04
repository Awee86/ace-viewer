(function(){
  const W=document.getElementById("coachw"); if(!W)return;
  const toggle=document.getElementById("coachw-toggle"), min=document.getElementById("coachw-min"),
        clear=document.getElementById("coachw-clear"), msgs=document.getElementById("coachw-msgs"),
        q=document.getElementById("coachw-q"), send=document.getElementById("coachw-send"),
        useData=document.getElementById("coachw-usedata"), navOpen=document.getElementById("coach-open");
  const HKEY="ace_coach_history", OKEY="ace_coach_open", UKEY="ace_coach_usedata";
  let history=[];
  try{history=JSON.parse(sessionStorage.getItem(HKEY)||"[]");}catch(e){history=[];}
  if(useData) useData.checked=sessionStorage.getItem(UKEY)==="1";

  function save(){sessionStorage.setItem(HKEY,JSON.stringify(history.slice(-40)));}
  function bubble(who,text,cls){const d=document.createElement("div");d.className="msg "+cls;
    d.innerHTML='<span class="who"></span><div class="txt"></div>';
    d.querySelector(".who").textContent=who;d.querySelector(".txt").textContent=text;
    msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;return d;}
  function renderAll(){msgs.innerHTML="";history.forEach(m=>bubble(m.role==="user"?(window.COACH_DRIVER||"Tu"):"Coach",m.content,m.role==="user"?"me":"ai"));}
  function open(){W.classList.remove("collapsed");sessionStorage.setItem(OKEY,"1");q.focus();msgs.scrollTop=msgs.scrollHeight;}
  function close(){W.classList.add("collapsed");sessionStorage.setItem(OKEY,"0");}

  renderAll();
  if(sessionStorage.getItem(OKEY)==="1") open();

  toggle.onclick=open; min.onclick=close;
  if(navOpen) navOpen.onclick=(e)=>{e.preventDefault();open();};
  clear.onclick=()=>{if(confirm("Pulire la conversazione?")){history=[];save();renderAll();}};
  if(useData) useData.onchange=()=>sessionStorage.setItem(UKEY,useData.checked?"1":"0");
  q.addEventListener("input",()=>{q.style.height="auto";q.style.height=Math.min(q.scrollHeight,100)+"px";});

  async function ask(){
    const text=q.value.trim(); if(!text)return;
    bubble(window.COACH_DRIVER||"Tu",text,"me"); history.push({role:"user",content:text}); save();
    q.value="";q.style.height="auto"; send.disabled=true;
    const wait=bubble("Coach","...","ai wait");
    try{
      const r=await fetch("/api/coach",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({messages:history,use_data:useData&&useData.checked})});
      const j=await r.json(); wait.remove();
      if(j.error){bubble("Coach",j.error,"ai err");}
      else{bubble("Coach",j.answer,"ai");history.push({role:"assistant",content:j.answer});save();}
    }catch(e){wait.remove();bubble("Coach","Errore: "+e,"ai err");}
    send.disabled=false; q.focus();
  }
  send.onclick=ask;
  q.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask();}});
})();
