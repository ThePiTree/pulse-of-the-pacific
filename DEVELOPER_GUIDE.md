# Developer Guide — Pulse of the Pacific

Everything a developer needs to own this project: why it is shaped the way it is, a tour of
every module, the data interface, the rules that must not be broken, the security model, and
checklists for the changes you are most likely to make.

To review and launch the November 2026 update, start with `HANDOFF.md`. This guide describes
the project as it stands once that update is applied.

---

## 1. Architecture

```
 NOAA Climate Prediction Center — five public text files (no API keys, no CORS)
        │  HTTPS, fixed list of URLs
        ▼
 .github/workflows/update-data.yml   "Refresh ENSO data"   Mon + Thu 16:10 UTC
     1. tests/run_all.py --pipeline          red tests BLOCK the refresh
     2. scripts/update_data.py               THE PIPELINE
          fetch (30 s timeout, 5 MB cap, 2 retries)
          → parse (one parser per NOAA layout)
          → VALIDATION GATES (volume, strictly increasing time, physical range, no-shrink)
          → write public/data/*.json  +  status.json
          → scripts/export_archive.py → public/archive/   (CSV + revision record)
     3. commit as enso-data-bot, only if something changed
        │
        ├─► .github/workflows/pages.yml  "Deploy to GitHub Pages"
        │      on: push to main, and workflow_run of "Refresh ENSO data"
        │      uploads public/  →  https://elninotracker.org
        │
        └─► .github/workflows/data-release.yml  "Publish data release"  12th of each month
               zips public/archive/ → GitHub Releases (+ optional e-mail)

 .github/workflows/ci.yml  "Tests"  — tests/run_all.py on every push and pull request
```

**Why no server?** Every classic attack surface — authentication, sessions, injection into a
live datastore, unpatched server software — exists only if you run a server. This site has no
user data and no write path reachable from the internet. The only process that can write runs
inside GitHub's infrastructure on a schedule, reading a fixed list of URLs. Robustness comes
from the same shape: the site works from its committed files even if the pipeline never runs
again.

**The contract.** The browser never talks to NOAA. The pipeline never touches HTML, CSS or
JavaScript. The interface between them is exactly the JSON in `public/data/` (§5.4).

**The coupling that is easy to break.** A commit pushed with the workflow's own token does not
start other workflows. So `pages.yml` redeploys after a data refresh through
`workflow_run: workflows: ["Refresh ENSO data"]`. That is a match on the workflow's **name**.
Rename `update-data.yml`'s `name:` and data silently stops reaching the site.
`tests/test_release.py` fails if the two drift apart.

## 2. Repository map

| Path | What it is | Notes |
|---|---|---|
| `public/index.html` | Tracker markup | No inline scripts, so a strict CSP is possible |
| `public/admin.html` | Operations page markup | Read-only telemetry; `noindex` |
| `public/assets/app.js` | The whole tracker | One file, seven labeled parts (§4) |
| `public/assets/admin.js` | Operations page | Builds the DOM with `textContent` only (§6) |
| `public/assets/analytics.js` | Google Analytics bootstrap | Home page only |
| `public/assets/style.css` | The design system | CSS custom properties are the theme |
| `public/vendor/echarts.min.js` | ECharts 5.5.1 | Vendored and pinned: no CDN |
| `public/data/*.json` | The data interface | Written by the bot (§5.4) |
| `public/archive/` | CSV archive and its page | **Generated** — never edit by hand (§5.5) |
| `public/_headers` | Security headers | Honored by Cloudflare/Netlify only; inert on GitHub Pages |
| `scripts/update_data.py` | The pipeline | §5 |
| `scripts/enso_rule.py` | The episode rule | The one place it is written down (§5.3) |
| `scripts/export_archive.py` | Archive builder | Called by the pipeline; also runnable alone |
| `scripts/backfill_vintages.py` | Revision record from git history | Needs a full clone |
| `scripts/release_meta.py` | Release calendar and notes | Used by `data-release.yml` |
| `scripts/email_bundle.py` | Optional e-mail of the bundle | Standard-library SMTP |
| `scripts/build_standalone.py` | Single-file offline build | Writes `dist/` (git-ignored) |
| `scripts/build_context.py` | Curated context JSON | Run by hand when the context changes |
| `tests/` | Six suites, fixtures, an optional browser check | §7 |

## 3. Local development

```bash
python3 tests/run_all.py                       # everything (stdlib + Node; about 2 seconds)
cd public && python3 -m http.server 8000       # the site at http://localhost:8000
python3 scripts/update_data.py                 # a real refresh (needs internet; writes public/)
python3 scripts/export_archive.py              # rebuild public/archive/ from the current JSON
python3 scripts/backfill_vintages.py --check   # is the revision record consistent with history?
python3 scripts/build_standalone.py            # dist/el-nino-tracker-standalone.html
node --check public/assets/app.js              # syntax check after editing
```

There is no build step, no framework and no `package.json`. That is a feature. The workflows use
Python 3.12 and Node 20; everything is standard library.

If you run `update_data.py` locally it rewrites `public/data/` and `public/archive/`. Do not
commit that: the bot owns those files. `git checkout -- public/data public/archive` discards it.

## 4. Front end tour (`public/assets/app.js`, in file order)

1. **Data layer** — `loadJSON` (with the `window.__EMBEDDED__` hook the standalone build uses),
   `bootData` (reads `data/manifest.json`, then fetches only the series that exist),
   `latestPulse` (the freshest number: weekly if present, else the ONI).
   `parseONIascii` / `tryLiveONI` are an unused, optional CORS-proxy mode (`PROXY` is empty).
2. **The rule** — `tenths(v)` returns a value the way NOAA's tables print it, in whole tenths.
   `classifySeq` and `phaseOf` compare tenths, never raw floats. `signed1` prints it. These are
   the JavaScript twins of `scripts/enso_rule.py`; `tests/test_frontend.mjs` holds both to the
   same NOAA tables.
3. **Living ocean** — `initOcean`: a coarse cell grid colored by `fieldColor`, advected
   particles; pauses on `visibilitychange`, honors `prefers-reduced-motion`. It is an
   illustration driven by the current index value, not a data map.
4. **Status cells** — `renderStatus`. **Invariant:** the phase pill and the hero word come from
   a three-month index — RONI when `DATA.roni` exists, else the ONI — never from the weekly
   value, and both index values are printed. The weekly value fills the "live reading" cell with
   its exact week date (`d`). The trend compares the ONI with the ONI twelve seasons earlier.
   The "Alert status" cell is fixed text: see `HANDOFF.md` §9.
5. **Timeline** — an ECharts bar chart, colored per bar through `visualMap` (per-item
   `itemStyle` is ignored in `large` mode — a past bug). `axisBounds` picks whole-degree limits
   and widens them when the data need it. "+ RONI" overlays `data/roni.json`; if that file is
   missing, a dashed schematic is drawn and `#roniNote` says so.
6. **Impact map** — Natural Earth 110 m coastlines pre-projected into one path (`LAND_PATH`,
   equirectangular, viewBox 1000×500). `lonlatToXY` is the projection that the markers, the
   Niño-3.4 box and the path all assume. Markers are keyboard-operable buttons.
7. **Forecast** — `computeForecast`: damped persistence `climo + (cur − climo)·r₁`, AR(1)
   variance growth, ×1.45 across March–May, and uncertainty that never shrinks with lead time.
   `drawForecast` draws the band as **one `custom`-series polygon**. Do not rebuild it with
   `stack`: on two value axes ECharts stacks the x dimension, which is how the band stayed
   invisible from launch until November 2026. Probabilities come from a normal CDF around ±0.5.
   The labels ("next month", "indicative") and the disclaimer are part of the science; keep them.
8. **Boot** — defensive `matchMedia` / `IntersectionObserver` checks, scroll reveals, clock.

`public/assets/admin.js` is small: `sourceState` decides each card's badge with the precedence
**FAIL > not advancing > last success too old > OK**; `renderIntegrity` re-checks the served
`oni.json` in the visitor's browser; everything is written with `textContent`.

## 5. Pipeline tour (`scripts/`)

### 5.1 Design rules

Standard library only · fixed URL list, all `https://www.cpc.ncep.noaa.gov/` · 30 s timeout,
5 MB cap, two retries with backoff · per-series validation gates · a failure keeps the last good
file · the script always exits 0, because a failed source is telemetry in `status.json`, not a
broken build (the Actions run page shows a warning for each failed source).

### 5.2 Parsers — each one encodes a real quirk of a NOAA file

- `parse_seasonal` — `SEAS YR …` rows with a season whitelist. ONI: `SEAS YR TOTAL ANOM`
  (anomaly in the fourth column). RONI: `SEAS YR ANOM` (third column, automatic fallback).
- `parse_wksst` — `wksst9120.for` is Fortran fixed-width; a negative anomaly glues to the SST
  before it (`23.4-0.5`). Splitting on whitespace silently drops every such line, which is all
  La Niña weeks. So: regex the date, regex the floats, Niño-3.4 anomaly is the sixth float, with
  an SST sanity range. Returns the **full record**, de-duplicated by date, each with `d`.
- `parse_soi` — `soi.3m.txt` is `I4,12F6.1`. A missing value is `-999.9`, and consecutive ones
  run together (`-999.9-999.9`), as does a missing value after a real one. `_UNGLUE` separates
  them before splitting. Without it the 1951 row and the whole current-year row are dropped —
  the cause of the SOI series standing still from launch until November 2026.
- `parse_heat` — `YR MON` plus three basins; the site uses 180°W–100°W (fifth column). Missing
  flags vary, so anything with |v| > 8 is rejected.

### 5.3 The episode rule (`enso_rule.py`)

`tenths(v)` → the value as NOAA tabulates it (one decimal, an exact half rounded up), as an
integer number of tenths. `episode_codes(values)` → `E` / `L` / `N` per season: at least five
consecutive overlapping seasons with the tabulated value at or beyond ±0.5. `pending_run(values)`
→ a run at the end of the record that meets the threshold but is not yet five seasons long.

`update_data.classify` writes the codes into the JSON as `c`. `export_archive.season_labels`
spells them out for the CSV and marks a pending run. The module's docstring and
`tests/fixtures/README.md` hold the evidence. **Never apply the threshold to the raw
two-decimal value**: that relabels about 5 % of all seasons and loses the 1969–70 and 1979–80
El Niños. `tests/test_rule.py` and `tests/test_frontend.mjs` both fail if anyone does.

### 5.4 Data schemas — the interface, and a public one

The home page reads these files, and so does at least one outside project. **Add fields; never
rename or remove one.** `tests/test_site.py` checks the shape.

```jsonc
// oni.json / roni.json
{ "meta": { "index", "source", "source_url", "threshold": 0.5, "seasons": [...], "updated",
            "note", "classification" },
  "records": [ { "y": 2026, "s": "ASO", "m": 9, "t": 2026.7083, "v": 2.46, "c": "E" }, ... ] }

// wksst.json — soi.json and heat.json are the same without "d"
{ "meta": { "series", "source_url", "unit", "updated" },
  "records": [ { "t": 2026.8433, "v": 3.3, "d": "2026-11-04" }, ... ] }

// manifest.json — which series exist; the front end fetches only these
{ "updated", "series": { "oni": true, "roni": true, "wksst": true, "soi": true, "heat": true, ... } }

// status.json — telemetry rendered by admin.html
{ "updated", "trigger",
  "sources": { "<key>": { "ok", "records", "latest", "latest_t", "value", "duration_ms",
                          "data_age_days", "data_age_limit_days",
                          "error"?, "updated", "cadence_days", "url" } },
  "history": [ { "ts", "ok": 5, "fail": [] }, ... ]      // last 30 runs
}
```

- `y`, `s`, `m`: NOAA's season label and the calendar month it is centered on (`DJF 2026` is
  December 2025–February 2026, `m` = 1).
- `t`: fractional year at the **center** of the period — `year + (m − 0.5)/12` for a month or
  season, `year + day_of_year/365.25` for a week. Both sides assume this.
- `v`: the value exactly as NOAA's file gives it. `c`: `E`, `L` or `N` (§5.3).
- `data_age_days` is measured from the center of the newest period to the run;
  `data_age_limit_days` is `DATA_AGE_LIMIT_DAYS` (ONI and RONI 115, weekly 30, SOI 120, heat 90).

### 5.5 The archive (`export_archive.py`, `backfill_vintages.py`)

`export_archive.main()` runs inside its own `try` at the end of `update_data.main()`: an archive
problem never costs the site its data refresh. It reads only the JSON on disk and stamps
everything with `status.json`'s `updated`, so it is deterministic — run it twice and nothing
changes. `write_if_changed` keeps quiet weeks quiet in git.

The **revision record** (`public/archive/vintages/*.csv`) has one row per distinct value served
for a period: `first_seen_utc, <period columns>, value, revision`. `apply_vintage` adds a row
only when a period is new or its value changed. Live runs append; `backfill_vintages.py` replays
every commit that touched `public/data` through the same function, so a rebuild and the live
appends always agree. `--check` exits 1 if the files differ from history; it refuses to shrink a
file unless `--force` is given.

### 5.6 Releases and e-mail (`release_meta.py`, `email_bundle.py`, `data-release.yml`)

`release_meta.py plan` prints `TAG<TAB>TITLE` for each bundle due and writes `email`, `subject`
and `count` to `$GITHUB_OUTPUT`; `notes` prints the release notes from the archive manifest. The
workflow builds one zip of `public/archive/`, creates each release that does not exist yet, and
— only when the `SMTP_*` secrets exist — calls `email_bundle.py`. Secrets reach the script as
environment variables and nothing else; the password is never printed.

### 5.7 Adding a data series (checklist)

1. URL → `URLS`; cadence → `CADENCE_DAYS`; age limit → `DATA_AGE_LIMIT_DAYS`.
2. Write `parse_<x>` returning `[{t, v}]` sorted by time. Save a few real lines of the file as a
   fixture and **write the tests first** (`tests/test_parsers.py`).
3. Register it in `main()` through `refresh_simple`.
4. Archive: add it to `VINTAGE_SPECS` and an `export_*` call in `export_archive.py`; extend
   `tests/test_archive.py`.
5. Front end: read `DATA.<x>` after `bootData`. Operations page: one line in `SOURCE_LABELS`.
6. `python3 tests/run_all.py`, then one manual run of "Refresh ENSO data".

## 6. Security model

| Threat | Mitigation |
|---|---|
| Script injection (XSS) | CSP `script-src 'self'` (plus the analytics host on the home page only); **no inline script and no inline event handler anywhere**; `admin.js` writes with `createElement` / `textContent`; chart tooltips are built from numbers and whitelisted season names. `tests/test_site.py` enforces all of it |
| Data poisoning through NOAA | Fixed HTTPS URL list; validation gates on volume, order and physical range; the no-shrink gate; a failure keeps the last good file |
| Text from a remote file reaching logs or pages | Error text is collapsed to one bounded line (`err_text`) before it is stored, printed or shown |
| Supply chain | No third-party Python or JavaScript packages at run time; ECharts is vendored and pinned; workflows use only GitHub's own `actions/*` at pinned major versions |
| Workflow abuse | Each workflow asks for the minimum: Tests reads; refresh and release have `contents: write`; only the deploy job has `pages: write`. User input to `workflow_dispatch` is passed through environment variables, never interpolated into shell |
| Mailbox credentials | Only if the owner opts in. Held as Actions secrets, used by a standard-library script, never echoed; an app password, not the account password |
| Clickjacking, MIME sniffing | `public/_headers` sets `frame-ancestors`, `X-Frame-Options`, `nosniff` — **but GitHub Pages does not serve it.** Only the meta-tag CSP is in force today |
| Operations page | Nothing to operate: read-only telemetry. It is public and `noindex`; gate it at a proxy if that matters |
| Denial of service | Static files on GitHub's CDN |

**The standing rule: never add an inline `<script>` or an `on…=` attribute to any page.** New
code goes in `assets/*.js`, or the CSP blocks it.

## 7. Testing

`python3 tests/run_all.py` runs six suites (558 checks at the time of writing):

| Suite | Guards |
|---|---|
| `test_parsers.py` | The five parsers on fixtures in NOAA's real layouts, validation gates, labels, error text |
| `test_rule.py` | The episode rule against NOAA's published tables (`tests/fixtures/`) |
| `test_archive.py` | Archive functions, plus four full pipeline runs in a temporary directory with a controlled clock: normal, a revision, a truncated download, a total outage; and the backfill in a temporary git repository |
| `test_release.py` | Release calendar for every month, trigger and cadence; the e-mail message; cross-checks between the four workflow files |
| `test_site.py` | Every page: CSP, no inline script or handler, every local link and anchor, sitemap, the shape of the data files, the archive's internal consistency |
| `test_frontend.mjs` | The logic in `app.js` and `admin.js`, lifted out by function name and run in plain Node |

`run_all.py --pipeline` runs the first three. The scheduled refresh runs that subset before it
fetches anything. It deliberately does not run the site checks: a typo in a page should turn the
push check red, not stop the data from updating.

`node tests/browser_check.mjs` is optional and needs Playwright
(`npm install --no-save playwright && npx playwright install chromium`). It opens every page in
Chromium at three widths with all outside requests refused, and checks what a visitor would see,
including the operations page against a doctored `status.json` and the single-file build offline.

When you fix a bug, add the test that would have caught it. Both of the worst bugs so far — the
weekly parser dropping La Niña weeks, the SOI parser dropping the current year — passed every
test that existed, because no fixture used the real file layout.

## 8. Performance and accessibility

About 100 KB of HTML, CSS and application JavaScript for the home page, 1 MB of vendored
ECharts (cacheable), and roughly 240 KB of JSON once the weekly file holds NOAA's full record
(far less when compressed in transit).
The ocean canvas pauses when hidden and honors reduced motion. Accessibility: skip link, labeled
charts, keyboard-operable map markers with `aria-pressed`, visible focus rings, semantic
landmarks. Tested without sideways scrolling at 390, 820 and 1440 px.

## 9. Ideas, in rough order of value

1. Shade official episodes on the timeline using `c`, and add moderate / very strong tiers.
2. Make the "Alert status" cell data-driven, or remove it.
3. A heat-content panel: `heat.json` already flows; it leads the surface by months.
4. Resolve exact-half values in the episode rule by computing the ONI from NOAA's monthly file.
5. NOAA's official probabilities beside the in-house projection.
6. A real sea-surface-temperature layer under the impact map.
