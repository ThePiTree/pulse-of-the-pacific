# Pulse of the Pacific — Data Archive

Generated from the pipeline run of 2026-11-13 09:44:35 UTC by `scripts/export_archive.py`.
The archive is regenerated at the end of every scheduled data refresh (Mondays and
Thursdays), so these files are exactly as current as the live site at https://elninotracker.org.

**Every series here is produced by NOAA's Climate Prediction Center (CPC).** This archive
is a convenience re-publication in analysis-ready CSV — consistent headers, a data
dictionary, and a record of revisions. The authoritative numbers are NOAA's, and NOAA data
is in the public domain. Cite NOAA CPC as the producer and this archive as the access point
(citation at the end).

## Files

| File | Rows | Coverage | What it is |
|---|---|---|---|
| `enso_monthly_merged.csv` | 923 | all series | Every series on one monthly axis. **Start here.** |
| `oni.csv` | 921 | DJF 1950 → ASO 2026 | Oceanic Niño Index: 3-month running mean of sea-surface-temperature anomalies in the Niño-3.4 region (5°N–5°S, 170°W–120°W), from NOAA's ERSST analysis (ERSSTv6 as of 2026) against centered 30-year base periods that NOAA updates every 5 years. NOAA's long-standing ENSO index. |
| `roni.csv` | 921 | DJF 1950 → ASO 2026 | Relative ONI: the Niño-3.4 anomaly minus the tropical-mean (20°S–20°N) SST anomaly, rescaled to the ONI's variance. **NOAA's official index for ENSO monitoring and prediction since February 2026.** Strong El Niños read several tenths of a degree lower than on the ONI. |
| `nino34_weekly.csv` | 2358 | 1981-09-02 → 2026-11-04 | Weekly Niño-3.4 SST anomaly from CPC's OISST-based weekly table (1991–2020 base period). The freshest surface signal. Each date is the Wednesday the week is centered on. |
| `soi_3month.csv` | 907 | Feb 1951 → Aug 2026 | 3-month running mean of the Southern Oscillation Index (standardized Tahiti-minus-Darwin sea-level pressure), as published by CPC. Negative during El Niño. |
| `heat_content_180w_100w.csv` | 574 | Jan 1979 → Oct 2026 | Upper-ocean (0–300 m) temperature anomaly averaged over the equatorial Pacific, 180°W–100°W. Subsurface heat leads the surface by months. |
| `vintages/*.csv` | 5695 | since 2026-08-17 | **The revision record** — one file per series; see below. |
| `pipeline_runs.csv` | 28 | since 2026-08-17 | Append-only log of every data refresh: UTC timestamp, sources refreshed, sources that failed. |
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
the long historical record that is the archive's first run (2026-08-17), not the date NOAA
originally published it. And weekly values older than about ten years entered the archive in
November 2026, when it began keeping NOAA's full weekly record rather than a rolling window.

Revised periods so far — ONI: 0 · RONI: 1 · weekly Niño-3.4: 7 · SOI: 0 · heat content: 3.

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
> heat content. Accessed via the *Pulse of the Pacific* data archive, https://elninotracker.org/archive/ ,
> data as of 2026-11-13.

For a fixed, recoverable snapshot cite a release bundle by its tag (for example
`data-2026-11`) from https://github.com/ThePiTree/pulse-of-the-pacific/releases .

Source files: https://www.cpc.ncep.noaa.gov/data/indices/ (`oni.ascii.txt`, `RONI.ascii.txt`,
`wksst9120.for`, `soi.3m.txt`) and
https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt

## Reproducing any past state

Every refresh is a git commit, so the complete JSON served on any date is recoverable from
https://github.com/ThePiTree/pulse-of-the-pacific with `git show <commit>:public/data/oni.json`.
`scripts/backfill_vintages.py` rebuilds the whole revision record from that history.
