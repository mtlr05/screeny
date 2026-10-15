"""Fetch full text for free newsletter posts listed in rerun/posts.json. Saves rerun/ft/*.json."""
import html
import json
import os
import re
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import RERUN, ensure, user_agent

H = {"User-Agent": user_agent()}
d = json.load(open(os.path.join(RERUN, "posts.json"), encoding="utf-8"))
P = [p for p in d["posts"] if p.get("audience") == "everyone" and p.get("ptype") == "newsletter"]
ft = os.path.join(RERUN, "ft")
ensure(ft)


def key(u):
    return re.sub(r"[^a-z0-9]+", "_", u.split("//")[1].lower())[:110]


def g(p):
    fn = os.path.join(ft, key(p["url"]) + ".json")
    if os.path.exists(fn):
        return 1
    m = re.match(r"https://([^/]+)/p/([^/?#]+)", p["url"])
    if not m:
        return 0
    j = None
    for _ in range(3):
        try:
            r = requests.get(f"https://{m.group(1)}/api/v1/posts/{m.group(2)}", headers=H, timeout=30)
            if r.status_code == 429:
                import time

                time.sleep(5)
                continue
            j = r.json()
            break
        except Exception:
            j = None
    if not j:
        return 0
    b = j.get("body_html") or ""
    t = re.sub(r"<(br|/p|/h\d|/li|/blockquote)[^>]*>", "\n", b)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    json.dump(
        dict(
            url=p["url"],
            title=j.get("title"),
            date=(j.get("post_date") or "")[:10],
            audience=j.get("audience"),
            wc=j.get("wordcount"),
            truncated=bool(j.get("truncated_body_text")) and not b,
            paywall_marker=("paywall" in b.lower()),
            text=t,
        ),
        open(fn, "w", encoding="utf-8"),
    )
    return 1


with cf.ThreadPoolExecutor(12) as ex:
    r = list(ex.map(g, P))
print(len(P), sum(r))
