const $=s=>document.querySelector(s);
let DATA=null,FIELDS=[],FOUND=-1,vis=[],cur=0,sortCol=-1,asc=true,rows=[],sel=-1;
// what is playing, as a pool index, plus the queue it came from
let nowIdx=-1,queue=[],qpos=-1,queueKey="",lcdFor=-1,lcdText="";
let shuffleOn=false,repeatMode="off";      // off | all | one
const MODEKEY="playlists.modes";
// How long the button holds its result before going back to its label.
const VLC_NOTICE_MS=1800;
const KEY="playlists.columns", SKINKEY="playlists.skin";

const mmss=s=>isFinite(s)
  ? `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}` : "";
const songs=n=>`${n} ${n===1?"song":"songs"}`;
const MB=1024*1024, GB=1024*MB;
const mb=b=>b>=GB?(b/GB).toFixed(2)+" GB":(b/MB).toFixed(1)+" MB";

// iTunes stored ratings 0-100; five stars is 100.
// iTunes stores a rating as 0-100; five stars means each is worth twenty.
const PER_STAR=20;
const stars=v=>v?"\u2605".repeat(Math.round(v/PER_STAR)):"";
function fmt(v,kind,gone){
  if(gone&&(kind==="time"||kind==="size"))return "";
  if(v===""||v===0||v===null)return kind==="bool"?"":"";
  switch(kind){
    case "time":return mmss(v);
    case "size":return mb(v);
    case "star":return `<span class="star">${stars(v)}</span>`;
    case "kbps":return v+" kbps";
    case "khz":return (v/1000).toFixed(1)+" kHz";
    case "bool":return v?"Yes":"";
    case "found":return v==="direct"?""
      :`<span class="found-${v.replace(/ /g,"-")}">${esc(v)}</span>`;
    default:return esc(String(v));
  }
}
const RIGHT=new Set(["time","size","int","kbps","khz"]);
// locate() distinguishes why a track is unresolved; neither can be played
const GONE=new Set(["gone","ambiguous"]);
const missing=t=>GONE.has(t[FOUND]);
// The visible rows minus the ones with no file. Four call sites wanted this.
const playable=()=>rows.filter(i=>!missing(DATA.tracks[i]));
function span(sec){
  const h=sec/3600;
  if(h>=1)return h.toFixed(1)+" hours";
  return Math.round(sec/60)+" minutes";
}

function drawSources(){
  $("#srclist").innerHTML=DATA.playlists.map((p,i)=>
    `<div class="src${i===cur?" on":""}" data-i="${i}">${NOTE}<span>${esc(p.name)}</span></div>`
  ).join("");
}
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function current(){
  const q=$("#search").value.trim().toLowerCase();
  let list=DATA.playlists[cur].ids.slice();
  if(q)list=list.filter(i=>{const t=DATA.tracks[i];
    return (t[0]+" "+t[2]+" "+t[3]).toLowerCase().includes(q);});
  if(sortCol>=0){
    list.sort((ia,ib)=>{
      const x=DATA.tracks[ia][sortCol],y=DATA.tracks[ib][sortCol];
      const r=typeof x==="number"&&typeof y==="number"?x-y
        :String(x).localeCompare(String(y),undefined,{sensitivity:"base",numeric:true});
      return asc?r:-r;
    });
  }
  return list;
}

function colClass(i,nth){
  const kind=FIELDS[i][1];
  return `col-${kind}`+(i===0?" grow c-name":"")+(nth===vis.length-1?" last":"")
        +(RIGHT.has(kind)?" num":"");
}

function draw(){
  rows=current();
  syncQueue();
  const total=DATA.playlists[cur].ids.length;
  const cls=vis.map(colClass);          // once per column, not once per cell
  $("#thead").innerHTML=vis.map((f,n)=>
    `<div class="${cls[n]}${f===sortCol?" sorted"+(asc?" asc":""):""}" `+
    `data-c="${f}">${esc(FIELDS[f][0])}</div>`).join("");
  $("#rows").innerHTML=rows.length?rows.map((idx,i)=>{
    const t=DATA.tracks[idx], gone=missing(t);
    return `<div class="row${i===sel?" sel":""}${gone?" ghost":""}`+
      `${idx===nowIdx?" playing":""}" data-i="${i}">`+
      vis.map((f,n)=>
        `<div class="${cls[n]}">${fmt(t[f],FIELDS[f][1],gone)}</div>`).join("")+
      `</div>`;}).join("")
    : `<div class="empty">Nothing matches.</div>`;

  const T=FIELDS.findIndex(f=>f[1]==="time"), S=FIELDS.findIndex(f=>f[1]==="size");
  const here=playable();
  const gone=rows.length-here.length;
  const secs=here.reduce((a,i)=>a+DATA.tracks[i][T],0),
        bytes=here.reduce((a,i)=>a+DATA.tracks[i][S],0);
  $("#status").textContent=rows.length
    ? songs(here.length)+`, ${span(secs)}, ${mb(bytes)}`
      +(gone?`   \u00b7   ${gone} missing`:"")
    : "no songs";
  $("#count").textContent=rows.length===total?songs(total):`${rows.length} of ${total}`;
  $("#lcdName").textContent=nowIdx>=0
    ? label(DATA.tracks[nowIdx]) : DATA.playlists[cur].name;
  $("#play").disabled=!here.length;   // nothing playable, even if rows show
  // the LCD covers the whole playlist, not the filtered view, so it only
  // changes when the playlist does -- no need to re-total it on every keystroke
  if(cur!==lcdFor){
    lcdFor=cur;
    const all=DATA.playlists[cur].ids, live=all.filter(i=>!missing(DATA.tracks[i]));
    const absent=all.length-live.length;
    lcdText=songs(live.length)
      +` — ${span(live.reduce((a,i)=>a+DATA.tracks[i][T],0))}`
      +(absent?`   \u00b7   ${absent} missing`:"");
  }
  $("#lcdSub").textContent=lcdText;
}

function saveCols(){try{localStorage.setItem(KEY,JSON.stringify(vis));}catch(e){}}
function loadCols(){
  try{
    const v=JSON.parse(localStorage.getItem(KEY));
    if(Array.isArray(v)&&v.length&&v.every(i=>Number.isInteger(i)&&FIELDS[i]))return v;
  }catch(e){}
  return FIELDS.map((f,i)=>f[2]?i:-1).filter(i=>i>=0);
}

function loadModes(){
  try{
    const m=JSON.parse(localStorage.getItem(MODEKEY));
    if(m&&typeof m==="object"){
      shuffleOn=!!m.shuffle;
      if(m.repeat in REPEAT)repeatMode=m.repeat;
    }
  }catch(e){}
}

function saveModes(){
  try{localStorage.setItem(MODEKEY,JSON.stringify(
    {shuffle:shuffleOn,repeat:repeatMode}));}catch(e){}
}

function paintModes(){
  $("#shuffle").classList.toggle("on",shuffleOn);
  $("#shuffle").title=shuffleOn?"Shuffle on":"Shuffle";
  $("#repeat").classList.toggle("on",repeatMode!=="off");
  $("#repeatBadge").textContent=repeatMode==="one"?"1":"";
  $("#repeat").title="Repeat "+repeatMode;
  audio.loop=(repeatMode==="one");
}

function skinName(){
  try{
    const v=localStorage.getItem(SKINKEY);
    if(SKINS.some(k=>k[0]===v))return v;
  }catch(e){}
  return SKINS[0][0];
}

function applySkin(name){
  // Greenwood is the base stylesheet, so it carries no attribute at all
  if(name===SKINS[0][0])document.documentElement.removeAttribute("data-skin");
  else document.documentElement.setAttribute("data-skin",name);
  try{localStorage.setItem(SKINKEY,name);}catch(e){}
}

function buildPrefs(){
  const now=skinName();
  $("#prefs").innerHTML="<h4>Appearance</h4>"+SKINS.map(([id,label,era])=>
    `<label><input type="radio" name="skin" value="${id}"${id===now?" checked":""}>`+
    `${esc(label)}<span class="era">${esc(era)}</span></label>`).join("");
}

function buildOptions(){
  $("#vo").innerHTML="<h4>View Options</h4>"+FIELDS.map((f,i)=>
    `<label><input type="checkbox" data-f="${i}"${vis.includes(i)?" checked":""}`+
    `${i===0?" disabled":""}> ${esc(f[0])}</label>`).join("");
}

const audio=$("#audio");
// paint() fires on every timeupdate, so these are resolved once rather than
// looked up four times a second for the life of the page.
let el={};
let painted={on:null,elapsed:"",left:"",ends:null};

function label(t){
  const artist=t[2]||t[8];
  return artist?`${t[0]} — ${artist}`:t[0];
}

function shuffled(list,first){
  const out=list.slice();
  for(let i=out.length-1;i>0;i--){            // Fisher-Yates
    const j=Math.floor(Math.random()*(i+1));
    [out[i],out[j]]=[out[j],out[i]];
  }
  // whatever is playing stays put; only what comes after is reordered
  if(first!==undefined){
    const at=out.indexOf(first);
    if(at>0)[out[0],out[at]]=[out[at],out[0]];
  }
  return out;
}

/* The queue is the visible rows. Rebuild it only when that *set* changes --
   selecting a row or retyping the same search must not reshuffle underfoot. */
function syncQueue(force){
  const list=playable();
  const key=list.join(",");
  if(!force&&key===queueKey)return;
  queueKey=key;
  queue=shuffleOn?shuffled(list,nowIdx>=0?nowIdx:undefined):list;
  qpos=queue.indexOf(nowIdx);
}

function play(poolIndex){
  const t=DATA.tracks[poolIndex];
  if(missing(t))return;
  nowIdx=poolIndex;
  syncQueue(true);
  qpos=queue.indexOf(poolIndex);
  audio.src=location.protocol==="file:"?DATA.files[poolIndex]:"audio?i="+poolIndex;
  audio.play().catch(()=>{ lcd(`Cannot play ${t[0]}`); });
  draw();
}

function step(by){
  if(!queue.length)return;
  let at=qpos+by;
  if(at<0||at>=queue.length){
    if(repeatMode!=="all"){stop();return;}
    at=(at+queue.length)%queue.length;
  }
  play(queue[at]);
}

function stop(){
  audio.pause(); audio.removeAttribute("src"); audio.load();
  nowIdx=-1; qpos=-1; paint(); draw();
}

function lcd(msg){ $("#lcdName").textContent=msg; }

function paint(){
  const on=nowIdx>=0&&!audio.paused;
  if(on!==painted.on){                  // play state holds for a whole track
    painted.on=on;
    el.toggleIcon.innerHTML=on
      ? '<path d="M2 1h3.5v12H2zM7.5 1H11v12H7.5z"/>'
      : '<path d="M2 1v12l9.5-6z"/>';
    el.toggle.title=on?"Pause":"Play";
  }
  const ends=nowIdx<0;
  if(ends!==painted.ends){painted.ends=ends; el.prev.disabled=el.next.disabled=ends;}

  const d=audio.duration||0, c=audio.currentTime||0;
  el.barFill.style.width=d?`${100*c/d}%`:"0";     // the only per-tick write

  // the clocks read to the second but timeupdate fires about four times a
  // second, so three writes in four would set the same string
  const elapsed=nowIdx>=0?mmss(c):"", left=nowIdx>=0&&d?"-"+mmss(d-c):"";
  if(elapsed!==painted.elapsed){painted.elapsed=elapsed; el.elapsed.textContent=elapsed;}
  if(left!==painted.left){painted.left=left; el.left.textContent=left;}
}

function boot(){
  for(const id of ["toggleIcon","toggle","barFill","elapsed","left","prev","next"])
    el[id]=$("#"+id);
  FIELDS=DATA.fields; FOUND=FIELDS.length-1; vis=loadCols();
  applySkin(skinName()); buildPrefs(); loadModes(); paintModes();
  drawSources();buildOptions();draw();paint();

  $("#srclist").onclick=e=>{const el=e.target.closest(".src");if(!el)return;
    cur=+el.dataset.i;sel=-1;$("#search").value="";
    drawSources();draw();$("#scroll").scrollTop=0;};
  $("#thead").onclick=e=>{const el=e.target.closest("div[data-c]");if(!el)return;
    const c=+el.dataset.c; asc=(c===sortCol)?!asc:true; sortCol=c; sel=-1; draw();};
  $("#rows").onclick=e=>{const el=e.target.closest(".row");if(!el)return;
    sel=+el.dataset.i;
    // moving a highlight must not rebuild a thousand rows of innerHTML
    $("#rows").querySelector(".row.sel")?.classList.remove("sel");
    el.classList.add("sel");};
  $("#rows").ondblclick=e=>{const el=e.target.closest(".row");if(!el)return;
    play(rows[+el.dataset.i]);};

  $("#toggle").onclick=()=>{
    if(nowIdx<0){                       // nothing cued: start at the selection
      const start=sel>=0?rows[sel]:playable()[0];
      if(start!==undefined)play(start);
      return;
    }
    audio.paused?audio.play():audio.pause();
  };
  $("#prev").onclick=()=>step(-1);
  $("#next").onclick=()=>step(1);
  $("#vol").oninput=e=>{audio.volume=+e.target.value;};

  $("#shuffle").onclick=()=>{
    shuffleOn=!shuffleOn;
    syncQueue(true);                     // reshuffle, as iTunes did on each toggle
    saveModes(); paintModes(); draw();
  };
  $("#repeat").onclick=()=>{
    repeatMode=REPEAT[repeatMode];
    saveModes(); paintModes();
  };

  $("#bar").onclick=e=>{
    if(!audio.duration)return;
    const r=$("#bar").getBoundingClientRect();
    audio.currentTime=audio.duration*Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
  };

  audio.addEventListener("timeupdate",paint);
  audio.addEventListener("play",paint);
  audio.addEventListener("pause",paint);
  audio.addEventListener("loadedmetadata",paint);
  audio.addEventListener("ended",()=>step(1));
  audio.addEventListener("error",()=>{
    const t=DATA.tracks[nowIdx];
    lcd(t?`Cannot play ${t[0]}`:"Playback failed");
  });
  $("#search").oninput=()=>{sel=-1;draw();};

  $("#play").onclick=async()=>{
    const pl=DATA.playlists[cur], btn=$("#play"), label=$("#playLabel");
    if(!rows.length)return;
    btn.disabled=true; label.textContent="Opening\u2026";
    let msg="Play in VLC";
    try{
      const r=await fetch("play",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({name:pl.name,
          indices:playable()})});
      if(!r.ok)msg=(await r.json()).error||"Failed";
    }catch(e){ msg="Server not running"; }
    label.textContent=msg==="Play in VLC"?"Playing\u2026":msg;
    setTimeout(()=>{label.textContent="Play in VLC";btn.disabled=false;},VLC_NOTICE_MS);
  };

  // right-click the headers for the column picker, as iTunes did
  const openPanel=(el,x,y)=>{
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("open"));
    el.style.left=Math.min(x,innerWidth-210)+"px";
    el.style.top=Math.min(y,innerHeight-el.scrollHeight-12)+"px";
    el.classList.add("open");
  };
  $("#thead").oncontextmenu=e=>{e.preventDefault();openPanel($("#vo"),e.clientX,e.clientY);};
  $("#gear").onclick=e=>{
    e.stopPropagation();
    const r=$("#gear").getBoundingClientRect();
    openPanel($("#prefs"),r.right-200,r.top-$("#prefs").scrollHeight-8);
  };
  $("#prefs").onchange=e=>{ applySkin(e.target.value); };
  $("#vo").onchange=e=>{
    const i=+e.target.dataset.f;
    vis = e.target.checked ? FIELDS.map((_,n)=>n).filter(n=>n===i||vis.includes(n))
                           : vis.filter(n=>n!==i);
    if(!vis.includes(sortCol))sortCol=-1;
    saveCols();draw();
  };
  document.addEventListener("mousedown",e=>{
    if(e.target.closest(".panel")||e.target.closest("#thead")||e.target.closest("#gear"))return;
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("open"));
  });
}

DATA=LIBRARY;boot();
