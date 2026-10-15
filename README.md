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
python3 scripts/make_report.py --prices
python3 scripts/make_report.py --example
```

`make_report.py --example` re-renders the 2026-10-14 sample from `examples/scored.json` into `cache/example-REPORT.md`. It does not call the network.

Triage files are JSON. `grab_fulltext.py` reads that file directly, so you do not need `jq`.

## Rules that do not change

Cite every source. Never invent a number or a URL. Score only articles read in full. Do not bypass paywalls or bot checks. Never use Seeking Alpha investing groups. If Seeking Alpha shows a bot check, stop and score what was already read. The author has to disclose a long position. X links are optional and are pasted by hand. This repo does not call the X MCP.
