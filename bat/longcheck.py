"""Exclude a pitch from the 2-year batting average.

Unclear stance still counts. A short, a sell rating, or a hold rating
without a clear long disclosure does not. Hold with clear ownership is kept.
"""
import re

# Clear ownership. "not own", "do not own", and "may hold" do not match.
OWN_RE = re.compile(
    r"\bi own\b|\bwe own\b"
    r"|\bi am long\b|\bi'm long\b|\bwe are long\b|\bwe're long\b"
    r"|\bmy position\b|\bour position\b|\blong position\b"
    r"|\bi hold shares\b|\bbeneficially long\b",
    re.I,
)
SHORT_RE = re.compile(
    r"\b(?:i am short|i'm short|we are short|we're short|short thesis|short report)\b",
    re.I,
)
SELL_RE = re.compile(
    r"\b(?:rating|verdict|recommendation)\s*[:\-]?\s*sell\b|\bwe rate\s+sell\b|\bsell rating\b",
    re.I,
)
HOLD_RE = re.compile(
    r"\b(?:rating|verdict|recommendation)\s*[:\-]?\s*hold\b|\bhold rating\b",
    re.I,
)
NEG_PRE = re.compile(r"\b(?:not|no|never|don't|do not|doesn't|does not|may|might)\b", re.I)


def _negated(text, match):
    pre = (text or "")[max(0, match.start() - 24):match.start()]
    if NEG_PRE.search(pre):
        return True
    span = match.group(0)
    if re.search(r"\b(?:not|never|no)\b|n't", span, re.I):
        return True
    return False


def is_long(text):
    """'long' when the text clearly owns shares, otherwise 'unclear'."""
    text = text or ""
    for match in OWN_RE.finditer(text):
        if _negated(text, match):
            continue
        return "long"
    return "unclear"


def exclude_reason(title, text):
    """'short', 'sell', 'hold', or None. None means the pitch still counts."""
    blob = f"{title or ''}\n{text or ''}"
    if SHORT_RE.search(blob):
        return "short"
    if SELL_RE.search(blob):
        return "sell"
    if HOLD_RE.search(blob):
        if is_long(blob) == "long":
            return None
        return "hold"
    return None


def _self_test():
    assert exclude_reason("I am short XYZ", "") == "short"
    assert exclude_reason("Rating: Sell", "") == "sell"
    assert exclude_reason("Recommendation: Hold", "") == "hold"
    assert exclude_reason("Recommendation: Hold. I own shares.", "") is None
    assert exclude_reason("A note about the business.", "Revenue grew.") is None
    assert exclude_reason("I do not own it. Rating: Hold", "") == "hold"
    assert is_long("I may hold this someday") == "unclear"
    assert is_long("I own shares") == "long"
    assert is_long("I do not own it") == "unclear"
    print("longcheck self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
