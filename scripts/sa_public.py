"""Public Seeking Alpha reads. No cookies, no login, no paywall bypass.

Author history (batting averages): title, date, tickers, sentiment.
A new article is readable only when the public payload includes a full body.
If the request is blocked, short, or preview-only, the article is skipped and
must not be scored. A bot check means stop gathering.
"""
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import user_agent

H = {"User-Agent": user_agent()}
MIN_WORDS = 600


def _get(url, params=None):
    r = requests.get(url, params=params, headers=H, timeout=30)
    text = r.text or ""
    bot = r.status_code in (401, 403, 429) or bool(re.search(r"press\s*&\s*hold|bot check|captcha", text[:2000], re.I))
    return r, bot


def author_articles(slug, max_pages=1):
    """Metadata only: title, date, id, tickers, sentiment. Enough for past-pitch batting averages."""
    arts = []
    status = "ok"
    bot = False
    for p in range(1, max_pages + 1):
        r, bot = _get(
            f"https://seekingalpha.com/api/v3/authors/{slug}/articles",
            params={"page[size]": 20, "page[number]": p, "include": "primaryTickers,sentiments"},
        )
        if bot or r.status_code != 200:
            status = "bot_check" if bot else f"HTTP {r.status_code}"
            break
        d = r.json()
        inc = {(i["type"], i["id"]): i for i in d.get("included", [])}
        for a in d.get("data") or []:
            at = a.get("attributes") or {}
            rel = a.get("relationships") or {}
            tk = []
            for t in (rel.get("primaryTickers") or {}).get("data") or []:
                ia = inc.get(("tag", t["id"]), {}).get("attributes", {})
                tk.append(ia.get("name") or ia.get("slug") or "")
            se = []
            for t in (rel.get("sentiments") or {}).get("data") or []:
                ia = inc.get(("sentiment", t["id"]), {}).get("attributes", {})
                se.append(ia.get("type"))
            pub = at.get("publishOn") or ""
            arts.append({"title": at.get("title"), "date": pub[:10], "id": a.get("id"), "tickers": [x for x in tk if x], "sentiment": se})
        time.sleep(2)
    return {"slug": slug, "status": status, "bot_check": bot or status == "bot_check", "articles": arts}


def _words(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def article(id_or_url):
    """Try the public article payload. Skip unless the body is long enough to be the full text."""
    m = re.search(r"/article/(\d+)", id_or_url) or re.search(r"^(\d+)$", str(id_or_url))
    if not m:
        return {"status": "skipped", "reason": "not a Seeking Alpha article id", "id": id_or_url}
    aid = m.group(1)
    r, bot = _get(f"https://seekingalpha.com/api/v3/articles/{aid}")
    if bot:
        return {"status": "blocked", "bot_check": True, "reason": "bot check or access denied", "id": aid, "http": r.status_code}
    if r.status_code != 200:
        return {"status": "skipped", "reason": f"HTTP {r.status_code}", "id": aid, "bot_check": False}
    try:
        d = r.json()
    except Exception:
        return {"status": "skipped", "reason": "not JSON", "id": aid}
    at = ((d.get("data") or {}).get("attributes") or {})
    body = at.get("content") or ""
    text = _words(body)
    wc = len(text.split())
    paywall = bool(re.search(r"subscribe to read|continue reading|paywall|premium content", text[-800:], re.I))
    if wc < MIN_WORDS or paywall or not body:
        return {
            "status": "skipped",
            "reason": "preview-only or body not in the public payload",
            "id": aid,
            "title": at.get("title"),
            "words": wc,
            "bot_check": False,
        }
    return {"status": "full", "id": aid, "title": at.get("title"), "date": (at.get("publishOn") or "")[:10], "words": wc, "text": text, "bot_check": False}


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("author", "article"):
        print("usage: python3 scripts/sa_public.py author SLUG [pages]")
        print("       python3 scripts/sa_public.py article URL_OR_ID")
        sys.exit(2)
    if sys.argv[1] == "author":
        pages = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        out = author_articles(sys.argv[2], pages)
        print(json.dumps({k: v for k, v in out.items() if k != "articles"}, indent=1))
        for a in out["articles"]:
            print(a["date"], a["id"], a["tickers"], a["sentiment"], (a["title"] or "")[:80])
    else:
        out = article(sys.argv[2])
        show = dict(out)
        if "text" in show:
            show["text"] = show["text"][:400] + "..."
        print(json.dumps(show, indent=1))
