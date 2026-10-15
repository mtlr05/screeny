"""Disposition of every candidate read in full.

S maps an extract index (or ticker) to (T, R, C, M, D, K, short note):
  T thesis/runway, R return ~40%/yr, C CEO large holder,
  M moat or edge, D differential view, K dated catalyst.
D maps an index to a DROP key for articles dropped after the full read.
EXTRA is a list of manual adds: sym, title, url, date, source, sc, note.
LONG is the set of indexes/tickers whose author disclosed a long position.
AMBIG maps an index/ticker to the quote that was not an explicit long.

Weekly runs record the same facts in state/scored.json (see make_report.py).
This module is the full-rerun worksheet used with --legacy when
rerun/extract.json is present. It starts empty; do not invent rows.
"""
DROP = {
    "hold": "not a bullish pitch (hold / fairly valued / bearish / no buy case)",
    "nomoat": "no moat or edge (commodity, shipping, explorer, cash shell, special situation)",
    "nonna": "not US/Canada listed (or company not identifiable)",
    "notpitch": "not a single-stock pitch (essay, primer, roundup, credit/arb trade)",
    "preview": "preview-only / member-gated text",
    "large": "not small/mid cap",
}
D = {}
S = {}
EXTRA = []
LONG = set()
AMBIG = {}
