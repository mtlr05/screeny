"""Find small/mid-cap US/Canada names with a >=10% one-day drop in the last 7 days.

Universe: config/universe.csv (column ticker, optional) + tickers in state/returns.json
and state/articles_scored.csv. The agent confirms the drop was earnings-day news and
searches for thesis posts. This script does not score anything.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CONFIG, REPORTS, SEEN, STATE, ensure

from px import series


def universe():
    U = set()
    rj = os.path.join(STATE, "returns.json")
    if os.path.exists(rj):
        U |= set(json.load(open(rj, encoding="utf-8")))
    for p in (os.path.join(STATE, "articles_scored.csv"), os.path.join(CONFIG, "universe.csv")):
        if os.path.exists(p):
            U |= {r["ticker"] for r in csv.DictReader(open(p, newline="", encoding="utf-8")) if r.get("ticker")}
    return {t.split(" /")[0].strip() for t in U if t and t not in ("IWM", "XIC.TO")}


U = universe()
ensure(REPORTS)
if not U:
    print("earnings_drops: 0 tickers. Add rows to config/universe.csv (column ticker), or provide state/returns.json or state/articles_scored.csv. Nothing to check.")
    sys.exit(0)
cut = (dt.date.today() - dt.timedelta(days=7)).isoformat()
hits = []
with cf.ThreadPoolExecutor(16) as ex:
    SER = dict(zip(sorted(U), ex.map(series, sorted(U))))
for t, s in SER.items():
    if "err" in s or len(s.get("rows") or []) < 10:
        continue
    r = s["rows"]
    for a, b in zip(r, r[1:]):
        if b[0] >= cut and a[1] and b[1] / a[1] - 1 <= -0.10:
            hits.append((t, b[0], round(100 * (b[1] / a[1] - 1), 1)))
posts = list(csv.reader(open(SEEN, encoding="utf-8")))
out = []
for t, d, p in hits:
    k = re.escape(t.split(".")[0])
    m = [x[0] for x in posts if len(x) > 3 and re.search(rf"\b\$?{k}\b", x[3])][-5:]
    out.append(
        dict(
            ticker=t,
            date=d,
            drop_pct=p,
            known_posts=m,
            todo="confirm earnings-day news; check mcap/listing; search Substack/web for thesis posts in the last 7 days. Pasted X links are optional.",
        )
    )
fn = os.path.join(REPORTS, f"earnings_drops_{dt.date.today().isoformat()}.json")
json.dump(out, open(fn, "w", encoding="utf-8"), indent=1)
print(f"earnings_drops: {len(U)} tickers checked, {len(out)} drops >=10% since {cut} -> {fn}")
for o in out:
    print(o["ticker"], o["date"], o["drop_pct"], len(o["known_posts"]), "known posts")
