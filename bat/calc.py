"""Batting average: share of past long pitches that beat the benchmark.

1-year window: published 1–2 years ago, 12-month total return.
2-year window: published 2–3 years ago, 24-month total return.
Benchmark: SPY for US listings, XIC.TO for Canadian (.TO / .V).
Writes state/batting.json. Reads bat/pitches.json.
"""
import datetime as dt
import json
import os
import statistics as S
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import STATE, ensure

HERE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(HERE, "pitches.json"), encoding="utf-8"))
TODAY = pd.Timestamp(dt.date.today())
y1_end = (TODAY - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
y1_start = (TODAY - pd.DateOffset(years=2)).strftime("%Y-%m-%d")
y2_end = y1_start
y2_start = (TODAY - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
W = {"1y": (y1_start, y1_end, 12), "2y": (y2_start, y2_end, 24)}
# Known buyouts where the adjusted-close series stops. Extend this when a pitch was acquired.
BUY = {"CTLP": ("2025-07-31", 11.20), "IAS": ("2025-12-01", 10.30)}
cache = {}


def hist(t):
    if t not in cache:
        h = None
        try:
            h = yf.Ticker(t).history(start=y2_start, end=(TODAY + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), auto_adjust=True)["Close"]
        except Exception:
            h = None
        if h is None or h.empty:
            h = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        else:
            h.index = pd.DatetimeIndex(h.index).tz_localize(None)
        cache[t] = h
    return cache[t]


def ret(t, d0, m):
    h = hist(t)
    d0 = pd.Timestamp(d0)
    d1 = d0 + pd.DateOffset(months=m)
    if d1 > TODAY:
        return None, "window not complete"
    s = h[h.index >= d0]
    if s.empty:
        if t in BUY:
            return None, "buyout but no start price"
        return None, "no price data"
    p0 = s.iloc[0]
    e = h[h.index <= d1]
    if t in BUY and pd.Timestamp(BUY[t][0]) < d1:
        return BUY[t][1] / p0 - 1, "buyout price"
    if e.empty or e.index[-1] < d1 - pd.Timedelta(days=10):
        if t in BUY:
            return BUY[t][1] / p0 - 1, "buyout price"
        return (e.iloc[-1] / p0 - 1 if not e.empty else None), "last trade " + (str(e.index[-1].date()) if not e.empty else "")
    return e.iloc[-1] / p0 - 1, ""


def bret(b, d0, m):
    r, _ = ret(b, d0, m)
    return r


out = {}


def run(name, L):
    res = {"pitches": {}, "summary": {}, "excluded": []}
    for w, (a, b, m) in W.items():
        seen = set()
        rows = []
        for t, d, u, ti in sorted(L, key=lambda x: x[1]):
            if not (a <= d < b) or t in seen:
                continue
            seen.add(t)
            bm = "XIC.TO" if t.endswith((".TO", ".V")) else "SPY"
            r, note = ret(t, d, m)
            br = bret(bm, d, m)
            if r is None or br is None:
                res["excluded"].append(dict(ticker=t, date=d, window=w, why=note))
                continue
            rows.append(dict(ticker=t, date=d, url=u, title=ti, stock_ret=round(r, 4), bench=bm, bench_ret=round(br, 4), hit=int(r > br), note=note))
        res["pitches"][w] = rows
        if rows:
            ex = [x["stock_ret"] - x["bench_ret"] for x in rows]
            h = sum(x["hit"] for x in rows)
            bst = max(rows, key=lambda x: x["stock_ret"] - x["bench_ret"])
            wst = min(rows, key=lambda x: x["stock_ret"] - x["bench_ret"])
            res["summary"][w] = dict(
                hits=h,
                n=len(rows),
                pct=round(h / len(rows), 3),
                median_excess=round(S.median(ex), 4),
                best=f"{bst['ticker']} {bst['stock_ret']*100:+.0f}% vs {bst['bench_ret']*100:+.0f}%",
                worst=f"{wst['ticker']} {wst['stock_ret']*100:+.0f}% vs {wst['bench_ret']*100:+.0f}%",
                small=len(rows) < 5,
            )
        else:
            res["summary"][w] = None
    out[name] = res
    print(name, {w: (s and f"{s['hits']}/{s['n']}") for w, s in res["summary"].items()}, "excl", len(res["excluded"]))


for k, L in P.get("SUB", {}).items():
    run(k, L)
for k, L in P.get("SA", {}).items():
    run(k, L)
for k, why in P.get("NONE", {}).items():
    out[k] = {"pitches": {}, "summary": {"1y": None, "2y": None}, "note": why}
ensure(STATE)
dest = os.path.join(STATE, "batting.json")
json.dump(out, open(dest, "w", encoding="utf-8"), indent=1)
print("wrote", dest)
