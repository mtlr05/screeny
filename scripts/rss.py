"""Print RSS/Atom entries since a date. For manual sources (MicroCapClub, subreddit feeds).

    python3 scripts/rss.py FEED_URL --since YYYY-MM-DD
A blocked feed is reported and skipped. Nothing is scored from a headline.
"""
import argparse
import datetime as dt
import sys

import feedparser

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--since", default=(dt.date.today() - dt.timedelta(days=7)).isoformat())
a = ap.parse_args()
d = feedparser.parse(a.url)
if getattr(d, "bozo", 0) and not d.entries:
    print(f"unreachable {a.url}: {getattr(d, 'bozo_exception', 'no entries')}")
    sys.exit(0)
status = getattr(d, "status", None)
if status and status >= 400:
    print(f"unreachable {a.url}: HTTP {status}")
    sys.exit(0)
def entry_day(e):
    st = e.get("published_parsed") or e.get("updated_parsed")
    if st:
        return dt.date(st.tm_year, st.tm_mon, st.tm_mday).isoformat()
    raw = (e.get("published") or e.get("updated") or "")[:10]
    return raw


n = 0
for e in d.entries:
    day = entry_day(e)
    if day and day < a.since:
        continue
    title = e.get("title") or ""
    link = e.get("link") or ""
    print(f"{day}\t{link}\t{title}")
    n += 1
print(f"entries={n} feed={a.url}")
