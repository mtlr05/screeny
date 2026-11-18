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
SHORT = re.compile(
    r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+(?:currently\s+|still\s+)?short\b"
    r"|\bshort\s+the\s+(?:stock|shares)\b",
    re.I,
)
HOLD = re.compile(
    r"\b(?:rating|verdict|recommendation)\s*[:\-]?\s*hold\b"
    r"|\b(?:this|it)\s+is\s+a\s+hold\b",
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


def _explicit(text):
    for match in EXPLICIT.finditer(text or ""):
        pre = (text or "")[max(0, match.start() - 24):match.start()]
        if re.search(r"\b(?:do\s+not|don't|not|never|no)\b", pre, re.I):
            continue
        return True
    return False


def _valued_target(sentence):
    """A dollar figure for the shares. Net worth and past revenue do not count."""
    if WORTH_SHARES.search(sentence):
        return True
    if PER_SHARE.search(sentence) and PER_SHARE_STANCE.search(sentence):
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
    if NOT_OWN.search(blob) or SHORT.search(blob):
        return "drop"
    if _explicit(title or "") or _explicit(text or ""):
        return "pass"
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
    print("long_gate self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
