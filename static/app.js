const $=s=>document.querySelector(s);
// cur is a playlist index, or LIB for the whole music library
const LIB=-1;
let DATA=null,FIELDS=[],FOUND=-1,vis=[],cur=LIB,sortCol=-1,asc=true,rows=[],sel=-1;
// what is playing, as a pool index; the list it was started from, and the
// order that list plays in (shuffled or not)
let nowIdx=-1,context=[],queue=[],qpos=-1,lcdFor=null,lcdText="";
// Up Next plays ahead of the queue; fromUpNext marks a track that came from it
let upNext=[],fromUpNext=false;
let shuffleOn=false,repeatMode="off";      // off | all | one
let view="songs",browserOn=false,browse={genre:null,artist:null,album:null};
let openAlbum=-1,artistSel=null,viewAlbums=[],viewAlbumIds=new Map();
// pool index -> album index, and artist -> its place in iTunes' artist order
let ALBUM_OF=null,ARTIST_RANK=new Map();
let T=-1,S=-1,GENRE=-1,TRACKNO=-1,RATING=-1;
const MODEKEY="playlists.modes", VIEWKEY="playlists.view";
// How long the button holds its result before going back to its label.
const VLC_NOTICE_MS=1800;
const KEY="playlists.columns", SKINKEY="playlists.skin";
// Track rows are a fixed height, so only the ones on screen are built.
const ROW_H=17, OVERSCAN=20;
// Type-to-find keeps adding letters until the typist pauses this long.
const FIND_RESET_MS=900;
// album entries: [title, artist, year, art url, average colour, pool ids]
const A_TITLE=0,A_ARTIST=1,A_YEAR=2,A_ART=3,A_COLOUR=4,A_IDS=5;
const VIEWS=["songs","albums","artists"];
const BIG_NOTE='<svg viewBox="0 0 9 11"><path d="M3 0v7.1A2 2 0 1 0 4 9V3h4V0z"/></svg>';

const mmss=s=>isFinite(s)
  ? `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}` : "";
const songs=n=>`${n} ${n===1?"song":"songs"}`;
const MB=1024*1024, GB=1024*MB;
const mb=b=>b>=GB?(b/GB).toFixed(2)+" GB":(b/MB).toFixed(1)+" MB";

// iTunes stores a rating as 0-100; five stars means each is worth twenty.
// A rating half a point low is one iTunes computed from the album's, drawn
// hollow; it still sorts with its star count, just below the hand-set ones.
const PER_STAR=20;
const stars=v=>v?(Number.isInteger(v)?"★":"☆").repeat(Math.round(v/PER_STAR)):"";
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
const live=list=>list.filter(i=>!missing(DATA.tracks[i]));
// The visible rows minus the ones with no file.
const playable=()=>live(rows);
const secsOf=list=>list.reduce((a,i)=>a+DATA.tracks[i][T],0);
function span(sec){
  const h=sec/3600;
  if(h>=1)return h.toFixed(1)+" hours";
  return Math.round(sec/60)+" minutes";
}
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const byText=(a,b)=>a.localeCompare(b,undefined,{sensitivity:"base",numeric:true});
const byRank=(a,b)=>ARTIST_RANK.get(a)-ARTIST_RANK.get(b);

const sourceIds=()=>cur===LIB?DATA.music:DATA.playlists[cur].ids;
const sourceName=()=>cur===LIB?"Library":DATA.playlists[cur].name;
const albumOf=i=>DATA.albums[ALBUM_OF[i]];

function drawSources(){
  $("#srclist").innerHTML=
    `<div class="src lib${cur===LIB?" on":""}" data-i="${LIB}">${NOTE}<span>Library</span></div>`+
    DATA.playlists.map((p,i)=>
      `<div class="src${i===cur?" on":""}" data-i="${i}">${NOTE}<span>${esc(p.name)}</span></div>`
    ).join("");
}

function searched(){
  const q=$("#search").value.trim().toLowerCase();
  const list=sourceIds();
  if(!q)return list;
  return list.filter(i=>{const t=DATA.tracks[i];
    return (t[0]+" "+t[2]+" "+t[3]).toLowerCase().includes(q);});
}

function browsed(list){
  if(!browserOn)return list;
  return list.filter(i=>(browse.genre===null||DATA.tracks[i][GENRE]===browse.genre)
    &&(browse.artist===null||albumOf(i)[A_ARTIST]===browse.artist)
    &&(browse.album===null||albumOf(i)[A_TITLE]===browse.album));
}

function sorted(list){
  list=list.slice();
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

/* [album index, its ids within list] for every album list touches, in the
   library's album order, which is iTunes' artist-then-album order. */
function albumsIn(list){
  const inList=new Set(list), touched=new Set();
  for(const i of list)touched.add(ALBUM_OF[i]);
  return [...touched].sort((a,b)=>a-b)
    .map(a=>[a,DATA.albums[a][A_IDS].filter(i=>inList.has(i))]);
}

function colClass(i,nth){
  const kind=FIELDS[i][1];
  return `col-${kind}`+(i===0?" grow c-name":"")+(nth===vis.length-1?" last":"")
        +(RIGHT.has(kind)?" num":"");
}

function draw(){
  const base=searched();
  if(view==="songs"){
    drawBrowser(base);
    rows=sorted(browsed(base));
    drawSongs();
  }else{
    viewAlbums=albumsIn(base);
    viewAlbumIds=new Map(viewAlbums);
    rows=viewAlbums.flatMap(a=>a[1]);
    if(view==="albums")drawAlbums();
    else drawArtists();
  }

  const total=sourceIds().length;
  const here=playable();
  const gone=rows.length-here.length;
  const bytes=here.reduce((a,i)=>a+DATA.tracks[i][S],0);
  const albums=view==="songs"?"":`${viewAlbums.length} albums, `;
  $("#status").textContent=rows.length
    ? albums+songs(here.length)+`, ${span(secsOf(here))}, ${mb(bytes)}`
      +(gone?`   ·   ${gone} missing`:"")
    : "no songs";
  $("#count").textContent=rows.length===total?songs(total):`${rows.length} of ${total}`;
  $("#play").disabled=!here.length;   // nothing playable, even if rows show
  paintLcd();
}

/* ---- Songs: the column browser and the track table ----------------------- */

function distinct(list,f){
  const out=new Set();
  for(const i of list){const v=f(i); if(v!=="")out.add(v);}
  return [...out];
}

function pane(id,key,values,noun){
  $(id).innerHTML=
    `<div class="pi all${browse[key]===null?" on":""}" data-k="${key}" data-all>`+
    `All (${values.length} ${noun})</div>`+
    values.map(v=>`<div class="pi${v===browse[key]?" on":""}" data-k="${key}" `+
      `data-v="${esc(v)}">${esc(v)}</div>`).join("");
}

function drawBrowser(base){
  $("#browser").classList.toggle("on",browserOn);
  $("#browse").classList.toggle("on",browserOn);
  if(!browserOn)return;
  const genre=browse.genre===null?base:base.filter(i=>DATA.tracks[i][GENRE]===browse.genre);
  const artist=browse.artist===null?genre
    :genre.filter(i=>albumOf(i)[A_ARTIST]===browse.artist);
  pane("#pgenre","genre",distinct(base,i=>DATA.tracks[i][GENRE]).sort(byText),"Genres");
  pane("#partist","artist",distinct(genre,i=>albumOf(i)[A_ARTIST]).sort(byRank),"Artists");
  pane("#palbum","album",distinct(artist,i=>albumOf(i)[A_TITLE]).sort(byText),"Albums");
}

let colCls=[],shown=[-1,-1];
function drawSongs(){
  colCls=vis.map(colClass);          // once per column, not once per cell
  $("#thead").innerHTML=vis.map((f,n)=>
    `<div class="${colCls[n]}${f===sortCol?" sorted"+(asc?" asc":""):""}" `+
    `data-c="${f}">${esc(FIELDS[f][0])}</div>`).join("");
  const r=$("#rows");
  if(!rows.length){
    r.style.height=""; r.style.paddingTop="";
    r.innerHTML=`<div class="empty">Nothing matches.</div>`;
    shown=[-1,-1];
    return;
  }
  r.style.height=rows.length*ROW_H+"px";
  renderRows(true);
}

function rowHtml(i){
  const idx=rows[i], t=DATA.tracks[idx], gone=missing(t);
  return `<div class="row${i%2?" alt":""}${i===sel?" sel":""}${gone?" ghost":""}`+
    `${idx===nowIdx?" playing":""}" data-i="${i}" data-t="${idx}">`+
    vis.map((f,n)=>`<div class="${colCls[n]}">${fmt(t[f],FIELDS[f][1],gone)}</div>`).join("")+
    `</div>`;
}

// Build only the rows in view, plus a margin; the padding stands in for the rest.
function renderRows(force){
  if(!rows.length)return;
  const sc=$("#scroll"), r=$("#rows");
  const top=Math.max(0,sc.scrollTop-r.offsetTop);
  const first=Math.max(0,Math.floor(top/ROW_H)-OVERSCAN);
  const last=Math.min(rows.length,Math.ceil((top+sc.clientHeight)/ROW_H)+OVERSCAN);
  if(!force&&first===shown[0]&&last===shown[1])return;
  shown=[first,last];
  r.style.paddingTop=first*ROW_H+"px";
  let h="";
  for(let i=first;i<last;i++)h+=rowHtml(i);
  r.innerHTML=h;
}

function setSel(i){
  sel=i;
  document.querySelector("#rows .row.sel")?.classList.remove("sel");
  document.querySelector(`#rows .row[data-i="${i}"]`)?.classList.add("sel");
}

function ensureVisible(i){
  const sc=$("#scroll"), head=$("#rows").offsetTop, y=head+i*ROW_H;
  if(y<sc.scrollTop+head)sc.scrollTop=y-head;
  else if(y+ROW_H>sc.scrollTop+sc.clientHeight)sc.scrollTop=y+ROW_H-sc.clientHeight;
  renderRows();
}

function moveSel(by){
  if(!rows.length)return;
  const i=Math.min(rows.length-1,Math.max(0,sel<0?0:sel+by));
  ensureVisible(i); setSel(i);
}

/* ---- Albums: the iTunes 11 grid, expanded in place ------------------------ */

function coverHtml(a,lazy){
  const art=DATA.albums[a][A_ART];
  return art?`<img class="cover"${lazy?' loading="lazy"':""} src="${art}" alt="">`
            :`<div class="cover">${BIG_NOTE}</div>`;
}

function trkHtml(i,n){
  const t=DATA.tracks[i];
  return `<div class="trk${missing(t)?" ghost":""}${i===nowIdx?" playing":""}" data-t="${i}">`+
    `<i>${t[TRACKNO]||n+1}</i><span>${esc(t[0])}</span>`+
    `${fmt(t[RATING],"star")}<em>${mmss(t[T])}</em></div>`;
}

function albumSub(a,ids){
  const year=DATA.albums[a][A_YEAR];
  return (year?year+" · ":"")+`${songs(ids.length)}, ${span(secsOf(ids))}`;
}

function drawAlbums(){
  $("#grid").innerHTML=viewAlbums.length?viewAlbums.map(([a])=>{
    const al=DATA.albums[a];
    return `<div class="tile${a===openAlbum?" on":""}" data-a="${a}">${coverHtml(a,true)}`+
      `<b>${esc(al[A_TITLE])}</b><span>${esc(al[A_ARTIST])}</span></div>`;
  }).join("") : `<div class="empty">Nothing matches.</div>`;
  placeExpand();
}

// Light covers get dark text, as iTunes 11 did with its tinted panels.
function inkFor(hex){
  const n=parseInt(hex.slice(1),16);
  const lum=(0.299*(n>>16)+0.587*(n>>8&255)+0.114*(n&255))/255;
  return lum>0.55?"#141414":"#f5f5f5";
}

function placeExpand(){
  document.querySelector("#grid .expand")?.remove();
  document.querySelector("#grid .tile.on")?.classList.remove("on");
  const tile=document.querySelector(`#grid .tile[data-a="${openAlbum}"]`);
  if(!tile){openAlbum=-1;return;}
  tile.classList.add("on");
  // the panel opens under the clicked tile's whole row, not inside it
  let end=tile;
  while(end.nextElementSibling&&end.nextElementSibling.offsetTop===tile.offsetTop)
    end=end.nextElementSibling;
  const al=DATA.albums[openAlbum], ids=viewAlbumIds.get(openAlbum);
  const bg=al[A_COLOUR]||"#3c3f45";
  end.insertAdjacentHTML("afterend",
    `<div class="expand" data-a="${openAlbum}" style="--x-bg:${bg};--x-ink:${inkFor(bg)}">`+
    `${coverHtml(openAlbum)}<div class="xbody"><h3>${esc(al[A_TITLE])}</h3>`+
    `<div class="xsub">${esc(al[A_ARTIST])} · ${albumSub(openAlbum,ids)}`+
    `<button class="xplay">Play</button></div>`+
    `<div class="tracklist">${ids.map(trkHtml).join("")}</div></div></div>`);
  document.querySelector("#grid .expand").scrollIntoView({block:"nearest"});
}

/* ---- Artists: the list, and the chosen artist's albums -------------------- */

const artistTracks=name=>
  viewAlbums.filter(([a])=>DATA.albums[a][A_ARTIST]===name).flatMap(a=>a[1]);

function drawArtists(){
  // viewAlbums is in artist order already, so first appearance is the order
  const names=[...new Set(viewAlbums.map(([a])=>DATA.albums[a][A_ARTIST]))];
  if(!names.includes(artistSel))artistSel=names.length?names[0]:null;
  $("#alist").innerHTML=names.map(n=>
    `<div class="pi${n===artistSel?" on":""}" data-v="${esc(n)}">${esc(n)}</div>`).join("")
    || `<div class="empty">Nothing matches.</div>`;
  drawArtist();
}

function drawArtist(){
  const mine=viewAlbums.filter(([a])=>DATA.albums[a][A_ARTIST]===artistSel);
  $("#adetail").innerHTML=artistSel===null?"":`<h2>${esc(artistSel)}</h2>`+
    mine.map(([a,ids])=>`<div class="ablock" data-a="${a}">${coverHtml(a,true)}`+
      `<div class="xbody"><h3>${esc(DATA.albums[a][A_TITLE])}</h3>`+
      `<div class="xsub">${albumSub(a,ids)}</div>`+
      `<div class="tracklist">${ids.map(trkHtml).join("")}</div></div></div>`).join("");
}

function selectArtist(name){
  artistSel=name;
  document.querySelector("#alist .pi.on")?.classList.remove("on");
  [...document.querySelectorAll("#alist .pi")].find(p=>p.dataset.v===name)
    ?.classList.add("on");
  drawArtist(); $("#adetail").scrollTop=0;
}

// The list a track inside an album panel or the artist view plays through.
function contextFor(el){
  if(el.closest("#adetail"))return artistTracks(artistSel);
  return viewAlbumIds.get(+el.closest("[data-a]").dataset.a);
}

/* ---- Preferences ---------------------------------------------------------- */

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

function loadView(){
  try{
    const v=JSON.parse(localStorage.getItem(VIEWKEY));
    if(v&&typeof v==="object"){
      if(VIEWS.includes(v.view))view=v.view;
      browserOn=!!v.browser;
    }
  }catch(e){}
}

function saveView(){
  try{localStorage.setItem(VIEWKEY,JSON.stringify({view,browser:browserOn}));}catch(e){}
}

function paintModes(){
  $("#shuffle").classList.toggle("on",shuffleOn);
  $("#shuffle").title=shuffleOn?"Shuffle on":"Shuffle";
  $("#repeat").classList.toggle("on",repeatMode!=="off");
  $("#repeatBadge").textContent=repeatMode==="one"?"1":"";
  $("#repeat").title="Repeat "+repeatMode;
  audio.loop=(repeatMode==="one");
}

function paintView(){
  document.querySelectorAll("#views button").forEach(b=>
    b.classList.toggle("on",b.dataset.v===view));
  for(const v of VIEWS)$("#v"+v).classList.toggle("on",v===view);
  $("#browse").style.visibility=view==="songs"?"":"hidden";
}

function setView(v){
  view=v; saveView(); paintView(); draw();
}

function toggleBrowser(){
  if(view!=="songs")return;
  browserOn=!browserOn; saveView(); sel=-1; draw();
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

/* ---- Playback ------------------------------------------------------------- */

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

/* The queue is the list play started from, as in iTunes: browsing, searching
   or changing source afterwards does not change what plays next. */
function reorder(){
  queue=shuffleOn?shuffled(context,nowIdx>=0?nowIdx:undefined):context;
  qpos=queue.indexOf(nowIdx);
}

function play(poolIndex,list){
  if(poolIndex===undefined||missing(DATA.tracks[poolIndex]))return;
  context=live(list);
  nowIdx=poolIndex;
  reorder();
  start(poolIndex,false);
}

function playAt(at){ qpos=at; start(queue[at],false); }

function start(poolIndex,queued){
  const t=DATA.tracks[poolIndex];
  nowIdx=poolIndex; fromUpNext=queued;
  audio.src=location.protocol==="file:"?DATA.files[poolIndex]:"audio?i="+poolIndex;
  audio.play().catch(()=>{ lcd(`Cannot play ${t[0]}`); });
  markPlaying(); paintLcd(); setSession();
}

function step(by){
  if(by>0&&upNext.length){ start(upNext.shift(),true); paintUpNext(); return; }
  if(!queue.length)return;
  // back from an Up Next track returns to the queue track it interrupted
  let at=fromUpNext&&by<0?qpos:qpos+by;
  if(at<0||at>=queue.length){
    if(repeatMode!=="all"){stop();return;}
    at=(at+queue.length)%queue.length;
  }
  playAt(at);
}

function stop(){
  audio.pause(); audio.removeAttribute("src"); audio.load();
  nowIdx=-1; qpos=-1; fromUpNext=false; paint(); markPlaying(); paintLcd();
}

function togglePlay(){
  if(nowIdx>=0){ audio.paused?audio.play():audio.pause(); return; }
  if(upNext.length){ step(1); return; }
  // nothing cued: start at the selection, else at the top of the view
  play(view==="songs"&&sel>=0?rows[sel]:playable()[0],rows);
}

function markPlaying(){
  document.querySelectorAll(".playing").forEach(e=>e.classList.remove("playing"));
  if(nowIdx>=0)document.querySelectorAll(`[data-t="${nowIdx}"]`)
    .forEach(e=>e.classList.add("playing"));
}

function lcd(msg){ $("#lcdName").textContent=msg; }

function paintLcd(){
  const t=nowIdx>=0?DATA.tracks[nowIdx]:null;
  lcd(t?label(t):sourceName());
  const art=t?albumOf(nowIdx)[A_ART]:"";
  $("#lcd").classList.toggle("art",!!art);
  if(art)$("#lcdArt").src=art;
  // the second line covers the whole source, not the filtered view, so it only
  // changes when the source does -- no need to re-total it on every keystroke
  if(cur!==lcdFor){
    lcdFor=cur;
    const all=sourceIds(), here=live(all), absent=all.length-here.length;
    lcdText=songs(here.length)+` — ${span(secsOf(here))}`
      +(absent?`   ·   ${absent} missing`:"");
  }
  $("#lcdSub").textContent=lcdText;
}

// Media keys and the desktop's now-playing panel.
function setSession(){
  if(!("mediaSession" in navigator))return;
  const t=DATA.tracks[nowIdx], al=albumOf(nowIdx);
  navigator.mediaSession.metadata=new MediaMetadata({
    title:t[0], artist:t[2]||al[A_ARTIST], album:t[3],
    artwork:al[A_ART]?[{src:new URL(al[A_ART],location.href).href,type:"image/jpeg"}]:[]});
}

function paint(){
  const on=nowIdx>=0&&!audio.paused;
  if(on!==painted.on){                  // play state holds for a whole track
    painted.on=on;
    el.toggleIcon.innerHTML=on
      ? '<path d="M2 1h3.5v12H2zM7.5 1H11v12H7.5z"/>'
      : '<path d="M2 1v12l9.5-6z"/>';
    el.toggle.title=on?"Pause":"Play";
    if("mediaSession" in navigator)
      navigator.mediaSession.playbackState=nowIdx<0?"none":on?"playing":"paused";
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

/* ---- Up Next and the context menu ------------------------------------------ */

function enqueue(ids,next){
  const ok=live(ids);
  if(next)upNext.unshift(...ok); else upNext.push(...ok);
  paintUpNext();
}

function paintUpNext(){
  $("#upnextBadge").textContent=upNext.length?String(Math.min(upNext.length,99)):"";
  $("#upnextBtn").classList.toggle("on",upNext.length>0);
  $("#upnext").innerHTML=`<h4>Up Next<button data-clear>Clear</button></h4>`+
    (upNext.length?upNext.map((i,n)=>`<div class="un" data-n="${n}">`+
      `<span>${esc(label(DATA.tracks[i]))}</span><button title="Remove">✕</button></div>`)
      .join(""):`<div class="none">Nothing queued.</div>`);
}

function closePanels(){
  document.querySelectorAll(".panel").forEach(p=>p.classList.remove("open"));
}

function openPanel(p,x,y){
  closePanels();
  p.style.left=Math.max(4,Math.min(x,innerWidth-p.offsetWidth-12,innerWidth-210))+"px";
  p.classList.add("open");
  p.style.top=Math.max(4,Math.min(y,innerHeight-p.offsetHeight-12))+"px";
}

// What the open context menu acts on: the tracks, and what Play starts.
let menu={ids:[],first:undefined,list:[]};
function openMenu(e,ids,first,list){
  e.preventDefault();
  menu={ids,first,list};
  $("#ctx").innerHTML='<div class="mi" data-m="play">Play</div>'+
    '<div class="mi" data-m="next">Play Next</div>'+
    '<div class="mi" data-m="add">Add to Up Next</div>';
  openPanel($("#ctx"),e.clientX,e.clientY);
}

/* ---- Keyboard ---------------------------------------------------------------- */

let findText="",findAt=0;
function typeToFind(ch){
  const now=Date.now();
  findText=(now-findAt>FIND_RESET_MS?"":findText)+ch.toLowerCase(); findAt=now;
  const starts=s=>s.toLowerCase().startsWith(findText);
  if(view==="songs"){
    const col=sortCol>=0&&FIELDS[sortCol][1]==="text"?sortCol:0;
    const i=rows.findIndex(r=>starts(String(DATA.tracks[r][col])));
    if(i>=0){ensureVisible(i); setSel(i);}
  }else if(view==="artists"){
    const p=[...document.querySelectorAll("#alist .pi")].find(p=>starts(p.dataset.v));
    if(p){selectArtist(p.dataset.v); p.scrollIntoView({block:"nearest"});}
  }else{
    const tile=[...document.querySelectorAll("#grid .tile")]
      .find(x=>starts(DATA.albums[+x.dataset.a][A_TITLE]));
    if(tile)tile.scrollIntoView({block:"nearest"});
  }
}

function onKey(e){
  const typing=e.target.matches("input,textarea,select");
  const mod=e.ctrlKey||e.metaKey, key=e.key.toLowerCase();
  if(e.key==="Escape"){
    closePanels();
    if(typing)e.target.blur();
    else if(openAlbum>=0){openAlbum=-1; placeExpand();}
    return;
  }
  if(mod&&key==="f"){e.preventDefault(); $("#search").focus(); $("#search").select(); return;}
  if(mod&&key==="b"){e.preventDefault(); toggleBrowser(); return;}
  if(typing||e.altKey)return;
  if(e.key===" "){e.preventDefault(); togglePlay(); return;}
  if(e.key==="ArrowRight"){e.preventDefault(); step(1); return;}
  if(e.key==="ArrowLeft"){e.preventDefault(); step(-1); return;}
  if(mod)return;
  if(view==="songs"&&(e.key==="ArrowDown"||e.key==="ArrowUp")){
    e.preventDefault(); moveSel(e.key==="ArrowDown"?1:-1); return;
  }
  if(view==="songs"&&e.key==="Enter"&&sel>=0){play(rows[sel],rows); return;}
  if(e.key.length===1)typeToFind(e.key);
}

/* ---- Wiring ------------------------------------------------------------------- */

function boot(){
  for(const id of ["toggleIcon","toggle","barFill","elapsed","left","prev","next"])
    el[id]=$("#"+id);
  FIELDS=DATA.fields; FOUND=FIELDS.length-1; vis=loadCols();
  T=FIELDS.findIndex(f=>f[1]==="time"); S=FIELDS.findIndex(f=>f[1]==="size");
  GENRE=FIELDS.findIndex(f=>f[0]==="Genre"); TRACKNO=FIELDS.findIndex(f=>f[0]==="#");
  RATING=FIELDS.findIndex(f=>f[0]==="Rating");
  ALBUM_OF=new Int32Array(DATA.tracks.length);
  DATA.albums.forEach((al,a)=>{
    for(const i of al[A_IDS])ALBUM_OF[i]=a;
    if(!ARTIST_RANK.has(al[A_ARTIST]))ARTIST_RANK.set(al[A_ARTIST],a);
  });
  applySkin(skinName()); buildPrefs(); loadModes(); paintModes(); loadView(); paintView();
  drawSources();buildOptions();paintUpNext();draw();paint();

  $("#srclist").onclick=e=>{const el=e.target.closest(".src");if(!el)return;
    cur=+el.dataset.i;sel=-1;$("#search").value="";
    browse={genre:null,artist:null,album:null}; openAlbum=-1;
    drawSources();draw();
    for(const id of ["#scroll","#grid","#alist","#adetail"])$(id).scrollTop=0;};
  $("#views").onclick=e=>{const b=e.target.closest("button");if(b)setView(b.dataset.v);};
  $("#browse").onclick=toggleBrowser;
  $("#browser").onclick=e=>{const p=e.target.closest(".pi");if(!p)return;
    const k=p.dataset.k;
    browse[k]=p.hasAttribute("data-all")?null:p.dataset.v;
    if(k==="genre")browse.artist=browse.album=null;
    if(k==="artist")browse.album=null;
    sel=-1; draw(); $("#scroll").scrollTop=0;};

  $("#thead").onclick=e=>{const el=e.target.closest("div[data-c]");if(!el)return;
    const c=+el.dataset.c; asc=(c===sortCol)?!asc:true; sortCol=c; sel=-1; draw();};
  $("#scroll").addEventListener("scroll",()=>renderRows(),{passive:true});
  $("#rows").onclick=e=>{const el=e.target.closest(".row");if(el)setSel(+el.dataset.i);};
  $("#rows").ondblclick=e=>{const el=e.target.closest(".row");if(!el)return;
    play(rows[+el.dataset.i],rows);};
  $("#rows").oncontextmenu=e=>{const el=e.target.closest(".row");if(!el)return;
    setSel(+el.dataset.i); const t=rows[sel]; openMenu(e,[t],t,rows);};

  $("#grid").onclick=e=>{
    if(e.target.closest(".xplay")){const ids=viewAlbumIds.get(openAlbum);
      play(live(ids)[0],ids); return;}
    const tile=e.target.closest(".tile");if(!tile)return;
    openAlbum=+tile.dataset.a===openAlbum?-1:+tile.dataset.a; placeExpand();};
  $("#grid").ondblclick=e=>{const tile=e.target.closest(".tile");if(!tile)return;
    const ids=viewAlbumIds.get(+tile.dataset.a); play(live(ids)[0],ids);};
  $("#grid").oncontextmenu=e=>{
    if(e.target.closest(".trk"))return;           // handled as a track below
    const tile=e.target.closest(".tile");if(!tile)return;
    const ids=viewAlbumIds.get(+tile.dataset.a); openMenu(e,ids,live(ids)[0],ids);};

  $("#alist").onclick=e=>{const p=e.target.closest(".pi");if(p)selectArtist(p.dataset.v);};
  $("#alist").oncontextmenu=e=>{const p=e.target.closest(".pi");if(!p)return;
    selectArtist(p.dataset.v); const ids=artistTracks(p.dataset.v);
    openMenu(e,ids,live(ids)[0],ids);};

  // tracks inside an expanded album or the artist view
  for(const id of ["#grid","#adetail"]){
    $(id).addEventListener("click",e=>{const t=e.target.closest(".trk");if(!t)return;
      document.querySelector(".trk.sel")?.classList.remove("sel"); t.classList.add("sel");});
    $(id).addEventListener("dblclick",e=>{const t=e.target.closest(".trk");if(!t)return;
      e.stopPropagation(); play(+t.dataset.t,contextFor(t));});
    $(id).addEventListener("contextmenu",e=>{const t=e.target.closest(".trk");if(!t)return;
      openMenu(e,[+t.dataset.t],+t.dataset.t,contextFor(t));});
  }

  $("#ctx").onclick=e=>{const m=e.target.closest(".mi");if(!m)return;
    closePanels();
    if(m.dataset.m==="play")play(menu.first,menu.list);
    else enqueue(menu.ids,m.dataset.m==="next");};
  $("#upnextBtn").onclick=()=>{
    const p=$("#upnext");
    if(p.classList.contains("open")){closePanels(); return;}
    const r=$("#upnextBtn").getBoundingClientRect();
    p.classList.add("open");      // measured open, so its height is known
    openPanel(p,r.left,r.top-p.offsetHeight-8);
  };
  $("#upnext").onclick=e=>{
    if(e.target.closest("[data-clear]"))upNext=[];
    else{const un=e.target.closest(".un");
      if(un&&e.target.closest("button"))upNext.splice(+un.dataset.n,1);}
    paintUpNext();
  };

  $("#toggle").onclick=togglePlay;
  $("#prev").onclick=()=>step(-1);
  $("#next").onclick=()=>step(1);
  $("#vol").oninput=e=>{audio.volume=+e.target.value;};

  $("#shuffle").onclick=()=>{
    shuffleOn=!shuffleOn;
    reorder();                           // reshuffle, as iTunes did on each toggle
    saveModes(); paintModes();
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
  if("mediaSession" in navigator){
    const ms=navigator.mediaSession;
    ms.setActionHandler("play",togglePlay);
    ms.setActionHandler("pause",()=>audio.pause());
    ms.setActionHandler("previoustrack",()=>step(-1));
    ms.setActionHandler("nexttrack",()=>step(1));
    ms.setActionHandler("seekto",d=>{audio.currentTime=d.seekTime;});
  }
  $("#search").oninput=()=>{sel=-1;draw();};
  document.addEventListener("keydown",onKey);
  addEventListener("resize",()=>{
    if(view==="songs")renderRows(); else if(view==="albums")placeExpand();
  });

  $("#play").onclick=async()=>{
    const btn=$("#play"), label=$("#playLabel");
    if(!rows.length)return;
    btn.disabled=true; label.textContent="Opening…";
    let msg="Play in VLC";
    try{
      const r=await fetch("play",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({name:sourceName(),
          indices:playable()})});
      if(!r.ok)msg=(await r.json()).error||"Failed";
    }catch(e){ msg="Server not running"; }
    label.textContent=msg==="Play in VLC"?"Playing…":msg;
    setTimeout(()=>{label.textContent="Play in VLC";btn.disabled=false;},VLC_NOTICE_MS);
  };

  // right-click the headers for the column picker, as iTunes did
  $("#thead").oncontextmenu=e=>{e.preventDefault();openPanel($("#vo"),e.clientX,e.clientY);};
  $("#gear").onclick=e=>{
    e.stopPropagation();
    const r=$("#gear").getBoundingClientRect();
    $("#prefs").classList.add("open");
    openPanel($("#prefs"),r.right-200,r.top-$("#prefs").offsetHeight-8);
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
    if(e.target.closest(".panel,#thead,#gear,#upnextBtn"))return;
    closePanels();
  });
}

DATA=LIBRARY;boot();
