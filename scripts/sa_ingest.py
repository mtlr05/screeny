#!/usr/bin/env python3
"""Bookkeeping for one Seeking Alpha Long Ideas pull.

The signed-in browser does the reading. This script does not log in, does not
read cookies, and does not fetch Seeking Alpha. A bot with a browser:

1. Saves the Long Ideas list as CSV (list schema below).
2. python3 scripts/sa_ingest.py screen --list LIST.csv --out CANDIDATES.csv
3. Reads each candidate in the browser, slowly. Records word count and whether
   the page is a preview or a bot check. Does not save the login.
4. python3 scripts/sa_ingest.py check --obs OBS.json
5. python3 scripts/sa_ingest.py merge --candidates CANDIDATES.csv --triage TRIAGE.json

List CSV columns: id, url, title, author, date, ticker, exchange, market_cap, summary.
Candidates CSV extends state/seen_posts.csv:
url, source, date, title, audience, wordcount, first_seen_run,
sa_id, ticker, author, screen, reason.
state/sa_results.json dedupes article ids. state/sa_breakdown.json is what the report reads.
Seeking Alpha stays one pull. It is not a row in the tracked source list.
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
from _paths import REPORTS, SEEN, STATE, ensure

LIST_FIELDS = ["id", "url", "title", "author", "date", "ticker", "exchange", "market_cap", "summary"]
SEEN_FIELDS = ["url", "source", "date", "title", "audience", "wordcount", "first_seen_run"]
CAND_FIELDS = SEEN_FIELDS + ["sa_id", "ticker", "author", "screen", "reason"]
MIN_WORDS = 600
CAP_USD = 10_000_000_000
US_CA = {
    "",
    "NYSE",
    "NASDAQ",
    "NASDAQGS",
    "NASDAQGM",
    "NASDAQCM",
    "AMEX",
    "NYSEAMERICAN",
    "NYSEAM",
    "OTC",
    "OTCQX",
    "OTCQB",
    "PINK",
    "TSX",
    "TSXV",
    "TSX-V",
    "TSX.V",
    "CVE",
    "CSE",
    "NEO",
    "TOR",
    "VAN",
}
CA_SUFFIX = (".TO", ".V", ".CN", ".NE")
FOREIGN_SUFFIX = (".L", ".HK", ".AX", ".T", ".PA", ".DE", ".SW", ".KS", ".TW", ".SS", ".SZ", ".SI", ".KL")
GROUPS = re.compile(r"sifting the world|concentrated value|alpha picks|investing group", re.I)
ETF = re.compile(r"\betfs?\b|exchange[- ]traded", re.I)
RECAP = re.compile(
    r"portfolio update|monthly|weekly|roundup|recap|letter|macro|podcast|links|reading list|week in|digest|market update|watchlist|thread|interview|chart",
    re.I,
)
HOLD = re.compile(r"\bhold\b|neutral|market perform", re.I)
PAYWALL = re.compile(r"subscribe to read|continue reading|paywall|premium content|for subscribers", re.I)
BOT = re.compile(r"press\s*&\s*hold|bot check|captcha", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
XURL = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/\S+", re.I)
HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,}")


def scrub(text):
    text = EMAIL.sub("", text or "")
    text = XURL.sub("", text)
    text = HANDLE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def article_id(value):
    match = re.search(r"/article/(\d+)", value or "") or re.search(r"^(\d+)$", str(value or "").strip())
    return match.group(1) if match else ""


def _cap_usd(raw):
    text = (raw or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    mult = 1
    if text[-1:].upper() == "B":
        mult = 1_000_000_000
        text = text[:-1]
    elif text[-1:].upper() == "M":
        mult = 1_000_000
        text = text[:-1]
    try:
        return float(text) * mult
    except ValueError:
        return None


def _roots(ticker):
    parts = re.split(r"\s*(?:,|;|/|\band\b)\s*", ticker or "", flags=re.I)
    roots = []
    for part in parts:
        token = part.strip().upper().lstrip("$")
        if not token:
            continue
        token = re.sub(r"\(.*?\)", "", token).strip()
        root = token.split(".")[0].split(":")[-1].strip()
        if root and root not in roots:
            roots.append(root)
    return roots


def screen_row(row):
    """Cheap list screen. Returns (keep, reason). No network."""
    title = row.get("title") or ""
    author = row.get("author") or ""
    summary = row.get("summary") or ""
    blob = f"{title} {author} {summary}"
    url = (row.get("url") or "").lower()
    if "x.com/" in url or "twitter.com/" in url:
        return False, "not a Seeking Alpha article"
    if not article_id(row.get("id") or row.get("url") or ""):
        return False, "not a Seeking Alpha article"
    if GROUPS.search(blob):
        return False, "investing group"
    exchange = re.sub(r"[^A-Z]", "", (row.get("exchange") or "").upper())
    ticker = (row.get("ticker") or "").upper()
    if exchange and exchange not in US_CA:
        return False, "not US/Canada listed"
    if any(ticker.endswith(suffix) for suffix in FOREIGN_SUFFIX):
        return False, "not US/Canada listed"
    cap = _cap_usd(row.get("market_cap") or "")
    if cap is not None and cap > CAP_USD:
        return False, "market cap above about US$10B"
    if ETF.search(blob):
        return False, "ETF or fund"
    if RECAP.search(title):
        return False, "recap, macro, or list"
    if HOLD.search(title):
        return False, "hold"
    roots = _roots(row.get("ticker") or "")
    if len(roots) > 1 and not re.search(r"\bor\b", title, re.I):
        return False, "more than one company"
    if not roots and not re.search(r"\$[A-Z]{1,5}\b", title):
        return False, "no ticker"
    return True, ""


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


def results_doc(path):
    doc = load_json(path, {})
    doc.setdefault("screen", {})
    doc.setdefault("articles", {})
    return doc


def classify(obs):
    """One browser observation. Returns status full, preview, or bot_check."""
    ending = obs.get("ending") or ""
    text = obs.get("text") or ""
    if obs.get("bot_check") in (True, "true", "1", "yes") or BOT.search(ending) or BOT.search(text[:500]):
        return "bot_check"
    try:
        words = int(float(obs.get("words") or 0))
    except (TypeError, ValueError):
        words = 0
    tail = (ending or text[-800:]).strip()
    if words < MIN_WORDS or PAYWALL.search(tail):
        return "preview"
    return "full"


def screen(list_path, out_path, results_path, since, today):
    rows = read_csv(list_path)
    dates = []
    drops = {}
    kept = []
    seen_ids = set()
    for raw in rows:
        row = {key: scrub(raw.get(key) or "") for key in LIST_FIELDS}
        row["id"] = article_id(raw.get("id") or raw.get("url") or "") or scrub(raw.get("id") or "")
        row["url"] = (raw.get("url") or "").strip()
        if row["id"] in seen_ids:
            drops["duplicate"] = drops.get("duplicate", 0) + 1
            continue
        if row["id"]:
            seen_ids.add(row["id"])
        day = (row.get("date") or "")[:10]
        if since and day and day < since:
            drops["before window"] = drops.get("before window", 0) + 1
            continue
        if day:
            dates.append(day)
        keep, reason = screen_row(row)
        if not keep:
            drops[reason] = drops.get(reason, 0) + 1
            continue
        kept.append(
            {
                "url": row["url"] or f"https://seekingalpha.com/article/{row['id']}",
                "source": row.get("author") or "Seeking Alpha",
                "date": day,
                "title": row.get("title") or "",
                "audience": "everyone",
                "wordcount": "",
                "first_seen_run": today,
                "sa_id": row["id"],
                "ticker": row.get("ticker") or "",
                "author": row.get("author") or "",
                "screen": "pass",
                "reason": "",
            }
        )
    write_csv(out_path, CAND_FIELDS, kept)
    doc = results_doc(results_path)
    doc["screen"] = {
        "li": len(rows),
        "li_from": min(dates) if dates else "",
        "li_to": max(dates) if dates else "",
        "kept": len(kept),
        "drops": drops,
    }
    save_json(results_path, doc)
    print(f"Long Ideas rows: {len(rows)}. Kept: {len(kept)}. Drops: {sum(drops.values())}.")
    for reason, count in sorted(drops.items()):
        print(f"  {reason}: {count}")
    print(out_path)
    return kept


def check(obs_path, results_path, today):
    payload = load_json(obs_path, {})
    items = payload.get("articles") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and "id" in payload and not items:
        items = [payload]
    doc = results_doc(results_path)
    stopped = False
    for obs in items or []:
        status = classify(obs)
        aid = article_id(str(obs.get("id") or obs.get("url") or "")) or scrub(str(obs.get("id") or ""))
        if not aid:
            continue
        doc["articles"][aid] = {
            "url": (obs.get("url") or "").strip(),
            "status": status,
            "words": obs.get("words") or "",
            "checked": today,
            "merged": bool((doc["articles"].get(aid) or {}).get("merged")),
        }
        print(f"{aid} {status}")
        if status == "bot_check":
            stopped = True
            print("STOP: bot check. Score only what was already read in full. Do not continue the pull.")
            break
    save_json(results_path, doc)
    return 3 if stopped else 0


def merge(candidates_path, triage_path, results_path, seen_path, breakdown_path, today):
    candidates = read_csv(candidates_path)
    doc = results_doc(results_path)
    triage = load_json(triage_path, [])
    if not isinstance(triage, list):
        triage = []
    seen_rows = read_csv(seen_path)
    seen_urls = {(row.get("url") or "").rstrip("/") for row in seen_rows}
    triage_urls = {(row.get("url") or "").rstrip("/") for row in triage}
    added = 0
    previews = 0
    unread = 0
    for row in candidates:
        if (row.get("screen") or "") != "pass":
            continue
        aid = row.get("sa_id") or article_id(row.get("url") or "")
        record = doc["articles"].get(aid) or {}
        status = record.get("status") or ""
        if status == "preview":
            previews += 1
            continue
        if status != "full":
            unread += 1
            continue
        url = (row.get("url") or record.get("url") or "").rstrip("/")
        if not url or url in seen_urls or record.get("merged"):
            continue
        if url not in triage_urls:
            triage.append(
                {
                    "url": url,
                    "title": row.get("title") or "",
                    "date": (row.get("date") or "")[:10],
                    "source": scrub(row.get("author") or row.get("source") or ""),
                    "wc": record.get("words") or row.get("wordcount") or "",
                    "audience": "everyone",
                    "type": "seekingalpha",
                    "sa_id": aid,
                }
            )
            triage_urls.add(url)
        seen_rows.append(
            {
                "url": url,
                "source": scrub(row.get("author") or row.get("source") or "Seeking Alpha"),
                "date": (row.get("date") or "")[:10],
                "title": scrub(row.get("title") or ""),
                "audience": "everyone",
                "wordcount": str(record.get("words") or ""),
                "first_seen_run": today,
            }
        )
        seen_urls.add(url)
        record["merged"] = True
        record["url"] = url
        doc["articles"][aid] = record
        added += 1
    screen_info = doc.get("screen") or {}
    prior = load_json(breakdown_path, {})
    full = sum(1 for item in doc["articles"].values() if item.get("status") == "full")
    passed = sum(1 for item in doc["articles"].values() if item.get("status") == "full" and item.get("merged"))
    breakdown = {
        "li": screen_info.get("li", 0),
        "li_from": screen_info.get("li_from", ""),
        "li_to": screen_info.get("li_to", ""),
        "kept": screen_info.get("kept", 0),
        "read": full,
        "previews": previews + sum(1 for item in doc["articles"].values() if item.get("status") == "preview"),
        "skipped_unread": unread,
        "passed": passed,
        "scored": prior.get("scored", 0),
    }
    save_json(triage_path, triage)
    write_csv(seen_path, SEEN_FIELDS, seen_rows)
    save_json(results_path, doc)
    save_json(breakdown_path, breakdown)
    print(f"Merged {added} full Seeking Alpha articles into {triage_path}.")
    print(f"Previews not scored: {breakdown['previews']}. Not yet read: {unread}.")
    return added


def self_test():
    """Offline fake rows. No network and no login."""
    with tempfile.TemporaryDirectory() as folder:
        list_path = os.path.join(folder, "list.csv")
        cand_path = os.path.join(folder, "candidates.csv")
        results_path = os.path.join(folder, "sa_results.json")
        obs_path = os.path.join(folder, "obs.json")
        triage_path = os.path.join(folder, "triage.json")
        seen_path = os.path.join(folder, "seen.csv")
        breakdown_path = os.path.join(folder, "sa_breakdown.json")
        write_csv(seen_path, SEEN_FIELDS, [])
        rows = [
            {"id": "1", "url": "https://seekingalpha.com/article/1", "title": "Acme: why the market is wrong", "author": "Author A", "date": "2026-10-10", "ticker": "ACME", "exchange": "NASDAQ", "market_cap": "2B", "summary": "one company"},
            {"id": "2", "url": "https://seekingalpha.com/article/2", "title": "Weekly roundup of ideas", "author": "Author B", "date": "2026-10-11", "ticker": "BBB", "exchange": "NYSE", "market_cap": "1B", "summary": ""},
            {"id": "3", "url": "https://seekingalpha.com/article/3", "title": "A bond ETF to hold", "author": "Author C", "date": "2026-10-11", "ticker": "BOND", "exchange": "NYSE", "market_cap": "", "summary": ""},
            {"id": "4", "url": "https://seekingalpha.com/article/4", "title": "Two picks: AAA and BBB", "author": "Author D", "date": "2026-10-12", "ticker": "AAA, BBB", "exchange": "NYSE", "market_cap": "", "summary": ""},
            {"id": "5", "url": "https://seekingalpha.com/article/5", "title": "Large cap blue chip", "author": "Author E", "date": "2026-10-12", "ticker": "BIG", "exchange": "NYSE", "market_cap": "20B", "summary": ""},
            {"id": "6", "url": "https://seekingalpha.com/article/6", "title": "London listing", "author": "Author F", "date": "2026-10-12", "ticker": "LON.L", "exchange": "LSE", "market_cap": "1B", "summary": ""},
            {"id": "7", "url": "https://seekingalpha.com/article/7", "title": "Group pick", "author": "Alpha Picks", "date": "2026-10-12", "ticker": "GRP", "exchange": "NYSE", "market_cap": "1B", "summary": ""},
            {"id": "8", "url": "https://x.com/somehandle", "title": "not an article", "author": "nope", "date": "2026-10-12", "ticker": "NO", "exchange": "", "market_cap": "", "summary": "user@example.com"},
            {"id": "1", "url": "https://seekingalpha.com/article/1", "title": "duplicate", "author": "Author A", "date": "2026-10-10", "ticker": "ACME", "exchange": "NASDAQ", "market_cap": "2B", "summary": ""},
        ]
        write_csv(list_path, LIST_FIELDS, rows)
        screen(list_path, cand_path, results_path, "2026-10-01", "2026-10-16")
        kept = read_csv(cand_path)
        assert [row["sa_id"] for row in kept] == ["1"], kept
        assert "example.com" not in json.dumps(kept)
        assert "x.com" not in json.dumps(kept)
        save_json(
            obs_path,
            {
                "articles": [
                    {"id": "1", "url": "https://seekingalpha.com/article/1", "words": 900, "ending": "The shares are a buy."},
                    {"id": "9", "url": "https://seekingalpha.com/article/9", "words": 120, "ending": "Subscribe to read the rest."},
                    {"id": "10", "url": "https://seekingalpha.com/article/10", "words": 50, "ending": "Press & Hold to continue", "bot_check": True},
                    {"id": "11", "url": "https://seekingalpha.com/article/11", "words": 2000, "ending": "should not be recorded"},
                ]
            },
        )
        code = check(obs_path, results_path, "2026-10-16")
        assert code == 3
        recorded = results_doc(results_path)["articles"]
        assert recorded["1"]["status"] == "full"
        assert recorded["9"]["status"] == "preview"
        assert recorded["10"]["status"] == "bot_check"
        assert "11" not in recorded
        merge(cand_path, triage_path, results_path, seen_path, breakdown_path, "2026-10-16")
        triage = load_json(triage_path, [])
        assert len(triage) == 1 and triage[0]["sa_id"] == "1", triage
        merge(cand_path, triage_path, results_path, seen_path, breakdown_path, "2026-10-16")
        assert len(load_json(triage_path, [])) == 1
        breakdown = load_json(breakdown_path, {})
        assert breakdown["li"] == 9
        assert breakdown["kept"] == 1
        assert breakdown["read"] == 1
        assert breakdown["passed"] == 1
        assert classify({"words": 100, "ending": "summary only"}) == "preview"
        assert classify({"words": 800, "ending": "end of the article"}) == "full"
    print("sa_ingest self-test ok")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen, check, and merge one Seeking Alpha Long Ideas pull")
    parser.add_argument("command", choices=["screen", "check", "merge", "self-test"])
    parser.add_argument("--list", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--obs", default="")
    parser.add_argument("--candidates", default="")
    parser.add_argument("--triage", default="")
    parser.add_argument("--results", default=os.path.join(STATE, "sa_results.json"))
    parser.add_argument("--seen", default=SEEN)
    parser.add_argument("--breakdown", default=os.path.join(STATE, "sa_breakdown.json"))
    parser.add_argument("--since", default="")
    parser.add_argument("--today", default="")
    args = parser.parse_args(argv)
    today = args.today or dt.date.today().isoformat()
    if args.command == "self-test":
        return self_test()
    if args.command == "screen":
        if not args.list:
            parser.error("screen requires --list")
        out = args.out or os.path.join(REPORTS, f"sa_candidates_{today}.csv")
        screen(args.list, out, args.results, args.since, today)
        return 0
    if args.command == "check":
        if not args.obs:
            parser.error("check requires --obs")
        return check(args.obs, args.results, today)
    if not args.candidates or not args.triage:
        parser.error("merge requires --candidates and --triage")
    merge(args.candidates, args.triage, args.results, args.seen, args.breakdown, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
