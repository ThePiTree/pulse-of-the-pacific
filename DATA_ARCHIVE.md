# Data Archive — collection, download, delivery and research use

This document answers four questions: *is the data being collected*, *where is it archived*,
*how do I get it on a schedule*, and *how do I use it for analysis or publication*.

---

## 1. Is the data being collected? Yes — and here is how to see it

Every refresh (Mondays and Thursdays, 16:10 UTC, often hours late) is a git commit by
`enso-data-bot`. The commit history of `public/data/` **is** the collection log. From the first
run on 17 August 2026 to 10 November 2026 every scheduled slot produced a data commit: 25 slots,
26 commits, with all five NOAA sources reporting OK on the latest.

Confirm it at any time:

```bash
git log --date=short --format='%ad %s' -- public/data | head
```

or open `/admin.html` (**Recent pipeline runs**) or `/archive/pipeline_runs.csv`.

One series was *collected but not advancing*: the Southern Oscillation Index stood at December
2025 from launch until the November 2026 update, because of a parsing fault described in
`OPERATIONS_RUNBOOK.md` §3.2. NOAA's file holds the full history, so nothing was lost: the first
refresh after that update restores every month. The operations page now flags that condition.

## 2. What is archived, and where

Three layers, from most to least convenient:

| Layer | Where | What you get |
|---|---|---|
| **CSV archive** | https://elninotracker.org/archive/ (repository: `public/archive/`) | Analysis-ready CSV files, rebuilt at every refresh: each series in full, one merged monthly table, the revision record, the run log and a data dictionary |
| **Release bundles** | The repository's **Releases** tab | Dated, permanent zips of the archive: monthly (`data-YYYY-MM`), quarterly (`data-YYYY-Qn`), annual (`data-YYYY-annual`). Citable snapshots that are never overwritten |
| **Git history** | The repository | The complete JSON as served at every refresh since launch: `git show <sha>:public/data/oni.json` |

The files:

| File | Contents |
|---|---|
| `enso_monthly_merged.csv` | Every series on one monthly axis. **Start here** |
| `oni.csv`, `roni.csv` | Oceanic Niño Index and Relative ONI, DJF 1950 → present, with `event_classification` |
| `nino34_weekly.csv` | Weekly Niño-3.4 anomaly, 1990 → present (the full record from the first refresh after the November 2026 update) |
| `soi_3month.csv` | Three-month Southern Oscillation Index, 1951 → present |
| `heat_content_180w_100w.csv` | Upper-ocean heat anomaly, 1979 → present |
| `vintages/*.csv` | The revision record, one file per series |
| `pipeline_runs.csv` | One row per refresh: time, sources refreshed, sources failed |
| `README_DATA.md` | The data dictionary: every column, every convention, caveats, citation |
| `manifest.json` | A machine-readable listing with row counts and coverage |

**Back data.** NOAA's files are complete historical records, so every refresh already carries
the whole history. There was never a gap to fill in the *series*. What exists only from launch
onward is the **revision record** — which value NOAA had published for a period on a given
date. It has been rebuilt from git history by `scripts/backfill_vintages.py` and so starts on
17 August 2026.

**The revision record in one paragraph.** NOAA revises recent values after first publishing
them. Each `vintages/` file keeps one row for every distinct value this site has served for a
period: `first_seen_utc`, the period, the value, and `revision` (0 for the first value, 1, 2, …
for later ones). A period with more than one row was revised. To rebuild a series as it stood on
a date, take each period's last row on or before that date.

## 3. Getting it delivered on a schedule

**A link by e-mail, no setup (recommended).** On the repository page:
**Watch → Custom → tick "Releases" → Apply.** GitHub e-mails you the moment each monthly,
quarterly or annual bundle is published.

| Bundle | Published | Tag |
|---|---|---|
| Monthly | The 12th of every month, after NOAA's monthly update | `data-2026-11` |
| Quarterly | Also on the 12th of January, April, July and October, for the quarter just ended | `data-2026-Q4` |
| Annual | Also on the 12th of January, for the year just ended | `data-2026-annual` |

**The zip as an attachment (optional).** The release workflow can also send the bundle through
your own mailbox. It stays off until you add three repository secrets
(Settings → Secrets and variables → Actions):

| Kind | Name | Value |
|---|---|---|
| Secret | `SMTP_HOST` | Your mail provider's SMTP server, for example `smtp.mail.yahoo.com`, `smtp.gmail.com` or `smtp.office365.com` |
| Secret | `SMTP_USER` | The mailbox address that sends the message |
| Secret | `SMTP_PASSWORD` | An **app password** made for this purpose in your mail account's security settings — never your normal password |
| Secret (optional) | `MAIL_TO` | Who receives it, comma-separated. Defaults to `SMTP_USER` |
| Variable (optional) | `SMTP_PORT` | `465` (the default) or `587` |
| Variable (optional) | `EMAIL_CADENCE` | `weekly`, `monthly` (the default), `quarterly`, `annual` or `off` |

How often it arrives:

| `EMAIL_CADENCE` | You receive |
|---|---|
| `weekly` | The current archive every Tuesday |
| `monthly` | The archive on the 12th of each month |
| `quarterly` | The archive on the 12th of January, April, July and October |
| `annual` | The archive on the 12th of January |
| `off` | Nothing on a schedule; manual sends still work |

To test it: Actions → **Publish data release** → Run workflow → `kind: none`,
`send_email: true`. The password is used only inside that one step and is never printed. To stop
the e-mails, delete the secrets or set `EMAIL_CADENCE` to `off`.

**On demand.** Actions → **Publish data release** → Run workflow, or simply download from
`/archive/` whenever you like — it is as current as the site.

## 4. Using the data for analysis, mapping, trends and publication

Start with the merged table — one row per month, every series aligned:

```python
import pandas as pd

df = pd.read_csv("https://elninotracker.org/archive/enso_monthly_merged.csv")
df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=15))
df.set_index("date")[["oni_anomaly_c", "roni_anomaly_c", "soi_3month"]].plot(figsize=(14, 4))
```

Which values were revised, and by how much:

```python
v = pd.read_csv("https://elninotracker.org/archive/vintages/roni_vintages.csv")
revised = v[v.groupby(["year", "season"]).revision.transform("max") > 0]
print(revised.sort_values(["year", "season", "revision"]))
```

Research directions the archive supports directly:

1. **Anatomy of the 2026 El Niño** — onset, growth per season and peak against 1982–83, 1997–98,
   2015–16 and 2023–24 (`oni.csv`, `roni.csv`), and how far the weekly Niño-3.4 led the
   three-month indices (`nino34_weekly.csv`).
2. **ONI against Relative ONI** — NOAA changed its official index in February 2026. How the two
   classify the same events (onset dates, durations, the 2025–26 La Niña that only one of them
   records) is a timely, open question, and `event_classification` is in both files.
3. **Subsurface lead time** — cross-correlate `heat_content_180w_100w.csv` with the ONI to
   estimate how many months upper-ocean heat leads the surface.
4. **Ocean–atmosphere coupling** — the ONI against the SOI; expect a strong negative
   correlation, and look at the residuals.
5. **Real-time against final values** — `vintages/` measures how provisional recent values are.
   Few public datasets keep this, and it strengthens any claim built on "the latest value".
6. **Teleconnections** — join the phase labels to any regional series you collect (rainfall,
   fire, fisheries) by year and month.

**How the phase labels are made.** `event_classification` follows NOAA's historical-episode
rule: at least five consecutive overlapping seasons at or beyond ±0.5 °C, with the threshold
applied to the value rounded to one decimal, as in NOAA's published tables. The labels match the
coloring of NOAA's ONI table for every season it listed on 12 November 2026. Recent seasons of an
event still in progress are marked `(pending)`. `README_DATA.md` in the archive has the details
and the four seasons where the Relative ONI labels differ from NOAA's table.

**Citing.** Use the citation in `README_DATA.md`: NOAA's Climate Prediction Center is the
producer, this archive is the access point. For a snapshot others can recover, cite a release
tag such as `data-2026-Q4`.

**Caveats to state in any paper.** Recent values are provisional — quantify that with the
revision record. The ONI uses base periods that move every five years. Weekly values come from a
different sea-surface-temperature analysis than the monthly and seasonal ones. The projection on
the website is an illustrative statistical benchmark, not a forecast product, and is not in the
archive.

## 5. Operations notes

- The archive is rebuilt inside the refresh (`update_data.py` calls `export_archive.py`). If the
  export fails, the site's data is unaffected and the Actions run shows a yellow warning.
- Files are rewritten only when their content changes, and the export never looks at the clock,
  so quiet weeks stay quiet in git and re-running it changes nothing.
- `python3 scripts/backfill_vintages.py --check` confirms the revision record still agrees with
  the repository's history; `--force` rebuilds it.
- `public/archive/` is generated. Do not edit it by hand: the next refresh overwrites it.
