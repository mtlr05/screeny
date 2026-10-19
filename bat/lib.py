"""Detect a single US/Canada long pitch in a Substack post.

A title that names exactly one ticker is enough. When the title has no ticker,
or more than one company, the post body is fetched from the public Substack
route /api/v1/posts/<slug> (cached under cache/, one request at a time).

The primary ticker comes from the opening text and from repeated mentions
($CASHTAG, "(NYSE: X)", "(TSX: X)", "ticker: X"), or from a company name
looked up on Yahoo. Bearish, hold, recap, and macro posts are not pitches.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import calc as batcalc
from _paths import CACHE, ensure, user_agent

# Yahoo exchange codes for US and Canada listings, including OTC.
US_CA = {
    "NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "NAS",
    "TOR", "VAN", "CNQ", "NEO",
    "OQX", "OQB", "PNK", "OEM", "OBB",
}
EXCHANGE_RANK = {
    "NYQ": 5, "NMS": 5, "NGM": 4, "NAS": 5, "TOR": 5, "VAN": 4,
    "ASE": 4, "PCX": 3, "CNQ": 3, "NEO": 3, "OQX": 1, "OQB": 1, "PNK": 0,
}
# Words that look like tickers and are not.
STOP = {
    "US", "USA", "CEO", "CFO", "COO", "EPS", "FCF", "AI", "EV", "IPO", "USD", "CAD",
    "ETF", "NAV", "FDA", "THE", "FOR", "AND", "GDP", "CPI", "YOY", "QOQ", "EBITDA",
    "ROE", "ROIC", "SEC", "NYSE", "NASDAQ", "TSX", "TSXV", "OTC", "AMEX", "ALL",
    "NEW", "BIG", "TOP", "BUY", "LONG", "HOLD", "CASH", "DEBT", "FREE", "NOTE",
    "WEEK", "YEAR", "Q1", "Q2", "Q3", "Q4", "FY", "PE", "PS", "PB", "DCF", "TAM",
    "GAAP", "YTD", "TTM", "AUM", "ESG", "ATH", "SPAC", "RSU", "SBC", "KPI", "UK",
    "EU", "AUD", "GBP", "FAQ", "EDIT", "PART", "INC", "LTD", "CORP", "LLC", "ADR",
    "CAGR", "IRR", "NPV", "EBIT", "COGS", "B2B", "B2C", "API", "PDF", "OTCQX",
    "OTCQB", "CSE", "NEO", "LSE", "AIM", "ASX", "USD", "OR", "TO", "CN", "NE",
    "DD", "EST", "PST", "UTC", "IMO", "TBH", "FYI", "ROI", "ROCE", "WACC", "CAGR",
    "OTCMKTS", "PINK", "MKT", "AMERICAN",
    "IT", "AN", "AS", "AT", "BE", "DO", "GO", "IF", "IS", "MY", "NO", "OF", "SO",
    "UP", "WE", "BY", "IN", "AM", "PM", "OR",
}
NAME_DROP = {
    "inc", "corp", "corporation", "ltd", "limited", "holdings", "holding", "company",
    "co", "group", "plc", "llc", "the", "sa", "nv", "ag",
}
SKIP_TITLE = re.compile(
    r"portfolio (update|review)|monthly (update|letter|review)|weekly (update|screen|review)"
    r"|week in|round-?up|\brecap\b|letter to (investors|partners)|quarterly letter|\bmacro\b"
    r"|podcast|reading list|\bdigest\b|market update|\bwatchlist\b|\binterview\b"
    r"|\bq\s*&\s*a\b|\bask me\b|my holdings|best ideas|bullet investment ideas"
    r"|year in review|performance (update|review)|mailbag|\bAMA\b|thoughts on stocks"
    r"|investment ideas|stocks to watch|weekly screen|\bprimer\b|\d+ stocks\b",
    re.I,
)
EXIT_TITLE = re.compile(r"\(closed\)|\bposition closed\b|\bclosed (the )?position\b|\btrade closed\b", re.I)
EXIT_BODY = re.compile(
    r"\b(i sold|i ended up selling|ended up selling|i exited|we exited|position closed|closed the position)\b",
    re.I,
)
STILL_LONG = re.compile(r"\b(still own|still long|i am buying|i'm buying|adding to)\b", re.I)
SHORT_RE = re.compile(
    r"\b(short thesis|short report|i am short|i'm short|we are short|sell rating|rating:\s*sell|not a buy|still researching)\b",
    re.I,
)
HOLD_RE = re.compile(
    r"\b(rating|verdict|recommendation)\s*[:\-]?\s*(hold|neutral)\b|\bi am neutral\b|\bi(?:'m| am) not (buying|long)\b",
    re.I,
)
LONG_RE = re.compile(
    r"\b(?:i|we|i'm|i am|i've|i have)\b.{0,60}\b(?:own|long|bought|buying)\b"
    r"|\b(?:my|our)\s+(?:long\s+)?position\b"
    r"|\blong position\b|\bposition disclosure\b|\bdisclosure:\s*long\b"
    r"|\b(?:i am|i'm|we are)\s+long\b"
    r"|\bhighest conviction\b|\bmy cost\b|\bbought shares\b"
    r"|\bwhy am i buying\b|\bwhy i (?:own|bought|am long)\b"
    r"|\binvestment thesis\b|\b(?:long|buy) thesis\b|\bthesis\b"
    r"|\bquick pitch\b|\blong\s+\$[A-Za-z]"
    r"|\(buy\)|\b(?:strong )?buy\b"
    r"|\binitiat(?:e|ed|ing)\s+(?:a\s+)?(?:long\s+)?position\b",
    re.I,
)
EXCH_RE = re.compile(
    r"\b(NASDAQ(?:GS|GM|CM)?|Nasdaq|NYSE\s+American|NYSEAMERICAN|NYSE\s*MKT|NYSE|AMEX"
    r"|OTCQX|OTCQB|OTCMKTS|OTC\s*Pink|OTC|TSX\.?V|TSX-V|TSXV|TSX|CSE|NEO)"
    r"\s*[:\-]\s*\$?([A-Z][A-Z0-9]{0,4}(?:[.\-][A-Z]{1,2})?)\b"
)
CASH_RE = re.compile(r"\$([A-Z]{2,5}(?:\.[A-Z]{1,2})?)\b")
TITLE_CASH_RE = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
FOREIGN_TAG = re.compile(
    r"\b(TYO|LSE|AIM|ASX|HKEX|HKG|SGX|KRX|KOSDAQ|XETRA|FRA|EPA|BIT|STO|SWX|NSE|BSE)\s*[:\-]",
    re.I,
)
LABEL_RE = re.compile(r"\bticker\s*[:\-]\s*\$?([A-Z][A-Z0-9]{0,4}(?:[.\-][A-Z]{1,2})?)\b", re.I)
PAREN_RE = re.compile(r"\(([A-Z]{2,5})\)")
OTC_NAMES = re.compile(r"OTC|PINK", re.I)
FOREIGN_SUFFIX = re.compile(r"\.(L|AX|HK|T|TW|KS|KQ|SW|DE|PA|AS|ST|OL|CO|MX|SA|SI|NZ|BK)$", re.I)


# author_pitches fills this. Each entry is (subdomain, date, ticker, reason, method).
EXCL_LOG = []
# compute_ba sets this to time.time() + budget. 1e18 means no budget.
DEADLINE = [1e18]
PXSTAT = {"ok": 0, "notfound": 0, "fail": 0, "fallback_TO": 0, "fallback_V": 0}


class Limiter:
    """Wait between network starts. Cache hits do not wait. Safe to share across threads."""

    def __init__(self, interval=1.0):
        self.interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delay = self.interval - (now - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def html_to_text(body):
    text = re.sub(r"<(br|/p|/h\d|/li)[^>]*>", "\n", body or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _symbol_ok(symbol):
    sym = (symbol or "").upper().lstrip("$")
    if not sym or sym in STOP or FOREIGN_SUFFIX.search(sym):
        return False
    if re.fullmatch(r"\d+", sym):
        return False
    return True


def to_yahoo(symbol, exchange):
    """Map an exchange-qualified symbol to a Yahoo ticker, or None if it is not US/Canada."""
    sym = (symbol or "").upper().lstrip("$").strip()
    if not _symbol_ok(sym):
        return None
    if sym.endswith((".TO", ".V", ".CN", ".NE")):
        return sym
    exch = exchange or ""
    if re.search(r"TSX\.?V|TSX-V|TSXV|CDNX", exch, re.I):
        return sym + ".V"
    if re.fullmatch(r"TSX|TSE", exch.strip(), re.I):
        return sym + ".TO"
    if re.search(r"\bCSE\b|\bCNSX\b", exch, re.I):
        return sym + ".CN"
    if re.fullmatch(r"NEO", exch.strip(), re.I):
        return sym + ".NE"
    if re.search(r"\b(LSE|AIM|ASX|HKEX|TYO|XETRA|FRA|EPA|STO|KOSDAQ|SGX)\b", exch, re.I):
        return None
    if re.search(r"NASDAQ|NYSE|AMEX|OTC|PINK", exch, re.I):
        return sym
    return None


def _tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if w not in NAME_DROP and not w.isdigit()]


def pick_quote(quotes, query):
    """Best US/Canada equity whose name matches the query. None when the match is ambiguous."""
    qtokens = _tokens(query)
    long_q = [t for t in qtokens if len(t) >= 4]
    matches = []
    exact = None
    for quote in quotes or []:
        if quote.get("quoteType") != "EQUITY":
            continue
        if quote.get("exchange") not in US_CA:
            continue
        symbol = quote.get("symbol") or ""
        if query.upper() == symbol.upper() or query.upper() == symbol.upper().split(".")[0]:
            exact = quote
            break
        name_tokens = set(_tokens(quote.get("shortname") or quote.get("longname") or ""))
        if long_q and not all(t in name_tokens for t in long_q):
            continue
        if not (set(qtokens) & name_tokens):
            continue
        matches.append(quote)
    if exact:
        return exact
    if not matches:
        return None
    matches.sort(key=lambda q: ((q.get("score") or 0), EXCHANGE_RANK.get(q.get("exchange"), 0)), reverse=True)
    best = matches[0]
    if len(matches) > 1:
        second = matches[1]
        same = bool({t for t in set(_tokens(best.get("shortname"))) & set(_tokens(second.get("shortname"))) if len(t) >= 5})
        s1 = best.get("score") or 0
        s2 = second.get("score") or 0
        if not same and s1 and s2 >= 0.8 * s1:
            return None
    return best


def _long_hit(text):
    for match in LONG_RE.finditer(text or ""):
        span = match.group(0).lower()
        if re.search(r"\b(not|never|no)\b|n't", span):
            continue
        pre = (text or "")[max(0, match.start() - 16):match.start()].lower()
        if re.search(r"\b(may|might|not|no)\b", pre):
            continue
        return True
    return False


def stance(title, subtitle, body):
    """long, exclude, or unclear. body=None means only the title and subtitle are known."""
    head = f"{title or ''} {subtitle or ''}"
    if SKIP_TITLE.search(head) or EXIT_TITLE.search(head):
        return "exclude"
    if SHORT_RE.search(head) or HOLD_RE.search(head):
        return "exclude"
    blob = head if body is None else head + "\n" + body
    if body is not None and EXIT_BODY.search(body) and not STILL_LONG.search(body):
        return "exclude"
    if body is not None and (SHORT_RE.search(body) or HOLD_RE.search(body)) and not _long_hit(body):
        return "exclude"
    if _long_hit(blob if body is not None else head):
        return "long"
    return "unclear"


def _add(scores, kinds, symbol, weight, kind):
    if not symbol:
        return
    scores[symbol] = scores.get(symbol, 0) + weight
    kinds.setdefault(symbol, kind)


def title_symbols(title, subtitle):
    """Tickers named in the title or subtitle. Exchange tags are not verified again."""
    text = f"{title or ''} {subtitle or ''}"
    scores = {}
    kinds = {}
    found = []
    for match in EXCH_RE.finditer(text):
        yahoo = to_yahoo(match.group(2), match.group(1))
        if not yahoo:
            continue
        found.append((yahoo, match.group(1), match.start()))
        _add(scores, kinds, yahoo, 5, "exchange")
    # "(TSXV: SUM or OTC: SUMMF)" is one company. Keep the listed exchange.
    if len(found) == 2 and abs(found[0][2] - found[1][2]) < 80:
        otc = [item for item in found if OTC_NAMES.search(item[1])]
        listed = [item for item in found if not OTC_NAMES.search(item[1])]
        if len(otc) == 1 and len(listed) == 1:
            scores = {listed[0][0]: 5}
            kinds = {listed[0][0]: "exchange"}
    for match in LABEL_RE.finditer(text):
        yahoo = to_yahoo(match.group(1), "NYSE")
        _add(scores, kinds, yahoo, 4, "ticker")
    return scores, kinds


def body_symbols(text):
    """Weighted ticker mentions. Opening text counts more than a later aside."""
    scores = {}
    kinds = {}
    opening = 1500
    for match in EXCH_RE.finditer(text or ""):
        yahoo = to_yahoo(match.group(2), match.group(1))
        weight = 3 * (3 if match.start() < opening else 1)
        _add(scores, kinds, yahoo, weight, "exchange")
    for match in LABEL_RE.finditer(text or ""):
        yahoo = to_yahoo(match.group(1), "NYSE")
        weight = 3 * (3 if match.start() < opening else 1)
        _add(scores, kinds, yahoo, weight, "ticker")
    for match in CASH_RE.finditer(text or ""):
        raw = match.group(1).upper()
        if not _symbol_ok(raw):
            continue
        weight = 2 * (3 if match.start() < opening else 1)
        _add(scores, kinds, raw, weight, "cashtag")
    for match in PAREN_RE.finditer((text or "")[:opening]):
        raw = match.group(1).upper()
        if not _symbol_ok(raw):
            continue
        _add(scores, kinds, raw, 1, "paren")
    return scores, kinds


def _dominant(scores, kinds):
    """One primary ticker, or None when the post is about several companies."""
    if not scores:
        return None, None
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top, weight = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    kind = kinds.get(top, "")
    if second and weight == second:
        return None, "ambiguous"
    total = sum(scores.values())
    if len(ranked) > 1 and weight < 0.5 * total:
        return None, "ambiguous"
    if weight < 2:
        return None, "weak"
    return top, kind


def clean_company_name(name):
    """Drop a trailing legal suffix so Yahoo sees 'Titan Mining', not 'Titan Mining Company'."""
    text = re.sub(
        r"\b(incorporated|company|corporation|holdings|holding|inc|corp|ltd|limited|group|plc|co)\b\.?",
        " ",
        name or "",
        flags=re.I,
    )
    return re.sub(r"\s+", " ", text).strip(" ,.-")


def company_from_title(title):
    """Company name when the title is 'Acme Corp Q2 Update' rather than a sentence."""
    text = re.sub(r"\([^)]*\)", " ", title or "")
    text = re.sub(r"\$[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b", " ", text)
    text = re.sub(
        r"^(?:trade idea|quick pitch|long|update|deep dive|position disclosure|disclosure)\b\s*[-:|]*\s*",
        "",
        text,
        flags=re.I,
    )
    split = re.match(
        r"^(.{2,80}?)\s*[:|–—-]\s+(?:update|q[1-4]|earnings|post|deep|write|investment|thesis|quick|revisit)\b",
        text,
        re.I,
    )
    if split:
        text = split.group(1)
    text = re.sub(
        r"\b(?:q[1-4]\s*)?(?:20\d\d\s*)?(?:update|earnings|results|review|revisit|write-?up|deep dive|post earnings)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" -–—:|")
    words = text.split()
    if not words or len(words) > 6:
        return None
    if words[0].lower() in {"the", "a", "an", "why", "how", "my", "our", "what", "when", "unpolished", "weekly", "watchlist", "some", "and", "this"}:
        return None
    if len(text) < 3:
        return None
    return text


def _verify_loose(symbol, search):
    """Confirm a bare cashtag or parenthetical is a US/Canada equity."""
    if not search:
        return symbol if _symbol_ok(symbol) else None
    quotes = search(symbol) or []
    for quote in quotes:
        got = (quote.get("symbol") or "").upper()
        if quote.get("quoteType") != "EQUITY" or quote.get("exchange") not in US_CA:
            continue
        if got == symbol.upper() or got.split(".")[0] == symbol.upper():
            return quote.get("symbol")
    return None


def _resolve_scores(scores, kinds, search, verify_bare):
    resolved = {}
    resolved_kinds = {}
    for symbol, weight in scores.items():
        kind = kinds.get(symbol, "")
        if verify_bare and kind in {"cashtag", "paren"}:
            confirmed = _verify_loose(symbol, search)
            if not confirmed:
                continue
            symbol = confirmed
        resolved[symbol] = resolved.get(symbol, 0) + weight
        resolved_kinds.setdefault(symbol, kind)
    return resolved, resolved_kinds


def analyze(title, subtitle, body, search, require_long=True):
    """Decide whether a post is one pitch.

    body is None when the body has not been fetched. Returns a dict with
    status pitch, skip, or need_body.

    require_long=True (the article score) keeps only an explicit long.
    require_long=False (the 2-year batting average) keeps an unclear stance.
    Short, sell, and hold are decided afterwards by bat/longcheck.py.
    Recap, macro, watchlist, foreign, and closed-exit notes are still skipped.
    """
    head = f"{title or ''} {subtitle or ''}"
    if FOREIGN_TAG.search(head):
        return {"status": "skip", "reason": "not US/Canada listed"}
    if SKIP_TITLE.search(head) or EXIT_TITLE.search(head):
        return {"status": "skip", "reason": "not a long pitch (recap, macro, hold, or exit)"}
    head_stance = stance(title, subtitle, None)
    if require_long and head_stance == "exclude":
        return {"status": "skip", "reason": "not a long pitch (recap, macro, hold, or exit)"}
    scores, kinds = title_symbols(title, subtitle)
    # Bare tickers in the title still need a listing check.
    bare_scores = {}
    bare_kinds = {}
    head = f"{title or ''} {subtitle or ''}"
    lead = re.match(r"^([A-Z]{2,5}(?:\.[A-Z]{1,2})?)\s*[-:–—]\s+\S", title or "")
    if not lead:
        lead = re.match(r"^([A-Z]{2,5})\s+(?=[A-Z])", title or "")
    if lead and _symbol_ok(lead.group(1)):
        confirmed = _verify_loose(lead.group(1), search)
        if confirmed:
            _add(scores, kinds, confirmed, 4, "ticker")
    for match in re.finditer(r"\(([A-Z]{1,5})\s+or\s+([A-Z]{1,5})\)", title or ""):
        confirmed = []
        for raw in match.groups():
            if not _symbol_ok(raw):
                continue
            hit = _verify_loose(raw, search)
            if hit:
                confirmed.append(hit)
        if len(confirmed) == 1:
            _add(scores, kinds, confirmed[0], 4, "ticker")
        elif len(confirmed) >= 2:
            # Same company, two lines. Keep the first verified symbol.
            _add(scores, kinds, confirmed[0], 4, "ticker")
    for match in TITLE_CASH_RE.finditer(head):
        raw = match.group(1).upper()
        if _symbol_ok(raw):
            _add(bare_scores, bare_kinds, raw, 4, "cashtag")
    for match in PAREN_RE.finditer(head):
        raw = match.group(1).upper()
        if _symbol_ok(raw) and raw not in scores:
            _add(bare_scores, bare_kinds, raw, 2, "paren")
    bare_scores, bare_kinds = _resolve_scores(bare_scores, bare_kinds, search, verify_bare=True)
    for symbol, weight in bare_scores.items():
        _add(scores, kinds, symbol, weight, bare_kinds.get(symbol, "cashtag"))
    ticker, kind = _dominant(scores, kinds)
    ambiguous = kind == "ambiguous" or (len(scores) >= 2 and ticker is None)
    if ticker and not ambiguous:
        if not require_long and body and EXIT_BODY.search(body) and not STILL_LONG.search(body):
            return {"status": "skip", "reason": "not a long pitch (recap, macro, hold, or exit)"}
        if not require_long or head_stance == "long":
            conf = 0.9 if kind in {"exchange", "cashtag", "ticker"} else 0.8
            return {"status": "pitch", "ticker": ticker, "method": "title", "confidence": conf, "reason": "title names one ticker"}
        if body is None:
            return {"status": "need_body", "have_ticker": True, "reason": "title ticker, stance not in the title"}
        if stance(title, subtitle, body) == "long":
            conf = 0.9 if kind in {"exchange", "cashtag", "ticker"} else 0.8
            return {"status": "pitch", "ticker": ticker, "method": "title", "confidence": conf, "reason": "title names one ticker"}
        return {"status": "skip", "reason": "no long stance"}
    if body is None:
        return {"status": "need_body", "have_ticker": False, "reason": "no or ambiguous ticker in the title"}
    if body and EXIT_BODY.search(body) and not STILL_LONG.search(body):
        return {"status": "skip", "reason": "not a long pitch (recap, macro, hold, or exit)"}
    if require_long:
        full = stance(title, subtitle, body)
        if full != "long":
            return {"status": "skip", "reason": "no long stance" if full == "unclear" else "not a long pitch (recap, macro, hold, or exit)"}
    bscores, bkinds = body_symbols(body)
    bscores, bkinds = _resolve_scores(bscores, bkinds, search, verify_bare=True)
    ticker, kind = _dominant(bscores, bkinds)
    name = company_from_title(title)
    if not name and body:
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if 0 < len(first) <= 80:
            name = company_from_title(first)
    title_symbol = None
    if name and search:
        query = clean_company_name(name)
        hit = pick_quote(search(query) or [], query)
        if hit and hit.get("symbol"):
            title_symbol = hit["symbol"]
    # A holding-company writeup names subsidiaries in the body. The title company is the pitch.
    if title_symbol and ticker and ticker.split(".")[0] != title_symbol.split(".")[0]:
        return {
            "status": "pitch",
            "ticker": title_symbol,
            "method": "body",
            "confidence": 0.65,
            "reason": "company name via Yahoo",
        }
    if ticker and kind != "ambiguous":
        conf = 0.8 if kind in {"exchange", "ticker"} else 0.7
        return {"status": "pitch", "ticker": ticker, "method": "body", "confidence": conf, "reason": "body mentions one ticker"}
    if kind == "ambiguous" and not title_symbol:
        return {"status": "skip", "reason": "several tickers, no primary"}
    if title_symbol:
        return {
            "status": "pitch",
            "ticker": title_symbol,
            "method": "body",
            "confidence": 0.6,
            "reason": "company name via Yahoo",
        }
    return {"status": "skip", "reason": "no single ticker"}


def dedupe_windows(pitches, today=None):
    """One pitch per ticker in the 2-year window, the 1-year window, and the not-yet-mature recent bucket."""
    bounds = batcalc.window_bounds(today)
    recent_start = bounds["1y"][1]
    seen = {"2y": set(), "1y": set(), "recent": set()}
    kept = []
    ordered = sorted(pitches, key=lambda row: row.get("date") or "")
    for row in ordered:
        day = row.get("date") or ""
        ticker = row.get("ticker") or ""
        if bounds["2y"][0] <= day < bounds["2y"][1]:
            bucket = "2y"
        elif bounds["1y"][0] <= day < bounds["1y"][1]:
            bucket = "1y"
        elif day >= recent_start:
            bucket = "recent"
        else:
            continue
        if ticker in seen[bucket]:
            continue
        seen[bucket].add(ticker)
        kept.append(row)
    return kept


def _cache_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _write_json(path, data):
    ensure(os.path.dirname(path))
    json.dump(data, open(path, "w", encoding="utf-8"))


def fetch_archive_page(host, offset, limiter, cache_dir):
    path = os.path.join(cache_dir, "substack_archive", host, f"{offset}.json")
    cached = _cache_json(path)
    if cached is not None:
        return cached
    if time.time() > DEADLINE[0]:
        raise TimeoutError("author budget exceeded")
    limiter.wait()
    from prices import hard_get

    response = hard_get(
        f"https://{host}/api/v1/archive",
        params={"sort": "new", "offset": offset, "limit": 50},
        headers={"User-Agent": user_agent()},
        wall=20,
        timeout=(5, 8),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("archive was not a list")
    _write_json(path, data)
    return data


def fetch_post(host, slug, limiter, cache_dir):
    safe = re.sub(r"[^a-zA-Z0-9.-]+", "-", slug)[:90]
    path = os.path.join(cache_dir, "substack_posts", host, safe + ".json")
    cached = _cache_json(path)
    if cached is not None:
        return cached
    if time.time() > DEADLINE[0]:
        raise TimeoutError("author budget exceeded")
    limiter.wait()
    from prices import hard_get

    response = hard_get(
        f"https://{host}/api/v1/posts/{slug}",
        headers={"User-Agent": user_agent()},
        wall=20,
        timeout=(5, 8),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "body_html" not in data and "title" not in data:
        raise ValueError("post payload was not a post")
    _write_json(path, data)
    return data


def body_from_post(payload):
    """Plain text, and whether the public body is only a preview."""
    text = html_to_text(payload.get("body_html") or "")
    words = len(text.split())
    listed = payload.get("wordcount") or 0
    preview = bool(payload.get("truncated_body_text")) and words < max(80, 0.5 * listed)
    if payload.get("audience") not in (None, "everyone") and words < 80:
        preview = True
    return text, preview


def iter_archive(host, limiter, cache_dir, limit, since):
    seen = 0
    offset = 0
    while True:
        page = fetch_archive_page(host, offset, limiter, cache_dir)
        if not page:
            return
        for post in page:
            day = (post.get("post_date") or "")[:10]
            if since and day and day < since:
                return
            if post.get("type") not in (None, "newsletter"):
                continue
            seen += 1
            yield post
            if limit and seen >= limit:
                return
        if len(page) < 50:
            return
        offset += 50


def collect_author(subdomain, limit=0, since=None, sleep=1.0, cache_dir=None, search=None, today=None):
    """Detect pitches for one Substack subdomain. search=None uses Yahoo."""
    host = subdomain if "." in subdomain else f"{subdomain}.substack.com"
    sub = host.split(".")[0]
    cache_dir = cache_dir or CACHE
    limiter = Limiter(sleep)
    if since is None:
        since = batcalc.window_bounds(today)["2y"][0]
    if search is None:
        def search(query):
            try:
                data = _yahoo(query, limiter, cache_dir)
            except Exception:
                return []
            return (data or {}).get("quotes") or []

    pitches = []
    skipped = {}
    fetched = 0
    seen = 0
    for post in iter_archive(host, limiter, cache_dir, limit, since):
        seen += 1
        title = post.get("title") or ""
        subtitle = post.get("subtitle") or ""
        decision = analyze(title, subtitle, None, search)
        if decision["status"] == "need_body":
            slug = post.get("slug") or ""
            if not slug:
                skipped["no slug"] = skipped.get("no slug", 0) + 1
                continue
            try:
                payload = fetch_post(host, slug, limiter, cache_dir)
            except Exception:
                skipped["post fetch failed"] = skipped.get("post fetch failed", 0) + 1
                continue
            fetched += 1
            text, preview = body_from_post(payload)
            if preview and not decision.get("have_ticker"):
                # Title had no ticker and the public body is a preview. Do not guess.
                skipped["preview only"] = skipped.get("preview only", 0) + 1
                continue
            decision = analyze(title, subtitle, text or "", search)
        if decision["status"] != "pitch":
            reason = decision.get("reason") or "skipped"
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        url = post.get("canonical_url") or f"https://{host}/p/{post.get('slug')}"
        pitches.append(
            {
                "ticker": decision["ticker"],
                "date": (post.get("post_date") or "")[:10],
                "url": url,
                "title": title,
                "method": decision["method"],
                "confidence": decision["confidence"],
                "reason": decision.get("reason") or "",
            }
        )
    kept = dedupe_windows(pitches, today)
    return {
        "subdomain": sub,
        "host": host,
        "posts_seen": seen,
        "bodies_fetched": fetched,
        "pitches": kept,
        "pitches_before_dedupe": pitches,
        "skipped": skipped,
        "since": since,
    }


def _yahoo(query, limiter, cache_dir):
    key = re.sub(r"[^a-z0-9]+", "-", (query or "").lower()).strip("-")[:80] or "q"
    path = os.path.join(cache_dir, "yahoo_search", key + ".json")
    cached = _cache_json(path)
    if cached is not None:
        return cached
    if time.time() > DEADLINE[0]:
        raise TimeoutError("author budget exceeded")
    limiter.wait()
    from prices import hard_get

    response = hard_get(
        "https://query1.finance.yahoo.com/v1/finance/search",
        params={"q": query, "quotesCount": 8, "newsCount": 0},
        headers={"User-Agent": user_agent()},
        wall=20,
        timeout=(5, 8),
    )
    response.raise_for_status()
    data = response.json()
    _write_json(path, data)
    return data


def _clock(day=None):
    """Pandas timestamp for a window anchor. Defaults to today's date."""
    import pandas as pd

    if day is None:
        return pd.Timestamp(dt.date.today())
    return pd.Timestamp(dt.date.fromisoformat(str(day)[:10]))


_EXEC = None
_RL = {}
_RLK = threading.Lock()
_res = {}
_reslock = threading.Lock()


def _executor():
    global _EXEC
    if _EXEC is None:
        import concurrent.futures as cf

        _EXEC = cf.ThreadPoolExecutor(max_workers=32, thread_name_prefix="http")
    return _EXEC


def _rate(host, gap):
    """Polite per-host spacing. Safe to call from worker threads."""
    with _RLK:
        now = time.time()
        nxt = max(_RL.get(host, 0), now)
        _RL[host] = nxt + gap
    if nxt > now:
        time.sleep(nxt - now)


def _get_once(url, params, connect_timeout, read_timeout):
    import requests

    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": user_agent()},
        timeout=(connect_timeout, read_timeout),
        stream=True,
    )
    deadline = time.time() + 30
    chunks = []
    for chunk in response.iter_content(65536):
        chunks.append(chunk)
        if time.time() > deadline:
            response.close()
            raise TimeoutError("body deadline")
    response._content = b"".join(chunks)
    response._content_consumed = True
    return response


def http_get(url, params=None, timeout=(5, 20), wall=35):
    """GET with a hard wall-clock cap. Covers DNS, connect, and a slow body."""
    import concurrent.futures as cf

    if time.time() > DEADLINE[0]:
        raise TimeoutError("author budget exceeded")
    future = _executor().submit(_get_once, url, params, timeout[0], timeout[1])
    try:
        return future.result(timeout=wall)
    except cf.TimeoutError:
        raise TimeoutError("wall timeout " + url[:80])


def _px_dir():
    path = os.path.join(CACHE, "px_bat")
    ensure(path)
    return path


def _px_fetch(symbol):
    """('ok', Series) | ('notfound', None) | ('fail', None). A timeout is 'fail' and is not cached."""
    import pandas as pd

    period1 = int((_clock() - pd.DateOffset(years=4)).timestamp())
    period2 = int(time.time()) + 86400
    for attempt in range(3):
        _rate("yahoo", 0.12)
        host = "query1" if attempt % 2 == 0 else "query2"
        try:
            response = http_get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                {"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"},
                (5, 15),
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(response.status_code)
            payload = response.json()
            chart = payload.get("chart") or {}
            result = chart.get("result")
            if result:
                result = result[0]
                stamps = result.get("timestamp") or []
                quote = result["indicators"]["quote"][0]
                adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose") or quote["close"]
                rows = [(stamp, close) for stamp, close in zip(stamps, adjusted) if close is not None]
                if not rows:
                    return "notfound", None
                series = pd.Series(
                    [close for _stamp, close in rows],
                    index=pd.DatetimeIndex([dt.datetime.fromtimestamp(stamp).date() for stamp, _close in rows]),
                )
                return "ok", series[~series.index.duplicated(keep="last")]
            err = (chart.get("error") or {}).get("code", "")
            if response.status_code == 404 or err == "Not Found":
                return "notfound", None
            raise RuntimeError("chart error " + str(err))
        except Exception:
            time.sleep(2 * (3 ** attempt))
    return "fail", None


def _px_one(symbol):
    import pandas as pd

    path = os.path.join(_px_dir(), symbol.replace("^", "_").replace("/", "_") + ".json")
    if os.path.exists(path):
        cached = json.load(open(path, encoding="utf-8"))
        age = time.time() - os.path.getmtime(path)
        if cached["status"] == "ok" and age < 86400:
            return "ok", pd.Series(cached["v"], index=pd.DatetimeIndex(cached["d"]))
        if cached["status"] == "notfound" and age < 7 * 86400:
            return "notfound", None
    status, series = _px_fetch(symbol)
    if status == "ok":
        json.dump(
            {"status": "ok", "d": [day.strftime("%Y-%m-%d") for day in series.index], "v": [float(value) for value in series.values]},
            open(path, "w", encoding="utf-8"),
        )
    elif status == "notfound":
        json.dump({"status": "notfound"}, open(path, "w", encoding="utf-8"))
    return status, series


def resolve(symbol):
    """'ok', 'notfound', or 'fail'. A bare symbol with no listing is retried as SYM.TO, then SYM.V.

    A timeout ('fail') is not treated as missing and is not followed by the other suffix.
    """
    if symbol in _res and _res[symbol][0] != "fail":
        return _res[symbol]
    status, series = _px_one(symbol)
    resolved = symbol
    if status == "notfound" and "." not in symbol:
        for suffix in (".TO", ".V"):
            status2, series2 = _px_one(symbol + suffix)
            if status2 == "ok":
                status, series, resolved = status2, series2, symbol + suffix
                PXSTAT["fallback_" + suffix[1:]] += 1
                break
            if status2 == "fail":
                status = "fail"
                break
    with _reslock:
        PXSTAT[status] = PXSTAT.get(status, 0) + 1
    _res[symbol] = (status, resolved, series)
    return _res[symbol]


def hist(symbol):
    status, _resolved, series = resolve(symbol)
    return series if status == "ok" else None


def _ret_h(series, day, months, when=None):
    import pandas as pd

    start = pd.Timestamp(day)
    end = start + pd.DateOffset(months=months)
    now = _clock(when)
    if series is None or end > now:
        return None
    after = series[series.index >= start]
    before = series[series.index <= end]
    if after.empty or before.empty or before.index[-1] < end - pd.Timedelta(days=10):
        return None
    return before.iloc[-1] / after.iloc[0] - 1


def ret(symbol, day, months, when=None):
    return _ret_h(hist(symbol), day, months, when)


def bench(symbol, choice="auto"):
    return batcalc.choose_benchmark(symbol, choice)


def prefetch_px(tickers, workers=6, benchmark="auto"):
    """Warm resolve() for tickers and their benchmarks. Same results as calling resolve one by one."""
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(workers) as pool:
        resolved = list(pool.map(lambda symbol: resolve(symbol)[1], tickers))
        list(pool.map(resolve, {bench(symbol, benchmark) for symbol in resolved}))


def window(name, today=None):
    """(start, end, months). 1y is a 12-month cohort held 12 months. 2y is a 12-month cohort held 24 months."""
    if name == "1y":
        return batcalc.cohort(today, 12, 12)
    return batcalc.cohort(today, 12, 24)


def _pitch_row(row):
    """ticker, date, method, url, title. method defaults to title."""
    if isinstance(row, dict):
        return (
            row.get("ticker") or "",
            (row.get("date") or "")[:10],
            row.get("method") or "title",
            row.get("url") or "",
            row.get("title") or "",
        )
    symbol = row[0]
    day = (row[1] or "")[:10]
    method = row[2] if len(row) > 2 else "title"
    # (ticker, date, method, confidence) is the author_pitches shape.
    # (ticker, date, method, url, title) is the report shape.
    url = ""
    title = ""
    if len(row) >= 5:
        url = row[3] or ""
        title = row[4] or ""
    return symbol, day, method, url, title


def _buyout_return(symbol, series, day, months):
    """Buyout price over the start close, when the deal date falls inside the hold."""
    import pandas as pd

    deal = batcalc.BUY.get(str(symbol).split(".")[0])
    if not deal or series is None or len(getattr(series, "index", [])) == 0:
        return None
    d0 = pd.Timestamp(day)
    d1 = d0 + pd.DateOffset(months=months)
    if pd.Timestamp(deal[0]) >= d1:
        return None
    after = series[series.index >= d0]
    if after.empty or not after.iloc[0]:
        return None
    return deal[1] / float(after.iloc[0]) - 1


def score(pitches, window_name="2y", today=None, window_months=None, duration_months=None, benchmark="auto"):
    """Price kept pitches. Timeouts are lost_fail. A real Not Found is lost_notfound. Neither is in n.

    window_name selects the 12-month cohort held 12 months (1y) or 24 months (2y).
    window_months and duration_months override that when both are set.
    """
    import statistics

    if window_months is None or duration_months is None:
        start, end, months = window(window_name, today)
    else:
        start, end, months = batcalc.cohort(today, window_months, duration_months)
    keyed = []
    for row in pitches or []:
        symbol, day, method, url, title = _pitch_row(row)
        keyed.append((day, symbol, method, url, title))
    symbols = sorted({symbol for day, symbol, _method, _url, _title in keyed if start <= day < end and symbol})
    if symbols:
        prefetch_px(symbols, benchmark=benchmark)
    seen = set()
    excess = []
    stock_rets = []
    detail = []
    excluded = []
    hits = n_title = n_body = lost_fail = lost_notfound = lost_nodata = 0
    for day, symbol, method, url, title in sorted(keyed, key=lambda item: item[0]):
        if not (start <= day < end) or not symbol or symbol in seen:
            continue
        seen.add(symbol)
        status, resolved, series = resolve(symbol)
        if status == "fail":
            lost_fail += 1
            excluded.append(dict(ticker=symbol, date=day, why="timeout"))
            continue
        if status == "notfound":
            lost_notfound += 1
            excluded.append(dict(ticker=symbol, date=day, why="not found"))
            continue
        bm_symbol = bench(resolved, benchmark)
        bench_status, _bench_symbol, bench_series = resolve(bm_symbol)
        if bench_status != "ok":
            lost_fail += 1
            excluded.append(dict(ticker=symbol, date=day, why="benchmark " + bm_symbol))
            continue
        stock_ret = _ret_h(series, day, months, today)
        if stock_ret is None:
            stock_ret = _buyout_return(resolved, series, day, months)
        bench_ret = _ret_h(bench_series, day, months, today)
        if stock_ret is None or bench_ret is None:
            lost_nodata += 1
            excluded.append(dict(ticker=resolved, date=day, why="no completed price"))
            continue
        stock_rets.append(stock_ret)
        excess.append(stock_ret - bench_ret)
        hit = int(stock_ret > bench_ret)
        hits += hit
        n_title += method == "title"
        n_body += method == "body"
        detail.append(
            dict(
                ticker=resolved,
                date=day,
                url=url,
                title=title,
                method=method,
                stock_ret=round(float(stock_ret), 4),
                bench=bm_symbol,
                bench_ret=round(float(bench_ret), 4),
                hit=hit,
            )
        )
    return {
        "hits": int(hits),
        "n": len(excess),
        "pct": round(float(hits) / len(excess), 3) if excess else None,
        "median_return": round(float(statistics.median(stock_rets)), 4) if stock_rets else None,
        "median_excess": round(float(statistics.median(excess)), 4) if excess else None,
        "n_title": n_title,
        "n_body": n_body,
        "lost_fail": lost_fail,
        "lost_notfound": lost_notfound,
        "lost_nodata": lost_nodata,
        "rows": detail,
        "excluded": excluded,
        "start": start,
        "end": end,
        "months": months,
    }


def substack_archive(sub, oldest="2023-01-01", pause=0.5, full=False):
    """Pages of the public archive. None when the first page does not load."""
    posts = []
    offset = 0
    while True:
        url = f"https://{sub}.substack.com/api/v1/archive?sort=new&offset={offset}&limit=50"
        try:
            page = http_get(url).json()
        except Exception:
            time.sleep(3)
            try:
                page = http_get(url).json()
            except Exception:
                return None if not posts else posts
        if not page:
            break
        for post in page:
            title = post.get("title") or ""
            day = (post.get("post_date") or "")[:10]
            if full:
                posts.append((title, day, post.get("slug") or ""))
            else:
                posts.append((title, day))
        if (page[-1].get("post_date") or "")[:10] < oldest:
            break
        offset += 50
        time.sleep(pause)
    return posts


# Title parser used by the batting-average pass. TSX and TSXV both map to .TO, matching the run that produced the stored averages.
_TITLE_EX = [
    (re.compile(r"\((?:NYSE|NASDAQ|NYSE ?American|AMEX|OTC\w*)\s*:\s*([A-Z]{1,5})\)", re.I), ""),
    (re.compile(r"\((?:TSX|TSX-?V|CVE|TSXV)\s*:\s*([A-Z]{1,5})\)", re.I), ".TO"),
    (re.compile(r"\$([A-Z]{1,5})\b"), ""),
    (re.compile(r"^([A-Z]{2,5})\s*[-–:]\s"), ""),
    (re.compile(r"\(([A-Z]{2,5})\)"), ""),
]


def ticker_of(title):
    """The single ticker named in a title, or None. Long disclosure is not checked here."""
    found = set()
    for pattern, suffix in _TITLE_EX:
        for match in pattern.finditer(title or ""):
            found.add(match.group(1).upper() + suffix)
    return found.pop() if len(found) == 1 else None


_BODY_CACHE = os.path.join(CACHE, "pitch_bodies")
_US_EXCH = {"NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "BTS", "OQB", "OQX", "PNK", "NYS", "NAS", "NASDAQ", "NYSE", "OTC"}
_TAGS = [
    (re.compile(r"\((?:NYSE|NASDAQ|NYSE ?American|AMEX|OTC\w*)\s*:\s*([A-Z]{1,5})\)", re.I), ""),
    (re.compile(r"\((?:TSX|TSX-?V|CVE|TSXV)\s*:\s*([A-Z]{1,5})\)", re.I), ".TO"),
    (re.compile(r"\b(?:NYSE|NASDAQ|AMEX)\s*:\s*([A-Z]{1,5})\b"), ""),
    (re.compile(r"\b(?:TSX|TSXV|TSX-V)\s*:\s*([A-Z]{1,5})\b"), ".TO"),
    (re.compile(r"\b[Tt]icker(?: symbol)?\s*:?\s*\(?\$?([A-Z]{1,5})\b"), ""),
    (re.compile(r"\$([A-Z]{1,5})\b"), ""),
]
_BEAR = re.compile(
    r"\b(i am short|i'm short|short thesis|short position|short seller|sell rating|downgrade|overvalued|avoid this|stay away|short it|bearish)\b",
    re.I,
)
_LONGD = re.compile(
    r"\b(i own|i am long|i'm long|we own|we are long|i hold a position|i have a position|my position|a position in|i have been buying|i bought|i've bought|i added|i initiated|initiated a position|i am a shareholder|i'm a shareholder|long position|disclosure[^.]{0,80}\b(long|own|position|shares))\b",
    re.I,
)
_BUYL = re.compile(
    r"\b(buy rating|i rate (it|this|the stock) a buy|undervalued|margin of safety|price target|fair value|upside|investment thesis|bull case|why i (like|own|bought|am buying)|multibagger|re-?rating|intrinsic value|cheap)\b",
    re.I,
)
_NOTPITCH = re.compile(
    r"\b(weekly|monthly|quarterly (letter|update)|recap|round-?up|links|newsletter|macro|market (update|commentary)|portfolio update|year in review|letter to|podcast|interview|q&a|reading list|short(s)? (report|thesis)|why i sold|sell)\b",
    re.I,
)
_NAME_STOP = set(
    "the a an of in on and for to is are why how what this that stock shares company buy hold sell update earnings q1 q2 q3 q4 results deep dive thesis my our new investing idea ideas small cap value case bull bear".split()
)


def _body_path(name):
    ensure(_BODY_CACHE)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return os.path.join(_BODY_CACHE, safe + ".json")


def post_body(sub, slug):
    """Plain text of a public Substack post. Cached. None when the fetch fails. Paywalled posts return the preview only."""
    path = _body_path(f"{sub}__{slug}")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8")).get("text")
    _rate("substack", 0.15)
    try:
        response = http_get(f"https://{sub}.substack.com/api/v1/posts/{slug}")
        if response.status_code == 429:
            time.sleep(10)
            response = http_get(f"https://{sub}.substack.com/api/v1/posts/{slug}")
        if response.status_code != 200:
            return None
        raw = response.json().get("body_html") or ""
    except Exception:
        return None
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))).strip()
    json.dump({"text": text}, open(path, "w", encoding="utf-8"))
    return text


def lookup(query):
    """Yahoo search, cached. Each hit is symbol, name, exch, type."""
    path = _body_path("yq_" + (query or "").lower()[:80])
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    _rate("yahoo", 0.12)
    try:
        payload = http_get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            {"q": query, "quotesCount": 6, "newsCount": 0},
            (5, 15),
        ).json()
        out = [
            {
                "symbol": item["symbol"],
                "name": item.get("longname") or item.get("shortname") or "",
                "exch": item.get("exchange", ""),
                "type": item.get("quoteType", ""),
            }
            for item in payload.get("quotes", [])
        ]
    except Exception:
        return []
    json.dump(out, open(path, "w", encoding="utf-8"))
    return out


def norm_symbol(symbol, exchange):
    """Yahoo symbol for a US or Canada equity, or None."""
    if exchange in ("TOR",) or str(symbol).endswith(".TO"):
        return symbol if str(symbol).endswith(".TO") else symbol + ".TO"
    if exchange in ("VAN", "CNQ") or str(symbol).endswith(".V"):
        return symbol if str(symbol).endswith(".V") else symbol + ".V"
    if exchange in _US_EXCH and "." not in str(symbol):
        return symbol
    return None


def valid_us_ca(symbol):
    """Bare ticker to a Yahoo symbol when Yahoo lists it as a US or Canada equity."""
    base = str(symbol).split(".")[0]
    for item in lookup(base):
        if item["type"] == "EQUITY" and item["symbol"].split(".")[0].upper() == base.upper():
            normalized = norm_symbol(item["symbol"], item["exch"])
            if normalized and (normalized.endswith((".TO", ".V")) == str(symbol).endswith((".TO", ".V"))):
                return normalized
    return None


def _name_candidates(title):
    text = re.sub(r"[\(\[].*?[\)\]]", "", title or "")
    if re.search(r"[:|–—-]\s", text):
        text = re.split(r"[:|–—-]\s", text)[0]
    caps = re.findall(r"(?:[A-Z][\w&'.]*)(?:\s+(?:[A-Z][\w&'.]*|of|and|&))*", text)
    return [item.strip() for item in caps if len(item.strip()) > 2 and item.strip().lower() not in _NAME_STOP][:3]


def infer_from_body(title, text):
    """(ticker, confidence) or None. One dominant US/Canada ticker and a bullish or long stance."""
    if not text or len(text) < 400 or _NOTPITCH.search(title or ""):
        return None
    counts = {}
    for pattern, suffix in _TAGS:
        for match in pattern.finditer(text):
            symbol = match.group(1).upper() + suffix
            counts[symbol] = counts.get(symbol, 0) + (2 if match.start() < 2000 else 1)
    counts = {key: value for key, value in counts.items() if key not in {"USD", "CAD", "EPS", "CEO", "CFO", "ROE", "ROIC", "FCF", "AI", "EV", "US", "IPO", "ETF", "NAV"}}
    via = "tag"
    if not counts:
        via = "name"
        for name in _name_candidates(title):
            if len(re.findall(re.escape(name), text)) < 3:
                continue
            for item in lookup(name):
                normalized = norm_symbol(item["symbol"], item["exch"])
                if item["type"] == "EQUITY" and normalized and item["name"] and name.lower().split()[0] in item["name"].lower():
                    counts[normalized] = 3
                    break
            if counts:
                break
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    top, weight = ranked[0]
    if len(ranked) > 1 and ranked[1][1] * 2 > weight:
        return None
    if weight < 2:
        return None
    bear = len(_BEAR.findall(text))
    owned = len(_LONGD.findall(text))
    buy = len(_BUYL.findall(text))
    if bear >= 2 and bear > owned + buy:
        return None
    if owned == 0 and buy < 2:
        return None
    if not top.endswith((".TO", ".V")):
        confirmed = valid_us_ca(top)
        if not confirmed:
            return None
        top = confirmed
    else:
        base = top.split(".")[0]
        hits = [item for item in lookup(base) if item["type"] == "EQUITY" and item["symbol"].upper().startswith(base.upper() + ".")]
        if hits:
            top = norm_symbol(hits[0]["symbol"], hits[0]["exch"]) or top
    if owned > 0 and via == "tag":
        confidence = "high"
    elif owned > 0 or via == "tag":
        confidence = "medium"
    else:
        confidence = "low"
    return top, confidence


def author_pitches(sub, detail=True, today=None, body_fallback=True):
    """Pitches for one Substack subdomain, or None when the archive does not load.

    detail=True returns (ticker, date, 'title'|'body', confidence). Otherwise (ticker, date).
    Posts from 1–3 years ago have their bodies fetched in parallel. longcheck.exclude_reason
    drops a short, a sell, or a hold unless is_long is 'long'. An unclear pitch with no such
    signal still counts. Exclusions land in EXCL_LOG as (subdomain, date, ticker, reason, method).
    """
    import concurrent.futures as cf
    import longcheck

    del EXCL_LOG[:]
    posts = substack_archive(sub, full=True)
    if posts is None:
        return None
    anchor = _clock(today)
    import pandas as pd

    start = (anchor - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    end = (anchor - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    todo = [slug for _title, day, slug in posts if slug and start <= day < end]
    if todo:
        with cf.ThreadPoolExecutor(6) as pool:
            list(pool.map(lambda slug: post_body(sub, slug), todo))
    out = []
    for title, day, slug in posts:
        ticker = ticker_of(title)
        in_window = bool(slug) and start <= day < end
        if ticker:
            if in_window:
                reason = longcheck.exclude_reason(title, post_body(sub, slug) or "")
                if reason[0]:
                    EXCL_LOG.append((sub, day, ticker, reason[0], "title"))
                    continue
            out.append((ticker, day, "title", "high"))
            continue
        if not body_fallback or not in_window:
            continue
        text = post_body(sub, slug)
        inferred = infer_from_body(title, text)
        if not inferred:
            continue
        reason = longcheck.exclude_reason(title, text or "")
        if reason[0]:
            EXCL_LOG.append((sub, day, inferred[0], reason[0], "body"))
            continue
        out.append((inferred[0], day, "body", inferred[1]))
    return out if detail else [row[:2] for row in out]
def _self_test():
    """Offline checks. No network."""
    quotes = {
        "RKT": [{"symbol": "RKT", "shortname": "Rocket Companies", "quoteType": "EQUITY", "exchange": "NYQ", "score": 50}],
        "MIAX": [{"symbol": "MIAX", "shortname": "Miami International Holdings", "quoteType": "EQUITY", "exchange": "NYQ", "score": 50}],
        "SPY": [{"symbol": "SPY", "shortname": "SPDR S&P 500", "quoteType": "ETF", "exchange": "PCX", "score": 99}],
        "CCOI": [{"symbol": "CCOI", "shortname": "Cogent Communications", "quoteType": "EQUITY", "exchange": "NMS", "score": 40}],
        "TITAN MINING": [
            {"symbol": "TII", "shortname": "Titan Mining Corporation", "quoteType": "EQUITY", "exchange": "ASE", "score": 21075},
            {"symbol": "TI.TO", "shortname": "TITAN MINING CORPORATION", "quoteType": "EQUITY", "exchange": "TOR", "score": 20177},
        ],
        "DELEK US": [
            {"symbol": "DK", "shortname": "Delek US Holdings, Inc.", "quoteType": "EQUITY", "exchange": "NYQ", "score": 22000},
        ],
        "GXO": [{"symbol": "GXO", "shortname": "GXO Logistics", "quoteType": "EQUITY", "exchange": "NYQ", "score": 10}],
        "JVA": [{"symbol": "JVA", "shortname": "Coffee Holding Co", "quoteType": "EQUITY", "exchange": "ASE", "score": 10}],
        "NL": [{"symbol": "NL", "shortname": "NL Industries", "quoteType": "EQUITY", "exchange": "NYQ", "score": 20}],
        "NL INDUSTRIES": [{"symbol": "NL", "shortname": "NL Industries", "quoteType": "EQUITY", "exchange": "NYQ", "score": 20}],
        "DDI": [{"symbol": "DDI", "shortname": "DoubleDown Interactive", "quoteType": "EQUITY", "exchange": "NMS", "score": 20}],
        "CIX": [{"symbol": "CIX", "shortname": "CompX International", "quoteType": "EQUITY", "exchange": "ASE", "score": 20}],
        "Q": [{"symbol": "Q", "shortname": "Qnity Electronics", "quoteType": "EQUITY", "exchange": "NYQ", "score": 30}],
    }

    def search(query):
        return quotes.get((query or "").upper(), [])

    assert company_from_title("Titan Mining Q2 Update") == "Titan Mining"
    assert company_from_title("Position Disclosure: Delek US") == "Delek US"
    assert company_from_title("The Tiniest Stock That Ever Made Me Money") is None
    assert to_yahoo("SUM", "TSXV") == "SUM.V"
    assert to_yahoo("CCOI", "NASDAQ") == "CCOI"
    assert to_yahoo("7203", "TYO") is None

    long = analyze("Trade Idea - LONG $RKT for a Rocket!", "A quick pitch", None, search)
    assert long["status"] == "pitch" and long["ticker"] == "RKT" and long["method"] == "title", long

    watch = analyze("Watchlist Radar - Week 30", "Noodles & Co", None, search)
    assert watch["status"] == "skip", watch

    closed = analyze("$BBW - Build-A-Bear Workshop (CLOSED)", "", "The author holds a long position.", search)
    assert closed["status"] == "skip", closed

    need = analyze("Cogent Communications (NASDAQ: CCOI)", "Looking under the hood.", None, search)
    assert need["status"] == "need_body", need
    bought = analyze("Cogent Communications (NASDAQ: CCOI)", "", "So why am I buying? The core business is fine.", search)
    assert bought["status"] == "pitch" and bought["method"] == "title" and bought["ticker"] == "CCOI", bought

    titan_need = analyze("Titan Mining Q2 Update", "Market finally taking notice?", None, search)
    assert titan_need["status"] == "need_body", titan_need
    titan = analyze(
        "Titan Mining Q2 Update",
        "",
        "Titan is one of my highest conviction investments. My cost is a bit higher. Recapping the thesis.",
        search,
    )
    assert titan["status"] == "pitch" and titan["ticker"] == "TII" and titan["method"] == "body", titan

    delek = analyze("Position Disclosure: Delek US", "", "I own shares.", search)
    assert delek["ticker"] == "DK" and delek["method"] == "body", delek

    dual = analyze("Summit Royalties (TSXV: SUM or OTC: SUMMF)", "I own a position", None, search)
    assert dual["status"] == "pitch" and dual["ticker"] == "SUM.V" and dual["method"] == "title", dual

    may = analyze("Weekly letter", "", "The author may hold positions in names discussed. No thesis here.", search)
    assert may["status"] == "skip", may

    spy = analyze("LONG $SPY", "macro basket", None, search)
    assert spy["status"] != "pitch" or spy.get("ticker") != "SPY", spy

    ambiguous = analyze(
        "AAA (NYSE: AAA) and BBB (NYSE: BBB)",
        "I own both",
        "NYSE: AAA is one idea. NYSE: BBB is the other. I own both.",
        search,
    )
    assert ambiguous["status"] == "skip", ambiguous
    miax = analyze("Miami International Holdings (MIAX)", "I own shares", None, search)
    assert miax["status"] == "pitch" and miax["ticker"] == "MIAX" and miax["method"] == "title", miax
    assert company_from_title("Genius Sports: Update Post Earnings") == "Genius Sports"
    jva = analyze("JVA- Coffee Holding Co (buy)", "", None, search)
    assert jva["status"] == "pitch" and jva["ticker"] == "JVA" and jva["method"] == "title", jva
    nl = analyze("NL Industries", "", "I own the holding company. CompX (Ticker: CIX) is the subsidiary. Ticker: CIX again.", search)
    assert nl["status"] == "pitch" and nl["ticker"] == "NL", nl
    ddi = analyze("DDI Double Down Interactive (Brief writeup)", "", "I decided to buy.", search)
    assert ddi["status"] == "pitch" and ddi["ticker"] == "DDI" and ddi["method"] == "title", ddi
    assert clean_company_name("Titan Mining Company") == "Titan Mining"
    one = analyze("LONG $Q - 1Q26 ER Update", "", None, search)
    assert one["status"] == "pitch" and one["ticker"] == "Q" and one["method"] == "title", one
    japan = analyze("Nintendo (TYO: 7974)", "I own shares", None, search)
    assert japan["status"] == "skip" and japan["reason"] == "not US/Canada listed", japan
    unclear = analyze("JVA- Coffee Holding Co", "", None, search, require_long=False)
    assert unclear["status"] == "pitch" and unclear["ticker"] == "JVA", unclear
    held = analyze("JVA- Coffee Holding Co", "", "Recommendation: Hold.", search, require_long=False)
    assert held["status"] == "pitch" and held["ticker"] == "JVA", held

    pitches = dedupe_windows(
        [
            {"ticker": "AAA", "date": "2024-05-01", "url": "a", "title": "a", "method": "title", "confidence": 0.9},
            {"ticker": "AAA", "date": "2024-06-01", "url": "b", "title": "b", "method": "body", "confidence": 0.6},
            {"ticker": "BBB", "date": "2026-01-02", "url": "c", "title": "c", "method": "body", "confidence": 0.6},
        ],
        today=dt.date(2026, 10, 15),
    )
    assert len(pitches) == 2, pitches
    assert pitches[0]["method"] == "title"
    assert ticker_of("LONG $RKT") == "RKT"
    assert ticker_of("(TSXV: SUM)") == "SUM.TO"
    assert ticker_of("(NYSE: AAA) and (NASDAQ: BBB)") is None

    saved_archive = substack_archive
    saved_body = post_body
    saved_res = dict(_res)

    def fake_archive(sub, oldest="2023-01-01", pause=0.5, full=False):
        return [
            ("I am short XYZ (NYSE: XYZ)", "2024-06-01", "short-slug"),
            ("Recommendation: Hold (NYSE: HHH)", "2024-06-02", "hold-slug"),
            ("Note (NYSE: OKK)", "2024-06-03", "ok-slug"),
        ]

    def fake_body(sub, slug):
        return {
            "short-slug": "I am short XYZ.",
            "hold-slug": "Recommendation: Hold.",
            "ok-slug": "The business grew and the franchise is intact.",
        }.get(slug, "")

    try:
        globals()["substack_archive"] = fake_archive
        globals()["post_body"] = fake_body
        found = author_pitches("example", detail=True, today=dt.date(2026, 10, 16))
    finally:
        globals()["substack_archive"] = saved_archive
        globals()["post_body"] = saved_body
        _res.clear()
        _res.update(saved_res)
    tickers = [row[0] for row in found]
    assert tickers == ["OKK"], (tickers, EXCL_LOG)
    reasons = {(row[2], row[3]) for row in EXCL_LOG}
    assert reasons == {("XYZ", "short"), ("HHH", "hold")}, reasons

    saved_px = _px_one
    _res.clear()
    _res["MISS"] = ("notfound", "MISS", None)
    _res["SLOW"] = ("fail", "SLOW", None)

    def fake_px(symbol):
        if symbol in _res:
            return _res[symbol][0], _res[symbol][2]
        return "notfound", None

    try:
        globals()["_px_one"] = fake_px
        priced = score(
            [("MISS", "2024-06-01", "title"), ("SLOW", "2024-06-02", "body")],
            "2y",
            today=dt.date(2026, 10, 16),
        )
    finally:
        globals()["_px_one"] = saved_px
        _res.clear()
    assert priced["n"] == 0 and priced["lost_notfound"] == 1 and priced["lost_fail"] == 1, priced
    print("lib self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test())
