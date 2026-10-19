/* Smart playlist rules, run against the track pool. No page code here, so the
   tests can run the same file in Node.

   rules: {match:"all"|"any", rules:[{field,op,value}], limit, checkedOnly}
   limit: {count, unit:"items"|"minutes"|"hours"|"MB"|"GB", by} or null

   Values are in the units the rule editor shows: stars for a rating, MB for a
   size, seconds for a time, "YYYY-MM-DD" for a fixed date, {n,unit} for "in
   the last". Dates in the pool are UTC, "YYYY-MM-DD HH:MM:SS". */
const Smart=(()=>{
  const PER_STAR=20, MB=1024*1024, GB=1024*MB;
  // iTunes' own lengths for "in the last": a month is a twelfth of 365 days.
  const SPAN={days:86400,weeks:604800,months:2628000};
  // A rule value is in these units; the pool holds bytes and 0-100.
  const SCALE={size:MB,star:PER_STAR};

  const OPS={
    text:["is","is not","contains","does not contain","starts with","ends with"],
    number:["is","is not","greater than","less than","in range"],
    date:["is after","is before","in the last","not in the last"],
    bool:["is"],
  };
  const family=kind=>kind==="text"||kind==="date"||kind==="bool"?kind:"number";

  const BY=["random","name","album","artist","genre","highest rating","lowest rating",
    "most recently played","least recently played","most often played",
    "least often played","most recently added","least recently added"];
  const UNITS=["items","minutes","hours","MB","GB"];

  const stamp=s=>Date.parse(s.replace(" ","T")+"Z");
  // The rating a rule sees. A rating iTunes worked out from the album sits
  // half a point low. iTunes' rules count it only when the album rating was
  // set by hand, not itself worked out from the tracks.
  const rated=(v,album)=>Number.isInteger(v)?v:Number.isInteger(album)&&album?v+0.5:0;

  function test(rule,kind,v,now){
    const op=rule.op, want=rule.value;
    switch(family(kind)){
      case "text":{
        const s=String(v).toLowerCase(), w=String(want).toLowerCase();
        if(op==="is")return s===w;
        if(op==="is not")return s!==w;
        if(op==="contains")return s.includes(w);
        if(op==="does not contain")return !s.includes(w);
        if(op==="starts with")return s.startsWith(w);
        if(op==="ends with")return s.endsWith(w);
        break;
      }
      case "number":{
        const x=v/(SCALE[kind]||1);
        if(op==="is")return x===want;
        if(op==="is not")return x!==want;
        if(op==="greater than")return x>want;
        if(op==="less than")return x<want;
        if(op==="in range")return x>=want[0]&&x<=want[1];
        break;
      }
      case "date":{
        if(op==="in the last"||op==="not in the last"){
          const recent=v!==""&&stamp(v)>=now-want.n*SPAN[want.unit]*1000;
          return op==="in the last"?recent:!recent;   // never is not recent
        }
        if(v==="")return false;
        const day=v.slice(0,10);
        if(op==="is after")return day>want;
        if(op==="is before")return day<want;
        break;
      }
      case "bool":
        return (v===1)===want;
    }
    throw new Error(`no operator ${op} for ${rule.field}`);
  }

  // Small seeded generator, so "random" picks the same tracks each time a
  // playlist is drawn until it is asked to pick again.
  function mulberry32(seed){
    return ()=>{
      seed=seed+0x6D2B79F5|0;
      let t=Math.imul(seed^seed>>>15,1|seed);
      t=t+Math.imul(t^t>>>7,61|t)^t;
      return ((t^t>>>14)>>>0)/4294967296;
    };
  }

  function order(ids,by,tracks,col,value,seed){
    const out=ids.slice();
    if(by==="random"){
      const rnd=mulberry32(seed);
      for(let i=out.length-1;i>0;i--){
        const j=Math.floor(rnd()*(i+1)); [out[i],out[j]]=[out[j],out[i]];
      }
      return out;
    }
    const text=c=>(a,b)=>String(tracks[a][c]).localeCompare(String(tracks[b][c]),undefined,
      {sensitivity:"base",numeric:true});
    const num=(f,sign)=>(a,b)=>sign*(f(tracks[a])-f(tracks[b]));
    // Text dates sort as dates; a track never played sorts as the least recent.
    const date=(c,sign)=>(a,b)=>{
      const x=tracks[a][c], y=tracks[b][c];
      return sign*(x===y?0:x<y?-1:1);
    };
    const cmp={
      name:text(col("Song Name")), album:text(col("Album")),
      artist:text(col("Artist")), genre:text(col("Genre")),
      "highest rating":num(t=>value(t,col("Rating")),-1),
      "lowest rating":num(t=>value(t,col("Rating")),1),
      "most recently played":date(col("Last Played"),-1),
      "least recently played":date(col("Last Played"),1),
      "most often played":num(t=>t[col("Plays")],-1),
      "least often played":num(t=>t[col("Plays")],1),
      "most recently added":date(col("Date Added"),-1),
      "least recently added":date(col("Date Added"),1),
    }[by];
    if(!cmp)throw new Error(`no selection ${by}`);
    return out.sort(cmp);           // stable, so ties keep library order
  }

  // Take tracks in order until the next would go over the limit. iTunes stops
  // there: it does not pass over a big track to fit a smaller one after it.
  function limited(ids,limit,tracks,col){
    if(limit.unit==="items")return ids.slice(0,limit.count);
    const per={minutes:60,hours:3600,MB:MB,GB:GB}[limit.unit];
    const c=col(per>=MB?"Size":"Time"), cap=limit.count*per, out=[];
    let total=0;
    for(const i of ids){
      const v=tracks[i][c];
      if(total+v>cap)break;
      total+=v; out.push(i);
    }
    return out;
  }

  /* The pool rows that `rules` picks out of `ids`, in the order it picks them.
     fields is the page's [label, kind, show] list; now is in ms. */
  function evaluate(rules,tracks,fields,ids,{now=Date.now(),seed=1}={}){
    const at=new Map(fields.map((f,i)=>[f[0],i]));
    const col=label=>{
      if(!at.has(label))throw new Error(`no column ${label}`);
      return at.get(label);
    };
    const album=at.get("Album Rating");
    const value=(t,c)=>fields[c][0]==="Rating"?rated(t[c],t[album]):t[c];
    const checks=rules.rules.map(r=>[r,col(r.field),fields[col(r.field)][1]]);
    const all=rules.match!=="any";
    const checked=col("Checked");
    let out=ids.filter(i=>{
      const t=tracks[i];
      if(rules.checkedOnly&&t[checked]!==1)return false;
      if(!checks.length)return true;
      return all?checks.every(([r,c,k])=>test(r,k,value(t,c),now))
                :checks.some(([r,c,k])=>test(r,k,value(t,c),now));
    });
    if(rules.limit)
      out=limited(order(out,rules.limit.by,tracks,col,value,seed),rules.limit,tracks,col);
    return out;
  }

  return {evaluate,OPS,BY,UNITS,family,SPAN};
})();
if(typeof module!=="undefined")module.exports=Smart;
