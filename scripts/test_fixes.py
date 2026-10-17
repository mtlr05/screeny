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

    post = _post("https://ex.substack.com/p/slug", "Acme Corp")
    text = weekly_sweep.fetch_body(post, {}, getter=_ok)
    assert len(text.split()) == 1500, len(text.split())
    assert weekly_sweep.fetch_body(post, {}, getter=_boom) == ""
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


if __name__ == "__main__":
    test_in_window_sourced_count()
    test_pitch_titles_stay_and_recap_drops()
    test_content_screen_drops_only_clear_cases()
    test_report_drop_counts_come_from_the_screen_file()
