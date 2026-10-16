# Screeny

On-demand scout for single-stock investment write-ups. David runs it from the Cursor agent window. There is no schedule. The procedure is in `.cursor/skills/`. This file is the standing rules for every request.

## Hard rules

- Cite every source (title and URL). Never invent numbers, tickers, dates, or URLs. Mark anything unverified.
- Score only articles read in full. A paywalled or preview-only post is dropped. Never score from a title, summary, or preview. Do not bypass a paywall.
- Never use Seeking Alpha investing groups.
- If Seeking Alpha shows a bot check, stop gathering and score what was already read in full.
- The author must disclose a long position (a Seeking Alpha "beneficial long position" disclosure, or an explicit "I own / I am long / I hold a position" statement). A Buy/LONG rating alone, or "may hold" boilerplate, does not count. Drop reason: `author not long`.

## Preferences

- US or Canada listings. Small or mid cap, under about US$10B. One stock per pitch. Updates and earnings reviews count. The business needs a moat or an edge.
- Full run: last 4 months. "This week": last 7 days.
- Cap and listing are screening filters, not points on the /6 score.

## Report layout

1. **Stats** — three numbers only: articles sourced, articles read in full, articles scored.
2. Screening and scoring rules.
3. **Ranked list** — top 15 plus every name tied with the 15th score. Include a **BA 2y (1y)** column: the author's 2-year batting average as hits/n = %, else the 1-year tagged `(1y)`, else `n/a`. The column does not change the /6 score.
4. Author batting top-5 tables, near misses, caveats.
5. **Appendix: one-pagers**, then **Appendix: detailed stats** (drop reasons, Seeking Alpha breakdown, counts by source type). Detailed stats stay in the appendix.

## Where things live

- `config/sources.csv` — active sources. `config/sources_dormant_or_dead.csv` — parked. `config/sources_dropped_never_readd.csv` — authors who have been dropped. Do not add them back. A dormant recheck must not reactivate anyone on that list. Only a hand edit of the never-readd file overrides it.
- `state/seen_posts.csv` — dedupe key is `url`. Append-only.
- `state/source_stats.csv` — per tracked source: last post, consecutive failed loads, articles scored in the last 6 months, 6-month average score, 2-year batting average and pitch count, `ba2y_p_lt_hits`, `ba_updated`, exclusion and price-loss counts, plus title versus body pitch counts. Seeking Alpha is not in this file. A stored batting average has no expiry. Recalculate it only for an add candidate or a removal proposal, unless someone asks for `--full-ba`.
- `state/scored.json`, `state/batting.json` — this run's scores and batting averages.
- `reports/` — dated outputs. Sample: `reports/2026-10-14/`.
- `fulltext/` and `cache/` — local only, not committed.
- `.cursor/skills/stock-screen/` — sweep, triage, read, score, report.
- `.cursor/skills/author-batting-average/` — batting average on its own.
- `scripts/` — sweep, fetch, prices, earnings drops, report. `rerun/` — full-window helpers. `bat/` — batting-average helpers.

X links are optional. The user pastes them. Do not call the X MCP and do not keep an X account list.

## Source upkeep

After a screen, run `python3 scripts/source_upkeep.py --plan` and show the proposals. Every proposal includes `ba2y_p_lt_hits` and the date the batting average was calculated. Apply a proposal only after approval (`--apply` on entries marked approved). Tracked active sources have a soft cap of 600. Drop a source only for a 2-year batting average of 33% or less on at least 5 pitches, no post in 6 months, or 4 failed loads in a row. Do not drop a source only because it has no scored articles. Add a Substack recommendation only when that author scored at least 4.5/6 and the new author has a 2-year batting average above 50% on at least 5 pitches. Never add back an author who is on `config/sources_dropped_never_readd.csv`. Seeking Alpha stays on its own weekly pull and is not a tracked source.

The /6 score still needs an explicit long disclosure. The 2-year batting average is separate: skip a short, a sell, or a hold without clear ownership; keep a hold when the author owns the shares; keep a pitch whose stance is unclear. Price timeouts are not delistings. A symbol with no price data is retried as `.TO` then `.V`. The batting-average benchmark is XIC.TO for `.TO` and `.V`, and SPY otherwise.
