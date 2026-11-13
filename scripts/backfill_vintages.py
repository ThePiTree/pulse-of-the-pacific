#!/usr/bin/env python3
"""
backfill_vintages.py — rebuild the revision record from git history.

Every scheduled refresh is a commit, so the repository already holds the exact
JSON this site served after each run. This script replays those snapshots in
order through the same functions the live pipeline uses (export_archive.py) and
writes public/archive/vintages/*.csv, so the revision record reaches back to the
first successful refresh instead of starting today.

    python3 scripts/backfill_vintages.py           # rebuild and write
    python3 scripts/backfill_vintages.py --check   # compare only; exit 1 if the
                                                   # files on disk differ

It is a pure function of the repository's history plus the JSON in the working
tree, so it is safe to re-run at any time. It never silently discards data: if
a vintage file on disk holds MORE rows than history can reproduce, the script
stops and leaves it alone (use --force to overwrite anyway).

Needs the full history:  git fetch --unshallow   (if you cloned with --depth).
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import export_archive as X

def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], check=True,
                          capture_output=True, text=True).stdout

def snapshot(sha, fname):
    """The JSON document public/data/<fname> held at commit <sha>, or None."""
    try:
        return json.loads(git("show", f"{sha}:public/data/{fname}"))
    except (subprocess.CalledProcessError, ValueError):
        return None

def rebuild():
    """Replay every data commit, oldest first. -> {key: (rows, last, count)}"""
    shas = git("log", "--reverse", "--format=%H", "--", "public/data").split()
    state = {k: ([], {}, {}) for k in X.VINTAGE_SPECS}
    stamps = {k: None for k in X.VINTAGE_SPECS}
    used = 0
    def feed(key, doc):
        when = X.seen_date(doc)
        if not doc or not doc.get("records") or not when:
            return False                       # baseline with no run stamp
        stamp = doc["meta"]["updated"]
        if stamp == stamps[key]:
            return False                       # file untouched since the last snapshot
        stamps[key] = stamp
        X.apply_vintage(state[key], X.vintage_items(key, doc["records"]), when)
        return True
    for sha in shas:
        hit = [feed(k, snapshot(sha, spec[0])) for k, spec in X.VINTAGE_SPECS.items()]
        used += any(hit)
    # The working tree may be ahead of HEAD (pipeline run locally, not yet committed).
    for k, spec in X.VINTAGE_SPECS.items():
        feed(k, X.load(spec[0]))
    return state, len(shas), used

def main(argv):
    check, force = "--check" in argv, "--force" in argv
    try:
        if git("rev-parse", "--is-shallow-repository").strip() == "true":
            print("WARNING: this clone is shallow — only the commits present can be replayed.\n"
                  "         Run `git fetch --unshallow` first for the complete record.", file=sys.stderr)
    except subprocess.CalledProcessError:
        print("ERROR: not a git repository — the revision record is rebuilt from git history.", file=sys.stderr)
        return 2
    state, n_commits, n_used = rebuild()
    print(f"replayed {n_commits} data commits ({n_used} carried refreshed data)")
    os.makedirs(X.VINT, exist_ok=True)
    differ = blocked = 0
    for key, (_, fname, header) in X.VINTAGE_SPECS.items():
        path = os.path.join(X.VINT, fname)
        rows = state[key][0]
        new_text = X.csv_text(header, rows)
        old_rows = X.read_vintages(path, len(header) - 3)[0]
        old_text = X.csv_text(header, old_rows) if os.path.exists(path) else None
        revised = sum(1 for c in state[key][2].values() if c > 1)
        same = (old_text == new_text)
        print(f"  {fname:32s} {len(rows):5d} values, {revised:3d} periods revised"
              + ("" if same else f"   (on disk: {len(old_rows)} rows)" if old_text is not None else "   (new file)"))
        if same: continue
        differ += 1
        if check: continue
        if len(old_rows) > len(rows) and not force:
            print(f"    ! {fname} on disk has more rows than history reproduces — left untouched "
                  f"(re-run with --force to overwrite)", file=sys.stderr)
            blocked += 1; continue
        if rows: X.write_if_changed(path, new_text)
    if check:
        print("check: vintage files match git history" if not differ
              else f"check: {differ} vintage file(s) differ from what git history reproduces")
        return 1 if differ else 0
    return 1 if blocked else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
