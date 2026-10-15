"""Full-window sweep of every Substack source (no dedupe). Writes rerun/posts.json.

Defaults to the last ~4 months. Pass start and end dates as YYYY-MM-DD to override.
"""
import csv
import datetime as dt
import json
import os
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import RERUN, SOURCES, ensure, user_agent

today = dt.date.today()
S = sys.argv[1] if len(sys.argv) > 1 else (today - dt.timedelta(days=122)).isoformat()
E_ = sys.argv[2] if len(sys.argv) > 2 else today.isoformat()
H = {"User-Agent": user_agent()}
src = [r for r in csv.DictReader(open(SOURCES, newline="", encoding="utf-8")) if r["type"] == "substack"]


def pull(r):
    out = []
    try:
        for off in range(0, 400, 50):
            j = requests.get(
                f"{r['url'].rstrip('/')}/api/v1/archive?sort=new&limit=50&offset={off}",
                headers=H,
                timeout=25,
            ).json()
            if not j:
                break
            for p in j:
                d = p["post_date"][:10]
                if S <= d <= E_:
                    out.append(
                        dict(
                            source=r["name"],
                            stype="substack",
                            url=p["canonical_url"],
                            title=p["title"],
                            subtitle=p.get("subtitle") or "",
                            date=d,
                            audience=p.get("audience"),
                            wc=p.get("wordcount") or 0,
                            ptype=p.get("type"),
                        )
                    )
            if j[-1]["post_date"][:10] < S:
                break
        return r["name"], out, None
    except Exception as e:
        return r["name"], out, str(e)[:80]


with cf.ThreadPoolExecutor(24) as ex:
    res = list(ex.map(pull, src))
posts = [p for _, o, _ in res for p in o]
fails = [(n, e) for n, o, e in res if e]
ensure(RERUN)
json.dump({"posts": posts, "fails": fails, "n_sources": len(src), "manual": []}, open(os.path.join(RERUN, "posts.json"), "w", encoding="utf-8"))
print(len(src), "sources", len(posts), "posts", len(fails), "failed", fails[:5])
