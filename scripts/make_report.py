#!/usr/bin/env python3
"""Build REPORT.md and articles.csv.

On-demand input is state/scored.json (or --scored). --example renders the
checked-in sample (examples/scored.json + examples/onepagers.json).

--legacy assembles a full rerun from rerun/screen1.json, resolved.json,
cands.json, extract.json, posts.json, and rerun/dispo.py when those files exist.

--pdf writes a PDF next to the Markdown file and needs the optional markdown
and weasyprint packages. Markdown is the report either way.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, EXAMPLES, REPORTS, RERUN, ROOT, STATE, ensure

LBL = ["Thesis/runway", "Return ~40%/yr", "CEO large holder", "Moat or edge", "Differential view", "Dated catalyst"]
FULL = [1, 1, 1, 1, 1, 1]
CN = [
    "Thesis with secular runway",
    "Return ~40%/yr",
    "CEO is a large shareholder",
    "Moat or edge",
    "Differential view",
    "Dated catalyst within ~24 months",
]


def miss(sc):
    return "; ".join(f"{l} {v:g}" for l, v, f in zip(LBL, sc, FULL) if v < f) or "full credit"


def tot(sc):
    return round(sum(sc), 2)


def fmt_bat(bat):
    def one(w):
        x = (bat.get("summary") or {}).get(w)
        if not x:
            return f"{w} n/a"
        return f"{w} {x['hits']}/{x['n']} = {x['pct']*100:.0f}% (med excess {x['median_excess']*100:+.0f} pts)"

    note = bat.get("note")
    extra = f" [{note}]" if note else ""
    return f"{one('1y')}; {one('2y')}{extra}"


def bat_for(source, batting):
    return batting.get(source) or batting.get(source.replace(" (SA)", ""))


def cell_bat(article, batting):
    if article.get("ba"):
        return article["ba"]
    bat = bat_for(article.get("source") or "", batting)
    if not bat:
        return "n/a"
    s = bat.get("summary") or {}
    y2, y1 = s.get("2y"), s.get("1y")
    if y2:
        return f"{y2['hits']}/{y2['n']} = {y2['pct']*100:.0f}%"
    if y1:
        return f"{y1['hits']}/{y1['n']} = {y1['pct']*100:.0f}% (1y)"
    return "n/a"


def top_bat(authors, batting, window, n=5, min_n=5):
    rows = []
    seen = set()
    for a in authors:
        if a in seen:
            continue
        seen.add(a)
        bat = batting.get(a)
        if not bat:
            continue
        x = (bat.get("summary") or {}).get(window)
        if not x or x["n"] < min_n:
            continue
        rows.append((a, x))
    rows.sort(key=lambda ax: (-ax[1]["pct"], ax[0]))
    return rows[:n]


def since_publish(r, live):
    if r.get("since_publish"):
        return r["since_publish"]
    if not live:
        return "n/a"
    import px

    bm = "XIC.TO" if str(r["sym"]).endswith((".TO", ".V", ".CN")) else "IWM"
    a = px.ret(r["sym"], r["date"])
    b = px.ret(bm, r["date"])
    if not a or not b or b.get("ret") is None:
        return "n/a"
    return f"{a['ret']*100:+.1f}% vs {bm} {b['ret']*100:+.1f}%"


def rank(articles):
    rows = []
    for r in articles:
        sc = r.get("sc") or []
        if len(sc) < 6:
            continue
        item = dict(r)
        item["sc"] = list(sc[:6])
        item["score"] = tot(item["sc"])
        rows.append(item)
    best = {}
    for r in rows:
        b = best.get(r["sym"])
        if not b or r["score"] > b["score"] or (r["score"] == b["score"] and r["date"] > b["date"]):
            best[r["sym"]] = r
    pool = sorted(best.values(), key=lambda r: (-r["score"], r["sym"]))
    if not pool:
        return rows, [], [], 0
    # Top 15 plus ties at the 15th score. A shorter pool is the whole list.
    if len(pool) > 15:
        cut = pool[14]["score"]
        ranked = [r for r in pool if r["score"] >= cut]
        near = [r for r in pool if r["score"] < cut][:6]
    else:
        ranked = pool
        near = []
        cut = pool[-1]["score"]
    return rows, ranked, near, cut


def render(doc, onepagers, live):
    st = doc.get("stats") or {}
    batting = doc.get("batting") or {}
    if os.path.exists(os.path.join(STATE, "batting.json")):
        stored = json.load(open(os.path.join(STATE, "batting.json"), encoding="utf-8"))
        for k, v in stored.items():
            batting.setdefault(k, v)
    rows, ranked, near, cut = rank(doc.get("articles") or [])
    window = doc.get("window") or ["", ""]
    L = []
    A = L.append
    A("# Stock article scout: ranked report")
    A("")
    A(f"Window: articles published {window[0]} to {window[1]}. Generated {dt.date.today()}.")
    A("")
    A("## Stats")
    A("")
    A(f"- **Articles sourced:** {st.get('sourced', 0):,}")
    A(f"- **Articles read in full:** {st.get('read', 0)}")
    A(f"- **Articles scored:** {st.get('scored', len(rows))}")
    A("")
    A("## 1. Screening")
    A("")
    A(
        'A post must be: free to read in full (paywalled or preview-only posts are dropped); a single-stock bullish pitch (updates and earnings reviews count); on a small/mid-cap company; listed in the US or Canada; on a business with a moat or an edge; and the author must disclose holding a long position (a Seeking Alpha "beneficial long position" disclosure, or an explicit "I own / I am long / I hold a position" statement; "may hold" boilerplate does not count). Any length qualifies.'
    )
    A("")
    A("## 2. Reported, not scored")
    A("")
    A(
        "Fact-check of key claims, author batting average (share of past long pitches that beat SPY, or XIC.TO for Canadian listings, over 1-year and 2-year windows; see the Author batting average skill), management guidance record, balance-sheet flags, and soft notes. Shown per name; they do not change the score."
    )
    A("")
    A("## 3. Scoring (out of 6, 1 point each)")
    A("")
    A("1. **Thesis with secular runway**: cheap with no growth = 0.5.")
    A("2. **Return ~40%/yr**: from the publish-day close to the author's target over the author's timeframe (2 years if none given). 25-40%/yr = 0.5; under 25%/yr = 0.")
    A("3. **CEO is a large shareholder** (roughly 5%+ = 1; 1-5% = 0.5).")
    A("4. **Moat or edge**: moat graded on the five moat types (Strong 1 / Moderate 0.75 / Narrow 0.5), or an edge: proven operator, allocator or dealmaker, or an obsessive founder-builder (a good guidance record supports it).")
    A("5. **Differential view**: names why the market is wrong (stigma or label, temporary or mundane issue, neglect) and why it corrects; an overreaction to temporary news supports it.")
    A("6. **Dated catalyst within ~24 months**: undated = 0.5.")
    A("")
    A(f"Ranking: best article per ticker; top 15 plus all ties at 15th (cut = {cut:g}), ties alphabetical.")
    A("")
    A("## Ranked list")
    A("")
    A("| # | Ticker | Score /6 | Article | Source | Published | BA 2y (1y) | Below full credit | Since publish vs benchmark |")
    A("|---|---|---|---|---|---|---|---|---|")
    out = []
    for n, r in enumerate(ranked, 1):
        ps = since_publish(r, live)
        A(f"| {n} | {r['sym']} | {r['score']:g} | [{r['title']}]({r['url']}) | {r['source']} | {r['date']} | {cell_bat(r, batting)} | {miss(r['sc'])} | {ps} |")
        out.append((n, r))
    A("")
    A("### Per-name notes (reported, not scored)")
    A("")
    for n, r in out:
        nt = r.get("notes") or {}
        A(f"**{n}. {r['sym']}** ({r['score']:g}): {r.get('note') or ''}.")
        for k, label in (("fact", "Fact-check"), ("guidance", "Guidance"), ("balance", "Balance"), ("soft", "Soft")):
            if nt.get(k):
                A(f"- {label}: {nt[k]}")
        if r.get("bat_line"):
            A(f"- Author batting average: {r['bat_line']}")
        else:
            bat = bat_for(r["source"], batting)
            if bat:
                A(f"- Author batting average: {fmt_bat(bat)}")
        A("")
    authors = [r["source"] for r in ranked] + [r["source"] for r in near]
    A("## Author batting averages (top 5 of the 21)")
    A("")
    A("Measured on past single-stock long pitches only. 1-year window: pitches published 1–2 years ago, 12-month total return vs SPY (XIC.TO for Canadian listings). 2-year window: pitches published 2–3 years ago, 24-month total return. Min 5 pitches to rank; ties alphabetical. Authors with thinner archives show n/a on the one-pagers.")
    A("")
    for window_name, title in (("1y", "### By 1-year batting average"), ("2y", "### By 2-year batting average")):
        A(title)
        A("")
        A("| # | Author | Hits / N | Avg | Median excess | Best | Worst |")
        A("|---|---|---|---|---|---|---|")
        got = top_bat(authors, batting, window_name)
        for i, (a, x) in enumerate(got, 1):
            A(f"| {i} | {a} | {x['hits']}/{x['n']} | {x['pct']*100:.0f}% | {x['median_excess']*100:+.0f} pts | {x['best']} | {x['worst']} |")
        if not got:
            A("| — | none with ≥5 pitches | | | | | |")
        A("")
    A("## Next six (ranks 16–21)")
    A("")
    A("| # | Ticker | Score /6 | Article | Source | Below full credit |")
    A("|---|---|---|---|---|---|")
    for i, r in enumerate(near, 16):
        A(f"| {i} | {r['sym']} | {r['score']:g} | [{r['title']}]({r['url']}) | {r['source']} | {miss(r['sc'])} |")
    A("")
    A("## Caveats")
    A("")
    A('- Prices are Yahoo daily closes; "since publish" uses the first close on or after the publish date.')
    amb_text = doc.get("ambiguous_text")
    amb = doc.get("ambiguous") or []
    shown = amb_text if amb_text else ("; ".join(amb) if amb else "none recorded")
    A("- Long-disclosure ambiguous (dropped): " + shown + ".")
    A("- CEO stakes come from the article, checked against Yahoo insider holdings where available.")
    A("- Author batting averages use adjusted closes (Yahoo); SPY for US names, XIC.TO for Canadian. Delisted/acquired names use the buyout or last trade when available; otherwise they are excluded and noted in batting.json. SA author histories used the public author API (title, date, ticker, sentiment); full bodies were not required.")
    skipped = st.get("sa_skipped_unread")
    if skipped is not None:
        A(f"- Seeking Alpha articles skipped because the full text could not be read: {skipped}. Previews were not scored.")
    A("")
    A("## Appendix: one-pagers")
    A("")
    A("One page per ranked name: each criterion with its score and reason, then red flags (reported, not scored).")
    A("")
    pages = list(out) + [(i, r) for i, r in enumerate(near, 16)]
    for n, r in pages:
        o = onepagers.get(r["sym"]) if onepagers else None
        A('<div class="pb"></div>')
        A("")
        A(f"### {n}. {r['sym']}" + (f" ({o['company']})" if o else "") + f": {r['score']:g} / 6")
        A("")
        tail = f". {o['words']} words. {o['read']}. Long disclosure: {o['long']}." if o else "."
        A(f"[{r['title'].rstrip('.')}]({r['url']}). {r['source']}, {r['date']}{tail}")
        A("")
        if r.get("bat_line"):
            A(f"**Author batting average:** {r['bat_line']}")
            A("")
        else:
            bat = bat_for(r["source"], batting)
            if bat:
                A(f"**Author batting average:** {fmt_bat(bat)}")
                A("")
        if not o:
            A("_One-pager not yet written for this name; add it to onepagers.json._")
            A("")
            continue
        for k, (lab, v) in enumerate(zip(CN, r["sc"]), 1):
            A(f"{k}. **{lab}: {v:g}.** {o.get('c%d' % k, 'not recorded')}")
        A("")
        A("**Red flags (reported, not scored):**")
        for flag in o.get("flags") or []:
            A(f"- {flag}")
        if o.get("thin"):
            A("")
            A("_Stored notes were thin for this name, so the justifications were reconstructed from the saved full text._")
        A("")
    A('<div class="pb"></div>')
    A("")
    A("## Appendix: detailed stats")
    A("")
    if doc.get("detailed_stats_md"):
        A(doc["detailed_stats_md"].strip())
        A("")
    else:
        sourced = st.get("sourced", 0)
        A(f"- **Articles sourced:** {sourced:,} posts in window")
        for k, v in sorted((st.get("by_type") or {}).items(), key=lambda kv: -kv[1]):
            A(f"  - {k}: {v:,}")
        unr = st.get("unreachable") or []
        if unr:
            A(f"  - Sources that could not be read: {len(unr)} (" + "; ".join(unr) + ")")
        A(f"- **Passed screening:** {st.get('passed', st.get('scored', len(rows)))} articles ({st.get('tickers', len({r['sym'] for r in rows}))} tickers)")
        A("- **Dropped, by screening reason:**")
        for k, v in (st.get("drops") or {}).items():
            A(f"  - {k}: {v:,}")
        A(f"- **Read in full:** {st.get('read', 0)}")
        A(f"- **Scored /6:** {st.get('scored', len(rows))}")
        if skipped is not None:
            A(f"- **Seeking Alpha skipped (full text unavailable, not scored):** {skipped}")
        sa = st.get("sa")
        if sa:
            A("- **Seeking Alpha breakdown (Long Ideas only; investing-group posts excluded):**")
            A(f"  - Long Ideas captured: {sa.get('li', 0):,} (published {sa.get('li_from', '')} to {sa.get('li_to', '')})")
            A(f"  - Passed list screen (cap, listing, single stock, not ETF/recap): {sa.get('kept', 0):,}")
            A(f"  - Read in full: {sa.get('read', 0)} ({sa.get('previews', 0)} were previews and were not scored)")
            A(f"  - Skipped because the full text could not be read: {sa.get('skipped_unread', skipped or 0)}")
            A(f"  - Scored: {sa.get('scored', 0)}")
        A("")
    return "\n".join(L) + "\n", rows, ranked


def write_outputs(md, rows, ranked, out_path):
    ensure(os.path.dirname(out_path) or ".")
    open(out_path, "w", encoding="utf-8").write(md)
    csv_path = os.path.join(os.path.dirname(out_path), "articles.csv")
    rk = {id(r) for r in ranked}
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "score", "T", "R", "C", "M", "D", "K", "title", "url", "source", "date", "ranked"])
        for r in sorted(rows, key=lambda r: (-r["score"], r["sym"])):
            w.writerow([r["sym"], r["score"], *r["sc"], r["title"], r["url"], r["source"], r["date"], id(r) in rk])
    print(out_path)
    print(csv_path)


def try_pdf(md_path):
    try:
        import markdown
        import weasyprint
    except Exception as e:
        print("PDF skipped (optional markdown/weasyprint not installed):", e)
        return
    h = markdown.markdown(open(md_path, encoding="utf-8").read(), extensions=["tables"])
    css = "@page{size:Letter landscape;margin:1.4cm} body{font-family:sans-serif;font-size:9.5pt} table{border-collapse:collapse;font-size:8pt} td,th{border:1px solid #bbb;padding:3px} .pb{page-break-before:always} h3{margin-top:0} a{color:#1a4fa0}"
    pdf_path = os.path.splitext(md_path)[0] + ".pdf"
    weasyprint.HTML(string=f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{h}</body></html>").write_pdf(pdf_path)
    print(pdf_path)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def legacy(out_path, want_pdf):
    """Full-rerun assembly. Requires the rerun JSON bundle from a completed sweep."""
    needed = ["screen1.json", "resolved.json", "cands.json", "extract.json", "posts.json"]
    missing = [n for n in needed if not os.path.exists(os.path.join(RERUN, n))]
    if missing:
        print("legacy inputs missing:", ", ".join(missing))
        print("Weekly runs use state/scored.json. Pass --scored or --example.")
        sys.exit(2)
    sys.path.insert(0, RERUN)
    import dispo as _d
    from dispo import AMBIG, D, DROP, EXTRA, LONG, S

    scored = {i: v for i, v in S.items() if i in LONG}
    extra = [e for e in EXTRA if e["sym"] in LONG]
    notlong = len(_d.S) + len(_d.EXTRA) - len(scored) - len(extra)
    SCR = load_json(os.path.join(RERUN, "screen1.json"))
    RES = load_json(os.path.join(RERUN, "resolved.json"))["todo"]
    CAN = load_json(os.path.join(RERUN, "cands.json"))
    X = load_json(os.path.join(RERUN, "extract.json"))
    POSTS = load_json(os.path.join(RERUN, "posts.json"))
    articles = []
    for i, sc in scored.items():
        x = X[str(i)] if str(i) in X else X[i]
        articles.append(dict(sym=x["sym"], title=x["title"], url=x["url"], date=x["date"], source=x["source"], sc=list(sc[:6]), note=sc[6] if len(sc) > 6 else ""))
    for e in extra:
        articles.append(dict(e, sc=list(e["sc"])))
    sa_path = os.path.join(STATE, "sa_scores.json")
    if os.path.exists(sa_path):
        for v in load_json(sa_path).values():
            if v.get("status") == "scored":
                articles.append(dict(sym=v["ticker"], title=v["title"], url=v["url"], date=v["date"], source=v["author"] + " (SA)", sc=list(v["sc"]), note=v.get("note") or ""))
    drops = collections.Counter()
    for p in SCR:
        reason = p.get("reason")
        if reason and "hold" not in reason and not (str(reason).endswith("(no ticker focus)") and (p.get("vsig") or 0) >= 6):
            drops[reason] += 1
    for p in RES:
        c = p.get("scr")
        if c == "large cap":
            drops["not small/mid cap"] += 1
        elif c == "non-NA":
            drops["not US/Canada listed"] += 1
        elif c == "fund/ETF":
            drops["fund / ETF, not an operating company"] += 1
    drops["not a single-stock bullish pitch on a US/Canada small/mid cap (title review)"] += len(CAN.get("rest") or [])
    for k in D.values():
        drops[DROP[k] + " (after full read)"] += 1
    drops["author not long (no explicit long-position disclosure)"] += notlong
    by = collections.Counter(p.get("stype") for p in SCR)
    stats = {
        "sourced": len(SCR),
        "read": len(X) + len(_d.EXTRA),
        "scored": len(articles),
        "passed": len(articles),
        "by_type": dict(by),
        "unreachable": POSTS.get("manual_unreachable") or [],
        "drops": dict(drops.most_common()),
        "tickers": len({a["sym"] for a in articles}),
    }
    sab = os.path.join(STATE, "sa_breakdown.json")
    if os.path.exists(sab):
        stats["sa"] = load_json(sab)
        stats["sa_skipped_unread"] = stats["sa"].get("skipped_unread")
    doc = {
        "window": [POSTS.get("start") or "", POSTS.get("end") or ""],
        "stats": stats,
        "articles": articles,
        "ambiguous": [f"{k} {v}" for k, v in AMBIG.items()],
    }
    op_path = os.path.join(ROOT, "onepagers.json")
    if not os.path.exists(op_path):
        op_path = os.path.join(EXAMPLES, "onepagers.json")
    op = load_json(op_path) if os.path.exists(op_path) else {}
    op.pop("_about", None)
    md, rows, ranked = render(doc, op, live=False)
    write_outputs(md, rows, ranked, out_path)
    if want_pdf:
        try_pdf(out_path)


def main():
    ap = argparse.ArgumentParser(description="Write the Screeny ranked report")
    ap.add_argument("--scored", default="", help="scored JSON (default: state/scored.json)")
    ap.add_argument("--onepagers", default="")
    ap.add_argument("--example", action="store_true", help="render examples/scored.json")
    ap.add_argument("--legacy", action="store_true", help="assemble from rerun/*.json and rerun/dispo.py")
    ap.add_argument("--out", default="")
    ap.add_argument("--prices", action="store_true", help="fill empty since-publish cells from Yahoo")
    ap.add_argument("--pdf", action="store_true")
    a = ap.parse_args()
    if a.example:
        scored_path = os.path.join(EXAMPLES, "scored.json")
        op_path = a.onepagers or os.path.join(EXAMPLES, "onepagers.json")
        out = a.out or os.path.join(CACHE, "example-REPORT.md")
    elif a.legacy:
        out = a.out or os.path.join(REPORTS, dt.date.today().isoformat(), "REPORT.md")
        legacy(out, a.pdf)
        return
    else:
        scored_path = a.scored or os.path.join(STATE, "scored.json")
        op_path = a.onepagers or os.path.join(STATE, "onepagers.json")
        out = a.out or os.path.join(REPORTS, dt.date.today().isoformat(), "REPORT.md")
    if not os.path.exists(scored_path):
        print(f"missing {scored_path}")
        print("Write state/scored.json after scoring, or pass --example.")
        sys.exit(2)
    doc = load_json(scored_path)
    op = load_json(op_path) if os.path.exists(op_path) else {}
    op.pop("_about", None)
    md, rows, ranked = render(doc, op, live=a.prices)
    write_outputs(md, rows, ranked, out)
    print(f"ranked={len(ranked)} scored_rows={len(rows)}")
    if a.pdf:
        try_pdf(out)


if __name__ == "__main__":
    main()
