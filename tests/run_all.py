#!/usr/bin/env python3
"""
Run every test suite and print one verdict.

    python3 tests/run_all.py              everything (what a developer and CI run)
    python3 tests/run_all.py --pipeline   only the suites that guard the data refresh

Suites
    test_parsers.py     the five NOAA parsers, validation gates, status telemetry   [pipeline]
    test_rule.py        the El Nino / La Nina rule against NOAA's published tables  [pipeline]
    test_archive.py     CSV archive, revision record, a full simulated pipeline     [pipeline]
    test_release.py     release calendar, e-mail message, workflow cross-checks
    test_site.py        static checks on public/ (CSP, links, sitemap, data shape)
    test_frontend.mjs   logic inside app.js / admin.js (needs Node.js; skipped if absent)

Why two modes: the scheduled refresh (.github/workflows/update-data.yml) runs
--pipeline before it fetches anything, so a broken parser can never publish bad
numbers. It deliberately does NOT run the site checks - a typo in a page should
turn the push check red, not stop the data from updating.

Exit status 0 only if every suite that ran passed. Standard library only.
"""
import os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = ["test_parsers.py", "test_rule.py", "test_archive.py"]
EVERYTHING = PIPELINE + ["test_release.py", "test_site.py", "test_frontend.mjs"]

def run(name):
    """-> (status, passed, failed, seconds, output). status: 'ok' | 'FAILED' | 'skipped'."""
    path = os.path.join(HERE, name)
    if name.endswith(".mjs"):
        node = shutil.which("node")
        if not node:
            return "skipped", 0, 0, 0.0, "Node.js is not installed"
        cmd = [node, path]
    else:
        cmd = [sys.executable, path]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    m = re.search(r"(\d+) passed, (\d+) failed", out)
    passed, failed = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    good = p.returncode == 0 and m is not None and failed == 0      # a crash before the summary is a failure
    return ("ok" if good else "FAILED"), passed, failed, time.time() - t0, out

def main(argv):
    unknown = [a for a in argv if a != "--pipeline"]
    if unknown:
        print(__doc__.strip()); return 2
    suites = PIPELINE if "--pipeline" in argv else EVERYTHING
    total = bad = 0
    for name in suites:
        status, passed, failed, secs, out = run(name)
        total += passed
        if status == "skipped":
            print(f"  skipped  {name:20s} {out}")
            continue
        print(f"  {status:7s}  {name:20s} {passed:4d} passed, {failed} failed   ({secs:.1f}s)")
        if status != "ok":
            bad += 1
            print("\n".join("      " + line for line in out.splitlines()[-25:]))
    print(f"\n{'ALL SUITES PASSED' if not bad else str(bad) + ' SUITE(S) FAILED'} - {total} checks in {len(suites)} suite(s)")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
