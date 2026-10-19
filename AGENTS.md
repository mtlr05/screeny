# Screeny

On-demand scout for single-stock investment write-ups. David runs it from the Cursor agent window. There is no schedule. The procedure is in `.cursor/skills/`. This file is the standing rules for every request.

## Hard rules

- Cite every source (title and URL). Never invent numbers, tickers, dates, or URLs. Mark anything unverified.
- Score only articles read in full. A paywalled or preview-only post is dropped. Never score from a title, summary, or preview. Do not bypass a paywall. Criterion scores and the one-sentence evidence live in `state/scored.json` (`sc` of seven numbers and `notes.c1`–`notes.c7`, plus `score_out_of`). A stored `sc` of six numbers is the old rubric: criterion 4 is moat, edge is 0, the old fifth and sixth numbers are criteria 6 and 7, and the total stays out of 6. The report reprints those fields. Do not pass `--prices` when the stored `since_publish` should stay as written.
- Never use Seeking Alpha investing groups.
- If Seeking Alpha shows a bot check, pause and try that article once more. If it fails again, stop gathering and score what was already read in full. The new-article pull is the signed-in browser plus `scripts/sa_ingest.py`. Do not store a login or a cookie. If the session has expired, ask the user to sign in.
- The author must disclose a long position (a Seeking Alpha "beneficial long position" disclosure, or an explicit "I own / I am long / I hold a position" statement). A Buy/LONG rating alone, or "may hold" boilerplate, does not count. Drop reason: `author not long`.
- Criterion 3 is CEO ownership or incentive, from the article or a cited filing only. Score the highest tier in the stock-screen-scoring skill. If nothing is stated, score 0 and print "not stated". The evidence sentence quotes or cites the matched sentence. Do not use a holding figure from outside the text. `scripts/ceo_stake_grep.py` only lists candidate sentences.
- During a long step (a sweep or article reads), check its progress log every 1 to 2 minutes. The check takes a second or two. Restart the step immediately if it has stalled or died. On a Content Error, back off and resume.
- Do not re-download article text. Keep fetched text in `fulltext/`, in `state/`, and in the shared store (`SCREENY_TEXT_STORE`, or `~/.screeny/fulltext_store` if unset). On any run, including after a failed run or in a fresh clone, check `fulltext/` first, then the shared store, then seen or result records. Copy a usable store file into `fulltext/` instead of fetching. Fetch only a missing article, or one whose stored file is unusable (a bot-check page or an empty file). `python3 scripts/text_store.py import DIR` copies an existing `fulltext/` folder into the store.

## Preferences

- US or Canada listings. Small or mid cap, under about US$10B. One stock per pitch. Updates and earnings reviews count. A missing moat or edge is not a drop. Criterion 4 is moat and criterion 5 is edge. Each can be 0. The total is out of 7.
- The Substack sweep drops a free post on the title only when it is a recap, a macro phrase, or a list (whole words). The bare word "macro" is not a drop. A title that names one ticker or one exchange is not title-dropped; the body screen decides. It then reads about the first 1,500 words and drops the post only when that text is clearly not a single-stock pitch, or the author is short, selling, or on hold. Unclear posts stay. Every in-window post is a row in `reports/substack_screen_<date>.csv`. Triage drop counts in the report are read from that file.
- Full run: last 4 months. "This week": last 7 days.
- Cap and listing are screening filters, not points on the /7 score.

## Report layout

1. **Stats** — three numbers only: articles sourced, articles read in full, articles scored.
2. Screening and scoring rules.
3. **Ranked list** — top 15 plus every name tied with the 15th score. Include a **BA 2y (1y)** column: the author's 2-year batting average as hits/n = %, else the 1-year tagged `(1y)`, else `n/a`. The column does not change the /7 score. A total still stored out of 6 is shown as /6.
4. **Score vs P(fewer hits)** — one point per scored article. Blue is the 2-year `P(X < hits)`. Red is the 1-year figure, used only when the 2-year sample is missing. A black x at 0 means neither sample exists.
5. Author batting top-5 tables, near misses, then **Articles from top-record authors**, then caveats.
6. **Appendix: one-pagers**, then **Appendix: batting average and P(X < hits)** (the short explanation, then every chart point with its article link), then **Appendix: detailed stats** (drop reasons, Seeking Alpha breakdown, counts by source type). Detailed stats stay in the appendix.

## Where things live

- `config/sources.csv` — active sources. `config/sources_dormant_or_dead.csv` — parked. Automatic adds skip parked authors. A dormant recheck may put a parked author back. `config/sources_dropped_never_readd.csv` — authors removed by an approved drop (`name`, `url`, `dropped_on`, `reason`). It holds the 17 drops from 2026-10-16, plus later approved drops. Discovery skips them. `--apply` refuses the add. A dormant recheck must not reactivate anyone on that list. Only a hand edit of the never-readd file overrides it.
- `state/seen_posts.csv` — dedupe key is `url`. Append-only.
- `state/source_stats.csv` — per tracked source: last post, consecutive failed loads, articles scored in the last 6 months, 6-month average score, 2-year batting average and pitch count, `ba2y_p_lt_hits` (`p_lt_hits_by_chance`), `ba2y_median_excess`, `ba2y_med_ret` (2-year median stock return), `ba_updated`, `ba_method`, exclusion and price-loss counts, plus title versus body pitch counts. Seeking Alpha is not in this file. A stored batting average has no expiry. Recalculate it only for an add candidate or a removal proposal, and only when `ba_updated` is not today, unless someone asks for `--full-ba`.
- `state/scored.json`, `state/batting.json` — this run's scores and batting averages.
- `reports/` — dated outputs. Sample: `reports/2026-10-14/`.
- `fulltext/` and `cache/` — local only, not committed. A copy of each usable `fulltext/` file also goes to the shared store outside the clone (`SCREENY_TEXT_STORE`, default `~/.screeny/fulltext_store`).
- `.cursor/skills/stock-screen/` — sweep, triage, read, score, report.
- `.cursor/skills/stock-screen-scoring/` — the seven criteria and the evidence rules. This skill takes precedence over the scoring summary in the stock-screen skill.
- `.cursor/skills/author-batting-average/` — batting average on its own.
- `scripts/` — sweep, fetch, prices, earnings drops, report. `rerun/` — full-window helpers. `bat/` — batting-average helpers.

X links are optional. The user pastes them. Do not call the X MCP and do not keep an X account list. The sweep does not pull X-linked blogs, so the original run's two `x_network_blog` posts are not in the sourced count unless those links are pasted.

## Source upkeep

After a screen, run `python3 scripts/source_upkeep.py --plan` and show the proposals. Every drop and every add needs David's approval. Each line has the source name, drop or add, the reason, the numbers, `p_lt_hits_by_chance` (`ba2y_p_lt_hits`), and `ba_updated`. Apply only entries marked `"approved": true`.

Tracked active sources have a soft cap of 600. Drop a source only for a 2-year batting average of 33% or less on at least 5 pitches (cutoff under 0.334, so one third is included), no post in 6 months (a blank date stays), or 4 failed loads in a row. The fourth failure is enough; there is no probation. A source with no scored articles stays. Add a Substack recommendation only when that author scored at least 5.25/7 (4.5/6 when the stored total is still out of 6) and the new author has `ba2y_p_lt_hits` greater than 0.23 and `ba2y_median_excess` greater than 0. While evaluating new authors, skip a publication whose name or description is not stock research (crypto, bitcoin, forex, options trading, day trading, real estate, macro-only, or politics). Never add back an author who is on `config/sources_dropped_never_readd.csv`. Seeking Alpha is one pull, not a tracked source, and it is not in this file. New articles come from the signed-in browser and `scripts/sa_ingest.py`. Past pitches for a batting average still use the public author API.

David can approve a source by hand when it misses the automatic add bar. Three publications were added that way on 2026-10-16: Intrinsic Value System (15/31, `p_lt_hits_by_chance` 0.3601), Welfare Capital Research (2/2, 0.75), and The Lead-Lag Report (2/2, 0.75). The exception is recorded in each row's `how_discovered`. Later removal proposals still use the drop rules.

The /7 score still needs an explicit long disclosure. The 2-year batting average is separate. One pitch per ticker, published 2–3 years ago. `bat/longcheck.py` drops a short, a sell, or a hold unless the body shows the author owns the shares. A pitch with no such signal still counts. Price timeouts are not delistings. A symbol with no price data is retried as `.TO` then `.V`. The batting-average benchmark is XCS.TO for `.TO` and `.V`, and IWM otherwise. `ba_method` for a new calculation is `v3-iwm-xcs`. A stored row keeps its old method until that author is recalculated. The since-publish column stays IWM for US listings and XIC.TO for Canada.

`p_lt_hits_by_chance` is `P(X <= hits - 1)` with `p = 0.5`. It is always stored as `ba2y_p_lt_hits`, shown on every proposal and in the report, and batting summaries sort by it, highest first.

Median stock return and median excess return (1-year and 2-year) will be stored with the batting average and shown on proposals. Those columns are not in the stats file yet. The screen report already prints median excess for authors computed during a run.

An approved add writes the batting average computed for that candidate into `state/source_stats.csv`.

## Articles from top-record authors

The generated report includes this section after the next-six list, in `REPORT.md` and in `REPORT.pdf` when `python3 scripts/make_report.py --pdf` is used. The PDF is that Markdown converted in full. It is every article in the report window from an author whose stored 2-year `ba2y_p_lt_hits` is at least 0.5 on at least 2 pitches. Read `state/source_stats.csv` when the report is written, and keep only URLs still in `config/sources.csv`. Show hits/pitches, the batting average, and `p_lt_hits_by_chance` next to the author, then each article's title, date, link, and score when one exists. Sort authors by that chance, highest first. Do not keep a separate author list. An approved source add stores the recomputed row, so the next report includes that author.
