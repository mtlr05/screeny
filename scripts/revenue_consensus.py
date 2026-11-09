#!/usr/bin/env python3
"""Street revenue consensus from Yahoo Finance earningsTrend.

  python3 scripts/revenue_consensus.py TICKER [YEAR]

Prints each annual period with a revenue average and at least one analyst.
A timeout is not cached. A row with no analysts is not a consensus.
"""
import datetime as dt
import json
import os
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, ensure, user_agent

GAP_FULL = 0.10
OK_TTL = 24 * 3600
MODULES = "earningsTrend,financialData"
STORE = os.path.join(CACHE, "revenue_consensus")


def source_url(symbol):
    return (
        "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
        f"{symbol}?modules={MODULES}"
    )


def _raw(node):
    if isinstance(node, dict):
        return node.get("raw")
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return node
    return None


def _date(node):
    if isinstance(node, dict):
        if node.get("fmt"):
            return str(node["fmt"])
        raw = node.get("raw")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return dt.datetime.fromtimestamp(raw, dt.timezone.utc).strftime("%Y-%m-%d")
        return ""
    return str(node or "")


def _num(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _result(body):
    if not isinstance(body, dict):
        return None
    summary = body.get("quoteSummary") or {}
    if summary.get("error"):
        return None
    rows = summary.get("result") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    return rows[0]


def annual_rows(body):
    """Annual revenue rows with an average and at least one analyst.

    Quarterly periods are omitted. A zero or missing analyst count drops the row.
    """
    result = _result(body)
    if not result:
        return []
    financial = result.get("financialData") or {}
    currency = financial.get("financialCurrency")
    if isinstance(currency, dict):
        currency = currency.get("fmt") or currency.get("raw") or ""
    currency = str(currency or "")
    trend = ((result.get("earningsTrend") or {}).get("trend")) or []
    rows = []
    for item in trend:
        if not isinstance(item, dict):
            continue
        period = str(item.get("period") or "")
        if not period.endswith("y"):
            continue
        estimate = item.get("revenueEstimate") or {}
        analysts = _raw(estimate.get("numberOfAnalysts"))
        average = _raw(estimate.get("avg"))
        if analysts is None or analysts < 1 or average is None or average <= 0:
            continue
        rows.append({
            "period": period,
            "end": _date(item.get("endDate")),
            "avg": average,
            "low": _raw(estimate.get("low")),
            "high": _raw(estimate.get("high")),
            "analysts": int(analysts),
            "currency": currency,
        })
    return rows


def row_for_year(rows, year):
    """The annual row whose period end falls in `year`, or None."""
    prefix = str(year)
    matched = [row for row in rows if str(row.get("end") or "").startswith(prefix)]
    return matched[0] if matched else None


def gap_band(author, consensus):
    """Return (score, gap) for author / consensus - 1.

    1 at or above 10%, 0.5 when above zero and under 10%, else 0.
    """
    gap = author / consensus - 1
    if gap >= GAP_FULL - 1e-9:
        return 1, gap
    if gap > 1e-9:
        return 0.5, gap
    return 0, gap


def format_row(row):
    parts = [row["period"], "end", row["end"] or "unknown", "avg", _num(row["avg"])]
    if row.get("low") is not None:
        parts += ["low", _num(row["low"])]
    if row.get("high") is not None:
        parts += ["high", _num(row["high"])]
    parts += ["analysts", str(row["analysts"])]
    return " ".join(parts)


def _cache_path(symbol):
    ensure(STORE)
    safe = str(symbol).replace("^", "_").replace("/", "_")
    return os.path.join(STORE, safe + ".json")


def _read_cache(symbol):
    path = _cache_path(symbol)
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) >= OK_TTL:
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _session_get(session, url, params=None, wall=20):
    box = {}

    def run():
        try:
            box["r"] = session.get(url, params=params, timeout=(5, 12))
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


def _crumb_problem(status, body):
    if status in (401, 403):
        return True
    if isinstance(body, dict):
        blob = json.dumps(body).lower()
    else:
        blob = str(body).lower()
    return "crumb" in blob or "unauthorized" in blob


def fetch(symbol):
    """Return the quoteSummary body. Raise TimeoutError on a stall. Do not cache failures."""
    session = requests.Session()
    session.headers["User-Agent"] = user_agent()
    crumb = ""
    try:
        _session_get(session, "https://fc.yahoo.com", wall=15)
        crumb_response = _session_get(session, "https://query2.finance.yahoo.com/v1/test/getcrumb", wall=15)
        text = (crumb_response.text or "").strip()
        if text and "<" not in text and len(text) < 64:
            crumb = text
    except (TimeoutError, requests.RequestException):
        crumb = ""
    last_error = "no response"
    saw_timeout = False
    for host in ("query2", "query1"):
        url = f"https://{host}.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
        try:
            response = _session_get(
                session,
                url,
                params={"modules": MODULES, "crumb": crumb},
                wall=20,
            )
        except TimeoutError:
            saw_timeout = True
            last_error = "timeout"
            continue
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        try:
            body = response.json()
        except ValueError:
            last_error = f"http {response.status_code}"
            continue
        if _crumb_problem(response.status_code, body):
            raise RuntimeError(f"http {response.status_code}")
        if response.status_code != 200:
            last_error = f"http {response.status_code}"
            continue
        json.dump(body, open(_cache_path(symbol), "w", encoding="utf-8"))
        return body
    if saw_timeout and last_error == "timeout":
        raise TimeoutError(symbol)
    raise RuntimeError(last_error)


def load(symbol):
    """Cached body, or a fresh fetch. Returns (body, reason, as_of)."""
    path = _cache_path(symbol)
    cached = _read_cache(symbol)
    if cached is not None:
        as_of = dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()
        return cached, None, as_of
    try:
        return fetch(symbol), None, dt.date.today().isoformat()
    except TimeoutError:
        return None, "timeout", None
    except RuntimeError as exc:
        return None, str(exc), None
    except requests.RequestException as exc:
        return None, str(exc), None


def report(symbol, year=None):
    """Lines for one ticker. `status: unavailable` when nothing can be scored from."""
    lines = [f"symbol: {symbol}", f"source: {source_url(symbol)}"]
    body, reason, as_of = load(symbol)
    if body is None:
        lines.insert(1, "status: unavailable")
        lines.append(f"reason: {reason}")
        return lines
    lines.insert(1, "status: ok")
    if as_of:
        lines.append("as_of: " + as_of)
    rows = annual_rows(body)
    currency = rows[0]["currency"] if rows else ""
    if not rows:
        result = _result(body) or {}
        financial = result.get("financialData") or {}
        currency = financial.get("financialCurrency") or ""
        if isinstance(currency, dict):
            currency = currency.get("fmt") or ""
    if currency:
        lines.append(f"currency: {currency}")
    if not rows:
        lines[1] = "status: unavailable"
        lines.append("reason: no annual revenue estimate with at least 1 analyst")
        return lines
    for row in rows:
        lines.append(format_row(row))
    if year is not None:
        lines.append(f"year: {year}")
        match = row_for_year(rows, year)
        if match is None:
            lines.append("match: unavailable")
            lines.append(f"reason: no row for {year}")
        else:
            lines.append("match: " + format_row(match))
    return lines


def main(argv):
    if len(argv) not in (2, 3):
        print("usage: python3 scripts/revenue_consensus.py TICKER [YEAR]")
        return 2
    symbol = argv[1].strip()
    if not symbol:
        print("usage: python3 scripts/revenue_consensus.py TICKER [YEAR]")
        return 2
    year = None
    if len(argv) == 3:
        year = argv[2].strip()
        if len(year) != 4 or not year.isdigit():
            print("usage: python3 scripts/revenue_consensus.py TICKER [YEAR]")
            return 2
    for line in report(symbol, year):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
