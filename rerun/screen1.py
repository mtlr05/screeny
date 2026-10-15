"""First-pass screen of rerun/posts.json + saved full text. Writes rerun/screen1.json.

Rules match the scout skill: paywall, single-stock pitch, US/Canada listing, not a hold.
Cap, moat, and long-disclosure are applied later (resolve + full read).
"""
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from _paths import RERUN

d = json.load(open(os.path.join(RERUN, "posts.json"), encoding="utf-8"))
FT = {}
for f in glob.glob(os.path.join(RERUN, "ft", "*.json")):
    j = json.load(open(f, encoding="utf-8"))
    FT[j["url"]] = j
EX = r"(NASDAQ|Nasdaq|NYSE American|NYSEAMERICAN|NYSE ?MKT|NYSE|AMEX|OTCQX|OTCQB|OTC ?Pink|OTCMKTS|OTC|TSX-?V|TSXV|TSX|CSE|NEO|CBOE|LSE|AIM|ASX|TYO|TSE|HKEX|HKG|SGX|KRX|KOSDAQ|ETR|XETRA|FRA|EPA|BIT|BME|AMS|STO|OSL|CPH|HEL|SIX|SWX|WSE|JSE|BVMF|NSE|BSE|TASE|TPE|KLSE|IDX|SET|NZX|BMV)"
NA = {"NASDAQ", "Nasdaq", "NYSE American", "NYSEAMERICAN", "NYSE MKT", "NYSEMKT", "NYSE", "AMEX", "OTCQX", "OTCQB", "OTC Pink", "OTCPink", "OTCMKTS", "OTC", "TSX-V", "TSXV", "TSX", "CSE", "NEO", "CBOE", "TSXV"}
NEG = re.compile(
    r"portfolio (update|review)|monthly|weekly|week in|roundup|round-up|recap|letter to|quarterly letter|macro|podcast|links|reading list|digest|market update|watchlist|thread|interview|q&a|ask me|my holdings|holdings|best ideas|bullet investment ideas|ideas #|lessons|top \d+|\d+ stocks|stocks to|screen(er)?\b|newsletter|announcement|welcome|subscriber|giveaway|year in review|performance|returns? (update|review)|mailbag|AMA\b",
    re.I,
)
HOLD = re.compile(
    r"\b(rating|verdict|recommendation|conclusion)\s*[:\-]?\s*(hold|neutral|sell|avoid|pass)\b|\bi (am|\'m) (neutral|not buying|passing|short)\b|\bshort (thesis|report|idea)\b|\bstill researching\b|\bi (would|will) not (buy|own)\b|\bdo not intend to\b|\bnot a buy\b",
    re.I,
)
TK = re.compile(EX + r"\s*[:\-]\s*\$?([A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z]{1,2})?)\b")
DOL = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
PAR = re.compile(r"\(([A-Z]{2,5})\)")
rows = []
C = collections.Counter()
allp = d["posts"] + d.get("manual", [])
for p in allp:
    r = dict(p)
    r["reason"] = None
    if p.get("ptype") != "newsletter":
        r["reason"] = "not a written article (podcast/restack)"
    elif p.get("audience") != "everyone":
        r["reason"] = "paywalled"
    elif p.get("stype") == "forum":
        r["reason"] = None
    else:
        j = FT.get(p["url"])
        if not j:
            r["reason"] = "fetch failed"
        else:
            vis = len(j["text"].split())
            wc = j["wc"] or vis
            if j["truncated"] or (j["paywall_marker"] and vis < 0.7 * wc):
                r["reason"] = "preview-only (paywall in body)"
    if not r["reason"] and p.get("stype") != "forum":
        t = (p.get("title") or "") + " " + (p.get("subtitle") or "")
        body = FT[p["url"]]["text"]
        if NEG.search(t):
            r["reason"] = "not a single-stock pitch (recap/macro/portfolio/list)"
        else:
            ex = TK.findall(t + " " + body[:6000])
            dl = DOL.findall(t + " " + body)
            pr = PAR.findall(p.get("title") or "")
            cnt = collections.Counter([x[1] for x in ex] + dl + pr * 3)
            for bad in ["US", "CEO", "CFO", "EPS", "FCF", "AI", "EV", "ROIC", "USD", "CAD", "IPO", "M", "B", "K", "TAM", "GAAP", "EBITDA", "ETF", "SBC", "NAV", "LNG", "FDA", "THE", "I"]:
                cnt.pop(bad, None)
            if not cnt:
                r["reason"] = "not a single-stock pitch (no ticker focus)"
            else:
                top, n = cnt.most_common(1)[0]
                tot = sum(cnt.values())
                exch = [x[0] for x in ex if x[1] == top]
                r["ticker"] = top
                r["exch"] = exch[0] if exch else ""
                r["share"] = round(n / tot, 2)
                r["nt"] = len(cnt)
                if n / tot < 0.4 and len(cnt) >= 4:
                    r["reason"] = "not a single-stock pitch (multi-stock)"
                elif r["exch"] and r["exch"] not in NA:
                    r["reason"] = "not US/Canada listed"
                elif HOLD.search(body):
                    r["reason"] = "hold/neutral/short or still researching"
    rows.append(r)
    C[r["reason"]] += 1
json.dump(rows, open(os.path.join(RERUN, "screen1.json"), "w", encoding="utf-8"))
for k, v in C.most_common():
    print(v, k)
print(len(rows))
