# Operations Runbook — Pulse of the Pacific

How to keep the site healthy with about two minutes a week, and exactly what to do when
something breaks. Written for whoever is on support; no context assumed beyond access to the
GitHub repository.

---

## 1. The routine (weekly, about 2 minutes)

1. Open **https://elninotracker.org/admin.html**.
2. Read the banner:
   - **Green — "All systems normal"**: you are done.
   - **Amber — "Degraded but serving"** or **"Pipeline has not run yet"**: go to §3.
   - **Red — "CRITICAL: data/oni.json could not be loaded"**: go to §4.1.
3. Optional: glance at **Recent pipeline runs**. One amber or red dot among greens is a NOAA
   hiccup that heals on the next run. A streak means §3.

The system is built so that no failure blanks the public site: every refresh keeps the last
good data when anything goes wrong.

## 2. Reading the operations page

**Source cards**, one per NOAA file:

| Badge | Meaning | Urgency |
|---|---|---|
| `OK` | The last run fetched, validated and published this series, and the series is advancing | none |
| `FAIL` | The last run could not refresh it. **The site still serves the last good data** | look within days |
| `STALE` | Either the last *success* is older than 1.5× the cadence, **or** fetches succeed but the newest value is older than that source's limit (the card then says "⚠ series not advancing") | look within days |
| `UNKNOWN` | The pipeline has never reported on it | run the workflow once |

"Newest datum" limits, in days from the middle of the newest period: ONI and RONI 115, weekly
Niño-3.4 30, SOI 120, heat content 90. They live in `DATA_AGE_LIMIT_DAYS` in
`scripts/update_data.py`.

Each card shows the last success, the expected cadence, the record count, the latest value, the
age of the newest datum, the fetch time and — on failure — the pipeline's error text.

**Data integrity** is computed in your browser on the served `oni.json`: at least 800 records ·
time strictly increasing · all values within ±6 °C · every labeled episode at least five seasons
long · the latest season no more than 115 days old. A red card here means the *served data* is
suspect: §4.2.

**Recent pipeline runs**: the last 30 runs. Green is 5 of 5 sources, amber is partial, red is none.

**The Actions tab** is the other place to look. A refresh that could not update a source, or
could not rebuild the archive, shows a yellow warning on its run page even though the run is
green.

## 3. Playbooks — degraded states

### 3.1 A source is `FAIL` with `HTTPError` 403, 404 or 5xx, or a timeout

NOAA's servers sometimes block, move files or go down.

1. Open the source URL from the card in a browser.
   - **It loads** → a passing outage. Do nothing; Monday's or Thursday's run retries. After two
     failed scheduled runs in a row, treat it as moved.
   - **404 or a redirect** → NOAA moved the file. Find it under
     <https://www.cpc.ncep.noaa.gov/data/indices/>, change the entry in `URLS` at the top of
     `scripts/update_data.py`, commit, push, and start a manual run (§5).
2. If the error is a `ValueError` about records or range, NOAA changed the file's layout: §4.3.

### 3.2 `STALE` with "⚠ series not advancing"

The fetch works but the newest value is old. In order of likelihood:

1. **The parser no longer sees the newest rows.** This is what kept the SOI series at December
   2025 from launch until November 2026: NOAA prints a missing value as `-999.9`, and in its
   fixed-width file those run together with their neighbors (`-999.9-999.9`), so the row for the
   year in progress had too few "columns" and was skipped. Download the file, look at its last
   lines, compare with what `parse_<series>` expects, fix it, **add a fixture and a test in
   `tests/test_parsers.py` that uses the real lines**, push, run the workflow.
2. **NOAA has paused the product.** Check the CPC site for a notice. Nothing to fix.

### 3.3 `FAIL` with "record shrank from N to M - refusing to overwrite"

The no-shrink gate caught a download with fewer records than the file on disk. Usually it is a
truncated response and the next run is fine. If NOAA really did shorten the record (a re-issue),
accept it once, from your own machine, so the site never goes a moment without the file:

```bash
git pull
rm public/data/<series>.json            # the gate compares against the file on disk
python3 scripts/update_data.py          # fetches from NOAA and writes the shorter record
python3 tests/run_all.py
git add public/data public/archive
git commit -m "accept NOAA's shorter <series> record" && git push
```

This is the one case where committing a local pipeline run is right. The revision record keeps
the old values.

### 3.4 `STALE` on every card, no `FAIL`

The workflow is not running.

1. Repository → **Actions**. If runs are simply late: GitHub often starts scheduled jobs hours
   after the scheduled time (up to about eight hours has been seen here). That is normal.
2. If there are no runs for days: GitHub disables schedules in repositories with about 60 days
   of no activity. Press **Run workflow** once; any commit also re-arms it.
3. If runs exist but the commit step fails on permissions: Settings → Actions → General →
   Workflow permissions → **Read and write**.
4. If the push is rejected as "non-fast-forward": someone pushed to `main` while the run was in
   progress. The next run succeeds.

### 3.5 Banner: "Pipeline has not run yet"

A fresh deployment. Actions → **Refresh ENSO data** → **Run workflow**.

### 3.6 Yellow warning "Archive export failed" on a refresh run

The data refreshed; `public/archive/` was not rebuilt, so the CSV files lag the site by one run.
Read the message in the run log, then reproduce locally:

```bash
python3 scripts/export_archive.py
python3 tests/run_all.py --pipeline
```

Fix, push, start a manual run. If the revision record itself looks damaged, rebuild it from
history: `python3 scripts/backfill_vintages.py --force` (needs a full clone), then
`python3 scripts/export_archive.py`, and commit `public/archive/`.

### 3.7 The data refreshed but the site still shows old numbers

The refresh committed but the deployment did not follow. Actions → **Deploy to GitHub Pages**:
there should be a run a minute after each refresh, started by `workflow_run`. If there is none,
the refresh workflow's `name:` no longer matches the one in `pages.yml` — restore
`name: Refresh ENSO data`. To deploy now, run **Deploy to GitHub Pages** by hand.

### 3.8 "Tests" is red on a commit

Open the run; the failing check is named in the log with what it found. The site has already
deployed that commit (`pages.yml` does not wait for tests), so fix forward or revert. The
scheduled refresh is not affected unless one of the three pipeline suites is the red one, in
which case the refresh stops too until it is fixed — by design.

### 3.9 "Publish data release" fails

- **"public/archive/ does not exist yet"** → run "Refresh ENSO data" first.
- **The e-mail step fails** → the log shows the mail server's reply. A rejected login almost
  always means an expired or wrong app password in the `SMTP_PASSWORD` secret. The release
  itself was already published before the e-mail step ran.
- A tag that already exists is skipped with a notice. That is intended: bundles are immutable.
  To re-issue one, delete the release **and its tag** on GitHub, then run the workflow by hand.

## 4. Playbooks — serious states

### 4.1 Red banner, or the public site is blank

The deployment itself is broken.

1. `curl -I https://elninotracker.org/data/oni.json` — expect `200`.
2. `404` → open Actions → **Deploy to GitHub Pages** and read the last run. Check that the
   upload step still says `path: "public"` and that Settings → Pages → Source is **GitHub Actions**.
3. `200` but the page is broken → open the browser console. A Content-Security-Policy error
   means someone added an inline script or an `on…=` attribute to a page. Revert it or move the
   code into `assets/*.js`. `python3 tests/test_site.py` finds these before they ship.
4. The custom domain shows GitHub's 404 → Settings → Pages → Custom domain must read
   `elninotracker.org`, and the DNS records at the registrar must still point at GitHub Pages.

### 4.2 An integrity card is red (bad served data)

The last data commit is suspect. Roll it back:

```bash
git log --oneline -- public/data        # find the "data: scheduled ENSO refresh …" commit
git revert <that-commit-sha>
git push
```

The previous data is back within minutes. Then run `python3 scripts/update_data.py` locally and
look at what NOAA is serving. Discard the local output afterwards with
`git checkout -- public/data public/archive`.

### 4.3 NOAA changed a file's layout (`ValueError` from validation)

This is the designed failure: validation refused to publish nonsense.

1. Download the file from the URL on the card and read the new layout.
2. Adjust the matching `parse_*` function in `scripts/update_data.py`.
3. **Add a test** with real lines of the new layout to `tests/test_parsers.py`. The suite gates
   every future run; this is how a layout change never passes silently twice.
4. `python3 tests/run_all.py` → green → commit, push, manual run.

### 4.4 NOAA re-based or re-issued a whole index

Every five years NOAA moves the ONI's base periods, and now and then it changes the underlying
dataset (ERSSTv5 → v6 in 2026). Many old values change at once. The pipeline accepts this — the
record does not shrink — and the revision record gains a row for every changed period, dated
that run. Nothing to fix. `tests/fixtures/` is frozen and does not react; if you want fresh
evidence for the episode rule, see `tests/fixtures/README.md`.

## 5. Manual operations

| Task | How |
|---|---|
| Refresh the data now | Actions → **Refresh ENSO data** → Run workflow |
| Deploy now | Actions → **Deploy to GitHub Pages** → Run workflow |
| Publish a bundle now | Actions → **Publish data release** → Run workflow → `kind: auto` |
| Send a test e-mail | Same workflow → `kind: none`, `send_email: true` |
| Run every test | `python3 tests/run_all.py` |
| Run the pipeline locally | `python3 scripts/update_data.py` (rewrites `public/data/` and `public/archive/`; do not commit) |
| Rebuild the archive from the current JSON | `python3 scripts/export_archive.py` |
| Check the revision record against history | `python3 scripts/backfill_vintages.py --check` |
| Rebuild the single-file offline copy | `python3 scripts/build_standalone.py` → `dist/` |
| Roll back bad data | `git revert` the data commit (§4.2) |
| Change the refresh schedule | The two `cron:` lines in `.github/workflows/update-data.yml` (UTC) |
| Change the release day | The first `cron:` line in `.github/workflows/data-release.yml` **and** the same string in the `TRIGGER` expression below it; `tests/test_release.py` checks they match |

## 6. Alerting

GitHub e-mails you when a workflow **fails** (your profile → Settings → Notifications → Actions).
By design the refresh exits 0 even when sources fail — those are telemetry, shown on the
operations page and as warnings on the run page. So the e-mail fires for *infrastructure*
problems (a red test, permissions, a rejected push), while *source* problems wait for your
weekly glance, because the site protects itself with last-good data.

For release bundles: repository page → **Watch → Custom → Releases**.

## 7. What this system will never do

- Publish partially parsed, out-of-range or truncated data: the validation gates block the write.
- Erase good data because a run failed: writes are per series and gated.
- Depend on the pipeline being up: the site serves its committed files.
- Expose anything operable: the operations page is read-only.
- Overwrite a published release bundle.
