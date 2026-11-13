#!/usr/bin/env python3
"""
Parser + validation tests for the data pipeline (scripts/update_data.py).

    python3 tests/test_parsers.py        # or: python3 tests/run_all.py

CI runs the whole suite BEFORE every data refresh; a red test blocks the commit.
Standard library only. Every "REGRESSION" block reproduces a real NOAA layout
that once broke the pipeline — keep them, they are the format's memory.
"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import update_data as U

PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")

# ---------------------------------------------------------------- seasonal
oni_txt = """SEAS YR TOTAL ANOM
DJF 1950 24.72 -1.53
JFM 1950 25.17 -1.34
NDJ 2025 26.50 0.80
DJF 2026 26.60 0.90
garbage line that should be ignored
XXX 2026 1 2
"""
r = U.parse_seasonal(oni_txt, anom_col=3)
ok("seasonal: parses 4 valid rows", len(r) == 4)
ok("seasonal: latest value", r[-1]["v"] == 0.9 and r[-1]["s"] == "DJF" and r[-1]["y"] == 2026)
ok("seasonal: season whitelist blocks XXX", all(x["s"] in U.SEASONS for x in r))
ok("seasonal: time is the season's centre month", r[0]["t"] == round(1950 + 0.5/12, 4) and r[0]["m"] == 1)

roni_txt = "SEAS YR ANOM\nDJF 1950 -1.20\nDJF 2026 0.70\n"
r2 = U.parse_seasonal(roni_txt, anom_col=2)
ok("seasonal: RONI 3-col layout", len(r2) == 2 and r2[-1]["v"] == 0.70)
ok("seasonal: RONI layout yields nothing at ONI's column (triggers the fallback)",
   U.parse_seasonal(roni_txt, anom_col=3) == [])

# ------------------------------------------------------------------- wksst
# REGRESSION (Aug 2026): real Fortran fixed-width glues SST to a negative
# anomaly ('23.4-0.5'); whitespace-splitting dropped every such line.
glued = (" Weekly SST and anomalies\n"
         " Week          NINO1+2      NINO3       NINO34       NINO4\n"
         " 03JAN1990     23.4-0.5     25.1-0.3     26.2-0.4     28.1 0.1\n"
         " 10JAN1990     23.6-0.7     25.0-0.5     26.0-0.6     28.0-0.1\n"
         " 17JUN2026     24.0 1.2     26.0 1.5     27.0 1.7     29.0 0.9\n")
w = U.parse_wksst(glued)
ok("wksst: keeps ALL negative-anomaly weeks (glued format)", len(w) == 3)
ok("wksst: first N3.4 anomaly = -0.4", abs(w[0]["v"] - (-0.4)) < 1e-9)
ok("wksst: second N3.4 anomaly = -0.6", abs(w[1]["v"] - (-0.6)) < 1e-9)
ok("wksst: positive week parses too", abs(w[2]["v"] - 1.7) < 1e-9)
ok("wksst: chronological order", w[0]["t"] < w[1]["t"] < w[2]["t"])
ok("wksst: exact ISO date carried as d", [x["d"] for x in w] == ["1990-01-03", "1990-01-10", "2026-06-17"])
ok("wksst: t = year + day_of_year/365.25", w[2]["t"] == round(2026 + 168/365.25, 4))
junk = " 99ZZZ2020 nonsense\n 03JAN1990 only 1.0 two 2.0\n"
ok("wksst: junk lines ignored", U.parse_wksst(junk) == [])
insane = " 03JAN1990     23.4-0.5     25.1-0.3     55.0 9.9     28.1 0.1\n"
ok("wksst: physically impossible SST rejected", U.parse_wksst(insane) == [])
ok("wksst: impossible calendar date rejected",
   U.parse_wksst(" 31FEB1990     23.4-0.5     25.1-0.3     26.2-0.4     28.1 0.1\n") == [])

def wk_line(date, n34a):
    return f" {date.strftime('%d%b%Y').upper()}     23.4-0.5     25.1-0.3     26.2{n34a:4.1f}     28.1 0.1\n"
import datetime
# the FULL record is kept (the series used to be cut to its last 520 weeks)
long_txt = "".join(wk_line(datetime.date(1990, 1, 3) + datetime.timedelta(weeks=i), -0.4) for i in range(900))
ok("wksst: full record kept (900 weeks in, 900 out)", len(U.parse_wksst(long_txt)) == 900)
# a repeated date must not break the strictly-increasing gate: last occurrence wins
dup = wk_line(datetime.date(2026, 6, 10), 1.5) + wk_line(datetime.date(2026, 6, 17), 1.7) + wk_line(datetime.date(2026, 6, 10), 1.6)
wd = U.parse_wksst(dup)
ok("wksst: duplicate date collapses to one record, last wins", len(wd) == 2 and wd[0]["v"] == 1.6)
ok("wksst: out-of-order rows come back sorted", [x["d"] for x in wd] == ["2026-06-10", "2026-06-17"])
ok("wksst: de-duplicated output passes validation", U.validate_series(wd, 2, vmax=8.0) is wd)
# 31 Dec of a leap year is day 366: t lands just past the year boundary but stays ordered
edge = U.parse_wksst(wk_line(datetime.date(2008, 12, 31), 0.2) + wk_line(datetime.date(2009, 1, 7), 0.3))
ok("wksst: leap-year 31 Dec keeps its true date", edge[0]["d"] == "2008-12-31")
ok("wksst: leap-year 31 Dec stays before the next week", edge[0]["t"] < edge[1]["t"])

# --------------------------------------------------------------------- soi
def f6(vals):                       # Fortran F6.1: -999.9 fills its whole field
    return "".join(f"{v:6.1f}" for v in vals)
M = -999.9
# REGRESSION (found in production, Nov 2026): the real file is I4,12F6.1. A
# missing month prints as '-999.9' with NO space before it, so the first year
# is glued to its own year number and the current year ends in a glued run.
# The old whitespace/13-token parser dropped both rows, freezing the live SOI
# series at Dec 2025 for every run from launch (17 Aug) to 10 Nov 2026.
soi_real = ("  (STAND TAHITI - STAND DARWIN)  SEA LEVEL PRESS    3-MONTH RUNNING MEAN\n"
            "\n"
            "YEAR   JAN   FEB   MAR   APR   MAY   JUN   JUL   AUG   SEP   OCT   NOV   DEC\n"
            "1951" + f6([M, 1.5, 0.9, -0.1, -0.5, -1.0, -1.2, -0.8, -0.6, -0.9, -1.1, -1.0]) + "\n"
            "1952" + f6([-0.8, -0.6, 0.0, -0.1, 0.2, 0.4, 0.3, 0.0, 0.1, 0.0, 0.0, -0.6]) + "\n"
            "2025" + f6([0.9, 0.7, 0.6, 0.5, 0.4, 0.4, 0.4, 0.3, 0.5, 0.7, 0.7, 0.7]) + "\n"
            "2026" + f6([0.4, 0.1, -0.3, -0.8, -1.2, -1.6, -1.9, -2.2, -2.5, M, M, M]) + "\n")
ok("soi fixture really is glued", "1951-999.9" in soi_real and "-2.5-999.9-999.9-999.9" in soi_real)
sr = U.parse_soi(soi_real)
by = {x["t"]: x["v"] for x in sr}
t = lambda y, m: round(y + (m - 0.5) / 12, 4)
ok("soi: first year survives being glued to its year number", by.get(t(1951, 2)) == 1.5 and by.get(t(1951, 12)) == -1.0)
ok("soi: first year's missing January is dropped", t(1951, 1) not in by)
ok("soi: current year parses (was dropped entirely)", by.get(t(2026, 1)) == 0.4)
ok("soi: LAST valid month, glued to the first -999.9, is kept", by.get(t(2026, 9)) == -2.5)
ok("soi: not-yet-published months are absent", all(t(2026, m) not in by for m in (10, 11, 12)))
ok("soi: record count = 11 + 12 + 12 + 9", len(sr) == 44)
ok("soi: strictly increasing time", all(b["t"] > a["t"] for a, b in zip(sr, sr[1:])))
ok("soi: a leading space before the year changes nothing",
   U.parse_soi("\n".join(" " + ln for ln in soi_real.splitlines())) == sr)
# the same content with ordinary spaces must give the identical result
soi_spaced = "\n".join(" ".join(ln.replace("-999.9", " -999.9").split()) for ln in soi_real.splitlines())
ok("soi: space-separated layout parses identically", U.parse_soi(soi_spaced) == sr)
# a genuinely short row (months simply absent) also parses
partial = "2025  0.4  0.3  0.5  0.7  0.7  0.7  0.4  0.3  0.5  0.7  0.7  0.7\n2026 -0.8 -1.2 -1.5 -1.9 -2.1 -2.4 -2.2 -2.6 -2.9\n"
sp = U.parse_soi(partial)
ok("soi: short current-year row yields exactly its 9 months", sum(1 for x in sp if x["t"] > 2026) == 9)
# two tables in one file: the later one wins
two = "2026" + f6([-0.7, -0.9, M, M, M, M, M, M, M, M, M, M]) + "\n" + "2026" + f6([-0.6, -0.8, M, M, M, M, M, M, M, M, M, M]) + "\n"
s2 = U.parse_soi(two)
ok("soi: repeated table de-duplicates, later wins", len(s2) == 2 and s2[0]["v"] == -0.6)
ok("soi: prose and base-period lines yield nothing",
   U.parse_soi("1991-2020 base period means\nYEAR JAN FEB\n2026\n(1981-2010)\n") == [])
ok("soi: out-of-range values rejected", U.parse_soi("2026" + f6([9.5, 0.1] + [M]*10) + "\n") == [{"t": t(2026, 2), "v": 0.1}])

# -------------------------------------------------------------------- heat
heat_txt = (" 1979  1  0.12  0.08  0.15\n"
            " 1979  2  0.10  0.05 -9.99\n"     # missing flag style A
            " 1980  1  0.10  0.05 -99.9\n"     # missing flag style B
            " 2026  5  1.20  1.05  1.35\n")
h = U.parse_heat(heat_txt)
ok("heat: keeps valid rows", len(h) == 2)
ok("heat: -9.99 missing flag rejected", all(abs(x["v"]) <= 8 for x in h))
ok("heat: uses 180W-100W column", abs(h[-1]["v"] - 1.35) < 1e-9)
ok("heat: time is the month centre", h[-1]["t"] == round(2026 + 4.5/12, 4))

# ---------------------------------------------------------------- classify
recs = [{"v": x} for x in [0.6]*5 + [0.4] + [-0.6]*4 + [0.0]]
U.classify(recs)
cls = "".join(r["c"] for r in recs)
ok("classify: 5-season warm run => El Nino", cls[:5] == "EEEEE")
ok("classify: 4-season cool run => NOT an event", cls[6:10] == "NNNN")
ok("classify: exactly +0.5 counts (>=)", "".join(r["c"] for r in U.classify([{"v": 0.5} for _ in range(5)])) == "EEEEE")

# --------------------------------------------------------- validation gates
try:
    U.validate_series([{"t": 1, "v": 0}], min_len=5); ok("validate: short series rejected", False)
except ValueError:
    ok("validate: short series rejected", True)
try:
    U.validate_series([{"t": 1, "v": 0}, {"t": 1, "v": 0.1}] * 3, min_len=2)
    ok("validate: duplicate times rejected", False)
except ValueError:
    ok("validate: duplicate times rejected", True)
try:
    U.validate_series([{"t": i, "v": 0} for i in range(10)] + [{"t": 99, "v": 42}], min_len=2)
    ok("validate: insane value rejected", False)
except ValueError:
    ok("validate: insane value rejected", True)
okseries = [{"t": 2000 + i/12, "v": ((-1) ** i) * 1.5} for i in range(24)]
ok("validate: healthy series passes", U.validate_series(okseries, min_len=10) is okseries)

# ------------------------------------------------------------ no-shrink gate
_tmp = tempfile.mkdtemp()
_real_out = U.OUT
try:
    U.OUT = _tmp
    with open(os.path.join(_tmp, "x.json"), "w") as f:
        json.dump({"records": [{"t": i, "v": 0} for i in range(100)]}, f)
    mk = lambda n: [{"t": i, "v": 0} for i in range(n)]
    ok("no-shrink: a longer record is accepted", len(U.guard_shrink("x.json", mk(101))) == 101)
    ok("no-shrink: equal length is accepted", len(U.guard_shrink("x.json", mk(100))) == 100)
    ok("no-shrink: losing 2 records is tolerated", len(U.guard_shrink("x.json", mk(98))) == 98)
    try:
        U.guard_shrink("x.json", mk(97)); ok("no-shrink: losing 3 records is refused", False)
    except ValueError as e:
        ok("no-shrink: losing 3 records is refused", "shrank from 100 to 97" in str(e))
    ok("no-shrink: first ever write (no file on disk) is accepted", len(U.guard_shrink("new.json", mk(5))) == 5)
finally:
    U.OUT = _real_out
    shutil.rmtree(_tmp, ignore_errors=True)

# ------------------------------------------------------------------ labels
ok("month_label: month-centre time -> 'Sep 2026'", U.month_label(round(2026 + 8.5/12, 4)) == "Sep 2026")
ok("month_label: January and December", U.month_label(round(2026 + 0.5/12, 4)) == "Jan 2026"
   and U.month_label(round(2025 + 11.5/12, 4)) == "Dec 2025")
ok("every source has a cadence and a data-age limit",
   set(U.URLS) == set(U.CADENCE_DAYS) == set(U.DATA_AGE_LIMIT_DAYS))
ok("every fetched URL is HTTPS on NOAA CPC",
   all(u.startswith("https://www.cpc.ncep.noaa.gov/") for u in U.URLS.values()))

# ------------------------------------------------- error text + run warnings
import contextlib, io
_hostile = ValueError("bad token\n::add-mask::x\r\n" + "z" * 500)
ok("err_text: always one line, however the message was built", "\n" not in U.err_text(_hostile) and "\r" not in U.err_text(_hostile))
ok("err_text: bounded at 300 characters and names the exception type", len(U.err_text(_hostile)) == 300 and U.err_text(_hostile).startswith("ValueError: bad token"))
def _annotated(msg, on_actions):
    old = os.environ.pop("GITHUB_ACTIONS", None)
    if on_actions: os.environ["GITHUB_ACTIONS"] = "true"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): U.annotate("Title", msg)
    finally:
        os.environ.pop("GITHUB_ACTIONS", None)
        if old is not None: os.environ["GITHUB_ACTIONS"] = old
    return buf.getvalue()
ok("annotate: silent outside GitHub Actions", _annotated("x", False) == "")
ok("annotate: one escaped warning line on GitHub Actions",
   _annotated("50% done\nline two", True) == "::warning title=Title::50%25 done%0Aline two\n")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
