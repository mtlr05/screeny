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

- `config/sources.csv` — active sources. `config/sources_dormant_or_dead.csv` — parked; recheck about monthly.
- `state/seen_posts.csv` — dedupe key is `url`. Append-only.
- `state/scored.json`, `state/batting.json` — this run's scores and batting averages.
- `reports/` — dated outputs. Sample: `reports/2026-10-14/`.
- `fulltext/` and `cache/` — local only, not committed.
- `.cursor/skills/stock-screen/` — sweep, triage, read, score, report.
- `.cursor/skills/author-batting-average/` — batting average on its own.
- `scripts/` — sweep, fetch, prices, earnings drops, report. `rerun/` — full-window helpers. `bat/` — batting-average helpers.

X links are optional. The user pastes them. Do not call the X MCP and do not keep an X account list.
