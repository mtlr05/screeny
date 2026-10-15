"""Verify feeds from cache/crawl.json and write cache/sources_all.csv plus cache/swept_posts.json.

Article window: last ~4 months. A feed is active when it works and the latest post is within 180 days.
"""
import collections
import csv
import datetime as dt
import json
import os
import re
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, ensure, user_agent

H = {"User-Agent": user_agent()}
crawl_path = os.path.join(CACHE, "crawl.json")
src = json.load(open(crawl_path, encoding="utf-8"))
STRONG = re.compile(
    r"small.?cap|micro.?cap|special sit|canad|tsx|owner.?operat|spin.?off|serial acquir|multibagger|undervalued|deep.?value|compounder|moat",
    re.I,
)
keep = {
    k: v
    for k, v in src.items()
    if not v["how"].startswith("Substack recommendation from")
    or v["how"].split()[-1] in json.load(open(crawl_path, encoding="utf-8"))
    and (src[v["how"].split()[-1]]["how"].startswith("seed"))
    or STRONG.search((v.get("name") or "") + " " + v.get("hero", ""))
}
print(len(keep))
now = dt.datetime.now(dt.timezone.utc)
since = now - dt.timedelta(days=122)
active_cut = (now.date() - dt.timedelta(days=180)).isoformat()


def check(sub):
    b = f"https://{sub}.substack.com"
    posts = []
    ok = False
    last = ""
    try:
        for off in range(0, 200, 50):
            j = requests.get(f"{b}/api/v1/archive?sort=new&limit=50&offset={off}", headers=H, timeout=20).json()
            if not j:
                break
            ok = True
            for p in j:
                d = dt.datetime.fromisoformat(p["post_date"].replace("Z", "+00:00"))
                last = last or p["post_date"][:10]
                if d >= since:
                    posts.append(
                        {
                            "sub": sub,
                            "url": p["canonical_url"],
                            "title": p["title"],
                            "subtitle": p.get("subtitle") or "",
                            "date": p["post_date"][:10],
                            "audience": p.get("audience"),
                            "wc": p.get("wordcount") or 0,
                            "type": p.get("type"),
                        }
                    )
            if dt.datetime.fromisoformat(j[-1]["post_date"].replace("Z", "+00:00")) < since:
                break
        f = requests.get(b + "/feed", headers=H, timeout=20)
        feedok = f.status_code == 200 and b"<rss" in f.content[:500]
    except Exception:
        feedok = False
    return sub, ok, feedok, last, posts


with cf.ThreadPoolExecutor(20) as ex:
    res = list(ex.map(check, keep))
rows = []
allp = []
for sub, ok, feedok, last, posts in res:
    v = keep[sub]
    active = bool(last) and last >= active_cut
    rows.append(
        dict(
            name=v.get("name") or sub,
            type="substack",
            url=f"https://{sub}.substack.com",
            feed_url=f"https://{sub}.substack.com/feed",
            custom_domain=v.get("custom", ""),
            focus=v.get("hero", ""),
            how_discovered=v["how"],
            feed_ok=feedok,
            last_post=last,
            posts_in_window=len(posts),
            status="active" if feedok and active else ("dormant" if feedok else "dead"),
        )
    )
    allp += posts
ensure(CACHE)
json.dump(allp, open(os.path.join(CACHE, "swept_posts.json"), "w", encoding="utf-8"))
out_csv = os.path.join(CACHE, "sources_all.csv")
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, rows[0].keys() if rows else ["name"])
    w.writeheader()
    w.writerows(rows)
print(collections.Counter(r["status"] for r in rows), len(allp))
print("wrote", out_csv)
