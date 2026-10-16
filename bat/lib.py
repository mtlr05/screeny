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


# author_pitches fills this. Each entry is (ticker, date, title, reason).
EXCL_LOG = []
# compute_ba sets this to time.time() + budget. 1e18 means no budget.
DEADLINE = [1e18]
PXSTAT = {}


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


def window(name, today=None):
    """(start, end, months) for '1y' or '2y'. End is exclusive."""
    return batcalc.window_bounds(today)[name]


def _past_deadline():
    return time.time() > DEADLINE[0]


def author_pitches(sub, detail=True, today=None):
    """Pitches in the 2-year window for one Substack subdomain.

    Returns None when the archive itself does not load. Bodies are fetched
    for every post in the window so a hold or short in the body is visible.
    Unclear stance counts. bat.longcheck.exclude_reason drops short, sell,
    and hold-without-ownership into EXCL_LOG.
    """
    import longcheck
    from concurrent.futures import ThreadPoolExecutor

    EXCL_LOG.clear()
    host = sub if "." in (sub or "") else f"{sub}.substack.com"
    limiter = Limiter(0.4)
    start, end, _months = window("2y", today)
    try:
        page = fetch_archive_page(host, 0, limiter, CACHE)
    except TimeoutError:
        raise
    except Exception:
        return None
    if not isinstance(page, list):
        return None
    posts = []
    try:
        for post in iter_archive(host, limiter, CACHE, 0, start):
            if _past_deadline():
                raise TimeoutError("author budget exceeded")
            day = (post.get("post_date") or "")[:10]
            if start <= day < end:
                posts.append(post)
    except TimeoutError:
        raise
    except Exception:
        return None

    def body_for(post):
        if _past_deadline():
            raise TimeoutError("author budget exceeded")
        slug = post.get("slug") or ""
        if not slug:
            return ""
        try:
            payload = fetch_post(host, slug, limiter, CACHE)
        except TimeoutError:
            if _past_deadline():
                raise
            return ""
        except Exception:
            return ""
        text, _preview = body_from_post(payload)
        return text or ""

    if posts:
        with ThreadPoolExecutor(max_workers=4) as pool:
            bodies = list(pool.map(body_for, posts))
    else:
        bodies = []

    def search(query):
        if _past_deadline():
            raise TimeoutError("author budget exceeded")
        try:
            data = _yahoo(query, limiter, CACHE)
        except TimeoutError:
            raise
        except Exception:
            return []
        return (data or {}).get("quotes") or []

    found = []
    order = sorted(zip(posts, bodies), key=lambda item: (item[0].get("post_date") or ""))
    for post, text in order:
        if _past_deadline():
            raise TimeoutError("author budget exceeded")
        title = post.get("title") or ""
        subtitle = post.get("subtitle") or ""
        decision = analyze(title, subtitle, text, search, require_long=False)
        if decision.get("status") != "pitch":
            continue
        reason = longcheck.exclude_reason(title, text)
        day = (post.get("post_date") or "")[:10]
        if reason:
            EXCL_LOG.append((decision.get("ticker") or "", day, title, reason))
            continue
        url = post.get("canonical_url") or f"https://{host}/p/{post.get('slug')}"
        found.append(
            {
                "ticker": decision["ticker"],
                "date": day,
                "url": url,
                "title": title,
                "method": decision.get("method") or "",
                "confidence": decision.get("confidence"),
            }
        )
    kept = []
    seen = set()
    for row in found:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        kept.append(row)
    if not detail:
        return [(row["ticker"], row["date"], row["url"], row["title"]) for row in kept]
    return kept


def score(pitches, window_name="2y", today=None):
    """Price the kept pitches. Timeouts are lost_fail, not part of n, and not delisted."""
    import statistics
    from concurrent.futures import ThreadPoolExecutor

    import prices

    global PXSTAT
    PXSTAT = prices.PXSTAT
    _start, _end, months = window(window_name, today)
    rows = list(pitches or [])

    def one(pitch):
        if _past_deadline():
            raise TimeoutError("author budget exceeded")
        symbol = pitch.get("ticker") or ""
        status, ret = prices.total_return(symbol, pitch.get("date") or "", months, today=today, fallback=True)
        if status != "ok":
            return pitch, status, None
        bench = prices.benchmark(symbol)
        bstatus, bret = prices.total_return(bench, pitch.get("date") or "", months, today=today, fallback=False)
        if bstatus != "ok":
            # A benchmark timeout is a price failure, not a delisted stock.
            if bstatus == "notfound":
                return pitch, "nodata", None
            return pitch, bstatus if bstatus != "ok" else "nodata", None
        return pitch, "ok", (ret, bret)

    if rows:
        with ThreadPoolExecutor(max_workers=4) as pool:
            priced = list(pool.map(one, rows))
    else:
        priced = []
    hits = n = n_title = n_body = lost_fail = lost_notfound = 0
    excess = []
    for pitch, status, pair in priced:
        if status == "incomplete":
            continue
        if status == "notfound":
            lost_notfound += 1
            continue
        if status != "ok":
            lost_fail += 1
            continue
        ret, bret = pair
        n += 1
        method = pitch.get("method") or ""
        if method == "title":
            n_title += 1
        elif method == "body":
            n_body += 1
        if ret > bret:
            hits += 1
        excess.append(ret - bret)
    pct = None if n == 0 else hits / n
    median = None if not excess else statistics.median(excess)
    return {
        "hits": hits,
        "n": n,
        "pct": pct,
        "n_title": n_title,
        "n_body": n_body,
        "lost_fail": lost_fail,
        "lost_notfound": lost_notfound,
        "median_excess": 0 if median is None else median,
    }


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
    print("lib self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test())
