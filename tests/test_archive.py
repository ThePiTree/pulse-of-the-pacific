#!/usr/bin/env python3
"""
Tests for the CSV archive (scripts/export_archive.py, scripts/backfill_vintages.py)
and an END-TO-END run of the whole pipeline against NOAA-format fixture files.

    python3 tests/test_archive.py        # or: python3 tests/run_all.py

Nothing here touches the network or the real public/ tree: the pipeline is run
in a temporary directory with update_data.fetch() replaced by fixtures written
in NOAA's actual layouts (Fortran fixed-width, glued missing flags and all).
"""
import contextlib, csv, datetime, io, json, math, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import update_data as U
import export_archive as X
import backfill_vintages as B

PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")

# =========================================================== unit: helpers
ok("fmt: canonical two decimals", X.fmt(2.5) == "2.50" and X.fmt(-0.04) == "-0.04" and X.fmt("1.97") == "1.97")
ok("month_of: month-centre time -> (year, month)",
   X.month_of(round(2026 + 8.5/12, 4)) == (2026, 9) and X.month_of(round(2026 + 0.5/12, 4)) == (2026, 1)
   and X.month_of(round(2025 + 11.5/12, 4)) == (2025, 12))
ok("week_date: uses the exact date when present", X.week_date({"t": 2026.8433, "d": "2026-11-04"}) == "2026-11-04")
def t_of(d): return round(d.year + d.timetuple().tm_yday / 365.25, 4)        # the pipeline's formula
for d in [datetime.date(2026, 11, 4), datetime.date(2026, 1, 1), datetime.date(2025, 12, 31),
          datetime.date(2024, 12, 25), datetime.date(2016, 11, 23), datetime.date(2020, 2, 29),
          datetime.date(2008, 12, 31),      # day 366 of a leap year: stored past the year boundary
          datetime.date(2009, 1, 1)]:
    ok(f"week_date: recovers {d} from t alone (pre-Nov-2026 snapshots)", X.week_date({"t": t_of(d)}) == d.isoformat())
# every Wednesday for 40 years round-trips
d0, bad = datetime.date(1990, 1, 3), 0
for i in range(2090):
    d = d0 + datetime.timedelta(weeks=i)
    bad += X.week_date({"t": t_of(d)}) != d.isoformat()
ok("week_date: 2,090 consecutive weekly dates all round-trip", bad == 0)
ok("seen_date: date part of meta.updated", X.seen_date({"meta": {"updated": "2026-11-10T00:11:44Z"}}) == "2026-11-10")
ok("seen_date: None without a run stamp", X.seen_date({"meta": {}}) is None and X.seen_date(None) is None)

# ================================================= unit: classification labels
def seas(vals):
    recs = [{"v": v, "y": 2000 + i // 12, "s": U.SEASONS[i % 12], "m": i % 12 + 1} for i, v in enumerate(vals)]
    return U.classify(recs)
lab = X.season_labels(seas([0.0, 0.6, 0.7, 0.8, 0.9, 1.0, 0.2, -0.6, -0.7, 0.0]))
ok("labels: a completed 5-season run is El Nino", lab[1:6] == ["El Nino"] * 5)
ok("labels: a short run in mid-record stays Neutral", lab[7:9] == ["Neutral", "Neutral"])
lab = X.season_labels(seas([-0.04, 0.49, 0.97, 1.36, 1.69, 1.97]))                # RONI, AMJ-ASO 2026, as served
ok("labels: 0.49 is tabulated as 0.5, so RONI's 2026 run is already a five-season El Nino",
   lab == ["Neutral"] + ["El Nino"] * 5)
lab = X.season_labels(seas([0.0, 0.44, 0.97, 1.36, 1.69, 1.97]))
ok("labels: trailing 4-season warm run is 'El Nino (pending)'", lab == ["Neutral", "Neutral"] + ["El Nino (pending)"] * 4)
lab = X.season_labels(seas([0.0, 0.44, 0.97, 1.36, 1.69, 1.97, 2.2]))
ok("labels: the fifth season confirms the whole run", lab[2:] == ["El Nino"] * 5)
lab = X.season_labels(seas([0.2, 0.47, 0.50, 0.64, 0.62, 0.47, 0.35]))             # ONI, SON 1979 - JFM 1980
ok("labels: the 1979-80 El Nino (five seasons only after rounding to one decimal)", lab == ["Neutral"] + ["El Nino"] * 5 + ["Neutral"])
lab = X.season_labels(seas([-0.63, -0.45, -0.19, 0.0]))
ok("labels: -0.45 is tabulated as -0.4 and does not extend a La Nina", lab[1] == "Neutral")
lab = [{"v": v, "c": c} for v, c in zip([0.0, 0.47, 0.50, 0.64, 0.62, 0.47, 0.35], "NNNNNNN")]
ok("labels: computed from the values, never from a stale 'c' left in the JSON", X.season_labels(lab)[1:6] == ["El Nino"] * 5)
lab = X.season_labels(seas([0.3, -0.5, -0.9]))
ok("labels: trailing cool run is 'La Nina (pending)'", lab == ["Neutral", "La Nina (pending)", "La Nina (pending)"])
lab = X.season_labels(seas([0.9, 0.9, 0.3]))
ok("labels: a run that ended short is Neutral, not pending", lab == ["Neutral"] * 3)
ok("labels: empty input", X.season_labels([]) == [])

# ===================================================== unit: revision record
state = ([], {}, {})
a = X.apply_vintage(state, [(("2026", "JJA"), "1.80"), (("2026", "JAS"), "2.16")], "2026-10-05")
b = X.apply_vintage(state, [(("2026", "JJA"), "1.80"), (("2026", "JAS"), "2.16")], "2026-10-08")
c = X.apply_vintage(state, [(("2026", "JJA"), "1.80"), (("2026", "JAS"), "2.18"), (("2026", "ASO"), "2.46")], "2026-11-05")
d = X.apply_vintage(state, [(("2026", "JAS"), "2.16")], "2026-11-09")
ok("vintage: first snapshot records every period", a == 2)
ok("vintage: an unchanged snapshot adds nothing", b == 0)
ok("vintage: a revision and a new period add one row each", c == 2)
ok("vintage: reverting to an earlier value is itself a revision", d == 1)
ok("vintage: rows are [first_seen, *period, value, revision]",
   state[0] == [["2026-10-05", "2026", "JJA", "1.80", "0"], ["2026-10-05", "2026", "JAS", "2.16", "0"],
                ["2026-11-05", "2026", "JAS", "2.18", "1"], ["2026-11-05", "2026", "ASO", "2.46", "0"],
                ["2026-11-09", "2026", "JAS", "2.16", "2"]])
ok("vintage_items: weekly keyed by exact date", X.vintage_items("wksst", [{"t": 2026.8433, "v": 3.3, "d": "2026-11-04"}]) == [(("2026-11-04",), "3.30")])
ok("vintage_items: monthly keyed by (year, month)", X.vintage_items("heat", [{"t": round(2026 + 9.5/12, 4), "v": 3.33}]) == [(("2026", "10"), "3.33")])
ok("vintage_items: seasonal keyed by (year, season)", X.vintage_items("oni", [{"y": 2026, "s": "ASO", "v": 2.46}]) == [(("2026", "ASO"), "2.46")])

# ================================================================ fixtures
def series(n, phase=0.0):
    """Deterministic ENSO-like wiggle, two decimals."""
    return [round(1.6 * math.sin(i / 7.0 + phase) + 0.3 * math.sin(i / 2.3), 2) for i in range(n)]

def seasons_through(last_year, last_idx):
    out = []
    for y in range(1950, last_year + 1):
        for i, s in enumerate(U.SEASONS):
            if y == last_year and i > last_idx: break
            out.append((s, y))
    return out

def oni_text(pairs):       # SEAS YR TOTAL ANOM
    return "SEAS  YR   TOTAL   ANOM\n" + "".join(f" {s} {y}   {26.5 + v:5.2f}  {v:5.2f}\n" for (s, y), v in pairs)
def roni_text(pairs):      # SEAS YR ANOM
    return "SEAS  YR   ANOM\n" + "".join(f" {s} {y}  {v:5.2f}\n" for (s, y), v in pairs)
def wk_text(pairs):        # Fortran: 9-wide SST immediately followed by a 4-wide anomaly
    head = " Weekly SST data starts week centered on 3Jan1990\n\n                Nino1+2      Nino3        Nino34        Nino4\n Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA\n"
    return head + "".join(f" {d.strftime('%d%b%Y').upper()}{24.0:9.1f}{0.3:4.1f}{26.0:9.1f}{-0.2:4.1f}{27.0 + v:9.1f}{v:4.1f}{28.5:9.1f}{0.1:4.1f}\n"
                          for d, v in pairs)
def soi_text(rows):        # I4,12F6.1, -999.9 missing
    head = "  (STAND TAHITI - STAND DARWIN)  SEA LEVEL PRESS    3-MONTH RUNNING MEAN\n\nYEAR   JAN   FEB   MAR   APR   MAY   JUN   JUL   AUG   SEP   OCT   NOV   DEC\n"
    return head + "".join(f"{y:4d}" + "".join(f"{(-999.9 if v is None else v):6.1f}" for v in vals) + "\n" for y, vals in rows)
def heat_text(rows):       # YR MON 130E-80W 160E-80W 180W-100W
    return " YR MON  130E-80W  160E-80W  180W-100W\n" + "".join(f" {y}  {m:2d}  {v-0.2:6.2f}  {v-0.1:6.2f}  {v:6.2f}\n" for (y, m), v in rows)

SE = seasons_through(2026, 8)                               # DJF 1950 .. ASO 2026  (921 seasons)
ONI  = list(zip(SE, series(len(SE))))
RONI = list(zip(SE, [round(v - 0.3, 2) for v in series(len(SE))]))
WK   = [(datetime.date(2026, 11, 4) - datetime.timedelta(weeks=299 - i), round(v, 1)) for i, v in enumerate(series(300, 1.0))]
_sv  = [round(v, 1) for v in series(76 * 12, 2.0)]
SOI  = [(1951 + k, [None if (k == 0 and m == 0) or (k == 75 and m >= 9) else _sv[k * 12 + m] for m in range(12)]) for k in range(76)]
HEAT = [((1979 + i // 12, i % 12 + 1), v) for i, v in enumerate(series(48 * 12 - 2, 3.0))]   # Jan 1979 .. Oct 2026

FX = {}
def set_fixtures(oni=ONI, roni=RONI, wk=WK, soi=SOI, heat=HEAT):
    FX.update({U.URLS["oni"]: oni_text(oni), U.URLS["roni"]: roni_text(roni), U.URLS["wksst"]: wk_text(wk),
               U.URLS["soi"]: soi_text(soi), U.URLS["heat"]: heat_text(heat)})

# ============================================== end-to-end pipeline, in a sandbox
root = tempfile.mkdtemp()
saved = (U.OUT, U.fetch, U.utcnow, X.DATA, X.ARCH, X.VINT, B.ROOT)
CLOCK = ["2026-11-05T21:57:07Z"]
def quiet(fn, *args):
    """Call fn with its console output captured, so the test log stays readable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*args)
def run_pipeline():
    def go():
        try:
            U.main()
        except SystemExit as e:
            return e.code
        return None
    return quiet(go)
def J(name):
    with open(os.path.join(U.OUT, name)) as f: return json.load(f)
def C(name):
    with open(os.path.join(X.ARCH, name), newline="") as f: return list(csv.reader(f))
def snapshot_tree():
    out = {}
    for dp, _, fs in os.walk(X.ARCH):
        for fn in fs:
            with open(os.path.join(dp, fn), "rb") as f: out[os.path.relpath(os.path.join(dp, fn), X.ARCH)] = f.read()
    return out
have_git = shutil.which("git") is not None
def commit(msg):
    if not have_git: return
    subprocess.run(["git", "-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", msg],
                   check=True, capture_output=True)
try:
    U.OUT = os.path.join(root, "public", "data"); os.makedirs(U.OUT)
    X.DATA = U.OUT; X.ARCH = os.path.join(root, "public", "archive"); X.VINT = os.path.join(X.ARCH, "vintages")
    B.ROOT = root
    U.fetch = lambda url: FX[url]
    U.utcnow = lambda: CLOCK[0]
    if have_git:
        subprocess.run(["git", "-C", root, "init", "-q"], check=True, capture_output=True)

    # ---------------------------------------------------------------- run 1
    set_fixtures()
    code = run_pipeline()
    st = J("status.json")
    ok("e2e run 1: exits 0", code == 0)
    ok("e2e run 1: all five sources refreshed", all(s["ok"] for s in st["sources"].values()) and len(st["sources"]) == 5)
    ok("e2e run 1: ONI = 921 classified seasons", len(J("oni.json")["records"]) == 921 and all("c" in r for r in J("oni.json")["records"]))
    ok("e2e run 1: RONI parsed through the 3-column fallback", len(J("roni.json")["records"]) == 921 and J("roni.json")["records"][-1]["v"] == RONI[-1][1])
    ok("e2e run 1: ONI source label no longer claims a dataset version", J("oni.json")["meta"]["source"] == U.SOURCE_LABELS["oni"])
    wk = J("wksst.json")["records"]
    ok("e2e run 1: weekly — full record, exact dates, glued negatives kept",
       len(wk) == 300 and wk[-1]["d"] == "2026-11-04" and any(r["v"] < 0 for r in wk) and wk[-1]["v"] == WK[-1][1])
    soi = J("soi.json")["records"]
    ok("e2e run 1: SOI — 1951 and the current year both present (11 + 74*12 + 9 = 908)", len(soi) == 908)
    ok("e2e run 1: SOI newest value is Sep 2026 (the month glued to -999.9)", X.month_of(soi[-1]["t"]) == (2026, 9) and soi[-1]["v"] == SOI[-1][1][8])
    ok("e2e run 1: heat — Jan 1979 .. Oct 2026", len(J("heat.json")["records"]) == 574 and X.month_of(J("heat.json")["records"][-1]["t"]) == (2026, 10))
    ok("e2e run 1: status carries readable 'latest' labels",
       [st["sources"][k]["latest"] for k in ("oni", "wksst", "soi", "heat")] == ["ASO 2026", "week of 2026-11-04", "Sep 2026", "Oct 2026"])
    ok("e2e run 1: status carries data age + per-source limit",
       all(isinstance(s.get("data_age_days"), int) and s.get("data_age_limit_days") == U.DATA_AGE_LIMIT_DAYS[k]
           and isinstance(s.get("latest_t"), float) for k, s in st["sources"].items()))
    ok("e2e run 1: manifest lists all live series", all(J("manifest.json")["series"][k] for k in ("oni", "roni", "wksst", "soi", "heat")))
    for f in ["enso_monthly_merged.csv", "oni.csv", "roni.csv", "nino34_weekly.csv", "soi_3month.csv", "heat_content_180w_100w.csv",
              "pipeline_runs.csv", "README_DATA.md", "manifest.json", "index.html"] + ["vintages/" + s[1] for s in X.VINTAGE_SPECS.values()]:
        ok(f"e2e run 1: archive/{f} written", os.path.exists(os.path.join(X.ARCH, f)))
    ok("e2e run 1: oni.csv has one row per season", len(C("oni.csv")) == 922 and C("oni.csv")[-1][:2] == ["2026", "ASO"])
    ok("e2e run 1: every archived value starts at revision 0 on the run date",
       all(r[0] == "2026-11-05" and r[-1] == "0" for r in C("vintages/oni_vintages.csv")[1:]) and len(C("vintages/oni_vintages.csv")) == 922)
    ok("e2e run 1: vintage rows = records, per series",
       [len(C("vintages/" + X.VINTAGE_SPECS[k][1])) - 1 for k in ("roni", "wksst", "soi", "heat")] == [921, 300, 908, 574])
    ok("e2e run 1: run log has exactly this run", C("pipeline_runs.csv")[1:] == [["2026-11-05T21:57:07Z", "5", ""]])
    merged = {(r[0], r[1]): r for r in C("enso_monthly_merged.csv")[1:]}
    sep = merged[("2026", "9")]
    ok("e2e run 1: merged row Sep 2026 joins ONI/RONI (ASO), SOI and heat",
       sep[3] == "ASO" and sep[4] == X.fmt(ONI[-1][1]) and sep[6] == X.fmt(RONI[-1][1]) and sep[8] == X.fmt(SOI[-1][1][8]) and sep[9] != "")
    oct_weeks = [v for d, v in WK if (d.year, d.month) == (2026, 10)]
    ok("e2e run 1: weekly mean groups by the calendar month of each week's date",
       merged[("2026", "10")][10] == X.fmt(sum(oct_weeks) / len(oct_weeks)) and merged[("2026", "10")][11] == str(len(oct_weeks)))
    ok("e2e run 1: no sentinel values leak into any CSV",
       not any("-999" in open(os.path.join(X.ARCH, f)).read() for f in ("soi_3month.csv", "enso_monthly_merged.csv", "heat_content_180w_100w.csv")))
    page = open(os.path.join(X.ARCH, "index.html"), encoding="utf-8").read()
    ok("e2e run 1: download page is static (no executable script) and links every CSV",
       "<script src" not in page and page.count("<script") == 1 and 'type="application/ld+json"' in page
       and all(f'href="{f}"' in page for f in ("oni.csv", "vintages/soi_vintages.csv", "README_DATA.md")))
    commit("run 1")

    # determinism: exporting again from unchanged data rewrites nothing
    before = snapshot_tree(); quiet(X.main); after = snapshot_tree()
    ok("export is deterministic: a second export changes no byte", before == after)

    # ------------------------------------------- run 2: a revision + new data
    CLOCK[0] = "2026-11-10T00:11:44Z"
    oni2 = ONI[:-2] + [(ONI[-2][0], round(ONI[-2][1] + 0.03, 2)), ONI[-1], (("SON", 2026), 2.71)]
    wk2 = WK[:-1] + [(WK[-1][0], round(WK[-1][1] - 0.1, 1)), (datetime.date(2026, 11, 11), 3.4)]
    set_fixtures(oni=oni2, wk=wk2)
    code = run_pipeline()
    v = C("vintages/oni_vintages.csv")[1:]
    ok("e2e run 2: ONI vintages gained exactly two rows", len(v) == 923)
    ok("e2e run 2: the revised season is recorded as revision 1 with its new value and date",
       ["2026-11-10", "2026", "JAS", X.fmt(oni2[-3][1]), "1"] in v)
    ok("e2e run 2: the original value of that season is still there (revision 0)",
       ["2026-11-05", "2026", "JAS", X.fmt(ONI[-2][1]), "0"] in v)
    ok("e2e run 2: the new season enters at revision 0", ["2026-11-10", "2026", "SON", "2.71", "0"] in v)
    wv = C("vintages/nino34_weekly_vintages.csv")[1:]
    ok("e2e run 2: weekly revision + new week recorded",
       ["2026-11-10", "2026-11-04", X.fmt(wk2[-2][1]), "1"] in wv and ["2026-11-10", "2026-11-11", "3.40", "0"] in wv and len(wv) == 302)
    ok("e2e run 2: untouched series gained no vintage rows", len(C("vintages/soi_vintages.csv")) - 1 == 908)
    ok("e2e run 2: run log is append-only", [r[0] for r in C("pipeline_runs.csv")[1:]] == ["2026-11-05T21:57:07Z", "2026-11-10T00:11:44Z"])
    ok("e2e run 2: oni.csv shows the current (revised) value",
       C("oni.csv")[-3][:2] == ["2026", "JAS"] and C("oni.csv")[-3][5] == X.fmt(oni2[-3][1]))
    commit("run 2")

    # --------------------------- run 3: truncated download must not shrink history
    CLOCK[0] = "2026-11-12T16:20:00Z"
    good_oni = open(os.path.join(U.OUT, "oni.json")).read()
    set_fixtures(oni=oni2[:-40], wk=wk2)
    code = run_pipeline()
    st = J("status.json")
    ok("e2e run 3: a truncated ONI download is refused", st["sources"]["oni"]["ok"] is False and "shrank from 922 to 882" in st["sources"]["oni"]["error"])
    ok("e2e run 3: last-good oni.json is untouched", open(os.path.join(U.OUT, "oni.json")).read() == good_oni)
    ok("e2e run 3: the failed source keeps its last-success stamp", st["sources"]["oni"]["updated"] == "2026-11-10T00:11:44Z")
    ok("e2e run 3: the other four sources still refreshed", sum(s["ok"] for s in st["sources"].values()) == 4)
    ok("e2e run 3: archive kept the full ONI record", len(C("oni.csv")) == 923 and len(C("vintages/oni_vintages.csv")) == 924)
    ok("e2e run 3: run log names the failed source", C("pipeline_runs.csv")[-1] == ["2026-11-12T16:20:00Z", "4", "oni"])
    ok("e2e run 3: still exits 0 (failures are telemetry, not build errors)", code == 0)
    commit("run 3")

    # ------------------------------- run 4: NOAA unreachable — nothing may be lost
    CLOCK[0] = "2026-11-16T16:20:00Z"
    def down(url): raise OSError("simulated outage")
    U.fetch = down
    data_before = {f: open(os.path.join(U.OUT, f)).read() for f in ("oni.json", "roni.json", "wksst.json", "soi.json", "heat.json")}
    csv_before = {k: v for k, v in snapshot_tree().items() if k.endswith(".csv") and k != "pipeline_runs.csv"}
    code = run_pipeline()
    st = J("status.json")
    ok("e2e run 4: total outage -> five FAILs, exit 0", code == 0 and not any(s["ok"] for s in st["sources"].values()))
    ok("e2e run 4: every data file is byte-identical", all(open(os.path.join(U.OUT, f)).read() == data_before[f] for f in data_before))
    ok("e2e run 4: every data CSV and vintage file is byte-identical",
       {k: v for k, v in snapshot_tree().items() if k in csv_before} == csv_before)
    ok("e2e run 4: the outage is logged", C("pipeline_runs.csv")[-1] == ["2026-11-16T16:20:00Z", "0", "oni;roni;wksst;soi;heat"])
    ok("e2e run 4: history keeps all four runs", [h["ok"] for h in st["history"]] == [5, 5, 4, 0])
    commit("run 4")

    # ------------------- backfill: rebuilding from git history reproduces the files
    if have_git:
        live = {k: C("vintages/" + s[1]) for k, s in X.VINTAGE_SPECS.items()}
        ok("backfill --check: files written run-by-run match a rebuild from history", quiet(B.main, ["--check"]) == 0)
        shutil.rmtree(X.VINT)
        ok("backfill: rebuilds a deleted revision record", quiet(B.main, []) == 0)
        ok("backfill: the rebuild is identical to what the live runs wrote",
           {k: C("vintages/" + s[1]) for k, s in X.VINTAGE_SPECS.items()} == live)
        with open(os.path.join(X.VINT, "oni_vintages.csv"), "a") as f:
            f.write("2026-11-16,2099,DJF,9.99,0\n")
        ok("backfill --check: detects a file that differs from history", quiet(B.main, ["--check"]) == 1)
        ok("backfill: refuses to shrink a file that holds more than history explains", quiet(B.main, []) == 1)
        ok("backfill: ...and leaves that file untouched", C("vintages/oni_vintages.csv")[-1][1:3] == ["2099", "DJF"])
        ok("backfill --force: overwrites when told to", quiet(B.main, ["--force"]) == 0 and C("vintages/oni_vintages.csv") == live["oni"])
    else:
        print("  (git not found — backfill tests skipped)")

    # ---------------------- run log: entries before the archive began are ignored
    rows_before = C("pipeline_runs.csv")
    X.update_run_log({"history": [{"ts": "2026-08-11T22:55:54Z", "ok": 0, "fail": ["oni"]},
                                  {"ts": "2026-11-20T16:20:00Z", "ok": 5, "fail": []}]}, "2026-11-05")
    rows_after = C("pipeline_runs.csv")
    ok("run log: a pre-launch test entry is not logged; a new run is",
       [r[0] for r in rows_after[1:]] == [r[0] for r in rows_before[1:]] + ["2026-11-20T16:20:00Z"])
finally:
    U.OUT, U.fetch, U.utcnow, X.DATA, X.ARCH, X.VINT, B.ROOT = saved
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
