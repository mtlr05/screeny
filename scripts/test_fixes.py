#!/usr/bin/env python3
"""Offline checks for the in-window sourced count. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weekly_sweep


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
    print("in-window sourced count ok", len(window), "new", len(new))


if __name__ == "__main__":
    test_in_window_sourced_count()
