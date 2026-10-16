# Screeny

On-demand stock-article scout. It sweeps Substack and a short list of blogs, forums, Value Investors Club, and Seeking Alpha, reads pitches in full, scores them out of 6, and writes a ranked Markdown report.

David runs it from the Cursor agent window on his laptop. There is no schedule and no signed-in browser.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Commands assume the repo root. Scripts find `config/`, `state/`, and `reports/` from their own location.

Optional: set `SCREENY_USER_AGENT` if you want a specific User-Agent. The default is a plain browser string. Do not put an email address in the repo.

PDF output is optional. Markdown is the report. For a PDF, install `markdown` and `weasyprint`, then pass `--pdf`.

## Ask Cursor

- `Run the stock screen`
- `Screen this week's articles`
- `Screen articles since 2026-10-01`
- `What is Stephen Tobin's batting average?`

The agent follows `AGENTS.md` and `.cursor/skills/stock-screen/SKILL.md`.

## Layout

| Path | Role |
|---|---|
| `config/sources.csv` | Active sources (~300 Substack and a few manual feeds) |
| `config/sources_dormant_or_dead.csv` | Parked feeds |
| `config/sources_dropped_never_readd.csv` | Dropped authors. Never add them back |
| `config/universe.csv` | Optional ticker list for earnings-drop search |
| `state/seen_posts.csv` | URLs already swept (dedupe) |
| `state/source_stats.csv` | Per-source upkeep stats (Seeking Alpha is excluded) |
| `reports/` | Dated reports. Sample: `reports/2026-10-14/` |
| `examples/` | Same sample, plus `scored.json` so the report script can re-render it |
| `fulltext/`, `cache/` | Local fetches. Gitignored |
| `scripts/` | Sweep, fetch, prices, earnings drops, report |
| `rerun/` | Full 4-month rebuild helpers |
| `bat/` | Author batting average |

## Commands

```bash
python3 scripts/weekly_sweep.py --since 2026-10-08
python3 scripts/earnings_drops.py
python3 scripts/grab_fulltext.py reports/triage_YYYY-MM-DD.json
python3 scripts/px.py 2026-10-01 AAPL
python3 scripts/sa_public.py article https://seekingalpha.com/article/123
python3 bat/sa_one.py "Author Name" author-slug
python3 bat/pitches.py sylencecapital --limit 20
python3 scripts/make_report.py --prices
python3 scripts/make_report.py --example
python3 scripts/source_upkeep.py --plan
python3 scripts/source_upkeep.py --apply reports/source_upkeep_YYYY-MM-DD.json
```

`make_report.py --example` re-renders the 2026-10-14 sample from `examples/scored.json` into `cache/example-REPORT.md`. It does not call the network.

Triage files are JSON. `grab_fulltext.py` reads that file directly, so you do not need `jq`.

## Source upkeep

Runs happen when someone asks, so upkeep keys off dates and run counts. `python3 scripts/source_upkeep.py --plan` rewrites `state/source_stats.csv` and writes a proposal under `reports/`. It does not change the source lists, and it does not recompute every batting average. Show the proposal, set `"approved": true` on the entries to keep, then `--apply` that file. Approved drops move the row to `config/sources_dormant_or_dead.csv` and append it to `config/sources_dropped_never_readd.csv`. Approved adds append to `config/sources.csv`. An add for anyone on the never-readd list is refused. A dormant recheck must not put that author back. Only a hand edit of the never-readd file overrides it.

Each tracked source (everything except Seeking Alpha) records:

- last post date
- consecutive failed loads
- articles scored in the last 6 months
- average score over those articles
- 2-year batting average, the pitch count behind it, and `ba2y_p_lt_hits` (the chance of fewer hits than this author got, if each pitch were a coin flip)
- `ba_updated` (the date that average was calculated) and `ba_method`
- how many of those 2-year pitches were detected from the title and from the body
- how many pitches were excluded as short, sell, or hold, and how many were lost to a price timeout versus a real Not Found

There is no expiry on a stored batting average. `--plan` recalculates it only when that author is proposed for removal or is an add candidate, and only when `ba_updated` is not today. Every proposal prints `ba2y_p_lt_hits` and `ba_updated`. `python3 scripts/source_upkeep.py --plan --full-ba` is the one-off pass over every Substack author. It saves every 10 authors and resumes. `--force` redoes authors already stored with the current method, and `--ba-limit N` stops early. If an author's time budget runs out, that partial average is not saved.

`pitches_title` and `pitches_body` stay blank until that author has been detected. A blank percentage is not a drop and not an add.

### Substack pitch detection

`python3 bat/pitches.py subdomain` reads the archive. One pitch per ticker per window (the earliest).

- A title that names exactly one ticker is method `title`. `(TSXV: SUM or OTC: SUMMF)` is one company; the listed exchange is kept.
- No ticker, or more than one company: fetch `https://<host>/api/v1/posts/<slug>`. Files land in `cache/` (gitignored). Uncached calls wait 1 second (`--sleep`). Method `body`.
- The ticker comes from the opening text and from repeated mentions (`$TICKER`, `(NYSE: X)`, `(TSX: X)`, `ticker: X`). If none appear, the company name is looked up on Yahoo (US/Canada equity only).
- For the /6 score, the author must disclose a long: an explicit "I own / I am long / my position" line, or buy/thesis language. "May hold" does not count. Bearish, hold, recap, macro, watchlist, and closed positions are not scored.
- For the 2-year batting average the rule is looser. `bat/longcheck.py` drops a short, a sell rating, or a hold rating unless the author clearly owns the shares. A hold with "I own" stays in. A pitch with no such signal still counts. The body is fetched for title pitches too, so a hold or short in the body is visible. Counts by reason are stored in `ba2y_excl`.
- Each pitch stores `method` (`title` or `body`) and `confidence`. A preview body is not mined for a ticker. Seeking Alpha is unchanged: past pitches use the public author API only, not this body fetch.

Prices for the batting average use Yahoo's chart API. Each call has a hard wall-clock cap. A timeout is retried and is never cached, and it is not counted as a delisting (`ba2y_lost_px`). Only a real Not Found is cached, for 7 days (`ba2y_lost_notfound`). A symbol with no dot and no price data is retried as `SYM.TO`, then `SYM.V`. The benchmark is XIC.TO for `.TO` and `.V`, and SPY otherwise. Each author has about a 300 second budget. Body fetches and price fetches overlap, and they share one price cache.

Rules:

- Soft cap of 600 tracked active sources. Only when the list would exceed 600, propose trimming the lowest 6-month average score, and only for sources with at least 3 scored articles in that window, until it fits.
- Drop when the 2-year batting average is 33% or less on at least 5 pitches (a one-third record is included; the cutoff is a fraction under 0.334).
- Drop when the last known post is older than 6 months. An unknown date is not a drop.
- Drop when a feed fails to load on 4 consecutive runs (`weekly_sweep.py` records which sources it tried). No probation period.
- Do not drop a source only because it has no scored articles.
- Add a source only if it is a Substack recommendation of an author who scored at least 4.5/6 (`scripts/crawl_sources.py` walks those recommendations) and the candidate's 2-year batting average is above 50% on at least 5 pitches. Candidates with fewer than 5 pitches are skipped for now. `--crawl` fetches the recommendations; without it, `--plan` uses `cache/crawl.json` when that file exists. Discovery skips anyone already on the never-readd list.
- A dropped author is never added back. `--apply` appends every drop to `config/sources_dropped_never_readd.csv` (`name`, `url`, `dropped_on`, `reason`). `--apply` refuses an add that is already on that list.
- Seeking Alpha is not tracked as a source. The weekly Seeking Alpha pull is unchanged.

## Rules that do not change

Cite every source. Never invent a number or a URL. Score only articles read in full. Do not bypass paywalls or bot checks. Never use Seeking Alpha investing groups. If Seeking Alpha shows a bot check, stop and score what was already read. The author has to disclose a long position. X links are optional and are pasted by hand. This repo does not call the X MCP.
