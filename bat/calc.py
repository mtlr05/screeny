"""Batting average: share of past long pitches that beat the benchmark.

Default cohort width is 12 months. Default hold is 24 months (the 2-year
average): pitches published from 36 months ago up to 24 months ago.
The 1-year average is the same width held for 12 months.
auto benchmark: IWM, or XCS.TO for .TO and .V.
Writes state/batting.json. Reads bat/pitches.json.
"""
import argparse
import datetime as dt
import json
import os
import statistics as S
import sys
from calendar import monthrange

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import STATE, ensure

HERE = os.path.dirname(os.path.abspath(__file__))
# Known buyouts where the adjusted-close series stops. Extend this when a pitch was acquired.
BUY = {"CTLP": ("2025-07-31", 11.20), "IAS": ("2025-12-01", 10.30)}
BA_METHOD = "v3-iwm-xcs"


def _as_of(today):
    return dt.date.fromisoformat(str(today)[:10]) if today else dt.date.today()


def _shift_months(day, months):
    """Move a date by a number of months. The day is clamped to the target month."""
    months = int(months)
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = monthrange(year, month)[1]
    return dt.date(year, month, min(day.day, last))


def cohort(today=None, window_months=12, duration_months=24):
    """(start, end, hold_months). End is exclusive.

    Pitches published in [today - duration - window, today - duration).
    Each pitch is held for duration_months, so the return is finished.
    """
    anchor = _as_of(today)
    window_months = int(window_months)
    duration_months = int(duration_months)
    end = _shift_months(anchor, -duration_months)
    start = _shift_months(anchor, -(duration_months + window_months))
    return start.isoformat(), end.isoformat(), duration_months


def choose_benchmark(symbol, choice="auto"):
    """auto is IWM, or XCS.TO for .TO and .V. Any other choice is used for every pitch."""
    if choice and str(choice).lower() != "auto":
        return str(choice)
    sym = str(symbol or "")
    if sym.endswith(".TO") or sym.endswith(".V"):
        return "XCS.TO"
    return "IWM"


def window_bounds(today=None):
    """1y: published 1–2 years ago, held 12 months. 2y: published 2–3 years ago, held 24 months."""
    return {"1y": cohort(today, 12, 12), "2y": cohort(today, 12, 24)}


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


def _summary_from_scored(scored):
    """Report summary for one cohort. None when no pitch had a completed price."""
    rows = scored.get("rows") or []
    if not rows:
        return None
    ex = [x["stock_ret"] - x["bench_ret"] for x in rows]
    h = sum(x["hit"] for x in rows)
    bst = max(rows, key=lambda x: x["stock_ret"] - x["bench_ret"])
    wst = min(rows, key=lambda x: x["stock_ret"] - x["bench_ret"])
    return dict(
        hits=h,
        n=len(rows),
        pct=round(h / len(rows), 3),
        p_lt=p_lt_hits(h, len(rows)),
        median_excess=round(S.median(ex), 4),
        median_return=scored.get("median_return"),
        best=f"{bst['ticker']} {bst['stock_ret']*100:+.0f}% vs {bst['bench_ret']*100:+.0f}%",
        worst=f"{wst['ticker']} {wst['stock_ret']*100:+.0f}% vs {wst['bench_ret']*100:+.0f}%",
        small=len(rows) < 5,
    )


def batting_average(pitches, today=None, window_months=12, duration_months=24, benchmark="auto"):
    """One cohort. Prices and exclusions go through bat/lib.py.

    today is the as-of date. window_months is the publication-cohort width
    (default 12). duration_months is the hold (default 24). benchmark "auto"
    is IWM, or XCS.TO for .TO and .V. Any other symbol is used for every pitch.
    """
    import lib

    scored = lib.score(
        pitches,
        today=today,
        window_months=window_months,
        duration_months=duration_months,
        benchmark=benchmark,
    )
    return {
        "summary": _summary_from_scored(scored),
        "pitches": scored.get("rows") or [],
        "excluded": scored.get("excluded") or [],
        "benchmark": benchmark,
        "window_months": int(window_months),
        "duration_months": int(duration_months),
        "ba_method": BA_METHOD,
    }


def summarize(name, pitches, today=None, benchmark="auto"):
    """Both report windows. 1y is held 12 months. 2y is held 24 months. Cohort width is 12."""
    res = {"pitches": {}, "summary": {}, "excluded": [], "ba_method": BA_METHOD}
    for window, duration in (("1y", 12), ("2y", 24)):
        one = batting_average(pitches, today=today, window_months=12, duration_months=duration, benchmark=benchmark)
        res["pitches"][window] = one["pitches"]
        res["summary"][window] = one["summary"]
        for item in one["excluded"]:
            item = dict(item)
            item["window"] = window
            res["excluded"].append(item)
    return res


def _load_pitches(path):
    if not os.path.exists(path):
        print("missing", path, "(run python3 bat/pitches.py first)")
        sys.exit(2)
    return json.load(open(path, encoding="utf-8"))


def _authors(doc):
    found = []
    for group in ("SUB", "SA"):
        for key, rows in (doc.get(group) or {}).items():
            found.append((key, rows))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write state/batting.json from bat/pitches.json")
    ap.add_argument("--today", default="", help="as-of date YYYY-MM-DD (default: today)")
    ap.add_argument("--window-months", type=int, default=None, help="publication cohort width (default 12)")
    ap.add_argument("--duration-months", type=int, default=None, help="hold in months (default 24 when set; both windows when omitted)")
    ap.add_argument("--benchmark", default="auto", help="auto = IWM, or XCS.TO for .TO and .V; or one symbol for every pitch")
    ap.add_argument("--pitches", default="", help="pitches JSON (default bat/pitches.json)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    path = args.pitches or os.path.join(HERE, "pitches.json")
    doc = _load_pitches(path)
    today = args.today or None
    one_window = args.window_months is not None or args.duration_months is not None
    window_months = 12 if args.window_months is None else args.window_months
    duration_months = 24 if args.duration_months is None else args.duration_months
    out = {}
    for key, rows in _authors(doc):
        if one_window:
            one = batting_average(rows, today=today, window_months=window_months, duration_months=duration_months, benchmark=args.benchmark)
            label = "1y" if duration_months == 12 and window_months == 12 else "2y" if duration_months == 24 and window_months == 12 else f"{duration_months}m"
            res = {
                "pitches": {label: one["pitches"]},
                "summary": {label: one["summary"]},
                "excluded": one["excluded"],
                "ba_method": BA_METHOD,
                "benchmark": args.benchmark,
            }
        else:
            res = summarize(key, rows, today=today, benchmark=args.benchmark)
            res["benchmark"] = args.benchmark
        out[key] = res
        print(key, {w: (s and f"{s['hits']}/{s['n']}") for w, s in res["summary"].items()}, "excl", len(res["excluded"]))
    for key, why in (doc.get("NONE") or {}).items():
        out[key] = {"pitches": {}, "summary": {"1y": None, "2y": None}, "note": why, "ba_method": BA_METHOD}
    ensure(STATE)
    dest = os.path.join(STATE, "batting.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), indent=1)
    print("wrote", dest)
    return 0


def _self_test():
    start, end, months = cohort("2026-10-18", 12, 24)
    assert (start, end, months) == ("2023-10-18", "2024-10-18", 24), (start, end, months)
    start, end, months = cohort("2026-10-18", 12, 12)
    assert (start, end, months) == ("2024-10-18", "2025-10-18", 12), (start, end, months)
    assert window_bounds("2026-10-18")["2y"][2] == 24
    assert choose_benchmark("ABC") == "IWM"
    assert choose_benchmark("ABC.TO") == "XCS.TO"
    assert choose_benchmark("ABC.V") == "XCS.TO"
    assert choose_benchmark("ABC.CN") == "IWM"
    assert choose_benchmark("ABC.NE") == "IWM"
    assert choose_benchmark("ABC", "SPY") == "SPY"
    assert p_lt_hits(2, 2) == 0.75
    assert p_lt_hits(0, 5) == 0.0
    assert p_lt_hits(15, 31) == 0.3601
    print("calc self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
