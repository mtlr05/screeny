"""Resolve tickers that passed the title screen to Yahoo symbols, quote, and market cap. Writes rerun/resolved.json."""
import json
import os
import re
import sys
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import RERUN, user_agent

R = json.load(open(os.path.join(RERUN, "screen1.json"), encoding="utf-8"))
s = requests.Session()
s.headers["User-Agent"] = user_agent()
try:
    s.get("https://fc.yahoo.com", timeout=20)
    crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text
except Exception:
    crumb = ""
SUF = {"TSX": ".TO", "TSXV": ".V", "TSX-V": ".V", "CSE": ".CN", "NEO": ".NE"}


def search(q):
    try:
        j = s.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": q, "quotesCount": 5, "newsCount": 0}, timeout=20).json()
        return [x for x in j.get("quotes", []) if x.get("quoteType") == "EQUITY"]
    except Exception:
        return []


def cand_sym(r):
    t = r.get("ticker")
    if t:
        if "." in t:
            return t
        return t + SUF.get(r.get("exch", ""), "")
    name = re.split(r"[:|\-–—(]", r["title"])[0].strip()
    q = search(name)
    return q[0]["symbol"] if q else None


todo = [
    r
    for r in R
    if r["reason"] is None
    or (r["reason"] == "not a single-stock pitch (no ticker focus)" and r.get("vsig", 0) >= 6)
    or r["reason"] == "hold/neutral/short or still researching"
]
with cf.ThreadPoolExecutor(8) as ex:
    syms = list(ex.map(cand_sym, todo))
for r, sy in zip(todo, syms):
    r["sym"] = sy
U = sorted({x for x in syms if x})
Q = {}


def quote_batch(symbols):
    if not symbols:
        return []
    try:
        q = s.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": ",".join(symbols), "crumb": crumb},
            timeout=30,
        ).json()
        return q["quoteResponse"]["result"]
    except Exception:
        return []


for i in range(0, len(U), 40):
    for x in quote_batch(U[i : i + 40]):
        Q[x["symbol"]] = {k: x.get(k) for k in ["shortName", "longName", "currency", "regularMarketPrice", "marketCap", "fullExchangeName", "exchange", "quoteType"]}
miss = [u for u in U if u not in Q and "." not in u]
alt = [m + x for m in miss for x in (".TO", ".V")]
for i in range(0, len(alt), 40):
    for x in quote_batch(alt[i : i + 40]):
        Q[x["symbol"]] = {k: x.get(k) for k in ["shortName", "longName", "currency", "regularMarketPrice", "marketCap", "fullExchangeName", "exchange", "quoteType"]}
json.dump({"todo": todo, "Q": Q}, open(os.path.join(RERUN, "resolved.json"), "w", encoding="utf-8"))
print(len(todo), len(U), len(Q))
