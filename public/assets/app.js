/* ============================================================================
   PULSE OF THE PACIFIC — application core
   Data layer (live + embedded fallback) · living ocean · charts · map · forecast
   ============================================================================ */
"use strict";

const SEASONS = ["DJF","JFM","FMA","MAM","AMJ","MJJ","JJA","JAS","ASO","SON","OND","NDJ"];
const reduceMotion = (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || false;

/* ---------- Data layer -------------------------------------------------------
   Strategy: load embedded baseline JSON (always works). Then, when online and
   CORS permits (or a proxy is configured), fetch the live leading edge from NOAA
   and splice it onto the baseline. The site is fully functional with zero network.
----------------------------------------------------------------------------- */
const DATA = { oni:[], events:[], impacts:[], roni:[], roniCompare:[], wksst:[], soi:[], heat:[], live:false, sources:{} };

// Optional: set a CORS proxy base (e.g. your own Cloudflare Worker) to enable live NOAA fetch.
// Leave "" to run purely on embedded + same-origin /data files.
const PROXY = ""; // e.g. "https://your-worker.workers.dev/?url="

async function loadJSON(path){
  // Standalone single-file builds embed all data on window.__EMBEDDED__,
  // keyed by filename without extension (e.g. "oni", "manifest").
  if(typeof window!=="undefined" && window.__EMBEDDED__){
    const key = path.replace(/^data\//,"").replace(/\.json$/,"");
    if(key in window.__EMBEDDED__) return window.__EMBEDDED__[key];
    throw new Error(path+" not embedded");
  }
  const r = await fetch(path, {cache:"no-store"});
  if(!r.ok) throw new Error(path+" "+r.status);
  return r.json();
}

// Parse NOAA oni.ascii.txt / RONI.ascii.txt (whitespace-delimited) if we can reach it.
function parseONIascii(txt){
  const lines = txt.trim().split(/\r?\n/);
  const out = [];
  for(let i=1;i<lines.length;i++){
    const p = lines[i].trim().split(/\s+/);
    if(p.length<4) continue;
    const seas=p[0], yr=+p[1], anom=parseFloat(p[3]);
    const si=SEASONS.indexOf(seas);
    if(si<0||isNaN(yr)||isNaN(anom)) continue;
    out.push({y:yr, s:seas, m:si+1, t:+(yr+(si+0.5)/12).toFixed(4), v:anom});
  }
  return out;
}

// An index value exactly as NOAA's tables print it: one decimal, an exact half rounded
// up (0.45 -> 0.5, -0.45 -> -0.4), returned in whole TENTHS so every threshold below is
// an integer comparison. NOAA applies the +/-0.5 C threshold to this tabulated value,
// not to the two-decimal value in its data file. The same rule lives in
// scripts/enso_rule.py; tests/test_frontend.mjs holds the two to one NOAA table.
function tenths(v){ return Math.floor((Math.round(v*100)+5)/10); }

// NOAA's episode rule: tabulated value at or beyond +/-0.5 for >= 5 consecutive
// overlapping seasons => "E" (El Nino) / "L" (La Nina), otherwise "N".
function classifySeq(recs){
  const side=recs.map(r=>{ const t=tenths(r.v); return t>=5 ? 1 : t<=-5 ? -1 : 0; });
  const n=side.length, out=side.map(()=> "N");
  let i=0;
  while(i<n){
    if(side[i]===0){ i++; continue; }
    let j=i; while(j<n && side[j]===side[i]) j++;
    if(j-i>=5) for(let k=i;k<j;k++) out[k] = side[i]>0 ? "E" : "L";
    i=j;
  }
  recs.forEach((r,k)=>r.c=out[k]); return recs;
}

async function tryLiveONI(){
  if(!PROXY) return null;
  try{
    const url = PROXY + encodeURIComponent("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt");
    const r = await fetch(url, {cache:"no-store"});
    if(!r.ok) return null;
    const recs = parseONIascii(await r.text());
    return recs.length>800 ? recs : null;
  }catch(e){ return null; }
}

async function bootData(){
  // 1) embedded baseline (required) — the ONI history the whole site is built on
  const base = await loadJSON("data/oni.json");
  DATA.oni = base.records;
  DATA.sources.oni = base.meta || {};

  // 2) a manifest tells us which OPTIONAL live series exist right now, so we only
  //    request files that are present (no spurious 404s before the pipeline runs).
  const manifest = await loadJSON("data/manifest.json").catch(()=>({series:{events:true,impacts:true,roni_compare:true}}));
  const has = (k)=> manifest.series && manifest.series[k];
  const want = (k, path)=> has(k) ? loadJSON(path).catch(()=>null) : Promise.resolve(null);

  const [events, impacts, roniCmp, roniFull, wksst, soi, heat] = await Promise.all([
    want("events","data/events.json"),
    want("impacts","data/impacts.json"),
    want("roni_compare","data/roni_compare.json"),
    want("roni","data/roni.json"),
    want("wksst","data/wksst.json"),
    want("soi","data/soi.json"),
    want("heat","data/heat.json"),
  ]);
  DATA.events = events||[]; DATA.impacts = impacts||[]; DATA.roniCompare = roniCmp||[];
  if(roniFull && roniFull.records){ DATA.roni = roniFull.records; DATA.sources.roni = roniFull.meta||{}; }
  if(wksst && wksst.records){ DATA.wksst = wksst.records; DATA.sources.wksst = wksst.meta||{}; }
  if(soi && soi.records){ DATA.soi = soi.records; DATA.sources.soi = soi.meta||{}; }
  if(heat && heat.records){ DATA.heat = heat.records; DATA.sources.heat = heat.meta||{}; }

  // 3) "live" badge: the data is live-refreshed if the pipeline stamped any series.
  const stamped = Object.values(DATA.sources).some(m => m && m.updated);
  if(stamped) DATA.live = true;

  // 4) optional direct NOAA splice (only if a CORS proxy is configured)
  const live = await tryLiveONI();
  if(live){
    const lastT = DATA.oni[DATA.oni.length-1].t;
    const extra = live.filter(r=>r.t>lastT);
    if(extra.length){ DATA.oni = classifySeq(DATA.oni.concat(extra)); }
    DATA.live = true;
  }
  return DATA;
}

// The freshest single anomaly reading we can show: prefer the latest WEEKLY
// Niño-3.4 value (updates every Monday) and fall back to the latest ONI season.
function latestPulse(){
  if(DATA.wksst && DATA.wksst.length){
    const w = DATA.wksst[DATA.wksst.length-1];
    return { v:w.v, t:w.t, d:w.d, kind:"weekly", label:"weekly Niño-3.4" };
  }
  const o = DATA.oni[DATA.oni.length-1];
  return { v:o.v, t:o.t, kind:"oni", label:o.s+" ONI" };
}

/* ---------- Phase helpers ---------- */
function phaseOf(v){
  const t=tenths(v);   // thresholds apply to the value as tabulated (one decimal), like NOAA's
  if(t>=15) return {key:"E", label:"Strong El Niño", color:"#ff7a4d"};
  if(t>=5) return {key:"E", label:"El Niño", color:"#e85d3d"};
  if(t<=-15) return {key:"L", label:"Strong La Niña", color:"#3a9be8"};
  if(t<=-5) return {key:"L", label:"La Niña", color:"#2b6fb3"};
  return {key:"N", label:"ENSO-neutral", color:"#6f8aa8"};
}
// anomaly -> diverging color (cool blue / neutral / warm vermilion)
function anomColor(v){
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  if(v>=0){
    const t=clamp(v/2.6,0,1);
    // neutral #16263b -> warm #e85d3d -> hot #ffb347
    if(t<0.6){const u=t/0.6;return mix([22,38,59],[232,93,61],u);}
    const u=(t-0.6)/0.4;return mix([232,93,61],[255,179,71],u);
  }else{
    const t=clamp(-v/2.0,0,1);
    return mix([22,38,59],[43,111,179],t);
  }
}
function mix(a,b,t){return `rgb(${Math.round(a[0]+(b[0]-a[0])*t)},${Math.round(a[1]+(b[1]-a[1])*t)},${Math.round(a[2]+(b[2]-a[2])*t)})`;}

/* ============================================================================
   LIVING OCEAN — hero canvas
   A breathing equatorial SST-anomaly ribbon with advected current particles.
   Color is driven by the live ONI value: warm pushes the field red & eastward.
   ============================================================================ */
function initOcean(currentONI){
  const cv = document.getElementById("oceanCanvas");
  const ctx = cv.getContext("2d", {alpha:false});
  let W,H,dpr;
  const N = reduceMotion ? 0 : 520; // particle count
  let particles = [];
  const warm = Math.max(-2, Math.min(2.6, currentONI)); // -2..2.6

  function resize(){
    dpr = Math.min(2, window.devicePixelRatio||1);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = W*dpr; cv.height = H*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  resize(); window.addEventListener("resize", resize);

  // seed particles across the field
  for(let i=0;i<N;i++){
    particles.push({x:Math.random(), y:Math.random(), s:0.2+Math.random()*0.8, life:Math.random()});
  }

  // The equatorial "thermocline" band sits around mid-canvas; warmth bulges it east.
  function fieldColor(nx, ny, time){
    // nx,ny in 0..1 ; equator band centered at 0.52 with gentle wave
    const band = 0.52 + 0.05*Math.sin(nx*6.2 + time*0.15);
    const dist = Math.abs(ny - band);
    // anomaly intensity: strongest along equator, pushed toward east (right) when warm
    const eastBias = 0.5 + warm*0.16;           // warm shifts the hot core eastward
    const lon = Math.exp(-Math.pow((nx-eastBias)/0.34,2)); // gaussian along equator
    const lat = Math.exp(-Math.pow(dist/0.16,2));
    const wave = 0.5+0.5*Math.sin(nx*9 - time*0.6 + ny*4); // travelling Kelvin-wave shimmer
    const amp = lon*lat*(0.7+0.3*wave);
    const localAnom = warm*amp*1.9 + (ny<band? -0.25:0.05); // cool poleward, warm core
    return anomColor(localAnom);
  }

  let raf, t=0, running=true;
  document.addEventListener("visibilitychange", ()=>{
    if(document.hidden){ running=false; if(raf) cancelAnimationFrame(raf); }
    else if(!running){ running=true; frame(); }
  });
  function frame(){
    if(!running) return;
    t += reduceMotion?0:0.016;
    // base gradient (deep ocean)
    const g = ctx.createLinearGradient(0,0,0,H);
    
    g.addColorStop(0,"#040a14"); g.addColorStop(1,"#02060d");
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);

    // paint the anomaly field as a coarse grid of soft cells (cheap + smooth)
    const cols=46, rows=26;
    const cw=W/cols, ch=H/rows;
    for(let i=0;i<cols;i++){
      for(let j=0;j<rows;j++){
        const nx=(i+0.5)/cols, ny=(j+0.5)/rows;
        ctx.fillStyle=fieldColor(nx,ny,t);
        ctx.globalAlpha=0.72;
        ctx.fillRect(i*cw-1, j*ch-1, cw+2, ch+2);
      }
    }
    ctx.globalAlpha=1;

    // soft blur veil to blend cells into a continuous field
    ctx.fillStyle="rgba(4,10,20,0.10)"; ctx.fillRect(0,0,W,H);

    // advected current particles flow east along the equator (the Pacific current)
    if(N){
      ctx.lineWidth=1.1;
      for(const p of particles){
        const band = 0.52 + 0.05*Math.sin(p.x*6.2 + t*0.15);
        const pull = (band - p.y)*0.02;            // gently pulled to equator
        const speed = (0.0016 + 0.0022*Math.exp(-Math.pow((p.x-0.5)/0.4,2)))*(1+warm*0.18);
        const px=p.x, py=p.y;
        p.x += speed*p.s; p.y += pull + (Math.sin(p.x*20+t)*0.0003);
        p.life -= 0.004;
        if(p.x>1||p.life<=0){ p.x=Math.random()*0.15; p.y=band+(Math.random()-0.5)*0.3; p.life=1; }
        const a = Math.min(1,p.life)*0.5*(Math.exp(-Math.pow((p.x-0.55)/0.45,2)));
        ctx.strokeStyle=`rgba(225,240,250,${a*1.25})`;
        ctx.beginPath(); ctx.moveTo(px*W,py*H); ctx.lineTo(p.x*W,p.y*H); ctx.stroke();
      }
    }

    // equator guide line + label glow
    ctx.strokeStyle="rgba(61,214,196,0.10)"; ctx.lineWidth=1;
    ctx.beginPath();
    for(let i=0;i<=W;i+=6){const nx=i/W; const y=(0.52+0.05*Math.sin(nx*6.2+t*0.15))*H; i===0?ctx.moveTo(i,y):ctx.lineTo(i,y);}
    ctx.stroke();

    if(!reduceMotion) raf=requestAnimationFrame(frame); 
  }
  frame();
  if(reduceMotion){ frame(); } // single static paint
  return ()=>cancelAnimationFrame(raf);
}
/* ============================================================================
   STATUS READOUT
   ============================================================================ */
// Convert a fractional year (e.g. 2026.46) to a short human date like "17 Jun 2026".
function fracToDate(t){
  const y=Math.floor(t), doy=Math.max(1,Math.round((t-y)*365.25));
  const d=new Date(Date.UTC(y,0,doy));
  return d.getUTCDate()+" "+["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getUTCMonth()]+" "+y;
}

// "2026-11-04" -> "4 Nov 2026" (the exact week date the pipeline stores since Nov 2026).
function isoToShort(iso){
  const p = String(iso).split("-");
  return (+p[2])+" "+["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][(+p[1])-1]+" "+p[0];
}
// Signed one-decimal text of the tabulated value, e.g. +2.5 / -0.4 / 0.0 - the number
// NOAA's own table shows for the same season (see tenths()).
function signed1(v){ const t=tenths(v); return (t>0?"+":"")+(t/10).toFixed(1); }

// Whole-degree chart bounds that always contain the data. The defaults keep the
// familiar scale; a record-strength event widens the axis instead of running off it.
function axisBounds(values, defMin, defMax){
  let lo=defMin, hi=defMax;
  for(const v of values){
    if(v==null || !isFinite(v)) continue;
    if(v > hi-0.15) hi = Math.ceil(v+0.15);
    if(v < lo+0.15) lo = Math.floor(v-0.15);
  }
  return [lo,hi];
}

function renderStatus(){
  const recs = DATA.oni;
  const last = recs[recs.length-1];
  // SCIENTIFIC RULE: the ENSO *phase* comes from a 3-month index, never from a
  // single weekly reading. Since February 2026 NOAA's official index for ENSO
  // monitoring is the Relative ONI (RONI), so the phase pill and hero word follow
  // RONI whenever the live RONI feed is present and fall back to the ONI when it
  // is not. Both values are printed, so the reader always sees which is which.
  // The weekly value stays in its own cell as the freshest pulse.
  const roniLast = (DATA.roni && DATA.roni.length) ? DATA.roni[DATA.roni.length-1] : null;
  const official = roniLast || last;
  const phase = phaseOf(official.v);
  const pulse = latestPulse();
  const pulsePhase = phaseOf(pulse.v);

  const heroWord = phase.key==="E" ? "warming" : phase.key==="L" ? "cooling" : "breathing";
  const hp = document.getElementById("heroPhase"); if(hp) hp.textContent = heroWord;

  document.getElementById("phaseTxt").textContent = phase.label;
  document.querySelector("#phasePill .orb").style.background = phase.color;
  document.getElementById("phasePill").style.color = phase.color;
  const sub = document.getElementById("phaseSub");
  if(roniLast){
    sub.textContent = (roniLast.s===last.s && roniLast.y===last.y)
      ? `${last.s} ${last.y} · RONI ${signed1(roniLast.v)} · ONI ${signed1(last.v)}`
      : `RONI ${signed1(roniLast.v)} (${roniLast.s} ${roniLast.y}) · ONI ${signed1(last.v)} (${last.s} ${last.y})`;
    sub.title = "Phase follows the Relative ONI (RONI), NOAA's official ENSO index since February 2026. The long-standing ONI is shown alongside.";
  }else{
    sub.textContent = `${last.s} ${last.y} · ONI ${signed1(last.v)} · 3-month index`;
    sub.title = "Phase follows the Oceanic Niño Index (ONI). The Relative ONI feed is not available.";
  }

  // Freshest reading cell: weekly Niño-3.4 when the live feed exists, else latest ONI.
  const lbl = document.getElementById("pulseLabel");
  if(lbl) lbl.textContent = pulse.kind==="weekly" ? "Live Niño 3.4 · weekly" : "Latest ONI";
  const ov = document.getElementById("oniVal");
  ov.textContent = signed1(pulse.v);
  ov.style.color = pulsePhase.color;
  document.getElementById("oniSeason").textContent =
    pulse.kind==="weekly" ? `°C · week of ${pulse.d ? isoToShort(pulse.d) : fracToDate(pulse.t)}` : `°C · Niño 3.4 · ${last.s} ${last.y}`;

  // trend: ONI vs ONI twelve seasons earlier — like compared with like.
  const past = recs[Math.max(0,recs.length-13)];
  const d = tenths(last.v - past.v);          // change in whole tenths: no "+0.0" with an arrow
  const tv = document.getElementById("trendVal");
  tv.textContent = (d>0?"▲ +":d<0?"▼ ":"– ")+(Math.abs(d)/10).toFixed(1);
  tv.style.color = d>0? "#ff7a4d" : d<0? "#3a9be8" : "#6f8aa8";
  document.getElementById("trendSub").textContent = `since ${past.s} ${past.y}`;

  // alert (current advisory; auto-refreshed wording would be scraped at deploy)
  document.getElementById("alertVal").textContent = "El Niño Advisory";
  document.getElementById("alertSub").textContent = "NOAA CPC · developing 2026–27";

  // build stamp — show when the data pipeline last refreshed, if known
  const now = new Date();
  const stamp = (DATA.sources.oni && DATA.sources.oni.updated) ? DATA.sources.oni.updated.slice(0,16).replace("T"," ") : null;
  document.getElementById("buildStamp").textContent =
    stamp ? `Data refreshed ${stamp} UTC · rendered ${now.toISOString().slice(0,16).replace("T"," ")} UTC`
          : `Rendered ${now.toISOString().slice(0,16).replace("T"," ")} UTC · ${DATA.live?"live data spliced":"embedded baseline"}`;
}

/* live clock in topbar */
function startClock(){
  const el=document.getElementById("liveClock");
  function tick(){ const d=new Date(); el.textContent = d.toUTCString().slice(17,25)+" UTC"; }
  tick(); setInterval(tick,1000);
}

/* ============================================================================
   ONI TIMELINE  (ECharts)
   ============================================================================ */
let oniChart, oniState={range:"all", idx:"oni"};
function buildONIChart(){
  oniChart = echarts.init(document.getElementById("oniChart"), null, {renderer:"canvas"});
  drawONI();
  window.addEventListener("resize", ()=>oniChart.resize());
}
function rangeStartYear(){
  const last = DATA.oni[DATA.oni.length-1].y;
  if(oniState.range==="all") return 1950;
  return last - (+oniState.range);
}
function drawONI(){
  const startY = rangeStartYear();
  const recs = DATA.oni.filter(r=>r.y>=startY);
  const data = recs.map(r=>[r.t, r.v, r.c, r.s, r.y]);

  // color each bar by anomaly value via visualMap (performant + correct)
  const series=[{
    type:"bar", name:"ONI",
    data: data.map(d=>[d[0],d[1]]),
    barWidth: oniState.range==="all"? "62%" : "72%",
    animationDelay:(i)=>Math.min(i*1.2,600),
    markLine:{
      silent:true, symbol:"none",
      data:[
        {yAxis:0.5, lineStyle:{color:"rgba(232,93,61,.45)",type:[4,4],width:1}, label:{show:true,formatter:"El Niño +0.5",color:"rgba(232,93,61,.7)",fontFamily:"JetBrains Mono",fontSize:9,position:"insideStartTop"}},
        {yAxis:-0.5,lineStyle:{color:"rgba(43,111,179,.45)",type:[4,4],width:1}, label:{show:true,formatter:"La Niña −0.5",color:"rgba(77,159,224,.7)",fontFamily:"JetBrains Mono",fontSize:9,position:"insideStartBottom"}},
        {yAxis:0,   lineStyle:{color:"rgba(125,150,179,.25)",width:1}, label:{show:false}}
      ]
    }
  }];

  // optional RONI overlay — plot the REAL Relative ONI series if the pipeline
  // fetched it; otherwise fall back to a clearly-labelled schematic estimate.
  if(oniState.idx==="roni"){
    let roniLine, roniName;
    if(DATA.roni && DATA.roni.length){
      const byT = new Map(DATA.roni.map(r=>[Math.round(r.t*12), r.v]));
      roniLine = recs.map(r=>{
        const v = byT.get(Math.round(r.t*12));
        return v===undefined ? [r.t, null] : [r.t, +v.toFixed(2)];
      });
      roniName = "RONI (relative)";
    }else{
      roniLine = recs.map(r=>{
        const trend = Math.max(0, (r.y-1980))*0.006; // ~0.6C since 1980, schematic
        return [r.t, +(r.v - trend).toFixed(2)];
      });
      roniName = "RONI (schematic)";
    }
    series.push({
      type:"line", name:roniName, data:roniLine, showSymbol:false, connectNulls:true,
      lineStyle:{color:"#3dd6c4",width:1.8,type:DATA.roni&&DATA.roni.length?"solid":[6,4]}, z:5,
      tooltip:{show:true}
    });
  }

  // y-range: ±3 by default, widened by whole degrees if any bar (or the RONI line) needs it
  const yVals = recs.map(r=>r.v).concat(series[1] ? series[1].data.map(d=>d[1]) : []);
  const [yLo,yHi] = axisBounds(yVals, -3, 3);

  oniChart.setOption({
    backgroundColor:"transparent",
    grid:{left:46,right:18,top:24,bottom:34},
    animationDuration:700, animationEasing:"cubicOut",
    visualMap:{
      type:"continuous", min:-2.6, max:2.6, dimension:1, seriesIndex:0, show:false,
      inRange:{ color:["#2b6fb3","#3a6f9a","#16263b","#b6452f","#e85d3d","#ffb347"] }
    },
    tooltip:{
      trigger:"axis",
      backgroundColor:"rgba(10,20,36,.97)", borderColor:"#162a44", borderWidth:1,
      textStyle:{color:"#e8edf4",fontFamily:"JetBrains Mono",fontSize:11.5},
      formatter:(ps)=>{
        const p=ps[0]; const idx=p.dataIndex; const r=recs[idx];
        const ph=phaseOf(r.v);
        let s=`<b style="font-family:Space Grotesk">${r.s} ${r.y}</b><br/>ONI <b style="color:${ph.color}">${signed1(r.v)} °C</b><br/><span style="color:${ph.color}">${ph.label}</span>`;
        if(ps[1] && ps[1].value[1]!=null){
          const rv = ps[1].value[1], real = DATA.roni && DATA.roni.length;
          s+=`<br/>RONI ${real?"":"≈ "}${signed1(+rv)} °C`;
        }
        return s;
      }
    },
    xAxis:{
      type:"value", min:startY, max:DATA.oni[DATA.oni.length-1].t+0.3,
      interval: oniState.range==="all"?10: oniState.range==="40"?10: oniState.range==="20"?5:2,
      axisLine:{lineStyle:{color:"#1c3350"}},
      axisLabel:{color:"#5f7a9a",fontFamily:"JetBrains Mono",fontSize:11,formatter:(v)=>Math.round(v)},
      splitLine:{show:false}
    },
    yAxis:{
      type:"value", min:yLo, max:yHi, interval:1,
      name:"°C anomaly", nameTextStyle:{color:"#5f7a9a",fontFamily:"JetBrains Mono",fontSize:10,align:"left"},
      axisLine:{show:false}, axisTick:{show:false},
      axisLabel:{color:"#5f7a9a",fontFamily:"JetBrains Mono",fontSize:11,formatter:(v)=>v>0?"+"+v:v},
      splitLine:{lineStyle:{color:"#0f2138"}}
    },
    series
  }, true);

  // RONI caveat note: be explicit about whether the teal line is real or estimated
  const note = document.getElementById("roniNote");
  if(note){
    if(oniState.idx!=="roni"){
      note.style.display="none";
    }else if(DATA.roni && DATA.roni.length){
      note.style.display="block";
      note.textContent = "RONI (Relative ONI) is NOAA's operational index since Feb 2026: it removes tropical-mean warming, so strong events read slightly cooler than ONI. Shown here from official NOAA data.";
    }else{
      note.style.display="block";
      note.textContent = "Note: this RONI line is a schematic estimate (ONI minus a simple tropical-warming term), shown for illustration until the live NOAA RONI feed is connected. It is not official RONI data.";
    }
  }
}

/* segmented controls for timeline */
function wireTimelineControls(){
  document.querySelectorAll("#rangeSeg button").forEach(b=>{
    b.addEventListener("click",()=>{
      document.querySelectorAll("#rangeSeg button").forEach(x=>x.setAttribute("aria-pressed","false"));
      b.setAttribute("aria-pressed","true");
      oniState.range=b.dataset.range; drawONI();
    });
  });
  document.querySelectorAll("#idxSeg button").forEach(b=>{
    b.addEventListener("click",()=>{
      const on = b.getAttribute("aria-pressed")==="true";
      // RONI button toggles overlay; ONI button is always-on base
      if(b.dataset.idx==="roni"){
        b.setAttribute("aria-pressed", on?"false":"true");
        oniState.idx = on? "oni":"roni"; drawONI();
      }
    });
  });
}
/* ============================================================================
   INTERACTIVE IMPACT MAP  (real Natural Earth coastlines, projected to SVG)
   Equirectangular viewBox 1000x500 => lon -180..180 -> x, lat 90..-90 -> y.
   Self-contained: land geometry embedded; no external tiles or fetches.
   ============================================================================ */
function lonlatToXY(lon,lat){ return [ (lon+180)/360*1000, (90-lat)/180*500 ]; }

// Real world land outline (Natural Earth 110m, simplified ~0.45°), single path, ~22KB.
const LAND_PATH = "M 334.5 472.3 L 332.9 475.0 L 315.9 472.9 L 328.1 473.3 L 331.6 471.2 L 334.5 472.3 Z M 57.8 470.8 L 52.4 471.2 L 45.2 468.3 L 52.1 467.7 L 57.8 470.8 Z M 364.8 466.8 L 378.0 468.0 L 379.6 472.3 L 359.8 475.1 L 349.5 474.0 L 364.8 466.8 Z M 309.9 447.1 L 308.9 450.5 L 302.6 451.4 L 293.9 451.0 L 291.6 449.1 L 299.8 447.8 L 300.7 443.1 L 304.9 441.3 L 309.9 447.1 Z M 341.0 426.5 L 327.7 430.0 L 326.0 431.9 L 327.4 433.9 L 317.6 438.8 L 328.3 446.4 L 331.0 454.7 L 321.2 459.1 L 303.9 462.9 L 285.4 463.1 L 295.4 466.4 L 283.5 467.7 L 283.3 469.9 L 290.7 472.9 L 334.2 478.8 L 338.3 481.2 L 361.8 477.0 L 381.1 478.0 L 386.7 476.0 L 420.7 473.2 L 417.5 470.2 L 401.0 470.7 L 400.6 467.6 L 451.3 458.7 L 456.4 456.9 L 457.2 455.9 L 454.3 455.2 L 457.1 453.2 L 471.4 448.0 L 479.4 449.2 L 480.9 447.0 L 499.4 449.0 L 521.5 444.1 L 530.0 446.8 L 537.3 444.4 L 575.3 445.7 L 588.9 443.5 L 594.1 440.3 L 607.4 443.8 L 651.5 432.8 L 670.6 438.8 L 677.9 437.2 L 691.4 438.7 L 693.5 442.3 L 688.4 445.3 L 691.9 446.3 L 688.7 449.6 L 694.1 450.7 L 705.2 444.1 L 715.7 443.0 L 729.9 436.7 L 741.0 436.5 L 744.4 433.9 L 749.1 436.5 L 766.1 437.2 L 777.0 436.8 L 785.6 432.1 L 794.9 435.9 L 815.6 433.0 L 832.9 436.9 L 842.3 434.7 L 874.3 433.9 L 875.2 431.4 L 881.8 436.0 L 904.1 435.9 L 913.4 440.0 L 928.6 440.4 L 948.8 446.1 L 975.6 449.2 L 970.2 454.6 L 961.4 456.6 L 954.4 461.8 L 954.1 464.1 L 957.6 467.2 L 963.9 468.8 L 949.4 469.9 L 943.9 474.8 L 970.6 482.8 L 1000.0 485.3 L 1000.0 500.0 L 0.0 500.0 L 0.0 485.3 L 2.6 483.7 L 15.6 484.8 L 27.9 483.0 L 60.9 487.1 L 102.5 486.2 L 103.1 484.9 L 73.4 482.5 L 75.4 477.9 L 64.3 475.3 L 81.5 475.9 L 93.3 473.2 L 84.6 470.4 L 68.5 469.6 L 61.0 466.7 L 60.1 463.6 L 79.6 465.0 L 94.2 462.4 L 93.9 459.4 L 124.4 456.4 L 163.7 457.0 L 183.5 454.8 L 188.1 457.5 L 201.2 458.8 L 221.9 458.0 L 215.2 455.9 L 212.0 451.7 L 232.4 454.5 L 249.8 453.7 L 252.1 451.6 L 273.7 455.1 L 277.0 453.1 L 292.0 455.2 L 312.9 451.3 L 309.6 443.7 L 312.7 439.3 L 311.8 437.0 L 325.0 429.6 L 341.0 426.5 Z M 311.8 399.6 L 319.3 401.9 L 307.7 404.2 L 292.6 396.8 L 302.5 400.2 L 307.4 395.9 L 311.8 399.6 Z M 337.4 391.9 L 338.8 394.2 L 330.0 394.0 L 333.3 392.4 L 337.4 391.9 Z M 695.2 388.1 L 691.0 388.3 L 691.5 385.1 L 695.9 386.3 L 695.2 388.1 Z M 902.0 364.3 L 911.9 363.5 L 910.9 370.0 L 905.7 371.0 L 902.0 364.3 Z M 978.0 363.8 L 984.0 364.9 L 979.8 370.5 L 980.8 371.8 L 976.3 372.9 L 973.9 377.5 L 970.4 379.6 L 963.0 378.4 L 964.0 375.3 L 973.7 369.5 L 978.0 363.8 Z M 984.2 348.0 L 991.0 355.2 L 995.9 354.7 L 994.4 358.8 L 992.2 358.7 L 986.8 365.8 L 985.1 364.7 L 985.8 360.9 L 982.8 359.7 L 985.3 353.8 L 979.5 345.9 L 984.2 348.0 Z M 964.2 311.6 L 959.7 310.2 L 955.6 305.8 L 958.4 306.8 L 964.2 311.6 Z M 636.7 283.4 L 639.9 293.6 L 638.0 293.6 L 630.8 319.3 L 626.1 321.1 L 622.3 319.4 L 620.2 311.3 L 623.3 305.8 L 622.1 298.4 L 623.5 295.0 L 632.5 290.5 L 636.7 283.4 Z M 898.8 288.2 L 903.8 291.6 L 906.6 302.7 L 913.5 306.6 L 915.8 312.1 L 918.7 312.2 L 925.4 322.4 L 926.6 328.1 L 924.7 337.9 L 917.6 349.1 L 916.7 354.0 L 906.4 358.4 L 902.4 356.7 L 902.9 355.3 L 898.9 357.8 L 890.7 355.6 L 887.7 350.4 L 883.7 348.9 L 883.9 345.5 L 880.1 347.9 L 882.8 341.4 L 877.7 346.9 L 873.0 340.6 L 864.8 337.5 L 850.4 339.5 L 845.1 341.6 L 843.5 344.1 L 833.0 344.4 L 827.8 347.4 L 819.5 345.0 L 821.4 337.8 L 814.8 322.5 L 816.1 323.7 L 815.1 321.2 L 817.3 323.1 L 815.0 317.7 L 817.1 310.4 L 817.3 312.5 L 824.2 307.5 L 835.7 304.7 L 841.7 295.6 L 844.1 297.4 L 843.1 296.1 L 849.1 289.5 L 853.0 288.4 L 860.1 291.6 L 862.8 284.8 L 868.3 283.7 L 866.2 281.3 L 867.7 280.9 L 875.8 284.0 L 879.1 282.9 L 880.4 284.3 L 876.4 291.7 L 889.5 299.2 L 892.4 295.5 L 895.9 279.6 L 898.8 288.2 Z M 853.7 273.3 L 842.9 278.4 L 847.5 274.0 L 853.7 273.3 Z M 841.4 272.5 L 841.0 274.0 L 833.1 274.5 L 835.3 272.9 L 841.4 272.5 Z M 801.7 268.8 L 807.7 268.0 L 821.4 273.3 L 818.2 274.3 L 792.7 269.0 L 794.6 266.4 L 801.7 268.8 Z M 922.2 265.2 L 917.3 267.5 L 912.0 266.0 L 917.1 263.9 L 918.9 265.2 L 920.9 261.6 L 923.2 262.0 L 922.2 265.2 Z M 862.4 258.6 L 863.4 260.7 L 855.3 259.4 L 855.9 257.9 L 862.4 258.6 Z M 872.6 253.2 L 873.4 257.7 L 876.3 259.4 L 878.6 256.4 L 884.2 254.7 L 901.6 260.7 L 905.5 265.2 L 910.1 266.9 L 908.9 270.5 L 918.6 279.4 L 910.9 278.1 L 905.7 272.4 L 902.1 271.2 L 896.2 275.9 L 886.5 272.5 L 882.3 273.4 L 885.2 270.3 L 883.1 265.0 L 871.3 259.8 L 869.4 261.4 L 866.6 257.8 L 871.4 256.2 L 867.3 256.1 L 862.6 252.6 L 867.7 251.0 L 872.6 253.2 Z M 847.9 246.1 L 843.6 249.3 L 833.8 249.3 L 835.9 253.9 L 842.6 251.7 L 837.5 255.3 L 842.1 264.8 L 839.5 264.7 L 840.9 262.4 L 837.5 262.7 L 836.0 257.3 L 834.2 258.1 L 834.5 265.4 L 831.6 264.9 L 831.9 259.7 L 829.9 257.8 L 833.4 248.4 L 835.8 246.4 L 841.5 247.6 L 847.9 246.1 Z M 855.4 244.0 L 857.3 249.3 L 855.9 249.0 L 855.8 252.5 L 853.9 247.2 L 855.4 244.0 Z M 793.9 266.3 L 790.9 266.3 L 785.0 261.7 L 764.7 234.8 L 770.8 235.4 L 779.6 244.2 L 782.4 244.2 L 788.4 249.7 L 787.3 252.0 L 794.7 258.5 L 793.9 266.3 Z M 825.9 241.0 L 830.5 247.5 L 827.3 247.8 L 822.6 261.1 L 806.2 258.2 L 803.0 251.3 L 804.6 244.4 L 808.8 244.9 L 809.4 242.5 L 813.9 241.4 L 824.2 230.8 L 831.1 235.0 L 825.9 241.0 Z M 848.4 222.9 L 851.5 230.0 L 850.5 232.6 L 849.5 229.7 L 848.2 231.1 L 848.3 234.5 L 845.1 232.9 L 843.4 228.2 L 838.7 230.0 L 843.0 225.9 L 844.0 227.1 L 848.5 225.0 L 848.4 222.9 Z M 725.6 232.8 L 723.2 233.4 L 721.9 231.2 L 722.6 222.7 L 727.2 229.1 L 725.6 232.8 Z M 844.7 218.8 L 841.7 224.9 L 839.9 223.0 L 841.5 219.8 L 843.1 219.6 L 842.6 221.5 L 844.7 218.8 Z M 832.5 220.7 L 825.5 226.8 L 832.0 218.4 L 832.5 220.7 Z M 848.6 216.2 L 849.4 219.3 L 847.3 218.6 L 846.7 221.8 L 845.2 215.1 L 848.6 216.2 Z M 835.3 198.6 L 839.6 198.7 L 840.3 202.5 L 838.0 205.7 L 838.1 210.2 L 844.3 211.7 L 844.7 215.2 L 841.5 212.4 L 835.1 211.5 L 836.1 209.7 L 833.5 208.4 L 833.0 204.5 L 834.1 205.5 L 835.3 198.6 Z M 296.1 195.4 L 305.7 195.4 L 310.2 198.3 L 303.7 198.8 L 301.7 201.1 L 293.2 199.0 L 299.1 198.1 L 296.1 195.4 Z M 806.5 198.1 L 801.8 198.6 L 801.7 196.2 L 807.7 194.2 L 806.5 198.1 Z M 271.5 185.6 L 282.4 187.5 L 293.9 193.7 L 284.0 194.8 L 285.9 193.3 L 281.3 190.0 L 271.8 187.8 L 272.8 187.1 L 264.0 189.2 L 271.5 185.6 Z M 838.8 180.6 L 835.4 189.0 L 833.6 184.6 L 837.5 179.7 L 838.8 180.6 Z M 874.0 155.1 L 872.8 157.8 L 867.7 158.4 L 869.2 155.4 L 874.0 155.1 Z M 543.1 143.8 L 541.9 148.3 L 534.5 145.5 L 534.9 144.1 L 543.1 143.8 Z M 525.6 135.5 L 526.9 141.2 L 524.5 141.9 L 522.7 136.2 L 525.6 135.5 Z M 894.1 141.2 L 889.6 152.4 L 881.2 153.9 L 877.2 157.0 L 875.2 153.9 L 863.9 155.9 L 866.7 157.9 L 864.8 162.6 L 861.7 162.7 L 862.4 160.2 L 859.5 157.5 L 868.4 151.6 L 876.9 151.3 L 879.8 146.4 L 881.6 147.7 L 887.3 143.8 L 888.6 137.3 L 892.7 135.1 L 894.1 141.2 Z M 899.8 127.3 L 903.7 126.7 L 904.3 129.8 L 900.2 130.6 L 897.7 133.3 L 893.4 131.4 L 891.9 134.5 L 888.8 134.5 L 888.4 131.8 L 892.7 129.5 L 894.4 123.5 L 899.8 127.3 Z M 156.9 115.2 L 151.0 114.4 L 144.3 111.1 L 143.4 109.0 L 150.7 110.3 L 156.9 115.2 Z M 346.1 106.7 L 342.2 111.6 L 351.5 113.2 L 350.6 115.2 L 352.5 114.8 L 353.8 118.0 L 352.6 120.4 L 349.5 120.0 L 349.3 117.4 L 346.1 119.8 L 344.5 119.7 L 346.4 118.4 L 343.7 117.7 L 335.4 117.8 L 335.5 115.2 L 340.7 109.1 L 346.1 106.7 Z M 130.1 99.5 L 134.0 99.7 L 133.2 102.8 L 135.6 105.1 L 130.4 101.6 L 130.1 99.5 Z M 896.3 99.0 L 901.8 114.0 L 897.7 113.0 L 896.0 117.1 L 898.6 121.8 L 896.5 120.2 L 894.7 122.3 L 894.9 108.5 L 893.3 105.7 L 893.6 101.9 L 896.1 100.7 L 895.0 99.4 L 896.3 99.0 Z M 481.1 104.8 L 472.3 106.1 L 474.5 103.2 L 473.1 100.3 L 481.3 96.7 L 484.3 98.5 L 481.1 104.8 Z M 491.7 87.1 L 488.7 90.1 L 494.6 89.8 L 491.3 94.5 L 494.2 94.7 L 501.3 103.0 L 504.7 103.5 L 502.9 106.1 L 504.0 107.5 L 485.4 111.2 L 484.0 110.7 L 490.5 107.1 L 485.4 105.6 L 488.3 104.7 L 487.3 101.4 L 491.4 101.7 L 491.8 100.0 L 486.5 97.8 L 486.0 95.0 L 484.5 96.4 L 482.9 92.3 L 486.1 87.1 L 491.7 87.1 Z M 261.4 67.4 L 264.0 68.8 L 277.5 73.0 L 269.1 71.9 L 262.4 74.9 L 261.5 73.2 L 257.7 73.5 L 260.1 72.1 L 261.4 67.4 Z M 459.7 65.4 L 459.1 67.2 L 462.2 69.1 L 448.2 73.6 L 436.8 72.3 L 439.5 71.1 L 433.5 69.7 L 438.3 68.4 L 432.4 67.7 L 438.5 65.5 L 442.8 67.4 L 459.7 65.4 Z M 13.8 65.0 L 22.6 64.1 L 28.1 66.7 L 20.7 68.2 L 19.6 71.5 L 4.6 68.4 L 3.6 66.4 L 0.3 67.0 L 1.6 68.3 L 0.0 69.5 L 0.0 58.4 L 14.1 63.3 L 13.8 65.0 Z M 234.3 58.0 L 232.6 59.0 L 222.8 57.2 L 227.2 55.2 L 234.3 58.0 Z M 248.5 57.0 L 248.5 59.8 L 252.2 57.6 L 255.5 59.4 L 254.7 61.5 L 257.4 63.3 L 262.3 58.9 L 262.4 55.9 L 270.5 56.5 L 274.2 57.9 L 272.3 60.7 L 274.3 62.2 L 268.5 65.5 L 261.8 65.1 L 257.4 70.1 L 241.2 77.7 L 238.2 80.8 L 237.0 86.3 L 241.1 86.7 L 243.6 91.4 L 247.5 90.9 L 263.9 96.4 L 271.5 96.8 L 271.9 102.0 L 278.0 107.8 L 281.7 104.0 L 278.3 98.1 L 287.4 93.0 L 281.9 86.7 L 285.2 83.7 L 283.0 76.9 L 294.9 76.5 L 301.7 80.2 L 306.7 80.4 L 307.5 86.2 L 312.1 88.3 L 320.6 82.4 L 329.5 91.8 L 328.3 93.5 L 340.7 98.3 L 345.1 102.0 L 345.3 105.1 L 333.2 110.4 L 315.6 110.5 L 302.5 119.9 L 309.3 115.8 L 319.3 113.2 L 321.7 114.6 L 319.1 116.5 L 320.9 121.6 L 329.1 122.5 L 331.9 119.4 L 333.9 122.4 L 318.4 129.0 L 316.3 128.8 L 316.2 126.5 L 321.0 124.2 L 313.5 124.6 L 303.6 130.5 L 305.7 134.3 L 295.2 136.3 L 300.2 136.3 L 294.6 136.8 L 291.9 141.8 L 290.2 140.3 L 291.5 143.3 L 289.1 146.6 L 287.9 141.2 L 288.0 144.2 L 286.2 143.8 L 288.1 144.7 L 289.6 151.2 L 274.1 162.7 L 277.6 175.3 L 276.7 180.0 L 273.0 178.1 L 269.6 169.2 L 266.4 166.4 L 263.6 167.7 L 260.0 165.6 L 252.3 165.8 L 252.2 168.6 L 249.6 169.1 L 239.3 167.5 L 231.7 171.4 L 229.5 173.9 L 228.1 187.7 L 232.5 196.3 L 237.7 199.6 L 244.3 198.0 L 247.9 196.4 L 249.2 191.7 L 258.2 190.2 L 253.0 205.9 L 263.9 205.6 L 268.3 207.6 L 267.2 219.2 L 273.8 225.6 L 279.0 223.3 L 286.6 226.0 L 291.9 219.2 L 296.1 218.8 L 300.7 215.5 L 302.4 216.4 L 300.1 218.3 L 300.8 224.8 L 302.7 222.6 L 301.7 219.5 L 305.1 218.4 L 305.7 216.2 L 310.6 220.7 L 319.7 222.0 L 328.1 220.2 L 325.7 221.1 L 326.7 222.4 L 331.0 223.9 L 331.5 226.2 L 335.8 227.8 L 341.3 233.4 L 350.1 234.0 L 357.5 238.3 L 361.2 245.2 L 360.0 250.2 L 364.9 250.7 L 365.0 253.4 L 367.2 251.6 L 375.3 254.3 L 376.2 257.5 L 388.9 258.0 L 396.6 263.4 L 401.1 264.3 L 403.5 270.4 L 402.4 275.0 L 392.6 286.3 L 390.9 299.6 L 386.3 310.9 L 383.4 313.8 L 376.0 314.9 L 367.6 319.1 L 365.3 321.9 L 364.2 329.7 L 350.5 345.5 L 343.8 346.8 L 337.7 344.2 L 342.3 352.5 L 339.6 356.1 L 335.5 357.6 L 326.8 357.9 L 327.4 363.0 L 325.7 364.0 L 319.1 364.1 L 319.5 366.8 L 323.7 368.2 L 318.9 370.8 L 317.9 375.1 L 313.1 376.5 L 312.3 378.6 L 317.7 381.2 L 316.7 383.7 L 307.9 390.9 L 310.7 395.4 L 303.2 396.9 L 302.8 399.5 L 291.8 395.2 L 290.0 385.2 L 294.1 380.4 L 289.9 379.6 L 293.5 372.5 L 296.6 373.5 L 298.0 367.7 L 296.1 367.0 L 295.3 370.5 L 293.5 370.1 L 296.6 359.1 L 295.6 353.2 L 301.6 340.1 L 305.1 304.9 L 304.5 301.0 L 301.5 298.2 L 288.9 290.7 L 278.4 270.0 L 274.3 267.0 L 273.9 263.2 L 278.4 257.4 L 275.1 256.2 L 275.2 252.9 L 277.5 247.9 L 281.0 246.2 L 285.8 239.3 L 282.8 226.9 L 279.0 225.2 L 276.4 227.5 L 277.8 229.0 L 275.3 229.9 L 274.8 228.3 L 268.0 226.5 L 264.0 222.0 L 263.6 223.5 L 262.1 222.4 L 261.9 219.2 L 257.0 213.1 L 246.6 211.3 L 237.0 205.0 L 231.8 206.5 L 212.5 199.2 L 207.0 194.6 L 207.6 190.5 L 205.5 186.7 L 188.3 169.6 L 185.7 163.4 L 181.2 161.7 L 181.5 166.2 L 196.0 185.6 L 194.4 186.6 L 188.4 181.3 L 188.1 177.7 L 180.4 173.0 L 182.9 170.6 L 179.1 167.9 L 174.2 158.2 L 164.9 153.9 L 154.4 138.0 L 155.8 123.5 L 153.6 116.2 L 158.0 116.6 L 159.5 119.2 L 158.8 113.9 L 146.0 108.8 L 144.9 104.6 L 141.3 103.5 L 127.6 88.5 L 91.3 80.9 L 88.3 81.5 L 88.8 83.4 L 78.6 85.7 L 81.6 79.8 L 72.2 85.1 L 74.2 86.5 L 71.6 88.5 L 59.9 94.5 L 42.3 98.9 L 61.9 90.1 L 63.8 86.3 L 50.1 87.0 L 50.3 84.4 L 44.9 83.9 L 38.6 79.2 L 42.9 74.6 L 53.4 72.9 L 51.3 71.1 L 53.4 70.0 L 41.8 71.0 L 33.0 67.6 L 43.1 65.1 L 50.9 66.3 L 36.8 60.1 L 50.3 54.6 L 65.1 51.8 L 120.8 58.6 L 139.5 55.0 L 141.4 56.2 L 144.1 54.2 L 150.7 57.0 L 154.4 55.1 L 154.8 57.2 L 162.6 56.1 L 183.6 60.0 L 179.7 61.4 L 194.6 61.2 L 197.6 62.8 L 200.6 61.4 L 197.7 60.2 L 199.5 59.3 L 205.1 58.9 L 218.2 62.1 L 226.5 61.7 L 226.2 60.0 L 228.7 59.5 L 233.0 60.4 L 233.0 63.1 L 238.2 58.1 L 232.0 55.3 L 232.2 52.2 L 235.5 50.2 L 245.8 55.0 L 243.3 56.4 L 248.5 57.0 Z M 182.9 46.9 L 181.5 48.2 L 194.7 47.3 L 199.5 51.0 L 200.9 49.8 L 198.9 47.0 L 204.1 47.0 L 207.2 48.1 L 209.8 52.8 L 219.2 56.7 L 214.6 56.9 L 215.5 59.0 L 205.7 57.8 L 185.2 59.6 L 174.1 55.7 L 187.7 54.5 L 172.5 54.1 L 171.0 53.0 L 177.5 51.9 L 168.3 51.2 L 172.6 48.0 L 182.9 46.9 Z M 287.9 46.9 L 279.2 47.9 L 275.3 46.3 L 283.2 45.4 L 287.9 46.9 Z M 259.5 46.8 L 261.7 48.5 L 264.3 46.3 L 271.3 45.1 L 276.1 48.0 L 275.7 49.8 L 283.8 47.9 L 294.2 51.9 L 299.3 51.2 L 308.9 54.1 L 314.0 57.8 L 308.9 59.1 L 328.2 64.3 L 322.4 69.4 L 314.7 65.6 L 311.1 65.9 L 310.7 67.5 L 318.6 71.2 L 320.4 73.9 L 319.4 75.9 L 308.9 72.9 L 316.2 78.0 L 302.7 75.2 L 292.1 70.3 L 284.1 71.6 L 281.8 70.6 L 283.6 68.6 L 294.6 68.2 L 293.6 67.2 L 298.2 63.1 L 297.4 61.9 L 280.7 55.1 L 264.0 55.6 L 253.7 54.4 L 251.4 53.4 L 254.3 52.2 L 250.3 52.2 L 249.4 49.3 L 251.6 46.9 L 261.6 45.0 L 259.5 46.8 Z M 217.9 46.2 L 229.5 45.1 L 227.6 47.2 L 231.8 48.4 L 231.3 50.9 L 224.1 51.8 L 215.3 48.6 L 221.0 48.0 L 217.9 46.2 Z M 898.9 46.6 L 894.7 46.7 L 888.5 46.2 L 894.6 44.8 L 898.9 46.6 Z M 248.6 44.8 L 235.0 49.8 L 233.3 46.0 L 237.5 44.1 L 248.6 44.8 Z M 165.4 51.7 L 158.1 53.1 L 150.2 50.4 L 155.7 45.3 L 153.0 43.6 L 173.5 43.9 L 179.1 45.9 L 168.8 48.6 L 165.4 51.7 Z M 918.7 41.4 L 915.5 42.5 L 905.9 41.2 L 906.6 40.3 L 918.7 41.4 Z M 240.0 41.7 L 238.5 42.8 L 231.1 41.9 L 236.5 39.9 L 240.0 41.7 Z M 903.0 40.1 L 900.8 42.2 L 886.0 42.7 L 880.5 40.9 L 885.6 38.5 L 903.0 40.1 Z M 226.4 36.9 L 228.5 38.2 L 227.3 41.7 L 215.3 40.1 L 215.1 38.0 L 226.4 36.9 Z M 195.6 36.7 L 206.4 40.3 L 188.3 43.3 L 183.7 42.4 L 189.5 41.2 L 173.0 41.0 L 179.4 37.6 L 197.0 40.4 L 193.1 37.7 L 195.6 36.7 Z M 659.8 53.6 L 649.1 53.4 L 642.9 50.0 L 651.2 45.5 L 648.6 45.1 L 655.3 42.7 L 654.5 41.4 L 669.9 38.2 L 691.3 37.4 L 662.4 43.6 L 653.9 49.0 L 654.5 51.3 L 659.8 53.6 Z M 230.2 36.8 L 245.5 36.7 L 252.3 40.0 L 274.6 39.7 L 278.2 41.9 L 250.7 43.0 L 243.3 42.1 L 239.2 38.0 L 230.2 36.8 Z M 177.2 34.3 L 174.7 37.4 L 158.7 38.6 L 169.2 34.7 L 177.2 34.3 Z M 790.8 35.8 L 817.0 39.3 L 803.9 43.9 L 813.9 44.5 L 815.4 46.3 L 821.0 45.1 L 842.2 47.3 L 842.4 45.2 L 852.7 45.7 L 857.2 47.1 L 858.5 48.9 L 856.8 50.1 L 864.7 53.4 L 867.4 50.5 L 888.5 51.4 L 886.5 48.8 L 890.2 47.6 L 915.3 49.4 L 924.9 53.2 L 941.7 53.1 L 944.0 54.3 L 943.6 56.3 L 947.1 57.1 L 966.2 56.7 L 971.0 59.2 L 974.5 58.3 L 972.2 56.5 L 973.5 55.3 L 988.1 55.9 L 1000.0 58.4 L 1000.0 69.5 L 992.8 70.5 L 998.3 75.0 L 997.9 76.9 L 982.4 78.7 L 973.1 83.7 L 969.2 81.7 L 954.3 83.7 L 950.0 88.2 L 953.3 90.0 L 952.9 94.0 L 950.4 94.1 L 949.2 96.4 L 950.3 97.6 L 945.5 99.0 L 944.5 102.2 L 940.4 102.9 L 939.5 105.7 L 935.5 108.3 L 931.8 96.2 L 933.1 92.3 L 935.6 89.4 L 939.9 88.7 L 954.6 80.2 L 956.9 76.2 L 944.8 81.8 L 942.5 78.4 L 935.3 79.3 L 928.4 84.0 L 930.7 85.7 L 920.2 86.7 L 920.4 84.7 L 916.1 84.3 L 895.0 86.0 L 875.4 98.0 L 883.8 100.7 L 888.6 99.5 L 892.6 102.5 L 892.7 104.9 L 889.1 115.4 L 883.9 121.4 L 874.6 129.4 L 870.9 131.1 L 867.4 129.8 L 854.3 139.6 L 859.6 147.8 L 858.6 152.5 L 851.3 154.5 L 850.3 148.0 L 852.4 147.5 L 846.4 144.1 L 848.1 140.1 L 845.2 139.1 L 836.3 142.0 L 839.4 137.7 L 837.9 136.3 L 827.9 141.1 L 826.5 142.4 L 830.3 146.0 L 839.9 146.0 L 840.3 147.4 L 836.4 148.2 L 831.0 153.0 L 834.0 154.6 L 838.6 162.0 L 836.8 164.8 L 839.1 167.1 L 838.0 171.6 L 829.6 181.8 L 821.9 186.7 L 807.7 190.6 L 806.8 193.5 L 805.2 193.7 L 805.2 190.6 L 801.5 189.7 L 794.1 195.1 L 793.5 197.1 L 802.4 207.6 L 803.7 212.7 L 803.3 217.6 L 792.1 226.1 L 791.9 222.4 L 787.5 220.5 L 785.0 216.1 L 780.1 214.9 L 780.5 212.7 L 778.0 212.8 L 775.6 224.3 L 786.0 234.7 L 789.5 246.4 L 781.6 242.3 L 778.0 232.0 L 773.6 226.7 L 773.2 228.3 L 774.3 218.2 L 769.9 203.0 L 764.9 206.3 L 761.6 205.4 L 762.0 199.4 L 753.9 186.8 L 751.4 186.7 L 750.8 189.3 L 741.6 190.3 L 740.3 194.0 L 728.3 204.0 L 723.1 205.8 L 721.8 221.2 L 715.4 227.9 L 704.3 205.6 L 701.8 190.7 L 695.8 192.0 L 692.1 188.6 L 692.6 186.5 L 684.4 179.4 L 670.8 180.3 L 659.4 178.5 L 656.9 174.6 L 652.0 176.4 L 643.1 172.6 L 639.2 166.3 L 633.3 166.7 L 641.1 181.2 L 641.7 177.8 L 643.3 178.3 L 643.9 183.3 L 650.0 183.0 L 656.6 176.7 L 657.9 182.7 L 663.1 184.5 L 666.1 188.0 L 660.6 193.8 L 660.3 197.4 L 653.5 202.1 L 645.5 204.5 L 644.9 206.7 L 635.2 211.1 L 620.8 214.9 L 618.5 203.4 L 608.7 190.9 L 606.9 184.2 L 596.2 172.1 L 597.0 168.1 L 594.2 173.2 L 590.1 167.1 L 599.1 183.5 L 598.7 185.8 L 602.4 188.9 L 604.1 198.3 L 609.1 205.8 L 620.3 215.6 L 618.7 217.4 L 623.9 221.0 L 642.0 216.6 L 641.8 220.4 L 632.6 238.3 L 611.8 257.1 L 608.9 263.0 L 607.8 268.0 L 609.6 269.0 L 608.9 273.6 L 612.4 279.9 L 613.3 290.8 L 609.6 296.4 L 596.6 305.0 L 598.9 315.9 L 590.5 321.5 L 589.5 329.9 L 578.4 341.0 L 571.6 344.3 L 562.7 344.1 L 554.5 346.7 L 551.0 344.8 L 550.6 337.9 L 542.3 325.3 L 539.6 311.4 L 532.8 300.2 L 532.7 293.9 L 538.0 279.8 L 533.1 264.0 L 524.4 253.1 L 527.2 241.5 L 526.1 239.6 L 523.6 236.7 L 516.4 238.2 L 512.0 232.6 L 505.2 232.9 L 494.5 236.9 L 487.1 235.6 L 479.1 237.9 L 475.0 236.6 L 465.5 229.8 L 458.8 219.8 L 453.9 216.2 L 451.0 209.1 L 454.3 205.2 L 455.1 199.7 L 452.9 189.2 L 459.9 177.1 L 473.4 166.9 L 474.2 159.5 L 480.8 155.2 L 483.5 150.7 L 494.0 152.3 L 504.1 148.3 L 526.4 146.2 L 530.8 147.5 L 528.7 156.2 L 553.0 165.9 L 555.7 163.9 L 555.9 160.4 L 559.8 158.8 L 580.3 164.2 L 586.0 162.3 L 593.8 164.0 L 600.0 153.8 L 600.4 148.2 L 590.3 149.7 L 576.8 148.2 L 573.1 143.9 L 574.5 141.7 L 572.7 140.4 L 575.8 137.7 L 580.1 137.6 L 581.2 135.5 L 586.5 135.9 L 593.1 133.3 L 606.5 136.3 L 612.1 136.1 L 615.8 133.4 L 601.9 124.3 L 608.7 118.7 L 597.1 121.5 L 600.9 124.7 L 594.1 126.8 L 590.2 124.1 L 592.5 122.0 L 585.4 120.6 L 580.1 125.2 L 576.9 131.7 L 580.0 136.0 L 573.2 138.5 L 569.2 136.3 L 565.9 137.0 L 567.8 138.5 L 566.4 139.0 L 562.9 138.2 L 566.8 145.4 L 564.2 144.7 L 564.3 148.8 L 562.5 148.9 L 553.9 138.2 L 554.3 134.1 L 536.5 123.0 L 534.2 123.9 L 535.0 127.5 L 551.3 138.4 L 546.9 137.7 L 545.7 139.5 L 547.4 141.9 L 544.7 144.5 L 542.8 138.8 L 524.7 126.8 L 518.1 130.2 L 508.6 130.3 L 508.4 133.6 L 502.3 136.1 L 499.2 140.8 L 500.3 142.4 L 494.0 148.1 L 487.9 148.1 L 485.1 150.1 L 481.9 147.4 L 475.3 147.6 L 475.4 143.7 L 473.5 142.4 L 475.6 136.8 L 473.9 130.5 L 477.8 128.5 L 494.7 129.4 L 496.2 127.7 L 496.7 122.2 L 487.5 116.8 L 487.2 114.8 L 495.5 114.9 L 494.6 111.7 L 497.3 112.9 L 503.7 110.8 L 504.6 108.5 L 510.6 106.6 L 513.1 102.5 L 522.6 101.3 L 524.4 99.9 L 522.6 95.8 L 523.7 91.4 L 529.4 89.6 L 528.5 92.0 L 530.3 93.2 L 526.8 95.9 L 530.4 100.0 L 534.8 98.7 L 539.2 100.7 L 549.0 97.6 L 554.6 98.8 L 559.1 96.7 L 559.9 90.5 L 562.6 89.6 L 567.0 91.6 L 567.9 87.8 L 564.8 85.6 L 580.9 83.3 L 578.0 81.9 L 563.5 83.8 L 559.2 81.3 L 559.8 74.5 L 570.6 69.1 L 566.4 66.6 L 561.6 67.4 L 558.9 69.4 L 559.4 71.1 L 549.6 75.7 L 547.6 79.6 L 552.2 83.1 L 546.7 86.9 L 544.1 94.2 L 536.0 96.2 L 528.8 84.8 L 523.3 88.0 L 515.7 87.3 L 513.9 77.9 L 529.2 70.9 L 541.0 61.6 L 553.3 56.1 L 564.0 55.0 L 568.2 52.7 L 578.2 52.3 L 586.9 54.3 L 583.3 55.0 L 586.4 56.8 L 601.4 58.2 L 614.1 62.6 L 614.2 64.5 L 606.6 66.7 L 592.2 64.9 L 596.7 66.9 L 597.1 71.1 L 602.8 72.6 L 601.4 70.1 L 603.3 69.0 L 610.0 70.8 L 612.3 70.1 L 610.5 68.1 L 616.9 65.3 L 622.1 66.5 L 623.7 64.6 L 620.7 59.5 L 628.5 60.4 L 630.1 62.0 L 626.5 62.3 L 626.6 63.9 L 628.7 64.8 L 649.2 58.7 L 651.3 58.9 L 648.6 60.6 L 663.3 58.7 L 666.5 60.3 L 669.7 58.5 L 666.8 56.9 L 668.2 56.0 L 690.3 60.9 L 692.2 59.4 L 685.9 57.1 L 685.3 52.7 L 692.2 47.7 L 701.6 47.8 L 699.6 51.6 L 702.2 54.5 L 701.6 58.3 L 704.6 60.0 L 698.0 65.8 L 701.2 66.2 L 708.5 61.8 L 706.9 60.2 L 708.2 58.4 L 704.4 56.6 L 706.7 53.8 L 703.1 51.5 L 708.0 49.7 L 707.4 47.7 L 710.2 49.2 L 709.1 51.8 L 712.1 52.4 L 710.8 50.3 L 715.5 49.3 L 726.4 50.7 L 723.6 45.4 L 741.2 44.6 L 738.9 43.2 L 742.1 41.3 L 779.9 37.7 L 789.9 34.2 L 794.6 35.1 L 790.8 35.8 Z M 568.7 33.7 L 562.5 34.9 L 557.6 34.2 L 559.5 33.5 L 557.8 32.6 L 563.6 32.1 L 568.7 33.7 Z M 207.0 29.7 L 223.1 33.6 L 207.8 32.3 L 210.5 31.5 L 207.0 29.7 Z M 792.7 31.4 L 776.2 33.6 L 783.6 29.6 L 792.7 31.4 Z M 550.7 28.6 L 559.8 30.7 L 552.9 31.8 L 547.6 36.6 L 544.2 36.7 L 538.2 35.1 L 540.7 34.1 L 529.0 28.7 L 550.7 28.6 Z M 548.2 26.9 L 576.1 27.6 L 564.0 29.4 L 548.2 26.9 Z M 643.1 25.8 L 632.2 27.7 L 624.6 26.1 L 643.1 25.8 Z M 777.6 30.9 L 763.8 30.4 L 753.3 26.8 L 766.5 24.3 L 778.3 28.4 L 777.6 30.9 Z M 243.3 24.3 L 261.6 29.6 L 247.8 32.7 L 242.0 32.4 L 239.0 31.2 L 241.3 29.5 L 231.4 27.3 L 238.1 25.1 L 236.8 24.4 L 243.3 24.3 Z M 279.7 19.1 L 328.2 20.5 L 312.1 23.6 L 318.1 23.6 L 302.3 28.3 L 286.4 29.7 L 290.2 30.0 L 288.3 30.5 L 290.6 31.9 L 278.4 35.5 L 283.6 36.7 L 276.2 38.4 L 251.4 37.6 L 251.1 36.2 L 256.2 35.6 L 254.8 33.6 L 264.0 34.6 L 255.7 32.3 L 263.6 29.6 L 258.5 27.1 L 272.6 26.5 L 256.7 26.3 L 245.6 22.5 L 279.7 19.1 Z M 424.7 18.0 L 442.1 20.2 L 411.4 21.7 L 438.7 23.0 L 435.6 24.6 L 456.2 22.5 L 466.1 24.2 L 444.3 27.3 L 450.7 27.4 L 445.3 31.2 L 445.4 34.3 L 448.7 36.2 L 439.8 37.1 L 444.9 38.6 L 445.6 41.0 L 442.6 41.2 L 446.2 43.6 L 440.0 43.8 L 443.2 45.0 L 442.3 45.9 L 434.5 46.4 L 438.1 49.5 L 431.1 49.1 L 438.5 51.5 L 439.6 53.7 L 434.6 54.2 L 429.0 51.6 L 430.0 53.5 L 426.8 54.9 L 437.9 55.2 L 422.9 59.8 L 411.7 60.8 L 405.0 64.8 L 389.4 68.2 L 385.6 73.7 L 381.1 75.9 L 382.2 78.1 L 379.5 83.1 L 365.9 80.9 L 356.6 73.3 L 350.1 63.4 L 352.8 60.1 L 357.0 59.1 L 358.7 55.8 L 348.1 56.6 L 349.0 53.3 L 357.2 54.0 L 344.9 51.0 L 348.0 48.4 L 337.3 40.2 L 309.7 38.7 L 301.7 36.1 L 314.5 35.1 L 296.4 33.2 L 317.5 29.5 L 318.5 28.4 L 311.0 27.5 L 327.1 24.1 L 326.0 22.9 L 360.0 21.0 L 376.3 23.2 L 370.1 20.5 L 392.7 17.9 L 424.7 18.0 Z";

const EFF_STYLE = {
  flood:{c:"#3aa0ff", label:"Wetter / flood risk"},
  drought:{c:"#e8843d", label:"Drier / drought risk"},
  storm:{c:"#9b7fd4", label:"Storm-track shift"},
  calm:{c:"#5fc9b0", label:"Suppressed storms"}
};

function buildMap(){
  const svg = document.getElementById("impactSvg");
  const NS="http://www.w3.org/2000/svg";
  svg.innerHTML="";
  svg.setAttribute("viewBox","0 0 1000 500");
  svg.setAttribute("preserveAspectRatio","xMidYMid meet");

  const defs=document.createElementNS(NS,"defs");
  defs.innerHTML=`
    <radialGradient id="oceanG" cx="52%" cy="50%" r="75%">
      <stop offset="0%" stop-color="#0b2740"/>
      <stop offset="55%" stop-color="#081a2e"/>
      <stop offset="100%" stop-color="#040c16"/>
    </radialGradient>
    <linearGradient id="landG" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#16304b"/>
      <stop offset="100%" stop-color="#102338"/>
    </linearGradient>
    <radialGradient id="warmPool" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="rgba(232,93,61,.42)"/>
      <stop offset="60%" stop-color="rgba(232,93,61,.12)"/>
      <stop offset="100%" stop-color="rgba(232,93,61,0)"/>
    </radialGradient>
    <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation="3.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="frame"><rect x="0" y="0" width="1000" height="500"/></clipPath>`;
  svg.appendChild(defs);

  const root=document.createElementNS(NS,"g");
  root.setAttribute("clip-path","url(#frame)");
  svg.appendChild(root);

  const bg=document.createElementNS(NS,"rect");
  bg.setAttribute("width",1000); bg.setAttribute("height",500); bg.setAttribute("fill","url(#oceanG)");
  root.appendChild(bg);

  // Warm-tongue glow over the eastern equatorial Pacific (scientifically: El Niño pushes warmth east)
  const warmEllipse=document.createElementNS(NS,"ellipse");
  const [wx,wy]=lonlatToXY(-150,0);
  warmEllipse.setAttribute("cx",wx); warmEllipse.setAttribute("cy",wy);
  warmEllipse.setAttribute("rx",150); warmEllipse.setAttribute("ry",46);
  warmEllipse.setAttribute("fill","url(#warmPool)");
  root.appendChild(warmEllipse);

  // graticule
  for(let lat=-60;lat<=60;lat+=30){const y=(90-lat)/180*500;const l=document.createElementNS(NS,"line");l.setAttribute("x1",0);l.setAttribute("x2",1000);l.setAttribute("y1",y);l.setAttribute("y2",y);l.setAttribute("stroke","#0e2236");l.setAttribute("stroke-width",lat===0?1.3:0.6);if(lat===0)l.setAttribute("stroke-dasharray","2 4");root.appendChild(l);}
  for(let lon=-120;lon<=120;lon+=60){const x=(lon+180)/360*1000;const l=document.createElementNS(NS,"line");l.setAttribute("x1",x);l.setAttribute("x2",x);l.setAttribute("y1",0);l.setAttribute("y2",500);l.setAttribute("stroke","#0e2236");l.setAttribute("stroke-width",0.6);root.appendChild(l);}

  // land
  const land=document.createElementNS(NS,"path");
  land.setAttribute("d",LAND_PATH);
  land.setAttribute("fill","url(#landG)");
  land.setAttribute("stroke","#2c5a86");
  land.setAttribute("stroke-width",0.7);
  land.setAttribute("stroke-linejoin","round");
  root.appendChild(land);

  // Niño 3.4 box (5N-5S, 170W-120W)
  const [x1,y1]=lonlatToXY(-170,5); const [x2,y2]=lonlatToXY(-120,-5);
  const box=document.createElementNS(NS,"rect");
  box.setAttribute("x",x1);box.setAttribute("y",y1);box.setAttribute("width",x2-x1);box.setAttribute("height",y2-y1);
  box.setAttribute("fill","rgba(255,179,71,.10)");box.setAttribute("stroke","rgba(255,179,71,.85)");box.setAttribute("stroke-width",1.1);box.setAttribute("stroke-dasharray","4 3");
  box.setAttribute("rx","2");
  root.appendChild(box);
  const bl=document.createElementNS(NS,"text"); bl.setAttribute("x",(x1+x2)/2); bl.setAttribute("y",y1-5); bl.setAttribute("fill","#ffb347"); bl.setAttribute("font-size","9.5"); bl.setAttribute("font-family","JetBrains Mono"); bl.setAttribute("text-anchor","middle"); bl.setAttribute("letter-spacing","0.5"); bl.textContent="NIÑO 3.4"; root.appendChild(bl);

  // impact markers
  DATA.impacts.forEach((im,i)=>{
    const [x,y]=lonlatToXY(im.coord[0], im.coord[1]);
    const st=EFF_STYLE[im.effect]||EFF_STYLE.flood;
    const g=document.createElementNS(NS,"g"); g.style.cursor="pointer";
    g.setAttribute("tabindex","0"); g.setAttribute("role","button"); g.setAttribute("aria-label",im.region+": "+st.label);
    g.dataset.idx=i;

    const halo=document.createElementNS(NS,"circle");
    halo.setAttribute("cx",x);halo.setAttribute("cy",y);halo.setAttribute("r",5+im.sev*2.6);
    halo.setAttribute("fill",st.c);halo.setAttribute("opacity","0.18");halo.setAttribute("filter","url(#glow)");
    if(!reduceMotion){const an=document.createElementNS(NS,"animate");an.setAttribute("attributeName","r");an.setAttribute("values",`${5+im.sev*2.6};${9+im.sev*2.6};${5+im.sev*2.6}`);an.setAttribute("dur",`${3+i*0.22}s`);an.setAttribute("repeatCount","indefinite");halo.appendChild(an);}
    g.appendChild(halo);

    const ring=document.createElementNS(NS,"circle");
    ring.setAttribute("cx",x);ring.setAttribute("cy",y);ring.setAttribute("r",3.2+im.sev*0.7);
    ring.setAttribute("fill","none");ring.setAttribute("stroke",st.c);ring.setAttribute("stroke-width",0.8);ring.setAttribute("opacity",0.55);
    g.appendChild(ring);

    const dot=document.createElementNS(NS,"circle");
    dot.setAttribute("cx",x);dot.setAttribute("cy",y);dot.setAttribute("r",2.6+im.sev*0.6);
    dot.setAttribute("fill",st.c);dot.setAttribute("stroke","#04101e");dot.setAttribute("stroke-width",0.9);
    g.appendChild(dot);

    const pick=()=>selectImpact(i);
    g.addEventListener("click",pick);
    g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick();}});
    g.addEventListener("mouseenter",e=>showTip(e, `${im.region} — ${st.label}`));
    g.addEventListener("mousemove",moveTip);
    g.addEventListener("mouseleave",hideTip);
    root.appendChild(g);
  });

  selectImpact(0);
}

function selectImpact(i){
  const im=DATA.impacts[i]; if(!im) return;
  const st=EFF_STYLE[im.effect]||EFF_STYLE.flood;
  document.getElementById("icName").textContent=im.region;
  const eff=document.getElementById("icEff");
  eff.textContent=st.label; eff.style.background=st.c+"22"; eff.style.color=st.c;
  document.getElementById("icTxt").textContent=im.txt;
  document.getElementById("impactCard").style.borderColor=st.c+"55";
  // highlight selected marker + expose selection to assistive tech
  document.querySelectorAll('#impactSvg g[data-idx]').forEach(g=>{
    const sel = +g.dataset.idx===i;
    g.setAttribute('aria-pressed', sel ? 'true' : 'false');
    const dot=g.querySelector('circle:last-of-type');
    if(dot) dot.setAttribute('r', sel ? (3.6+(DATA.impacts[+g.dataset.idx].sev*0.7)) : (2.6+(DATA.impacts[+g.dataset.idx].sev*0.6)));
  });
}

/* tooltip helpers (shared) */
const TT=document.getElementById("tooltip");
function showTip(e,text){TT.textContent=text;TT.style.opacity="1";moveTip(e);}
function moveTip(e){const pad=14;let x=e.clientX+pad,y=e.clientY+pad;const r=TT.getBoundingClientRect();if(x+r.width>innerWidth)x=e.clientX-r.width-pad;if(y+r.height>innerHeight)y=e.clientY-r.height-pad;TT.style.left=x+"px";TT.style.top=y+"px";}
function hideTip(){TT.style.opacity="0";}
/* ============================================================================
   FORECAST ENGINE
   Damped persistence (benchmark), pure persistence, climatology — all transparent.
   Uncertainty widens with lead time AND across the boreal-spring barrier (MAM).
   ============================================================================ */
let fcChart, fcState={model:"damped"};
const LEAD = 9; // months ahead

// lag-1 autocorrelation of monthly ONI (empirical, ~0.9/mo for ENSO)
function autocorr1(vals){
  const m=vals.reduce((a,b)=>a+b,0)/vals.length;
  let num=0,den=0;
  for(let i=1;i<vals.length;i++){num+=(vals[i]-m)*(vals[i-1]-m);}
  for(let i=0;i<vals.length;i++){den+=(vals[i]-m)**2;}
  return den? num/den : 0.9;
}
// climatological ONI by calendar month (≈0 by construction, but tiny seasonal bias)
function climoByMonth(recs){
  const sum=Array(13).fill(0), cnt=Array(13).fill(0);
  recs.forEach(r=>{sum[r.m]+=r.v;cnt[r.m]++;});
  return sum.map((s,i)=>cnt[i]?s/cnt[i]:0);
}

function computeForecast(){
  const recs=DATA.oni;
  const last=recs[recs.length-1];
  const vals=recs.map(r=>r.v);
  const r1=Math.min(0.97,Math.max(0.7,autocorr1(vals.slice(-180)))); // monthly persistence
  const climo=climoByMonth(recs);
  const sd=Math.sqrt(vals.slice(-360).reduce((a,b)=>a+b*b,0)/Math.min(360,vals.length)); // ~spread

  const out=[];
  let cur=last.v, uncPrev=0;
  for(let k=1;k<=LEAD;k++){
    const mIdx=((last.m-1+k)%12)+1; // calendar month of this lead
    let mean;
    if(fcState.model==="damped"){ mean = climo[mIdx] + (cur-climo[mIdx])*r1; }
    else if(fcState.model==="persist"){ mean = cur; }
    else { mean = climo[mIdx]; } // climatology
    // base uncertainty grows ~ sqrt of lead toward the climatological spread
    let unc = sd*Math.sqrt(1-Math.pow(r1,2*k))*1.05;
    // spring predictability barrier: inflate uncertainty when target month is MAM (3,4,5)
    if(mIdx>=3&&mIdx<=5) unc*=1.45;
    // A projection that has crossed the barrier does not become MORE certain afterwards:
    // uncertainty never shrinks with lead time.
    unc=Math.max(0.12,unc,uncPrev); uncPrev=unc;
    const tFrac=+(last.y+( (last.m-1+k)+0.5)/12).toFixed(4);
    out.push({t:tFrac, m:mIdx, mean:+mean.toFixed(2), lo:+(mean-unc).toFixed(2), hi:+(mean+unc).toFixed(2)});
    cur=mean;
  }
  return out;
}

function buildForecastChart(){
  fcChart=echarts.init(document.getElementById("fcChart"),null,{renderer:"canvas"});
  drawForecast();
  window.addEventListener("resize",()=>fcChart.resize());
}
function drawForecast(){
  const recs=DATA.oni;
  const hist=recs.slice(-30); // recent context
  const fc=computeForecast();
  const last=recs[recs.length-1];

  const histData=hist.map(r=>[r.t,r.v]);
  const meanData=[[last.t,last.v]].concat(fc.map(f=>[f.t,f.mean]));
  const loData=[[last.t,last.v]].concat(fc.map(f=>[f.t,f.lo]));
  const hiData=[[last.t,last.v]].concat(fc.map(f=>[f.t,f.hi]));

  updateProbabilities(fc[0]);

  // Whole-degree y-range that contains the history, the projection and the whole band.
  const [yLo,yHi] = axisBounds(histData.concat(loData,hiData).map(d=>d[1]), -2, 3);
  // Half-year x ticks: a year label at each 1 January, "Jul" at mid-year.
  const xMin = Math.floor(hist[0].t*2)/2;
  const xMax = Math.ceil((fc[fc.length-1].t+0.05)*2)/2;

  fcChart.setOption({
    backgroundColor:"transparent",
    grid:{left:42,right:16,top:22,bottom:30},
    animationDuration:600,
    tooltip:{trigger:"axis",backgroundColor:"rgba(10,20,36,.97)",borderColor:"#162a44",
      textStyle:{color:"#e8edf4",fontFamily:"JetBrains Mono",fontSize:11.5},
      formatter:(ps)=>{
        const rel=ps.filter(p=>p.seriesName==="Observed"||p.seriesName==="Projection");
        if(!rel.length) return "";
        const t=rel[0].value[0]; const yr=Math.floor(t); const mo=Math.round((t-yr)*12-0.5);
        const mn=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Math.max(0,Math.min(11,mo))];
        let s=`<b style="font-family:Space Grotesk">${mn} ${yr}</b>`;
        rel.forEach(p=>{ const v=p.value[1]; s+=`<br/>${p.seriesName}: <b>${signed1(+v)}</b>`; });
        const f=fc.find(x=>Math.abs(x.t-t)<0.001);
        if(f) s+=`<br/><span style="color:#7d96b3">range ${f.lo>0?"+":""}${f.lo} … ${f.hi>0?"+":""}${f.hi}</span>`;
        return s;
      }},
    xAxis:{type:"value",min:xMin,max:xMax,interval:0.5,
      axisLine:{lineStyle:{color:"#1c3350"}},
      axisLabel:{color:"#5f7a9a",fontFamily:"JetBrains Mono",fontSize:10,
        formatter:(v)=>Math.abs(v-Math.round(v))<0.01 ? String(Math.round(v)) : "Jul"},
      splitLine:{show:false}},
    yAxis:{type:"value",min:yLo,max:yHi,interval:1,
      axisLine:{show:false},axisTick:{show:false},
      axisLabel:{color:"#5f7a9a",fontFamily:"JetBrains Mono",fontSize:10,formatter:(v)=>v>0?"+"+v:v},
      splitLine:{lineStyle:{color:"#0f2138"}}},
    series:[
      // Uncertainty band: ONE polygon — upper edge left-to-right, lower edge back again.
      // Do NOT rebuild this with `stack`: on two value axes ECharts stacks the x
      // dimension, which silently drew the previous stacked band off the chart.
      {name:"Uncertainty",type:"custom",silent:true,clip:true,z:2,tooltip:{show:false},
        data:[[last.t,last.v]],
        renderItem:(params,api)=>({
          type:"polygon",silent:true,
          shape:{points:hiData.map(d=>api.coord(d)).concat(loData.slice().reverse().map(d=>api.coord(d)))},
          style:{fill:"rgba(61,214,196,0.18)"}
        })},
      // observed history
      {name:"Observed",type:"line",data:histData,showSymbol:false,lineStyle:{color:"#8aa6c4",width:2},z:6},
      // projection
      {name:"Projection",type:"line",data:meanData,showSymbol:false,
        lineStyle:{color:"#3dd6c4",width:2.6,type: fcState.model==="climo"?[5,4]:"solid"},z:7,
        markLine:{silent:true,symbol:"none",data:[
          {yAxis:0.5,lineStyle:{color:"rgba(232,93,61,.35)",type:[4,4]},label:{show:true,formatter:"El Niño +0.5",color:"rgba(232,93,61,.7)",fontFamily:"JetBrains Mono",fontSize:9,position:"insideStartTop"}},
          {yAxis:-0.5,lineStyle:{color:"rgba(43,111,179,.35)",type:[4,4]},label:{show:true,formatter:"La Niña −0.5",color:"rgba(77,159,224,.7)",fontFamily:"JetBrains Mono",fontSize:9,position:"insideStartBottom"}},
          {xAxis:last.t,lineStyle:{color:"rgba(125,150,179,.3)",type:[3,3]},label:{show:true,formatter:"now",color:"#7d96b3",fontFamily:"JetBrains Mono",fontSize:10,position:"insideEndTop"}}
        ]}}
    ]
  }, true);
}

// Map projected ONI to coarse phase probabilities using a logistic spread around thresholds.
function updateProbabilities(f1){
  if(!f1) return;
  const mean=f1.mean, spread=(f1.hi-f1.lo)/2 || 0.4;
  // P(>0.5) and P(<-0.5) via normal CDF approximation
  const cdf=(x)=>0.5*(1+erf(x/Math.SQRT2));
  let pEl=1-cdf((0.5-mean)/spread);
  let pLa=cdf((-0.5-mean)/spread);
  let pNe=Math.max(0,1-pEl-pLa);
  const tot=pEl+pNe+pLa; pEl/=tot;pNe/=tot;pLa/=tot;
  setProb("El",pEl);setProb("Ne",pNe);setProb("La",pLa);
}
function setProb(id,p){
  const pct=Math.round(p*100);
  document.getElementById("p"+id).textContent=pct+"%";
  document.getElementById("f"+id).style.width=pct+"%";
}
// error function approximation (Abramowitz & Stegun 7.1.26)
function erf(x){const s=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return s*y;}

function wireForecastControls(){
  document.querySelectorAll("#fcSeg button").forEach(b=>{
    b.addEventListener("click",()=>{
      document.querySelectorAll("#fcSeg button").forEach(x=>x.setAttribute("aria-pressed","false"));
      b.setAttribute("aria-pressed","true"); fcState.model=b.dataset.fc; drawForecast();
    });
  });
}

/* ============================================================================
   SCROLL REVEALS + BOOT
   ============================================================================ */
function wireReveals(){
  const items=document.querySelectorAll(".fade");
  if(typeof IntersectionObserver==="undefined" || reduceMotion){
    items.forEach(el=>el.classList.add("in")); return;
  }
  // reveal just before an element scrolls into view; never leave anything hidden
  const obs=new IntersectionObserver((es)=>{es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("in");obs.unobserve(e.target);}});},{rootMargin:"0px 0px -8% 0px",threshold:0.01});
  items.forEach(el=>obs.observe(el));
  // safety net: if anything is still hidden after 4s (e.g. observer edge cases), show it
  setTimeout(()=>items.forEach(el=>el.classList.add("in")),4000);
}

async function boot(){
  startClock();
  try{
    await bootData();
  }catch(err){
    console.error("Data load failed:",err);
    document.getElementById("phaseSub").textContent="data unavailable — check /data files";
    return;
  }
  const last=DATA.oni[DATA.oni.length-1];
  renderStatus();
  initOcean(last.v);
  buildONIChart(); wireTimelineControls();
  buildMap();
  buildForecastChart(); wireForecastControls();
  wireReveals();
}
document.addEventListener("DOMContentLoaded",boot);
