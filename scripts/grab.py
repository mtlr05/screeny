"""Fetch Substack full text from the public post API. Paywalled or truncated bodies are saved and must be dropped, not scored.

Stdin: one URL per line. Or pass a triage JSON file.
"""
import html
import json
import os
import re
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import FULLTEXT, ensure, user_agent

H = {"User-Agent": user_agent()}
ensure(FULLTEXT)


def g(url):
    m = re.match(r"https://([^/]+)/p/([^/?#]+)", url)
    if not m:
        return url, None
    try:
        j = requests.get(f"https://{m.group(1)}/api/v1/posts/{m.group(2)}", headers=H, timeout=30).json()
    except Exception:
        return url, None
    b = j.get("body_html") or ""
    t = re.sub(r"<(br|/p|/h\d|/li)[^>]*>", "\n", b)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    fn = os.path.join(FULLTEXT, m.group(2)[:60] + ".txt")
    truncated = j.get("truncated_body_text") is not None and not b
    open(fn, "w", encoding="utf-8").write(
        f"{j.get('title')} | {j.get('post_date')} | {j.get('audience')} | words {j.get('wordcount')} | truncated={truncated}\n{url}\n{t}"
    )
    return url, fn, len(t.split()), "drop-preview" if truncated or j.get("audience") not in (None, "everyone") else "ok"


if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
    urls = [p["url"] for p in json.load(open(sys.argv[1], encoding="utf-8"))]
else:
    urls = [l.strip() for l in sys.stdin if l.strip()]
with cf.ThreadPoolExecutor(10) as ex:
    for r in ex.map(g, urls):
        print(r)
