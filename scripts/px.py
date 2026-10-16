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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bat"))
from _paths import PRICES, ensure, user_agent

H = {"User-Agent": user_agent()}
CACHE = PRICES


def _usable_cache(fn):
    """Ignore a cached timeout. A Not Found cache expires after 7 days."""
    if not os.path.exists(fn):
        return None
    age = time.time() - os.path.getmtime(fn)
    try:
        cached = json.load(open(fn, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    err = str(cached.get("err") or "").lower()
    status = cached.get("status") or ""
    if status == "timeout" or "timeout" in err or "timed out" in err or "no response" in err:
        return None
    if status == "notfound":
        return cached if age < 7 * 86400 else None
    if age < 6 * 3600:
        return cached
    return None


def series(sym):
    ensure(CACHE)
    fn = os.path.join(CACHE, sym.replace("^", "_") + ".json")
    cached = _usable_cache(fn)
    if cached is not None:
        return cached
    from prices import hard_get

    p1 = int(dt.datetime(2022, 6, 1).timestamp())
    p2 = int(time.time()) + 86400
    r = None
    for host in ["query1", "query2"]:
        try:
            r = hard_get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"},
                headers=H,
                wall=20,
                timeout=(5, 8),
            )
            if r.status_code == 200:
                break
        except (TimeoutError, requests.Timeout, requests.ConnectionError):
            r = None
        except Exception:
            r = None
        time.sleep(0.4)
    if r is None:
        # A timeout is not cached and is not a delisting.
        return {"err": f"no response for {sym}", "status": "timeout"}
    try:
        j = r.json()
    except Exception:
        j = {"http": r.status_code, "body": r.text[:100]}
    chart = j.get("chart") if isinstance(j, dict) else None
    res = (chart or {}).get("result") if isinstance(chart, dict) else None
    if not res:
        err = (chart or {}).get("error") if isinstance(chart, dict) else {}
        code = str((err or {}).get("code") or "") if isinstance(err, dict) else ""
        blob = str(j).lower()
        if code.lower() == "not found" or "not found" in blob:
            out = {"err": code or "Not Found", "status": "notfound"}
            json.dump(out, open(fn, "w", encoding="utf-8"))
            return out
        # Anything that is not a real Not Found stays uncached, including timeouts.
        return {"err": str(j)[:200], "status": "nodata"}
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
