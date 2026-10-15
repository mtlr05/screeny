"""Walk two levels of Substack recommendations from the seed list. Writes cache/crawl.json."""
import json
import os
import re
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, ensure, user_agent

H = {"User-Agent": user_agent()}
seeds = (
    "sylencecapital guillaumemeignin kairosresearch thestockstories thevaluationdesk1 p14capital "
    "themultibbagerinvestor multibaggerideas maaizkhan nickclayton moeonmargin mvcinvesting yianisz "
    "moodywriter13 montecristoinvesting kenderdu domumcapital spinoffanalysis pettycash reboundcapital "
    "clarksquarecapital jpprewitt microcapclub canadianvalue speedwellresearch nongaap "
    "wolfofharcourtstreet thescienceofhitting deepvalueinvesting specialsituationinvesting"
).split()


def base(s):
    return f"https://{s}.substack.com"


def info(sub):
    try:
        j = requests.get(base(sub) + "/api/v1/archive?limit=1", headers=H, timeout=15).json()
        return j[0]["publication_id"] if j else None
    except Exception:
        return None


def recs(sub):
    pid = info(sub)
    if not pid:
        return sub, None, []
    try:
        r = requests.get(f"{base(sub)}/api/v1/recommendations/from/{pid}", headers=H, timeout=15).json()
    except Exception:
        r = []
    return sub, pid, [x["recommendedPublication"] for x in r if x.get("recommendedPublication")]


KW = re.compile(
    r"small.?cap|micro.?cap|value|special sit|stock|invest|equit|compound|canad|tsx|owner|capital|multibagger|deep dive|undervalued|spin.?off|serial acquir|moat|alpha|fund|portfolio|research|thesis",
    re.I,
)
NEG = re.compile(r"crypto|bitcoin|forex|options trad|day trad|real estate|macro only|politic", re.I)
src = {}
for s in seeds:
    src[s] = {"name": s, "how": "seed: prior scored author / known small-cap writer", "hero": ""}
frontier = list(seeds)
seen = set()
for depth in (1, 2):
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(recs, [f for f in frontier if f not in seen]))
    nxt = []
    for sub, pid, rp in res:
        seen.add(sub)
        if sub in src:
            src[sub]["pid"] = pid
        for p in rp:
            sd = p.get("subdomain")
            txt = (p.get("name") or "") + " " + (p.get("hero_text") or "")
            if not sd or sd in src:
                continue
            if KW.search(txt) and not NEG.search(txt):
                src[sd] = {
                    "name": p.get("name"),
                    "how": f"Substack recommendation from {sub}",
                    "hero": (p.get("hero_text") or "")[:150],
                    "custom": p.get("custom_domain") or "",
                }
                nxt.append(sd)
    frontier = nxt[:250]
    print(depth, len(src))
ensure(CACHE)
json.dump(src, open(os.path.join(CACHE, "crawl.json"), "w", encoding="utf-8"))
print("wrote", os.path.join(CACHE, "crawl.json"))
