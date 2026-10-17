"""Weekly sweep: pull active Substack archives, dedupe against seen_posts.csv, write a triage file.

Default window is the last 7 days. Paths are repo-relative (config/, state/, reports/).
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys

import requests
import concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, REPORTS, SEEN, SOURCES, ensure, user_agent

NEG = re.compile(
    r"portfolio update|monthly|weekly|roundup|recap|letter|macro|podcast|links|reading list|week in|digest|market update|watchlist|thread|interview|chart",
    re.I,
)
POS = re.compile(
    r"thesis|deep.?dive|undervalued|upside|multibagger|why i (own|bought)|initiat|long |\(\$?[A-Z]{2,5}\)|\$[A-Z]{2,5}|tsx|nasdaq|nyse|otc|spin.?off|compounder|bagger|mispriced|cheap",
    re.I,
)


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


def drop_counts(posts):
    dropped = collections.Counter()
    for post in posts:
        if post.get("audience") != "everyone":
            dropped["paywalled"] += 1
        elif NEG.search((post.get("title") or "") + " " + (post.get("subtitle") or "")):
            dropped["not a single-stock pitch (recap/macro/list)"] += 1
        elif not POS.search((post.get("title") or "") + " " + (post.get("subtitle") or "")):
            dropped["not a single-stock pitch (no pitch signal in title)"] += 1
    return dropped


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

    cand = [
        post
        for post in new
        if post["audience"] == "everyone"
        and not NEG.search(post["title"] + " " + post["subtitle"])
        and POS.search(post["title"] + " " + post["subtitle"])
    ]
    bl_path = os.path.join(os.path.dirname(a.seen), "backlog.json")
    bl = json.load(open(bl_path, encoding="utf-8")) if os.path.exists(bl_path) else []
    for item in bl:
        item["backlog"] = True
    cand = cand + [item for item in bl if item["url"] not in {row["url"] for row in cand}]
    fn = os.path.join(a.out_dir, f"triage_{dt.date.today().isoformat()}.json")
    json.dump(cand, open(fn, "w", encoding="utf-8"), indent=1)
    print(f"sources={len(src)} failed={len(dead)} in_window={len(in_window)} new_posts={len(new)} candidates={len(cand)} (backlog {len(bl)}) -> {fn}")
    if dead:
        print("failed_sources", dead[:20])
    for post in cand:
        print("BACKLOG" if post.get("backlog") else "NEW", post["date"], post.get("wc"), post["url"], (post.get("title") or "")[:80])

    stats = {
        "date": dt.date.today().isoformat(),
        "since": a.since,
        "sources": len(src),
        "failed_sources": len(dead),
        "attempted": [row["url"] for row in src],
        "failed": dead,
        "sourced": len(in_window),
        "new_since_last_run": len(new),
        "dropped": dict(drop_counts(in_window)),
        "candidates_new": len(cand) - len(bl),
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
