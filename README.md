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

Runs happen when someone asks, so upkeep keys off dates and run counts. `python3 scripts/source_upkeep.py --plan` rewrites `state/source_stats.csv` and writes a proposal under `reports/`. It does not change the source lists. Show the proposal, set `"approved": true` on the entries to keep, then `--apply` that file. Approved drops move the row to `config/sources_dormant_or_dead.csv`. Approved adds append to `config/sources.csv`.

Each tracked source (everything except Seeking Alpha) records:

- last post date
- consecutive failed loads
- articles scored in the last 6 months
- average score over those articles
- 2-year batting average and the pitch count behind it
- how many of those 2-year pitches were detected from the title (`pitches_title`) and from the body (`pitches_body`)

Batting averages use the windows in `bat/calc.py`. If `state/batting.json` is missing, pitch counts can still come from `bat/pitches.py` and the percentage stays blank. A blank percentage is not a drop and not an add. `python3 bat/pitches.py` then `python3 bat/calc.py` fills the percentages. `--compute-ba` on the upkeep script calls that calculator for saved pitches.

`pitches_title` and `pitches_body` stay blank until that author has been detected. They count the same 2-year pitches as `ba_2y_n`, split by method, and they add up to `ba_2y_n` after detection.

### Substack pitch detection

`python3 bat/pitches.py subdomain` reads the archive and keeps a single US or Canada long. One pitch per ticker per window (the earliest).

- A title that names exactly one ticker is method `title`. `(TSXV: SUM or OTC: SUMMF)` is one company; the listed exchange is kept. The body is not fetched when the title also shows a long stance.
- No ticker, or more than one company: fetch `https://<host>/api/v1/posts/<slug>`. Files land in `cache/` (gitignored). Uncached calls wait 1 second (`--sleep`). Method `body`.
- The ticker comes from the opening text and from repeated mentions (`$TICKER`, `(NYSE: X)`, `(TSX: X)`, `ticker: X`). If none appear, the company name is looked up on Yahoo (US/Canada equity only).
- Long stance means an explicit "I own / I am long / my position" line, or buy/thesis language ("investment thesis", "LONG $TICKER", "why I own"). "May hold" does not count. Bearish, hold, recap, macro, watchlist, and closed positions are dropped.
- Each pitch stores `method` (`title` or `body`) and `confidence`. A preview body is not mined for a ticker. Seeking Alpha is unchanged: past pitches use the public author API only, not this body fetch.

Rules:

- Soft cap of 600 tracked active sources. Only when the list would exceed 600, propose trimming the lowest 6-month average score, and only for sources with at least 3 scored articles in that window, until it fits.
- Drop when the 2-year batting average is under 30% on at least 5 pitches.
- Drop when the last known post is older than 6 months. An unknown date is not a drop.
- Drop when a feed fails to load on 4 consecutive runs (`weekly_sweep.py` records which sources it tried). No probation period.
- Do not drop a source only because it has no scored articles.
- Add a source only if it is a Substack recommendation of an author who scored at least 4.5/6 (`scripts/crawl_sources.py` walks those recommendations) and the candidate's 2-year batting average is above 50% on at least 5 pitches. Candidates with fewer than 5 pitches are skipped for now. `--crawl` fetches the recommendations; without it, `--plan` uses `cache/crawl.json` when that file exists.
- Seeking Alpha is not tracked as a source. The weekly Seeking Alpha pull is unchanged.

## Rules that do not change

Cite every source. Never invent a number or a URL. Score only articles read in full. Do not bypass paywalls or bot checks. Never use Seeking Alpha investing groups. If Seeking Alpha shows a bot check, stop and score what was already read. The author has to disclose a long position. X links are optional and are pasted by hand. This repo does not call the X MCP.
