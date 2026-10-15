"""Cheap title triage of a swept-posts JSON file. Screening rules are applied later, by hand, after the full read."""
import collections
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, STATE

posts_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(CACHE, "swept_posts.json")
P = json.load(open(posts_path, encoding="utf-8"))
old = set()
scored = os.path.join(STATE, "articles_scored.csv")
if os.path.exists(scored):
    old = {r["url"] for r in csv.DictReader(open(scored, newline="", encoding="utf-8")) if r.get("url")}
c = collections.Counter()
out = []
NEG = re.compile(
    r"portfolio update|monthly|weekly|roundup|recap|letter|macro|podcast|links|reading list|week in|digest|market update|watchlist|thread|interview|chart",
    re.I,
)
POS = re.compile(
    r"thesis|deep.?dive|undervalued|upside|multibagger|why i (own|bought)|initiat|long |\(\$?[A-Z]{2,5}\)|\$[A-Z]{2,5}|tsx|nasdaq|nyse|otc|spin.?off|compounder|bagger|mispriced|cheap",
    re.I,
)
for p in P:
    if p["url"] in old:
        c["already_scored"] += 1
        continue
    if p["audience"] != "everyone":
        c["paywalled"] += 1
        continue
    # no word-count cutoff
    t = p["title"] + " " + p.get("subtitle", "")
    if NEG.search(t):
        c["recap/macro"] += 1
        continue
    if not POS.search(t):
        c["no_pitch_signal"] += 1
        continue
    c["candidate"] += 1
    out.append(p)
print(c)
dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(CACHE, "triage1.json")
json.dump(out, open(dest, "w", encoding="utf-8"))
for p in out:
    print(p["date"], p.get("sub", "")[:18], p.get("wc"), p["title"][:90])
