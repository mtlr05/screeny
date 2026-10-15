#!/usr/bin/env python3
"""Propose source-list changes. Runs are on request, so rules use dates and run counts.

--plan refreshes state/source_stats.csv and writes a proposal file. It does not
edit config/sources.csv or config/sources_dormant_or_dead.csv.

--apply PROPOSAL applies only entries with approved set true.
Drops move the row onto the dormant list. Adds append a Substack row.

Seeking Alpha rows are not tracked and are never dropped or added here.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import CACHE, CONFIG, DORMANT, REPORTS, ROOT, SEEN, SOURCES, STATE, ensure

BAT = os.path.join(ROOT, "bat")
sys.path.insert(0, BAT)
import calc as batcalc
import pitches as batpitches

CAP = 600
BA_DROP = 30.0
BA_ADD = 50.0
MIN_PITCHES = 5
MIN_SCORED_FOR_TRIM = 3
SCORE_FLOOR = 4.5
FAILS_TO_DROP = 4
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
STATS_FIELDS = [
    "name",
    "type",
    "url",
    "last_post",
    "consecutive_failed_loads",
    "articles_scored",
    "avg_score_6m",
    "ba_2y",
    "ba_2y_n",
    "pitches_title",
    "pitches_body",
    "as_of",
    "last_sweep_file",
]
SOURCE_FIELDS = [
    "name",
    "type",
    "url",
    "feed_url",
    "custom_domain",
    "focus",
    "how_discovered",
    "feed_ok",
    "last_post",
    "posts_in_window",
    "status",
    "track_record",
]


def shift_months(day, months):
    y, m = day.year, day.month - months
    while m <= 0:
        m += 12
        y -= 1
    nxt = dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)
    last = (nxt - dt.timedelta(days=1)).day
    return dt.date(y, m, min(day.day, last))


def read_csv(path):
    if not path or not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def write_csv(path, fields, rows):
    ensure(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})
    os.replace(tmp, path)


def is_sa(row):
    t = (row.get("type") or "").lower()
    url = (row.get("url") or "").lower()
    return t == "seekingalpha" or "seekingalpha.com" in url


def host_of(url):
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def subdomain(url):
    host = host_of(url)
    if host.endswith(".substack.com"):
        return host[: -len(".substack.com")]
    return host


def scrub(text):
    return re.sub(r"\s{2,}", " ", EMAIL.sub("", text or "")).strip()


def load_seen_latest(path):
    latest = {}
    for row in read_csv(path)[1]:
        key = (row.get("source") or "").strip().lower().rstrip("/")
        day = (row.get("date") or "")[:10]
        if key and day and day > latest.get(key, ""):
            latest[key] = day
    return latest


def last_post_for(row, latest):
    keys = []
    url = (row.get("url") or "").rstrip("/")
    sub = subdomain(url)
    if sub:
        keys.append(sub.lower())
    if url:
        keys.append(url.lower())
        keys.append(host_of(url))
    name = (row.get("name") or "").strip().lower()
    if name:
        keys.append(name)
    dates = [(row.get("last_post") or "")[:10]]
    dates += [latest.get(k, "") for k in keys]
    dates = [d for d in dates if d]
    return max(dates) if dates else ""


def article_score(article):
    if article.get("score") not in (None, ""):
        return float(article["score"])
    sc = article.get("sc") or []
    return float(sum(float(x) for x in sc[:6]))


def load_articles(path):
    if not path or not os.path.exists(path):
        return []
    if path.endswith(".json"):
        doc = json.load(open(path, encoding="utf-8"))
        rows = doc.get("articles") if isinstance(doc, dict) else doc
        return rows or []
    out = []
    for row in read_csv(path)[1]:
        try:
            score = float(row["score"])
        except (KeyError, ValueError):
            continue
        out.append({"source": row.get("source") or "", "date": (row.get("date") or "")[:10], "score": score, "url": row.get("url") or ""})
    return out


def load_batting(path):
    if not path or not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


def _pitch_subs(key):
    subs = re.findall(r"([a-z0-9-]+)\.substack\.com", (key or "").lower())
    if subs:
        return subs
    token = re.split(r"[\s(]", (key or "").strip().lower())[0]
    return [token] if token else []


def _absorb_pitches(idx, mapping, replace):
    for key, rows in (mapping or {}).items():
        for sub in _pitch_subs(key):
            if replace or sub not in idx:
                idx[sub] = list(rows)
            else:
                idx[sub].extend(rows)


def pitch_index():
    """Subdomain -> pitches. Seeking Alpha lists are omitted.

    Hand-entered rows in bat/pitches.py are the fallback. A detected list in
    bat/pitches.json (each row tagged title or body) replaces that author.
    """
    idx = {}
    _absorb_pitches(idx, batpitches.SUB, replace=False)
    path = os.path.join(BAT, "pitches.json")
    if os.path.exists(path):
        try:
            saved = json.load(open(path, encoding="utf-8")).get("SUB") or {}
        except (OSError, json.JSONDecodeError):
            saved = {}
        tagged = {}
        for key, rows in saved.items():
            if any(batcalc.pitch_parts(row)[4] for row in rows or []):
                tagged[key] = rows
        _absorb_pitches(idx, tagged, replace=True)
    return idx


def method_counts(rows, today):
    """2-year-window pitches split by detection method. Blank when untagged."""
    if not rows or not any(batcalc.pitch_parts(row)[4] for row in rows):
        return None, None
    title = body = 0
    for row in batcalc.pitches_in_window(rows, "2y", today):
        method = batcalc.pitch_parts(row)[4]
        if method == "title":
            title += 1
        elif method == "body":
            body += 1
    return title, body


def batting_index(batting):
    idx = {}
    for key, val in (batting or {}).items():
        if "(sa)" in key.lower():
            continue
        idx[key.strip().lower()] = val
        for sub in re.findall(r"([a-z0-9-]+)\.substack\.com", key.lower()):
            idx[sub] = val
    return idx


def row_keys(row):
    keys = set()
    sub = subdomain(row.get("url") or "")
    if sub:
        keys.add(sub.lower())
    name = (row.get("name") or "").strip().lower()
    if name:
        keys.add(name)
    return keys


def label_hits(label, keys):
    lab = (label or "").strip().lower()
    if not lab or "(sa)" in lab or "seekingalpha.com" in lab:
        return False
    if lab in keys:
        return True
    for k in keys:
        if len(k) >= 4 and len(lab) >= 4 and (k in lab or lab in k):
            return True
    return False


def ba_for_sub(sub, pitches, batting_by_key, today, compute):
    """Return (pct or None, n or None). n is None when this author was not collected."""
    rec = batting_by_key.get(sub) or batting_by_key.get((sub or "").lower())
    if rec and isinstance(rec.get("summary"), dict) and "2y" in rec["summary"]:
        y2 = rec["summary"].get("2y")
        if not y2:
            return None, 0
        return round(float(y2["pct"]) * 100, 1), int(y2["n"])
    rows = pitches.get(sub)
    if rows is None:
        return None, None
    windowed = batcalc.pitches_in_window(rows, "2y", today)
    n = len(windowed)
    if compute and n:
        summary = batcalc.summarize(sub, rows, today=today)
        y2 = (summary.get("summary") or {}).get("2y")
        if not y2:
            return None, 0
        return round(float(y2["pct"]) * 100, 1), int(y2["n"])
    return None, n


def fmt_num(value, digits=1):
    if value is None or value == "":
        return ""
    return f"{float(value):.{digits}f}"


def build_stats(sources, seen_latest, articles, pitches, batting_by_key, prev, sweep, as_of, cutoff, compute, scores_loaded):
    by_url = {(r.get("url") or "").rstrip("/"): r for r in prev}
    sweep_id = ""
    attempted = set()
    failed = set()
    if sweep:
        sweep_id = sweep.get("_id") or ""
        attempted = {u.rstrip("/") for u in sweep.get("attempted") or []}
        failed = {u.rstrip("/") for u in sweep.get("failed") or []}
    scored = []
    for article in articles:
        url = article.get("url") or ""
        if "seekingalpha.com" in url.lower():
            continue
        day = (article.get("date") or "")[:10]
        if day and day < cutoff:
            continue
        if not day:
            continue
        try:
            score = article_score(article)
        except (TypeError, ValueError):
            continue
        scored.append((article.get("source") or "", score))

    rows = []
    for src in sources:
        if is_sa(src):
            continue
        url = (src.get("url") or "").rstrip("/")
        prev_row = by_url.get(url, {})
        fails = int(prev_row.get("consecutive_failed_loads") or 0)
        last_file = prev_row.get("last_sweep_file") or ""
        if sweep and attempted and url in attempted and last_file != sweep_id:
            fails = fails + 1 if url in failed else 0
            last_file = sweep_id
        keys = row_keys(src)
        mine = [s for label, s in scored if label_hits(label, keys)] if scores_loaded else []
        sub = subdomain(url)
        pct, n = ba_for_sub(sub, pitches, batting_by_key, as_of, compute)
        title_n, body_n = method_counts(pitches.get(sub) if sub else None, as_of)
        rows.append(
            {
                "name": src.get("name") or sub or url,
                "type": src.get("type") or "",
                "url": src.get("url") or "",
                "last_post": last_post_for(src, seen_latest),
                "consecutive_failed_loads": str(fails),
                "articles_scored": str(len(mine)) if scores_loaded else "",
                "avg_score_6m": f"{statistics.mean(mine):.2f}" if mine else "",
                "ba_2y": fmt_num(pct),
                "ba_2y_n": "" if n is None else str(n),
                "pitches_title": "" if title_n is None else str(title_n),
                "pitches_body": "" if body_n is None else str(body_n),
                "as_of": as_of.isoformat(),
                "last_sweep_file": last_file,
            }
        )
    rows.sort(key=lambda r: (r["name"].lower(), r["url"]))
    return rows


def high_scorers(sources, articles, cutoff):
    """Subdomains with at least one article scored >= 4.5 inside the window."""
    subs = set()
    details = {}
    keyed = [(row_keys(s), subdomain(s.get("url") or ""), s.get("name") or "") for s in sources if not is_sa(s) and (s.get("type") == "substack")]
    for article in articles:
        if "seekingalpha.com" in (article.get("url") or "").lower():
            continue
        day = (article.get("date") or "")[:10]
        if not day or day < cutoff:
            continue
        try:
            score = article_score(article)
        except (TypeError, ValueError):
            continue
        if score < SCORE_FLOOR:
            continue
        label = article.get("source") or ""
        for keys, sub, name in keyed:
            if sub and label_hits(label, keys):
                subs.add(sub)
                details[sub] = {"name": name, "score": score}
                break
    return subs, details


def load_crawl(path, seeds, do_crawl):
    if do_crawl and seeds:
        import crawl_sources

        return crawl_sources.crawl(sorted(seeds), seed_how="seed: author scored at least 4.5/6")
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {}


def consider_adds(crawl, seeds, known_subs, pitches, batting_by_key, as_of, compute):
    adds = []
    skipped = []
    declined = []
    for sub, info in (crawl or {}).items():
        how = info.get("how") or ""
        m = re.search(r"Substack recommendation from ([A-Za-z0-9-]+)", how)
        if not m or m.group(1) not in seeds:
            continue
        if sub in known_subs or sub in seeds:
            continue
        pct, n = ba_for_sub(sub, pitches, batting_by_key, as_of, compute)
        name = info.get("name") or sub
        numbers = {
            "subdomain": sub,
            "recommended_by": m.group(1),
            "ba_2y": pct,
            "ba_2y_n": n,
            "bar": f">{BA_ADD:g}% on >={MIN_PITCHES} pitches",
        }
        item = {
            "action": "add",
            "name": name,
            "url": f"https://{sub}.substack.com",
            "feed_url": f"https://{sub}.substack.com/feed",
            "custom_domain": info.get("custom") or "",
            "focus": scrub(info.get("hero") or ""),
            "approved": False,
            "numbers": numbers,
        }
        if n is None or n < MIN_PITCHES:
            item["reason"] = "skipped for now: fewer than 5 pitches in the 2-year window"
            item["reason_code"] = "few_pitches"
            skipped.append(item)
        elif pct is None:
            item["reason"] = "skipped for now: 2-year batting average has not been computed"
            item["reason_code"] = "ba_unknown"
            skipped.append(item)
        elif pct > BA_ADD:
            item["reason"] = f"2-year batting average {pct:g}% on {n} pitches (above 50%), recommended by {m.group(1)} who scored >= 4.5/6"
            item["reason_code"] = "ba_2y"
            adds.append(item)
        else:
            item["reason"] = f"not added: 2-year batting average {pct:g}% on {n} pitches is not above 50%"
            item["reason_code"] = "ba_below_bar"
            declined.append(item)
    return adds, skipped, declined


def propose(stats_rows, tracked, cutoff, cap):
    drops = []
    for row in stats_rows:
        reasons = []
        codes = []
        numbers = {
            "last_post": row["last_post"],
            "consecutive_failed_loads": int(row["consecutive_failed_loads"] or 0),
            "articles_scored": int(row["articles_scored"] or 0),
            "avg_score_6m": row["avg_score_6m"],
            "ba_2y": row["ba_2y"],
            "ba_2y_n": row["ba_2y_n"],
            "stale_before": cutoff,
        }
        n = int(row["ba_2y_n"]) if row["ba_2y_n"] != "" else None
        pct = float(row["ba_2y"]) if row["ba_2y"] != "" else None
        if pct is not None and n is not None and n >= MIN_PITCHES and pct < BA_DROP:
            codes.append("ba_2y")
            reasons.append(f"2-year batting average {pct:g}% on {n} pitches (under 30%)")
        if row["last_post"] and row["last_post"] < cutoff:
            codes.append("stale")
            reasons.append(f"no article published in 6 months (last post {row['last_post']}, before {cutoff})")
        fails = int(row["consecutive_failed_loads"] or 0)
        if fails >= FAILS_TO_DROP:
            codes.append("failed_loads")
            reasons.append(f"feed failed to load on {fails} consecutive runs")
        if not reasons:
            continue
        drops.append(
            {
                "action": "drop",
                "name": row["name"],
                "url": row["url"],
                "type": row["type"],
                "reason": "; ".join(reasons),
                "reason_codes": codes,
                "approved": False,
                "numbers": numbers,
            }
        )
    drop_urls = {d["url"].rstrip("/") for d in drops}
    projected = tracked - len(drop_urls)
    trims = []
    if projected > cap:
        eligible = []
        for row in stats_rows:
            url = row["url"].rstrip("/")
            if url in drop_urls:
                continue
            n = int(row["articles_scored"] or 0)
            if n < MIN_SCORED_FOR_TRIM or row["avg_score_6m"] == "":
                continue
            eligible.append(row)
        eligible.sort(key=lambda r: (float(r["avg_score_6m"]), r["name"].lower()))
        for row in eligible:
            if projected <= cap:
                break
            trims.append(
                {
                    "action": "drop",
                    "name": row["name"],
                    "url": row["url"],
                    "type": row["type"],
                    "reason": f"active list would be {projected} sources, over the {cap} cap; lowest 6-month average among sources with at least {MIN_SCORED_FOR_TRIM} scored articles",
                    "reason_codes": ["cap"],
                    "approved": False,
                    "numbers": {
                        "avg_score_6m": row["avg_score_6m"],
                        "articles_scored": int(row["articles_scored"] or 0),
                        "active_before_trim": tracked,
                        "cap": cap,
                    },
                }
            )
            projected -= 1
            drop_urls.add(row["url"].rstrip("/"))
    return drops + trims


def load_sweep(path):
    if not path or not os.path.exists(path):
        return None
    doc = json.load(open(path, encoding="utf-8"))
    doc["_id"] = os.path.abspath(path)
    return doc


def latest_sweep(report_dir):
    paths = []
    if not os.path.isdir(report_dir):
        return ""
    for name in os.listdir(report_dir):
        if name.startswith("stats_") and name.endswith(".json"):
            paths.append(os.path.join(report_dir, name))
    if not paths:
        return ""
    return max(paths, key=os.path.getmtime)


def known_subdomains(rows):
    out = set()
    for row in rows:
        sub = subdomain(row.get("url") or "")
        if sub:
            out.add(sub)
    return out


def plan(args):
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    cutoff = shift_months(as_of, 6).isoformat()
    fields, sources = read_csv(args.sources)
    if not sources:
        print("no sources in", args.sources)
        sys.exit(2)
    sa_rows = [r for r in sources if is_sa(r)]
    tracked_rows = [r for r in sources if not is_sa(r)]
    _, prev = read_csv(args.stats)
    seen_latest = load_seen_latest(args.seen)
    score_path = args.scored
    if not score_path and os.path.exists(os.path.join(STATE, "scored.json")):
        score_path = os.path.join(STATE, "scored.json")
    articles = load_articles(score_path)
    batting = load_batting(args.batting)
    pitches = pitch_index()
    bidx = batting_index(batting)
    sweep_path = args.sweep_stats or latest_sweep(args.reports)
    sweep = load_sweep(sweep_path) if sweep_path else None
    if sweep and not sweep.get("attempted"):
        sweep = None
        sweep_note = f"{sweep_path} has no attempted list, so fail counts were not changed"
    elif sweep:
        sweep_note = sweep_path
    else:
        sweep_note = "no sweep stats file"
    stats_rows = build_stats(
        tracked_rows,
        seen_latest,
        articles,
        pitches,
        bidx,
        prev,
        sweep,
        as_of,
        cutoff,
        args.compute_ba,
        scores_loaded=bool(score_path),
    )
    write_csv(args.stats, STATS_FIELDS, stats_rows)
    seeds, seed_details = high_scorers(tracked_rows, articles, cutoff)
    _, dormant = read_csv(args.dormant)
    known = known_subdomains(sources) | known_subdomains(dormant)
    crawl = load_crawl(args.crawl_cache, seeds, args.crawl)
    adds, skipped, declined = consider_adds(crawl, seeds, known, pitches, bidx, as_of, args.compute_ba)
    # Count adds toward the cap. Rule drops (batting, stale, failed loads) come off first.
    all_drops = propose(stats_rows, len(tracked_rows) + len(adds), cutoff, args.cap)
    base_drops = [d for d in all_drops if "cap" not in d["reason_codes"]]
    cap_drops = [d for d in all_drops if d["reason_codes"] == ["cap"]]
    proposals = all_drops + adds
    out_path = args.out or os.path.join(args.reports, f"source_upkeep_{as_of.isoformat()}.json")
    doc = {
        "as_of": as_of.isoformat(),
        "cutoff_6m": cutoff,
        "cap": args.cap,
        "tracked_active": len(tracked_rows),
        "seeking_alpha_not_tracked": len(sa_rows),
        "score_file": score_path or "",
        "batting_file": args.batting if os.path.exists(args.batting) else "",
        "sweep_stats": sweep_note,
        "high_scorers": seed_details,
        "rules": {
            "drop_ba": f"2-year batting average < {BA_DROP:g}% on >= {MIN_PITCHES} pitches",
            "drop_stale": "no article published in 6 months (known last-post date only)",
            "drop_fails": f"feed failed to load on {FAILS_TO_DROP} consecutive runs",
            "no_drop_for": "producing no scored articles",
            "add": f"Substack recommendation of an author who scored >= {SCORE_FLOOR}/6, and the candidate's 2-year batting average > {BA_ADD:g}% on >= {MIN_PITCHES} pitches",
            "cap": f"only when active tracked sources would exceed {args.cap}, trim lowest 6-month average among sources with >= {MIN_SCORED_FOR_TRIM} scored articles",
            "seeking_alpha": "not tracked; the weekly Seeking Alpha pull is unchanged",
        },
        "proposals": proposals,
        "skipped": skipped,
        "not_added": declined,
    }
    ensure(os.path.dirname(out_path) or ".")
    json.dump(doc, open(out_path, "w", encoding="utf-8"), indent=2)
    print(f"Source upkeep plan {as_of.isoformat()}")
    print(f"Tracked active sources: {len(tracked_rows)} (Seeking Alpha excluded: {len(sa_rows)}). Cap: {args.cap}.")
    print(f"Stats: {args.stats}")
    print(f"Drops proposed: {len(base_drops) + len(cap_drops)}")
    print(f"Adds proposed: {len(adds)}")
    print(f"Candidates skipped (<{MIN_PITCHES} pitches or batting average not computed): {len(skipped)}")
    print(f"Recommendations not added (batting average at or under {BA_ADD:g}%): {len(declined)}")
    if len(tracked_rows) + len(adds) - len(base_drops) <= args.cap:
        print("Cap trim: not needed.")
    else:
        print(f"Cap trim proposed: {len(cap_drops)}")
    print(f"Sweep stats: {sweep_note}")
    if not score_path:
        print("No scored-article file. articles_scored and avg_score_6m stay empty until state/scored.json exists.")
    if not os.path.exists(args.batting):
        print("No state/batting.json. Pitch counts come from bat/pitches.py; percentages stay blank until bat/calc.py has run. A blank percentage is not a drop and not an add.")
    tagged = sum(1 for row in stats_rows if row.get("pitches_title") or row.get("pitches_body"))
    print(f"Pitch methods: title/body counts filled for {tagged} sources. Blank means bat/pitches.py has not detected that author yet.")
    if not seeds:
        print("No Substack author with a score >= 4.5/6 in the score file, so no recommendation candidates were considered.")
    elif not crawl:
        print("High-scoring authors are present, but there is no crawl cache. Re-run with --crawl to fetch their Substack recommendations.")
    for item in proposals:
        nums = ", ".join(f"{k}={v}" for k, v in item["numbers"].items() if v not in ("", None))
        print(f"- {item['action'].upper()} {item['name']}: {item['reason']} ({nums})")
    print(out_path)
    print("Source lists were not changed. Set approved to true on the entries to keep, then:")
    print(f"  python3 scripts/source_upkeep.py --apply {out_path}")
    return out_path


def approved(item):
    v = item.get("approved")
    return v is True or str(v).strip().lower() in {"1", "true", "yes", "y"}


def apply_proposal(path, sources_path, dormant_path):
    doc = json.load(open(path, encoding="utf-8"))
    chosen = [p for p in doc.get("proposals") or [] if approved(p)]
    if not chosen:
        print("No approved entries. Source lists were not changed.")
        return
    fields, sources = read_csv(sources_path)
    dfields, dormant = read_csv(dormant_path)
    fields = fields or SOURCE_FIELDS
    dfields = dfields or fields
    by_url = {(r.get("url") or "").rstrip("/"): r for r in sources}
    dormant_urls = {(r.get("url") or "").rstrip("/") for r in dormant}
    remove = set()
    new_rows = []
    dropped = []
    added = []
    for item in chosen:
        url = (item.get("url") or "").rstrip("/")
        if is_sa({"type": item.get("type"), "url": url}):
            print("skip Seeking Alpha", item.get("name"))
            continue
        if item.get("action") == "drop":
            row = by_url.get(url)
            if not row:
                print("not in active list:", item.get("name"), url)
                continue
            moved = dict(row)
            moved["status"] = "dormant"
            note = "upkeep: " + scrub(item.get("reason") or "")
            prev = (moved.get("track_record") or "").strip()
            moved["track_record"] = (prev + "; " if prev else "") + note
            if url not in dormant_urls:
                dormant.append(moved)
                dormant_urls.add(url)
            remove.add(url)
            dropped.append(moved.get("name") or url)
        elif item.get("action") == "add":
            if url in by_url or url in dormant_urls:
                print("already listed:", item.get("name"), url)
                continue
            sub = subdomain(url)
            nums = item.get("numbers") or {}
            pct = nums.get("ba_2y")
            n = nums.get("ba_2y_n")
            row = {k: "" for k in fields}
            row.update(
                {
                    "name": scrub(item.get("name") or sub),
                    "type": "substack",
                    "url": item.get("url") or f"https://{sub}.substack.com",
                    "feed_url": item.get("feed_url") or f"https://{sub}.substack.com/feed",
                    "custom_domain": item.get("custom_domain") or "",
                    "focus": scrub(item.get("focus") or ""),
                    "how_discovered": scrub(
                        f"Substack recommendation from {nums.get('recommended_by', '')}; 2y batting average {pct}% on {n} pitches"
                    ),
                    "status": "active",
                    "track_record": f"ba_2y={pct}; n={n}",
                }
            )
            new_rows.append(row)
            by_url[url] = row
            added.append(row["name"])
        else:
            print("unknown action", item.get("action"), item.get("name"))
    kept = [r for r in sources if (r.get("url") or "").rstrip("/") not in remove]
    write_csv(sources_path, fields, kept + new_rows)
    write_csv(dormant_path, dfields, dormant)
    print(f"Dropped {len(dropped)}: {', '.join(dropped) if dropped else 'none'}")
    print(f"Added {len(added)}: {', '.join(added) if added else 'none'}")


def main():
    ap = argparse.ArgumentParser(description="Plan or apply source-list upkeep")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", default="", metavar="PROPOSAL")
    ap.add_argument("--sources", default=SOURCES)
    ap.add_argument("--dormant", default=DORMANT)
    ap.add_argument("--stats", default=os.path.join(STATE, "source_stats.csv"))
    ap.add_argument("--seen", default=SEEN)
    ap.add_argument("--scored", default="")
    ap.add_argument("--batting", default=os.path.join(STATE, "batting.json"))
    ap.add_argument("--crawl-cache", default=os.path.join(CACHE, "crawl.json"))
    ap.add_argument("--reports", default=REPORTS)
    ap.add_argument("--sweep-stats", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--as-of", default="")
    ap.add_argument("--cap", type=int, default=CAP)
    ap.add_argument("--crawl", action="store_true", help="fetch Substack recommendations of authors who scored >= 4.5")
    ap.add_argument("--compute-ba", action="store_true", help="call bat/calc.py for authors with saved pitches")
    args = ap.parse_args()
    if args.plan and args.apply:
        print("Pass only one of --plan or --apply")
        sys.exit(2)
    if args.apply:
        apply_proposal(args.apply, args.sources, args.dormant)
    elif args.plan:
        plan(args)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
