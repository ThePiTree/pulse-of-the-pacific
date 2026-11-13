#!/usr/bin/env python3
"""
Static checks on the deployable site in public/ — the mistakes that do not show
up until a page is live:

  * every page is well-formed and carries the strict Content-Security-Policy;
  * no inline script or inline event handler (the CSP would silently block it);
  * every local link, script, stylesheet and #anchor points at something real;
  * sitemap / robots / canonical URLs agree with the files on disk;
  * the JSON the front end (and outside consumers) read keeps its shape;
  * the committed CSV archive is internally consistent and in step with the data.

    python3 tests/test_site.py        # or: python3 tests/run_all.py

Standard library only; nothing is fetched and nothing is written.
"""
import csv, json, os, re, sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PUB = os.path.join(ROOT, "public")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import enso_rule
SITE = "https://elninotracker.org"
ANALYTICS_HOST = "https://www.googletagmanager.com"
# Outbound links that are still plain http. The Bureau of Meteorology served its old site
# over http only; switch this link (and delete the entry) once its https address is confirmed.
KNOWN_HTTP_LINKS = {"http://www.bom.gov.au/climate/enso/"}

PASS = FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f"  [{detail}]" if detail else ""))

def read(*parts):
    with open(os.path.join(PUB, *parts), encoding="utf-8") as f: return f.read()

class Page(HTMLParser):
    """Collects what the checks need: tags with attributes, script bodies, ids."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.scripts, self.ids, self._script = [], [], set(), None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a, self.getpos()))
        if "id" in a: self.ids.add(a["id"])
        if tag == "script": self._script = [a, ""]
    handle_startendtag = handle_starttag
    def handle_data(self, data):
        if self._script is not None: self._script[1] += data
    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append(tuple(self._script)); self._script = None

def csp_of(page):
    for tag, a, _ in page.tags:
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "content-security-policy":
            out = {}
            for part in (a.get("content") or "").split(";"):
                bits = part.split()
                if bits: out[bits[0]] = bits[1:]
            return out
    return None

def local_target(page_rel, url):
    """Map a local URL found in page_rel to the file it must resolve to."""
    path = urlsplit(url).path
    base = PUB if path.startswith("/") else os.path.join(PUB, os.path.dirname(page_rel))
    target = os.path.normpath(os.path.join(base, path.lstrip("/")))
    if path.endswith("/") or os.path.isdir(target): target = os.path.join(target, "index.html")
    return target

pages = sorted(os.path.relpath(os.path.join(dp, fn), PUB).replace(os.sep, "/")
               for dp, _, fs in os.walk(PUB) for fn in fs if fn.endswith(".html") and "vendor" not in dp)
ok("the five pages of the site are all present",
   set(pages) >= {"index.html", "admin.html", "privacy/index.html", "creator/melyssa-kimura/index.html"}, str(pages))

canonicals = {}
for rel in pages:
    raw = read(*rel.split("/"))
    low = raw.lower()
    p = Page(); p.feed(raw)
    ok(f"{rel}: starts with <!doctype html>", low.lstrip().startswith("<!doctype html>"))
    for t in ("<head", "</head>", "<body", "</body>", "</html>"):
        n = len(re.findall(re.escape(t) + (r"[\s>]" if not t.endswith(">") else ""), low))
        ok(f"{rel}: exactly one {t}{'' if t.endswith('>') else '>'}", n == 1, f"found {n}")
    ok(f"{rel}: declares a language and UTF-8", re.search(r"<html[^>]*\blang=", low) is not None and "charset=\"utf-8\"" in low.replace("'", '"'))

    # ---- Content-Security-Policy
    csp = csp_of(p)
    ok(f"{rel}: has a Content-Security-Policy meta tag", csp is not None)
    if csp:
        loads_analytics = any(t == "script" and (a.get("src") or "").startswith(ANALYTICS_HOST) for t, a, _ in p.tags)
        allowed = {"'self'"} | ({ANALYTICS_HOST} if loads_analytics else set())
        ok(f"{rel}: script-src is exactly what the page needs ('self'" + (" + analytics)" if loads_analytics else ")"),
           set(csp.get("script-src", [])) == allowed, " ".join(csp.get("script-src", [])))
        ok(f"{rel}: CSP never allows unsafe-eval or inline script",
           "'unsafe-eval'" not in sum(csp.values(), []) and "'unsafe-inline'" not in csp.get("script-src", []))
        ok(f"{rel}: CSP locks default-src, object-src, base-uri and form-action",
           csp.get("default-src") == ["'self'"] and csp.get("object-src") == ["'none'"]
           and csp.get("base-uri") == ["'none'"] and csp.get("form-action") == ["'none'"])
        csp_line = next(pos[0] for t, a, pos in p.tags if t == "meta" and (a.get("http-equiv") or "").lower() == "content-security-policy")
        first_load = min([pos[0] for t, a, pos in p.tags if t == "script" or (t == "link" and "stylesheet" in (a.get("rel") or ""))] or [10**9])
        ok(f"{rel}: the CSP comes before every script and stylesheet it governs", csp_line < first_load)
        # every external script / stylesheet origin is allowed by the page's own policy
        for t, a, _ in p.tags:
            if t == "script" and a.get("src", "").startswith("http"):
                o = "{0.scheme}://{0.netloc}".format(urlsplit(a["src"]))
                ok(f"{rel}: script origin {o} is allowed by script-src", o in csp.get("script-src", []))
            if t == "link" and "stylesheet" in (a.get("rel") or "") and a.get("href", "").startswith("http"):
                o = "{0.scheme}://{0.netloc}".format(urlsplit(a["href"]))
                ok(f"{rel}: stylesheet origin {o} is allowed by style-src", o in csp.get("style-src", []))

    # ---- scripts: external files or JSON-LD data only
    for a, body in p.scripts:
        if a.get("type") == "application/ld+json":
            try: json.loads(body); good = True
            except ValueError: good = False
            ok(f"{rel}: JSON-LD block is valid JSON", good)
        else:
            ok(f"{rel}: <script> loads a file and has no inline code", bool(a.get("src")) and not body.strip(), body.strip()[:60])
    handlers = sorted({k for _, a, _ in p.tags for k in a if k.lower().startswith("on")})
    ok(f"{rel}: no inline event handlers (CSP would block them)", not handlers, ", ".join(handlers))

    # ---- links
    for t, a, pos in p.tags:
        for attr in ("href", "src"):
            url = a.get(attr)
            if url is None: continue
            where = f"{rel}:{pos[0]} <{t} {attr}=\"{url[:70]}\">"
            if url.lower().startswith("javascript:"):
                ok(f"{where}: no javascript: URLs", False)
            elif url.startswith(("mailto:", "tel:", "data:")):
                pass
            elif url.startswith("#"):
                ok(f"{where}: anchor target exists on the page", url == "#" or url[1:] in p.ids)
            elif url.startswith(("http://", "https://", "//")):
                if t == "a":      # a plain-http *link* still works; anything the page LOADS must be https
                    ok(f"{where}: external link uses https (or is a known exception)", url.startswith("https://") or url in KNOWN_HTTP_LINKS)
                else:
                    ok(f"{where}: everything the page loads from elsewhere uses https", url.startswith("https://"))
                if t == "a" and a.get("target") == "_blank":
                    ok(f"{where}: target=_blank link carries rel=noopener", "noopener" in (a.get("rel") or ""))
            else:
                target = local_target(rel, url)
                ok(f"{where}: local file exists", os.path.isfile(target), os.path.relpath(target, PUB))
                frag = urlsplit(url).fragment
                if frag and target.endswith(".html") and os.path.isfile(target):
                    q = Page(); q.feed(open(target, encoding="utf-8").read())
                    ok(f"{where}: #{frag} exists on the target page", frag in q.ids)
        if t == "link" and a.get("rel") == "canonical":
            canonicals[rel] = a.get("href")

# ------------------------------------------------- canonical / sitemap / robots
for rel, url in canonicals.items():
    expect = SITE + "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
    ok(f"{rel}: canonical URL matches where the file is served", url == expect, f"{url} != {expect}")
ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
locs = [e.text.strip() for e in ET.fromstring(read("sitemap.xml")).findall("s:url/s:loc", ns)]
ok("sitemap: lists at least the home page", SITE + "/" in locs)
ok("sitemap: no duplicate entries", len(locs) == len(set(locs)))
for loc in locs:
    ok(f"sitemap: {loc} is on this site and exists on disk",
       loc.startswith(SITE + "/") and os.path.isfile(local_target("index.html", loc[len(SITE):])))
ok("sitemap: every page with a canonical URL is listed", set(canonicals.values()) <= set(locs),
   str(sorted(set(canonicals.values()) - set(locs))))
robots = read("robots.txt")
ok("robots.txt: points crawlers at the sitemap", f"Sitemap: {SITE}/sitemap.xml" in robots)
ok("robots.txt: keeps the operations page out of search results", "Disallow: /admin.html" in robots
   and re.search(r'<meta name="robots" content="noindex', read("admin.html")) is not None)
ok("sitemap: the operations page is not advertised", not any("admin" in l for l in locs))

# ---------------------------------------------------------------- JavaScript
for js in ("assets/app.js", "assets/admin.js", "assets/analytics.js"):
    src = read(*js.split("/"))
    ok(f"{js}: no eval / Function constructor / document.write",
       not re.search(r"\beval\s*\(|new\s+Function\s*\(|document\.write\s*\(", src))
    ok(f"{js}: fetches only same-origin, relative URLs", not re.search(r"fetch\(\s*[\"'`]https?:", src))

# ------------------------------------- data files: the shape consumers rely on
def data(name):
    with open(os.path.join(PUB, "data", name), encoding="utf-8") as f: return json.load(f)
manifest = data("manifest.json")
ok("data/manifest.json: lists the eight series", set(manifest.get("series", {})) >= {"oni", "roni", "wksst", "soi", "heat", "events", "impacts", "roni_compare"})
for key, present in manifest.get("series", {}).items():
    ok(f"data/{key}.json: exists when the manifest says so", (not present) or os.path.isfile(os.path.join(PUB, "data", key + ".json")))
SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
for key in ("oni", "roni"):
    if not manifest.get("series", {}).get(key): continue
    d = data(key + ".json"); recs = d["records"]
    ok(f"data/{key}.json: meta keeps index / threshold / seasons / updated",
       d["meta"].get("index") == key.upper() and d["meta"].get("threshold") == 0.5 and d["meta"].get("seasons") == SEASONS and "updated" in d["meta"])
    ok(f"data/{key}.json: every record keeps y, s, m, t, v, c", all(set(r) >= {"y", "s", "m", "t", "v", "c"} for r in recs))
    ok(f"data/{key}.json: seasons are consistent (s matches m; c is E, L or N)",
       all(SEASONS[r["m"] - 1] == r["s"] and r["c"] in "ELN" for r in recs))
    ok(f"data/{key}.json: starts at DJF 1950 and is continuous, one season per month",
       (recs[0]["y"], recs[0]["s"]) == (1950, "DJF") and all((b["y"] * 12 + b["m"]) - (a["y"] * 12 + a["m"]) == 1 for a, b in zip(recs, recs[1:])))
    ok(f"data/{key}.json: values are plausible anomalies", all(isinstance(r["v"], (int, float)) and abs(r["v"]) < 5 for r in recs))
    if "classification" in d["meta"]:      # written by a pipeline that states its rule: hold it to that rule
        ok(f"data/{key}.json: every 'c' is what scripts/enso_rule.py gives for the values",
           [r["c"] for r in recs] == enso_rule.episode_codes([r["v"] for r in recs]))
for key, lim in (("wksst", 6), ("soi", 8), ("heat", 6)):
    if not manifest.get("series", {}).get(key): continue
    d = data(key + ".json"); recs = d["records"]
    ok(f"data/{key}.json: records keep t and v, in strictly increasing time order",
       all(set(r) >= {"t", "v"} for r in recs) and all(a["t"] < b["t"] for a, b in zip(recs, recs[1:])))
    ok(f"data/{key}.json: values are plausible", all(abs(r["v"]) <= lim for r in recs))
    ok(f"data/{key}.json: meta keeps source_url and updated", "source_url" in d["meta"] and "updated" in d["meta"])
status = data("status.json")
ok("data/status.json: reports all five sources with ok / records / latest / value / url",
   set(status.get("sources", {})) == {"oni", "roni", "wksst", "soi", "heat"}
   and all({"ok", "url", "cadence_days"} <= set(s) for s in status["sources"].values()))
ok("data/status.json: keeps a run history", isinstance(status.get("history"), list) and len(status["history"]) >= 1
   and all({"ts", "ok", "fail"} <= set(h) for h in status["history"]))

# ----------------------------------------- the committed archive, if it exists
ARCH = os.path.join(PUB, "archive")
if os.path.isfile(os.path.join(ARCH, "manifest.json")):
    with open(os.path.join(ARCH, "manifest.json"), encoding="utf-8") as f: am = json.load(f)
    def rows(name):
        with open(os.path.join(ARCH, name), newline="", encoding="utf-8") as f: return list(csv.reader(f))
    for name in am["files"]:
        ok(f"archive/{name}: listed in the manifest and present", os.path.isfile(os.path.join(ARCH, name)))
    page = read("archive", "index.html")
    for name in am["files"]:
        if name.endswith(".csv") or name.endswith(".md"):
            ok(f"archive/index.html: links to {name}", f'href="{name}"' in page)
    st = am["stats"]
    ok("archive: is in step with the data it was built from (same refresh timestamp)",
       st["generated"] == status["updated"].replace("T", " ").replace("Z", " UTC"), f"{st['generated']} vs {status['updated']}")
    for name, key, n, col in (("oni.csv", "oni", "oni_n", "oni_anomaly_c"), ("roni.csv", "roni", "roni_n", "roni_anomaly_c"),
                              ("nino34_weekly.csv", "wksst", "wk_n", "nino34_sst_anomaly_c"), ("soi_3month.csv", "soi", "soi_n", "soi_3month"),
                              ("heat_content_180w_100w.csv", "heat", "heat_n", "heat_content_anomaly_c")):
        r, recs = rows(name), data(key + ".json")["records"]
        ok(f"archive/{name}: one row per record in data/{key}.json", len(r) - 1 == st[n] == len(recs),
           f"csv {len(r) - 1}, manifest {st[n]}, json {len(recs)}")
        ok(f"archive/{name}: rectangular (every row has the header's column count)", all(len(x) == len(r[0]) for x in r))
        ok(f"archive/{name}: column '{col}' equals data/{key}.json value for value",
           col in r[0] and all(float(row[r[0].index(col)]) == rec["v"] for row, rec in zip(r[1:], recs)))
    total = 0
    for name in am["files"]:
        if name.startswith("vintages/"):
            r = rows(name); total += len(r) - 1
            ok(f"archive/{name}: header ends '..., revision' and rows are rectangular",
               r[0][0] == "first_seen_utc" and r[0][-1] == "revision" and all(len(x) == len(r[0]) for x in r))
            ok(f"archive/{name}: rows are in the order they were first seen", [x[0] for x in r[1:]] == sorted(x[0] for x in r[1:]))
    ok("archive: revision-record row count matches the manifest", total == st["vint_rows"], f"{total} vs {st['vint_rows']}")
    ok("archive/pipeline_runs.csv: one row per run in the manifest", len(rows("pipeline_runs.csv")) - 1 == st["runs_n"])
    ok("home page links to the archive, and the archive links home",
       'href="archive/"' in read("index.html") and 'href="../"' in page)
else:
    print("  note: public/archive/ has not been generated yet - archive checks skipped "
          "(run: python3 scripts/backfill_vintages.py && python3 scripts/export_archive.py)")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
