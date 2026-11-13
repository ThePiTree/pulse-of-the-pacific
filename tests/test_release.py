#!/usr/bin/env python3
"""
Tests for the release tooling: scripts/release_meta.py (which bundles are due,
release notes), scripts/email_bundle.py (message building; nothing is sent),
and static checks that the three workflow files still agree with each other.

    python3 tests/test_release.py        # or: python3 tests/run_all.py
"""
import contextlib, datetime, io, json, os, re, shutil, sys, tempfile, zipfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import release_meta as R
import email_bundle as E

PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")
D = datetime.date
tags = lambda rel: [t for t, _ in rel]

# ------------------------------------------------------------ what is due
ok("monthly tag is the snapshot's own month", R.monthly_release(D(2026, 11, 12))[0] == "data-2026-11")
ok("monthly title names the month", "November 2026" in R.monthly_release(D(2026, 11, 12))[1])
ok("an ordinary month publishes only the monthly bundle", tags(R.due_releases(D(2026, 11, 12))) == ["data-2026-11"])
ok("April adds Q1", tags(R.due_releases(D(2027, 4, 12))) == ["data-2027-04", "data-2027-Q1"])
ok("July adds Q2", tags(R.due_releases(D(2027, 7, 12))) == ["data-2027-07", "data-2027-Q2"])
ok("October adds Q3", tags(R.due_releases(D(2027, 10, 12))) == ["data-2027-10", "data-2027-Q3"])
ok("January adds Q4 and the annual bundle of the PREVIOUS year",
   tags(R.due_releases(D(2027, 1, 12))) == ["data-2027-01", "data-2026-Q4", "data-2026-annual"])
# quarterly = the quarter that most recently ended, for every month of the year
expect = {1: "2026-Q4", 2: "2026-Q4", 3: "2026-Q4", 4: "2027-Q1", 5: "2027-Q1", 6: "2027-Q1",
          7: "2027-Q2", 8: "2027-Q2", 9: "2027-Q2", 10: "2027-Q3", 11: "2027-Q3", 12: "2027-Q3"}
ok("quarterly: correct for all twelve months (never 'Q0')",
   all(R.quarterly_release(D(2027, m, 15))[0] == "data-" + q for m, q in expect.items()))
ok("annual: always the previous calendar year", R.annual_release(D(2027, 6, 1))[0] == "data-2026-annual")
alltags = [t for m in range(1, 13) for t in tags(R.due_releases(D(2027, m, 12)))]
ok("a full year of scheduled runs yields 12 monthly + 4 quarterly + 1 annual, all distinct",
   len(alltags) == 17 and len(set(alltags)) == 17)
ok("every tag is a safe git tag name", all(re.fullmatch(r"data-\d{4}-(\d{2}|Q[1-4]|annual)", t) for t in alltags))

# ----------------------------------------------------------------- plans
p = lambda trig, kind="auto", cad="monthly", send=False, d=D(2026, 11, 12): R.plan(trig, kind, cad, send, d)
ok("weekly tick publishes nothing", p("weekly")[0] == [])
ok("weekly tick e-mails only when cadence = weekly", p("weekly", cad="weekly")[1] is True and p("weekly", cad="monthly")[1] is False)
ok("monthly run does not e-mail when cadence = weekly (the Tuesday tick does)", p("monthly", cad="weekly")[1] is False)
ok("monthly run publishes what is due and e-mails on monthly cadence", tags(p("monthly")[0]) == ["data-2026-11"] and p("monthly")[1] is True)
ok("quarterly cadence e-mails only in Jan/Apr/Jul/Oct",
   [p("monthly", cad="quarterly", d=D(2027, m, 12))[1] for m in range(1, 13)] == [m in (1, 4, 7, 10) for m in range(1, 13)])
ok("annual cadence e-mails only in January",
   [p("monthly", cad="annual", d=D(2027, m, 12))[1] for m in range(1, 13)] == [m == 1 for m in range(1, 13)])
ok("cadence 'off' never e-mails on a schedule", not p("monthly", cad="off")[1] and not p("weekly", cad="off")[1])
ok("an unrecognised cadence falls back to monthly", p("monthly", cad="fortnightly")[1] is True)
ok("manual 'auto' publishes what is due", tags(p("manual")[0]) == ["data-2026-11"])
ok("manual 'quarterly' in February gives last year's Q4", tags(p("manual", kind="quarterly", d=D(2027, 2, 3))[0]) == ["data-2026-Q4"])
ok("manual 'annual' / 'monthly' / 'none'",
   tags(p("manual", kind="annual")[0]) == ["data-2025-annual"] and tags(p("manual", kind="monthly")[0]) == ["data-2026-11"]
   and p("manual", kind="none")[0] == [])
ok("manual run e-mails only when asked, whatever the cadence", p("manual", cad="weekly")[1] is False and p("manual", send=True, cad="off")[1] is True)

# ------------------------------------------------------- CLI + $GITHUB_OUTPUT
tmp = tempfile.mkdtemp()
try:
    gh_out = os.path.join(tmp, "gh_output.txt")
    os.environ["GITHUB_OUTPUT"] = gh_out
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = R.main(["plan", "--trigger", "monthly", "--kind", "auto", "--cadence", "quarterly", "--date", "2027-01-12"])
    lines = out.getvalue().splitlines()
    ok("CLI plan: one 'TAG<TAB>TITLE' line per release", rc == 0 and [l.split("\t")[0] for l in lines] == ["data-2027-01", "data-2026-Q4", "data-2026-annual"]
       and all(len(l.split("\t")) == 2 for l in lines))
    gh = dict(l.split("=", 1) for l in open(gh_out).read().splitlines())
    ok("CLI plan: writes email / subject / count for the workflow", gh["email"] == "yes" and gh["count"] == "3" and "2027-01-12" in gh["subject"])
    open(gh_out, "w").close()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        R.main(["plan", "--trigger", "weekly", "--cadence", "monthly", "--date", "2026-11-17"])
    gh = dict(l.split("=", 1) for l in open(gh_out).read().splitlines())
    ok("CLI plan: an idle weekly tick reports count=0, email=no", gh["count"] == "0" and gh["email"] == "no")
    del os.environ["GITHUB_OUTPUT"]

    # ---------------------------------------------------------- release notes
    stats = {"generated": "2026-11-10 00:11:44 UTC", "oni_n": 921, "oni_span": "DJF 1950 → ASO 2026", "roni_n": 921,
             "roni_span": "DJF 1950 → ASO 2026", "wk_n": 1920, "wk_span": "1990-01-03 → 2026-11-04", "soi_n": 908,
             "soi_span": "Feb 1951 → Sep 2026", "heat_n": 574, "heat_span": "Jan 1979 → Oct 2026", "vint_start": "2026-08-17",
             "rev_oni": 0, "rev_roni": 1, "rev_wksst": 7, "rev_soi": 0, "rev_heat": 3, "runs_n": 26}
    man = os.path.join(tmp, "manifest.json")
    with open(man, "w", encoding="utf-8") as f: json.dump({"stats": stats}, f)
    saved = R.MANIFEST; R.MANIFEST = man
    notes = R.notes(); R.MANIFEST = saved
    ok("notes: carry the data date and every series' coverage",
       "2026-11-10 00:11:44 UTC" in notes and "DJF 1950 → ASO 2026" in notes and "1990-01-03 → 2026-11-04" in notes and "26 pipeline runs" in notes)
    ok("notes: credit NOAA and disclaim officialness", "NOAA's Climate" in notes and "not a" in notes)
    if os.path.exists(os.path.join(ROOT, "public", "archive", "manifest.json")):
        ok("notes: build from the repository's real manifest", "ONI" in R.notes())

    # ------------------------------------------------------------ e-mail (dry)
    body = os.path.join(tmp, "notes.md"); open(body, "w", encoding="utf-8").write(notes)
    z = os.path.join(tmp, "enso-archive-2026-11-12.zip")
    with zipfile.ZipFile(z, "w") as zf: zf.writestr("archive/oni.csv", "year,season\n")
    msg = E.build_message("sender@example.invalid", ["a@example.invalid", "b@example.invalid"], "Subject — test", notes, z)
    att = [p for p in msg.iter_attachments()]
    ok("email: headers and UTF-8 subject/body survive", msg["To"] == "a@example.invalid, b@example.invalid" and msg["Subject"] == "Subject — test"
       and "→" in msg.get_body(preferencelist=("plain",)).get_content())
    ok("email: the zip is attached under its own name", len(att) == 1 and att[0].get_filename() == "enso-archive-2026-11-12.zip"
       and att[0].get_content_type() == "application/zip" and att[0].get_payload(decode=True) == open(z, "rb").read())
    def run_email(env, *args):
        keep = {k: os.environ.pop(k, None) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")}
        os.environ.update(env)
        o, e = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
                rc = E.main(list(args))
        finally:
            for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"): os.environ.pop(k, None)
            os.environ.update({k: v for k, v in keep.items() if v is not None})
        return rc, o.getvalue() + e.getvalue()
    base = ("--subject", "S", "--body", body, "--attach", z)
    rc, text = run_email({"SMTP_HOST": "smtp.example.invalid", "SMTP_USER": "me@example.invalid", "SMTP_PASSWORD": "app-password-xyz"}, *base, "--dry-run")
    ok("email dry run: exit 0, describes the send, recipient defaults to the sender", rc == 0 and "1 recipient(s)" in text and "smtp.example.invalid:465" in text)
    ok("email: the password never appears in output", "app-password-xyz" not in text)
    rc, text = run_email({}, *base)
    ok("email: missing configuration -> exit 2 naming what is missing", rc == 2 and "SMTP_HOST" in text and "SMTP_USER" in text and "SMTP_PASSWORD" in text)
    rc, text = run_email({"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p", "SMTP_PORT": "tls"}, *base, "--dry-run")
    ok("email: a non-numeric port is a configuration error", rc == 2)
    rc, text = run_email({"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}, "--subject", "S", "--body", body, "--attach", os.path.join(tmp, "nope.zip"), "--dry-run")
    ok("email: a missing attachment is reported, not raised", rc == 2)
finally:
    os.environ.pop("GITHUB_OUTPUT", None)
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------- workflows: static cross-file checks
def wf(name):
    with open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8") as f: return f.read()
refresh, pages, release, ci = wf("update-data.yml"), wf("pages.yml"), wf("data-release.yml"), wf("ci.yml")
name = re.search(r"^name:\s*(.+)$", refresh, re.M).group(1).strip().strip('"')
ok("refresh workflow keeps the name the Pages deploy listens for", name == "Refresh ENSO data")
ok("pages.yml redeploys after that exact workflow (GitHub Pages only redeploys bot commits this way)",
   re.search(r"workflow_run:\s*\n\s*workflows:\s*\[\s*\"" + re.escape(name) + r"\"\s*\]", pages) is not None)
ok("refresh workflow commits the archive together with the data - and the data alone if the archive is missing",
   'PATHS="public/data"' in refresh and 'if [ -d public/archive ]; then PATHS="$PATHS public/archive"; fi' in refresh
   and "git add $PATHS" in refresh and 'git status --porcelain $PATHS' in refresh)
ok("refresh workflow never stages anything outside public/data and public/archive",
   re.findall(r"git add (.+)", refresh) == ["$PATHS"] and "git add -A" not in refresh and "git add ." not in refresh)
ok("refresh workflow gates on the pipeline tests - not on the site checks, which must never block a data refresh",
   "python tests/run_all.py --pipeline" in refresh)
ok("refresh workflow fetches only after its tests", 0 < refresh.find("run: python tests/run_all.py") < refresh.find("run: python scripts/update_data.py"))
ok("test workflow runs every suite on pushes and pull requests", "python tests/run_all.py\n" in ci + "\n" and "pull_request" in ci and "push:" in ci)
ok("test workflow can only read the repository", re.search(r"^permissions:\s*\n\s*contents:\s*read\s*$", ci, re.M) is not None and "write" not in ci)
ok("only the refresh job may push commits; only the deploy job may publish pages",
   "git push" in refresh and "git push" not in release + pages + ci and "pages: write" in pages and "pages: write" not in refresh + release + ci)
crons = re.findall(r'cron:\s*"([^"]+)"', release)
ok("release workflow has a monthly (12th) and a weekly (Tuesday) schedule", crons == ["17 6 12 * *", "17 6 * * 2"])
ok("the cron string the trigger expression tests is the monthly cron itself", f"github.event.schedule == '{crons[0]}'" in release)
ok("release workflow never interpolates user input into the shell", "${{ github.event.inputs" not in "\n".join(
   l for l in release.splitlines() if l.strip().startswith(("python3", "gh ", "cp ", "echo", "if [", "EXTRA", "zip"))))
ok("release workflow may create releases and nothing more", re.search(r"^permissions:\s*\n\s*contents:\s*write", release, re.M) is not None
   and "id-token" not in release and "pages:" not in release)
ok("SMTP secrets are only ever passed through env", all(("secrets.SMTP_PASSWORD" not in l) or ("SMTP_PASSWORD:" in l or "SMTP_READY:" in l) for l in release.splitlines()))
for wname, text in (("update-data.yml", refresh), ("pages.yml", pages), ("data-release.yml", release), ("ci.yml", ci)):
    ok(f"{wname}: no tab characters (YAML forbids them for indentation)", "\t" not in text.replace("$'\\t'", ""))
    ok(f"{wname}: every action is pinned to a major version of an official GitHub action",
       all(re.fullmatch(r"actions/[a-z-]+@v\d+", u) for u in re.findall(r"uses:\s*(\S+)", text)))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
