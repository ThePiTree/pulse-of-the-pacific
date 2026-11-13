# Test fixtures — NOAA's published ENSO tables

These two files freeze what NOAA's Climate Prediction Center published on 12 November 2026,
side by side with the two-decimal values of NOAA's data files as this site served them that
week (commit `fc4eb32`, data refresh of 2026-11-10). `tests/test_rule.py` uses them to prove
that `scripts/enso_rule.py` labels El Niño and La Niña seasons the way NOAA's tables do.

| File | Rows | Columns |
|---|---|---|
| `noaa_oni_table.tsv` | 920 (DJF 1950 – JAS 2026) | year, season, file value (2 decimals), table value (1 decimal), colored as an episode in NOAA's table (1/0) |
| `noaa_roni_table.tsv` | 921 (DJF 1950 – ASO 2026) | year, season, file value (2 decimals), table value (1 decimal) |

Sources:

- ONI table — https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/index.php
- Relative ONI table — https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni
- File values — `oni.ascii.txt` and `RONI.ascii.txt` at https://www.cpc.ncep.noaa.gov/data/indices/

**They are frozen on purpose. Do not regenerate them from live data.** NOAA revises recent
values and periodically re-bases the whole record; a fixture that tracked the live files would
stop being evidence of anything.

## How they were made, and how far to trust them

The table values were transcribed from NOAA's two web pages by an automated page reader, three
blocks of years per page, and then checked against the data files rather than by eye:

- For every value that is **not** an exact half (0.x5), the table value equals the file value
  rounded to one decimal: 830 of 830 for the ONI and 834 of 834 for the Relative ONI. A
  transcription slip would almost certainly have broken that.
- One cell was re-read individually (DJF 1952, ONI) because its coloring had been dropped in the
  first pass. The Relative ONI page's coloring was not present in the text that was read, so that
  fixture carries values only.

## What they show

1. **NOAA applies the ±0.5 °C threshold to the one-decimal value it prints, not to the
   two-decimal value in its file.** The coloring of the ONI table equals "five or more
   consecutive seasons at or beyond ±0.5" computed on the printed values for all 920 seasons.
   Computed on the two-decimal file values instead, 46 seasons come out differently and whole
   episodes disappear — among them La Niña AMJ–SON 1954, El Niño ASO 1969–DJF 1970 and
   El Niño SON 1979–JFM 1980.
2. **An exact half is printed rounded up** — toward the warmer value, so 0.45 → 0.5 and
   −0.45 → −0.4 — in 87 of 90 cases for the ONI and 80 of 87 for the Relative ONI. The remaining
   ten go the other way, presumably because NOAA's table is produced from digits beyond the two
   it publishes; nothing in a two-decimal file can predict them.
3. With that convention, `enso_rule.episode_codes()` reproduces NOAA's ONI coloring for **all 920
   seasons**, and the five-season rule on NOAA's printed Relative ONI values for **917 of 921**.
   The four exceptions are FMA–MJJ 1984: NOAA's file has FMA 1984 = −0.45, its table prints
   −0.5 (one of the ten), and that single cell joins two La Niña runs.

The exact halves that NOAA prints rounded *down*:

- ONI: DJF 1964 (0.95 → 0.9), JFM 2021 (−0.85 → −0.9), AMJ 2026 (0.95 → 0.9)
- Relative ONI: JJA 1967 (0.25 → 0.2), DJF 1979 (0.35 → 0.3), FMA 1984 (−0.45 → −0.5),
  AMJ 1987 (0.85 → 0.8), JJA 2006 (0.15 → 0.1), MAM 2020 (−0.25 → −0.3), OND 2022 (−1.05 → −1.1)

Only FMA 1984 sits on the ±0.5 threshold, which is why it is the only one that changes a label.

## If a test here ever fails

It means `scripts/enso_rule.py` (or `public/assets/app.js`, which carries the same rule for the
browser and is checked by `tests/test_frontend.mjs`) was changed — not that NOAA changed. Read
the docstring of `enso_rule.py` before touching either.
