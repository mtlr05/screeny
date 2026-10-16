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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import STATE, ensure

HERE = os.path.dirname(os.path.abspath(__file__))
# Known buyouts where the adjusted-close series stops. Extend this when a pitch was acquired.
BUY = {"CTLP": ("2025-07-31", 11.20), "IAS": ("2025-12-01", 10.30)}


def window_bounds(today=None):
    """1y: published 1–2 years ago. 2y: published 2–3 years ago. End dates are exclusive."""
    today = dt.date.fromisoformat(str(today)[:10]) if today else dt.date.today()

    def back(years):
        try:
            return today.replace(year=today.year - years)
        except ValueError:
            return today.replace(year=today.year - years, day=28)

    y1_end = back(1).isoformat()
    y1_start = back(2).isoformat()
    y2_start = back(3).isoformat()
    return {"1y": (y1_start, y1_end, 12), "2y": (y2_start, y1_start, 24)}


def pitch_parts(row):
    """ticker, date, url, title, method, confidence. method is title, body, or blank."""
    if isinstance(row, dict):
        return (
            row.get("ticker") or "",
            (row.get("date") or "")[:10],
            row.get("url") or "",
            row.get("title") or "",
            row.get("method") or "",
            row.get("confidence"),
        )
    title = row[3] if len(row) > 3 else ""
    method = row[4] if len(row) > 4 else ""
    confidence = row[5] if len(row) > 5 else None
    return row[0], (row[1] or "")[:10], row[2], title, method, confidence


def p_lt_hits(hits, n):
    """P(X <= hits-1) for X ~ Binomial(n, 0.5). 0 when hits is 0. Blank when n is missing."""
    if n is None or n == "":
        return ""
    n = int(n)
    if n <= 0:
        return ""
    h = int(hits or 0)
    if h <= 0:
        return 0.0
    if h > n:
        h = n
    # sum_{k=0}^{h-1} C(n, k) / 2^n
    total = 0
    choose = 1
    for k in range(h):
        total += choose
        choose = choose * (n - k) // (k + 1)
    return round(total / (2 ** n), 4)


def pitches_in_window(pitches, window="2y", today=None):
    """First pitch per ticker inside the window. Rows are tuples or dicts."""
    start, end, _months = window_bounds(today)[window]
    seen = set()
    out = []
    keyed = []
    for row in pitches or []:
        ticker, day, _url, _title, _method, _conf = pitch_parts(row)
        keyed.append((day, ticker, row))
    for day, ticker, row in sorted(keyed, key=lambda item: item[0]):
        if start <= day < end and ticker not in seen:
            seen.add(ticker)
            out.append(row)
    return out


def summarize(name, pitches, today=None):
    """Batting-average record for one author. Market libraries load only when this runs."""
    import pandas as pd
    import yfinance as yf

    today_d = dt.date.fromisoformat(str(today)[:10]) if today else dt.date.today()
    TODAY = pd.Timestamp(today_d)
    W = window_bounds(today_d)
    cache = {}

    def hist(t):
        if t not in cache:
            h = None
            try:
                h = yf.Ticker(t).history(
                    start=W["2y"][0],
                    end=(TODAY + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    auto_adjust=True,
                )["Close"]
            except Exception:
                h = None
            if h is None or len(getattr(h, "index", [])) == 0:
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

    res = {"pitches": {}, "summary": {}, "excluded": []}
    for w, (_a, _b, m) in W.items():
        rows = []
        for raw in pitches_in_window(pitches, w, today_d):
            t, d, u, ti, method, conf = pitch_parts(raw)
            bm = "XIC.TO" if str(t).endswith((".TO", ".V")) else "SPY"
            r, note = ret(t, d, m)
            br = bret(bm, d, m)
            if r is None or br is None:
                res["excluded"].append(dict(ticker=t, date=d, window=w, why=note))
                continue
            row = dict(
                ticker=t,
                date=d,
                url=u,
                title=ti,
                stock_ret=round(r, 4),
                bench=bm,
                bench_ret=round(br, 4),
                hit=int(r > br),
                note=note,
            )
            if method:
                row["method"] = method
                row["confidence"] = conf
            rows.append(row)
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
                p_lt=p_lt_hits(h, len(rows)),
                median_excess=round(S.median(ex), 4),
                best=f"{bst['ticker']} {bst['stock_ret']*100:+.0f}% vs {bst['bench_ret']*100:+.0f}%",
                worst=f"{wst['ticker']} {wst['stock_ret']*100:+.0f}% vs {wst['bench_ret']*100:+.0f}%",
                small=len(rows) < 5,
            )
        else:
            res["summary"][w] = None
    return res


def main():
    path = os.path.join(HERE, "pitches.json")
    if not os.path.exists(path):
        print("missing", path, "(run python3 bat/pitches.py first)")
        sys.exit(2)
    P = json.load(open(path, encoding="utf-8"))
    out = {}
    for group in ("SUB", "SA"):
        for k, L in P.get(group, {}).items():
            res = summarize(k, L)
            out[k] = res
            print(k, {w: (s and f"{s['hits']}/{s['n']}") for w, s in res["summary"].items()}, "excl", len(res["excluded"]))
    for k, why in P.get("NONE", {}).items():
        out[k] = {"pitches": {}, "summary": {"1y": None, "2y": None}, "note": why}
    ensure(STATE)
    dest = os.path.join(STATE, "batting.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), indent=1)
    print("wrote", dest)


if __name__ == "__main__":
    main()
