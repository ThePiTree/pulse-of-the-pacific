#!/usr/bin/env python3
"""
Tests for scripts/enso_rule.py - the El Nino / La Nina episode rule - against
NOAA's own published tables, frozen in tests/fixtures/ (see the README there).

    python3 tests/test_rule.py        # or: python3 tests/run_all.py

The point of this file: the rule must reproduce what NOAA publishes, and nobody
should be able to "simplify" it back to a plain `value >= 0.5` without a red test.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import enso_rule as R
import update_data as U
import export_archive as X

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f"  [{detail}]" if detail else ""))

# ------------------------------------------------------------- tenths / side
ok("tenths: ordinary values round to the nearest tenth",
   [R.tenths(v) for v in (0.44, 0.46, 0.54, 1.97, 2.46, -0.44, -0.46, -1.04, 0.0)] == [4, 5, 5, 20, 25, -4, -5, -10, 0])
ok("tenths: an exact half rounds UP - 0.45 -> 0.5, 0.95 -> 1.0, 0.05 -> 0.1", [R.tenths(v) for v in (0.45, 0.95, 0.05)] == [5, 10, 1])
ok("tenths: ... also below zero - -0.45 -> -0.4, -0.05 -> 0.0, -1.05 -> -1.0", [R.tenths(v) for v in (-0.45, -0.05, -1.05)] == [-4, 0, -10])
ok("tenths: immune to floating-point noise (0.29, 0.57, 1.15 as parsed from text)",
   [R.tenths(float(t)) for t in ("0.29", "0.57", "1.15", "-0.15", "2.675")] == [3, 6, 12, -1, 27])
ok("tenths: exact at every two-decimal value from -3.00 to +3.00",
   all(R.tenths(h / 100) == (h + 5) // 10 for h in range(-300, 301)))
ok("one_decimal: the tabulated value as a float", R.one_decimal(0.47) == 0.5 and R.one_decimal(-0.45) == -0.4 and R.one_decimal(1.97) == 2.0)
ok("side: threshold met from 0.45 upward and from -0.46 downward",
   [R.side(v) for v in (0.44, 0.45, 0.50, -0.45, -0.46, -0.50, 0.0)] == [0, 1, 1, 0, -1, -1, 0])

# ------------------------------------------------------------- episode_codes
ok("codes: five seasons make an episode, four do not",
   R.episode_codes([0.6] * 5) == ["E"] * 5 and R.episode_codes([0.6] * 4) == ["N"] * 4
   and R.episode_codes([-0.6] * 5) == ["L"] * 5 and R.episode_codes([-0.6] * 4) == ["N"] * 4)
ok("codes: SON 1979 - JFM 1980 (0.47 0.50 0.64 0.62 0.47) is an El Nino, as in NOAA's table",
   R.episode_codes([0.34, 0.47, 0.50, 0.64, 0.62, 0.47, 0.35]) == ["N", "E", "E", "E", "E", "E", "N"])
ok("codes: a warm run and a cold run never merge", R.episode_codes([0.6] * 3 + [-0.6] * 3) == ["N"] * 6)
ok("codes: a single neutral season splits a run", R.episode_codes([0.6] * 4 + [0.3] + [0.6] * 4) == ["N"] * 9)
ok("codes: back-to-back opposite episodes are both kept", R.episode_codes([0.9] * 5 + [-0.9] * 5) == ["E"] * 5 + ["L"] * 5)
ok("codes: empty and one-element input", R.episode_codes([]) == [] and R.episode_codes([2.0]) == ["N"])
ok("pending: a short run at the end of the record", R.pending_run([0.0, 0.9, 1.2]) == (1, 1) and R.pending_run([0.0, -0.9]) == (1, -1))
ok("pending: none once the run qualifies, when it has ended, or on an empty record",
   R.pending_run([0.9] * 5) == (None, 0) and R.pending_run([0.9, 0.9, 0.1]) == (None, 0) and R.pending_run([]) == (None, 0))
ok("pending: the whole record can be a pending run", R.pending_run([0.9, 0.9]) == (0, 1))

# ---------------------------------------------- every caller uses this one rule
recs = [{"v": v} for v in (0.34, 0.47, 0.50, 0.64, 0.62, 0.47, 0.35)]
ok("update_data.classify writes exactly these codes into the JSON", [r["c"] for r in U.classify(recs)] == R.episode_codes([r["v"] for r in recs]))
ok("export_archive.season_labels spells out exactly these codes", X.season_labels(recs) == ["Neutral"] + ["El Nino"] * 5 + ["Neutral"])
ok("the JSON says in words what 'c' means", "one decimal" in U.CLASSIFICATION_NOTE and "5" in U.CLASSIFICATION_NOTE)

# ------------------------------------------------------ NOAA's published tables
def fixture(name):
    rows = []
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip(): continue
            p = line.rstrip("\n").split("\t")
            rows.append({"y": int(p[0]), "s": p[1], "v": float(p[2]), "table": float(p[3]), "flag": (p[4] == "1") if len(p) > 4 else None})
    return rows
def is_half(v): return abs(int(round(v * 100))) % 10 == 5
def strict_codes(values):
    """The rule this project used until November 2026: threshold on the two-decimal value."""
    n = len(values); out = ["N"] * n; i = 0
    while i < n:
        s = 1 if values[i] >= 0.5 else -1 if values[i] <= -0.5 else 0
        if not s: i += 1; continue
        j = i
        while j < n and (values[j] >= 0.5 if s > 0 else values[j] <= -0.5): j += 1
        if j - i >= 5: out[i:j] = ["E" if s > 0 else "L"] * (j - i)
        i = j
    return out
name = lambda r: f"{r['s']} {r['y']}"

oni = fixture("noaa_oni_table.tsv")
ok("ONI fixture: 920 seasons, DJF 1950 - JAS 2026, in order", len(oni) == 920 and name(oni[0]) == "DJF 1950" and name(oni[-1]) == "JAS 2026")
ok("ONI: away from exact halves, NOAA's table is the file value rounded to one decimal - every time",
   all(abs(round(r["v"], 1) - r["table"]) < 1e-9 for r in oni if not is_half(r["v"])))
halves = [r for r in oni if is_half(r["v"])]
other = sorted(name(r) for r in halves if abs(R.one_decimal(r["v"]) - r["table"]) > 1e-9)
ok("ONI: 87 of the 90 exact halves are printed rounded up - the convention tenths() follows",
   len(halves) == 90 and other == sorted(["DJF 1964", "JFM 2021", "AMJ 2026"]), f"{len(halves)} halves; exceptions {other}")
codes = R.episode_codes([r["v"] for r in oni])
bad = [name(r) for r, c in zip(oni, codes) if (c != "N") != r["flag"]]
ok("ONI: the rule reproduces NOAA's episode colouring for ALL 920 seasons", not bad, f"{len(bad)} differ: {bad[:8]}")
ok("ONI: warm episodes sit on positive values, cold on negative", all((c == "E") == (r["v"] > 0) for r, c in zip(oni, codes) if c != "N"))
bad = [name(r) for r, c in zip(oni, R.episode_codes([r["table"] for r in oni])) if (c != "N") != r["flag"]]
ok("ONI: NOAA's colouring IS the five-season rule applied to the printed one-decimal values", not bad, str(bad[:8]))
n_old = sum((c != "N") != r["flag"] for r, c in zip(oni, strict_codes([r["v"] for r in oni])))
ok("ONI: guard - a plain 'value >= 0.5' on the file values gets 46 of these seasons wrong", n_old == 46, f"got {n_old}")
for label, lo, hi in (("the 1954 La Nina, AMJ-SON", ("AMJ", 1954), ("SON", 1954)), ("the 1969-70 El Nino, ASO-DJF", ("ASO", 1969), ("DJF", 1970)),
                      ("the 1979-80 El Nino, SON-JFM", ("SON", 1979), ("JFM", 1980))):
    i = next(k for k, r in enumerate(oni) if (r["s"], r["y"]) == lo); j = next(k for k, r in enumerate(oni) if (r["s"], r["y"]) == hi)
    ok(f"ONI: {label}, is found (the old rule missed it entirely)",
       all(c != "N" for c in codes[i:j + 1]) and all(c == "N" for c in strict_codes([r["v"] for r in oni])[i:j + 1]))

roni = fixture("noaa_roni_table.tsv")
ok("RONI fixture: 921 seasons, DJF 1950 - ASO 2026, in order", len(roni) == 921 and name(roni[0]) == "DJF 1950" and name(roni[-1]) == "ASO 2026")
ok("RONI: away from exact halves, NOAA's table is the file value rounded to one decimal - every time",
   all(abs(round(r["v"], 1) - r["table"]) < 1e-9 for r in roni if not is_half(r["v"])))
halves = [r for r in roni if is_half(r["v"])]
other = sorted(name(r) for r in halves if abs(R.one_decimal(r["v"]) - r["table"]) > 1e-9)
ok("RONI: 80 of the 87 exact halves are printed rounded up", len(halves) == 87 and len(other) == 7, f"{len(halves)} halves; exceptions {other}")
codes = R.episode_codes([r["v"] for r in roni])
ref = R.episode_codes([r["table"] for r in roni])              # the five-season rule on NOAA's printed values
diff = [name(r) for r, a, b in zip(roni, codes, ref) if a != b]
ok("RONI: the rule matches NOAA's printed table for 917 of 921 seasons; the four others are FMA-MJJ 1984",
   diff == ["FMA 1984", "MAM 1984", "AMJ 1984", "MJJ 1984"], str(diff))
ok("RONI: ... and those four hinge on one value, FMA 1984: -0.45 in the file, -0.5 in the table",
   next(r for r in roni if name(r) == "FMA 1984")["v"] == -0.45 and next(r for r in roni if name(r) == "FMA 1984")["table"] == -0.5)
n_old = sum(a != b for a, b in zip(strict_codes([r["v"] for r in roni]), ref))
ok("RONI: guard - a plain 'value >= 0.5' on the file values gets 52 seasons wrong", n_old == 52, f"got {n_old}")
ok("RONI: AMJ-ASO 2026 (0.49 0.97 1.36 1.69 1.97) is a five-season El Nino, as NOAA's table prints it (0.5 1.0 1.4 1.7 2.0)",
   codes[-5:] == ["E"] * 5 and [r["table"] for r in roni[-5:]] == [0.5, 1.0, 1.4, 1.7, 2.0] and R.pending_run([r["v"] for r in roni]) == (None, 0))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
