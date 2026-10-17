"""Weekly sweep: pull active Substack archives, dedupe against seen_posts.csv, write a triage file.

Default window is the last 7 days. Paths are repo-relative (config/, state/, reports/).

A free post is dropped on the title only when it is a recap, a macro phrase
(not the bare word), or a list, matched on whole words. A title that names one
ticker or one exchange is not title-dropped; the body screen decides. Every
other free post is fetched (first 1500 words) and dropped only when that text
is clearly not a single-stock pitch, or the author is short, selling, or on
hold. Unclear posts stay candidates. Every in-window post is recorded in
reports/substack_screen_<date>.csv.
"""
import argparse
import collections
import csv
import datetime as dt
import html as html_lib
import json
import os
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse

import requests
import concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bat"))
from _paths import CACHE, FULLTEXT, REPORTS, ROOT, SEEN, SOURCES, ensure, user_agent
from longcheck import exclude_reason

# Whole words only, so "chart" does not match Charter and "letter" does not match newsletter.
# "macro" alone is not a drop: a pitch can be "our best macro idea".
NEG = re.compile(
    r"\b(?:portfolio update|monthly|weekly|roundup|recap|letter|podcast|links|reading list|week in|digest|market update|watchlist|thread|interview|chart"
    r"|macro\s+(?:update|outlook|view|notes?|letter|weekly|monthly|recap|roundup|thoughts))\b",
    re.I,
)
# One $TICKER, exchange-qualified symbol (AXL.V), or exchange tag. Two names stay a title drop.
_LISTING = re.compile(
    r"\$([A-Za-z]{1,6}(?:\.[A-Za-z]{1,3})?)"
    r"|\((?:NYSE|NASDAQ|Nasdaq|AMEX|TSX|TSXV|TSX-V|CSE|OTCQX|OTCQB|OTC)\s*:\s*([A-Za-z][A-Za-z0-9.]{0,8})\)"
    r"|\b(?:NYSE|NASDAQ|Nasdaq|AMEX|TSX|TSXV|TSX-V|CSE|OTC)\s*:\s*([A-Za-z][A-Za-z0-9.]{0,8})\b"
    r"|\b([A-Za-z]{2,6}\.(?:V|TO|CN|NE))\b",
    re.I,
)
_BARE_EXCHANGE = re.compile(r"\b(NYSE|NASDAQ|TSX|TSXV|TSX-V|AMEX)\b", re.I)
BOOK = re.compile(
    r"\bbook review\b|\breview of (?:the |this )?(?:book|memoir)\b|\bi (?:just |recently )?finished (?:reading )?(?:the |this )?book\b",
    re.I,
)
MULTI = re.compile(
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|several|multiple)\s+(?:stocks?|names|ideas|picks|companies|positions)\b"
    r"|\bstocks?\s+(?:to buy|worth buying|i(?:'m| am)\s+buying)\b"
    r"|\b(?:my|our)\s+(?:top\s+)?(?:picks|ideas)\s+(?:this|for)\b"
    r"|\bhere are\s+(?:my\s+|our\s+)?(?:\d+\s+)?(?:stocks|ideas|picks|names)\b",
    re.I,
)
EXCHANGE_TAG = re.compile(
    r"\((?:NYSE|NASDAQ|Nasdaq|AMEX|TSX|TSXV|TSX-V|CSE|OTCQX|OTCQB|OTC)\s*:\s*[A-Z][A-Z0-9.]{0,7}\)",
    re.I,
)
MACRO = re.compile(
    r"\b(?:macro(?:economic)? outlook|market outlook|the economy|federal reserve|the fed|interest rates)\b",
    re.I,
)
POSSESSIVE_STOP = {"fed", "market", "week", "today", "world", "year", "investor", "reader"}
NO_COMPANY = re.compile(
    r"\b(?:not about (?:a |any )?(?:single )?(?:stock|company|listed company)|no identifiable listed company|general essay|not a stock pitch)\b",
    re.I,
)
TICKER = re.compile(
    r"\$[A-Z]{1,5}\b|\((?:NYSE|NASDAQ|Nasdaq|AMEX|TSX|TSXV|TSX-V|CSE|OTCQX|OTCQB|OTC)\s*:\s*[A-Z][A-Z0-9.]{0,7}\)",
)
COMPANY_TITLE = re.compile(
    r"^(?:[A-Z0-9][\w'’.&-]*(?:\s+[A-Z0-9][\w'’.&-]*){0,6})\s*[:\-\u2013\u2014]",
)
COMPANY_WORD = re.compile(
    r"\b(?:Inc|Corp|Corporation|Ltd|Limited|plc|AB|ASA|Group|Software|Holdings|Bancorp|Company)\b",
)
POSSESSIVE_NAME = re.compile(r"\b[A-Z][\w.-]*(?:'s|’s)\b")
SCREEN_FIELDS = ("url", "title", "decision", "reason")
BODY_WORDS = 1500
BOT_PAGE = re.compile(r"press\s*&\s*hold|bot check|captcha", re.I)


def posts_in_window(res):
    """Every post the sweep returned, one row per URL. Failed feeds contribute nothing."""
    seen = set()
    out = []
    for _url, posts in res or []:
        if not posts:
            continue
        for post in posts:
            url = post.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(post)
    return out


def title_blob(post):
    return ((post.get("title") or "") + " " + (post.get("subtitle") or "")).strip()


def _listing_bases(text):
    bases = []
    for match in _LISTING.finditer(text or ""):
        raw = next(group for group in match.groups() if group)
        base = re.sub(r"\.(?:V|TO|CN|NE)$", "", raw.upper())
        if base and base not in bases:
            bases.append(base)
    return bases


def single_listing_title(text):
    """True when the title names one ticker or one exchange. The body screen decides."""
    bases = _listing_bases(text)
    if len(bases) == 1:
        return True
    if bases:
        return False
    exchanges = {match.group(1).upper() for match in _BARE_EXCHANGE.finditer(text or "")}
    return len(exchanges) == 1


def title_drop_reason(post):
    """Paywall, or a recap/macro/list title. A missing pitch keyword is not a drop."""
    # A swept post always has audience. Only "everyone" is free. A backlog row
    # with no audience key is not treated as paywalled.
    if "audience" in post and post.get("audience") != "everyone":
        return "paywalled"
    blob = title_blob(post)
    if single_listing_title(blob):
        return ""
    if NEG.search(blob):
        return "not a single-stock pitch (recap/macro/list)"
    return ""


def drop_counts(posts):
    """Title-stage drops only. Report stats use dropped_from_screen on the CSV."""
    dropped = collections.Counter()
    for post in posts:
        reason = title_drop_reason(post)
        if reason:
            dropped[reason] += 1
    return dropped


def company_signal(title, text):
    blob = f"{title or ''}\n{text or ''}"
    if TICKER.search(blob):
        return True
    title = title or ""
    if COMPANY_TITLE.search(title.strip()):
        return True
    if COMPANY_WORD.search(title):
        return True
    for match in POSSESSIVE_NAME.finditer(title):
        name = re.split(r"['’]", match.group(0))[0]
        if name.lower() not in POSSESSIVE_STOP:
            return True
    return False


def content_drop_reason(title, text):
    """Drop only a clear non-pitch or a short/sell/hold. Empty string means keep."""
    text = text or ""
    stance, _hit = exclude_reason(title, text)
    if stance in ("short", "sell", "hold"):
        return f"author {stance}"
    head = " ".join(text.split()[:400])
    lead = f"{title or ''}\n{head}"
    if BOOK.search(lead):
        return "not a single-stock pitch (book review)"
    tags = {match.group(0).upper() for match in EXCHANGE_TAG.finditer(head)}
    if MULTI.search(lead) or len(tags) >= 4:
        return "not a single-stock pitch (multi-stock list)"
    if company_signal(title, text):
        return ""
    if not head.strip():
        return ""
    if NO_COMPANY.search(lead):
        return "not a single-stock pitch (no identifiable listed company)"
    if MACRO.search(lead) and len(text.split()) >= 40:
        return "not a single-stock pitch (macro/general essay)"
    if re.search(r"\b(?:this essay|investing philosophy|how i invest)\b", lead, re.I) and len(text.split()) >= 40:
        return "not a single-stock pitch (general essay)"
    return ""


def html_to_text(body):
    text = re.sub(r"<(br|/p|/h\d|/li)[^>]*>", "\n", body or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def first_words(text, n=BODY_WORDS):
    return " ".join((text or "").split()[:n])


def text_usable(text):
    """A stored body can be reused. Empty text and a bot-check page cannot."""
    if BOT_PAGE.search(text or ""):
        return False
    return len((text or "").split()) >= 20


def post_slug(post):
    match = re.search(r"/p/([^/?#]+)", urlparse(post.get("url") or "").path)
    return unquote(match.group(1)) if match else ""


def body_store_path(post, store_dir):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", post_slug(post))[:80]
    if not slug:
        return ""
    return os.path.join(store_dir, slug + ".txt")


def stored_body_paths(post, store_dir=None):
    paths = []
    if store_dir:
        path = body_store_path(post, store_dir)
        if path:
            paths.append(path)
        return paths
    slug = post_slug(post)
    if not slug:
        return paths
    paths.append(os.path.join(FULLTEXT, slug[:60] + ".txt"))
    paths.append(body_store_path(post, os.path.join(CACHE, "screen_bodies")))
    return paths


def load_stored_body(post, store_dir=None):
    for path in stored_body_paths(post, store_dir):
        if not path or not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if text_usable(text):
            return first_words(text)
    return ""


def save_stored_body(post, text, store_dir=None):
    directory = store_dir or os.path.join(CACHE, "screen_bodies")
    path = body_store_path(post, directory)
    if not path or not text_usable(text):
        return
    ensure(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def post_api(post):
    url = post.get("url") or ""
    parts = urlparse(url)
    match = re.search(r"/p/([^/?#]+)", parts.path)
    if not match:
        return ""
    slug = unquote(match.group(1))
    host = ""
    sub = post.get("sub") or ""
    if sub:
        host = urlparse(sub).netloc
    host = host or parts.netloc
    if not host or not slug:
        return ""
    return f"https://{host}/api/v1/posts/{slug}"


def fetch_body(post, headers, getter=None, store_dir=None):
    """Plain text of the post, first 1500 words. Reuse a usable stored file."""
    stored = load_stored_body(post, store_dir)
    if stored:
        return stored
    api = post_api(post)
    if not api:
        return ""
    getter = getter or requests.get
    try:
        resp = getter(api, headers=headers, timeout=20)
        payload = resp.json() if hasattr(resp, "json") else resp
        if not isinstance(payload, dict):
            return ""
        raw = payload.get("body_html") or payload.get("truncated_body_text") or ""
        text = first_words(html_to_text(raw))
    except Exception:
        return ""
    save_stored_body(post, text, store_dir)
    return text


def _row(post, decision, reason):
    return {
        "url": post.get("url") or "",
        "title": post.get("title") or "",
        "decision": decision,
        "reason": reason,
    }


def screen_posts(posts, seen, fetch, backlog=None):
    """Classify every in-window post, then any backlog item not already classified.

    fetch(post) -> body text. Already-seen free posts are not fetched.
    Returns (rows, candidates). A row is url, title, decision, reason.
    """
    rows = []
    kept = []
    seen_urls = set(seen or [])
    for post in posts:
        reason = title_drop_reason(post)
        if reason:
            rows.append(_row(post, "drop", reason))
            continue
        if post.get("url") in seen_urls:
            rows.append(_row(post, "seen", "already swept"))
            continue
        body = fetch(post) if fetch else ""
        drop = content_drop_reason(post.get("title") or "", body)
        if drop:
            rows.append(_row(post, "drop", drop))
            continue
        if (body or "").strip():
            rows.append(_row(post, "keep", "kept (single-stock pitch or unclear)"))
        else:
            rows.append(_row(post, "keep", "body not available; kept (unclear)"))
        kept.append(post)
    kept_urls = {post.get("url") for post in kept}
    recorded = {row["url"] for row in rows}
    bl_urls = set()
    for item in backlog or []:
        url = item.get("url")
        if not url:
            continue
        bl_urls.add(url)
        if url in kept_urls or url in recorded:
            continue
        item = dict(item)
        item["backlog"] = True
        reason = title_drop_reason(item)
        if reason:
            rows.append(_row(item, "drop", reason))
            continue
        body = fetch(item) if fetch else ""
        drop = content_drop_reason(item.get("title") or "", body)
        if drop:
            rows.append(_row(item, "drop", drop))
            continue
        if (body or "").strip():
            rows.append(_row(item, "keep", "kept (single-stock pitch or unclear)"))
        else:
            rows.append(_row(item, "keep", "body not available; kept (unclear)"))
        kept.append(item)
    for post in kept:
        if post.get("url") in bl_urls:
            post["backlog"] = True
    return rows, kept


def write_screen(path, rows):
    ensure(os.path.dirname(path) or ".")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREEN_FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in SCREEN_FIELDS})


def dropped_from_screen(path):
    """Drop counts read from a screen CSV. Keeps and already-swept rows are not drops."""
    dropped = collections.Counter()
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("decision") or "").strip() == "drop":
                dropped[(row.get("reason") or "unspecified").strip()] += 1
    return dict(dropped)


def apply_screen_counts(stats):
    """Replace stats['dropped'] with counts read from stats['substack_screen']."""
    stats = dict(stats or {})
    path = stats.get("substack_screen") or ""
    if not path:
        return stats
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    if not os.path.exists(path):
        return stats
    stats["dropped"] = dropped_from_screen(path)
    return stats


def pull(r, since, headers):
    out = []
    try:
        for off in range(0, 200, 50):
            j = requests.get(
                f"{r['url'].rstrip('/')}/api/v1/archive?sort=new&limit=50&offset={off}",
                headers=headers,
                timeout=20,
            ).json()
            if not j:
                break
            for p in j:
                if dt.datetime.fromisoformat(p["post_date"].replace("Z", "+00:00")) >= since:
                    out.append(
                        {
                            "sub": r["url"],
                            "url": p["canonical_url"],
                            "title": p["title"],
                            "subtitle": p.get("subtitle") or "",
                            "date": p["post_date"][:10],
                            "audience": p.get("audience"),
                            "wc": p.get("wordcount") or 0,
                        }
                    )
            if dt.datetime.fromisoformat(j[-1]["post_date"].replace("Z", "+00:00")) < since:
                break
    except Exception:
        return r["url"], None
    return r["url"], out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sweep Substack sources for new posts")
    ap.add_argument("--since", default=(dt.date.today() - dt.timedelta(days=7)).isoformat())
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--seen", default=SEEN)
    ap.add_argument("--out-dir", default=REPORTS)
    ap.add_argument("--limit", type=int, default=0, help="only the first N Substack sources (smoke tests)")
    ap.add_argument("--dry-run", action="store_true", help="do not append state/seen_posts.csv")
    ap.add_argument("--skip-earnings", action="store_true")
    a = ap.parse_args(argv)

    headers = {"User-Agent": user_agent()}
    since = dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc)
    ensure(a.out_dir, CACHE, os.path.dirname(a.seen))

    with open(a.seen, newline="", encoding="utf-8") as handle:
        seen = {row["url"] for row in csv.DictReader(handle)}
    with open(a.sources, newline="", encoding="utf-8") as handle:
        src = [row for row in csv.DictReader(handle) if row.get("type") == "substack" and row.get("url")]
    if a.limit:
        src = src[: a.limit]

    with cf.ThreadPoolExecutor(min(20, max(1, len(src)))) as ex:
        res = list(ex.map(lambda row: pull(row, since, headers), src))
    dead = [url for url, posts in res if posts is None]
    in_window = posts_in_window(res)
    new = [post for post in in_window if post["url"] not in seen]
    if not a.dry_run and new:
        with open(a.seen, "a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            for post in new:
                writer.writerow([post["url"], post["sub"], post["date"], post["title"], post["audience"], post["wc"], dt.date.today().isoformat()])

    bl_path = os.path.join(os.path.dirname(a.seen), "backlog.json")
    bl = json.load(open(bl_path, encoding="utf-8")) if os.path.exists(bl_path) else []
    to_fetch = []
    for post in in_window:
        if title_drop_reason(post):
            continue
        if post["url"] in seen:
            continue
        to_fetch.append(post)
    bl_urls_in_window = {post["url"] for post in in_window}
    for item in bl:
        if item.get("url") and item["url"] not in bl_urls_in_window and not title_drop_reason(item):
            to_fetch.append(item)
    bodies = {}
    if to_fetch:
        workers = min(8, len(to_fetch))
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(fetch_body, post, headers): post.get("url") for post in to_fetch}
            for fut in cf.as_completed(futs):
                bodies[futs[fut]] = fut.result()

    def _fetch(post):
        return bodies.get(post.get("url"), "")

    rows, cand = screen_posts(in_window, seen, _fetch, bl)
    today = dt.date.today().isoformat()
    screen_fn = os.path.join(a.out_dir, f"substack_screen_{today}.csv")
    write_screen(screen_fn, rows)
    fn = os.path.join(a.out_dir, f"triage_{today}.json")
    json.dump(cand, open(fn, "w", encoding="utf-8"), indent=1)
    print(f"sources={len(src)} failed={len(dead)} in_window={len(in_window)} new_posts={len(new)} candidates={len(cand)} (backlog {len(bl)}) -> {fn}")
    print(f"screen={screen_fn} rows={len(rows)}")
    if dead:
        print("failed_sources", dead[:20])
    for post in cand:
        print("BACKLOG" if post.get("backlog") else "NEW", post.get("date"), post.get("wc"), post["url"], (post.get("title") or "")[:80])

    rel_screen = os.path.relpath(screen_fn, ROOT)
    if rel_screen.startswith(".."):
        rel_screen = screen_fn
    stats = {
        "date": today,
        "since": a.since,
        "sources": len(src),
        "failed_sources": len(dead),
        "attempted": [row["url"] for row in src],
        "failed": dead,
        "sourced": len(in_window),
        "new_since_last_run": len(new),
        "substack_screen": rel_screen,
        "dropped": dropped_from_screen(screen_fn),
        "candidates_new": len([post for post in cand if not post.get("backlog")]),
        "backlog": len(bl),
        "dry_run": a.dry_run,
    }
    stats_fn = os.path.join(a.out_dir, f"stats_{dt.date.today().isoformat()}.json")
    json.dump(stats, open(stats_fn, "w", encoding="utf-8"), indent=1)
    print("STATS", json.dumps(stats))

    if not a.skip_earnings:
        ed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "earnings_drops.py")
        try:
            print(subprocess.run([sys.executable, ed], capture_output=True, text=True, timeout=600).stdout)
        except Exception as exc:
            print("earnings_drops failed:", exc)


if __name__ == "__main__":
    main()
