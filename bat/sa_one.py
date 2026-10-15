"""Fetch one Seeking Alpha author's public article list (title, date, ticker, sentiment).

    python3 bat/sa_one.py "Author Name" author-slug

No cookies. Full bodies are not requested. If the API returns a bot check, stop.
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import user_agent

H = {"User-Agent": user_agent()}
HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, "sa_auth.json")
out = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
if len(sys.argv) < 3:
    print('usage: python3 bat/sa_one.py "Author Name" author-slug')
    sys.exit(2)
n, s = sys.argv[1], sys.argv[2]
force = os.environ.get("FORCE")
if not force and n in out and out[n].get("status") == "ok" and out[n].get("arts") and out[n]["arts"][0].get("tk") and not str(out[n]["arts"][0]["tk"][0]).isdigit():
    print("skip", n, len(out[n]["arts"]))
    raise SystemExit
arts = []
p = 1
st = "ok"
while True:
    r = requests.get(
        f"https://seekingalpha.com/api/v3/authors/{s}/articles",
        params={"page[size]": 50, "page[number]": p, "include": "primaryTickers,sentiments,secondaryTickers"},
        headers=H,
        timeout=45,
    )
    if r.status_code != 200:
        st = f"HTTP {r.status_code}"
        print(n, st, r.text[:200])
        if r.status_code in (401, 403, 429):
            print("bot check or access denied; stop gathering")
        break
    d = r.json()
    inc = {(i["type"], i["id"]): i for i in d.get("included", [])}
    for a in d["data"]:
        at = a["attributes"]
        rel = a["relationships"]
        tk = []
        for t in rel.get("primaryTickers", {}).get("data", []):
            ia = inc.get(("tag", t["id"]), {}).get("attributes", {})
            tk.append(ia.get("name") or ia.get("slug") or "")
        se = []
        for t in rel.get("sentiments", {}).get("data", []):
            ia = inc.get(("sentiment", t["id"]), {}).get("attributes", {})
            se.append(ia.get("type"))
        arts.append(
            dict(
                t=at["title"],
                d=at["publishOn"][:10],
                id=a["id"],
                tk=[x for x in tk if x],
                se=se,
                themes=list((at.get("themes") or {}).keys()),
            )
        )
    tp = d.get("meta", {}).get("page", {}).get("totalPages", 1)
    print(n, "page", p, "/", tp, "n", len(arts), "oldest", arts[-1]["d"] if arts else "")
    if p >= tp or (os.environ.get("ALL") is None and arts and arts[-1]["d"] < "2023-10-01"):
        break
    p += 1
    time.sleep(2.5)
out[n] = dict(slug=s, status=st, arts=arts)
json.dump(out, open(path, "w", encoding="utf-8"), indent=0)
print("DONE", n, st, len(arts), arts[0] if arts else "")
