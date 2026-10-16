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
from _paths import REPORTS, STATE, ensure

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


def ticker_named(disclosure, ticker, tickers_line):
    wanted = (ticker or "").upper()
    if not wanted:
        match = re.search(r"\(([A-Z]{1,6})\)", tickers_line or "")
        wanted = match.group(1) if match else ""
    if not wanted:
        return False
    return bool(re.search(rf"\b{re.escape(wanted)}\b", disclosure or "", re.I))


def classify_text(text, ticker=""):
    """full, preview, not_long, or blocked. A bot-check page is blocked."""
    if BOT.search(text or ""):
        return "blocked", "bot check"
    parsed = parse_fulltext(text or "")
    words = len((parsed["body"] or "").split())
    if words < MIN_WORDS or PAYWALL.search(text or "") or not parsed["disclosure"]:
        return "preview", "preview or missing analyst disclosure"
    if not LONG.search(parsed["disclosure"]) or not ticker_named(parsed["disclosure"], ticker, parsed["tickers"]):
        return "not_long", "author not long"
    return "full", ""


def check(path, results_path, candidates_path=""):
    text = open(path, encoding="utf-8").read()
    parsed = parse_fulltext(text)
    aid = article_id(parsed["url"] or os.path.basename(path))
    doc = load_json(results_path, {})
    existing = doc.get(aid) or {}
    if existing.get("status") == "scored":
        print(f"{aid} already scored")
        return 0
    status, reason = classify_text(text, existing.get("ticker") or "")
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
                row["sa_status"] = {"full": "full", "preview": "preview", "not_long": "not_long", "blocked": "blocked"}[status]
                row["drop_reason"] = reason
        write_csv(candidates_path, CAND_FIELDS, rows)
    print(f"{aid} {status}")
    if status == "blocked":
        print("Bot check. Pause and read this article once more. If it fails again, stop and score only what was already read in full.")
        return 3
    return 0


def merge(candidates_path, triage_path, results_path, breakdown_path):
    candidates = read_csv(candidates_path)
    doc = load_json(results_path, {})
    screen_summary = load_json(results_path + ".screen.json", {})
    triage = load_json(triage_path, [])
    if not isinstance(triage, list):
        triage = []
    triage_urls = {(row.get("url") or "").rstrip("/") for row in triage}
    added = 0
    previews = 0
    not_long = 0
    unread = 0
    for row in candidates:
        if row.get("drop_reason") and row.get("sa_status") != "full":
            continue
        aid = article_id(row.get("url") or "")
        record = doc.get(aid) or {}
        if record.get("status") == "drop" and record.get("reason") == "author not long":
            not_long += 1
            continue
        if record.get("status") == "drop" and "preview" in (record.get("reason") or ""):
            previews += 1
            continue
        if record.get("status") != "needs_score" or not record.get("words"):
            unread += 1
            continue
        url = (row.get("url") or record.get("url") or "").rstrip("/")
        if not url or url in triage_urls or record.get("in_triage"):
            continue
        triage.append(
            {
                "sub": "seekingalpha",
                "url": url,
                "title": row.get("title") or record.get("title") or "",
                "subtitle": "",
                "date": (row.get("date") or record.get("date") or "")[:10],
                "audience": "everyone",
                "wc": record.get("words") or "",
                "source": "Seeking Alpha",
                "ticker": row.get("ticker") or record.get("ticker") or "",
                "author": scrub(row.get("author") or record.get("author") or ""),
            }
        )
        triage_urls.add(url)
        record["in_triage"] = True
        doc[aid] = record
        added += 1
    prior = load_json(breakdown_path, {})
    full = sum(1 for item in doc.values() if isinstance(item, dict) and item.get("status") == "needs_score" and item.get("words"))
    breakdown = {
        "li": screen_summary.get("li", 0),
        "li_from": screen_summary.get("li_from", ""),
        "li_to": screen_summary.get("li_to", ""),
        "kept": screen_summary.get("kept", 0),
        "read": full,
        "previews": previews,
        "skipped_unread": unread,
        "passed": sum(1 for item in doc.values() if isinstance(item, dict) and item.get("in_triage")),
        "scored": prior.get("scored", 0),
    }
    save_json(triage_path, triage)
    save_json(results_path, doc)
    save_json(breakdown_path, breakdown)
    print(f"Merged {added} Seeking Alpha articles into {triage_path}.")
    print(f"Previews: {previews}. Author not long: {not_long}. Not yet read: {unread}.")
    return added


def fetch_quotes(symbols):
    """Public Yahoo quote for exchange, type, and market cap. No Seeking Alpha login."""
    import requests

    from _paths import user_agent

    out = {}
    symbols = [symbol for symbol in symbols if symbol]
    if not symbols:
        return out
    try:
        response = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": ",".join(symbols)},
            headers={"User-Agent": user_agent()},
            timeout=30,
        )
        result = ((response.json().get("quoteResponse") or {}).get("result")) or []
    except Exception:
        result = []
    got = {item.get("symbol"): item for item in result}
    for symbol in symbols:
        quote = got.get(symbol)
        if not quote:
            out[symbol] = {"missing": 1}
            continue
        out[symbol] = {
            "quoteType": quote.get("quoteType"),
            "exchange": quote.get("exchange"),
            "marketCap": quote.get("marketCap"),
            "regularMarketPrice": quote.get("regularMarketPrice"),
            "currency": quote.get("currency"),
            "longName": quote.get("longName"),
            "shortName": quote.get("shortName"),
            "sym": quote.get("symbol"),
        }
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
    quotes = {
        "ACME": {"quoteType": "EQUITY", "exchange": "NMS", "marketCap": 2e9, "regularMarketPrice": 10, "currency": "USD", "longName": "Acme", "sym": "ACME"},
        "BOND": {"quoteType": "ETF", "exchange": "PCX", "marketCap": 1e9, "regularMarketPrice": 20, "currency": "USD", "longName": "Bond ETF", "sym": "BOND"},
        "BIG": {"quoteType": "EQUITY", "exchange": "NYQ", "marketCap": 20e9, "regularMarketPrice": 100, "currency": "USD", "longName": "Big Co", "sym": "BIG"},
        "LON": {"quoteType": "EQUITY", "exchange": "LSE", "marketCap": 1e9, "regularMarketPrice": 5, "currency": "GBP", "longName": "London Co", "sym": "LON"},
        "AAA": {"quoteType": "EQUITY", "exchange": "NMS", "marketCap": 1e9, "regularMarketPrice": 8, "currency": "USD", "longName": "Aaa", "sym": "AAA"},
    }
    with tempfile.TemporaryDirectory() as folder:
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
        assert check(good, results_path, cand_path) == 0
        assert load_json(results_path, {})["1"]["status"] == "needs_score"
        assert check(short, results_path) == 0
        assert load_json(results_path, {})["12"]["status"] == "drop"
        assert check(wrong, results_path) == 0
        assert load_json(results_path, {})["13"]["reason"] == "author not long"
        assert check(blocked, results_path) == 3
        merge(cand_path, triage_path, results_path, breakdown_path)
        triage = load_json(triage_path, [])
        assert len(triage) == 1 and triage[0]["source"] == "Seeking Alpha" and triage[0]["ticker"] == "ACME", triage
        merge(cand_path, triage_path, results_path, breakdown_path)
        assert len(load_json(triage_path, [])) == 1
        assert load_json(breakdown_path, {})["kept"] == 1
        assert not os.path.exists(os.path.join(folder, "seen_posts.csv"))
    print("sa_ingest self-test ok")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen, check, and merge one Seeking Alpha Long Ideas pull")
    parser.add_argument("command", choices=["screen", "check", "merge", "self-test"])
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
        screen(args.path, out, args.results, args.since, today, quotes)
        return 0
    if args.command == "check":
        if not args.path:
            parser.error("check requires a fulltext file")
        return check(args.path, args.results, args.candidates)
    if not args.path or not args.triage:
        parser.error("merge requires the candidates CSV and the triage JSON")
    merge(args.path, args.triage, args.results, args.breakdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
