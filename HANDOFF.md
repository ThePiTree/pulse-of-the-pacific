# El Niño Tracker — Developer Handoff Guide

Prepared 12 November 2026 (UTC) · for the developer who will review and launch this update of
**elninotracker.org** (repository `ThePiTree/pulse-of-the-pacific`).

**Nothing in this package is live yet.** It is a tested set of changes prepared against commit
`fc4eb32` of the repository (the data refresh of 10 November 2026). It reaches the public site
only when you apply it, review it and push.

---

## 1. Read this first

The live site works and has refreshed its data on every scheduled Monday and Thursday since
17 August 2026 (25 schedule slots, 26 data commits, no gaps). This update does three things:

1. **Fixes defects found in a full audit** — one data series frozen since launch, an event rule
   that disagreed with NOAA's own tables, a forecast band that never drew, and smaller items.
2. **Adds a public data archive** at `/archive/` — every series as CSV, a record of how NOAA
   revises values, optional dated release bundles and optional e-mail delivery.
3. **Adds the tests and documentation** needed to keep it correct: 558 automated checks in six
   suites, a browser check, and a check that runs on every push.

What you need to do, in short:

1. Apply `changes.patch` on a branch, rebuild the archive with two commands, run the tests.
2. Review (section 5 lists the behavior changes that deserve a conscious yes).
3. Merge, start one data refresh by hand, and tick off the checklist in section 7.

Allow about an hour, most of it reading.

**What could not be checked from where this was prepared:** the live website, the repository's
Actions pages, NOAA's servers, a real e-mail send and a real GitHub release were all out of reach
for network reasons. Everything else was run. Section 10 says exactly what was and was not
verified; the first data refresh after launch is the real end-to-end test, and section 7 tells
you what it must show.

## 2. How the pieces fit

```
 NOAA Climate Prediction Center — five public text files
        │  HTTPS, fixed list of URLs
        ▼
 "Refresh ENSO data"  (.github/workflows/update-data.yml · Mon + Thu 16:10 UTC)
   1. tests/run_all.py --pipeline      a red test stops the refresh
   2. scripts/update_data.py           fetch → parse → validate → public/data/*.json + status.json
        └─ scripts/export_archive.py   → public/archive/  (CSV, revision record, README, page)   NEW
   3. commit as enso-data-bot, only if something changed
        │
        ├──► "Deploy to GitHub Pages"  (pages.yml, started by workflow_run on the name above)
        │        └─► elninotracker.org   index.html · admin.html · archive/ · privacy/ · creator/
        │
        └──► "Publish data release"  (data-release.yml · 12th of each month)                     NEW
                 └─► GitHub Releases: data-YYYY-MM, data-YYYY-Qn, data-YYYY-annual  (+ optional e-mail)

 "Tests"  (ci.yml · every push and pull request) — runs tests/run_all.py; reads only            NEW
```

There is no server and no database. The browser only ever reads same-origin files. The only
process that can write is the scheduled job inside GitHub Actions.

Two couplings to know before you touch anything:

- **Do not rename the workflow "Refresh ENSO data".** A commit made by a workflow does not start
  other workflows, so `pages.yml` redeploys through `workflow_run`, keyed on that exact name. A
  rename silently stops data from reaching the site. `tests/test_release.py` checks the pair.
- **`public/data/*.json` is a public interface.** The home page reads it, and at least one
  outside project of the owner's reads the ONI file. Add fields; do not rename or remove them.

## 3. What is in the package

| Item | What it is | What to do with it |
|---|---|---|
| `HANDOFF.md` | This guide | Read it |
| `changes.patch` | Every source change as one git patch against `fc4eb32` (36 files: 20 new, 15 changed, 1 removed) | Apply it — section 6 |
| `changed-files/` | The same changes as plain files in repository layout, plus `DELETED.txt` | Fallback if you would rather copy files than apply a patch |
| `full-project-preview/` | The whole project with the changes applied, including data and a generated archive | Read it, or preview the site locally. **Do not upload it:** its data is a snapshot from 10 November and would overwrite newer data |
| `verification/` | Logs and screenshots from every check listed in section 10 | Evidence; compare with your own runs |
| `extras/el-nino-tracker-standalone.html` | The tracker as one offline file, data as of 10 November 2026 | Optional: open it by double-click for a quick look |

The patch deliberately contains **no data and no generated archive**. Data belongs to the bot
and moves twice a week; the archive is rebuilt from whatever data and history your clone has.

Documentation inside the project, all updated for this release:

| File | Use it to |
|---|---|
| `README.md` | Get oriented: what the project is, the repository map |
| `DEVELOPER_GUIDE.md` | Understand the code: architecture, every module, data schemas, invariants, testing |
| `OPERATIONS_RUNBOOK.md` | Operate it: the weekly check and a playbook for every failure state |
| `DATA_ARCHIVE.md` | Use and deliver the data: files, releases, e-mail setup, research use |
| `DEPLOYMENT_GUIDE.md` | First-time setup from zero (written for a beginner; mostly not needed here) |
| `public/archive/README_DATA.md` | The data dictionary that ships with the CSV files (generated) |
| `tests/fixtures/README.md` | The evidence behind the event rule |

## 4. What changed, and why

### 4.1 Data pipeline (`scripts/update_data.py`, new `scripts/enso_rule.py`)

| Change | Why |
|---|---|
| **SOI parser fixed.** A missing value (`-999.9`) is glued to its neighbor in NOAA's fixed-width file; the parser now separates them. | The SOI series has been frozen at December 2025 on the live site since launch: the parser silently dropped the 1951 row and the whole current-year row. Fetches "succeeded", so nothing flagged it. |
| **Weekly Niño-3.4 keeps NOAA's full record** (1990 onward, not the last ~10 years), de-duplicated, with the exact week date in a new `d` field. | The archive needs the whole series; dates rebuilt from a fractional year were off by a day in one leap-year case. |
| **El Niño / La Niña rule corrected** and moved into one module, `enso_rule.py`. The ±0.5 °C threshold is applied to the value rounded to one decimal, as NOAA's tables do. | See section 5.2. The old rule mislabeled about 5 % of seasons and missed whole episodes. |
| **No-shrink gate:** a refresh that would shorten a series by more than two records is refused and the last good file kept. | A truncated download must never replace a complete record. |
| **"Not advancing" telemetry:** `status.json` gains `data_age_days`, `data_age_limit_days`, `latest_t`, and readable `latest` labels (`Sep 2026`, `week of 2026-11-04`). | Lets the operations page catch a series that stops moving while its fetches still succeed — the SOI failure mode. |
| Source label no longer says "ERSSTv5"; error text is one bounded line; failed sources and a failed archive export raise a warning on the Actions run page. | NOAA's ONI is ERSSTv6-based since 2026; warnings were only visible on the operations page. |

### 4.2 Data archive (new)

| Piece | What it does |
|---|---|
| `scripts/export_archive.py` | Runs at the end of every refresh. Writes `public/archive/`: one CSV per series, `enso_monthly_merged.csv` (everything on one monthly axis), the revision record, `pipeline_runs.csv`, `README_DATA.md`, `manifest.json` and the `/archive/` page. Output depends only on the data, never on the clock, so re-running it changes nothing. |
| `public/archive/vintages/*.csv` | The **revision record**: one row for every distinct value the site has served for a period, for all five series. A period with more than one row was revised by NOAA. Rebuilt from git history, it starts 17 August 2026 and currently holds 3,849 rows; 11 periods have been revised so far. |
| `scripts/backfill_vintages.py` | Rebuilds the revision record from the repository's history. `--check` verifies the files against history; `--force` rebuilds over existing files. Needs a full (not shallow) clone. |

### 4.3 Releases and e-mail (new, optional)

| Piece | What it does |
|---|---|
| `.github/workflows/data-release.yml` | On the 12th of each month publishes the archive as a GitHub Release (`data-YYYY-MM`); in Jan/Apr/Jul/Oct also the quarter just ended (`data-YYYY-Qn`); in January also the year just ended (`data-YYYY-annual`). Existing tags are never overwritten. |
| `scripts/release_meta.py` | All the calendar logic, unit-tested for every month. |
| `scripts/email_bundle.py` | E-mails the zip through the owner's own mailbox, standard library only. Runs only if three repository secrets exist; otherwise the step is skipped. |

### 4.4 The public page (`public/index.html`, `assets/app.js`, `assets/style.css`)

| Change | Why |
|---|---|
| Headline phase follows the **Relative ONI** when its feed is present, and prints both indices (`ASO 2026 · RONI +2.0 · ONI +2.5`). | RONI is NOAA's official index since February 2026. See section 5.1. |
| Index values are printed the way NOAA's tables print them; phase thresholds use the same one-decimal value. | A season could read "+0.5 °C" and "ENSO-neutral" in the same tooltip. |
| **Forecast uncertainty band now draws.** It is a single polygon instead of two stacked series. | The band has never been visible: with two value axes ECharts stacked the wrong dimension. |
| Chart axes use whole degrees and widen when the data need it; forecast uncertainty never shrinks with lead time; half-year ticks on the forecast. | The fixed ±2.8 axis could not hold a record event (the ONI is +2.46 now). |
| "Download this data" card, footer link, sitemap entry for `/archive/`; exact week date under the live reading; timeline intro no longer calls the ONI "the official" index. | New archive; accuracy. |
| Missing `</head>` restored in `index.html`. | Absent since the first upload; browsers recover, validators do not. |

### 4.5 Operations page (`public/admin.html`, `assets/admin.js`)

A source is now `STALE` when its last success is too old **or** when its newest value is older
than the pipeline's limit for that source. Each card shows a "newest datum" age. The freshness
window for the ONI record is 115 days. Labels reflect RONI's status; the footer credits the data
correctly and links back to the tracker on phones.

### 4.6 Tests and tooling

| Piece | What it does |
|---|---|
| `tests/run_all.py` | Runs every suite; `--pipeline` runs the three that guard the data refresh. |
| `tests/test_parsers.py` (60 checks) | The five NOAA parsers with real-layout fixtures, validation gates, telemetry. |
| `tests/test_rule.py` (36) | The event rule against NOAA's two published tables, frozen in `tests/fixtures/`. |
| `tests/test_archive.py` (97) | The archive, plus four simulated pipeline runs: normal, a revision, a truncated download, a total outage. |
| `tests/test_release.py` (58) | Release calendar, the e-mail message, and cross-checks between the four workflow files. |
| `tests/test_site.py` (268) | Every page: CSP, no inline script, every link and anchor, sitemap, data shape, archive consistency. |
| `tests/test_frontend.mjs` (39) | The logic inside `app.js` and `admin.js`, in plain Node. Holds the JavaScript copy of the event rule to the same NOAA tables as the Python one. |
| `tests/browser_check.mjs` (optional, 230) | Real Chromium at phone, tablet and desktop sizes. Needs Playwright; not part of CI. |
| `.github/workflows/ci.yml` | "Tests": runs `run_all.py` on every push and pull request. Read-only. |
| `.github/workflows/update-data.yml` | Test gate is now `run_all.py --pipeline`; the commit step still commits the data if the archive folder is missing; the comment describes GitHub Pages, not the original host. |
| `scripts/build_standalone.py` | Rewritten: strips analytics and the CSP from the offline copy, makes links absolute, fails loudly if the page shell changes, `--out DIR`. |
| `.gitignore` | New. Ignores `__pycache__/`, `dist/`, editor folders. |
| Removed: `scripts/build_oni.py`, `dist/el-nino-tracker-standalone.html` | The first held a hand-typed baseline table that was wrong for 2025–26; the second is a build artifact that had gone stale in the repository. |

## 5. Decisions to sign off

These change what visitors or data users see. Each is deliberate; each deserves a conscious yes.

### 5.1 The headline phase follows RONI, not ONI

Today both agree on "Strong El Niño" (RONI +1.97, ONI +2.46), so nothing visible changes at
launch. They can disagree: RONI removes the tropics-wide warming trend, so warm events read
cooler and cool events stronger. Last winter (2025–26) the Relative ONI recorded a La Niña while
the ONI did not stay below −0.5 long enough to count as one.
The page prints both numbers and falls back to the ONI if the RONI file is ever missing.

### 5.2 The El Niño / La Niña labels change for about 5 % of seasons

NOAA's data files carry two decimals; NOAA's published tables show one, and color episodes by
the one-decimal value. The project had applied ±0.5 to the two-decimal value. Checked against
NOAA's tables on 12 November 2026:

| | ONI | Relative ONI |
|---|---|---|
| Seasons relabeled by the fix | 42 of 921 | 48 of 921 |
| Episodes the old rule missed entirely | La Niña AMJ–SON 1954 · El Niño ASO 1969–DJF 1970 · El Niño SON 1979–JFM 1980 | El Niño NDJ 1958–MAM 1959 · ASO 1969–DJF 1970 · SON 1979–JFM 1980 · the current one, AMJ–ASO 2026 |
| Agreement with NOAA's table after the fix | all 920 seasons NOAA listed | 917 of 921 |

The four remaining differences are FMA–MJJ 1984 in the Relative ONI, and they come from a single
value that NOAA's file gives as −0.45 and NOAA's table prints as −0.5. `tests/fixtures/README.md`
has the full evidence. The home page does not shade episodes, so visitors see no change; the
change shows in the `c` field of `oni.json` / `roni.json` and in the archive's
`event_classification` columns.

### 5.3 Data files that outside readers may notice

| File | Change at the first refresh after launch |
|---|---|
| `data/soi.json` | Jumps from December 2025 to the current month: about 20 more records (888 → roughly 908) |
| `data/wksst.json` | Grows from 520 records to NOAA's full record of roughly 1,920; each record gains `d` (ISO date). Roughly 13 KB → 85 KB before compression |
| `data/oni.json`, `data/roni.json` | `c` changes for the seasons in 5.2; `meta.source` text changes; `meta.classification` is added |
| `data/status.json` | Each source gains `data_age_days`, `data_age_limit_days`, `latest_t`; `latest` becomes a readable label |

All additions; nothing renamed or removed. Until that first refresh, the JSON still carries the
old labels while the archive already carries the new ones (the archive computes them from the
values).

### 5.4 New public surface

- `/archive/` and its files become public and are listed in the sitemap.
- The Releases tab of the repository starts filling: the first scheduled bundle on the 12th of
  the month after launch, or sooner if you run "Publish data release" by hand.
- A "Tests" check appears on every push and pull request. It reports; it does **not** block
  `pages.yml`, which deploys every push to `main`. Look at the check before merging.

## 6. Launch steps

You need git, Python 3 and (for one test suite) Node.js 18 or newer. The workflows use Python
3.12 and Node 20; everything here was run on Python 3.13 and Node 22. There is nothing to
install: the project has no dependencies.

1. **Get a full clone and a branch.** A shallow clone cannot rebuild the revision record.

   ```bash
   git clone https://github.com/ThePiTree/pulse-of-the-pacific.git
   cd pulse-of-the-pacific
   git checkout -b release-2026-11
   ```

2. **Apply the changes.** `main` will have moved past `fc4eb32` because the bot commits data
   twice a week. That is expected: the patch touches no data file, so it still applies.

   ```bash
   git apply --check /path/to/changes.patch      # prints nothing if it will apply cleanly
   git apply /path/to/changes.patch
   git rm -q dist/el-nino-tracker-standalone.html
   ```

   If `--check` reports a conflict, someone changed one of the same source files after
   10 November. Use `git apply --3way` and resolve, or copy from `changed-files/` and compare
   by hand. If you copy files instead of applying the patch, also delete the two paths named in
   `changed-files/DELETED.txt`.

3. **Build the archive from this clone's own data and history.**

   ```bash
   python3 scripts/backfill_vintages.py     # revision record, replayed from git history
   python3 scripts/export_archive.py        # CSV files, README, manifest, /archive/ page
   ```

   Expect a line per vintage file, then one summary line such as
   `archive: oni=921 roni=921 weekly=520 soi=888 heat=574 …`. Weekly 520 and SOI 888 are
   correct at this point: they grow at the first live refresh.

4. **Run the tests.**

   ```bash
   python3 tests/run_all.py
   ```

   Expect `ALL SUITES PASSED - 558 checks in 6 suite(s)`. Counts can differ by a few in
   `test_site.py` if pages have changed; a failure names the exact check. If Node.js is absent
   the last suite is reported as skipped — install Node and run again before trusting a release.

5. **Look at it.**

   ```bash
   cd public && python3 -m http.server 8000
   ```

   Open `http://localhost:8000/`, `/archive/` and `/admin.html`. Check the items in the first
   block of section 7. Optional, for the full browser check:

   ```bash
   npm install --no-save playwright && npx playwright install chromium
   node tests/browser_check.mjs --shots browser-shots/
   ```

6. **Commit and open a pull request.**

   ```bash
   git add -A
   git commit -m "Data archive, corrected ENSO episode rule, SOI fix, tests (handoff 2026-11)"
   git push -u origin release-2026-11
   ```

   The push changes files under `.github/workflows/`. A personal access token needs the
   **workflow** scope (classic) or **Workflows: read and write** (fine-grained) for that, or
   GitHub rejects the push. Wait for the **Tests** check on the pull request to turn green.

7. **Merge.** `pages.yml` deploys the new pages within a minute or two. The site now shows the
   new front end with the old data, which is a supported state.

8. **Start one data refresh by hand.** Actions → **Refresh ENSO data** → **Run workflow**. It
   runs the pipeline tests, fetches from NOAA, commits as `enso-data-bot`, and that triggers a
   second deploy. This is the step that proves the fixes against NOAA's real files.

9. **Work through section 7.**

10. **Optional:** Actions → **Publish data release** → Run workflow with `kind: auto` to publish
    this month's bundle now instead of waiting for the 12th of next month.

## 7. After launch: what to check

On your machine before merging, and again on the live site after step 7:

- [ ] Home page: the phase cell reads like `ASO 2026 · RONI +2.0 · ONI +2.5`
- [ ] Home page: the forecast chart shows a shaded band around the projection, in all three modes
- [ ] Home page: "+ RONI" draws a second line on the timeline; "Last 8 yrs" zooms it
- [ ] Home page: a "Download this data" card and a "Data archive" footer link, both opening `/archive/`
- [ ] `/archive/`: the table lists the files and each one downloads
- [ ] No red errors in the browser console on any page
- [ ] Actions: **Tests** and **Deploy to GitHub Pages** are green for the merge commit

After the manual refresh in step 8:

- [ ] The run is green and made a commit named `data: scheduled ENSO refresh …`
- [ ] A second **Deploy to GitHub Pages** run started by itself and is green
- [ ] `/admin.html`: all five sources `OK`; each card has a "newest datum" line
- [ ] `/admin.html`: **SOI** shows about 908 records and a latest month of September 2026 or later, not `Dec 2025`
- [ ] `/admin.html`: **Weekly Niño 3.4** shows about 1,920 records and `week of 2026-11-…`
- [ ] `/archive/soi_3month.csv` now runs into 2026; `/archive/nino34_weekly.csv` starts in 1990
- [ ] `/data/oni.json`: `meta.source` begins `NOAA Climate Prediction Center`, and `meta.classification` exists
- [ ] The run page shows no yellow warning titled "ENSO source not refreshed" or "Archive export failed"

If the SOI or weekly numbers do not move, stop and read `OPERATIONS_RUNBOOK.md` §3 before
anything else: that is the one result these changes exist to produce.

After the next scheduled run (Monday or Thursday, 16:10 UTC, often hours late):

- [ ] A new data commit and a new deploy appeared without anyone touching anything
- [ ] `/archive/pipeline_runs.csv` gained a row

## 8. Optional setup: releases and e-mail

**Release notifications, no setup.** On the repository page: **Watch → Custom → Releases**.
GitHub then e-mails a link to every bundle.

**The zip as an e-mail attachment.** Repository → Settings → Secrets and variables → Actions:

| Kind | Name | Value |
|---|---|---|
| Secret | `SMTP_HOST` | The mailbox provider's SMTP server |
| Secret | `SMTP_USER` | The mailbox address that sends |
| Secret | `SMTP_PASSWORD` | An **app password** created for this purpose — never the account password |
| Secret (optional) | `MAIL_TO` | Recipients, comma-separated; defaults to `SMTP_USER` |
| Variable (optional) | `SMTP_PORT` | `465` (default, TLS from the start) or `587` (STARTTLS) |
| Variable (optional) | `EMAIL_CADENCE` | `weekly`, `monthly` (default), `quarterly`, `annual` or `off` |

With no secrets the e-mail step is skipped and nothing else changes. To test: Actions →
**Publish data release** → Run workflow → `kind: none`, `send_email: true`. `DATA_ARCHIVE.md` §3
has the details.

## 9. Open items — known, not changed, your call

| Item | Detail |
|---|---|
| The "Alert status" cell is fixed text | `El Niño Advisory · NOAA CPC · developing 2026–27` is written into `renderStatus()` in `app.js`. It will be wrong the day NOAA changes its alert. Update it by hand, or build a feed. |
| Only one strength tier | The page says "Strong" from 1.5 up. Common usage, and NOAA's strength outlooks, also use moderate (1.0–1.4) and very strong (2.0 and above). The Relative ONI is at +2.0 now. |
| Timeline bars are colored by value, not by episode | The `c` field is not used by the page. Shading official episodes would be a natural next feature. |
| `events.json`, `roni_compare.json` | Loaded but not shown; `events.json` quotes peaks from the older ERSSTv5 record. |
| Privacy page | Still shows the placeholder "Last reviewed: TO BE DATED AT LAUNCH". |
| No social preview image | No `og:image` on any page. |
| Security headers | `public/_headers` has no effect on GitHub Pages. The CSP works through the meta tag in each page; `X-Frame-Options` and the other headers are not served. A proxy in front of the site that can add headers would restore them. |
| `/admin.html` is public | It is read-only and marked `noindex`, but anyone with the address can read it. |
| One plain-http link | The Bureau of Meteorology link on the home page; switch it once the https address is confirmed, then remove the exception in `tests/test_site.py`. |
| Push race | If someone pushes to `main` while a refresh is running, the bot's push is rejected and that run fails; the next one recovers. A `git pull --rebase` before the push would remove the gap. |
| Deploy is not gated on tests | `pages.yml` deploys every push to `main`. |
| Repository address | The repository answers at both `ThePiTree/…` and `itremedypoint-hub/…` (same commits). The site's own pages link to `ThePiTree`, so the archive does too. If that is not the current name, change `REPO_URL` in `scripts/export_archive.py` and re-run the export. |
| Exact halves in the event rule | Ten published values resolve an exact half differently from the rule (section 5.2). Computing the ONI from NOAA's monthly file would settle most of them. |

## 10. How this was checked

| Check | Result |
|---|---|
| Six test suites (`tests/run_all.py`) | 558 checks, all passing |
| Browser check, real Chromium at 390, 820 and 1440 px wide | 230 checks, all passing: every page, the charts, the controls, the operations page healthy and degraded, the offline single-file build |
| Break-it test: 16 deliberate defects introduced one at a time (missing tag, inline script, dead link, renamed workflow, altered CSV value …) | All 16 turned a test red |
| Event rule against NOAA's published ONI and Relative ONI tables | Section 5.2 |
| Site data against NOAA's tables | Every one of the 1,664 values that is not an exact half equals NOAA's printed value |
| Release workflow shell steps, run for real against a stand-in for the GitHub CLI | 29 checks: an ordinary month, a January with three bundles, an existing tag, an idle weekly tick, a missing archive |
| Refresh workflow's commit step, run for real in a throwaway repository with its own remote | 7 checks: data and archive committed together and pushed as `enso-data-bot`; nothing else staged; no commit when nothing changed; data still committed if the archive folder is missing; a rejected push fails without forcing |
| E-mail step against local mail servers | Sent over TLS-from-the-start and over STARTTLS; subject, body and attachment arrived intact; a wrong password failed cleanly and was never printed |
| Archive determinism | A second export and `backfill_vintages.py --check` produce identical files |
| This guide's own launch steps | Carried out on a fresh clone from GitHub at `fc4eb32`, steps 1 to 6 up to the commit (nothing was pushed): the patch applied cleanly, the result was byte-identical to the prepared project, 558 tests and 230 browser checks passed |
| The same steps after the bot has committed again | Simulated with one extra data commit on top of `fc4eb32`: the patch still applied cleanly, the rebuilt revision record picked up the new values, all tests passed |
| Screens read by eye with the production fonts | Home at three widths, operations page healthy and degraded, archive, privacy, creator |

**Not checked, because it could not be reached:**

- The live site and the repository's Actions and Pages run pages. The statement that the site
  is healthy rests on the repository's commit history and the `status.json` committed by the bot.
- NOAA's servers. The parsers were tested against fixtures in NOAA's layout, and the SOI fixture
  reproduces the production symptom exactly, but the new code has not yet read a real NOAA file.
- A real GitHub release and a real e-mail through a real provider.
- Windows. Everything was run on Linux; the scripts use only the standard library.

## 11. Rollback

The launch is one merge, so undoing it is one revert:

```bash
git revert -m 1 <merge-commit-sha>      # or: git revert <sha> for a squash merge
git push
```

`pages.yml` redeploys the previous site within minutes. Data commits made in between stay valid
for the old code: it reads only fields it already knew, and the old pipeline simply writes its
shorter weekly file and its frozen SOI again at the next run. `public/archive/` stops updating
but stays in the tree until you delete it. Releases already published stay until deleted by hand.

To undo only a bad data refresh, revert that one data commit; `OPERATIONS_RUNBOOK.md` §4.2.

## 12. Sources

- NOAA CPC, Oceanic Niño Index table — https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/index.php
- NOAA CPC, Relative Oceanic Niño Index table — https://cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni
- NOAA CPC, index data files — https://www.cpc.ncep.noaa.gov/data/indices/
- Golden Gate Weather Services, El Niño and La Niña years by RONI — https://ggweather.com/enso/roni.htm
