"""Build bat/pitches.json: single-stock long pitches for the batting-average windows.

SUB is a worked list of Substack pitches (ticker, date, url, title).
SA pitches come from bat/sa_auth.json when that file exists (public API metadata only).
"""
import json
import os

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
sa_path = os.path.join(HERE, "sa_auth.json")
sa = json.load(open(sa_path, encoding="utf-8")) if os.path.exists(sa_path) else {}
SAP = {}
for n, v in sa.items():
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
json.dump({"SUB": SUB, "SA": SAP, "NONE": NONE}, open(os.path.join(HERE, "pitches.json"), "w", encoding="utf-8"), indent=0)
for k, v in SAP.items():
    print(k, len(v))
print("wrote", os.path.join(HERE, "pitches.json"), "sa_authors", len(SAP))
