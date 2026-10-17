"""Build bat/pitches.json: single-stock long pitches for the batting-average windows.

SUB is a worked list of Substack pitches (ticker, date, url, title) used when an
author has not been detected yet. `python3 bat/pitches.py SUBDOMAIN` reads the
archive and tags each pitch with method title or body (see bat/lib.py).

SA pitches come from bat/sa_author_cache.json when that file exists (public API metadata only).
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SUB = {
    "Value & Error (Matt Lindsay, mattlindsay.substack.com)": [("DK", "2025-04-05", "https://mattlindsay.substack.com/", "Position Disclosure: Delek US")],
    "mvcinvesting (mvcinvesting.substack.com)": [
        (t, d, "https://mvcinvesting.substack.com/", n)
        for t, d, n in [
            ("RKLB", "2025-03-13", "Rocket Lab: Investment Thesis Explained"),
            ("HITI", "2025-03-14", "High Tide: Investment Thesis Explained"),
            ("HIMS", "2025-03-14", "Hims & Hers: Q3 2024 Earnings Call Takeaways (holding)"),
            ("REAX", "2025-03-15", "The Real Brokerage: Investment Thesis Explained"),
            ("NBIS", "2025-03-16", "Nebius: Investment Thesis Explained"),
            ("TEM", "2025-03-16", "Tempus AI: Investment Thesis Explained"),
            ("DLO", "2025-03-16", "DLocal: Investment Thesis Explained"),
            ("TBBB", "2025-03-25", "BBB Foods: Investment Thesis Explained"),
            ("ALVO", "2025-05-01", "Alvotech: Investment Thesis Explained"),
            ("CLPT", "2025-06-06", "Clearpoint Neuro: Investment Thesis Explained"),
            ("NURS.V", "2025-06-26", "Hydreight: Investment Thesis Explained"),
            ("PGY", "2025-07-14", "Pagaya: Investment Thesis Explained"),
            ("HROW", "2025-08-26", "Why I Own Harrow: My New Position"),
            ("SEI", "2025-09-24", "Solaris Energy Infrastructure: Investment Thesis Explained"),
            ("TWST", "2025-10-09", "Twist Biosciences: Investment Thesis Explained"),
        ]
    ],
    "P14 Capital (p14capital.substack.com)": [
        (t, d, "https://p14capital.substack.com/", n)
        for t, d, n in [
            ("GXO", "2025-01-17", "LONG $GXO"),
            ("CTLP", "2025-02-06", "LONG $CTLP"),
            ("IAS", "2025-04-14", "LONG $IAS"),
            ("EEFT", "2025-04-23", "LONG $EEFT"),
            ("DSP", "2025-06-29", "LONG $DSP"),
        ]
    ],
    "Sylence Capital (sylencecapital.substack.com)": [
        (t, d, "https://sylencecapital.substack.com/", n)
        for t, d, n in [
            ("JVA", "2024-04-27", "JVA- Coffee Holding Co (buy)"),
            ("IOFNF", "2024-04-28", "IOFNF- Iofina (buy)"),
            ("SCIA", "2024-08-15", "SCIA- SCI Engineered Materials"),
            ("ALTO", "2024-08-15", "ALTO- ALTO Ingredients"),
            ("NL", "2025-06-20", "NL Industries"),
            ("GTEC", "2025-06-28", "GTEC- Greenland Technologies"),
            ("DDI", "2025-08-04", "Double Down Interactive"),
            ("RKDA", "2025-10-06", "RKDA- Reverse Merger with Roosevelt Resources"),
        ]
    ],
}
NONE = {
    "guillaumemeignin (PDEX)": "archive starts 2026-04-29",
    "The Multibagger Investor (KITS.TO)": "archive starts 2026-07-25",
    "The Micro-Capo / Rodrigo Lezama (LEAT)": "archive starts 2025-10-28",
    "Blindspot Value (LUMN, SRI)": "archive starts 2026-06-23",
    "Gustav / aktieblogg (KARO)": "archive starts 2026-01-24",
}
def sa_from_auth(sa):
    """Single-stock bullish pitches from a public Seeking Alpha author dump."""
    SAP = {}
    for n, v in (sa or {}).items():
        L = []
        for a in v.get("arts") or []:
            se = a.get("se") or []
            if not se or se[0] not in ("bullish", "very_bullish"):
                continue
            tk = a.get("tk") or []
            us = [t for t in tk if ":" not in t]
            ca = [t.split(":")[0] for t in tk if str(t).endswith(":CA")]
            if len(us) == 1:
                t = us[0]
            elif not us and len(set(ca)) == 1:
                t = ca[0] + ".TO"
            else:
                continue
            L.append((t, a["d"], f"https://seekingalpha.com/article/{a['id']}", a["t"]))
        SAP[n + " (SA)"] = L
    return SAP


def author_subdomain(key):
    found = re.findall(r"([a-z0-9-]+)\.substack\.com", (key or "").lower())
    if found:
        return found[0]
    token = re.split(r"[\s(]", (key or "").strip().lower())[0]
    return token


def merge_detected(base, subdomain, pitches):
    """Replace any hand-entered rows for this subdomain with detected pitches."""
    sub = (subdomain or "").lower()
    for key in [k for k in base if author_subdomain(k) == sub]:
        del base[key]
    base[f"{sub} ({sub}.substack.com)"] = pitches
    return base


def main(argv=None):
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Build bat/pitches.json from hand lists, or detect Substack pitches")
    ap.add_argument("subdomains", nargs="*", help="Substack subdomains to detect (title, then body)")
    ap.add_argument("--limit", type=int, default=0, help="newest N newsletter posts per author (0 = through the 2-year window)")
    ap.add_argument("--since", default="", help="oldest publish date to read (default: start of the 2-year window)")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between uncached HTTP calls")
    ap.add_argument("--out", default="", help="output JSON (default bat/pitches.json)")
    args = ap.parse_args(argv)
    out_path = args.out or os.path.join(HERE, "pitches.json")
    sa_path = os.path.join(HERE, "sa_author_cache.json")
    sa = json.load(open(sa_path, encoding="utf-8")) if os.path.exists(sa_path) else {}
    SAP = sa_from_auth(sa)
    sub = {k: list(v) for k, v in SUB.items()}
    if args.subdomains:
        import lib

        for name in args.subdomains:
            result = lib.collect_author(
                name,
                limit=args.limit,
                since=args.since or None,
                sleep=args.sleep,
            )
            merge_detected(sub, result["subdomain"], result["pitches"])
            raw = result.get("pitches_before_dedupe") or []
            title_n = sum(1 for p in result["pitches"] if p.get("method") == "title")
            body_n = sum(1 for p in result["pitches"] if p.get("method") == "body")
            raw_title = sum(1 for p in raw if p.get("method") == "title")
            raw_body = sum(1 for p in raw if p.get("method") == "body")
            print(
                f"{result['subdomain']}: posts={result['posts_seen']} bodies={result['bodies_fetched']} "
                f"pitches={len(result['pitches'])} title={title_n} body={body_n} "
                f"(before one-per-ticker: title={raw_title} body={raw_body}) since={result['since']}"
            )
            for pitch in result["pitches"]:
                print(
                    f"  {pitch['date']} {pitch['method']:5} {pitch['confidence']:.2f} {pitch['ticker']:8} "
                    f"{pitch['reason']} | {(pitch['title'] or '')[:70]}"
                )
            if result["skipped"]:
                print("  skipped", dict(sorted(result["skipped"].items(), key=lambda item: -item[1])))
            kept_urls = {p.get("url") for p in result["pitches"]}
            repeats = [p for p in raw if p.get("url") not in kept_urls]
            for pitch in repeats:
                print(
                    f"  repeat {pitch['date']} {pitch['method']:5} {pitch['confidence']:.2f} {pitch['ticker']:8} "
                    f"| {(pitch['title'] or '')[:70]}"
                )
    json.dump({"SUB": sub, "SA": SAP, "NONE": NONE}, open(out_path, "w", encoding="utf-8"), indent=0)
    for key, rows in SAP.items():
        print(key, len(rows))
    print("wrote", out_path, "sa_authors", len(SAP), "substack_authors", len(sub))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
