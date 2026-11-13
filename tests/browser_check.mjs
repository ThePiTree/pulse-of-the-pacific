#!/usr/bin/env node
/*
 * browser_check.mjs - opens every page of the site in a real (headless) Chromium at phone,
 * tablet and desktop sizes and checks what a person would see: the charts draw, the numbers
 * are filled in, nothing overflows sideways, nothing is blocked by the Content-Security-Policy,
 * and the operations page tells the truth when the pipeline is unhealthy.
 *
 * OPTIONAL. It is not part of tests/run_all.py and CI does not run it, because it needs
 * Playwright, which the project otherwise has no use for:
 *
 *     npm install --no-save playwright && npx playwright install chromium
 *     node tests/browser_check.mjs                  # checks only
 *     node tests/browser_check.mjs --shots out/     # also saves screenshots to out/
 *
 * It serves public/ itself on a local port and refuses every other network request, so it
 * needs no internet, sends nothing to analytics, and gives the same answer every run. (Web
 * fonts are therefore replaced by system fonts in the screenshots.)
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch {
  console.log("Playwright is not installed, so the browser check was not run.\n" +
              "  npm install --no-save playwright && npx playwright install chromium");
  process.exit(2);
}

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PUB = path.join(ROOT, "public");
const shotsAt = process.argv.indexOf("--shots");
const SHOTS = shotsAt > 0 ? path.resolve(process.argv[shotsAt + 1] || "browser-shots") : null;
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

let PASS = 0, FAIL = 0;
function ok(name, cond, detail = "") {
  if (cond) PASS++;
  else { FAIL++; console.log(`  FAIL: ${name}` + (detail ? `  [${String(detail).slice(0, 300)}]` : "")); }
}

/* ------------------------------------------------------------- tiny server */
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".css": "text/css",
                ".csv": "text/csv", ".md": "text/markdown; charset=utf-8", ".txt": "text/plain", ".xml": "application/xml" };
function serve(root) {
  root = path.resolve(root);
  const srv = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    if (p.endsWith("/")) p += "index.html";
    const fp = path.join(root, p);
    if (!fp.startsWith(root) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) { res.writeHead(404); res.end("not found"); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(fp)] || "application/octet-stream" });
    fs.createReadStream(fp).pipe(res);
  });
  return new Promise(r => srv.listen(0, "127.0.0.1", () => r({ base: `http://127.0.0.1:${srv.address().port}`, close: () => srv.close() })));
}

/* ----------------------------------------------------------- page plumbing */
const VIEWPORTS = [
  { name: "phone",   width: 390,  height: 844,  mobile: true },
  { name: "tablet",  width: 820,  height: 1180, mobile: true },
  { name: "desktop", width: 1440, height: 900,  mobile: false },
];
async function openPage(browser, vp, url, { offline = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile, offline });
  const problems = [], external = [];
  await ctx.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", e => window.__csp.push(`${e.violatedDirective} <- ${e.blockedURI || "inline"}`));
  });
  await ctx.route(u => u.protocol !== "file:" && u.hostname !== "127.0.0.1", r => { external.push(r.request().url()); return r.abort(); });
  const pg = await ctx.newPage();
  pg.on("pageerror", e => problems.push("script error: " + e.message));
  pg.on("console", m => { if (m.type() === "error" && !/net::ERR_|Failed to load resource/.test(m.text())) problems.push("console: " + m.text()); });
  pg.on("response", r => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  await pg.goto(url, { waitUntil: "load" });
  return { pg, ctx, problems, external };
}
/* Scroll through the page so every lazily revealed block is shown, then wait for the charts. */
async function settle(pg) {
  const h = await pg.evaluate(() => document.body.scrollHeight);
  const step = Math.round((pg.viewportSize().height || 800) * 0.7);
  for (let y = 0; y < h; y += step) { await pg.evaluate(v => scrollTo(0, v), y); await pg.waitForTimeout(60); }
  await pg.evaluate(() => { document.querySelectorAll(".fade").forEach(e => e.classList.add("in")); scrollTo(0, 0); });
  await pg.waitForTimeout(1300);
}
async function common(tag, x) {
  const sideways = await x.pg.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  ok(`${tag}: no script errors, failed requests or console errors`, x.problems.length === 0, x.problems.join(" | "));
  ok(`${tag}: nothing blocked by the Content-Security-Policy`, (await x.pg.evaluate(() => window.__csp)).length === 0,
     (await x.pg.evaluate(() => window.__csp)).join(" | "));
  ok(`${tag}: no sideways scrolling`, sideways <= 1, `${sideways}px wider than the screen`);
}
async function shot(pg, name, selector = null) {
  if (!SHOTS) return;
  const file = path.join(SHOTS, name + ".png");
  if (selector) { const el = await pg.$(selector); if (el) { await el.scrollIntoViewIfNeeded(); await pg.waitForTimeout(250); await el.screenshot({ path: file }); } }
  else await pg.screenshot({ path: file, fullPage: true });
}

/* ------------------------------------------------------ the tracker itself */
const PHASES = ["Strong El Niño", "El Niño", "ENSO-neutral", "La Niña", "Strong La Niña"];
async function checkTracker(tag, x, { standalone = false } = {}) {
  const pg = x.pg;
  await settle(pg);
  await common(tag, x);
  const t = await pg.evaluate(() => {
    const txt = id => (document.getElementById(id) || {}).textContent || "";
    const chart = id => { const c = echarts.getInstanceByDom(document.getElementById(id)); return c ? c.getOption() : null; };
    const o = chart("oniChart"), f = chart("fcChart");
    const size = id => { const r = document.querySelector(`#${id} canvas`).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
    return { phase: txt("phaseTxt"), sub: txt("phaseSub"), pulse: txt("oniVal"), pulseSub: txt("oniSeason"), trend: txt("trendVal"), hero: txt("heroPhase"),
             stamp: txt("buildStamp"), probs: ["pEl", "pNe", "pLa"].map(txt),
             oniBars: o ? o.series[0].data.length : 0, oniY: o ? [o.yAxis[0].min, o.yAxis[0].max] : null, oniSize: size("oniChart"),
             fcSeries: f ? f.series.map(s => `${s.name}:${s.type}`) : [], fcY: f ? [f.yAxis[0].min, f.yAxis[0].max] : null, fcSize: size("fcChart"),
             roni: DATA.roni.length, oniN: DATA.oni.length, weekly: DATA.wksst.length,
             lastOni: DATA.oni[DATA.oni.length - 1], lastRoni: DATA.roni[DATA.roni.length - 1] || null,
             expectPhase: phaseOf((DATA.roni[DATA.roni.length - 1] || DATA.oni[DATA.oni.length - 1]).v).label,
             impacts: document.querySelectorAll("#impactSvg circle").length };
  });
  ok(`${tag}: data loaded - ONI ${t.oniN} seasons, RONI ${t.roni}, weekly ${t.weekly}`, t.oniN > 900 && t.roni > 900 && t.weekly > 100);
  ok(`${tag}: headline phase is filled in and follows the Relative ONI`, PHASES.includes(t.phase) && t.phase === t.expectPhase, `${t.phase} vs ${t.expectPhase}`);
  ok(`${tag}: both indices are printed under the phase`, /RONI [+-]?\d\.\d/.test(t.sub) && /ONI [+-]?\d\.\d/.test(t.sub.replace(/RONI [+-]?\d\.\d/, "")), t.sub);
  ok(`${tag}: live reading, trend and hero word are filled in`, /^[+-]?\d\.\d$/.test(t.pulse) && /\d/.test(t.pulseSub) && /\d\.\d$/.test(t.trend) && /^(warming|cooling|breathing)$/.test(t.hero),
     `${t.pulse} | ${t.pulseSub} | ${t.trend} | ${t.hero}`);
  ok(`${tag}: page says when the data were refreshed`, /Data refreshed \d{4}-\d\d-\d\d \d\d:\d\d UTC/.test(t.stamp), t.stamp);
  ok(`${tag}: timeline draws one bar per season at a usable size`, t.oniBars === t.oniN && t.oniSize[0] > 250 && t.oniSize[1] > 200, `${t.oniBars} bars, ${t.oniSize}`);
  ok(`${tag}: timeline axis is in whole degrees and contains the data`, Number.isInteger(t.oniY[0]) && Number.isInteger(t.oniY[1]) && t.oniY[1] > t.lastOni.v, String(t.oniY));
  ok(`${tag}: forecast has observed line, projection and uncertainty band`,
     ["Observed:line", "Projection:line", "Uncertainty:custom"].every(s => t.fcSeries.includes(s)) && t.fcSize[0] > 250, t.fcSeries.join(", "));
  ok(`${tag}: outlook probabilities add up to 100 %`, t.probs.every(p => /^\d+%$/.test(p)) && Math.abs(t.probs.reduce((a, p) => a + parseInt(p), 0) - 100) <= 1, t.probs.join(" "));
  ok(`${tag}: impact map has its markers`, t.impacts >= 10, t.impacts);

  // The uncertainty band must actually be painted, in every forecast mode.
  for (const mode of ["damped", "persist", "climo"]) {
    await pg.click(`#fcSeg button[data-fc="${mode}"]`);
    await pg.waitForTimeout(700);
    const b = await pg.evaluate(() => {
      const chart = echarts.getInstanceByDom(document.getElementById("fcChart"));
      const f = computeForecast(), p = f[Math.floor(f.length * 0.7)];
      const cv = document.querySelector("#fcChart canvas"), c2 = cv.getContext("2d"), dpr = cv.width / cv.getBoundingClientRect().width;
      const at = (t, v) => { const q = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [t, v]); return Array.from(c2.getImageData(Math.round(q[0] * dpr), Math.round(q[1] * dpr), 1, 1).data); };
      const y = chart.getOption().yAxis[0];
      return { inUpper: at(p.t, p.mean + (p.hi - p.mean) * 0.6), inLower: at(p.t, p.mean - (p.mean - p.lo) * 0.6), band: [p.lo, p.hi], axis: [y.min, y.max] };
    });
    const teal = px => px[3] > 15 && px[1] > px[0] + 40 && px[2] > px[0] + 40;
    ok(`${tag}: forecast "${mode}" - uncertainty band is painted above and below the projection`, teal(b.inUpper) && teal(b.inLower), JSON.stringify(b));
    ok(`${tag}: forecast "${mode}" - the band fits inside the axis`, b.axis[0] <= b.band[0] && b.band[1] <= b.axis[1], JSON.stringify(b));
  }
  await pg.click('#fcSeg button[data-fc="damped"]');

  // Controls: the RONI overlay and the time-range buttons.
  await pg.click('#idxSeg button[data-idx="roni"]');
  await pg.waitForTimeout(600);
  const r = await pg.evaluate(() => { const o = echarts.getInstanceByDom(document.getElementById("oniChart")).getOption();
    return { names: o.series.map(s => s.name), points: o.series[1] ? o.series[1].data.filter(d => d[1] != null).length : 0, note: document.getElementById("roniNote").textContent }; });
  ok(`${tag}: "+ RONI" overlays NOAA's real Relative ONI series`, r.names.includes("RONI (relative)") && r.points > 900 && /official NOAA data/.test(r.note), JSON.stringify(r.names) + " " + r.points);
  await shot(pg, `${tag.replace(/\W+/g, "_")}_timeline_roni`, "#timeline .card");
  await pg.click('#rangeSeg button[data-range="8"]');
  await pg.waitForTimeout(500);
  const x8 = await pg.evaluate(() => echarts.getInstanceByDom(document.getElementById("oniChart")).getOption().xAxis[0].min);
  ok(`${tag}: "Last 8 yrs" zooms the timeline`, x8 === t.lastOni.y - 8, x8);
  await pg.click('#rangeSeg button[data-range="all"]');
  await pg.click('#idxSeg button[data-idx="oni"]');
  await common(tag + " (after using the controls)", x);

  if (!standalone) {
    const links = await pg.evaluate(() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute("href")).filter(h => !/^(https?:|mailto:|#)/.test(h)));
    ok(`${tag}: links to the data archive`, links.includes("archive/"), links.join(" "));
    const odd = x.external.filter(u => !/^https:\/\/(fonts\.googleapis\.com|fonts\.gstatic\.com|www\.googletagmanager\.com|([a-z0-9-]+\.)*google-analytics\.com)\//.test(u));
    ok(`${tag}: the only outside requests are web fonts and analytics`, odd.length === 0, odd.join(" "));
  } else {
    const odd = x.external.filter(u => !/^https:\/\/(fonts\.googleapis\.com|fonts\.gstatic\.com)\//.test(u));
    ok(`${tag}: asks the network for nothing but web fonts - no analytics, no data`, odd.length === 0, odd.join(" "));
    const abs = await pg.evaluate(() => Array.from(document.querySelectorAll("a[href]")).map(a => a.getAttribute("href")).filter(h => !/^(https?:\/\/|mailto:|#)/.test(h)));
    ok(`${tag}: every link is absolute (works from a file on disk)`, abs.length === 0, abs.join(" "));
  }
}

/* --------------------------------------------------------- operations page */
async function checkAdmin(tag, x, expect) {
  const pg = x.pg;
  await pg.waitForFunction(() => document.getElementById("genStamp").textContent.startsWith("Rendered"), null, { timeout: 8000 });
  await common(tag, x);
  const a = await pg.evaluate(() => ({
    banner: document.getElementById("banner").textContent, bannerClass: document.getElementById("banner").className,
    badges: Array.from(document.querySelectorAll("#sources .admin-badge")).map(b => b.textContent),
    integrity: Array.from(document.querySelectorAll("#integrity .admin-badge")).map(b => b.textContent),
    dots: document.querySelectorAll("#history .admin-dot").length, text: document.getElementById("sources").textContent,
    injected: document.querySelectorAll("#sources img, #sources script, #history img").length }));
  ok(`${tag}: five source cards, with the expected states`, a.badges.join(",") === expect.badges.join(","), a.badges.join(","));
  ok(`${tag}: banner says "${expect.banner}"`, a.banner.includes(expect.banner) && a.bannerClass.includes(expect.bannerClass), a.banner.slice(0, 120));
  ok(`${tag}: five integrity checks, all passing`, a.integrity.length === 5 && a.integrity.every(b => b === "OK"), a.integrity.join(","));
  ok(`${tag}: run history is drawn`, a.dots >= 1, a.dots);
  if (expect.text) for (const s of expect.text) ok(`${tag}: shows "${s}"`, a.text.includes(s), a.text.slice(0, 200));
  ok(`${tag}: text from status.json is never turned into HTML`, a.injected === 0);
}

/* ------------------------------------------------------------------- main */
const browser = await chromium.launch();
const site = await serve(PUB);
try {
  for (const vp of VIEWPORTS) {
    let x = await openPage(browser, vp, `${site.base}/index.html`);
    await checkTracker(`home/${vp.name}`, x);
    await shot(x.pg, `home_${vp.name}`);
    await x.ctx.close();

    x = await openPage(browser, vp, `${site.base}/archive/`);
    await x.pg.waitForTimeout(300);
    await common(`archive/${vp.name}`, x);
    const ar = await x.pg.evaluate(() => ({ files: Array.from(document.querySelectorAll(".arch-table a[href]")).map(a => a.getAttribute("href")),
      back: !!document.querySelector('a[href="../"]'), ld: document.querySelector('script[type="application/ld+json"]').textContent }));
    ok(`archive/${vp.name}: lists the data files and links back to the tracker`, ar.files.length >= 12 && ar.back && JSON.parse(ar.ld)["@type"] === "Dataset", ar.files.length);
    if (vp.name === "desktop") {
      for (const f of ar.files) { const res = await x.pg.request.get(`${site.base}/archive/${f}`); ok(`archive: ${f} downloads`, res.status() === 200 && (await res.body()).length > 50, res.status()); }
    }
    await shot(x.pg, `archive_${vp.name}`);
    await x.ctx.close();

    x = await openPage(browser, vp, `${site.base}/admin.html`);
    const live = JSON.parse(fs.readFileSync(path.join(PUB, "data", "status.json"), "utf8"));
    const healthy = Object.values(live.sources).every(s => s.ok) && (Date.now() - Date.parse(live.updated)) / 86400000 < 9;
    if (healthy) await checkAdmin(`operations/${vp.name}`, x, { badges: ["OK", "OK", "OK", "OK", "OK"], banner: "All systems normal", bannerClass: "admin-banner-ok" });
    else { await common(`operations/${vp.name}`, x); console.log(`  note: status.json is not all-healthy and under 9 days old, so the "healthy" expectations were skipped at ${vp.name}`); }
    await shot(x.pg, `operations_${vp.name}`);
    await x.ctx.close();

    for (const page of ["privacy/", "creator/melyssa-kimura/"]) {
      x = await openPage(browser, vp, `${site.base}/${page}`);
      await x.pg.waitForTimeout(200);
      await common(`${page}${vp.name}`, x);
      ok(`${page}${vp.name}: has a heading and a way back`, await x.pg.evaluate(() => !!document.querySelector("h1, h2") && !!document.querySelector('a[href]')));
      await x.ctx.close();
    }
  }

  /* The operations page when things are NOT fine: a copy of the site with a doctored status.json. */
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pulse-check-"));
  try {
    fs.cpSync(PUB, path.join(tmp, "public"), { recursive: true });
    const sp = path.join(tmp, "public", "data", "status.json");
    const st = JSON.parse(fs.readFileSync(sp, "utf8"));
    const now = new Date().toISOString().slice(0, 19) + "Z";
    for (const s of Object.values(st.sources)) { s.ok = true; s.updated = now; s.data_age_days = 30; s.data_age_limit_days = 115; }
    st.updated = now;
    Object.assign(st.sources.soi, { data_age_days: 320, data_age_limit_days: 120 });                       // fetch fine, series frozen
    Object.assign(st.sources.heat, { ok: false, error: 'URLError: <img src=x onerror="document.title=1"> timed out' });   // fetch failed
    st.sources.wksst.updated = new Date(Date.now() - 20 * 86400000).toISOString();                          // last success long ago
    st.history.push({ ts: now, ok: 4, fail: ["heat<script>"] });
    fs.writeFileSync(sp, JSON.stringify(st));
    const bad = await serve(path.join(tmp, "public"));
    try {
      for (const vp of [VIEWPORTS[0], VIEWPORTS[2]]) {
        const x = await openPage(browser, vp, `${bad.base}/admin.html`);
        await checkAdmin(`operations, degraded/${vp.name}`, x, { badges: ["OK", "OK", "STALE", "STALE", "FAIL"], banner: "Degraded but serving", bannerClass: "admin-banner-warn",
          text: ["series not advancing", "320 days old", "failed — kept last-good data", '<img src=x onerror="document.title=1">'] });
        ok(`operations, degraded/${vp.name}: the hostile error text did not run`, (await x.pg.title()) !== "1");
        await shot(x.pg, `operations_degraded_${vp.name}`);
        await x.ctx.close();
      }
    } finally { bad.close(); }
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }

  /* The single-file build, opened straight from disk with the network switched off. */
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "pulse-standalone-"));
  try {
    const py = spawnSync(process.platform === "win32" ? "python" : "python3", [path.join(ROOT, "scripts", "build_standalone.py"), "--out", out], { encoding: "utf8" });
    const file = path.join(out, "el-nino-tracker-standalone.html");
    ok("standalone: scripts/build_standalone.py builds the single-file copy", py.status === 0 && fs.existsSync(file), (py.stderr || py.stdout || "").slice(-200));
    if (fs.existsSync(file)) {
      for (const vp of [VIEWPORTS[0], VIEWPORTS[2]]) {
        const x = await openPage(browser, vp, pathToFileURL(file).href, { offline: true });
        await checkTracker(`standalone/${vp.name}`, x, { standalone: true });
        await shot(x.pg, `standalone_${vp.name}`);
        await x.ctx.close();
      }
    }
  } finally { fs.rmSync(out, { recursive: true, force: true }); }
} finally {
  site.close();
  await browser.close();
}
console.log(`\n${PASS} passed, ${FAIL} failed` + (SHOTS ? `   (screenshots in ${SHOTS})` : ""));
process.exit(FAIL ? 1 : 0);
