#!/usr/bin/env python3
"""
export_archive.py — turn the site's live JSON into a citable, analysis-ready
CSV archive under public/archive/.

Called at the end of every data refresh (scripts/update_data.py), and safe to
run by hand:  python3 scripts/export_archive.py

WHAT IT WRITES (all under public/archive/)
  enso_monthly_merged.csv      every series on one monthly axis (start here)
  oni.csv  roni.csv            the two seasonal indices, 1950 -> present
  nino34_weekly.csv            weekly Nino-3.4 SST anomaly, full record
  soi_3month.csv               3-month running-mean Southern Oscillation Index
  heat_content_180w_100w.csv   upper-300 m temperature anomaly, 180W-100W
  vintages/<series>_vintages.csv   the revision record (see below)
  pipeline_runs.csv            append-only log of every refresh
  README_DATA.md               data dictionary, caveats, citation
  manifest.json                machine-readable listing + summary numbers
  index.html                   the human download page (static, no JavaScript)

THE REVISION RECORD ("vintages")
  NOAA revises recent values after first publishing them. A vintage file holds
  one row per DISTINCT value this site has ever served for a period:
      first_seen_utc, <period columns>, value, revision
  revision 0 is the first value archived for that period; 1, 2, ... are later
  changes. A row is appended only when a period is new or its value changed,
  so the files stay small and every revision is explicit. To get the record
  "as it stood on date D", take each period's last row with first_seen_utc <= D.

DESIGN RULES
  * Standard library only.
  * DETERMINISTIC: output depends only on the JSON in public/data/ (dates come
    from each file's own meta.updated stamp, never from the wall clock), so
    re-running on unchanged data rewrites nothing.
  * The vintage and run-log files are append-only; everything else is a pure
    re-rendering of the current JSON.
  * scripts/backfill_vintages.py rebuilds the vintage files from git history
    using the same functions, so live appends and a rebuild always agree.
"""
import csv, datetime, io, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # sibling modules, however we are run
import enso_rule

HERE = os.path.dirname(os.path.abspath(__file__))
PUB  = os.path.join(HERE, "..", "public")
DATA = os.path.join(PUB, "data")
ARCH = os.path.join(PUB, "archive")
VINT = os.path.join(ARCH, "vintages")

SITE_URL = "https://elninotracker.org"
REPO_URL = "https://github.com/ThePiTree/pulse-of-the-pacific"

SEASONS    = ["DJF","JFM","FMA","MAM","AMJ","MJJ","JJA","JAS","ASO","SON","OND","NDJ"]
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# series key -> (json file, vintage file, vintage header)
VINTAGE_SPECS = {
    "oni":   ("oni.json",   "oni_vintages.csv",
              ["first_seen_utc", "year", "season", "value_c", "revision"]),
    "roni":  ("roni.json",  "roni_vintages.csv",
              ["first_seen_utc", "year", "season", "value_c", "revision"]),
    "wksst": ("wksst.json", "nino34_weekly_vintages.csv",
              ["first_seen_utc", "week_centered_date", "value_c", "revision"]),
    "soi":   ("soi.json",   "soi_vintages.csv",
              ["first_seen_utc", "year", "month", "value", "revision"]),
    "heat":  ("heat.json",  "heat_content_vintages.csv",
              ["first_seen_utc", "year", "month", "value_c", "revision"]),
}

# ------------------------------------------------------------------- helpers
def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p): return None
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return None

def write_if_changed(path, text):
    """Write only when the bytes differ, so unchanged data produces no diff."""
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() == text: return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f: f.write(text)
    return True

def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header); w.writerows(rows)
    return buf.getvalue()

def fmt(v):
    """Canonical text form of a value. Every CSV and every vintage comparison
    uses this, so 2.5 and 2.50 can never look like a revision."""
    return f"{float(v):.2f}"

def month_of(t):
    """Fractional year at a month CENTRE (y + (m-0.5)/12) -> (year, month)."""
    y = int(t); m = int(round((t - y) * 12 - 0.5)) + 1
    return y, min(12, max(1, m))

def week_date(rec):
    """ISO date a weekly record is centred on. Records written since Nov 2026
    carry it exactly as `d`; for older snapshots (git history) it is recovered
    from `t` = year + day_of_year/365.25. One edge needs care: 31 Dec of a leap
    year is day 366, stored as (year+1) + 0.0021 — just below 1 Jan's 0.0027."""
    if rec.get("d"): return rec["d"]
    t = rec["t"]; y = int(t); days = (t - y) * 365.25
    if days < 0.875:
        return datetime.date(y - 1, 12, 31).isoformat()
    return (datetime.date(y, 1, 1) + datetime.timedelta(days=int(round(days)) - 1)).isoformat()

def seen_date(doc):
    """UTC date of the pipeline run that produced this JSON file."""
    stamp = ((doc or {}).get("meta") or {}).get("updated") or ""
    return stamp[:10] if len(stamp) >= 10 else None

# ------------------------------------------------------ classification labels
def season_labels(records):
    """Text label per season, computed from the VALUES with the shared rule in
    enso_rule.py (never from the `c` stored in the JSON, so the archive is right
    even when it is rebuilt from JSON written by an older pipeline).

    NOAA's rule is retrospective: a run counts only once it is five seasons long.
    That would leave an event in progress labelled 'Neutral' until its fifth
    season arrives, so a run that reaches the end of the record but is still
    short is labelled '(pending)': it becomes El Nino / La Nina when the fifth
    season arrives, or reverts to Neutral if the run ends first."""
    names = {"E": "El Nino", "L": "La Nina", "N": "Neutral"}
    values = [r["v"] for r in records]
    labels = [names[c] for c in enso_rule.episode_codes(values)]
    start, side = enso_rule.pending_run(values)
    if start is not None:
        for k in range(start, len(records)):
            labels[k] = "El Nino (pending)" if side > 0 else "La Nina (pending)"
    return labels

# --------------------------------------------------------- period keys/values
def vintage_items(key, records):
    """[(period_key_tuple_of_str, value_str)] for one series, oldest first."""
    if key in ("oni", "roni"):
        return [((str(r["y"]), r["s"]), fmt(r["v"])) for r in records]
    if key == "wksst":
        return [((week_date(r),), fmt(r["v"])) for r in records]
    out = []
    for r in records:                                   # soi, heat: monthly
        y, m = month_of(r["t"])
        out.append(((str(y), str(m)), fmt(r["v"])))
    return out

# ------------------------------------------------------------------ vintages
def read_vintages(path, nkey):
    """-> (rows, last_value_by_key, revisions_by_key). rows are lists of str."""
    rows, last, count = [], {}, {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if len(row) != nkey + 3: continue        # first_seen + key + value + revision
                k = tuple(row[1:1 + nkey])
                rows.append(row); last[k] = row[1 + nkey]; count[k] = count.get(k, 0) + 1
    return rows, last, count

def apply_vintage(state, items, first_seen):
    """Pure core of the revision record. `state` is (rows, last, count) as
    returned by read_vintages; appends a row for every period that is new or
    whose value differs from the last one recorded. Returns rows added."""
    rows, last, count = state
    added = 0
    for k, v in items:
        if last.get(k) == v: continue
        rows.append([first_seen, *k, v, str(count.get(k, 0))])
        last[k] = v; count[k] = count.get(k, 0) + 1; added += 1
    return added

def update_vintage_file(key, doc):
    """Append this snapshot's new/changed values to the series' vintage file."""
    _, fname, header = VINTAGE_SPECS[key]
    path = os.path.join(VINT, fname)
    when = seen_date(doc)
    if not doc or not doc.get("records") or not when:
        return 0                     # baseline without a run stamp: nothing to record
    state = read_vintages(path, len(header) - 3)
    added = apply_vintage(state, vintage_items(key, doc["records"]), when)
    if added:
        write_if_changed(path, csv_text(header, state[0]))
    return added

def vintage_summary(key):
    """(distinct rows, revised periods, first_seen min) for the README/page."""
    _, fname, header = VINTAGE_SPECS[key]
    rows, _, count = read_vintages(os.path.join(VINT, fname), len(header) - 3)
    revised = sum(1 for c in count.values() if c > 1)
    start = min((r[0] for r in rows), default=None)
    return len(rows), revised, start

# -------------------------------------------------------------- series CSVs
def export_seasonal(doc, outname, col):
    recs = (doc or {}).get("records") or []
    if not recs: return []
    labels = season_labels(recs)
    rows = [[r["y"], r["s"], r["m"], MONTH_ABBR[r["m"] - 1], f"{r['t']:.4f}", fmt(r["v"]), lab]
            for r, lab in zip(recs, labels)]
    hdr = ["year", "season", "center_month", "center_month_name", "time_fractional_year",
           col, "event_classification"]
    write_if_changed(os.path.join(ARCH, outname), csv_text(hdr, rows))
    return list(zip(recs, labels))

def export_weekly(doc):
    recs = (doc or {}).get("records") or []
    if not recs: return []
    rows = [[week_date(r), f"{r['t']:.4f}", fmt(r["v"])] for r in recs]
    write_if_changed(os.path.join(ARCH, "nino34_weekly.csv"),
                     csv_text(["week_centered_date", "time_fractional_year", "nino34_sst_anomaly_c"], rows))
    return recs

def export_monthly(doc, outname, col):
    recs = (doc or {}).get("records") or []
    if not recs: return []
    rows = []
    for r in recs:
        y, m = month_of(r["t"])
        rows.append([y, m, MONTH_ABBR[m - 1], f"{r['t']:.4f}", fmt(r["v"])])
    write_if_changed(os.path.join(ARCH, outname),
                     csv_text(["year", "month", "month_name", "time_fractional_year", col], rows))
    return recs

def export_merged(oni, roni, soi, heat, weekly):
    """One row per calendar month. ONI/RONI sit on the month their 3-month
    season is centred on; weekly values are averaged over the calendar month
    their centre date falls in (with the number of weeks, since the current
    month is partial). Blank = the series has no value for that month."""
    table = {}
    for r, lab in oni:
        e = table.setdefault((r["y"], r["m"]), {}); e["oni"] = fmt(r["v"]); e["oni_c"] = lab
    for r, lab in roni:
        e = table.setdefault((r["y"], r["m"]), {}); e["roni"] = fmt(r["v"]); e["roni_c"] = lab
    for r in soi:
        table.setdefault(month_of(r["t"]), {})["soi"] = fmt(r["v"])
    for r in heat:
        table.setdefault(month_of(r["t"]), {})["heat"] = fmt(r["v"])
    weeks = {}
    for r in weekly:
        d = week_date(r)
        weeks.setdefault((int(d[:4]), int(d[5:7])), []).append(r["v"])
    for k, vals in weeks.items():
        e = table.setdefault(k, {}); e["wk"] = fmt(sum(vals) / len(vals)); e["wk_n"] = str(len(vals))
    rows = []
    for (y, m) in sorted(table):
        e = table[(y, m)]
        rows.append([y, m, MONTH_ABBR[m - 1], SEASONS[m - 1],
                     e.get("oni", ""), e.get("oni_c", ""), e.get("roni", ""), e.get("roni_c", ""),
                     e.get("soi", ""), e.get("heat", ""), e.get("wk", ""), e.get("wk_n", "")])
    hdr = ["year", "month", "month_name", "season_centered_on_month",
           "oni_anomaly_c", "oni_event_classification", "roni_anomaly_c", "roni_event_classification",
           "soi_3month", "heat_content_180w_100w_anomaly_c",
           "nino34_weekly_mean_c", "nino34_weekly_weeks_in_mean"]
    write_if_changed(os.path.join(ARCH, "enso_monthly_merged.csv"), csv_text(hdr, rows))
    return len(rows)

# ------------------------------------------------------------------ run log
def update_run_log(status, archive_start):
    """Append-only log of refreshes, fed from status.json's rolling history.
    Entries dated before the archive's first successful refresh are skipped:
    they are pre-launch test runs, not operation of the live site."""
    path = os.path.join(ARCH, "pipeline_runs.csv")
    rows, seen = [], set()
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if len(row) == 3: rows.append(row); seen.add(row[0])
    for h in (status or {}).get("history", []):
        ts = h.get("ts", "")
        if not ts or ts in seen: continue
        if archive_start and ts[:10] < archive_start: continue
        rows.append([ts, str(h.get("ok", "")), ";".join(h.get("fail", []))]); seen.add(ts)
    rows.sort(key=lambda r: r[0])
    if rows:
        write_if_changed(path, csv_text(["run_timestamp_utc", "sources_ok", "sources_failed"], rows))
    return len(rows)

# --------------------------------------------------------------------- docs
def _span(first, last):
    return f"{first} → {last}" if first and last else "n/a"

def write_readme(s):
    txt = f"""# Pulse of the Pacific — Data Archive

Generated from the pipeline run of {s['generated']} by `scripts/export_archive.py`.
The archive is regenerated at the end of every scheduled data refresh (Mondays and
Thursdays), so these files are exactly as current as the live site at {SITE_URL}.

**Every series here is produced by NOAA's Climate Prediction Center (CPC).** This archive
is a convenience re-publication in analysis-ready CSV — consistent headers, a data
dictionary, and a record of revisions. The authoritative numbers are NOAA's, and NOAA data
is in the public domain. Cite NOAA CPC as the producer and this archive as the access point
(citation at the end).

## Files

| File | Rows | Coverage | What it is |
|---|---|---|---|
| `enso_monthly_merged.csv` | {s['merged_n']} | all series | Every series on one monthly axis. **Start here.** |
| `oni.csv` | {s['oni_n']} | {s['oni_span']} | Oceanic Niño Index: 3-month running mean of sea-surface-temperature anomalies in the Niño-3.4 region (5°N–5°S, 170°W–120°W), from NOAA's ERSST analysis (ERSSTv6 as of 2026) against centered 30-year base periods that NOAA updates every 5 years. NOAA's long-standing ENSO index. |
| `roni.csv` | {s['roni_n']} | {s['roni_span']} | Relative ONI: the Niño-3.4 anomaly minus the tropical-mean (20°S–20°N) SST anomaly, rescaled to the ONI's variance. **NOAA's official index for ENSO monitoring and prediction since February 2026.** Strong El Niños read several tenths of a degree lower than on the ONI. |
| `nino34_weekly.csv` | {s['wk_n']} | {s['wk_span']} | Weekly Niño-3.4 SST anomaly from CPC's OISST-based weekly table (1991–2020 base period). The freshest surface signal. Each date is the Wednesday the week is centered on. |
| `soi_3month.csv` | {s['soi_n']} | {s['soi_span']} | 3-month running mean of the Southern Oscillation Index (standardized Tahiti-minus-Darwin sea-level pressure), as published by CPC. Negative during El Niño. |
| `heat_content_180w_100w.csv` | {s['heat_n']} | {s['heat_span']} | Upper-ocean (0–300 m) temperature anomaly averaged over the equatorial Pacific, 180°W–100°W. Subsurface heat leads the surface by months. |
| `vintages/*.csv` | {s['vint_rows']} | since {s['vint_start']} | **The revision record** — one file per series; see below. |
| `pipeline_runs.csv` | {s['runs_n']} | since {s['vint_start']} | Append-only log of every data refresh: UTC timestamp, sources refreshed, sources that failed. |
| `manifest.json` | — | — | Machine-readable listing of these files with the summary numbers above. |

## The revision record (`vintages/`)

NOAA routinely revises recent values after first publishing them (its own ONI page notes that
values “may change up to two months after the initial ‘real time’ value is posted”). Each vintage
file keeps **one row for every distinct value this site has served for a period**:

| Column | Meaning |
|---|---|
| `first_seen_utc` | UTC date of the pipeline run that first served this value |
| period columns | `year, season` (ONI, RONI) · `week_centered_date` (weekly) · `year, month` (SOI, heat) |
| `value_c` / `value` | the value as served from that run onward |
| `revision` | `0` = first value archived for the period; `1, 2, …` = later changes |

A row is added only when a period is new or its value changed, so a period with more than one
row **was revised**, and `revision > 0` selects exactly the revisions. To rebuild a series as it
stood on a given date, take each period's last row with `first_seen_utc` on or before that date.

Two things to keep in mind. `first_seen_utc` is when *this archive* first recorded a value: for
the long historical record that is the archive's first run ({s['vint_start']}), not the date NOAA
originally published it. And weekly values older than about ten years entered the archive in
November 2026, when it began keeping NOAA's full weekly record rather than a rolling window.

Revised periods so far — ONI: {s['rev_oni']} · RONI: {s['rev_roni']} · weekly Niño-3.4: {s['rev_wksst']} · SOI: {s['rev_soi']} · heat content: {s['rev_heat']}.

## Conventions

- `time_fractional_year` places each sample at the **center** of its period: a 3-month season
  centered on month *m*, or the month *m* itself, is `year + (m − 0.5)/12`; a week is
  `year + day_of_year/365.25`. Use the date columns for exact work.
- ONI and RONI seasons follow NOAA's labels: `DJF 2026` is December 2025 – February 2026,
  centered on January 2026 (`center_month = 1`); `NDJ 2026` is centered on December 2026.
- `event_classification` applies NOAA's historical-episode rule: an El Niño or La Niña is a run
  of at least **five consecutive overlapping seasons** with the index at or beyond ±0.5 °C. As in
  NOAA's published tables, the threshold is applied to the value **rounded to one decimal place**
  (an exact half rounds up: 0.45 counts as 0.5, −0.45 as −0.4), while the value columns keep
  NOAA's two decimals. So a season printed here as 0.47 can belong to an El Niño. Seasons inside
  a qualifying run are labeled `El Nino` / `La Nina`; all others `Neutral`.
- The one exception is an event still in progress: when the most recent seasons meet the
  threshold but the run has not yet reached five, they are labeled `El Nino (pending)` /
  `La Nina (pending)`. Those labels change once the run reaches five seasons, or revert to
  `Neutral` if it ends short.
- The labels were checked against NOAA's own tables on 12 November 2026. They match the
  coloring of NOAA's ONI table for all 920 seasons it listed, and the same rule applied to
  NOAA's Relative ONI table for 917 of its 921 seasons. The four that differ are FMA–MJJ 1984:
  NOAA's file gives FMA 1984 as −0.45 and NOAA's table prints it as −0.5, which joins two
  La Niña runs that stay separate here. Files written before that date used the two-decimal
  values directly and differ for about 5 % of seasons.
- In `enso_monthly_merged.csv`, `nino34_weekly_mean_c` averages the weekly values whose center
  date falls in that calendar month; `nino34_weekly_weeks_in_mean` says how many (the current
  month is partial).
- Missing values are blank cells — never sentinels such as −999.9.
- SOI month labels are exactly as printed in CPC's file.

## Caveats for publication-grade use

1. **The most recent values are provisional.** Re-pull after a few months for final values, and
   use `vintages/` to state how much they moved.
2. The ONI's base period shifts every five years, so it is not an anomaly from one fixed
   climatology. RONI was introduced partly to remove the warming trend this leaves behind.
3. Weekly (OISST) and monthly/seasonal (ERSST) values come from different SST analyses. Small
   offsets between them are expected and are not errors.
4. Event classifications are retrospective by definition; treat `(pending)` rows accordingly.
5. The statistical projection on the website is an illustrative benchmark. It is not part of
   this archive and is not a forecast product.

## How to cite

> NOAA Climate Prediction Center (producer). ENSO indices: Oceanic Niño Index, Relative Oceanic
> Niño Index, weekly Niño-3.4 SST anomaly, Southern Oscillation Index, equatorial upper-ocean
> heat content. Accessed via the *Pulse of the Pacific* data archive, {SITE_URL}/archive/ ,
> data as of {s['generated'][:10]}.

For a fixed, recoverable snapshot cite a release bundle by its tag (for example
`data-2026-11`) from {REPO_URL}/releases .

Source files: https://www.cpc.ncep.noaa.gov/data/indices/ (`oni.ascii.txt`, `RONI.ascii.txt`,
`wksst9120.for`, `soi.3m.txt`) and
https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt

## Reproducing any past state

Every refresh is a git commit, so the complete JSON served on any date is recoverable from
{REPO_URL} with `git show <commit>:public/data/oni.json`.
`scripts/backfill_vintages.py` rebuilds the whole revision record from that history.
"""
    write_if_changed(os.path.join(ARCH, "README_DATA.md"), txt)

def _esc(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def write_index_html(s, files):
    rows = "\n".join(
        f'        <tr><td><a href="{_esc(f)}">{_esc(f)}</a></td><td class="n">{_esc(sz)}</td><td>{_esc(desc)}</td></tr>'
        for f, sz, desc in files)
    ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Pulse of the Pacific ENSO data archive",
        "description": ("Analysis-ready CSV re-publication of NOAA Climate Prediction Center ENSO indices "
                        "(Oceanic Niño Index, Relative ONI, weekly Niño-3.4 SST anomaly, Southern Oscillation "
                        "Index, equatorial upper-ocean heat content), refreshed twice weekly, with a record of "
                        "how published values were later revised."),
        "url": f"{SITE_URL}/archive/",
        "keywords": ["El Niño", "La Niña", "ENSO", "Oceanic Niño Index", "Relative Oceanic Niño Index",
                     "Niño 3.4", "Southern Oscillation Index", "sea surface temperature"],
        "temporalCoverage": "1950-01/" + (s["generated"][:7] if s["generated"][:4].isdigit() else ".."),
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "NOAA Climate Prediction Center",
                    "url": "https://www.cpc.ncep.noaa.gov/"},
        "isBasedOn": "https://www.cpc.ncep.noaa.gov/data/indices/",
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                          "contentUrl": f"{SITE_URL}/archive/{f}"} for f, _, _ in files if f.endswith(".csv")],
    }
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>Data Archive | Pulse of the Pacific</title>
<meta name="description" content="Download the ENSO data behind Pulse of the Pacific as analysis-ready CSV: ONI, RONI, weekly Niño 3.4, SOI, ocean heat content, and a record of how NOAA revised recent values."/>
<meta name="theme-color" content="#05080f"/>
<link rel="canonical" href="{SITE_URL}/archive/"/>
<meta property="og:title" content="Data Archive | Pulse of the Pacific"/>
<meta property="og:description" content="The ENSO indices behind the tracker as analysis-ready CSV, refreshed twice a week, with a revision record."/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{SITE_URL}/archive/"/>
<meta property="og:image" content="{SITE_URL}/social-preview.png"/>
<meta property="og:image:width" content="1200"/>
<meta property="og:image:height" content="630"/>
<meta property="og:image:alt" content="The Pulse of the Pacific: the Oceanic Niño Index from 1950 to today, El Niño peaks in red and orange, La Niña in blue."/>
<meta name="twitter:card" content="summary_large_image"/>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%2305080f'/%3E%3Ccircle cx='16' cy='16' r='6' fill='%233dd6c4'/%3E%3C/svg%3E"/>
<!-- Generated by scripts/export_archive.py on every data refresh — edit the generator, not this file.
     Static page: no scripts run here (the JSON-LD block below is data, not code). -->
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/style.css">
<script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False, indent=2)}
</script>
</head>
<body>

<div class="topbar">
  <div class="wrap">
    <div class="brand"><span class="dot"></span>Pulse of the Pacific · Data Archive</div>
    <nav class="topnav"><a href="../">← Back to the tracker</a><a href="../admin.html">System status</a></nav>
  </div>
</div>

<section class="band" style="padding-top:56px">
  <div class="wrap arch">

    <div class="band-head">
      <div class="label">Open data</div>
      <h2>Download the data</h2>
      <p>Everything the tracker displays, as analysis-ready CSV, regenerated with every data refresh
      (Mondays and Thursdays). Every series is produced by NOAA's Climate Prediction Center; this
      archive republishes it with consistent headers, a data dictionary, and a <em>revision record</em>
      that keeps each value NOAA later changed.</p>
      <p class="arch-stamp">Data as of {_esc(s['generated'])} · latest ONI season {_esc(s['oni_latest'])} ·
      revision record since {_esc(s['vint_start'])}</p>
    </div>

    <div class="arch-scroll">
    <table class="arch-table">
      <thead><tr><th scope="col">File</th><th scope="col">Size</th><th scope="col">Contents</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
    </div>

    <div class="arch-note">
      <b>Start with</b> <span class="mono">enso_monthly_merged.csv</span> for most analyses, and read
      <a href="README_DATA.md">README_DATA.md</a> for the conventions, caveats and citation format.
      Dated monthly, quarterly and annual bundles of this archive are published as
      <a href="{REPO_URL}/releases" target="_blank" rel="noopener">releases on GitHub</a>.
    </div>

  </div>
</section>

<footer>
  <div class="wrap">
    <div class="frow">
      <div><b>Pulse of the Pacific</b> — data produced by NOAA/CPC (public domain). Independent educational project; not an official NOAA product.</div>
      <div class="tag">Archive regenerated automatically · {_esc(s['generated'])}</div>
    </div>
    <div class="frow arch-back"><a href="../">← Back to the tracker</a></div>
  </div>
</footer>

</body>
</html>
"""
    write_if_changed(os.path.join(ARCH, "index.html"), html)

# --------------------------------------------------------------------- main
def _size(fn):
    p = os.path.join(ARCH, fn)
    return f"{max(1, round(os.path.getsize(p) / 1024))} KB" if os.path.exists(p) else "—"

def main():
    os.makedirs(VINT, exist_ok=True)
    docs = {k: load(spec[0]) for k, spec in VINTAGE_SPECS.items()}
    status = load("status.json")

    # 1. series tables
    oni   = export_seasonal(docs["oni"],  "oni.csv",  "oni_anomaly_c")
    roni  = export_seasonal(docs["roni"], "roni.csv", "roni_anomaly_c")
    wk    = export_weekly(docs["wksst"])
    soi   = export_monthly(docs["soi"],  "soi_3month.csv", "soi_3month")
    heat  = export_monthly(docs["heat"], "heat_content_180w_100w.csv", "heat_content_anomaly_c")
    merged_n = export_merged(oni, roni, soi, heat, wk)

    # 2. revision record (append-only)
    added = {k: update_vintage_file(k, docs[k]) for k in VINTAGE_SPECS}
    summ  = {k: vintage_summary(k) for k in VINTAGE_SPECS}
    starts = [v[2] for v in summ.values() if v[2]]
    vint_start = min(starts) if starts else None

    # 3. run log
    runs_n = update_run_log(status, vint_start)

    # 4. documentation, page, manifest — stamped from the data, never the clock
    stamps = [d["meta"]["updated"] for d in docs.values() if d and (d.get("meta") or {}).get("updated")]
    generated = (status or {}).get("updated") or (max(stamps) if stamps else "unknown")
    generated = generated.replace("T", " ").replace("Z", " UTC") if "T" in generated else generated
    seas = lambda pair: f"{pair[0]['s']} {pair[0]['y']}"
    ym   = lambda r: "{} {}".format(MONTH_ABBR[month_of(r["t"])[1] - 1], month_of(r["t"])[0])
    s = {
        "generated": generated,
        "oni_n": len(oni),   "oni_span":  _span(seas(oni[0]), seas(oni[-1])) if oni else "n/a",
        "oni_latest": seas(oni[-1]) if oni else "n/a",
        "roni_n": len(roni), "roni_span": _span(seas(roni[0]), seas(roni[-1])) if roni else "n/a",
        "wk_n": len(wk),     "wk_span":   _span(week_date(wk[0]), week_date(wk[-1])) if wk else "n/a",
        "soi_n": len(soi),   "soi_span":  _span(ym(soi[0]), ym(soi[-1])) if soi else "n/a",
        "heat_n": len(heat), "heat_span": _span(ym(heat[0]), ym(heat[-1])) if heat else "n/a",
        "merged_n": merged_n,
        "vint_rows": sum(v[0] for v in summ.values()),
        "vint_start": vint_start or "n/a",
        "rev_oni": summ["oni"][1], "rev_roni": summ["roni"][1], "rev_wksst": summ["wksst"][1],
        "rev_soi": summ["soi"][1], "rev_heat": summ["heat"][1],
        "runs_n": runs_n,
    }
    write_readme(s)

    def vdesc(key, label):
        n, revised, _ = summ[key]
        return f"{label} revision record — {n} values, {revised} period{'s' if revised != 1 else ''} revised"
    files = [
        ("enso_monthly_merged.csv", "All series on one monthly axis — start here"),
        ("oni.csv", f"Oceanic Niño Index, {s['oni_span']}"),
        ("roni.csv", f"Relative ONI (NOAA's official index since Feb 2026), {s['roni_span']}"),
        ("nino34_weekly.csv", f"Weekly Niño-3.4 SST anomaly, {s['wk_span']}"),
        ("soi_3month.csv", f"Southern Oscillation Index, 3-month mean, {s['soi_span']}"),
        ("heat_content_180w_100w.csv", f"Upper-300 m heat anomaly 180°W–100°W, {s['heat_span']}"),
        ("vintages/oni_vintages.csv", vdesc("oni", "ONI")),
        ("vintages/roni_vintages.csv", vdesc("roni", "RONI")),
        ("vintages/nino34_weekly_vintages.csv", vdesc("wksst", "Weekly Niño-3.4")),
        ("vintages/soi_vintages.csv", vdesc("soi", "SOI")),
        ("vintages/heat_content_vintages.csv", vdesc("heat", "Heat content")),
        ("pipeline_runs.csv", f"Refresh log — {runs_n} runs"),
        ("README_DATA.md", "Data dictionary, conventions, caveats, citation"),
    ]
    files = [(f, d) for f, d in files if os.path.exists(os.path.join(ARCH, f))]
    write_index_html(s, [(f, _size(f), d) for f, d in files])
    write_if_changed(os.path.join(ARCH, "manifest.json"),
                     json.dumps({"generated": s["generated"], "site": f"{SITE_URL}/archive/",
                                 "files": [f for f, _ in files] + ["manifest.json", "index.html"],
                                 "stats": s}, indent=2, ensure_ascii=False) + "\n")
    print(f"  archive: oni={s['oni_n']} roni={s['roni_n']} weekly={s['wk_n']} soi={s['soi_n']} "
          f"heat={s['heat_n']} merged={merged_n} | vintage rows +{sum(added.values())} "
          f"(total {s['vint_rows']}) | runs logged {runs_n}")
    return s

if __name__ == "__main__":
    main()
