#!/usr/bin/env node
/*
 * Tests for the logic inside the two browser scripts, run in plain Node - no browser,
 * no packages:
 *
 *     node tests/test_frontend.mjs        (python3 tests/run_all.py runs it too)
 *
 * public/assets/app.js and admin.js are ordinary page scripts, not modules, so the
 * functions under test are lifted out of the source text by name and evaluated on
 * their own. Most important here: the El Nino / La Nina rule exists twice - in
 * scripts/enso_rule.py for the data files and in app.js for the browser - and both
 * are held to the same frozen NOAA tables (tests/fixtures/), so they cannot drift.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), "utf8");

let PASS = 0, FAIL = 0;
function ok(name, cond, detail = "") {
  if (cond) PASS++;
  else { FAIL++; console.log(`  FAIL: ${name}` + (detail ? `  [${detail}]` : "")); }
}

/* Source text of the top-level `function NAME(...) { ... }` in a script. */
function grab(src, name) {
  const m = new RegExp(`^function ${name}\\s*\\(`, "m").exec(src);
  if (!m) throw new Error(`function ${name} not found - was it renamed?`);
  let depth = 0;
  for (let k = src.indexOf("{", m.index); k < src.length; k++) {
    if (src[k] === "{") depth++;
    else if (src[k] === "}" && --depth === 0) return src.slice(m.index, k + 1);
  }
  throw new Error(`function ${name}: unbalanced braces`);
}
function load(src, names, preamble = "", extra = "") {
  const code = `${preamble}\n${names.map(n => grab(src, n)).join("\n")}\n({${names.join(",")}${extra}})`;
  return vm.runInNewContext(code, { Math, Date, Number, String, isFinite, isNaN, parseFloat, Infinity, NaN });
}

const appSrc = read("public", "assets", "app.js");
const lead = /^const LEAD\s*=\s*(\d+)/m.exec(appSrc);
const A = load(appSrc,
  ["tenths", "classifySeq", "phaseOf", "signed1", "isoToShort", "axisBounds", "autocorr1", "climoByMonth", "computeForecast"],
  `const DATA = { oni: [] }; const fcState = { model: "damped" }; const LEAD = ${lead ? lead[1] : "NaN"};`,
  `, setOni(r){ DATA.oni = r; }, setModel(m){ fcState.model = m; }`);

/* ------------------------------------------------------------ tenths / text */
const T = (v) => A.tenths(v);
ok("tenths: ordinary values round to the nearest tenth",
   [0.44, 0.46, 0.54, 1.97, 2.46, -0.44, -0.46, -1.04, 0].map(T).join() === "4,5,5,20,25,-4,-5,-10,0");
ok("tenths: an exact half rounds UP, above and below zero",
   [0.45, 0.95, 0.05, -0.45, -0.05, -1.05].map(T).join() === [5, 10, 1, -4, 0, -10].join());
let exact = true;
for (let h = -300; h <= 300; h++) if (T(h / 100) !== Math.floor((h + 5) / 10)) exact = false;
ok("tenths: exact at every two-decimal value from -3.00 to +3.00 (same table as scripts/enso_rule.py)", exact);
ok("signed1: the number NOAA's table shows, with its sign",
   [2.46, 1.97, 0.45, -0.45, 0.95, -0.46].map(A.signed1).join(" ") === "+2.5 +2.0 +0.5 -0.4 +1.0 -0.5");
ok("signed1: zero is plain 0.0 - never '-0.0' or '+0.0'", [0, -0.04, 0.04, -0.05].map(A.signed1).join(" ") === "0.0 0.0 0.0 0.0");
ok("isoToShort: 2026-11-04 -> 4 Nov 2026", A.isoToShort("2026-11-04") === "4 Nov 2026" && A.isoToShort("2027-01-13") === "13 Jan 2027");

/* ----------------------------------------------------------------- phaseOf */
const label = (v) => A.phaseOf(v).label;
ok("phaseOf: neutral below the tabulated threshold", label(0.44) === "ENSO-neutral" && label(-0.45) === "ENSO-neutral" && label(0) === "ENSO-neutral");
ok("phaseOf: El Niño from 0.45 (tabulated 0.5), strong from 1.45 (tabulated 1.5)",
   label(0.45) === "El Niño" && label(1.44) === "El Niño" && label(1.45) === "Strong El Niño" && label(1.97) === "Strong El Niño");
ok("phaseOf: La Niña from -0.46 (tabulated -0.5), strong from -1.46 (tabulated -1.5)",
   label(-0.46) === "La Niña" && label(-1.45) === "La Niña" && label(-1.46) === "Strong La Niña");
ok("phaseOf: key and colour come with every label", ["E", "L", "N"].join() === [1, -1, 0].map(v => A.phaseOf(v).key).join()
   && [1.6, 0.6, 0, -0.6, -1.6].every(v => /^#[0-9a-f]{6}$/.test(A.phaseOf(v).color)));

/* ------------------------------------- classifySeq against NOAA's own tables */
function fixture(name) {
  return read("tests", "fixtures", name).split("\n").filter(l => l && !l.startsWith("#")).map(l => {
    const p = l.split("\t");
    return { y: +p[0], s: p[1], v: parseFloat(p[2]), table: parseFloat(p[3]), flag: p.length > 4 ? p[4] === "1" : null };
  });
}
const codes = (vals) => A.classifySeq(vals.map(v => ({ v }))).map(r => r.c);
const oni = fixture("noaa_oni_table.tsv");
const oniCodes = codes(oni.map(r => r.v));
const oniBad = oni.filter((r, k) => (oniCodes[k] !== "N") !== r.flag).map(r => `${r.s} ${r.y}`);
ok("classifySeq: reproduces NOAA's ONI episode colouring for all 920 seasons", oni.length === 920 && oniBad.length === 0, oniBad.slice(0, 6).join(", "));
ok("classifySeq: SON 1979 - JFM 1980 is an El Niño (five seasons only after rounding)",
   codes([0.34, 0.47, 0.50, 0.64, 0.62, 0.47, 0.35]).join("") === "NEEEEEN");
ok("classifySeq: four seasons are not an episode; warm and cold runs never merge",
   codes([0.6, 0.6, 0.6, 0.6]).join("") === "NNNN" && codes([0.6, 0.6, 0.6, -0.6, -0.6, -0.6]).join("") === "NNNNNN");
const roni = fixture("noaa_roni_table.tsv");
const roniCodes = codes(roni.map(r => r.v)), roniRef = codes(roni.map(r => r.table));
const roniDiff = roni.filter((r, k) => roniCodes[k] !== roniRef[k]).map(r => `${r.s} ${r.y}`);
ok("classifySeq: matches NOAA's Relative ONI table for 917 of 921 seasons - the same four exceptions as the Python rule",
   roni.length === 921 && roniDiff.join() === "FMA 1984,MAM 1984,AMJ 1984,MJJ 1984", roniDiff.join(", "));
ok("classifySeq: RONI AMJ-ASO 2026 is already a five-season El Niño", roniCodes.slice(-5).join("") === "EEEEE");
ok("every printed value agrees with NOAA's table except the ten known half-way cases",
   oni.filter(r => A.tenths(r.v) / 10 !== r.table).length === 3 && roni.filter(r => A.tenths(r.v) / 10 !== r.table).length === 7);

/* -------------------------------------------------------------- axisBounds */
ok("axisBounds: keeps the default range when the data fit inside it", A.axisBounds([-1.2, 0.3, 2.46], -3, 3).join() === "-3,3");
ok("axisBounds: widens by whole degrees before a value can touch the edge",
   A.axisBounds([2.9], -3, 3).join() === "-3,4" && A.axisBounds([-3.2, 3.9], -3, 3).join() === "-4,5");
ok("axisBounds: ignores gaps and non-numbers", A.axisBounds([null, NaN, undefined, Infinity, 1], -2, 3).join() === "-2,3");

/* ---------------------------------------------------------- computeForecast */
const real = JSON.parse(read("public", "data", "oni.json")).records;
A.setOni(real);
ok("forecast: the lead time is read from app.js", Number.isInteger(+(lead || [])[1]) && +lead[1] >= 6);
for (const model of ["damped", "persist", "climo"]) {
  A.setModel(model);
  const f = A.computeForecast();
  const half = f.map(p => (p.hi - p.lo) / 2);
  ok(`forecast (${model}): one point per month of lead, in time order`, f.length === +lead[1] && f.every((p, k) => !k || p.t > f[k - 1].t));
  ok(`forecast (${model}): the band always contains the projection`, f.every(p => p.lo <= p.mean && p.mean <= p.hi));
  ok(`forecast (${model}): uncertainty never shrinks with lead time`, half.every((h, k) => !k || h >= half[k - 1] - 0.011), half.map(h => h.toFixed(2)).join(" "));
  ok(`forecast (${model}): values are finite and plausible`, f.every(p => [p.mean, p.lo, p.hi].every(x => Number.isFinite(x) && Math.abs(x) < 8)));
}

/* ------------------------------------------------------------------- admin */
const D = load(read("public", "assets", "admin.js"), ["notAdvancing", "sourceState", "relTime"]);
const ago = (days) => new Date(Date.now() - days * 86400000).toISOString();
const src = (o) => Object.assign({ ok: true, cadence_days: 35, updated: ago(1), data_age_days: 40, data_age_limit_days: 115 }, o);
ok("admin: a healthy source is OK", D.sourceState(src({})) === "ok");
ok("admin: a failed fetch is FAIL, whatever else is true", D.sourceState(src({ ok: false, data_age_days: 400 })) === "fail");
ok("admin: a series that stopped advancing is STALE even though the fetch succeeded (the 2026 SOI freeze)",
   D.sourceState(src({ data_age_days: 300, data_age_limit_days: 120 })) === "stale");
ok("admin: a last good run older than 1.5 cadences is STALE", D.sourceState(src({ updated: ago(60) })) === "stale" && D.sourceState(src({ updated: ago(50) })) === "ok");
ok("admin: missing status is UNKNOWN", D.sourceState(null) === "unknown" && D.sourceState(undefined) === "unknown");
ok("admin: not-advancing uses the pipeline's own limit, with a fallback for old status files",
   D.notAdvancing({ data_age_days: 116, data_age_limit_days: 115 }) && !D.notAdvancing({ data_age_days: 115, data_age_limit_days: 115 })
   && D.notAdvancing({ data_age_days: 116, cadence_days: 35 }) && !D.notAdvancing({ data_age_days: 115, cadence_days: 35 })
   && !D.notAdvancing({ cadence_days: 35 }) && !D.notAdvancing(null));
ok("admin: relative times read naturally", D.relTime(null) === "never" && D.relTime("not a date") === "unknown"
   && /min ago$/.test(D.relTime(ago(0.01))) && /h ago$/.test(D.relTime(ago(0.3))) && /days ago$/.test(D.relTime(ago(3))));

console.log(`\n${PASS} passed, ${FAIL} failed`);
process.exit(FAIL ? 1 : 0);
