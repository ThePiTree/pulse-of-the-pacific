/* ============================================================================
   admin.js — the operations dashboard for Pulse of the Pacific.
   Renders data/status.json (written by scripts/update_data.py) plus live
   client-side integrity checks on the served data.

   SECURITY NOTES
   - Zero inline scripts anywhere on this site; this file is loaded under a
     strict CSP (script-src 'self').
   - Everything rendered here uses textContent / createElement — status.json
     content is never interpreted as HTML, so even a compromised status file
     cannot inject markup.
   - The page is read-only telemetry about public data. If you want it private
     anyway, gate /admin.html behind Cloudflare Access (see DEPLOYMENT_GUIDE).
   ============================================================================ */
"use strict";

const $ = (id)=>document.getElementById(id);
const el = (tag, cls, text)=>{
  const n=document.createElement(tag);
  if(cls) n.className=cls;
  if(text!==undefined) n.textContent=text;
  return n;
};

const SOURCE_LABELS = {
  oni:   ["ONI",              "Oceanic Niño Index — NOAA's long-standing 3-month index"],
  roni:  ["RONI",             "Relative ONI — NOAA's official index since Feb 2026; sets the headline phase"],
  wksst: ["Weekly Niño 3.4",  "Freshest surface pulse; new value every Monday"],
  soi:   ["SOI (3-mo)",       "Southern Oscillation Index — the atmospheric side"],
  heat:  ["Upper-300 m heat", "Subsurface heat anomaly, 180°W–100°W — the fuel gauge"],
};

function relTime(iso){
  if(!iso) return "never";
  const ms = Date.now() - Date.parse(iso);
  if(isNaN(ms)) return "unknown";
  const d = ms/86400000;
  if(d < 1/24) return Math.max(1,Math.round(ms/60000)) + " min ago";
  if(d < 1)    return Math.round(d*24) + " h ago";
  return d.toFixed(d<10?1:0) + " days ago";
}

function badge(state){ // ok | fail | stale | unknown
  const b = el("span","admin-badge admin-badge-"+state, state.toUpperCase());
  return b;
}

// A series is "not advancing" when its fetch succeeds but its newest datum is older
// than the per-source limit the pipeline publishes (data_age_limit_days). Either
// NOAA stopped updating the file or our parser stopped seeing the new rows — the
// second is exactly how the SOI series froze unnoticed for months in 2026.
function notAdvancing(s){
  if(!s || typeof s.data_age_days!=="number") return false;
  const limit = (typeof s.data_age_limit_days==="number") ? s.data_age_limit_days : (s.cadence_days||35)*2+45;
  return s.data_age_days > limit;
}

function sourceState(s){
  // Precedence: FAIL (last fetch failed) > STALE (series not advancing) >
  // STALE (the last successful run is itself too old) > OK.
  if(!s) return "unknown";
  if(!s.ok) return "fail";
  if(notAdvancing(s)) return "stale";
  const age = s.updated ? (Date.now()-Date.parse(s.updated))/86400000 : Infinity;
  return age > (s.cadence_days||35)*1.5 ? "stale" : "ok";
}

async function getJSON(path){
  const r = await fetch(path, {cache:"no-store"});
  if(!r.ok) throw new Error(path+" "+r.status);
  return r.json();
}

/* ---------------- sources panel ---------------- */
function renderSources(status){
  const grid = $("sources"); grid.textContent="";
  const sources = (status && status.sources) || {};
  for(const key of Object.keys(SOURCE_LABELS)){
    const [name, desc] = SOURCE_LABELS[key];
    const s = sources[key];
    const state = s ? sourceState(s) : "unknown";
    const card = el("div","admin-card");
    const head = el("div","admin-card-head");
    head.appendChild(el("span","admin-card-name",name));
    head.appendChild(badge(state));
    card.appendChild(head);
    card.appendChild(el("div","admin-card-desc",desc));
    const rows = el("div","admin-rows");
    const row = (k,v)=>{const r=el("div","admin-row");r.appendChild(el("span","admin-k",k));r.appendChild(el("span","admin-v",v));rows.appendChild(r);};
    if(s){
      row("last success", relTime(s.updated));
      row("expected cadence", (s.cadence_days||"?")+" days");
      if(s.ok){
        row("records", String(s.records ?? "—"));
        row("latest", `${s.latest ?? "—"}  →  ${s.value>0?"+":""}${s.value ?? "—"}`);
        if(typeof s.data_age_days==="number"){
          row("newest datum", `${s.data_age_days} days old` + (notAdvancing(s) ? "  ⚠ series not advancing" : ""));
        }
      }else{
        row("last run", "failed — kept last-good data");
        const err = el("div","admin-err", s.error || "unknown error");
        card.appendChild(rows); card.appendChild(err);
        grid.appendChild(card); continue;
      }
      row("fetch time", (s.duration_ms??"—")+" ms");
    }else{
      row("status","pipeline has not reported on this source yet");
    }
    card.appendChild(rows);
    grid.appendChild(card);
  }
}

/* ---------------- integrity panel (live checks on served data) ------------ */
function integrityCard(name, ok, detail){
  const card = el("div","admin-card");
  const head = el("div","admin-card-head");
  head.appendChild(el("span","admin-card-name",name));
  head.appendChild(badge(ok ? "ok" : "fail"));
  card.appendChild(head);
  card.appendChild(el("div","admin-card-desc",detail));
  return card;
}

function renderIntegrity(oni){
  const grid = $("integrity"); grid.textContent="";
  const recs = (oni && oni.records) || [];
  // 1. record volume
  grid.appendChild(integrityCard("ONI record volume", recs.length>=800,
    `${recs.length} seasonal records on disk (expect ≥ 800 for 1950→present).`));
  // 2. time axis strictly increasing, no duplicates
  let mono = true;
  for(let i=1;i<recs.length;i++) if(recs[i].t<=recs[i-1].t){ mono=false; break; }
  grid.appendChild(integrityCard("Time axis", mono,
    mono ? "Strictly increasing — no duplicate or disordered seasons."
         : "Duplicate or out-of-order seasons detected — investigate the last data commit."));
  // 3. physical range
  const insane = recs.filter(r=>Math.abs(r.v)>6);
  grid.appendChild(integrityCard("Physical range", insane.length===0,
    insane.length===0 ? "All anomalies within ±6 °C — physically plausible."
                      : `${insane.length} values outside ±6 °C — data corruption likely.`));
  // 4. classification sanity: every labelled event is ≥5 consecutive seasons
  let runOK = true, i=0;
  while(i<recs.length){
    const c = recs[i].c;
    if(c==="E"||c==="L"){ let j=i; while(j<recs.length&&recs[j].c===c)j++; if(j-i<5){runOK=false;break;} i=j; }
    else i++;
  }
  grid.appendChild(integrityCard("Event rule (±0.5 °C × 5 seasons)", runOK,
    runOK ? "Every labelled El Niño / La Niña spans ≥ 5 overlapping seasons — matches the NOAA definition."
          : "An event shorter than 5 seasons is labelled — classifier or data problem."));
  // 5. freshness of the record itself
  const last = recs[recs.length-1];
   const ageDays = last ? (Date.now() - Date.UTC(last.y, last.m - 1, 1))/86400000 : Infinity;
  //const ageDays = last ? (Date.now() - Date.UTC(Math.floor(last.t), Math.round((last.t%1)*12), 1))/86400000 : Infinity;
  // Window: a season centred on month m is published early in month m+2, so the newest season is
  // normally 66–102 days past the 1st of its centre month. 115 leaves about two weeks of slack.
  grid.appendChild(integrityCard("Series freshness", ageDays < 115,
    last ? `Latest season on disk: ${last.s} ${last.y} (${last.v>0?"+":""}${last.v}). `
           + (ageDays<115 ? "Within the expected monthly publication window."
                          : "Older than ~3.8 months — check pipeline runs.")
         : "No records found."));
}

/* ---------------- run history ---------------- */
function renderHistory(status){
  const box = $("history"); box.textContent="";
  const hist = (status && status.history) || [];
  if(!hist.length){ box.appendChild(el("div","admin-card-desc","No pipeline runs recorded yet.")); return; }
  const strip = el("div","admin-strip");
  hist.slice(-30).forEach(h=>{
    const dot = el("span","admin-dot "+(h.fail && h.fail.length ? (h.ok? "admin-dot-part":"admin-dot-fail") : "admin-dot-ok"));
    dot.title = `${h.ts} — ${h.ok} ok` + (h.fail&&h.fail.length? `, failed: ${h.fail.join(", ")}`:"");
    strip.appendChild(dot);
  });
  box.appendChild(strip);
  const lastRun = hist[hist.length-1];
  box.appendChild(el("div","admin-card-desc",
    `Last run ${relTime(lastRun.ts)} — ${lastRun.ok}/5 sources ok`
    + (lastRun.fail && lastRun.fail.length ? ` (failed: ${lastRun.fail.join(", ")})` : "")));
}

/* ---------------- boot ---------------- */
async function boot(){
  const clock = $("nowClock");
  const tick = ()=>{ clock.textContent = new Date().toUTCString().slice(17,25)+" UTC"; };
  tick(); setInterval(tick, 1000);

  let status=null, oni=null;
  try{ oni = await getJSON("data/oni.json"); }catch(e){ /* handled below */ }
  try{ status = await getJSON("data/status.json"); }catch(e){ /* first deploy: not written yet */ }

  const banner = $("banner");
  if(!oni){
    banner.className="admin-banner admin-banner-fail";
    banner.textContent="CRITICAL: data/oni.json could not be loaded — the tracker itself will not render. Check the deploy output directory.";
  }else if(!status){
    banner.className="admin-banner admin-banner-warn";
    banner.textContent="Pipeline has not run yet — the site is serving its embedded baseline. Run the “Refresh ENSO data” workflow once from the GitHub Actions tab to activate live telemetry.";
  }else{
    const fails = Object.values(status.sources||{}).filter(s=>!s.ok).length;
    const stales = Object.entries(status.sources||{}).filter(([k,s])=>sourceState(s)==="stale").length;
    if(fails===0 && stales===0){
      banner.className="admin-banner admin-banner-ok";
      banner.textContent=`All systems normal — last pipeline run ${relTime(status.updated)} (trigger: ${status.trigger||"?"}). All 5 sources fresh.`;
    }else{
      banner.className="admin-banner admin-banner-warn";
      banner.textContent=`Degraded but serving — last run ${relTime(status.updated)}: ${fails} source(s) failed on their last attempt, ${stales} stale. The site keeps last-good data automatically; see cards below and the runbook.`;
    }
  }

  renderSources(status);
  if(oni) renderIntegrity(oni);
  renderHistory(status);
  $("genStamp").textContent = "Rendered "+new Date().toISOString().slice(0,16).replace("T"," ")+" UTC in your browser";
}
document.addEventListener("DOMContentLoaded", boot);
