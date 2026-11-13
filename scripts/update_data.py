#!/usr/bin/env python3
"""
update_data.py — the backend of "Pulse of the Pacific".

Run on a schedule by GitHub Actions (.github/workflows/update-data.yml), or by
hand: `python3 scripts/update_data.py`. It fetches the latest official ENSO
indices from NOAA, validates them, writes compact JSON into public/data/,
records full operational telemetry into public/data/status.json — which the
admin dashboard (public/admin.html) renders — and finally regenerates the
public CSV archive (scripts/export_archive.py -> public/archive/).

SERIES (all free, no API keys)
  oni    ONI            monthly   3-month Nino-3.4 SST anomaly (defines ENSO phase)
  roni   Relative ONI   monthly   NOAA's operational index since Feb 2026
  wksst  Weekly N3.4    weekly    freshest surface pulse (Mondays); full record
  soi    SOI 3-mo       monthly   atmospheric side of the oscillation
  heat   Upper-300m T'  monthly   subsurface "fuel gauge" (180W-100W)

SECURITY / RESILIENCE MODEL
  * Fixed HTTPS allowlist of NOAA URLs — nothing user-supplied is ever fetched.
  * Response size hard cap (5 MB) and connect timeout; 2 retries w/ backoff.
  * Every parsed series passes VALIDATION GATES (min records, value ranges,
    duplicate/monotonic time checks, and a no-shrink check against the record
    already on disk) before it may overwrite last-good JSON.
  * Any failure keeps the previous file, is logged to status.json, and the
    process still exits 0 — a bad NOAA day can never blank the site.
  * Stdlib only: zero third-party Python dependencies to supply-chain-audit.
"""
import json, sys, os, re, time, datetime, traceback, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # sibling modules, however we are run
import enso_rule

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "..", "public", "data")
os.makedirs(OUT, exist_ok=True)

SEASONS = ["DJF","JFM","FMA","MAM","AMJ","MJJ","JJA","JAS","ASO","SON","OND","NDJ"]
MONTHS  = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
UA = {"User-Agent": "PulseOfThePacific/2.0 (scheduled data refresh)"}
MAX_BYTES = 5_000_000
TIMEOUT_S = 30
RETRIES   = 2          # additional attempts after the first
BACKOFF_S = (1, 4)

# The complete, fixed allowlist of what this backend will ever fetch.
URLS = {
    "oni":   "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "roni":  "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
    "wksst": "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for",
    "soi":   "https://www.cpc.ncep.noaa.gov/data/indices/soi.3m.txt",
    "heat":  "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt",
}
# Expected refresh cadence in days (admin page flags STALE past 1.5x this).
CADENCE_DAYS = {"oni":35, "roni":35, "wksst":9, "soi":35, "heat":40}
# Oldest the NEWEST datum of each series may be (days, measured from the centre
# of its period) before the dashboard flags the series as "not advancing" even
# though fetches succeed. Normal worst cases: ONI/RONI ~90 d (a season centred
# on month m is published early in month m+2), weekly ~15 d, heat ~60 d,
# 3-month SOI ~90 d. Each limit leaves roughly one missed release of slack.
DATA_AGE_LIMIT_DAYS = {"oni":115, "roni":115, "wksst":30, "soi":120, "heat":90}
# A refreshed series may be at most this many records SHORTER than the copy on
# disk. Real series only grow; a shorter one means a truncated download.
SHRINK_TOLERANCE = 2
SOURCE_LABELS = {
    "oni":  "NOAA Climate Prediction Center - Oceanic Nino Index (oni.ascii.txt)",
    "roni": "NOAA Climate Prediction Center - Relative Oceanic Nino Index (RONI.ascii.txt)",
}
# Written into oni.json / roni.json so that anyone reading the files knows what `c` means.
CLASSIFICATION_NOTE = ("c: E = El Nino episode, L = La Nina episode, N = neither. An episode is >= 5 "
                       "consecutive overlapping seasons with the index at or beyond +/-0.5 C, the threshold "
                       "being applied to the value rounded to one decimal (halves up), as NOAA tabulates it.")
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ------------------------------------------------------------------ utilities
def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def fetch(url):
    """GET with timeout, size cap, and retry/backoff. Returns decoded text."""
    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                if getattr(r, "status", 200) != 200:
                    raise urllib.error.HTTPError(url, r.status, "non-200", r.headers, None)
                data = r.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError(f"response exceeds {MAX_BYTES} byte cap")
                return data.decode("utf-8", "replace")
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S)-1)])
    raise last_err

def err_text(e):
    """An exception as ONE bounded line. The text is stored in status.json, shown on
    admin.html and printed in the run log, so it must never span lines (a line that
    starts with '::' is a command to GitHub Actions) or grow without limit."""
    return " ".join(f"{type(e).__name__}: {e}".split())[:300]

def annotate(title, msg):
    """Put a warning on the GitHub Actions run page. A no-op anywhere else."""
    if os.environ.get("GITHUB_ACTIONS"):
        safe = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title={title}::{safe}")

def load_json(name):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        try:
            with open(p) as f: return json.load(f)
        except Exception:
            return None
    return None

def write_json(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))

def classify(recs):
    """Label every season E (El Nino episode), L (La Nina episode) or N.

    NOAA's rule: the index at or beyond +/-0.5 C for >= 5 consecutive overlapping
    3-month seasons - with the threshold applied to the value as NOAA TABULATES it
    (one decimal), not to the two-decimal file value. The rule, and the evidence
    for that detail, live in scripts/enso_rule.py."""
    for r, c in zip(recs, enso_rule.episode_codes([r["v"] for r in recs])):
        r["c"] = c
    return recs

# ------------------------------------------------------------------- parsers
def parse_seasonal(txt, anom_col):
    """CPC seasonal rows: SEAS YR [cols...]. Returns [{y,s,m,t,v}]."""
    recs = []
    for line in txt.strip().splitlines():
        p = line.split()
        if len(p) <= anom_col: continue
        seas = p[0]
        if seas not in SEASONS: continue
        try:
            yr = int(p[1]); anom = float(p[anom_col])
        except (ValueError, IndexError):
            continue
        si = SEASONS.index(seas)
        recs.append({"y":yr,"s":seas,"m":si+1,"t":round(yr+(si+0.5)/12,4),"v":anom})
    return recs

_WK_DATE = re.compile(r"^\s*(\d{2})([A-Z]{3})(\d{4})(.*)$")
_FLOAT   = re.compile(r"[-+]?\d+\.\d+")
def parse_wksst(txt):
    """Weekly Nino SST file (wksst9120.for). CRITICAL FORMAT NOTE: this is
    Fortran fixed-width; when an anomaly is negative there is NO SPACE between
    the SST and the anomaly (e.g. '23.4-0.5'). Whitespace-splitting silently
    drops those lines — which is every La Nina week. We therefore regex-extract
    the date, then pull all floats from the remainder:
      [N1+2, N1+2a, N3, N3a, N3.4, N3.4a, N4, N4a]  ->  N3.4 anomaly = index 5.
    Returns the FULL record as [{t, v, d}], oldest first. `d` is the exact ISO
    date printed in the file (the Wednesday the week is centred on); `t` is the
    fractional-year form the charts use. Rows are de-duplicated on the date
    (last occurrence wins) so a repeated line can never fail validation."""
    by_date = {}
    mon = {m:i for i,m in enumerate(MONTHS)}
    for line in txt.splitlines():
        m = _WK_DATE.match(line)
        if not m: continue
        day, mo3, yr, rest = int(m.group(1)), m.group(2).upper(), int(m.group(3)), m.group(4)
        if mo3 not in mon: continue
        nums = _FLOAT.findall(rest)
        if len(nums) < 8: continue
        try:
            sst34 = float(nums[4]); n34a = float(nums[5])
        except ValueError:
            continue
        # physical sanity: tropical Pacific SST 18..35 C; anomalies within +/-6
        if not (18.0 < sst34 < 35.0) or abs(n34a) > 6.0: continue
        try:
            date = datetime.date(yr, mon[mo3]+1, day)
        except ValueError:
            continue
        doy = date.timetuple().tm_yday
        by_date[date] = {"t": round(yr + doy/365.25, 4), "v": n34a, "d": date.isoformat()}
    return [by_date[k] for k in sorted(by_date)]

# A '-' that directly follows a digit or '.' is the start of a new number that
# Fortran printed with no separating space (see parse_soi).
_UNGLUE = re.compile(r"(?<=[0-9.])-")
def parse_soi(txt):
    """soi.3m.txt: a YEAR JAN..DEC matrix written by Fortran as I4,12F6.1 with
    -999.9 for missing months.

    CRITICAL FORMAT NOTE: -999.9 fills its whole 6-character field, so it is
    printed with NO SPACE before it. Two rows are affected on every run:
        1951-999.9   1.5   0.9 ...        (first year: January is missing)
        2026  -0.7  -0.9 ...  -2.9-999.9-999.9-999.9   (current year: months
                                                        not yet published)
    Whitespace-splitting therefore sees the wrong number of tokens and — when
    exactly 13 tokens were required — silently dropped the whole current year.
    That froze the live SOI series at December 2025 from launch until this was
    found in November 2026. We un-glue first (insert a space before any '-'
    that directly follows a digit), then read YEAR + up to 12 months, so full
    rows, glued rows and genuinely short rows all parse.

    Some CPC SOI files carry a second (standardized) table with the same shape:
    values are de-duplicated on time, the LAST occurrence winning, so the later
    table is used consistently."""
    by_t = {}
    for line in txt.splitlines():
        p = _UNGLUE.sub(" -", line).split()
        if not (2 <= len(p) <= 13): continue
        if len(p[0]) != 4 or not p[0].isdigit(): continue
        yr = int(p[0])
        if yr < 1950 or yr > 2100: continue
        for mi, tok in enumerate(p[1:13]):
            try: val = float(tok)
            except ValueError: continue
            if val <= -999 or abs(val) > 8: continue
            by_t[round(yr+(mi+0.5)/12,4)] = val
    return [{"t":t,"v":v} for t,v in sorted(by_t.items())]

def parse_heat(txt):
    """heat_content_index.txt: YR MON <3 basin anomalies>; use 180W-100W (col 5).
    Missing flags vary (-9.99 / -99.9 / -999): physical upper-300m anomalies
    never exceed ~+/-5 C, so reject |v| > 8."""
    out = []
    for line in txt.splitlines():
        p = line.split()
        if len(p) < 5 or not p[0].isdigit(): continue
        try:
            yr = int(p[0]); mo = int(p[1]); val = float(p[4])
        except (ValueError, IndexError):
            continue
        if not (1 <= mo <= 12) or abs(val) > 8: continue
        out.append({"t": round(yr+(mo-0.5)/12,4), "v": val})
    out.sort(key=lambda r: r["t"])
    return out                      # full record (Jan 1979 ->); ~15 KB

# ---------------------------------------------------------- validation gates
def validate_series(recs, min_len, vmax=6.0):
    """Gate every series before it may overwrite last-good data."""
    if len(recs) < min_len:
        raise ValueError(f"only {len(recs)} records (< {min_len} required)")
    ts = [r["t"] for r in recs]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError("time axis not strictly increasing (duplicates or disorder)")
    bad = [r for r in recs if abs(r["v"]) > vmax]
    if bad:
        raise ValueError(f"{len(bad)} values outside physical range +/-{vmax} (e.g. {bad[0]})")
    return recs

def guard_shrink(name, recs):
    """Refuse to replace a series with a noticeably SHORTER one. NOAA's series
    only ever grow, so a shorter record means a truncated or partial download —
    and because public/archive/ is regenerated from these files, accepting it
    would silently delete published history. To accept a genuinely shorter
    record (NOAA restructured a product), delete the old JSON file and re-run."""
    prev = load_json(name) or {}
    old_n = len(prev.get("records") or [])
    if len(recs) < old_n - SHRINK_TOLERANCE:
        raise ValueError(f"record shrank from {old_n} to {len(recs)} - refusing to overwrite "
                         f"(delete public/data/{name} to accept a shorter record)")
    return recs

def month_label(t):
    """Fractional year at a month centre -> 'Sep 2026'."""
    y = int(t); m = min(11, max(0, int(round((t - y) * 12 - 0.5))))
    return f"{MONTH_ABBR[m]} {y}"

# ------------------------------------------------------------------ updaters
def _result(ok, **kw):
    d = {"ok": ok}; d.update(kw); return d

def refresh_seasonal(key, name, label, min_len, note):
    t0 = time.time()
    try:
        txt = fetch(URLS[key])
        recs = parse_seasonal(txt, anom_col=3)
        if len(recs) < min_len:                       # RONI layout: SEAS YR ANOM
            recs = parse_seasonal(txt, anom_col=2)
        recs = validate_series(sorted(recs, key=lambda r: r["t"]), min_len)
        recs = classify(guard_shrink(name, recs))
        prev = load_json(name) or {}
        meta = prev.get("meta", {})
        meta.update({"index": label, "source": SOURCE_LABELS[key], "source_url": URLS[key],
                     "threshold": 0.5, "seasons": SEASONS, "updated": utcnow(), "note": note,
                     "classification": CLASSIFICATION_NOTE})
        write_json(name, {"meta": meta, "records": recs})
        last = recs[-1]
        return _result(True, records=len(recs), latest=f"{last['s']} {last['y']}",
                       value=last["v"], latest_t=last["t"],
                       duration_ms=int((time.time()-t0)*1000))
    except Exception as e:
        return _result(False, error=err_text(e),
                       duration_ms=int((time.time()-t0)*1000))

def refresh_simple(key, name, parser, label, min_len, unit):
    t0 = time.time()
    try:
        recs = validate_series(parser(fetch(URLS[key])), min_len, vmax=8.0)
        recs = guard_shrink(name, recs)
        write_json(name, {"meta": {"series": label, "source_url": URLS[key],
                                   "unit": unit, "updated": utcnow()},
                          "records": recs})
        last = recs[-1]
        latest = f"week of {last['d']}" if "d" in last else month_label(last["t"])
        return _result(True, records=len(recs), latest=latest,
                       value=last["v"], latest_t=last["t"],
                       duration_ms=int((time.time()-t0)*1000))
    except Exception as e:
        return _result(False, error=err_text(e),
                       duration_ms=int((time.time()-t0)*1000))

# --------------------------------------------------- manifest + status files
def update_manifest():
    series = {"oni": True, "events": True, "impacts": True, "roni_compare": True}
    for key, fname in [("roni","roni.json"),("wksst","wksst.json"),
                       ("soi","soi.json"),("heat","heat.json")]:
        series[key] = os.path.exists(os.path.join(OUT, fname))
    write_json("manifest.json",
               {"note": "Maintained by update_data.py; lists available series.",
                "updated": utcnow(), "series": series})
    return series

def update_status(results):
    """public/data/status.json — the admin dashboard's data source."""
    prev = load_json("status.json") or {}
    history = prev.get("history", [])
    fails = [k for k, r in results.items() if not r["ok"]]
    history.append({"ts": utcnow(), "ok": len(results)-len(fails), "fail": fails})
    history = history[-30:]
    sources = {}
    for k, r in results.items():
        entry = dict(r)
        entry["url"] = URLS[k]
        entry["cadence_days"] = CADENCE_DAYS[k]
        entry["data_age_limit_days"] = DATA_AGE_LIMIT_DAYS[k]
        if r["ok"]:
            entry["updated"] = utcnow()
            # Age of the newest DATUM in days, measured from the centre of its
            # period. This is what lets the dashboard tell "fetched fine" apart
            # from "fetched fine but the series has stopped advancing" — the
            # failure that hid the frozen SOI series behind a green badge.
            now_t = datetime.datetime.now(datetime.timezone.utc)
            now_frac = now_t.year + (now_t.timetuple().tm_yday - 0.5) / 365.25
            entry["data_age_days"] = round((now_frac - r.get("latest_t", now_frac)) * 365.25)
        else:
            # keep the last successful stamp so staleness is measurable
            old = (prev.get("sources") or {}).get(k, {})
            if "updated" in old: entry["updated"] = old["updated"]
        sources[k] = entry
    write_json("status.json", {
        "updated": utcnow(),
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "manual"),
        "sources": sources,
        "history": history,
        "note": "Operational telemetry written by scripts/update_data.py; rendered by admin.html.",
    })
    return fails

# ----------------------------------------------------------------------- main
def main():
    print(f"== Pulse of the Pacific data refresh @ {utcnow()} ==")
    results = {
        "oni":   refresh_seasonal("oni",  "oni.json",  "ONI",
                    800, "Live-refreshed from NOAA CPC oni.ascii.txt"),
        "roni":  refresh_seasonal("roni", "roni.json", "RONI",
                    700, "NOAA operational Relative ONI (since Feb 2026)"),
        "wksst": refresh_simple("wksst", "wksst.json", parse_wksst,
                    "Weekly Nino-3.4 SST anomaly", 100, "degC"),
        "soi":   refresh_simple("soi",   "soi.json",   parse_soi,
                    "Southern Oscillation Index (3-mo)", 300, "std"),
        "heat":  refresh_simple("heat",  "heat.json",  parse_heat,
                    "Equatorial Pacific upper-300m heat anomaly", 200, "degC"),
    }
    for k, r in results.items():
        mark = "ok " if r["ok"] else "FAIL"
        detail = (f"{r.get('records','?')} recs, latest {r.get('latest','?')} = {r.get('value','?')}"
                  if r["ok"] else r.get("error",""))
        print(f"  [{mark}] {k:5s} {detail}  ({r['duration_ms']} ms)")
        if not r["ok"]:
            annotate("ENSO source not refreshed", f"{k}: {detail} - the site keeps the last good copy. See OPERATIONS_RUNBOOK.md.")
    update_manifest()
    fails = update_status(results)
    # Regenerate the public CSV archive from the JSON just written. Isolated in
    # its own try: an archive problem must never cost the site its data refresh.
    try:
        import export_archive
        export_archive.main()
    except Exception as e:
        print(f"  archive export FAILED (site data unaffected): {err_text(e)}", file=sys.stderr)
        annotate("Archive export failed", f"{err_text(e)} - site data is unaffected, but public/archive/ was not rebuilt.")
    print(f"Done. {len(results)-len(fails)}/{len(results)} refreshed."
          + ("" if not fails else f" Failed (kept last-good): {', '.join(fails)}"))
    sys.exit(0)      # never break the workflow; failures live in status.json

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
