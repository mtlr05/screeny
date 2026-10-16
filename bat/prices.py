"""Yahoo chart prices for the batting average.

Every call has a hard wall-clock cap. A timeout is never cached.
Only a real Not Found is cached, for 7 days. A symbol with no dot and no
price data is retried as SYM.TO, then SYM.V. The benchmark is XIC.TO for
.TO and .V listings and SPY otherwise.
"""
import datetime as dt
import json
import os
import sys
import threading
import time
from calendar import monthrange

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import calc as batcalc
from _paths import PRICES, ensure, user_agent

PXSTAT = {"ok": 0, "timeout": 0, "notfound": 0, "nodata": 0}
_LOCK = threading.Lock()
NOTFOUND_TTL = 7 * 86400
OK_TTL = 7 * 86400


def hard_get(url, params=None, headers=None, wall=20, timeout=(5, 8)):
    """GET with a wall-clock cap. requests' own timeout does not cover a stalled read."""
    box = {}

    def run():
        try:
            box["r"] = requests.get(
                url,
                params=params,
                headers=headers or {"User-Agent": user_agent()},
                timeout=timeout,
            )
        except Exception as exc:
            box["e"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(wall)
    if thread.is_alive():
        raise TimeoutError(url)
    if "e" in box:
        raise box["e"]
    return box["r"]


def benchmark(symbol):
    sym = str(symbol or "")
    if sym.endswith(".TO") or sym.endswith(".V"):
        return "XIC.TO"
    return "SPY"


def _path(symbol):
    ensure(PRICES)
    safe = str(symbol).replace("^", "_").replace("/", "_")
    return os.path.join(PRICES, safe + ".json")


def _bump(status):
    with _LOCK:
        PXSTAT[status] = PXSTAT.get(status, 0) + 1


def _read_cache(symbol):
    path = _path(symbol)
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    age = time.time() - os.path.getmtime(path)
    status = data.get("status") or ""
    err = str(data.get("err") or "").lower()
    if status == "timeout" or "timeout" in err or "timed out" in err or "no response" in err:
        return None
    if data.get("rows"):
        if age > OK_TTL:
            return None
        return {"status": "ok", "rows": data["rows"]}
    if status == "notfound" and age <= NOTFOUND_TTL:
        return {"status": "notfound", "rows": None}
    return None


def _write(symbol, payload):
    path = _path(symbol)
    with _LOCK:
        json.dump(payload, open(path, "w", encoding="utf-8"))


def _rows_from(result):
    ts = result.get("timestamp") or []
    quote = (result.get("indicators") or {}).get("quote") or [{}]
    quote = quote[0]
    adj = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or quote.get("close") or []
    closes = quote.get("close") or []
    rows = []
    for stamp, close, adj_close in zip(ts, closes, adj):
        if close is None or adj_close is None:
            continue
        rows.append([dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime("%Y-%m-%d"), close, adj_close])
    rows.sort(key=lambda row: row[0])
    return rows


def _chart_once(symbol, period1, period2, host):
    return hard_get(
        f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"},
        wall=20,
        timeout=(5, 8),
    )


def fetch_chart(symbol, period1, period2):
    """Return (status, rows). status is ok, notfound, nodata, or timeout."""
    cached = _read_cache(symbol)
    if cached:
        return cached["status"], cached.get("rows")
    last = "timeout"
    for attempt in range(3):
        if attempt:
            time.sleep(0.4 * attempt)
        response = None
        timed_out = False
        for host in ("query1", "query2"):
            try:
                response = _chart_once(symbol, period1, period2, host)
            except (TimeoutError, requests.Timeout, requests.ConnectionError):
                timed_out = True
                response = None
                continue
            except Exception:
                timed_out = True
                response = None
                continue
            if response is not None and response.status_code == 200:
                break
        if response is None:
            last = "timeout" if timed_out else "nodata"
            continue
        if response.status_code == 404:
            _write(symbol, {"status": "notfound", "err": "Not Found"})
            _bump("notfound")
            return "notfound", None
        try:
            payload = response.json()
        except Exception:
            last = "nodata"
            continue
        error = ((payload.get("chart") or {}).get("error") or {})
        code = str(error.get("code") or "")
        if code.lower() == "not found":
            _write(symbol, {"status": "notfound", "err": code or "Not Found"})
            _bump("notfound")
            return "notfound", None
        result = (payload.get("chart") or {}).get("result")
        if not result:
            last = "nodata"
            continue
        rows = _rows_from(result[0])
        if not rows:
            last = "nodata"
            continue
        meta = result[0].get("meta") or {}
        _write(
            symbol,
            {
                "status": "ok",
                "meta": {k: meta.get(k) for k in ["currency", "exchangeName", "longName", "shortName", "instrumentType"]},
                "rows": rows,
            },
        )
        _bump("ok")
        return "ok", rows
    _bump(last if last in PXSTAT else "timeout")
    return last, None


def resolve_series(symbol, period1, period2, fallback=True):
    """Price series, retrying SYM.TO then SYM.V when the bare symbol has no data.

    A timeout is not treated as missing data and is not followed by a suffix retry.
    fallback=False is for benchmarks (SPY, XIC.TO), which are not retried as .TO/.V.
    """
    status, rows = fetch_chart(symbol, period1, period2)
    if status == "ok":
        return status, symbol, rows
    if status == "timeout" or not fallback or "." in str(symbol):
        return status, symbol, None
    for alt in (f"{symbol}.TO", f"{symbol}.V"):
        alt_status, alt_rows = fetch_chart(alt, period1, period2)
        if alt_status == "timeout":
            return "timeout", alt, None
        if alt_status == "ok":
            return "ok", alt, alt_rows
    return status, symbol, None


def add_months(day, months):
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = monthrange(year, month)[1]
    return dt.date(year, month, min(day.day, last))


def total_return(symbol, date, months, today=None, fallback=True):
    """(status, return). status ok, incomplete, timeout, notfound, or nodata."""
    today = today or dt.date.today()
    day = dt.date.fromisoformat(str(date)[:10])
    end = add_months(day, int(months))
    if end > today:
        return "incomplete", None
    period1 = int(dt.datetime(2022, 1, 1).timestamp())
    period2 = int(time.time()) + 86400
    status, _used, rows = resolve_series(symbol, period1, period2, fallback=fallback)
    if status != "ok" or not rows:
        return status, None
    start_rows = [row for row in rows if row[0] >= day.isoformat()]
    if not start_rows or not start_rows[0][2]:
        return "nodata", None
    start_px = start_rows[0][2]
    root = str(symbol).split(".")[0]
    if root in batcalc.BUY and batcalc.BUY[root][0] < end.isoformat():
        return "ok", batcalc.BUY[root][1] / start_px - 1
    end_rows = [row for row in rows if row[0] <= end.isoformat()]
    if not end_rows:
        return "nodata", None
    last = end_rows[-1]
    if last[0] < (end - dt.timedelta(days=10)).isoformat():
        return "nodata", None
    return "ok", last[2] / start_px - 1


def _self_test():
    """A socket that accepts and never answers must raise TimeoutError within the wall."""
    import socket

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def hold():
        try:
            conn, _addr = server.accept()
            time.sleep(2)
            conn.close()
        except Exception:
            pass

    threading.Thread(target=hold, daemon=True).start()
    started = time.time()
    try:
        hard_get(f"http://127.0.0.1:{port}/", wall=0.4, timeout=(5, 30))
    except TimeoutError:
        elapsed = time.time() - started
        assert elapsed < 1.5, elapsed
    else:
        raise SystemExit("hard_get did not time out")
    finally:
        server.close()
    assert benchmark("ABC.TO") == "XIC.TO"
    assert benchmark("ABC.V") == "XIC.TO"
    assert benchmark("ABC") == "SPY"
    assert benchmark("ABC.CN") == "SPY"
    print("prices self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
