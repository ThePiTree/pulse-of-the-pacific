# Pulse of the Pacific — a living El Niño / ENSO tracker

A self-updating static website, live at **https://elninotracker.org**, that shows the state of
the El Niño–Southern Oscillation: a breathing model of the equatorial Pacific, the full
1950–present record of NOAA's indices, a map of global impacts, an honest statistical
projection — plus a public **data archive**, an operations page, and the scheduled pipeline
that keeps all of it current.

**Hosting:** GitHub Pages, deployed by `.github/workflows/pages.yml`, with `elninotracker.org`
attached as a custom domain under Settings → Pages. `DEPLOYMENT_GUIDE.md` also describes
Cloudflare Pages, the original hosting plan; it is kept for reference and is **not** what is
live. In particular `public/_headers` has no effect on GitHub Pages — see the note at the top of
that file.

## The documents

| Read this | When you want to |
|---|---|
| `HANDOFF.md` | **Review and launch the November 2026 update** — what changed, why, and the exact steps |
| `README.md` (this file) | Understand what this is and how it is organized |
| `DEVELOPER_GUIDE.md` | **Work on the code** — architecture, every module, data schemas, invariants, testing |
| `OPERATIONS_RUNBOOK.md` | **Operate it** — the weekly check, every failure state, incident playbooks |
| `DATA_ARCHIVE.md` | **Use the data** — what is archived, CSV downloads, release bundles, e-mail delivery, research use, citation |
| `DEPLOYMENT_GUIDE.md` | Set the project up from nothing — every click, no experience assumed |

## Repository map

```
pulse-of-the-pacific/
├── public/                        ← the entire deployed site (GitHub Pages serves this folder)
│   ├── index.html                 ← the tracker (markup only — no inline scripts)
│   ├── admin.html                 ← operations / system-status page (read-only, noindex)
│   ├── privacy/ · creator/        ← static pages
│   ├── archive/                   ← GENERATED on every refresh: CSV archive + its page
│   │   ├── enso_monthly_merged.csv, oni.csv, roni.csv, nino34_weekly.csv, …
│   │   ├── vintages/*.csv         ← the revision record (what NOAA changed, and when)
│   │   ├── pipeline_runs.csv, manifest.json, README_DATA.md, index.html
│   ├── assets/
│   │   ├── style.css              ← the whole design system
│   │   ├── app.js                 ← the tracker
│   │   ├── admin.js               ← the operations page
│   │   └── analytics.js           ← Google Analytics bootstrap (home page only)
│   ├── vendor/echarts.min.js      ← charting library, pinned and vendored (no CDN)
│   ├── data/                      ← WRITTEN BY THE BOT — the interface between pipeline and pages
│   │   ├── oni.json, roni.json    ← seasonal indices, 1950 → present
│   │   ├── wksst.json, soi.json, heat.json
│   │   ├── events.json, impacts.json, roni_compare.json   ← curated context (static)
│   │   ├── manifest.json          ← which series exist
│   │   └── status.json            ← pipeline telemetry, read by admin.html
│   ├── _headers                   ← security headers for hosts that honor them (not GitHub Pages)
│   ├── robots.txt · sitemap.xml
├── scripts/
│   ├── update_data.py             ← THE PIPELINE: fetch → parse → validate → publish + telemetry
│   ├── enso_rule.py               ← the El Niño / La Niña episode rule (one place only)
│   ├── export_archive.py          ← builds public/archive/ from the JSON (runs inside the pipeline)
│   ├── backfill_vintages.py       ← rebuilds the revision record from git history
│   ├── release_meta.py            ← which release bundles are due; release notes
│   ├── email_bundle.py            ← optional: e-mail the bundle (standard library SMTP)
│   ├── build_standalone.py        ← builds a single-file offline copy into dist/
│   └── build_context.py           ← regenerates the curated context JSON
├── tests/
│   ├── run_all.py                 ← runs every suite (`--pipeline` = the refresh gate)
│   ├── test_parsers.py · test_rule.py · test_archive.py · test_release.py · test_site.py
│   ├── test_frontend.mjs          ← logic inside app.js / admin.js (Node, no packages)
│   ├── browser_check.mjs          ← optional real-browser check (needs Playwright)
│   └── fixtures/                  ← NOAA's published tables, frozen as test data
├── .github/workflows/
│   ├── update-data.yml            ← "Refresh ENSO data": Mon + Thu, tests → refresh → commit
│   ├── pages.yml                  ← "Deploy to GitHub Pages": on push and after each refresh
│   ├── data-release.yml           ← "Publish data release": monthly bundles, optional e-mail
│   └── ci.yml                     ← "Tests": every push and pull request
├── LICENSE                        ← MIT (code). NOAA data is in the public domain
└── .gitignore
```

## Architecture in one paragraph

There is deliberately **no server and no database**. The "backend" is a scheduled GitHub
Actions job that fetches five public NOAA files, passes them through validation gates, writes
compact JSON, a `status.json` telemetry file and the CSV archive, and commits. Because a commit
made by a workflow does not trigger other workflows, the Pages deployment listens for that
job's completion by name (`workflow_run` on "Refresh ENSO data" — do not rename it). The browser
only ever fetches same-origin files. The operations page is a read-only rendering of the
telemetry. This shape is why the site is hard to attack: no credentials, sessions or write
paths are exposed to the internet. Full threat model in `DEVELOPER_GUIDE.md` §6.

## Quick start (2 minutes, local)

```bash
python3 tests/run_all.py                  # every test suite; no packages to install
cd public && python3 -m http.server 8000  # then open http://localhost:8000
```

Serve over HTTP — browsers block data `fetch()` from `file://`. For a no-server copy, run
`python3 scripts/build_standalone.py` and open `dist/el-nino-tracker-standalone.html`.

## Verification status (November 2026)

- **Automated:** 558 checks in six suites (`python3 tests/run_all.py`): the five NOAA parsers
  against real-layout fixtures, the episode rule against NOAA's published tables, the archive
  through four simulated pipeline runs, the release calendar, every page's markup and links, and
  the logic inside both browser scripts.
- **Browser:** 230 checks in real Chromium at phone, tablet and desktop widths
  (`node tests/browser_check.mjs`), including the operations page in a degraded state and the
  single-file build opened offline.
- **Failure behavior:** a truncated download is refused, a total outage keeps every last-good
  file and still exits 0, and a hostile string in `status.json` is shown as text.
- **Not covered by any of the above:** the live interaction with NOAA's servers and with GitHub
  itself. `HANDOFF.md` §7 lists what the first live run after a change must show.

## Scientific ground rules (do not break these when editing)

1. The ENSO **phase** comes from a three-month index, never from a single weekly value. Since
   February 2026 NOAA's official index is the **Relative ONI (RONI)**, so the headline follows
   RONI when its feed is present and the ONI otherwise, and prints both. The weekly Niño-3.4
   number is shown separately as the freshest reading.
2. An El Niño or La Niña **episode** is at least five consecutive overlapping seasons at or
   beyond ±0.5 °C, with the threshold applied to the value **rounded to one decimal** — the way
   NOAA's own tables are colored. The rule lives in `scripts/enso_rule.py` (and once more in
   `app.js`); both are tested against NOAA's tables. Do not replace it with `value >= 0.5`.
3. Values are shown as NOAA publishes them. The archive keeps NOAA's two decimals and records
   every later revision; nothing is smoothed, filled or adjusted.
4. The projection is a transparent statistical baseline (damped persistence and two reference
   models) whose uncertainty widens across the boreal-spring barrier and never narrows with
   lead time. The page says so and defers to NOAA CPC, IRI and BoM for official outlooks.

*Independent educational project. Data: NOAA Climate Prediction Center and partners (public
domain). Not an official forecast product.*
