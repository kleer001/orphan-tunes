#!/usr/bin/env python3
"""
Build a local browser for the exported playlists, in the iTunes 4 idiom.

    python build_browser.py [output_dir]

Emits data.json (a shared track pool plus one index list per playlist) and
index.html. Reads only. Serve the output directory over localhost.
"""

import json
import os
import plistlib
import sys
from collections import defaultdict

from config import BROWSER_DIR, LIBRARY, LOCAL_ROOT
from make_playlists import locate  # the .m3u8 writer's own file lookup

# Every field worth showing, in iTunes' own column order. "plumbing" fields
# (Track ID, Location, Persistent ID, the Sort* sort keys, the *Computed flags)
# are the only ones left behind. type drives both formatting and alignment;
# `show` is the default column set, the rest are available from View Options.
FIELDS = [
    ("Name",           "Song Name",   "text", True),
    ("Total Time",     "Time",        "time", True),
    ("Artist",         "Artist",      "text", True),
    ("Album",          "Album",       "text", True),
    ("Genre",          "Genre",       "text", True),
    ("Year",           "Year",        "int",  True),
    ("Size",           "Size",        "size", True),
    ("Play Count",     "Plays",       "int",  True),
    ("Album Artist",   "Album Artist", "text", False),
    ("Composer",       "Composer",    "text", False),
    ("Grouping",       "Grouping",    "text", False),
    ("Work",           "Work",        "text", False),
    ("Kind",           "Kind",        "text", False),
    ("Track Number",   "#",           "int",  False),
    ("Track Count",    "of",          "int",  False),
    ("Disc Number",    "Disc",        "int",  False),
    ("Disc Count",     "Discs",       "int",  False),
    ("Rating",         "Rating",      "star", False),
    ("Album Rating",   "Album Rating", "star", False),
    ("BPM",            "BPM",         "int",  False),
    ("Bit Rate",       "Bit Rate",    "kbps", False),
    ("Sample Rate",    "Sample Rate", "khz",  False),
    ("Comments",       "Comments",    "text", False),
    ("Compilation",    "Compilation", "bool", False),
    ("Date Added",     "Date Added",  "date", False),
    ("Date Modified",  "Date Modified", "date", False),
    ("Play Date UTC",  "Last Played", "date", False),
    ("Skip Count",     "Skips",       "int",  False),
    ("Skip Date",      "Last Skipped", "date", False),
]

AUDIO = {".mp3", ".m4a", ".wav", ".mp4", ".aif", ".aiff",
         ".mpga", ".m4b", ".flac", ".ogg", ".mov", ".m4v"}


def index_by_name(root):
    index = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in AUDIO:
                index[name.lower()].append(os.path.join(dirpath, name))
    return index


def build_data(out_dir):
    with open(LIBRARY, "rb") as fh:
        lib = plistlib.load(fh)
    tracks = lib["Tracks"]
    index = index_by_name(LOCAL_ROOT)

    pool, paths, seen = [], [], {}
    playlists, missing = [], 0

    def cell(track, key, kind):
        v = track.get(key)
        if v is None:
            return "" if kind in ("text", "date") else 0
        if kind == "time":
            return round(v / 1000)
        if kind == "date":
            return v.strftime("%Y-%m-%d")      # plist datetime -> sortable string
        if kind == "bool":
            return 1 if v else 0
        return v

    def track_index(track, path, how):
        """Intern a track into the shared pool; playlists store only offsets."""
        key = track["Track ID"]
        if key not in seen:
            seen[key] = len(pool)
            pool.append([cell(track, k, kind) for k, _, kind, _ in FIELDS] + [how])
            paths.append(path)          # None when the file could not be found
        return seen[key]

    for playlist in lib["Playlists"]:
        if "Smart Info" in playlist or playlist.get("Master") \
                or playlist.get("Distinguished Kind") or not playlist.get("Playlist Items"):
            continue
        ids = []
        for item in playlist["Playlist Items"]:
            track = tracks.get(str(item["Track ID"]))
            if not track or not track.get("Location"):
                continue
            path, how = locate(track, index)
            if not path:
                missing += 1
            ids.append(track_index(track, path, how))
        if ids:
            playlists.append({"name": playlist["Name"], "ids": ids})

    playlists.sort(key=lambda p: p["name"].lower())

    fields = [[label, kind, show] for _, label, kind, show in FIELDS]
    fields.append(["Found", "found", False])   # derived, not from the library
    data = {"fields": fields, "tracks": pool, "playlists": playlists}
    path = os.path.join(out_dir, "data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    # Index-aligned with the track pool. Read by the server, never by the page,
    # so the browser can only ever ask for a row number, not a filesystem path.
    with open(os.path.join(out_dir, "paths.json"), "w", encoding="utf-8") as fh:
        json.dump(paths, fh, ensure_ascii=False, separators=(",", ":"))

    refs = sum(len(p["ids"]) for p in playlists)
    print(f"  {len(playlists)} playlists, {refs} track refs, "
          f"{len(pool)} unique tracks, {missing} shown as missing")
    print(f"  data.json {os.path.getsize(path) / 1e6:.1f} MB")
    return len(playlists), refs


CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:#6b6b6b;font:11px/1.35 "Lucida Grande","Segoe UI",Helvetica,Arial,sans-serif;
     color:#000;display:flex;align-items:center;justify-content:center;padding:14px;
     -webkit-font-smoothing:antialiased}

/* brushed metal: fine horizontal grain over a soft vertical gradient */
.metal{background-image:repeating-linear-gradient(0deg,
         rgba(255,255,255,.55) 0 1px, rgba(0,0,0,.035) 1px 2px),
       linear-gradient(#e8e8e8,#d0d0d0)}

.win{width:100%;max-width:1180px;height:100%;max-height:820px;display:flex;flex-direction:column;
     border:1px solid #6f6f6f;border-radius:7px;overflow:hidden;
     box-shadow:0 12px 34px rgba(0,0,0,.45)}

.title{height:22px;flex:none;display:flex;align-items:center;justify-content:center;
       border-bottom:1px solid #a4a4a4;font-weight:600;color:#3a3a3a;
       font-size:12px;position:relative}
.lights{position:absolute;left:8px;display:flex;gap:6px}
.lights i{width:11px;height:11px;border-radius:50%;display:block;border:1px solid rgba(0,0,0,.35)}
.lights i:nth-child(1){background:radial-gradient(circle at 35% 30%,#ff9a90,#e04f43)}
.lights i:nth-child(2){background:radial-gradient(circle at 35% 30%,#ffd479,#e0a234)}
.lights i:nth-child(3){background:radial-gradient(circle at 35% 30%,#a8e57f,#4fa42f)}

/* transport, restored from the original now that it drives real playback */
.transport{flex:none;display:flex;align-items:center;gap:7px}
.tbtn{width:29px;height:29px;border-radius:50%;border:1px solid #8d8d8d;cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0;
  background:linear-gradient(#fdfdfd,#d7d7d7);
  box-shadow:inset 0 1px 0 #fff,0 1px 2px rgba(0,0,0,.28)}
.tbtn.big{width:39px;height:39px}
.tbtn:hover{background:linear-gradient(#fff,#e4e4e4)}
.tbtn:active{background:linear-gradient(#c4c4c4,#e8e8e8);box-shadow:inset 0 2px 4px rgba(0,0,0,.3)}
.tbtn:disabled{opacity:.4;cursor:default}
.tbtn svg{fill:#3c3c3c;pointer-events:none}
.vol{width:74px;margin-left:4px;accent-color:#5a5a5a}

/* progress, inside the LCD as it was */
.bar{width:88%;height:7px;border-radius:4px;background:#b9bfae;cursor:pointer;
  border:1px solid #949a8a;box-shadow:inset 0 1px 2px rgba(0,0,0,.25);position:relative}
.bar span{display:block;height:100%;border-radius:3px 0 0 3px;
  background:linear-gradient(#8f9c82,#6f7c63)}
.times{display:flex;justify-content:space-between;width:88%;font-size:9.5px;
  color:#4a5044;font-variant-numeric:tabular-nums}
.row.playing{font-weight:600}
.row.playing .c-name::before{content:"\25B6";font-size:8px;margin-right:5px;color:#3a6ea5}

/* the fallback: hands the whole view to VLC instead */
.playbtn{flex:none;display:flex;align-items:center;gap:8px;height:30px;
  padding:0 14px 0 11px;border-radius:15px;cursor:pointer;font-size:11px;
  border:1px solid #2f2f2f;color:#f4f4f4;font:600 12px "Lucida Grande",sans-serif;
  background:linear-gradient(#6f6f6f 0%,#575757 48%,#454545 52%,#3a3a3a 100%);
  text-shadow:0 -1px 0 rgba(0,0,0,.55);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.28),0 1px 3px rgba(0,0,0,.4)}
.playbtn:hover{background:linear-gradient(#7d7d7d 0%,#636363 48%,#505050 52%,#454545 100%)}
.playbtn:active{background:linear-gradient(#3a3a3a,#565656);
  box-shadow:inset 0 2px 6px rgba(0,0,0,.5)}
.playbtn:disabled{opacity:.45;cursor:default}
.playbtn svg{flex:none;filter:drop-shadow(0 -1px 0 rgba(0,0,0,.5))}

/* the LCD is a readout, not a transport */
.top{flex:none;display:flex;align-items:center;gap:14px;padding:9px 12px;
     border-bottom:1px solid #a4a4a4}
.lcd{flex:1;height:66px;border-radius:9px;background:linear-gradient(#d7dbcd,#c9cebe);
     border:1px solid #8e9384;box-shadow:inset 0 1px 3px rgba(0,0,0,.3);
     display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
     text-shadow:0 1px 0 rgba(255,255,255,.4);overflow:hidden;padding:0 12px}
#lcdName{font-weight:600;font-size:12px;color:#20241c;white-space:nowrap;overflow:hidden;
         text-overflow:ellipsis;max-width:100%}
#lcdSub{font-size:10px;color:#4a5044;font-variant-numeric:tabular-nums}
.searchwrap{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:5px}
#search{width:190px;height:20px;border-radius:10px;border:1px solid #8f8f8f;padding:0 22px 0 22px;
        font:11px "Lucida Grande",sans-serif;background:#fff url("data:image/svg+xml;charset=utf8,\
%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cg fill='none' stroke='%23888' \
stroke-width='1.6'%3E%3Ccircle cx='7' cy='7' r='4'/%3E\
%3Cpath d='M10 10l3.5 3.5'/%3E%3C/g%3E%3C/svg%3E") \
6px 50%/11px no-repeat;box-shadow:inset 0 1px 2px rgba(0,0,0,.18)}
#search:focus{outline:2px solid #7ba7e0;outline-offset:-1px}
#count{font-size:10px;color:#4a4a4a;font-variant-numeric:tabular-nums}

.body{flex:1;display:flex;min-height:0;border-top:1px solid #fff}

/* source list */
.source{width:172px;flex:none;background:#fff;border-right:1px solid #9a9a9a;
        display:flex;flex-direction:column;min-height:0}
.srchead{flex:none;height:18px;display:flex;align-items:center;justify-content:center;
         font-size:10px;color:#555;border-bottom:1px solid #b4b4b4;
         background:linear-gradient(#ededed,#dcdcdc)}
.srclist{flex:1;overflow-y:auto;padding:3px 0}
.src{display:flex;align-items:center;gap:5px;padding:2px 8px;cursor:default;
     white-space:nowrap;overflow:hidden}
.src span{overflow:hidden;text-overflow:ellipsis}
.src svg{flex:none}
.src.on{background:#3a6ea5;color:#fff}
.src.on svg{fill:#fff}

/* track table */
.tracks{flex:1;display:flex;flex-direction:column;min-height:0;min-width:0;
        background:#fff}
.thead{position:sticky;top:0;z-index:2;display:flex;width:max-content;min-width:100%;
       background:linear-gradient(#f0f0f0,#dadada);
       border-bottom:1px solid #9a9a9a;font-size:10px;color:#333}
.thead div{padding:3px 6px;border-right:1px solid #c4c4c4;cursor:default;
           white-space:nowrap;overflow:hidden;position:relative;user-select:none}
.thead div:hover{background:rgba(0,0,0,.05)}
.thead div.sorted{background:linear-gradient(#dfe7f2,#c9d6e8)}
.thead div.sorted::after{content:"";position:absolute;right:4px;top:50%;margin-top:-2px;
  border-left:3.5px solid transparent;border-right:3.5px solid transparent;
  border-top:4px solid #4a4a4a}
.thead div.sorted.asc::after{border-top:none;border-bottom:4px solid #4a4a4a}
.scroll{flex:1;overflow:auto}
.row{display:flex;height:17px;align-items:center;width:max-content;min-width:100%}
.row:nth-child(even){background:#edf3fb}
.row.sel{background:#b6c8de}
.row.ghost{color:#a0a0a0;font-style:italic}
.row.ghost.sel{color:#5a5a5a}
.found-gone,.found-ambiguous{color:#b23b3b;font-style:normal}
.found-moved,.found-by-size{color:#8a6d1f;font-style:normal}
.row div{padding:0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;font-variant-numeric:tabular-nums}

.col-text{width:148px;flex:none}
.col-time,.col-int,.col-kbps{width:56px;flex:none}
.col-size,.col-khz{width:76px;flex:none}
.col-date{width:88px;flex:none}
.col-star{width:64px;flex:none}
.col-bool{width:54px;flex:none}
.grow{flex:1 1 auto;width:300px;min-width:90px}
.last{padding-right:10px}
.star{color:#5a5a5a;letter-spacing:1px}

/* View Options, reached by right-clicking the column headers */
.vo{position:fixed;z-index:20;background:#f2f2f2;border:1px solid #7a7a7a;border-radius:5px;
    box-shadow:0 6px 20px rgba(0,0,0,.35);padding:6px 0;max-height:70vh;overflow-y:auto;
    min-width:186px;display:none}
.vo.open{display:block}
.vo h4{font-size:10px;color:#666;font-weight:400;padding:2px 12px 5px;
       border-bottom:1px solid #d6d6d6;margin-bottom:4px}
.vo label{display:flex;align-items:center;gap:7px;padding:2px 12px;cursor:default}
.vo label:hover{background:#3a6ea5;color:#fff}
.vo input{margin:0}

.empty{padding:26px;color:#888;text-align:center}
.status{flex:none;height:22px;display:flex;align-items:center;justify-content:center;
        border-top:1px solid #fff;font-size:10px;color:#3a3a3a;
        text-shadow:0 1px 0 rgba(255,255,255,.5)}
::-webkit-scrollbar{width:13px}
::-webkit-scrollbar-track{background:#f0f0f0;border-left:1px solid #c4c4c4}
::-webkit-scrollbar-thumb{background:linear-gradient(90deg,#c8d4e4,#9db2cc);
  border:1px solid #7f92aa;border-radius:6px}
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
           "%3Cpath fill='%233a6ea5' d='M5 1v9.2A2.6 2.6 0 1 0 6.6 12.6V4.6H12V1z'/%3E%3C/svg%3E")

NOTE_SVG = ("<svg width='9' height='11' viewBox='0 0 9 11' fill='%233a6ea5'>"
            "<path d='M3 0v7.1A2 2 0 1 0 4 9V3h4V0z'/></svg>")

JS = r"""
const $=s=>document.querySelector(s);
let DATA=null,FIELDS=[],FOUND=-1,vis=[],cur=0,sortCol=-1,asc=true,rows=[],sel=-1;
// what is playing, as a pool index, plus the queue it came from
let nowIdx=-1,queue=[],qpos=-1;
const KEY="playlists.columns";

const mmss=s=>`${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
const songs=n=>`${n} ${n===1?"song":"songs"}`;
const mb=b=>b>=1073741824?(b/1073741824).toFixed(2)+" GB":(b/1048576).toFixed(1)+" MB";

// iTunes stored ratings 0-100; five stars is 100.
const stars=v=>v?"\u2605".repeat(Math.round(v/20)):"";
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
  const total=DATA.playlists[cur].ids.length;
  $("#thead").innerHTML=vis.map((f,n)=>
    `<div class="${colClass(f,n)}${f===sortCol?" sorted"+(asc?" asc":""):""}" `+
    `data-c="${f}">${esc(FIELDS[f][0])}</div>`).join("");
  $("#rows").innerHTML=rows.length?rows.map((idx,i)=>{
    const t=DATA.tracks[idx], gone=missing(t);
    return `<div class="row${i===sel?" sel":""}${gone?" ghost":""}`+
      `${idx===nowIdx?" playing":""}" data-i="${i}">`+
      vis.map((f,n)=>
        `<div class="${colClass(f,n)}">${fmt(t[f],FIELDS[f][1],gone)}</div>`).join("")+
      `</div>`;}).join("")
    : `<div class="empty">Nothing matches.</div>`;

  const T=FIELDS.findIndex(f=>f[1]==="time"), S=FIELDS.findIndex(f=>f[1]==="size");
  const here=rows.filter(i=>!missing(DATA.tracks[i]));
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
  // the LCD covers the whole playlist, so it counts what is actually there
  const all=DATA.playlists[cur].ids, playable=all.filter(i=>!missing(DATA.tracks[i]));
  const absent=all.length-playable.length;
  $("#lcdSub").textContent=songs(playable.length)
    +` — ${span(playable.reduce((a,i)=>a+DATA.tracks[i][T],0))}`
    +(absent?`   \u00b7   ${absent} missing`:"");
}

function saveCols(){try{localStorage.setItem(KEY,JSON.stringify(vis));}catch(e){}}
function loadCols(){
  try{
    const v=JSON.parse(localStorage.getItem(KEY));
    if(Array.isArray(v)&&v.length&&v.every(i=>Number.isInteger(i)&&FIELDS[i]))return v;
  }catch(e){}
  return FIELDS.map((f,i)=>f[2]?i:-1).filter(i=>i>=0);
}

function buildOptions(){
  $("#vo").innerHTML="<h4>View Options</h4>"+FIELDS.map((f,i)=>
    `<label><input type="checkbox" data-f="${i}"${vis.includes(i)?" checked":""}`+
    `${i===0?" disabled":""}> ${esc(f[0])}</label>`).join("");
}

const audio=$("#audio");
const clock=s=>isFinite(s)?`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}`:"";

function label(t){
  const artist=t[2]||t[8];
  return artist?`${t[0]} — ${artist}`:t[0];
}

function play(poolIndex){
  const t=DATA.tracks[poolIndex];
  if(missing(t))return;
  nowIdx=poolIndex;
  queue=rows.filter(i=>!missing(DATA.tracks[i]));
  qpos=queue.indexOf(poolIndex);
  audio.src="audio?i="+poolIndex;
  audio.play().catch(()=>{ lcd(`Cannot play ${t[0]}`); });
  draw();
}

function step(by){
  if(!queue.length)return;
  const at=qpos+by;
  if(at<0||at>=queue.length){stop();return;}
  play(queue[at]);
}

function stop(){
  audio.pause(); audio.removeAttribute("src"); audio.load();
  nowIdx=-1; qpos=-1; paint(); draw();
}

function lcd(msg){ $("#lcdName").textContent=msg; }

function paint(){
  const on=nowIdx>=0&&!audio.paused;
  $("#toggleIcon").innerHTML=on
    ? '<path d="M2 1h3.5v12H2zM7.5 1H11v12H7.5z"/>'
    : '<path d="M2 1v12l9.5-6z"/>';
  $("#toggle").title=on?"Pause":"Play";
  const d=audio.duration||0, c=audio.currentTime||0;
  $("#barFill").style.width=d?`${100*c/d}%`:"0";
  $("#elapsed").textContent=nowIdx>=0?clock(c):"";
  $("#left").textContent=nowIdx>=0&&d?"-"+clock(d-c):"";
  $("#prev").disabled=$("#next").disabled=nowIdx<0;
}

function boot(){
  FIELDS=DATA.fields; FOUND=FIELDS.length-1; vis=loadCols();
  drawSources();buildOptions();draw();paint();

  $("#srclist").onclick=e=>{const el=e.target.closest(".src");if(!el)return;
    cur=+el.dataset.i;sel=-1;$("#search").value="";
    drawSources();draw();$("#scroll").scrollTop=0;};
  $("#thead").onclick=e=>{const el=e.target.closest("div[data-c]");if(!el)return;
    const c=+el.dataset.c; asc=(c===sortCol)?!asc:true; sortCol=c; sel=-1; draw();};
  $("#rows").onclick=e=>{const el=e.target.closest(".row");if(!el)return;
    sel=+el.dataset.i;draw();};
  $("#rows").ondblclick=e=>{const el=e.target.closest(".row");if(!el)return;
    play(rows[+el.dataset.i]);};

  $("#toggle").onclick=()=>{
    if(nowIdx<0){                       // nothing cued: start at the selection
      const start=sel>=0?rows[sel]:rows.find(i=>!missing(DATA.tracks[i]));
      if(start!==undefined)play(start);
      return;
    }
    audio.paused?audio.play():audio.pause();
  };
  $("#prev").onclick=()=>step(-1);
  $("#next").onclick=()=>step(1);
  $("#vol").oninput=e=>{audio.volume=+e.target.value;};

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
          indices:rows.filter(i=>!missing(DATA.tracks[i]))})});
      if(!r.ok)msg=(await r.json()).error||"Failed";
    }catch(e){ msg="Server not running"; }
    label.textContent=msg==="Play in VLC"?"Playing\u2026":msg;
    setTimeout(()=>{label.textContent="Play in VLC";btn.disabled=false;},1800);
  };

  // right-click the headers for the column picker, as iTunes did
  $("#thead").oncontextmenu=e=>{
    e.preventDefault();
    const vo=$("#vo");
    vo.style.left=Math.min(e.clientX,innerWidth-200)+"px";
    vo.style.top=Math.min(e.clientY,innerHeight-320)+"px";
    vo.classList.add("open");
  };
  $("#vo").onchange=e=>{
    const i=+e.target.dataset.f;
    vis = e.target.checked ? FIELDS.map((_,n)=>n).filter(n=>n===i||vis.includes(n))
                           : vis.filter(n=>n!==i);
    if(!vis.includes(sortCol))sortCol=-1;
    saveCols();draw();
  };
  document.addEventListener("mousedown",e=>{
    if(!e.target.closest("#vo")&&!e.target.closest("#thead"))$("#vo").classList.remove("open");
  });
}

fetch("data.json").then(r=>r.json()).then(d=>{DATA=d;boot();});
"""


def write_page(out_dir, n_playlists, n_refs):
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Playlists</title>
<link rel="icon" href="{FAVICON}"><style>{CSS}</style></head>
<body>
<div class="win metal">
  <div class="title metal"><div class="lights"><i></i><i></i><i></i></div>Playlists</div>
  <div class="top metal">
    <div class="transport">
      <button class="tbtn" id="prev" title="Previous">
        <svg width="11" height="11" viewBox="0 0 11 11">
          <path d="M2 1h1.6v9H2zM10 1v9L4 5.5z"/></svg>
      </button>
      <button class="tbtn big" id="toggle" title="Play">
        <svg id="toggleIcon" width="13" height="14" viewBox="0 0 13 14">
          <path d="M2 1v12l9.5-6z"/></svg>
      </button>
      <button class="tbtn" id="next" title="Next">
        <svg width="11" height="11" viewBox="0 0 11 11">
          <path d="M7.4 1H9v9H7.4zM1 1l6 4.5L1 10z"/></svg>
      </button>
      <input class="vol" id="vol" type="range" min="0" max="1" step="0.01" value="1"
             title="Volume">
    </div>
    <div class="lcd">
      <div id="lcdName">&nbsp;</div>
      <div id="lcdSub">&nbsp;</div>
      <div class="bar" id="bar"><span id="barFill" style="width:0"></span></div>
      <div class="times"><span id="elapsed"></span><span id="left"></span></div>
    </div>
    <div class="searchwrap">
      <button class="playbtn" id="play" title="Open this view in VLC instead">
        <svg width="11" height="12" viewBox="0 0 15 16" aria-hidden="true">
          <path d="M2 1.4v13.2L13.2 8z" fill="#fff"/></svg>
        <span id="playLabel">Play in VLC</span>
      </button>
      <input id="search" type="search" placeholder="Search" autocomplete="off">
      <div id="count"></div>
    </div>
  </div>
  <audio id="audio" preload="none"></audio>
  <div class="body">
    <div class="source">
      <div class="srchead">Source</div>
      <div class="srclist" id="srclist"></div>
    </div>
    <div class="tracks">
      <div class="scroll" id="scroll">
        <div class="thead" id="thead"></div>
        <div id="rows"></div>
      </div>
    </div>
  </div>
  <div class="status metal" id="status"></div>
</div>
<div class="vo" id="vo"></div>
<script>const NOTE="{NOTE_SVG}";</script>
<script>{JS}</script>
</body></html>"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"  index.html {os.path.getsize(path) / 1024:.0f} KB "
          f"({n_playlists} playlists, {n_refs} refs)")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else BROWSER_DIR
    os.makedirs(out_dir, exist_ok=True)
    print(f"building into {out_dir}")
    n_playlists, n_refs = build_data(out_dir)
    write_page(out_dir, n_playlists, n_refs)


if __name__ == "__main__":
    main()
