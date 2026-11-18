#!/usr/bin/env python3
"""Offline checks for the sweep window and the Substack content screen. No network."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weekly_sweep

PITCH_TITLES = [
    "Now Vertical: A data and AI services company that grew by acquisition",
    "Reckon Software - Phase 1: Lie Detection & ROIC",
    "Reckon Software - Phase 1: Lie Detection &amp; ROIC",
    "Flerie AB's fungal bull case",
    "Primary Energy - it's for Sale",
    "Domino's Has a Problem That Doesn't Show Up in Its Accounts",
]


def _post(url, title, audience="everyone", subtitle=""):
    return {
        "url": url,
        "sub": "https://ex.substack.com",
        "title": title,
        "subtitle": subtitle,
        "audience": audience,
        "date": "2026-10-16",
        "wc": 100,
    }


def test_in_window_sourced_count():
    res = [
        ("https://a.substack.com", [
            {"url": "https://a.substack.com/p/one", "title": "One", "subtitle": "", "audience": "everyone"},
            {"url": "https://a.substack.com/p/two", "title": "Weekly roundup", "subtitle": "", "audience": "everyone"},
        ]),
        ("https://b.substack.com", None),
        ("https://c.substack.com", [
            {"url": "https://a.substack.com/p/one", "title": "One", "subtitle": "", "audience": "everyone"},
            {"url": "https://c.substack.com/p/three", "title": "Paid", "subtitle": "", "audience": "only_paid"},
        ]),
    ]
    window = weekly_sweep.posts_in_window(res)
    assert len(window) == 3, len(window)
    seen = {"https://a.substack.com/p/one"}
    new = [post for post in window if post["url"] not in seen]
    assert len(new) == 2
    dropped = weekly_sweep.drop_counts(window)
    assert dropped["not a single-stock pitch (recap/macro/list)"] == 1
    assert dropped["paywalled"] == 1
    assert "not a single-stock pitch (no pitch signal in title)" not in dropped
    print("in-window sourced count ok", len(window), "new", len(new))


def test_pitch_titles_stay_and_recap_drops():
    for title in PITCH_TITLES:
        post = _post("https://ex.substack.com/p/idea", title)
        assert weekly_sweep.title_drop_reason(post) == "", title
        assert weekly_sweep.content_drop_reason(title, "") == "", title
    for title in (
        "Charter Communications: still a rollup",
        "The newsletter company grew by acquisition",
        "Recapitalization of Acme",
    ):
        assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/ok", title)) == "", title
    recap = _post("https://ex.substack.com/p/recap", "Weekly roundup")
    assert weekly_sweep.title_drop_reason(recap) == "not a single-stock pitch (recap/macro/list)"
    missing = _post("https://ex.substack.com/p/none", "Acme Corp: one business")
    missing["audience"] = None
    assert weekly_sweep.title_drop_reason(missing) == "paywalled"
    backlog = {"url": "https://ex.substack.com/p/bl", "title": "Acme Corp: one business"}
    assert weekly_sweep.title_drop_reason(backlog) == ""
    posts = [_post(f"https://ex.substack.com/p/idea-{i}", title) for i, title in enumerate(PITCH_TITLES)]
    posts.append(_post("https://ex.substack.com/p/recap", "Weekly roundup"))
    posts.append(_post("https://ex.substack.com/p/paid", "A real pitch", audience="only_paid"))
    posts.append(_post("https://ex.substack.com/p/old", "Old Pitch Inc: still one company"))
    rows, cand = weekly_sweep.screen_posts(posts, {"https://ex.substack.com/p/old"}, fetch=lambda post: "")
    kept_titles = {row["title"] for row in rows if row["decision"] == "keep"}
    assert kept_titles == set(PITCH_TITLES), kept_titles
    assert [post["title"] for post in cand] == PITCH_TITLES
    assert any(row["decision"] == "drop" and "recap/macro/list" in row["reason"] for row in rows)
    assert any(row["decision"] == "drop" and row["reason"] == "paywalled" for row in rows)
    assert any(row["decision"] == "seen" and row["reason"] == "already swept" for row in rows)
    for row in rows:
        assert row["url"] and row["title"] and row["decision"] and row["reason"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "substack_screen_2026-10-16.csv")
        weekly_sweep.write_screen(path, rows)
        dropped = weekly_sweep.dropped_from_screen(path)
        assert dropped["not a single-stock pitch (recap/macro/list)"] == 1
        assert dropped["paywalled"] == 1
        assert sum(dropped.values()) == 2
        stats = weekly_sweep.apply_screen_counts({"substack_screen": path, "dropped": {"stale": 9}})
        assert stats["dropped"] == dropped
        assert "stale" not in stats["dropped"]
    print("pitch titles stay; recap still drops")


def test_macro_phrase_and_single_listing():
    arrow = "A 10%+ Portfolio Position. Multiple Catalysts. Our Best Macro Idea for the Next 6 Months?"
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/arrow", arrow)) == ""
    body = "Arrow Exploration is our third largest position. We are long the shares."
    assert weekly_sweep.content_drop_reason(arrow, body) == ""
    rows, cand = weekly_sweep.screen_posts(
        [_post("https://ex.substack.com/p/arrow", arrow)],
        set(),
        fetch=lambda post: body,
    )
    assert rows[0]["decision"] == "keep", rows[0]
    assert [post["title"] for post in cand] == [arrow]
    for title in (
        "Weekly Macro Roundup",
        "Q4 2026 Macro Outlook: growth, rates, and positioning",
    ):
        assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/macro", title)) == (
            "not a single-stock pitch (recap/macro/list)"
        ), title
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/one", "Weekly roundup", subtitle="AXL.V")) == ""
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/one", "Macro update $AXL")) == ""
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/one", "Weekly roundup (TSX: AXL)")) == ""
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/one", "Weekly roundup NYSE")) == ""
    assert weekly_sweep.title_drop_reason(_post("https://ex.substack.com/p/two", "Weekly roundup $AAA $MSFT")) == (
        "not a single-stock pitch (recap/macro/list)"
    )
    paid = _post("https://ex.substack.com/p/paid", "Weekly roundup AXL.V", audience="only_paid")
    assert weekly_sweep.title_drop_reason(paid) == "paywalled"
    print("macro phrase and single listing ok")


def test_content_screen_drops_only_clear_cases():
    assert weekly_sweep.content_drop_reason("Acme Corp", "I am short the stock.") == "author short"
    assert weekly_sweep.content_drop_reason("Acme Corp", "Recommendation: Hold. I do not own it.") == "author hold"
    assert weekly_sweep.content_drop_reason("Acme Corp", "Recommendation: Hold. I own shares.") == ""
    assert "book review" in weekly_sweep.content_drop_reason(
        "Book review: a history of markets",
        "This book review covers a memoir about the economy and is not about one listed company.",
    )
    assert "multi-stock" in weekly_sweep.content_drop_reason("5 stocks to buy", "Here are five names.")
    macro = "This note is about the economy and interest rates. " * 12
    assert weekly_sweep.content_drop_reason("The Fed and inflation", macro) == "not a single-stock pitch (macro/general essay)"
    essay = "This is a general essay. It is not about a listed company. " * 8
    assert "no identifiable listed company" in weekly_sweep.content_drop_reason("Some thoughts", essay)
    vague = "Something changed last quarter and I am still working through it."
    assert weekly_sweep.content_drop_reason("A note", vague) == ""
    assert weekly_sweep.content_drop_reason(
        "Now Vertical: A data and AI services company that grew by acquisition",
        "The business grew by buying smaller firms.",
    ) == ""
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def _ok(url, headers, timeout):
        words = " ".join(["alpha"] * 1600)
        return _Resp({"body_html": f"<p>{words}</p>"})

    def _boom(url, headers, timeout):
        raise OSError("offline")

    with tempfile.TemporaryDirectory() as tmp:
        post = _post("https://ex.substack.com/p/slug", "Acme Corp")
        text = weekly_sweep.fetch_body(post, {}, getter=_ok, store_dir=tmp)
        assert len(text.split()) == 1500, len(text.split())
        missing = _post("https://ex.substack.com/p/other", "Other Corp")
        assert weekly_sweep.fetch_body(missing, {}, getter=_boom, store_dir=tmp) == ""
    print("content screen ok")


def test_report_drop_counts_come_from_the_screen_file():
    import make_report

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "substack_screen_2026-10-16.csv")
        weekly_sweep.write_screen(
            path,
            [
                {
                    "url": "https://ex.substack.com/p/recap",
                    "title": "Weekly roundup",
                    "decision": "drop",
                    "reason": "not a single-stock pitch (recap/macro/list)",
                },
                {
                    "url": "https://ex.substack.com/p/now",
                    "title": "Now Vertical: A data and AI services company that grew by acquisition",
                    "decision": "keep",
                    "reason": "kept (single-stock pitch or unclear)",
                },
            ],
        )
        doc = {
            "window": ["2026-10-01", "2026-10-16"],
            "stats": {"sourced": 2, "new_since_last_run": 2, "substack_screen": path, "dropped": {"stale": 4}},
            "articles": [],
        }
        md, _rows, _ranked = make_report.render(doc, {}, live=False)
    assert "not a single-stock pitch (recap/macro/list): 1" in md
    assert "stale" not in md
    print("report counts come from the screen file")


def test_old_six_point_scores_stay_marked_out_of_6():
    import make_report
    import source_upkeep

    old = {"sc": [1, 1, 1, 0.75, 0.5, 1]}
    got = make_report.normalize(old)
    assert got["sc"] == [1, 1, 1, 0.75, 0, 0.5, 1]
    assert got["score_out_of"] == 6
    assert got["score"] == 5.25
    new = {"sc": [1, 1, 0, 0.5, 0.75, 1, 1]}
    got = make_report.normalize(new)
    assert got["score_out_of"] == 7
    assert got["score"] == 5.25
    assert got["sc"][3] == 0.5 and got["sc"][4] == 0.75
    assert source_upkeep.clears_recommend_bar(4.5, 6)
    assert not source_upkeep.clears_recommend_bar(4.5, 7)
    assert source_upkeep.clears_recommend_bar(5.25, 7)
    assert source_upkeep.on_seven_point_scale(4.5, 6) == 5.25
    print("old totals stay out of 6; the add bar is 5.25/7")


def test_fetch_body_reuses_stored_text():
    post = _post("https://ex.substack.com/p/slug", "Acme Corp")

    class _Resp:
        def json(self):
            return {"body_html": "<p>" + " ".join(["beta"] * 30) + "</p>"}

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "slug.txt")
        open(path, "w", encoding="utf-8").write(" ".join(["alpha"] * 40))

        def boom(*_args, **_kwargs):
            raise AssertionError("stored text should be reused")

        text = weekly_sweep.fetch_body(post, {}, getter=boom, store_dir=tmp)
        assert text.split()[0] == "alpha"
        open(path, "w", encoding="utf-8").write("Press & Hold to confirm you are human")
        calls = []

        def fetch(*_args, **_kwargs):
            calls.append(1)
            return _Resp()

        text = weekly_sweep.fetch_body(post, {}, getter=fetch, store_dir=tmp)
        assert calls == [1]
        assert "beta" in text.split()
        calls.clear()
        text = weekly_sweep.fetch_body(post, {}, getter=boom, store_dir=tmp)
        assert "beta" in text.split()
        assert calls == []
    print("stored body is reused; a bot-check page is fetched again")


def test_shared_store_copies_into_fulltext():
    import text_store

    post = _post("https://ex.substack.com/p/shared-slug", "Acme Corp")
    previous = os.environ.get("SCREENY_TEXT_STORE")
    old_fulltext = weekly_sweep.FULLTEXT
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SCREENY_TEXT_STORE"] = os.path.join(tmp, "store")
        local = os.path.join(tmp, "fulltext")
        os.makedirs(local)
        weekly_sweep.FULLTEXT = local
        try:
            text_store.publish("shared-slug.txt", " ".join(["gamma"] * 30))

            def boom(*_args, **_kwargs):
                raise AssertionError("shared store should fill fulltext")

            text = weekly_sweep.fetch_body(post, {}, getter=boom)
            assert text.split()[0] == "gamma"
            assert os.path.isfile(os.path.join(local, "shared-slug.txt"))
        finally:
            weekly_sweep.FULLTEXT = old_fulltext
            if previous is None:
                os.environ.pop("SCREENY_TEXT_STORE", None)
            else:
                os.environ["SCREENY_TEXT_STORE"] = previous
    print("shared store copies into fulltext")


def _estimate(avg, analysts, low=None, high=None, bare_count=False):
    def box(value):
        return None if value is None else {"raw": value, "fmt": str(value)}

    count = analysts if bare_count else box(analysts)
    return {
        "avg": box(avg),
        "low": box(low),
        "high": box(high),
        "numberOfAnalysts": count,
    }


def test_revenue_consensus_parser():
    """Saved earningsTrend payload. No network."""
    import datetime as dt

    import revenue_consensus as rc

    end_2027 = int(dt.datetime(2027, 12, 31, tzinfo=dt.timezone.utc).timestamp())
    payload = {
        "quoteSummary": {
            "result": [{
                "financialData": {"financialCurrency": "USD"},
                "earningsTrend": {
                    "trend": [
                        {
                            "period": "0q",
                            "endDate": "2026-03-31",
                            "revenueEstimate": _estimate(999, 8, 900, 1100),
                        },
                        {
                            "period": "0y",
                            "endDate": "2026-12-31",
                            "revenueEstimate": _estimate(100, 4, 90, 110, bare_count=True),
                        },
                        {
                            "period": "+1y",
                            "endDate": {"raw": end_2027, "fmt": "2027-12-31"},
                            "revenueEstimate": _estimate(150, 3, 140, 160),
                        },
                        {
                            "period": "+1y",
                            "endDate": "2028-12-31",
                            "revenueEstimate": _estimate(180, 0, 170, 190),
                        },
                    ]
                },
            }],
            "error": None,
        }
    }
    rows = rc.annual_rows(payload)
    assert [row["period"] + " " + row["end"][:4] for row in rows] == ["0y 2026", "+1y 2027"], rows
    assert rows[0]["analysts"] == 4 and rows[0]["currency"] == "USD"
    assert rows[0]["low"] == 90 and rows[0]["high"] == 110
    match = rc.row_for_year(rows, 2027)
    assert match["avg"] == 150 and match["analysts"] == 3 and match["end"] == "2027-12-31"
    assert rc.row_for_year(rows, 2028) is None
    assert rc.row_for_year(rows, 2026)["avg"] == 100
    assert "0q" not in [row["period"] for row in rows]

    zero = {
        "quoteSummary": {
            "result": [{
                "earningsTrend": {
                    "trend": [
                        {
                            "period": "0y",
                            "endDate": "2026-12-31",
                            "revenueEstimate": _estimate(100, 2),
                        },
                        {
                            "period": "+1y",
                            "endDate": "2027-12-31",
                            "revenueEstimate": _estimate(150, 0),
                        },
                    ]
                }
            }]
        }
    }
    zero_rows = rc.annual_rows(zero)
    assert rc.row_for_year(zero_rows, 2027) is None
    assert [row["end"][:4] for row in zero_rows] == ["2026"]

    assert rc.gap_band(110, 100)[0] == 1
    assert rc.gap_band(109, 100)[0] == 0.5
    assert rc.gap_band(100.01, 100)[0] == 0.5
    assert rc.gap_band(100, 100)[0] == 0
    assert rc.gap_band(90, 100)[0] == 0
    score, gap = rc.gap_band(110, 100)
    assert score == 1 and gap >= rc.GAP_FULL
    print("revenue consensus parser ok", match["end"], "gap", round(gap, 4))


def test_long_gate_substack_fallback_and_structured_forms():
    """Stance gate. The score is not an input. SA and VIC still require the form."""
    import inspect

    import long_gate
    import sa_ingest

    params = inspect.signature(long_gate.decision).parameters
    assert "score" not in params and "sc" not in params

    passes = [
        ("substack", "I own the shares.", ""),
        ("substack", "I am long the stock.", ""),
        ("substack", "I hold a position in the company.", ""),
        ("blog", "We are long.", ""),
        ("forum", "The author holds a long position in the stock.", ""),
        ("substack", "I value the shares at $40, about double the current price.", ""),
        ("substack", "My 12-month price target for the stock is $25.", ""),
        ("substack", "Over the next two years I expect the shares to double.", ""),
        ("substack", "I recommend owning the shares.", ""),
        ("substack", "The shares are worth $25.", ""),
        ("substack", "I think the stock is worth $18 a share.", ""),
        ("substack", "Base case $40 per share over two years.", ""),
        ("substack", "I own the shares. Recommendation: Hold.", ""),
        ("substack", "I may hold a position. I recommend owning the shares.", ""),
        ("substack", "I recommend owning the shares.", "ACME is a Buy"),
    ]
    for source, text, title in passes:
        assert long_gate.decision(source, text, title) == "pass", (source, title, text)
        assert long_gate.reason(source, text, title) == "", (source, text)

    drops = [
        ("substack", "ACME is a Buy", "ACME: Buy"),
        ("substack", "LONG", "LONG $ACME"),
        ("substack", "Acme makes widgets for hospitals. Revenue was $40 million. The CEO joined in 2019.", "Acme Corp"),
        ("substack", "The CEO's net worth is $40 million. Revenue was $40 million.", "Acme Corp"),
        ("substack", "The lithium sector will grow over the next two years as demand rises.", "Lithium"),
        ("substack", "I love this company. The product is amazing and the team is world class.", "Acme"),
        ("substack", "I may hold a position in the stock.", ""),
        ("substack", "My price target is $40. I do not own the stock.", ""),
        ("substack", "My price target is $40. I am short the shares.", ""),
        ("substack", "My price target is $40. Recommendation: Hold.", ""),
        ("substack", "The company makes widgets.", "Price target $40"),
        (
            "substack",
            "This is a thorough look at a high-quality compounder with a long runway, strong returns on capital, and an excellent culture. " * 8,
            "Acme",
        ),
    ]
    for source, text, title in drops:
        assert long_gate.decision(source, text, title) == "drop", (source, title, text)
        assert long_gate.reason(source, text, title) == "author not long", (source, text)

    stance = "I am long the shares. My price target is $40. I recommend owning them."
    assert long_gate.decision("seeking alpha", stance) == "drop"
    assert long_gate.decision("SA", stance) == "drop"
    assert long_gate.reason("Author (SA)", stance) == "author not long"
    disclosed = stance + " I/we have a beneficial long position in the shares of ACME."
    assert long_gate.decision("Seeking Alpha", disclosed) == "pass"

    vic_pos = "I and/or others I advise hold a material investment in the issuer's securities."
    vic_neg = "I and/or others I advise do not hold a material investment in the issuer's securities."
    assert long_gate.decision("Value Investors Club", vic_pos) == "pass"
    assert long_gate.decision("vic", vic_neg) == "drop"
    assert long_gate.decision("vic", vic_neg + " " + stance) == "drop"
    assert long_gate.decision("VIC", stance) == "drop"

    body = "I recommend owning the shares. My price target is $40. " + " ".join(["word"] * 700)
    saved = (
        "URL: https://seekingalpha.com/article/77\nTITLE: Acme\nAUTHOR: A\nDATE: Oct 13, 2026\n"
        "TICKERS: Example (ACME) Stock\n\n=== SUMMARY ===\n- a bullet\n\n=== ARTICLE BODY ===\n"
        f"{body}\n\n=== ANALYST'S DISCLOSURE ===\nNo position is disclosed here.\n"
    )
    status, why = sa_ingest.classify_text(saved, "ACME", {})
    assert status == "not_long" and why == "author not long", (status, why)
    print("long gate: substack fallback passes; SA and VIC still require the form")


def test_batting_average_longcheck_is_unchanged():
    """The 2-year batting average still counts a pitch with no long signal."""
    import longcheck

    assert longcheck.is_long("My price target is $40. I recommend owning the shares.")[0] == "unclear"
    assert longcheck.exclude_reason("Acme", "My price target is $40.")[0] is None
    assert longcheck.exclude_reason("Acme", "I am short the stock.")[0] == "short"
    print("batting-average longcheck still counts a pitch with no long signal")


def test_long_gate_wording_matches_across_screener_docs():
    import long_gate
    import make_report

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (
        "AGENTS.md",
        "README.md",
        ".cursor/skills/stock-screen/SKILL.md",
        ".cursor/skills/author-batting-average/SKILL.md",
    ):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert long_gate.FALLBACK in text, rel
    doc = {"window": ["2026-10-01", "2026-10-16"], "stats": {"sourced": 0, "read": 0, "scored": 0}, "articles": []}
    md, _rows, _ranked = make_report.render(doc, {}, live=False)
    assert long_gate.FALLBACK in md
    assert "beneficial long position" in md
    assert "The /7 score does not keep or drop the article." in md
    print("long-gate wording matches")


if __name__ == "__main__":
    test_in_window_sourced_count()
    test_pitch_titles_stay_and_recap_drops()
    test_macro_phrase_and_single_listing()
    test_content_screen_drops_only_clear_cases()
    test_report_drop_counts_come_from_the_screen_file()
    test_old_six_point_scores_stay_marked_out_of_6()
    test_fetch_body_reuses_stored_text()
    test_shared_store_copies_into_fulltext()
    test_revenue_consensus_parser()
    test_long_gate_substack_fallback_and_structured_forms()
    test_batting_average_longcheck_is_unchanged()
    test_long_gate_wording_matches_across_screener_docs()
