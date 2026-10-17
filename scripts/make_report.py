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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bat"))
from _paths import CACHE, EXAMPLES, REPORTS, RERUN, ROOT, SEEN, SOURCES, STATE, ensure
import calc as batcalc
import weekly_sweep

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


def _chance(summary):
    if not summary:
        return ""
    if summary.get("p_lt") not in (None, ""):
        return summary["p_lt"]
    return batcalc.p_lt_hits(summary.get("hits") or 0, summary.get("n") or 0)


def fmt_bat(bat):
    def one(w):
        x = (bat.get("summary") or {}).get(w)
        if not x:
            return f"{w} n/a"
        line = f"{w} {x['hits']}/{x['n']} = {x['pct']*100:.0f}% (med excess {x['median_excess']*100:+.0f} pts)"
        if w == "2y":
            line += f", P(fewer hits by chance) {_chance(x)}"
        return line

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
        return f"{y2['hits']}/{y2['n']} = {y2['pct']*100:.0f}% (p_lt {_chance(y2)})"
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
    rows.sort(key=lambda ax: (-float(_chance(ax[1]) or 0), ax[0]))
    return rows[:n]


def _host_token(value):
    text = (value or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    if text.endswith(".substack.com"):
        text = text[: -len(".substack.com")]
    return text


def _num(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pct_label(row, hits, n):
    stored = _num(row.get("ba_2y"))
    if stored is None:
        frac = _num(row.get("ba2y_pct"))
        stored = None if frac is None else frac * 100
    if stored is None and n:
        stored = 100.0 * hits / n
    if stored is None:
        return ""
    if abs(stored - round(stored)) < 0.05:
        return f"{round(stored):.0f}%"
    return f"{stored:.1f}%"


def top_record_authors(stats_path=None, sources_path=None):
    """Active sources whose stored 2y chance is at least 0.5 on at least 2 pitches.

    Read at report time from state/source_stats.csv, limited to URLs still in
    config/sources.csv, so a newly added author appears once their stats are stored.
    """
    stats_path = stats_path or os.path.join(STATE, "source_stats.csv")
    sources_path = sources_path or SOURCES
    if not os.path.exists(stats_path):
        return []
    active = None
    if sources_path and os.path.exists(sources_path):
        with open(sources_path, newline="", encoding="utf-8") as f:
            active = {(row.get("url") or "").rstrip("/") for row in csv.DictReader(f)}
    found = []
    with open(stats_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").rstrip("/")
            if active is not None and url not in active:
                continue
            n = _num(row.get("ba2y_n"))
            if n is None:
                n = _num(row.get("ba_2y_n"))
            chance = _num(row.get("ba2y_p_lt_hits"))
            hits = _num(row.get("ba2y_hits"))
            if n is None or chance is None or n < 2 or chance < 0.5:
                continue
            hits = 0 if hits is None else int(hits)
            n = int(n)
            found.append(
                {
                    "name": row.get("name") or _host_token(url),
                    "url": url,
                    "sub": _host_token(url),
                    "hits": hits,
                    "n": n,
                    "pct": _pct_label(row, hits, n),
                    "p": str(row.get("ba2y_p_lt_hits")).strip(),
                    "chance": chance,
                }
            )
    found.sort(key=lambda row: (-row["chance"], row["name"].lower()))
    return found


def _article_owner(url, source, authors):
    url_sub = _host_token(url)
    if url_sub:
        for author in authors:
            if url_sub == author["sub"]:
                return author
    src_sub = _host_token(source)
    label = (source or "").strip().lower()
    for author in authors:
        if src_sub and (src_sub == author["sub"] or src_sub == author["name"].lower()):
            return author
        if label and label == author["name"].lower():
            return author
    return None


def _md_cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def top_record_lines(doc, authors, seen_path=None):
    """Markdown for every in-window article by a top-record author."""
    window = doc.get("window") or ["", ""]
    start = (window[0] or "")[:10] if window else ""
    end = (window[1] or "")[:10] if len(window) > 1 else ""
    scores = {}
    for article in doc.get("articles") or []:
        url = (article.get("url") or "").rstrip("/")
        sc = article.get("sc") or []
        if url and len(sc) >= 6:
            scores[url] = tot(sc[:6])
    posts = {}

    def add(url, title, date, source):
        day = (date or "")[:10]
        if not url or not day:
            return
        if start and day < start:
            return
        if end and day > end:
            return
        owner = _article_owner(url, source, authors)
        if not owner:
            return
        key = url.rstrip("/")
        prev = posts.get(key)
        score = scores.get(key)
        if prev and prev.get("score") is not None and score is None:
            score = prev["score"]
        posts[key] = {
            "author": owner["name"],
            "date": day,
            "title": title or url,
            "url": url,
            "score": score if score is not None else (prev or {}).get("score"),
        }

    seen_path = seen_path or SEEN
    if seen_path and os.path.exists(seen_path):
        with open(seen_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                add(row.get("url") or "", row.get("title") or "", row.get("date") or "", row.get("source") or "")
    for article in doc.get("articles") or []:
        add(article.get("url") or "", article.get("title") or "", article.get("date") or "", article.get("source") or "")
    by_author = {author["name"]: [] for author in authors}
    for post in posts.values():
        by_author.setdefault(post["author"], []).append(post)
    lines = [
        "## Articles from top-record authors",
        "",
        "Every article in this window from an author whose stored 2-year record has at least 2 pitches and `p_lt_hits_by_chance` (`ba2y_p_lt_hits`) of 0.5 or higher. The author list is read from `state/source_stats.csv` when the report is written, so it follows the source list. Hits/pitches, batting average, and that chance are shown next to the author. A score is shown only when the article was scored.",
        "",
    ]
    if not authors:
        lines.append("No author currently meets that bar.")
        lines.append("")
        return lines
    for author in authors:
        lines.append(f"### {author['name']} ({author['hits']}/{author['n']} = {author['pct']}, p_lt {author['p']})")
        lines.append("")
        rows = by_author.get(author["name"]) or []
        rows.sort(key=lambda row: row["title"].lower())
        rows.sort(key=lambda row: row["date"], reverse=True)
        if not rows:
            lines.append("No articles in this window.")
            lines.append("")
            continue
        lines.append("| Date | Article | Score |")
        lines.append("|---|---|---|")
        for row in rows:
            score = "" if row["score"] is None else f"{row['score']:g}"
            title = _md_cell(row["title"])
            lines.append(f"| {row['date']} | [{title}]({row['url']}) | {score} |")
        lines.append("")
    return lines


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
    st = weekly_sweep.apply_screen_counts(doc.get("stats") or {})
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
    A(f"- **Articles sourced (posts in window):** {st.get('sourced', 0):,}")
    if st.get("new_since_last_run") is not None:
        A(f"- **New since last run:** {st.get('new_since_last_run'):,}")
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
        A("| # | Author | Hits / N | Avg | P(fewer hits by chance) | Median excess | Best | Worst |")
        A("|---|---|---|---|---|---|---|---|")
        got = top_bat(authors, batting, window_name)
        for i, (a, x) in enumerate(got, 1):
            A(
                f"| {i} | {a} | {x['hits']}/{x['n']} | {x['pct']*100:.0f}% | {_chance(x)} | {x['median_excess']*100:+.0f} pts | {x['best']} | {x['worst']} |"
            )
        if not got:
            A("| — | none with ≥5 pitches | | | | | | |")
        A("")
    A("## Next six (ranks 16–21)")
    A("")
    A("| # | Ticker | Score /6 | Article | Source | Below full credit |")
    A("|---|---|---|---|---|---|")
    for i, r in enumerate(near, 16):
        A(f"| {i} | {r['sym']} | {r['score']:g} | [{r['title']}]({r['url']}) | {r['source']} | {miss(r['sc'])} |")
    A("")
    for line in top_record_lines(doc, top_record_authors()):
        A(line)
    A("## Caveats")
    A("")
    run_notes = {}
    notes_path = os.path.join(STATE, "run_notes.json")
    if os.path.exists(notes_path):
        try:
            run_notes = json.load(open(notes_path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_notes = {}
    price_source = run_notes.get("price_source") or "not recorded"
    ceo_source = run_notes.get("ceo_stake_source") or "from the article only"
    A(f'- Prices: {price_source}. "Since publish" uses the first close on or after the publish date when a price source was recorded.')
    amb_text = doc.get("ambiguous_text")
    amb = doc.get("ambiguous") or []
    shown = amb_text if amb_text else ("; ".join(amb) if amb else "none recorded")
    A("- Long-disclosure ambiguous (dropped): " + shown + ".")
    A(f"- CEO stakes: {ceo_source}. If the article and any cited filing do not state the stake, criterion 3 is 0 and the note says not stated.")
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
        notes = r.get("notes") or {}
        if not o and not any(notes.get("c%d" % k) for k in range(1, 7)):
            A("_One-pager not yet written for this name; add it to onepagers.json or notes.c1–c6 in scored.json._")
            A("")
            continue
        for k, (lab, v) in enumerate(zip(CN, r["sc"]), 1):
            evidence = notes.get("c%d" % k) or (o or {}).get("c%d" % k) or "not recorded"
            if k == 3 and evidence == "not recorded":
                evidence = "not stated"
            A(f"{k}. **{lab}: {v:g}.** {evidence}")
        if notes.get("return_formula"):
            A("")
            A(f"Return formula: {notes['return_formula']}")
        A("")
        A("**Red flags (reported, not scored):**")
        for flag in (o or {}).get("flags") or []:
            A(f"- {flag}")
        if (o or {}).get("thin"):
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
        A(f"- **Articles sourced (posts in window):** {sourced:,}")
        if st.get("new_since_last_run") is not None:
            A(f"- **New since last run:** {st.get('new_since_last_run'):,}")
        for k, v in sorted((st.get("by_type") or {}).items(), key=lambda kv: -kv[1]):
            A(f"  - {k}: {v:,}")
        unr = st.get("unreachable") or []
        if unr:
            A(f"  - Sources that could not be read: {len(unr)} (" + "; ".join(unr) + ")")
        A(f"- **Passed screening:** {st.get('passed', st.get('scored', len(rows)))} articles ({st.get('tickers', len({r['sym'] for r in rows}))} tickers)")
        triage = st.get("dropped") or {}
        if triage:
            A("- **Substack triage drops (counted from the screen file):**")
            for k, v in triage.items():
                A(f"  - {k}: {v:,}")
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
            unread = sa.get("unread") or []
            if unread:
                tickers = ", ".join(item.get("ticker") or item.get("id") or "" for item in unread)
                A(f"- **Not read (SA):** {len(unread)} ({tickers})")
            elif run_notes.get("sa_pull_complete") is False:
                A("- **Not read (SA):** the pull stopped before every candidate was read. See state/sa_breakdown.json.")
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
    """Write REPORT.pdf from the same Markdown, including Articles from top-record authors."""
    try:
        import markdown
        import weasyprint
    except Exception as e:
        print("PDF skipped (optional markdown/weasyprint not installed):", e)
        return
    source = open(md_path, encoding="utf-8").read()
    h = markdown.markdown(source, extensions=["tables"])
    heading = "Articles from top-record authors"
    if heading in source and heading not in h:
        print(f"PDF not written: the Markdown has {heading!r} but the HTML conversion dropped it")
        sys.exit(1)
    css = "@page{size:Letter landscape;margin:1.4cm} body{font-family:sans-serif;font-size:9.5pt} table{border-collapse:collapse;font-size:8pt} td,th{border:1px solid #bbb;padding:3px} .pb{page-break-before:always} h2,h3{break-after:avoid} h3{margin-top:0} tr{break-inside:avoid} a{color:#1a4fa0}"
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
