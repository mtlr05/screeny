"""Yahoo daily prices and total return from a publish date to the latest close.

    python3 scripts/px.py YYYY-MM-DD TICKER [TICKER...]
    from px import ret; ret('TICKER', 'YYYY-MM-DD')
"""
import datetime as dt
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import PRICES, ensure, user_agent

H = {"User-Agent": user_agent()}
CACHE = PRICES


def series(sym):
    ensure(CACHE)
    fn = os.path.join(CACHE, sym.replace("^", "_") + ".json")
    if os.path.exists(fn) and time.time() - os.path.getmtime(fn) < 6 * 3600:
        return json.load(open(fn, encoding="utf-8"))
    p1 = int(dt.datetime(2022, 6, 1).timestamp())
    p2 = int(time.time()) + 86400
    r = None
    for host in ["query1", "query2"]:
        try:
            r = requests.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"},
                headers=H,
                timeout=30,
            )
            if r.status_code == 200:
                break
        except Exception:
            r = None
        time.sleep(1)
    if r is None:
        out = {"err": f"no response for {sym}"}
        json.dump(out, open(fn, "w", encoding="utf-8"))
        return out
    try:
        j = r.json()
    except Exception:
        j = {"http": r.status_code, "body": r.text[:100]}
    res = (j.get("chart") or {}).get("result")
    if not res:
        out = {"err": str(j)[:200]}
    else:
        res = res[0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        ac = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
        rows = [
            (dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), c, a)
            for t, c, a in zip(ts, q["close"], ac)
            if c is not None and a is not None
        ]
        out = {
            "meta": {k: res["meta"].get(k) for k in ["currency", "exchangeName", "longName", "shortName", "regularMarketPrice", "regularMarketTime", "instrumentType"]},
            "rows": rows,
        }
    json.dump(out, open(fn, "w", encoding="utf-8"))
    time.sleep(0.4)
    return out


def ret(sym, date):
    s = series(sym)
    if "err" in s or not s.get("rows"):
        return None
    rows = s["rows"]
    first = [r for r in rows if r[0] >= date]
    if not first:
        return None
    if rows[0][0] > date:
        return {
            "start": first[0][0],
            "p0": first[0][1],
            "a0": first[0][2],
            "end": rows[-1][0],
            "p1": rows[-1][1],
            "a1": rows[-1][2],
            "ret": rows[-1][2] / first[0][2] - 1,
            "note": "data starts after publish date",
        }
    f = first[0]
    last = rows[-1]
    return {"start": f[0], "p0": f[1], "a0": f[2], "end": last[0], "p1": last[1], "a1": last[2], "ret": last[2] / f[2] - 1, "note": ""}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 scripts/px.py YYYY-MM-DD TICKER [TICKER...]")
        sys.exit(2)
    for sym in sys.argv[2:]:
        print(sym, ret(sym, sys.argv[1]))
