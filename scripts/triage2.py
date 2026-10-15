"""Second-pass skim of saved full text. Ranking here is a reading queue, not the /6 score."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, FULLTEXT

T = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(CACHE, "triage1.json"), encoding="utf-8"))
rows = []
for p in T:
    slug = re.search(r"/p/([^/?#]+)", p["url"])
    if not slug:
        continue
    fn = os.path.join(FULLTEXT, slug.group(1)[:60] + ".txt")
    if not os.path.exists(fn):
        continue
    t = open(fn, encoding="utf-8").read()
    low = t.lower()
    na = len(re.findall(r"\b(nasdaq|nyse|tsx|tsxv|tsx-v|otc|cse|nyse american)\b", low))
    nonna = len(re.findall(r"\b(lse|aim:|\.l\b|kosdaq|tokyo|tse:|euronext|xetra|asx|stockholm|warsaw|nse|bse|\(\d{4}\)|sek|€|£|hkex)", low))
    tgt = len(re.findall(r"price target|target price|fair value|intrinsic value|base case|upside", low))
    up = [int(x) for x in re.findall(r"(\d{2,3})\s?%\s?upside", low)]
    hold = bool(re.search(r"\b(hold|neutral|monitor|not a long|pass)\b", low[:1500]))
    big = bool(
        re.search(
            r"\b(amazon|microsoft|netflix|meta|nvidia|tsmc|mercadolibre|salesforce|adobe|uber|booking|s&p global|nike|lululemon|sap|applovin|hermès|lvmh|novo|shopify|cloudflare|micron|reddit|sea limited|nebius|brookfield|vertiv|cadence|deckers|domino|paypal|copart|kinsale|ferrari)\b",
            p["title"].lower(),
        )
    )
    hc = bool(re.search(r"pharma|biotech|therap|clinical|fda|medical|health", low[:3000]))
    s = min(na, 5) * 2 - min(nonna, 5) * 2 + min(tgt, 6) + (3 if up and max(up) >= 40 else 0) - (4 if hold else 0) - (8 if big else 0)
    rows.append(
        dict(
            score=s,
            url=p["url"],
            title=p["title"][:80],
            date=p["date"],
            wc=p.get("wc"),
            na=na,
            nonna=nonna,
            tgt=tgt,
            maxup=max(up) if up else "",
            hold=hold,
            big=big,
            hc=hc,
            fn=fn,
        )
    )
rows.sort(key=lambda r: -r["score"])
dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(CACHE, "triage2.json")
os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
json.dump(rows, open(dest, "w", encoding="utf-8"), indent=1)
for r in rows:
    print(r["score"], r["date"], r["na"], r["nonna"], r["tgt"], r["maxup"], "H" if r["hold"] else "", "HC" if r["hc"] else "", r["title"])
