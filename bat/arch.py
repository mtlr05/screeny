"""Pull a Substack archive back through the batting-average window. Writes bat/arch.json."""
import datetime as dt
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import user_agent

H = {"User-Agent": user_agent()}
cut = (dt.date.today() - dt.timedelta(days=365 * 3 + 20)).isoformat()
out = {}
for s in sys.argv[1:]:
    posts = []
    off = 0
    while True:
        try:
            r = requests.get(
                f"https://{s}.substack.com/api/v1/archive?sort=new&offset={off}&limit=50",
                headers=H,
                timeout=30,
            )
            d = r.json()
        except Exception as e:
            print(s, "err", e)
            break
        if not d:
            break
        posts += [
            dict(
                t=p.get("title"),
                st=p.get("subtitle"),
                d=(p.get("post_date") or "")[:10],
                u=p.get("canonical_url"),
                a=p.get("audience"),
                desc=(p.get("description") or "")[:300],
            )
            for p in d
        ]
        if d[-1].get("post_date", "")[:10] < cut:
            break
        off += 50
        time.sleep(1)
    out[s] = posts
    print(s, len(posts), posts[-1]["d"] if posts else "")
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arch.json"), "w", encoding="utf-8"), indent=0)
