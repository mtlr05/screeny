"""Weekly sweep: pull active Substack archives, dedupe against seen_posts.csv, write a triage file.

Default window is the last 7 days. Paths are repo-relative (config/, state/, reports/).
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys

import requests
import concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, REPORTS, SEEN, SOURCES, ensure, user_agent

ap = argparse.ArgumentParser(description="Sweep Substack sources for new posts")
ap.add_argument("--since", default=(dt.date.today() - dt.timedelta(days=7)).isoformat())
ap.add_argument("--sources", default=SOURCES)
ap.add_argument("--seen", default=SEEN)
ap.add_argument("--out-dir", default=REPORTS)
ap.add_argument("--limit", type=int, default=0, help="only the first N Substack sources (smoke tests)")
ap.add_argument("--dry-run", action="store_true", help="do not append state/seen_posts.csv")
ap.add_argument("--skip-earnings", action="store_true")
a = ap.parse_args()

H = {"User-Agent": user_agent()}
since = dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc)
ensure(a.out_dir, CACHE, os.path.dirname(a.seen))

with open(a.seen, newline="", encoding="utf-8") as f:
    seen = {r["url"] for r in csv.DictReader(f)}
with open(a.sources, newline="", encoding="utf-8") as f:
    src = [r for r in csv.DictReader(f) if r.get("type") == "substack" and r.get("url")]
if a.limit:
    src = src[: a.limit]


def pull(r):
    out = []
    try:
        for off in range(0, 200, 50):
            j = requests.get(
                f"{r['url'].rstrip('/')}/api/v1/archive?sort=new&limit=50&offset={off}",
                headers=H,
                timeout=20,
            ).json()
            if not j:
                break
            for p in j:
                if dt.datetime.fromisoformat(p["post_date"].replace("Z", "+00:00")) >= since:
                    out.append(
                        {
                            "sub": r["url"],
                            "url": p["canonical_url"],
                            "title": p["title"],
                            "subtitle": p.get("subtitle") or "",
                            "date": p["post_date"][:10],
                            "audience": p.get("audience"),
                            "wc": p.get("wordcount") or 0,
                        }
                    )
            if dt.datetime.fromisoformat(j[-1]["post_date"].replace("Z", "+00:00")) < since:
                break
    except Exception:
        return r["url"], None
    return r["url"], out


with cf.ThreadPoolExecutor(min(20, max(1, len(src)))) as ex:
    res = list(ex.map(pull, src))
dead = [u for u, o in res if o is None]
new = [p for u, o in res if o for p in o if p["url"] not in seen]
if not a.dry_run and new:
    with open(a.seen, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for p in new:
            w.writerow([p["url"], p["sub"], p["date"], p["title"], p["audience"], p["wc"], dt.date.today().isoformat()])

NEG = re.compile(
    r"portfolio update|monthly|weekly|roundup|recap|letter|macro|podcast|links|reading list|week in|digest|market update|watchlist|thread|interview|chart",
    re.I,
)
POS = re.compile(
    r"thesis|deep.?dive|undervalued|upside|multibagger|why i (own|bought)|initiat|long |\(\$?[A-Z]{2,5}\)|\$[A-Z]{2,5}|tsx|nasdaq|nyse|otc|spin.?off|compounder|bagger|mispriced|cheap",
    re.I,
)
cand = [p for p in new if p["audience"] == "everyone" and not NEG.search(p["title"] + " " + p["subtitle"]) and POS.search(p["title"] + " " + p["subtitle"])]

bl_path = os.path.join(os.path.dirname(a.seen), "backlog.json")
bl = json.load(open(bl_path, encoding="utf-8")) if os.path.exists(bl_path) else []
for x in bl:
    x["backlog"] = True
cand = cand + [x for x in bl if x["url"] not in {c["url"] for c in cand}]
fn = os.path.join(a.out_dir, f"triage_{dt.date.today().isoformat()}.json")
json.dump(cand, open(fn, "w", encoding="utf-8"), indent=1)
print(f"sources={len(src)} failed={len(dead)} new_posts={len(new)} candidates={len(cand)} (backlog {len(bl)}) -> {fn}")
if dead:
    print("failed_sources", dead[:20])
for p in cand:
    print("BACKLOG" if p.get("backlog") else "NEW", p["date"], p.get("wc"), p["url"], (p.get("title") or "")[:80])

dr = collections.Counter()
for p in new:
    if p["audience"] != "everyone":
        dr["paywalled"] += 1
    elif NEG.search(p["title"] + " " + p["subtitle"]):
        dr["not a single-stock pitch (recap/macro/list)"] += 1
    elif not POS.search(p["title"] + " " + p["subtitle"]):
        dr["not a single-stock pitch (no pitch signal in title)"] += 1
ST = {
    "date": dt.date.today().isoformat(),
    "since": a.since,
    "sources": len(src),
    "failed_sources": len(dead),
    "failed": dead,
    "sourced": len(new),
    "dropped": dict(dr),
    "candidates_new": len(cand) - len(bl),
    "backlog": len(bl),
    "dry_run": a.dry_run,
}
stats_fn = os.path.join(a.out_dir, f"stats_{dt.date.today().isoformat()}.json")
json.dump(ST, open(stats_fn, "w", encoding="utf-8"), indent=1)
print("STATS", json.dumps(ST))

if not a.skip_earnings:
    ed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "earnings_drops.py")
    try:
        print(subprocess.run([sys.executable, ed], capture_output=True, text=True, timeout=600).stdout)
    except Exception as e:
        print("earnings_drops failed:", e)
