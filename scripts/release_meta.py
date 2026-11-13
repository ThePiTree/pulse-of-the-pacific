#!/usr/bin/env python3
"""
release_meta.py — decide which dated bundles of the data archive are due, and
write their release notes. Used by .github/workflows/data-release.yml; kept in
Python (not shell) so the calendar logic is unit-tested.

    python3 scripts/release_meta.py plan --trigger monthly|weekly|manual
                                         [--kind auto|monthly|quarterly|annual|none]
                                         [--cadence weekly|monthly|quarterly|annual|off]
                                         [--send-email] [--date YYYY-MM-DD]
        stdout : one line per release to publish:  TAG <TAB> TITLE
        $GITHUB_OUTPUT (if set):  email=yes|no  and  subject=...

    python3 scripts/release_meta.py notes
        stdout : Markdown release notes built from public/archive/manifest.json

WHAT GETS PUBLISHED
  The monthly run happens on the 12th — after NOAA's monthly update, which lands
  around the 5th-10th — so each bundle contains that month's new ONI/RONI season.
    data-YYYY-MM       every month; the snapshot taken that month
    data-YYYY-Qn       in Jan/Apr/Jul/Oct, for the quarter that just ended
    data-YYYY-annual   in January, for the year that just ended
  Bundles are immutable once published: the workflow skips a tag that exists.

E-MAIL CADENCE (only used when SMTP secrets are configured)
  weekly     every Tuesday run          monthly    every 12th-of-month run
  quarterly  the 12th of Jan/Apr/Jul/Oct           annual   the 12th of January
"""
import argparse, datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "..", "public", "archive", "manifest.json")
MONTHS = ["January","February","March","April","May","June","July","August",
          "September","October","November","December"]
QUARTER_MONTHS = (1, 4, 7, 10)
CADENCES = ("weekly", "monthly", "quarterly", "annual", "off")

def monthly_release(d):
    return (f"data-{d.year}-{d.month:02d}",
            f"ENSO data archive — {MONTHS[d.month-1]} {d.year} snapshot")

def quarterly_release(d):
    """The quarter that most recently ENDED before date d."""
    q, y = (d.month - 1) // 3, d.year
    if q == 0: q, y = 4, y - 1
    return (f"data-{y}-Q{q}", f"ENSO data archive — {y} Q{q}")

def annual_release(d):
    return (f"data-{d.year-1}-annual", f"ENSO data archive — {d.year-1} annual")

def due_releases(d):
    """Everything a scheduled 12th-of-month run publishes."""
    out = [monthly_release(d)]
    if d.month in QUARTER_MONTHS: out.append(quarterly_release(d))
    if d.month == 1: out.append(annual_release(d))
    return out

def plan(trigger, kind, cadence, send_email, d):
    """-> (releases [(tag, title)], email_due bool)"""
    cadence = cadence if cadence in CADENCES else "monthly"
    if trigger == "weekly":
        return [], cadence == "weekly"
    if trigger == "monthly":
        email = (cadence == "monthly"
                 or (cadence == "quarterly" and d.month in QUARTER_MONTHS)
                 or (cadence == "annual" and d.month == 1))
        return due_releases(d), email
    # manual run from the Actions tab
    releases = {"auto": due_releases(d), "monthly": [monthly_release(d)],
                "quarterly": [quarterly_release(d)], "annual": [annual_release(d)],
                "none": []}.get(kind, [])
    return releases, bool(send_email)

def notes():
    with open(MANIFEST, encoding="utf-8") as f:
        s = json.load(f)["stats"]
    return "\n".join([
        f"Analysis-ready CSV archive of the ENSO indices shown on https://elninotracker.org , "
        f"as of the data refresh of {s['generated']}.",
        "",
        f"- **ONI** — {s['oni_n']} seasons, {s['oni_span']}",
        f"- **RONI** (NOAA's official index since Feb 2026) — {s['roni_n']} seasons, {s['roni_span']}",
        f"- **Weekly Niño-3.4** — {s['wk_n']} weeks, {s['wk_span']}",
        f"- **SOI (3-month)** — {s['soi_n']} months, {s['soi_span']}",
        f"- **Upper-ocean heat content** — {s['heat_n']} months, {s['heat_span']}",
        f"- **Revision record** since {s['vint_start']} — periods revised so far: "
        f"ONI {s['rev_oni']}, RONI {s['rev_roni']}, weekly {s['rev_wksst']}, "
        f"SOI {s['rev_soi']}, heat content {s['rev_heat']}",
        f"- **Refresh log** — {s['runs_n']} pipeline runs",
        "",
        "Unzip and start with `archive/enso_monthly_merged.csv`; `archive/README_DATA.md` has the "
        "data dictionary, caveats and citation format. Every series is produced by NOAA's Climate "
        "Prediction Center (public domain); this archive is an independent re-publication, not a "
        "NOAA product.",
    ]) + "\n"

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--trigger", choices=["monthly", "weekly", "manual"], required=True)
    p.add_argument("--kind", default="auto")
    p.add_argument("--cadence", default="monthly")
    p.add_argument("--send-email", action="store_true")
    p.add_argument("--date", default=None, help="override today's UTC date (tests)")
    sub.add_parser("notes")
    a = ap.parse_args(argv)
    if a.cmd == "notes":
        sys.stdout.write(notes()); return 0
    d = (datetime.date.fromisoformat(a.date) if a.date
         else datetime.datetime.now(datetime.timezone.utc).date())
    releases, email = plan(a.trigger, (a.kind or "auto").strip() or "auto",
                           (a.cadence or "monthly").strip().lower() or "monthly", a.send_email, d)
    for tag, title in releases:
        print(f"{tag}\t{title}")
    subject = f"Pulse of the Pacific — ENSO data archive, {d.isoformat()}"
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"email={'yes' if email else 'no'}\nsubject={subject}\ncount={len(releases)}\n")
    print(f"plan: trigger={a.trigger} date={d} releases={[t for t, _ in releases]} "
          f"email={'yes' if email else 'no'}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
