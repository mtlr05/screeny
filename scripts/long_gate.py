#!/usr/bin/env python3
"""Long gate for the screen. A stance check, not a point on the /7 score.

Seeking Alpha still needs a "beneficial long position" disclosure. Value
Investors Club still needs the form line that the author or people they advise
hold a material investment. On a source with no structured disclosure form
(Substack and similar), an explicit ownership statement counts, and a clear
long-side stance in the body counts when that sentence is missing.

bat/longcheck.py is the 2-year batting average. It is not this gate.
"""
import re

DROP = "author not long"

FALLBACK = (
    'On a source with no structured disclosure form (Substack and similar), an explicit "I own," "I am long," or "I hold a position" statement still counts. '
    "If that sentence is missing, the article still passes the long gate when the author takes a clear long-side investment stance in the body: a valued upside target or forecast horizon for the shares, or an unequivocal recommendation to own them, and does not disclose a short, a hold, or that they do not own the stock. "
    "A descriptive overview, a sector explainer, or enthusiasm without an investment conclusion still drops as `author not long`. "
    "A bullish headline or a Buy/LONG label alone is not enough. "
    "This fallback does not apply to Seeking Alpha or Value Investors Club, where a disclosure form exists and remains required."
)

SA_LONG = re.compile(r"beneficial long position in the shares of", re.I)
VIC_NEG = re.compile(r"\b(?:do\s+not|don't)\s+hold\s+a\s+material\s+investment\b", re.I)
VIC_POS = re.compile(
    r"\bhold\s+a\s+material\s+investment\s+in\s+the\s+issuer(?:'s|\u2019s)\s+securities\b",
    re.I,
)
NOT_OWN = re.compile(
    r"\b(?:i|we)\s+(?:do\s+not|don't)\s+(?:currently\s+)?(?:own|hold)\b",
    re.I,
)
NO_POSITION = re.compile(
    r"\b(?:i|we)\s+(?:currently\s+|still\s+)?have\s+no\s+position\b"
    r"|\b(?:disclosure|disclaimer)\s*[:\-]\s*no\s+position\b",
    re.I,
)
NOT_ADDING = re.compile(
    r"\bnot\s+adding\b[^.]{0,80}\bportfolio\b",
    re.I,
)
SHORT = re.compile(
    r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+(?:currently\s+|still\s+)?short\b"
    r"|\bshort\s+the\s+(?:stock|shares)\b",
    re.I,
)
HOLD = re.compile(
    r"\b(?:rating|verdict|recommendation)\s*[:\-]?\s*hold\b"
    r"|\b(?:this|it)\s+is\s+a\s+hold\b"
    r"|\brate[ds]?\s+(?:the\s+|this\s+)?(?:stock|shares|it)\s+(?:as\s+a\s+|as\s+|a\s+)?hold\b"
    r"|\brating\s+(?:the\s+|this\s+)?(?:stock|shares|it)\s+(?:as\s+a\s+|as\s+|a\s+)?hold\b",
    re.I,
)
EXPLICIT = re.compile(
    r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+(?:currently\s+|still\s+|personally\s+|also\s+|very\s+)?long\b(?![\s-]*(?:term|dated|run))"
    r"|\b(?:i|we)\s+hold\s+a\s+(?:long\s+)?position\b"
    r"|\b(?:i|we)\s+own\s+(?:the\s+|some\s+|these\s+|this\s+|a\s+)?(?:shares|share|stock|stocks|position|stake)\b"
    r"|\b(?:i|we)\s+own\s+it\b"
    r"|\bauthor\s+(?:of\s+this\s+(?:post|article|note)\s+)?holds?\s+a\s+long\s+position\b"
    r"|\b(?:i|we)\s+have\s+a\s+(?:long\s+)?position\b"
    r"|\bbeneficial\s+long\s+position\b",
    re.I,
)
# Ownership said another way: a named holding, a portfolio line, or adding shares.
# "may hold" boilerplate is not one of these.
OWNERSHIP = re.compile(
    r"\b(?:my|our)\s+(?:largest|biggest|top)\s+(?:holding|position|stake)s?\b"
    r"|\b(?:a|the)\s+top\s+holding\s+of\s+(?:mine|ours)\b"
    r"|\bin\s+(?:my|our)\s+portfolio\b"
    r"|\b(?:have\s+|has\s+|'ve\s+)?(?:increased|built|started)\s+(?:my|our|a)\s+position\b(?!\s+of\s+strength)"
    r"|\badded\s+to\s+(?:my|our)\s+position\b"
    r"|\bbought\s+more\s+shares\b",
    re.I,
)
MAY_HOLD = re.compile(r"\b(?:may|might|could)\s+hold\b|\bmay\s+or\s+may\s+not\b", re.I)
_ACTION_WORD = re.compile(r"\b(?:increased|built|started|added|bought)\b", re.I)
DOLLAR = re.compile(r"\$\s?\d")
WAS_WORTH = re.compile(r"\b(?:was|were)\s+worth\b", re.I)
FORWARD_VALUE = re.compile(
    r"\b(?:price\s+targets?|target\s+prices?|fair\s+value|intrinsic\s+value|value\s+the\s+shares|valued\s+at|upside\s+to)\b",
    re.I,
)
WORTH_SHARES = re.compile(
    r"\b(?:shares|(?:the|this)\s+stock)\b(?!\s+market)[^.]{0,60}\bworth\s+\$\s?\d"
    r"|\bworth\s+\$\s?\d[\d,]*(?:\.\d+)?\s+(?:a|per)\s+share\b",
    re.I,
)
PER_SHARE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s+(?:a|per)\s+share\b", re.I)
PER_SHARE_STANCE = re.compile(r"\b(?:target|upside|base\s+case|forecast|fair\s+value|intrinsic)\b", re.I)
_MONEY = r"\$\s?\d[\d,]*(?:\.\d+)?"
# A per-share value with a horizon: "value of $90 per share by 2030",
# "per share value of $90 by the end of the decade".
PER_SHARE_VALUE = re.compile(
    rf"\b(?:value|valuation)\b[^.\n]{{0,48}}{_MONEY}\s+(?:a|per)\s+share\b"
    rf"|{_MONEY}\s+(?:a|per)\s+share\b[^.\n]{{0,32}}\b(?:value|valuation)\b"
    rf"|(?:per|a)\s+share\s+value\b[^.\n]{{0,40}}{_MONEY}",
    re.I,
)
VALUE_HORIZON = re.compile(
    r"\bby\s+(?:the\s+end\s+of\s+)?(?:19|20)\d{2}\b"
    r"|\bby\s+the\s+end\s+of\s+the\s+decade\b",
    re.I,
)
PAST_FIGURE = re.compile(r"\bnet\s+worth\b|\brevenue\s+was\b", re.I)
_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|eighteen|twenty)"
HORIZON = re.compile(
    rf"\b(?:over|in|within)\s+the\s+next\s+{_NUM}\s+(?:months?|years?)\b",
    re.I,
)
SHARES = re.compile(r"\bshares\b|\b(?:the|this)\s+stock\b(?!\s+market)", re.I)
REC = re.compile(
    r"\bi\s+recommend\s+owning\b"
    r"|\bi\s+recommend\s+(?:that\s+)?(?:investors|readers|you)\s+(?:own|buy)\b"
    r"|\b(?:investors|readers|you)\s+should\s+own\s+(?:the\s+)?(?:shares|stock)\b"
    r"|\bi\s+would\s+buy\s+(?:the\s+)?(?:shares|stock)\b",
    re.I,
)


def source_kind(source):
    """sa, vic, or open. Open sources have no structured disclosure form."""
    text = re.sub(r"\s+", " ", (source or "").strip().lower())
    if text in {"sa", "seeking alpha", "seekingalpha"} or "seeking alpha" in text or re.search(r"\(sa\)$", text):
        return "sa"
    if text in {"vic", "value investors club"} or "value investors club" in text:
        return "vic"
    return "open"


def _sentences(text):
    return [part.strip() for part in re.split(r"[\n.!?]+", text or "") if part.strip()]


def _sentence_span(text, index):
    start = 0
    for pos in range(index - 1, -1, -1):
        if text[pos] in ".!?\n":
            start = pos + 1
            break
    end = len(text)
    for pos in range(index, len(text)):
        if text[pos] in ".!?\n":
            end = pos
            break
    return text[start:end]


def _negated_before(text, index):
    pre = (text or "")[max(0, index - 24):index]
    return re.search(r"\b(?:do\s+not|don't|not|never|no)\b", pre, re.I) is not None


def _explicit(text):
    for match in EXPLICIT.finditer(text or ""):
        if _negated_before(text, match.start()):
            continue
        return True
    return False


def _ownership(text):
    """A holding, a portfolio line, or shares the author added. May-hold boilerplate does not count."""
    for match in OWNERSHIP.finditer(text or ""):
        if _negated_before(text, match.start()):
            continue
        if not _ACTION_WORD.search(match.group(0)) and MAY_HOLD.search(_sentence_span(text, match.start())):
            continue
        return True
    return False


def _per_share_value_horizon(sentence):
    """Per-share value plus a by-year or end-of-decade horizon. Net worth and past revenue do not count."""
    if WAS_WORTH.search(sentence) or PAST_FIGURE.search(sentence):
        return False
    if not VALUE_HORIZON.search(sentence):
        return False
    return PER_SHARE_VALUE.search(sentence) is not None


def _valued_target(sentence):
    """A dollar figure for the shares. Net worth and past revenue do not count."""
    if WORTH_SHARES.search(sentence):
        return True
    if PER_SHARE.search(sentence) and PER_SHARE_STANCE.search(sentence):
        return True
    if _per_share_value_horizon(sentence):
        return True
    if not DOLLAR.search(sentence) or not FORWARD_VALUE.search(sentence):
        return False
    if WAS_WORTH.search(sentence):
        return False
    return True


def _clear_stance(text):
    """Body only. A headline target or a Buy/LONG label is not a stance."""
    for sentence in _sentences(text):
        if _valued_target(sentence):
            return True
        if HORIZON.search(sentence) and SHARES.search(sentence):
            return True
        if REC.search(sentence):
            return True
    return False


def decision(source, text, title=""):
    """Return 'pass' or 'drop'. The /7 score is not an argument."""
    kind = source_kind(source)
    blob = f"{title or ''}\n{text or ''}"
    if kind == "sa":
        return "pass" if SA_LONG.search(blob) else "drop"
    if kind == "vic":
        if VIC_NEG.search(blob):
            return "drop"
        return "pass" if VIC_POS.search(blob) else "drop"
    # A negative stance about the author's own position wins over a long signal in the same article.
    if NOT_OWN.search(blob) or SHORT.search(blob) or NO_POSITION.search(blob) or NOT_ADDING.search(blob):
        return "drop"
    if _explicit(title or "") or _explicit(text or "") or _ownership(title or "") or _ownership(text or ""):
        return "pass"
    # A hold rating beats a valued target. Explicit ownership above still stands.
    if HOLD.search(blob):
        return "drop"
    if _clear_stance(text or ""):
        return "pass"
    return "drop"


def reason(source, text, title=""):
    """Empty string when the article passes, else 'author not long'."""
    if decision(source, text, title) == "pass":
        return ""
    return DROP


def self_test():
    """Offline cases for the fallback and for the SA and VIC forms."""
    passes = [
        ("substack", "I own the shares.", ""),
        ("substack", "I am long the stock.", ""),
        ("substack", "I hold a position in the company.", ""),
        ("blog", "We are long.", ""),
        ("forum", "The author holds a long position in the stock.", ""),
        ("substack", "I value the shares at $40, about double the current price.", ""),
        ("substack", "My 12-month price target for the stock is $25.", ""),
        ("substack", "Over the next two years I expect the shares to double.", ""),
        ("substack", "I recommend owning the shares.", ""),
        ("substack", "The shares are worth $25.", ""),
        ("substack", "I think the stock is worth $18 a share.", ""),
        ("substack", "Base case $40 per share over two years.", ""),
        ("substack", "I own the shares. Recommendation: Hold.", ""),
        ("substack", "I may hold a position. I recommend owning the shares.", ""),
        ("substack", "I recommend owning the shares.", "ACME is a Buy"),
        ("substack", "tied with Amazon (AMZN) as my largest holding", ""),
        ("substack", "This is my biggest position.", ""),
        ("substack", "It is a top holding of mine.", ""),
        ("substack", "The shares are in my portfolio.", ""),
        ("substack", "I have increased my position.", ""),
        ("substack", "I added to my position.", ""),
        ("substack", "I increased a position.", ""),
        ("substack", "I built a position.", ""),
        ("substack", "I started a position.", ""),
        ("substack", "I bought more shares.", ""),
        ("substack", "The model provides a value of over $90 per share by 2030.", ""),
        ("substack", "There is a per share value of over $90 by the end of the decade.", ""),
        ("substack", "I calculate a share value rising to above $90 per share by 2030.", ""),
        ("substack", "I own the shares. I rate the stock Hold.", ""),
        ("substack", "I may hold a position. The shares are in my portfolio.", ""),
    ]
    for source, text, title in passes:
        assert decision(source, text, title) == "pass", (source, title, text)
        assert reason(source, text, title) == "", (source, text)
    drops = [
        ("substack", "ACME is a Buy", "ACME: Buy"),
        ("substack", "LONG", "LONG $ACME"),
        ("substack", "Acme makes widgets for hospitals. Revenue was $40 million. The CEO joined in 2019.", "Acme Corp"),
        ("substack", "The CEO's net worth is $40 million. Revenue was $40 million.", "Acme Corp"),
        ("substack", "The lithium sector will grow over the next two years as demand rises.", "Lithium"),
        ("substack", "I love this company. The product is amazing and the team is world class.", "Acme"),
        ("substack", "I may hold a position in the stock.", ""),
        ("substack", "My price target is $40. I do not own the stock.", ""),
        ("substack", "My price target is $40. I am short the shares.", ""),
        ("substack", "My price target is $40. Recommendation: Hold.", ""),
        ("substack", "The company makes widgets.", "Price target $40"),
        ("substack", "My 12-month price target for the stock is $25. I rate the stock Hold.", ""),
        ("substack", "I rate the stock Hold.", ""),
        ("substack", "My price target is $40. Disclosure: no position.", ""),
        ("substack", "Disclosure: no position.", ""),
        ("substack", "My price target is $40. I have no position.", ""),
        ("substack", "I have no position.", ""),
        ("substack", "I value the shares at $40. I am not adding Deckers to the RC portfolio.", ""),
        ("substack", "I am not adding Deckers to the RC portfolio.", ""),
        ("substack", "I value the shares at $40. I am not adding X to the portfolio.", ""),
        ("substack", "tied with Amazon (AMZN) as my largest holding. I have no position.", ""),
        ("substack", "I have increased my position. Disclosure: no position.", ""),
        ("substack", "The shares are in my portfolio. I am not adding Deckers to the RC portfolio.", ""),
        ("substack", "I may hold a position in my portfolio.", ""),
        ("substack", "The stock trades at $90 per share.", ""),
        ("substack", "I love this company and expect great things by 2030.", "ACME is a Buy"),
        ("substack", "The firm built a position of strength in its home market.", ""),
        ("substack", "The share value of the firm reaches $90 million by 2030.", ""),
        ("substack", "Earnings per share of $4 by 2030.", ""),
    ]
    for source, text, title in drops:
        assert decision(source, text, title) == "drop", (source, title, text)
        assert reason(source, text, title) == DROP, (source, text)
    stance = "I am long the shares. My price target is $40. I recommend owning them."
    assert decision("seeking alpha", stance) == "drop"
    assert decision("SA", stance) == "drop"
    assert decision("Seeking Alpha", stance + " I/we have a beneficial long position in the shares of ACME.") == "pass"
    vic_pos = "I and/or others I advise hold a material investment in the issuer's securities."
    vic_neg = "I and/or others I advise do not hold a material investment in the issuer's securities."
    assert decision("Value Investors Club", vic_pos) == "pass"
    assert decision("vic", vic_neg) == "drop"
    assert decision("vic", vic_neg + " " + stance) == "drop"
    assert decision("VIC", stance) == "drop"
    open_long = "The shares are in my portfolio. The model provides a value of over $90 per share by 2030."
    assert decision("seeking alpha", open_long) == "drop"
    assert decision("vic", "I have increased my position. " + open_long) == "drop"
    print("long_gate self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
