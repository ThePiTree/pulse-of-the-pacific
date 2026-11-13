#!/usr/bin/env python3
"""
build_standalone.py — produce dist/el-nino-tracker-standalone.html: the tracker
as ONE self-contained file (CSS + JS + ECharts + the current data inlined) that
opens straight from disk with no server. For demos, sharing and archiving.

    python3 scripts/build_standalone.py              # writes dist/el-nino-tracker-standalone.html
    python3 scripts/build_standalone.py --out DIR    # writes it into DIR instead

It is a build artifact, not source: dist/ is git-ignored and never deployed.
Rebuild it whenever you want a copy with today's data; the deployable site in
public/ remains the single source of truth.

What the build changes relative to public/index.html
  * stylesheet, chart library and app script are inlined; every data file that
    exists (per data/manifest.json) is embedded on window.__EMBEDDED__, which
    assets/app.js reads instead of fetching;
  * the Content-Security-Policy meta tag is dropped (it forbids inline scripts);
  * analytics is removed — an offline copy must not report to the live property;
  * links to other pages of the site are made absolute (https://elninotracker.org/…)
    so they still work when the file is opened from a desktop.
"""
import argparse, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PUB  = os.path.join(ROOT, "public")
DIST = os.path.join(ROOT, "dist")
SITE_URL = "https://elninotracker.org"
SERIES = ["oni", "events", "impacts", "roni_compare", "roni", "wksst", "soi", "heat"]

def read(p):
    with open(os.path.join(PUB, p), encoding="utf-8") as f:
        return f.read()

def sub_once(pattern, repl, text, what, flags=0):
    """Regex-replace that must hit exactly once — a silent miss is how stale
    tags end up shipping in a 'self-contained' file."""
    out, n = re.subn(pattern, lambda m: repl, text, flags=flags)
    if n != 1:
        raise SystemExit(f"build_standalone: expected exactly one {what} in index.html, found {n} — "
                         f"index.html changed; update scripts/build_standalone.py")
    return out

def build():
    html = read("index.html")
    css  = read("assets/style.css")
    appj = read("assets/app.js")
    ech  = read("vendor/echarts.min.js")

    # ---- data: embed every series that exists right now
    data = {}
    for key in SERIES:
        p = os.path.join(PUB, "data", key + ".json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data[key] = json.load(f)
    if "oni" not in data:
        raise SystemExit("build_standalone: public/data/oni.json is missing")
    data["manifest"] = {"note": "embedded by build_standalone.py",
                        "series": {k: (k in data) for k in SERIES}}
    embed = "window.__EMBEDDED__=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";"
    embed = embed.replace("</", "<\\/")          # a data string can never close the <script>

    # All rewriting is done on the page SHELL, with placeholders standing in for the
    # inlined stylesheet and scripts, so no pattern can ever touch library code.
    CSS_SLOT, JS_SLOT = "\x00STANDALONE_CSS\x00", "\x00STANDALONE_JS\x00"
    # ---- 1. stylesheet link -> placeholder
    html = sub_once(r'<link rel="stylesheet" href="assets/style\.css">', CSS_SLOT, html, "stylesheet link")
    # ---- 2. drop the CSP (comment + meta): the inline scripts would violate it
    html = re.sub(r'<!-- Content-Security-Policy.*?-->\s*', "", html, flags=re.S)
    html = sub_once(r'<meta http-equiv="Content-Security-Policy"[^>]*>\s*', "", html, "CSP meta tag")
    # ---- 3. remove analytics entirely
    html = re.sub(r'<!-- Google tag.*?-->\s*', "", html, flags=re.S)
    html = re.sub(r'<script[^>]*googletagmanager[^>]*></script>\s*', "", html)
    html = re.sub(r'<script[^>]*assets/analytics\.js[^>]*></script>\s*', "", html)
    # ---- 4. the two deferred script tags -> placeholder
    html = sub_once(r'<script defer src="vendor/echarts\.min\.js"></script>\s*'
                    r'<script defer src="assets/app\.js"></script>', JS_SLOT, html, "echarts + app script pair")
    # ---- 5. links to the rest of the site -> absolute URLs on the live site
    html = re.sub(r'href="/(?!/)', f'href="{SITE_URL}/', html)
    html = re.sub(r'href="(archive/|admin\.html)"', lambda m: f'href="{SITE_URL}/{m.group(1)}"', html)

    # ---- integrity of the shell: nothing may still point at a local file
    for needle, why in [("googletagmanager", "analytics loader left in"),
                        ("analytics.js", "analytics script left in"),
                        ('src="assets/', "a local script/asset reference left in"),
                        ('src="vendor/', "a local library reference left in"),
                        ('href="assets/', "a local stylesheet reference left in"),
                        ('href="archive/', "a relative page link left in"),
                        ('href="admin.html', "a relative page link left in"),
                        ("Content-Security-Policy", "CSP meta left in")]:
        if needle in html:
            raise SystemExit(f"build_standalone: {why} ({needle!r})")

    # ---- 6. fill the placeholders (data first, then the library, then the app)
    html = html.replace(CSS_SLOT, "<style>\n" + css + "\n</style>")
    html = html.replace(JS_SLOT, "<script>\n" + embed + "\n</script>\n"
                                 "<script>\n" + ech + "\n</script>\n"
                                 "<script>\n" + appj + "\n</script>")
    return html, sorted(k for k in data if k != "manifest")

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the single-file, offline copy of the tracker.")
    ap.add_argument("--out", default=DIST, metavar="DIR", help="directory to write into (default: dist/)")
    args = ap.parse_args(argv)
    html, series = build()
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "el-nino-tracker-standalone.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {os.path.relpath(out)}  ({os.path.getsize(out):,} bytes; embedded: {', '.join(series)})")

if __name__ == "__main__":
    main()
