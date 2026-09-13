# Pulse of the Pacific — a living El Niño / ENSO tracker

A self-updating, security-hardened static website that shows the live state of the
El Niño–Southern Oscillation: a breathing model of the equatorial Pacific, the full
1950–present ONI record, a real-coastline map of global impacts, an honest statistical
forecast — plus a built-out backend pipeline and an operations dashboard.

**Live pieces:** the public tracker (`/index.html`) and the system-status / admin
dashboard (`/admin.html`).

**Actual production hosting:** GitHub Pages, deployed by `.github/workflows/pages.yml`, with
`elninotracker.org` attached as a custom domain under this repo's Settings → Pages (DNS-pointed).
The Cloudflare Pages instructions in `DEPLOYMENT_GUIDE.md` describe an alternative/original
hosting path and are kept for reference, but they are **not** what's currently live — in
particular, `public/_headers` has no effect on GitHub Pages; see the note at the top of that
file for what's actually enforced.

## The four documents

| Read this | When you want to |
|---|---|
| `README.md` (this file) | Understand what this is and how it's organized |
| `DEPLOYMENT_GUIDE.md` | **Launch it** — every click and command, no experience assumed |
| `OPERATIONS_RUNBOOK.md` | **Operate & support it** — routine checks, every failure mode, incident playbooks |
| `DEVELOPER_GUIDE.md` | **Hand it off / extend it** — architecture, code tour, security model, how to add features |

## Repository map

```
pulse-of-the-pacific/
├── public/                      ← the entire deployable site (host this folder)
│   ├── index.html               ← the tracker (markup only — zero inline scripts)
│   ├── admin.html               ← operations / system-status dashboard
│   ├── _headers                 ← security headers + CSP (Cloudflare/Netlify format)
│   ├── robots.txt
│   ├── assets/
│   │   ├── style.css            ← the whole design system
│   │   ├── app.js               ← the tracker application
│   │   └── admin.js             ← the dashboard application
│   ├── vendor/
│   │   └── echarts.min.js       ← charting library, pinned & vendored (no CDN)
│   └── data/
│       ├── oni.json             ← ONI 1950→present (baseline; pipeline refreshes it)
│       ├── events.json          ← major historical events
│       ├── impacts.json         ← global teleconnection markers
│       ├── roni_compare.json    ← ONI-vs-RONI reference points
│       ├── manifest.json        ← which optional live series exist (pipeline-managed)
│       └── status.json          ← pipeline telemetry (written by every run)
├── scripts/
│   ├── update_data.py           ← THE BACKEND: fetch → validate → publish + telemetry
│   ├── build_standalone.py      ← builds dist/el-nino-tracker-standalone.html
│   ├── build_oni.py             ← (one-time) baseline builders
│   └── build_context.py
├── tests/
│   └── test_parsers.py          ← parser/validation suite; CI runs it before any data commit
├── .github/workflows/
│   └── update-data.yml          ← the schedule: tests → refresh → commit-if-changed
├── dist/                        ← generated: single-file offline demo (not deployed)
├── LICENSE                      ← MIT (code); NOAA data is public domain
└── .gitignore
```

## Architecture in one paragraph

There is deliberately **no server and no database**. The "backend" is a scheduled GitHub
Actions job that fetches NOAA's official indices, passes them through validation gates,
writes compact JSON plus a `status.json` telemetry file, and commits — which triggers the
static host to redeploy. The browser only ever fetches same-origin JSON. The "admin
section" is a read-only dashboard rendering that telemetry (gate it privately with
Cloudflare Access if you wish — see the deployment guide). This shape is *why* the site is
hard to attack: there are no credentials, sessions, or write paths exposed to the internet.
Full threat model in `DEVELOPER_GUIDE.md`.

## Quick start (2 minutes, local)

```bash
cd public
python3 -m http.server 8000     # then open http://localhost:8000
```
(Serving over HTTP matters — browsers block data `fetch()` from `file://`.
For a no-server demo, open `dist/el-nino-tracker-standalone.html` instead.)

## Verification status of this build

* **Unit:** 23/23 pipeline parser & validation tests (`python3 tests/test_parsers.py`),
  including the Fortran fixed-width regression that silently dropped La Niña weeks.
* **Browser integration:** 43/43 checks across mobile / tablet / desktop viewports,
  the admin page in both degraded and healthy states, and the standalone file from disk.
* **Failure drill:** the pipeline was executed against a blocked network — all five
  sources failed, last-good data was preserved, telemetry recorded every error, exit 0.

## Scientific ground rules (do not break these when editing)

1. The ENSO **phase** is defined by the **ONI** (±0.5 °C sustained ≥ 5 overlapping
   3-month seasons) — never by a single weekly value. The weekly Niño-3.4 number is
   shown as the "freshest pulse," clearly labelled.
2. **RONI** is NOAA's operational index (since Feb 2026); until the live feed populates,
   the RONI overlay is a labelled schematic with an explicit on-page caveat.
3. Forecasts here are transparent statistical baselines (damped persistence et al.) with
   uncertainty that widens across the boreal-spring predictability barrier — and the page
   says so, deferring to NOAA CPC / IRI / BoM for official outlooks.

*Independent educational project. Data © NOAA/CPC and partners; not an official forecast product.*
