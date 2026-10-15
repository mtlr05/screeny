"""Fetch Seeking Alpha author history from the public API (title, date, ticker, sentiment).

No cookies and no full bodies. Pass author names only if sa_one.py is not used;
this file lists a fixed set of slugs from the sample report. For anyone else, use sa_one.py.
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import user_agent

H = {"User-Agent": user_agent()}
SL = {
    "Eljaye Tellis": "eljaye-tellis",
    "Krzysztof Bogdanski": "krzysztof-bogdanski",
    "Stephen Tobin": "stephen-tobin",
    "Laurentian Research": "laurentian-research",
    "The Asymmetric Contrarian": "the-asymmetric-contrarian",
    "The Bullionaire": "the-bullionaire",
    "Ignacio Planas Gonzalez": "ignacio-planas-gonzalez",
    "Early Retiree": "early-retiree",
    "Bret Jensen": "bret-jensen",
    "Grassroots Trading": "grassroots-trading",
}
HERE = os.path.dirname(os.path.abspath(__file__))
out = {}
for n, s in SL.items():
    arts = []
    p = 1
    st = "ok"
    while True:
        r = requests.get(
            f"https://seekingalpha.com/api/v3/authors/{s}/articles",
            params={"page[size]": 50, "page[number]": p, "include": "primaryTickers,sentiments"},
            headers=H,
            timeout=30,
        )
        if r.status_code != 200:
            st = f"HTTP {r.status_code}"
            break
        d = r.json()
        inc = {(i["type"], i["id"]): i for i in d.get("included", [])}
        for a in d["data"]:
            at = a["attributes"]
            rel = a["relationships"]
            tk = []
            for t in (rel.get("primaryTickers") or {}).get("data") or []:
                ia = inc.get(("tag", t["id"]), {}).get("attributes", {})
                tk.append(ia.get("name") or "")
            se = []
            for t in (rel.get("sentiments") or {}).get("data") or []:
                ia = inc.get(("sentiment", t["id"]), {}).get("attributes", {})
                se.append(ia.get("type"))
            arts.append(dict(t=at["title"], d=at["publishOn"][:10], id=a["id"], tk=[x for x in tk if x], se=se, themes=list((at.get("themes") or {}).keys())))
        tp = d["meta"]["page"]["totalPages"]
        cut = "2023-10-01"
        if p >= tp or (arts and arts[-1]["d"] < cut):
            break
        p += 1
        time.sleep(2)
    out[n] = dict(slug=s, status=st, arts=arts)
    print(n, st, len(arts), arts[-1]["d"] if arts else "")
json.dump(out, open(os.path.join(HERE, "sa_auth.json"), "w", encoding="utf-8"), indent=0)
