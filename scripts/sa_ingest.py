#!/usr/bin/env python3
"""One Seeking Alpha Long Ideas pull. The browser reads. This script does not log in.

  python3 scripts/sa_ingest.py screen reports/sa_list_<date>.csv
  python3 scripts/sa_ingest.py check fulltext/sa_<id>.txt
  python3 scripts/sa_ingest.py merge reports/sa_candidates_<date>.csv reports/triage_<date>.json
  python3 scripts/sa_ingest.py self-test

List CSV: url,article_id,source,author,date,title,ticker,date_text
Candidates CSV extends seen_posts.csv:
url,source,date,title,audience,wordcount,first_seen_run,author,ticker,mcap_usd,exchange,sa_status,drop_reason
source on a candidate is "Seeking Alpha". Seeking Alpha is not a tracked source and is not added to seen_posts.csv.
Dedupe is state/sa_results.json. Counts for the report are state/sa_breakdown.json.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import FULLTEXT, REPORTS, STATE, ensure
import text_store

LIST_FIELDS = ["url", "article_id", "source", "author", "date", "title", "ticker", "date_text"]
CAND_FIELDS = [
    "url",
    "source",
    "date",
    "title",
    "audience",
    "wordcount",
    "first_seen_run",
    "author",
    "ticker",
    "mcap_usd",
    "exchange",
    "sa_status",
    "drop_reason",
]
CAP = 10e9
CADUSD = 0.72
NA = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "PNK", "OQB", "OQX", "OEM", "OBB", "TOR", "VAN", "CNQ", "NEO", "NAS", "NYS", "NGS", "NCQ"}
RECAP = re.compile(
    r"recap|portfolio review|portfolio update|weekly|monthly|market (outlook|update|wrap)|webinar|letter from|earnings in focus|closed ideas|the dip is here|why conviction|watchlist|week ahead|roundup|digest|top \d+|best \d+",
    re.I,
)
MULTI = re.compile(
    r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|several|these)\s+(top\s+)?(\w+\s+){0,3}(stocks|picks|names|plays|ideas|companies|reits|bdcs|etfs|funds|dividend)\b|\bvs\.?\b|\bversus\b|\bplays\b|\bpair trade\b",
    re.I,
)
FUNDW = re.compile(r"\b(ETF|ETN|fund|CEF|closed-end|trust units?|income fund)\b", re.I)
PAYWALL = re.compile(r"subscribe to continue|to continue reading|only available to premium|sign up to continue|subscribe to read", re.I)
BOT = re.compile(r"press\s*&\s*hold|bot check|captcha", re.I)
LONG = re.compile(r"beneficial long position in the shares of", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
XURL = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/\S+", re.I)
HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,}")
MIN_WORDS = 600
NON_ARTICLE = re.compile(r"/symbol/|/author/|marketplace|/alpha-picks/", re.I)


def scrub(text):
    text = EMAIL.sub("", text or "")
    text = XURL.sub("", text)
    text = HANDLE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def article_id(value):
    match = re.search(r"/article/(\d+)", value or "") or re.search(r"^(\d+)$", str(value or "").strip())
    return match.group(1) if match else ""


def ysym(ticker):
    """Yahoo symbol. :CA becomes .TO. A colon or -USD is not a US equity symbol."""
    if not ticker:
        return None
    token = ticker.strip().upper()
    if token.endswith(":CA"):
        return token[:-3].replace(".", "-") + ".TO"
    if ":" in token or "-USD" in token:
        return None
    return token.replace(".", "-")


def mcap_usd(quote, day, price_at=None):
    """Market cap in USD. Borderline caps are scaled back to the publish-day price when a price function is supplied."""
    cap = quote.get("marketCap")
    price = quote.get("regularMarketPrice")
    if not cap:
        return None
    usd = cap * (CADUSD if quote.get("currency") == "CAD" else 1)
    if price_at and 3e9 < usd < 40e9 and price:
        try:
            returned = price_at(quote.get("sym") or "", day)
        except Exception:
            returned = None
        if returned and returned.get("p1"):
            usd = usd * returned["p0"] / returned["p1"]
    return usd


def read_csv(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fields, rows):
    ensure(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    os.replace(tmp, path)


def load_json(path, default):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, doc):
    ensure(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
    os.replace(tmp, path)


def parse_day(date, date_text, today):
    day = (date or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return day
    text = (date_text or date or "").strip()
    anchor = dt.date.fromisoformat(today)
    low = text.lower()
    if low.startswith("today"):
        return anchor.isoformat()
    if low.startswith("yesterday"):
        return (anchor - dt.timedelta(days=1)).isoformat()
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})", text)
    if match:
        try:
            parsed = dt.datetime.strptime(f"{match.group(1)} {match.group(2)} {anchor.year}", "%b %d %Y").date()
        except ValueError:
            try:
                parsed = dt.datetime.strptime(f"{match.group(1)} {match.group(2)} {anchor.year}", "%B %d %Y").date()
            except ValueError:
                return ""
        if parsed > anchor + dt.timedelta(days=2):
            parsed = parsed.replace(year=anchor.year - 1)
        return parsed.isoformat()
    return ""


def screen_one(row, quotes, price_at=None):
    """Cheap screen for one list row. quotes maps a Yahoo symbol to a quote dict. No network."""
    title = row.get("title") or ""
    url = row.get("url") or ""
    if NON_ARTICLE.search(url) or "x.com/" in url.lower() or "twitter.com/" in url.lower():
        return None, "not a Seeking Alpha article"
    if not article_id(row.get("article_id") or url):
        return None, "not a Seeking Alpha article"
    tickers = [part for part in (row.get("ticker") or "").split(";") if part]
    primary = {ysym(part) for part in tickers if not re.search(r"\.DB|W$|WS$|\.U", part)}
    if RECAP.search(title):
        return None, "recap / portfolio / housekeeping"
    if MULTI.search(title) or len(primary - {None}) > 1:
        return None, "multi-stock title"
    if not tickers:
        return None, "no ticker in metadata"
    symbol = ysym(tickers[0])
    quote = quotes.get(symbol) if symbol else None
    if not symbol:
        return None, "not an equity (currency/crypto/commodity)"
    if not quote or quote.get("missing"):
        return None, "ticker not found on Yahoo"
    name = quote.get("longName") or ""
    if quote.get("quoteType") in ("ETF", "MUTUALFUND", "INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE") or FUNDW.search(name):
        return None, "ETF / fund / trust"
    if quote.get("exchange") not in NA:
        return None, "not US/Canada listed"
    cap = mcap_usd(quote, row.get("date") or "", price_at)
    if cap is None:
        return None, "no market cap data"
    if cap >= CAP:
        return None, "not small/mid cap (>=US$10B at publish)"
    return {
        "ticker": quote.get("sym") or symbol,
        "mcap_usd": str(round(cap)),
        "exchange": quote.get("exchange") or "",
    }, ""


def screen(list_path, out_path, results_path, since, today, quotes, price_at=None):
    raw_rows = read_csv(list_path)
    doc = load_json(results_path, {})
    seen_urls = set()
    dates = []
    drops = {}
    kept = []
    for raw in raw_rows:
        url = (raw.get("url") or "").strip()
        if url in seen_urls:
            drops["duplicate"] = drops.get("duplicate", 0) + 1
            continue
        if url:
            seen_urls.add(url)
        aid = article_id(raw.get("article_id") or url)
        if aid and aid in doc and doc[aid].get("status") in ("drop", "needs_score", "scored"):
            drops["already recorded"] = drops.get("already recorded", 0) + 1
            continue
        day = parse_day(raw.get("date") or "", raw.get("date_text") or "", today)
        if since and day and day < since:
            drops["before window"] = drops.get("before window", 0) + 1
            continue
        if day:
            dates.append(day)
        row = {
            "url": url,
            "article_id": aid,
            "title": scrub(raw.get("title") or ""),
            "author": scrub(raw.get("author") or ""),
            "date": day,
            "ticker": scrub(raw.get("ticker") or ""),
        }
        info, reason = screen_one(row, quotes, price_at)
        base = {
            "url": url,
            "source": "Seeking Alpha",
            "date": day,
            "title": row["title"],
            "audience": "everyone",
            "wordcount": "",
            "first_seen_run": today,
            "author": row["author"],
            "ticker": (info or {}).get("ticker") or row["ticker"],
            "mcap_usd": (info or {}).get("mcap_usd", ""),
            "exchange": (info or {}).get("exchange", ""),
            "sa_status": "screened" if info else "listed",
            "drop_reason": reason,
        }
        if info:
            kept.append(base)
            if aid:
                doc[aid] = {
                    "url": url,
                    "title": row["title"],
                    "author": row["author"],
                    "date": day,
                    "ticker": base["ticker"],
                    "mcap": base["mcap_usd"],
                    "status": "needs_score",
                    "reason": "screened",
                    "words": "",
                }
        else:
            drops[reason] = drops.get(reason, 0) + 1
            if aid:
                doc[aid] = {
                    "url": url,
                    "title": row["title"],
                    "author": row["author"],
                    "date": day,
                    "ticker": row["ticker"],
                    "mcap": "",
                    "status": "drop",
                    "reason": reason,
                    "words": "",
                }
    write_csv(out_path, CAND_FIELDS, kept)
    order_path = os.path.join(os.path.dirname(out_path) or ".", f"sa_read_order_{today}.csv")
    write_read_order(kept, doc, order_path)
    save_json(results_path, doc)
    summary = {
        "li": len(raw_rows),
        "li_from": min(dates) if dates else "",
        "li_to": max(dates) if dates else "",
        "kept": len(kept),
        "drops": drops,
    }
    save_json(results_path + ".screen.json", summary)
    print(f"Long Ideas rows: {len(raw_rows)}. Kept: {len(kept)}.")
    for reason, count in sorted(drops.items()):
        print(f"  {reason}: {count}")
    print(out_path)
    return kept, summary


def _section(text, name):
    match = re.search(rf"===\s*{re.escape(name)}\s*===\s*(.*?)(?=\n===|\Z)", text or "", re.S | re.I)
    return match.group(1).strip() if match else ""


def write_read_order(candidates, results, path):
    """Unread tickers first, then anything already read, each group by date."""

    def rank(row):
        aid = article_id(row.get("url") or "")
        record = results.get(aid) or {}
        done = 1 if record.get("status") == "scored" or record.get("words") else 0
        return (done, row.get("date") or "", row.get("ticker") or "")

    ordered = sorted(candidates, key=rank)
    write_csv(path, ["url", "article_id", "ticker", "date", "title"], [
        {
            "url": row.get("url") or "",
            "article_id": article_id(row.get("url") or ""),
            "ticker": row.get("ticker") or "",
            "date": row.get("date") or "",
            "title": row.get("title") or "",
        }
        for row in ordered
    ])
    return ordered


def text_is_usable(text):
    """Stored article text can be reused. Empty text and a bot-check page cannot."""
    return text_store.text_usable(text)


def stored_sa_text(aid, directory):
    if not aid or not directory:
        return ""
    path = os.path.join(directory, f"sa_{aid}.txt")
    if not os.path.isfile(path):
        return ""
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def resume(order_path, results_path, fulltext_dir=None):
    """Ids that still need a browser fetch, in the saved read order.

    A usable file in fulltext/ is reused and is not fetched again.
    """
    if fulltext_dir is None:
        fulltext_dir = FULLTEXT
    rows = read_csv(order_path)
    doc = load_json(results_path, {})
    pending = []
    reused = []
    for row in rows:
        aid = article_id(row.get("url") or "") or (row.get("article_id") or "")
        record = doc.get(aid) or {}
        if record.get("status") == "scored" or record.get("words"):
            continue
        if record.get("status") == "drop" and record.get("reason") != "bot check":
            continue
        item = {"id": aid, "ticker": row.get("ticker") or "", "url": row.get("url") or ""}
        if not text_is_usable(stored_sa_text(aid, fulltext_dir)):
            text_store.materialize(f"sa_{aid}.txt", fulltext_dir)
        if text_is_usable(stored_sa_text(aid, fulltext_dir)):
            reused.append(item)
            continue
        pending.append(item)
    print(f"Reuse stored Seeking Alpha text: {len(reused)}")
    for item in reused:
        print(f"  stored {item['id']} {item['ticker']} {item['url']}")
    print(f"Unread Seeking Alpha articles: {len(pending)}")
    for item in pending:
        print(f"  {item['id']} {item['ticker']} {item['url']}")
    return pending


def unwrap_lines(text):
    """Join wrapped PDF lines. Blank lines stay as paragraph breaks."""
    parts = []
    buf = ""
    for line in (text or "").splitlines():
        if not line.strip():
            if buf:
                parts.append(buf)
                buf = ""
            continue
        buf = (buf + " " + line.strip()).strip()
    if buf:
        parts.append(buf)
    return "\n".join(parts)


def parse_fulltext(text):
    def field(label):
        match = re.search(rf"^{label}:\s*(.*)$", text or "", re.M)
        return match.group(1).strip() if match else ""

    return {
        "url": field("URL"),
        "title": scrub(field("TITLE")),
        "author": scrub(field("AUTHOR")),
        "date": field("DATE"),
        "tickers": field("TICKERS"),
        "summary": _section(text, "SUMMARY"),
        "body": _section(text, "ARTICLE BODY"),
        "disclosure": _section(text, "ANALYST'S DISCLOSURE"),
    }


def _base_symbol(symbol):
    token = (symbol or "").upper().strip()
    token = token.split(":")[-1]
    for suffix in (".TO", ".V", ".CN", ".NE"):
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token.split(".")[0]


def _norm_company(name):
    text = re.sub(r"\b(incorporated|inc|corp|corporation|ltd|limited|lp|l\.p|plc|company|co)\b", " ", name or "", flags=re.I)
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _issuer_name(name):
    head = re.split(r"\b(notes?|preferred|preference|bond|debenture|due)\b", name or "", maxsplit=1, flags=re.I)[0]
    return _norm_company(head)


def _is_other_security(symbol, quote):
    name = (quote or {}).get("longName") or ""
    if (quote or {}).get("quoteType") in ("PREFERRED", "BOND"):
        return True
    if re.search(r"\b(notes?|preferred|preference|bond|debenture|baby bond)\b", name, re.I):
        return True
    if re.search(r"(?:\.PR|PR[A-Z]?|[-.]P[A-Z]?)$", (symbol or "").upper()):
        return True
    return False


def _same_company_name(left, right):
    a = _issuer_name((left or {}).get("longName") or "")
    b = _issuer_name((right or {}).get("longName") or "")
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter.split()) >= 2 and longer.startswith(shorter)


def disclosed_symbols(disclosure):
    match = LONG.search(disclosure or "")
    if not match:
        return []
    tail = (disclosure or "")[match.end():]
    tail = re.split(r"\.\s", tail, maxsplit=1)[0]
    found = re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b", tail)
    stop = {"I", "A", "AN", "AND", "THE", "OF", "IN", "OR", "SA", "ET", "US", "USA"}
    return [item for item in found if item not in stop]


def long_relation(article, disclosed, quotes=None):
    """match, long_other_security, or unrelated. quotes maps a symbol to a Yahoo quote."""
    quotes = quotes or {}
    article_key = ysym(article) or (article or "").upper()
    article_quote = quotes.get(article_key) or quotes.get(article or "")
    other = []
    for raw in disclosed or []:
        disclosed_key = ysym(raw) or raw.upper()
        disclosed_quote = quotes.get(disclosed_key) or quotes.get(raw)
        other_security = _is_other_security(raw, disclosed_quote)
        bases_equal = _base_symbol(article) == _base_symbol(raw) and bool(_base_symbol(article))
        names_equal = _same_company_name(article_quote, disclosed_quote)
        exact = article_key and article_key == disclosed_key
        if other_security and (names_equal or bases_equal or (article_key and disclosed_key.startswith(article_key))):
            other.append(raw)
            continue
        if exact or (bases_equal and not other_security) or (names_equal and not other_security):
            if bases_equal and article_quote and disclosed_quote and not names_equal and not exact:
                continue
            return "match", ""
    if other:
        return "long_other_security", "long_other_security: " + ", ".join(other)
    return "unrelated", ""


def classify_text(text, ticker="", quotes=None):
    """full, preview, not_long, long_other_security, or blocked. A bot-check page is blocked."""
    if BOT.search(text or ""):
        return "blocked", "bot check"
    parsed = parse_fulltext(text or "")
    words = len(unwrap_lines(parsed["body"]).split())
    if words < MIN_WORDS or PAYWALL.search(text or "") or not parsed["disclosure"]:
        return "preview", "preview or missing analyst disclosure"
    if not LONG.search(parsed["disclosure"]):
        return "not_long", "author not long"
    article = ticker or ""
    if not article:
        match = re.search(r"\(([A-Z]{1,6}(?:\.[A-Z]{1,3})?)\)", parsed.get("tickers") or "")
        article = match.group(1) if match else ""
    relation, detail = long_relation(article, disclosed_symbols(parsed["disclosure"]), quotes)
    if relation == "match":
        return "full", ""
    if relation == "long_other_security":
        return "long_other_security", detail
    return "not_long", "author not long"


def check(path, results_path, candidates_path="", quotes=None):
    text = open(path, encoding="utf-8").read()
    if text_is_usable(text):
        text_store.publish_file(path)
    parsed = parse_fulltext(text)
    aid = article_id(parsed["url"] or os.path.basename(path))
    doc = load_json(results_path, {})
    existing = doc.get(aid) or {}
    if existing.get("status") == "scored":
        print(f"{aid} already scored")
        return 0
    article = existing.get("ticker") or ""
    if quotes is None:
        symbols = []
        for raw in [article] + disclosed_symbols(parsed.get("disclosure") or ""):
            key = ysym(raw) if raw.endswith(":CA") else (raw or "").upper()
            if key and key not in symbols:
                symbols.append(key)
        try:
            quotes = fetch_quotes(symbols)
        except QuoteFetchError as exc:
            print(f"WARNING: {exc}")
            quotes = {}
    status, reason = classify_text(text, article, quotes)
    words = len((parsed["body"] or "").split())
    record = {
        "url": parsed["url"] or existing.get("url") or "",
        "title": parsed["title"] or existing.get("title") or "",
        "author": parsed["author"] or existing.get("author") or "",
        "date": existing.get("date") or "",
        "ticker": existing.get("ticker") or "",
        "mcap": existing.get("mcap") or "",
        "status": "needs_score" if status == "full" else "drop",
        "reason": reason,
        "words": words,
    }
    if aid:
        doc[aid] = record
        save_json(results_path, doc)
    if candidates_path and os.path.exists(candidates_path):
        rows = read_csv(candidates_path)
        for row in rows:
            if article_id(row.get("url") or "") == aid:
                row["wordcount"] = str(words)
                row["audience"] = "preview" if status == "preview" else "everyone"
                row["sa_status"] = {
                    "full": "full",
                    "preview": "preview",
                    "not_long": "not_long",
                    "long_other_security": "long_other_security",
                    "blocked": "blocked",
                }[status]
                row["drop_reason"] = reason
        write_csv(candidates_path, CAND_FIELDS, rows)
    print(f"{aid} {status}")
    if status == "blocked":
        print("Bot check. Ask the user to resolve Press & Hold in the browser. Wait until the article loads, then continue reading. Do not score this page.")
        return 3
    return 0


def merge_counts(candidates):
    """Count from sa_status. drop_reason does not change the counts."""
    previews = not_long = unread = read = other = 0
    for row in candidates:
        status = (row.get("sa_status") or "").strip()
        if status == "preview":
            previews += 1
        elif status == "not_long":
            not_long += 1
        elif status == "long_other_security":
            other += 1
        elif status == "full":
            read += 1
        elif status in ("screened", "blocked"):
            unread += 1
    return {"read": read, "previews": previews, "skipped_unread": unread, "not_long": not_long, "long_other_security": other}


def merge(candidates_path, triage_path, results_path, breakdown_path):
    candidates = read_csv(candidates_path)
    doc = load_json(results_path, {})
    screen_summary = load_json(results_path + ".screen.json", {})
    triage = load_json(triage_path, [])
    if not isinstance(triage, list):
        triage = []
    triage_urls = {(row.get("url") or "").rstrip("/") for row in triage}
    counts = merge_counts(candidates)
    added = 0
    for row in candidates:
        status = (row.get("sa_status") or "").strip()
        if row.get("drop_reason") and status != "full":
            continue
        if status != "full":
            continue
        aid = article_id(row.get("url") or "")
        record = doc.get(aid) if isinstance(doc.get(aid), dict) else {}
        url = (row.get("url") or (record or {}).get("url") or "").rstrip("/")
        if not url or url in triage_urls or (record or {}).get("in_triage"):
            continue
        triage.append(
            {
                "sub": "seekingalpha",
                "url": url,
                "title": row.get("title") or (record or {}).get("title") or "",
                "subtitle": "",
                "date": (row.get("date") or (record or {}).get("date") or "")[:10],
                "audience": "everyone",
                "wc": row.get("wordcount") or (record or {}).get("words") or "",
                "source": "Seeking Alpha",
                "ticker": row.get("ticker") or (record or {}).get("ticker") or "",
                "author": scrub(row.get("author") or (record or {}).get("author") or ""),
            }
        )
        triage_urls.add(url)
        if aid:
            record = dict(record or {})
            record["in_triage"] = True
            doc[aid] = record
        added += 1
    prior = load_json(breakdown_path, {})
    breakdown = {
        "li": screen_summary.get("li", len(candidates)),
        "li_from": screen_summary.get("li_from", ""),
        "li_to": screen_summary.get("li_to", ""),
        "kept": screen_summary.get("kept", counts["read"]),
        "read": counts["read"],
        "previews": counts["previews"],
        "skipped_unread": counts["skipped_unread"],
        "not_long": counts["not_long"],
        "long_other_security": [
            {"article": row.get("ticker") or "", "disclosed": row.get("drop_reason") or "", "url": row.get("url") or ""}
            for row in candidates
            if (row.get("sa_status") or "") == "long_other_security"
        ],
        "unread": [
            {"id": article_id(row.get("url") or ""), "ticker": row.get("ticker") or ""}
            for row in candidates
            if (row.get("sa_status") or "") in ("screened", "blocked")
        ],
        "passed": sum(1 for item in doc.values() if isinstance(item, dict) and item.get("in_triage")),
        "scored": prior.get("scored", 0),
    }
    save_json(triage_path, triage)
    save_json(results_path, doc)
    save_json(breakdown_path, breakdown)
    print(f"Merged {added} Seeking Alpha articles into {triage_path}.")
    print(
        f"Previews: {counts['previews']}. Author not long: {counts['not_long']}. "
        f"Not yet read: {counts['skipped_unread']}."
    )
    return added


class QuoteFetchError(RuntimeError):
    """Yahoo did not return enough quotes to screen the list."""


def _quote_fields(item, symbol):
    return {
        "quoteType": item.get("quoteType"),
        "exchange": item.get("exchange") or item.get("exchangeName"),
        "marketCap": item.get("marketCap"),
        "regularMarketPrice": item.get("regularMarketPrice"),
        "currency": item.get("currency"),
        "longName": item.get("longName") or item.get("shortName"),
        "shortName": item.get("shortName"),
        "sym": item.get("symbol") or symbol,
    }


def _chart_quote(session, symbol):
    response = session.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "1d"},
        timeout=30,
    )
    if getattr(response, "status_code", 0) != 200:
        return None
    try:
        result = ((response.json().get("chart") or {}).get("result")) or []
    except Exception:
        return None
    if not result:
        return None
    meta = result[0].get("meta") or {}
    return _quote_fields(meta, symbol)


def fetch_quotes(symbols, session=None, cache_path=None):
    """Yahoo v7 quote with a crumb, then v8 chart, then .V/.CN for a missing .TO.

    A fetch that leaves more than 30% of symbols missing raises QuoteFetchError
    instead of marking the whole list ticker-not-found. No Seeking Alpha login.
    """
    import time

    import requests

    from _paths import CACHE, user_agent

    symbols = [symbol for symbol in symbols if symbol]
    cache_path = cache_path or os.path.join(CACHE, "yq_cache.json")
    out = {}
    if os.path.exists(cache_path):
        try:
            out.update(json.load(open(cache_path, encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            out = {}
    if not symbols:
        return out
    own_session = session is None
    if own_session:
        session = requests.Session()
        session.headers["User-Agent"] = user_agent()
    need = [symbol for symbol in symbols if symbol not in out or out[symbol].get("missing")]
    if need and own_session:
        try:
            session.get("https://fc.yahoo.com", timeout=20)
            crumb = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=20).text
        except Exception as exc:
            print(f"WARNING: Yahoo crumb request failed: {exc}")
            crumb = ""
    else:
        crumb = ""
    for start in range(0, len(need), 50):
        batch = need[start : start + 50]
        if not batch:
            continue
        result = []
        try:
            response = session.get(
                "https://query2.finance.yahoo.com/v7/finance/quote",
                params={"symbols": ",".join(batch), "crumb": crumb},
                timeout=30,
            )
            if getattr(response, "status_code", 0) == 401:
                print("WARNING: Yahoo v7 quote returned HTTP 401. Falling back to the chart API.")
            elif getattr(response, "status_code", 0) != 200:
                print(f"WARNING: Yahoo v7 quote returned HTTP {getattr(response, 'status_code', 'error')}.")
            else:
                result = ((response.json().get("quoteResponse") or {}).get("result")) or []
        except Exception as exc:
            print(f"WARNING: Yahoo v7 quote failed: {exc}")
        got = {item.get("symbol"): item for item in result}
        for symbol in batch:
            quote = got.get(symbol)
            if quote:
                out[symbol] = _quote_fields(quote, symbol)
                continue
            chart = None
            try:
                chart = _chart_quote(session, symbol)
            except Exception as exc:
                print(f"WARNING: Yahoo chart failed for {symbol}: {exc}")
            if chart:
                chart["marketCap"] = None
                out[symbol] = chart
            else:
                out[symbol] = {"missing": 1}
        if start + 50 < len(need):
            time.sleep(0.3)
    for symbol in list(need):
        if not str(symbol).endswith(".TO") or not out.get(symbol, {}).get("missing"):
            continue
        base = symbol[:-3]
        for suffix in (".V", ".CN"):
            alt = base + suffix
            if alt not in out or out[alt].get("missing"):
                try:
                    response = session.get(
                        "https://query2.finance.yahoo.com/v7/finance/quote",
                        params={"symbols": alt, "crumb": crumb},
                        timeout=30,
                    )
                    result = ((response.json().get("quoteResponse") or {}).get("result")) or [] if response.status_code == 200 else []
                except Exception:
                    result = []
                if result:
                    out[alt] = _quote_fields(result[0], alt)
                else:
                    chart = _chart_quote(session, alt)
                    out[alt] = chart if chart else {"missing": 1}
                    if chart:
                        out[alt]["marketCap"] = None
            if out.get(alt) and not out[alt].get("missing"):
                resolved = dict(out[alt])
                resolved["sym"] = out[alt].get("sym") or alt
                out[symbol] = resolved
                break
    missing = [symbol for symbol in symbols if out.get(symbol, {}).get("missing")]
    if symbols and len(missing) / len(symbols) > 0.30:
        raise QuoteFetchError(
            f"Yahoo quotes missing for {len(missing)} of {len(symbols)} symbols. "
            "Stopping. These rows were not marked ticker-not-found."
        )
    try:
        ensure(os.path.dirname(cache_path) or ".")
        json.dump(out, open(cache_path, "w", encoding="utf-8"))
    except OSError as exc:
        print(f"WARNING: could not write quote cache: {exc}")
    return out


def _quotes_for(rows, supplied):
    if supplied is not None:
        return supplied
    symbols = []
    for row in rows:
        first = (row.get("ticker") or "").split(";")[0]
        symbol = ysym(first)
        if symbol:
            symbols.append(symbol)
    return fetch_quotes(sorted(set(symbols)))


def _fulltext(url, title, author, ticker, body, disclosure):
    return (
        f"URL: {url}\nTITLE: {title}\nAUTHOR: {author}\nDATE: Oct 13, 2026, 11:20 AM ET\n"
        f"TICKERS: Example ({ticker}) Stock\nRATING: not shown\n\n"
        f"=== SUMMARY ===\n- a bullet\n\n=== ARTICLE BODY ===\n{body}\n\n"
        f"=== AUTHOR ===\n{author}\n\n=== ANALYST'S DISCLOSURE ===\n{disclosure}\n"
    )


def self_test():
    """Offline fake rows. No network and no login."""
    previous_store = os.environ.get("SCREENY_TEXT_STORE")
    quotes = {
        "ACME": {"quoteType": "EQUITY", "exchange": "NMS", "marketCap": 2e9, "regularMarketPrice": 10, "currency": "USD", "longName": "Acme", "sym": "ACME"},
        "BOND": {"quoteType": "ETF", "exchange": "PCX", "marketCap": 1e9, "regularMarketPrice": 20, "currency": "USD", "longName": "Bond ETF", "sym": "BOND"},
        "BIG": {"quoteType": "EQUITY", "exchange": "NYQ", "marketCap": 20e9, "regularMarketPrice": 100, "currency": "USD", "longName": "Big Co", "sym": "BIG"},
        "LON": {"quoteType": "EQUITY", "exchange": "LSE", "marketCap": 1e9, "regularMarketPrice": 5, "currency": "GBP", "longName": "London Co", "sym": "LON"},
        "AAA": {"quoteType": "EQUITY", "exchange": "NMS", "marketCap": 1e9, "regularMarketPrice": 8, "currency": "USD", "longName": "Aaa", "sym": "AAA"},
    }
    with tempfile.TemporaryDirectory() as folder:
        os.environ["SCREENY_TEXT_STORE"] = os.path.join(folder, "text_store")
        list_path = os.path.join(folder, "list.csv")
        cand_path = os.path.join(folder, "candidates.csv")
        results_path = os.path.join(folder, "sa_results.json")
        triage_path = os.path.join(folder, "triage.json")
        breakdown_path = os.path.join(folder, "sa_breakdown.json")
        rows = [
            {"url": "https://seekingalpha.com/article/1-acme", "article_id": "1", "source": "SA Long Ideas", "author": "Author A", "date": "2026-10-10", "title": "Acme is mispriced", "ticker": "ACME", "date_text": "Fri, Oct 9"},
            {"url": "https://seekingalpha.com/article/2-week", "article_id": "2", "source": "SA Long Ideas", "author": "Author B", "date": "2026-10-11", "title": "Weekly roundup of ideas", "ticker": "ACME", "date_text": ""},
            {"url": "https://seekingalpha.com/article/3-bond", "article_id": "3", "source": "SA Long Ideas", "author": "Author C", "date": "2026-10-11", "title": "A bond fund", "ticker": "BOND", "date_text": ""},
            {"url": "https://seekingalpha.com/article/4-two", "article_id": "4", "source": "SA Long Ideas", "author": "Author D", "date": "2026-10-12", "title": "Two picks for the year", "ticker": "AAA;BBB", "date_text": ""},
            {"url": "https://seekingalpha.com/article/5-big", "article_id": "5", "source": "SA Long Ideas", "author": "Author E", "date": "2026-10-12", "title": "Large company", "ticker": "BIG", "date_text": ""},
            {"url": "https://seekingalpha.com/article/6-lon", "article_id": "6", "source": "SA Long Ideas", "author": "Author F", "date": "2026-10-12", "title": "London name", "ticker": "LON", "date_text": ""},
            {"url": "https://seekingalpha.com/article/7-none", "article_id": "7", "source": "SA Long Ideas", "author": "Author G", "date": "2026-10-12", "title": "No symbol here", "ticker": "", "date_text": ""},
            {"url": "https://seekingalpha.com/alpha-picks/8", "article_id": "", "source": "SA Long Ideas", "author": "user@example.com", "date": "2026-10-12", "title": "group post", "ticker": "ACME", "date_text": ""},
            {"url": "https://x.com/somehandle", "article_id": "", "source": "SA Long Ideas", "author": "nope", "date": "2026-10-12", "title": "not an article", "ticker": "ACME", "date_text": ""},
            {"url": "https://seekingalpha.com/article/1-acme", "article_id": "1", "source": "SA Long Ideas", "author": "Author A", "date": "2026-10-10", "title": "duplicate", "ticker": "ACME", "date_text": ""},
        ]
        write_csv(list_path, LIST_FIELDS, rows)
        kept, summary = screen(list_path, cand_path, results_path, "", "2026-10-16", quotes, price_at=None)
        assert [article_id(row["url"]) for row in kept] == ["1"], kept
        assert kept[0]["source"] == "Seeking Alpha"
        assert kept[0]["sa_status"] == "screened"
        assert "example.com" not in json.dumps(kept)
        assert summary["drops"]["recap / portfolio / housekeeping"] == 1
        assert summary["drops"]["ETF / fund / trust"] == 1
        assert summary["drops"]["multi-stock title"] == 1
        assert summary["drops"]["not small/mid cap (>=US$10B at publish)"] == 1
        assert summary["drops"]["not US/Canada listed"] == 1
        assert summary["drops"]["no ticker in metadata"] == 1
        body = " ".join(["word"] * 700)
        good = os.path.join(folder, "sa_1.txt")
        short = os.path.join(folder, "sa_12.txt")
        wrong = os.path.join(folder, "sa_13.txt")
        blocked = os.path.join(folder, "sa_14.txt")
        open(good, "w", encoding="utf-8").write(
            _fulltext("https://seekingalpha.com/article/1-acme", "Acme is mispriced", "Author A", "ACME", body, "I have a beneficial long position in the shares of ACME.")
        )
        open(short, "w", encoding="utf-8").write(
            _fulltext("https://seekingalpha.com/article/12", "Short", "Author A", "ACME", "too short", "beneficial long position in the shares of ACME")
        )
        open(wrong, "w", encoding="utf-8").write(
            _fulltext("https://seekingalpha.com/article/13", "Other", "Author A", "ACME", body, "No position is disclosed here.")
        )
        open(blocked, "w", encoding="utf-8").write("Press & Hold to continue\n")
        assert check(good, results_path, cand_path, quotes={}) == 0
        assert load_json(results_path, {})["1"]["status"] == "needs_score"
        assert check(short, results_path, quotes={}) == 0
        assert load_json(results_path, {})["12"]["status"] == "drop"
        assert check(wrong, results_path, quotes={}) == 0
        assert load_json(results_path, {})["13"]["reason"] == "author not long"
        assert check(blocked, results_path, quotes={}) == 3
        company_quotes = {
            "ESVIF": {"longName": "Ensign Energy Services Inc.", "quoteType": "EQUITY"},
            "ESI.TO": {"longName": "Ensign Energy Services Inc.", "quoteType": "EQUITY"},
            "NIO": {"longName": "NIO Inc.", "quoteType": "EQUITY"},
            "LI": {"longName": "Li Auto Inc.", "quoteType": "EQUITY"},
            "XPEV": {"longName": "XPeng Inc.", "quoteType": "EQUITY"},
            "DMLP": {"longName": "Dorchester Minerals, L.P.", "quoteType": "EQUITY"},
            "BSM": {"longName": "Black Stone Minerals, L.P.", "quoteType": "EQUITY"},
            "KRP": {"longName": "Kimbell Royalty Partners, LP", "quoteType": "EQUITY"},
            "TXO": {"longName": "TXO Partners, L.P.", "quoteType": "EQUITY"},
            "MFIC": {"longName": "MidCap Financial Investment Corporation", "quoteType": "EQUITY"},
            "MFICL": {"longName": "MidCap Financial Investment Corporation 8.00% Notes due 2028", "quoteType": "EQUITY"},
        }
        long_body = " ".join(["word"] * 700)

        def verdict(article, disclosed):
            sample = _fulltext(
                "https://seekingalpha.com/article/99",
                "A note",
                "Author A",
                article,
                long_body,
                f"I have a beneficial long position in the shares of {disclosed}.",
            )
            return classify_text(sample, article, company_quotes)[0]

        assert verdict("ESI.TO", "ESVIF") == "full"
        assert verdict("XPEV", "NIO and LI") == "not_long"
        assert verdict("TXO", "DMLP, BSM and KRP") == "not_long"
        assert verdict("MFIC", "MFICL") == "long_other_security"
        merge(cand_path, triage_path, results_path, breakdown_path)
        triage = load_json(triage_path, [])
        assert len(triage) == 1 and triage[0]["source"] == "Seeking Alpha" and triage[0]["ticker"] == "ACME", triage
        merge(cand_path, triage_path, results_path, breakdown_path)
        assert len(load_json(triage_path, [])) == 1
        assert load_json(breakdown_path, {})["kept"] == 1
        assert not os.path.exists(os.path.join(folder, "seen_posts.csv"))
        mix = os.path.join(folder, "mix.csv")
        mix_triage = os.path.join(folder, "mix_triage.json")
        mix_break = os.path.join(folder, "mix_break.json")
        mix_results = os.path.join(folder, "mix_results.json")
        write_csv(
            mix,
            CAND_FIELDS,
            [
                {"url": "https://seekingalpha.com/article/21", "source": "Seeking Alpha", "date": "2026-10-10", "title": "Full", "audience": "everyone", "wordcount": "800", "first_seen_run": "2026-10-16", "author": "A", "ticker": "FULL", "mcap_usd": "1", "exchange": "NMS", "sa_status": "full", "drop_reason": ""},
                {"url": "https://seekingalpha.com/article/22", "source": "Seeking Alpha", "date": "2026-10-11", "title": "Preview", "audience": "preview", "wordcount": "100", "first_seen_run": "2026-10-16", "author": "A", "ticker": "PREV", "mcap_usd": "", "exchange": "", "sa_status": "preview", "drop_reason": "preview"},
                {"url": "https://seekingalpha.com/article/23", "source": "Seeking Alpha", "date": "2026-10-12", "title": "Not long", "audience": "everyone", "wordcount": "800", "first_seen_run": "2026-10-16", "author": "A", "ticker": "NOLONG", "mcap_usd": "", "exchange": "", "sa_status": "not_long", "drop_reason": "author not long"},
                {"url": "https://seekingalpha.com/article/24", "source": "Seeking Alpha", "date": "2026-10-09", "title": "Still screened", "audience": "everyone", "wordcount": "", "first_seen_run": "2026-10-16", "author": "A", "ticker": "WAIT", "mcap_usd": "", "exchange": "", "sa_status": "screened", "drop_reason": ""},
                {"url": "https://seekingalpha.com/article/25", "source": "Seeking Alpha", "date": "2026-10-13", "title": "Blocked", "audience": "everyone", "wordcount": "", "first_seen_run": "2026-10-16", "author": "A", "ticker": "STOP", "mcap_usd": "", "exchange": "", "sa_status": "blocked", "drop_reason": "bot check"},
            ],
        )
        merge(mix, mix_triage, mix_results, mix_break)
        counted = load_json(mix_break, {})
        assert counted["read"] == 1, counted
        assert counted["previews"] == 1, counted
        assert counted["not_long"] == 1, counted
        assert counted["skipped_unread"] == 2, counted
        assert counted["passed"] == 1, counted
        assert [row["ticker"] for row in load_json(mix_triage, [])] == ["FULL"]
        order = write_read_order(read_csv(mix), {}, os.path.join(folder, "order.csv"))
        assert [row["ticker"] for row in order[:4]] == ["WAIT", "FULL", "PREV", "NOLONG"]
        assert order[-1]["ticker"] == "STOP"
        reuse_order = os.path.join(folder, "reuse_order.csv")
        write_csv(
            reuse_order,
            ["url", "article_id", "ticker", "date", "title"],
            [
                {"url": "https://seekingalpha.com/article/31", "article_id": "31", "ticker": "KEEP", "date": "2026-10-01", "title": "Stored"},
                {"url": "https://seekingalpha.com/article/32", "article_id": "32", "ticker": "BOT", "date": "2026-10-02", "title": "Bot"},
                {"url": "https://seekingalpha.com/article/33", "article_id": "33", "ticker": "MISS", "date": "2026-10-03", "title": "Missing"},
            ],
        )
        texts = os.path.join(folder, "fulltext")
        os.makedirs(texts)
        open(os.path.join(texts, "sa_31.txt"), "w", encoding="utf-8").write(" ".join(["stored"] * 40))
        open(os.path.join(texts, "sa_32.txt"), "w", encoding="utf-8").write("Press & Hold to confirm you are human")
        pending = resume(reuse_order, os.path.join(folder, "no_results.json"), texts)
        assert [item["ticker"] for item in pending] == ["BOT", "MISS"], pending
        text_store.publish("sa_33.txt", " ".join(["fromstore"] * 30))
        pending = resume(reuse_order, os.path.join(folder, "no_results.json"), texts)
        assert [item["ticker"] for item in pending] == ["BOT"], pending
        assert "fromstore" in open(os.path.join(texts, "sa_33.txt"), encoding="utf-8").read()

        class _Resp:
            def __init__(self, status, payload=None, text=""):
                self.status_code = status
                self._payload = payload or {}
                self.text = text

            def json(self):
                return self._payload

        class _Session:
            def get(self, url, **_kwargs):
                if "fc.yahoo.com" in url or "getcrumb" in url:
                    return _Resp(200, text="crumb")
                if "/v7/finance/quote" in url:
                    return _Resp(401, {"quoteResponse": {"result": []}})
                if url.rstrip("/").endswith("/ACME"):
                    return _Resp(200, {"chart": {"result": [{"meta": {"symbol": "ACME", "exchangeName": "NMS", "currency": "USD", "regularMarketPrice": 10}}]}})
                if url.rstrip("/").endswith("/ZZ.V"):
                    return _Resp(200, {"chart": {"result": [{"meta": {"symbol": "ZZ.V", "exchangeName": "VAN", "currency": "CAD", "regularMarketPrice": 2}}]}})
                return _Resp(404, {"chart": {"result": None}})

        cache_path = os.path.join(folder, "yq_cache.json")
        quoted = fetch_quotes(["ACME", "ZZ.TO"], session=_Session(), cache_path=cache_path)
        assert quoted["ACME"]["exchange"] == "NMS" and quoted["ACME"]["marketCap"] is None
        assert quoted["ACME"].get("missing") != 1
        assert quoted["ZZ.TO"]["sym"] == "ZZ.V"
        try:
            fetch_quotes(["NO1", "NO2", "NO3", "NO4"], session=_Session(), cache_path=os.path.join(folder, "empty.json"))
        except QuoteFetchError:
            pass
        else:
            raise AssertionError("a 401 with no chart data should stop instead of marking every ticker missing")
    if previous_store is None:
        os.environ.pop("SCREENY_TEXT_STORE", None)
    else:
        os.environ["SCREENY_TEXT_STORE"] = previous_store
    print("sa_ingest self-test ok")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen, check, and merge one Seeking Alpha Long Ideas pull")
    parser.add_argument("command", choices=["screen", "check", "merge", "resume", "self-test"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("triage", nargs="?")
    parser.add_argument("--out", default="")
    parser.add_argument("--results", default=os.path.join(STATE, "sa_results.json"))
    parser.add_argument("--breakdown", default=os.path.join(STATE, "sa_breakdown.json"))
    parser.add_argument("--quotes", default="", help="JSON map of Yahoo quotes. Omit to query Yahoo.")
    parser.add_argument("--since", default="")
    parser.add_argument("--today", default="")
    parser.add_argument("--candidates", default="")
    args = parser.parse_args(argv)
    today = args.today or dt.date.today().isoformat()
    if args.command == "self-test":
        return self_test()
    if args.command == "screen":
        if not args.path:
            parser.error("screen requires the list CSV path")
        out = args.out or os.path.join(REPORTS, f"sa_candidates_{today}.csv")
        supplied = load_json(args.quotes, None) if args.quotes else None
        rows = read_csv(args.path)
        quotes = _quotes_for(rows, supplied)

        def price_at(symbol, day):
            try:
                import px
                return px.ret(symbol, day)
            except Exception as exc:
                print(f"WARNING: publish-day price failed for {symbol}: {exc}")
                return None

        screen(args.path, out, args.results, args.since, today, quotes, price_at)
        return 0
    if args.command == "check":
        if not args.path:
            parser.error("check requires a fulltext file")
        return check(args.path, args.results, args.candidates)
    if args.command == "resume":
        if not args.path:
            parser.error("resume requires the read-order CSV")
        resume(args.path, args.results)
        return 0
    if not args.path or not args.triage:
        parser.error("merge requires the candidates CSV and the triage JSON")
    merge(args.path, args.triage, args.results, args.breakdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
