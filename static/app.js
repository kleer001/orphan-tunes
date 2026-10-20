const $=s=>document.querySelector(s);
// cur is a playlist index, or LIB or BOOKS for a section of the library
const LIB=-1, BOOKS=-2;
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
let T=-1,S=-1,GENRE=-1,TRACKNO=-1,RATING=-1,PLAYS=-1,PLAYED=-1;
// Served by serve.py the page records plays, ratings and smart playlists in its
// state file. Opened from disk it shows the library as built and records nothing.
const SERVED=location.protocol!=="file:";
let STATE={tracks:{},playlists:{}};
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
// Five slots, so a click lands on a star. The empty ones show only on the
// hovered or selected row.
const rateHtml=v=>{
  const n=Math.round(v/PER_STAR), on=Number.isInteger(v)?"★":"☆";
  return `<span class="star rate">`+[1,2,3,4,5].map(r=>
    `<i data-r="${r}"${r>n?' class="off"':""}>${r>n?"·":on}</i>`).join("")+`</span>`;
};
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
    case "date":return v.slice(0,10);     // the time of day is kept for sorting only
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

// The library's sections, each a fixed source above the playlists.
const SECTION={[LIB]:["Library","music"],[BOOKS]:["Audiobooks","audiobooks"]};
const sourceIds=()=>cur<0?DATA[SECTION[cur][1]]:idsOf(DATA.playlists[cur]);
const sourceName=()=>cur<0?SECTION[cur][0]:DATA.playlists[cur].name;
const albumOf=i=>DATA.albums[ALBUM_OF[i]];
const colOf=label=>FIELDS.findIndex(f=>f[0]===label);

/* A playlist is one of three kinds. A plain one has `ids`. One of iTunes' smart
   playlists has `ids` as iTunes saved them, and `smart` with its rules; it is
   never edited, only copied. One made here has `user` (its id in the state
   file) and `rules`, and its ids come from running the rules. */
const GEAR_ICON='<svg width="10" height="10" viewBox="0 0 16 16" fill="#7a5aa5"><path d="M8 5.2A2.8'+
  ' 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2zM14 8.9v-1.8l-1.6-.3a4.6 4.6 0 0 0-.5-1.2l.9-1.3-1.3-1.3'+
  '-1.3.9a4.6 4.6 0 0 0-1.2-.5L8.9 2H7.1l-.3 1.6a4.6 4.6 0 0 0-1.2.5l-1.3-.9-1.3 1.3.9 1.3a4.6 4.6'+
  ' 0 0 0-.5 1.2L2 7.1v1.8l1.6.3c.1.4.3.8.5 1.2l-.9 1.3 1.3 1.3 1.3-.9c.4.2.8.4 1.2.5l.3 1.6h1.8l.3'+
  '-1.6c.4-.1.8-.3 1.2-.5l1.3.9 1.3-1.3-.9-1.3c.2-.4.4-.8.5-1.2L14 8.9z"/></svg>';
const rulesOf=p=>p.user?p.rules:p.smart?.rules;
// Bumped whenever a play, a rating or an edit can change what a rule picks.
let ver=0, ALL=[];
function idsOf(p){
  if(p.user&&p.ver!==ver){
    p.ids=Smart.evaluate(p.rules,DATA.tracks,FIELDS,ALL,{seed:p.seed}); p.ver=ver;
  }
  return p.ids;
}

function drawSources(){
  $("#srclist").innerHTML=
    [LIB,BOOKS].filter(i=>DATA[SECTION[i][1]].length).map(i=>
      `<div class="src lib${cur===i?" on":""}" data-i="${i}">${NOTE}<span>${SECTION[i][0]}</span></div>`
    ).join("")+
    DATA.playlists.map((p,i)=>`<div class="src${i===cur?" on":""}" data-i="${i}">`+
      `${p.smart||p.user?GEAR_ICON:NOTE}<span>${esc(p.name)}</span></div>`).join("");
}

function selectSource(i){
  cur=i; sel=-1; $("#search").value="";
  browse={genre:null,artist:null,album:null}; openAlbum=-1;
  drawSources(); draw();
  for(const id of ["#scroll","#grid","#alist","#adetail"])$(id).scrollTop=0;
}

// The same order the build gives the playlists, kept on the one being shown.
function sortLists(){
  const shown=DATA.playlists[cur];
  const key=p=>p.name.toLowerCase();
  DATA.playlists.sort((a,b)=>key(a)<key(b)?-1:key(a)>key(b)?1:0);
  if(shown)cur=DATA.playlists.indexOf(shown);
}

function addUser(id,pl){
  const p={name:pl.name,rules:pl.rules,user:id,ids:[],ver:-1,
    seed:Math.floor(Math.random()*2**31)};      // "random" holds still until reloaded
  DATA.playlists.push(p);
  return p;
}

/* ---- The rules, in words ------------------------------------------------------ */

const HINT={star:"stars",size:"MB",time:"seconds",kbps:"kbps",khz:"Hz"};
function ruleText(x){
  const kind=FIELDS[colOf(x.field)][1], fam=Smart.family(kind), v=x.value;
  const val=x.op==="in range"?`${v[0]} to ${v[1]}`:typeof v==="object"?`${v.n} ${v.unit}`
    :fam==="text"?`"${v}"`:fam==="number"&&HINT[kind]?`${v} ${HINT[kind]}`:String(v);
  return `${x.field} ${x.op} ${val}`;
}

function describe(r){
  let s=r.rules.length?r.rules.map(ruleText).join(r.match==="all"?" and ":" or "):"Every track";
  if(r.limit)s+=`, limited to ${r.limit.count} ${r.limit.unit} by ${r.limit.by}`;
  if(r.checkedOnly)s+=", checked songs only";
  return s;
}

function paintRules(){
  const p=cur<0?null:DATA.playlists[cur], bar=$("#rulebar");
  bar.classList.toggle("on",!!(p&&(p.smart||p.user)));
  if(!p||!(p.smart||p.user))return;
  const rules=rulesOf(p);
  const text=p.user?describe(rules)
    :`As iTunes saved it on ${DATA.exported.slice(0,10)}. `
      +(rules?describe(rules):p.smart.text.replace(/\s+/g," "));
  const act=!SERVED?"":p.user?'<button data-act="edit">Edit…</button>'
    :rules?'<button data-act="dup">Duplicate…</button>':"";
  bar.innerHTML=`<span title="${esc(p.smart?p.smart.text:text)}">${esc(text)}</span>${act}`;
}

/* ---- The rule editor ------------------------------------------------------------- */

// What is being edited: the user id (null for a new playlist), name and rules.
let draft=null;
const opt=(values,on)=>values.map(v=>
  `<option value="${esc(String(v))}"${String(v)===String(on)?" selected":""}>${esc(String(v))}</option>`)
  .join("");
const familyOf=label=>Smart.family(FIELDS[colOf(label)][1]);
const shapeOf=op=>op==="in range"?"pair":op.endsWith("in the last")?"span":"one";

function defaultValue(x){
  const fam=familyOf(x.field), shape=shapeOf(x.op);
  if(shape==="pair")return [0,0];
  if(shape==="span")return {n:1,unit:"months"};
  if(fam==="date")return new Date().toISOString().slice(0,10);
  return fam==="number"?0:fam==="bool"?true:"";
}

function valueHtml(x,kind){
  const fam=Smart.family(kind), v=x.value, num=(k,n)=>`<input type="number" data-k="${k}" value="${n}">`;
  if(shapeOf(x.op)==="pair")return num("v0",v[0])+" to "+num("v1",v[1]);
  if(shapeOf(x.op)==="span")return num("n",v.n)+`<select data-k="span">${opt(Object.keys(Smart.SPAN),v.unit)}</select>`;
  if(fam==="date")return `<input type="date" data-k="v" value="${esc(v)}">`;
  if(fam==="bool")return `<select data-k="v">${opt([true,false],v)}</select>`;
  if(fam==="number")return num("v",v)+`<span class="hint">${HINT[kind]||""}</span>`;
  return `<input data-k="v" value="${esc(v)}">`;
}

function drawEditor(){
  const r=draft.rules, lim=r.limit;
  const fields=FIELDS.slice(0,FOUND).map(f=>f[0]);
  $("#smartEd").innerHTML=`<h4>${draft.id?"Edit":"New"} Smart Playlist</h4><div class="ed">`+
    `<div class="edline">Name <input class="edname" data-k="name" value="${esc(draft.name)}"></div>`+
    `<div class="edline">Match <select data-k="match">${opt(["all","any"],r.match)}</select>`+
    ` of these rules:</div>`+
    r.rules.map((x,n)=>{
      const kind=FIELDS[colOf(x.field)][1];
      return `<div class="edline edrule" data-n="${n}">`+
        `<select data-k="field">${opt(fields,x.field)}</select>`+
        `<select data-k="op">${opt(Smart.OPS[Smart.family(kind)],x.op)}</select>`+
        valueHtml(x,kind)+`<button data-act="del" title="Remove this rule">−</button></div>`;
    }).join("")+
    `<div class="edline"><button data-act="add">+ Add Rule</button></div>`+
    `<div class="edline"><label><input type="checkbox" data-k="limit"${lim?" checked":""}>`+
    ` Limit to</label>`+(lim?`<input type="number" data-k="lcount" value="${lim.count}">`+
      `<select data-k="lunit">${opt(Smart.UNITS,lim.unit)}</select> selected by `+
      `<select data-k="lby">${opt(Smart.BY,lim.by)}</select>`:"")+`</div>`+
    `<div class="edline"><label><input type="checkbox" data-k="checked"`+
    `${r.checkedOnly?" checked":""}> Match only checked songs</label></div>`+
    `<div class="edbtns"><span class="ederr" id="edErr"></span>`+
    `<button data-act="cancel">Cancel</button><button data-act="ok">OK</button></div></div>`;
}

function openEditor(id,name,rules){
  draft={id,name,rules:structuredClone(rules)};
  drawEditor();
  const p=$("#smartEd");
  p.classList.add("open");                 // measured open, so its size is known
  openPanel(p,(innerWidth-p.offsetWidth)/2,(innerHeight-p.offsetHeight)/3);
  p.querySelector(".edname").focus();
}

function onEdit(e){
  const el=e.target, k=el.dataset.k;
  if(!k||!draft)return;
  const r=draft.rules, row=el.closest(".edrule"), x=row?r.rules[+row.dataset.n]:null;
  const val=el.type==="checkbox"?el.checked:el.value;
  switch(k){
    case "name":draft.name=val; return;
    case "match":r.match=val; return;
    case "field":
      x.field=val; x.op=Smart.OPS[familyOf(val)][0]; x.value=defaultValue(x); break;
    case "op":{
      const before=shapeOf(x.op);
      x.op=val;
      if(shapeOf(val)!==before)x.value=defaultValue(x);
      break;
    }
    case "v":
      x.value=familyOf(x.field)==="number"?Number(val):familyOf(x.field)==="bool"?val==="true":val;
      return;
    case "v0":x.value[0]=Number(val); return;
    case "v1":x.value[1]=Number(val); return;
    case "n":x.value.n=Number(val); return;
    case "span":x.value.unit=val; return;
    case "limit":r.limit=val?{count:25,unit:"items",by:"random"}:null; break;
    case "lcount":r.limit.count=Number(val); return;
    case "lunit":r.limit.unit=val; return;
    case "lby":r.limit.by=val; return;
    case "checked":r.checkedOnly=val; return;
  }
  drawEditor();          // only a change of shape redraws, so typing keeps its focus
}

// What is wrong with the draft, or "" when it can be saved.
function problem(){
  if(!draft.name.trim())return "Give the playlist a name.";
  const whole=n=>Number.isInteger(n)&&n>0;
  for(const x of draft.rules.rules){
    const v=x.value, shape=shapeOf(x.op), fam=familyOf(x.field);
    if(shape==="pair"&&!(isFinite(v[0])&&isFinite(v[1])))return `${x.field}: give both ends.`;
    if(shape==="span"&&!whole(v.n))return `${x.field}: give a whole number.`;
    if(shape==="one"&&fam==="number"&&!isFinite(v))return `${x.field}: give a number.`;
    if(shape==="one"&&fam==="date"&&!/^\d{4}-\d\d-\d\d$/.test(v))return `${x.field}: give a date.`;
  }
  if(draft.rules.limit&&!whole(draft.rules.limit.count))return "Give the limit as a whole number.";
  return "";
}

function saveDraft(){
  const why=problem();
  if(why){$("#edErr").textContent=why; return;}
  const id=draft.id||Date.now().toString(36);
  const pl={name:draft.name.trim(),rules:draft.rules};
  STATE.playlists[id]=pl;
  send({type:"save",id,playlist:pl});
  let p=DATA.playlists.find(q=>q.user===id);
  if(p){p.name=pl.name; p.rules=pl.rules;}
  else p=addUser(id,pl);
  draft=null; closePanels();
  sortLists(); ver++; lcdFor=null; selectSource(DATA.playlists.indexOf(p));
}

function duplicate(p){
  openEditor(null,p.name+" (copy)",rulesOf(p));
}

function removeList(p){
  if(!confirm(`Delete the smart playlist "${p.name}"?`))return;
  delete STATE.playlists[p.user];
  send({type:"delete",id:p.user});
  const shown=DATA.playlists[cur];
  DATA.playlists.splice(DATA.playlists.indexOf(p),1);
  selectSource(shown===p?LIB:DATA.playlists.indexOf(shown));
}

const NEW_RULES={match:"all",rules:[{field:"Artist",op:"contains",value:""}],
  limit:null,checkedOnly:false};

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
  paintLcd(); paintRules();
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
    vis.map((f,n)=>`<div class="${colCls[n]}">`+
      `${f===RATING&&SERVED?rateHtml(t[f]):fmt(t[f],FIELDS[f][1],gone)}</div>`).join("")+
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
  markPlaying(); paintLcd(); setSession(); setMarquee();
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
  nowIdx=-1; qpos=-1; fromUpNext=false; paint(); markPlaying(); paintLcd(); setMarquee();
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

// The tab title scrolls the playing track's name and artist while it plays.
// A tab that plays audio counts as in the foreground, so the browser does not
// slow this timer (MDN, Page Visibility API).
const PAGE_TITLE=document.title, MARQUEE_MS=300;
let marquee=[], marqueeTimer=0;    // by character, so an emoji stays whole
function setMarquee(){
  // No-break spaces: a title collapses ordinary ones, so the gap would jump.
  const nb=s=>s.replace(/ /g,"\u00a0");
  marquee=nowIdx>=0?[...nb(label(DATA.tracks[nowIdx])+"   ·   ")]:[];
  document.title=marquee.join("")||PAGE_TITLE;
}
function scrollTitle(on){
  clearInterval(marqueeTimer);
  if(on)marqueeTimer=setInterval(()=>{
    marquee.push(marquee.shift()); document.title=marquee.join("");
  },MARQUEE_MS);
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
    scrollTitle(on);
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

/* ---- Plays and ratings ------------------------------------------------------ */

function send(change){
  fetch("state",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(change)})
    .then(r=>{if(!r.ok)lcd("Could not save to the state file");})
    .catch(()=>lcd("Server not running: nothing saved"));
}

// The state file holds absolute values, keyed by Persistent ID, so they land on
// the right row whatever order a rebuild put the pool in.
function applyState(){
  const row=new Map(DATA.pids.map((p,i)=>[p,i]));
  for(const [pid,v] of Object.entries(STATE.tracks)){
    const t=DATA.tracks[row.get(pid)];
    if(!t)continue;                       // gone from the library since
    if("plays" in v){t[PLAYS]=v.plays; t[PLAYED]=v.played;}
    if("rating" in v)t[RATING]=v.rating;
  }
}

async function loadState(){
  if(!SERVED)return;
  try{const r=await fetch("state"); if(r.ok)STATE=await r.json();}catch(e){}
}

// iTunes counted a play when a track reached its end, not when it started.
function recordPlay(i){
  if(!SERVED||i<0)return;
  const t=DATA.tracks[i];
  t[PLAYS]+=1; t[PLAYED]=new Date().toISOString().slice(0,19).replace("T"," ");
  send({type:"play",pid:DATA.pids[i],plays:t[PLAYS],played:t[PLAYED]});
  changed();
}

// A rating set here is the track's own, so a hollow (album-derived) one turns
// solid. Clicking the star already set clears it.
function rate(i,n){
  if(!SERVED)return;
  const t=DATA.tracks[i], v=n*PER_STAR===t[RATING]?0:n*PER_STAR;
  t[RATING]=v;
  send({type:"rate",pid:DATA.pids[i],rating:v});
  changed();
}

function changed(){ ver++; lcdFor=null; draw(); }

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
    '<div class="mi" data-m="add">Add to Up Next</div>'+
    (SERVED&&ids.length===1?`<div class="mi rateline">Rating ${rateHtml(DATA.tracks[ids[0]][RATING])}</div>`:"");
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
  PLAYS=FIELDS.findIndex(f=>f[0]==="Plays"); PLAYED=FIELDS.findIndex(f=>f[0]==="Last Played");
  applyState();
  ALL=DATA.tracks.map((_,i)=>i);
  for(const [id,pl] of Object.entries(STATE.playlists))addUser(id,pl);
  sortLists();
  $("#newSmart").hidden=!SERVED;
  ALBUM_OF=new Int32Array(DATA.tracks.length);
  DATA.albums.forEach((al,a)=>{
    for(const i of al[A_IDS])ALBUM_OF[i]=a;
    if(!ARTIST_RANK.has(al[A_ARTIST]))ARTIST_RANK.set(al[A_ARTIST],a);
  });
  applySkin(skinName()); buildPrefs(); loadModes(); paintModes(); loadView(); paintView();
  drawSources();buildOptions();paintUpNext();draw();paint();

  $("#srclist").onclick=e=>{const el=e.target.closest(".src");if(el)selectSource(+el.dataset.i);};
  $("#srclist").oncontextmenu=e=>{
    e.preventDefault();
    if(!SERVED)return;
    const el=e.target.closest(".src"), i=el?+el.dataset.i:LIB;
    const p=i<0?null:DATA.playlists[i];
    menu={ids:[],first:undefined,list:[],src:p};
    $("#ctx").innerHTML='<div class="mi" data-m="new">New Smart Playlist…</div>'+
      (p?.smart?.rules?'<div class="mi" data-m="dup">Duplicate as Smart Playlist…</div>':"")+
      (p?.user?'<div class="mi" data-m="edit">Edit Smart Playlist…</div>'+
        '<div class="mi" data-m="dup">Duplicate…</div><div class="mi" data-m="del">Delete</div>':"");
    openPanel($("#ctx"),e.clientX,e.clientY);
  };
  $("#newSmart").onclick=()=>openEditor(null,"untitled playlist",NEW_RULES);
  $("#rulebar").onclick=e=>{const b=e.target.closest("button");if(!b)return;
    const p=DATA.playlists[cur];
    if(b.dataset.act==="edit")openEditor(p.user,p.name,p.rules); else duplicate(p);};
  for(const ev of ["input","change"])$("#smartEd").addEventListener(ev,onEdit);
  $("#smartEd").onclick=e=>{const b=e.target.closest("button[data-act]");if(!b)return;
    const r=draft.rules, act=b.dataset.act;
    if(act==="ok")return saveDraft();
    if(act==="cancel"){draft=null; closePanels(); return;}
    if(act==="add")r.rules.push({field:"Artist",op:"contains",value:""});
    if(act==="del")r.rules.splice(+b.closest(".edrule").dataset.n,1);
    drawEditor();};
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
  $("#rows").onclick=e=>{const el=e.target.closest(".row");if(!el)return;
    setSel(+el.dataset.i);
    const star=e.target.closest("[data-r]");
    if(star)rate(rows[+el.dataset.i],+star.dataset.r);};
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
    const star=e.target.closest("[data-r]");
    if(m.classList.contains("rateline")){
      if(star){closePanels(); rate(menu.ids[0],+star.dataset.r);}
      return;
    }
    closePanels();
    const src=menu.src, act=m.dataset.m;
    if(act==="new")openEditor(null,"untitled playlist",NEW_RULES);
    else if(act==="dup")duplicate(src);
    else if(act==="edit")openEditor(src.user,src.name,src.rules);
    else if(act==="del")removeList(src);
    else if(act==="play")play(menu.first,menu.list);
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
  audio.addEventListener("ended",()=>{recordPlay(nowIdx); step(1);});
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
    if($("#smartEd").classList.contains("open"))return;   // only Cancel or Esc lose a draft
    closePanels();
  });
}

DATA=LIBRARY;loadState().then(boot);
