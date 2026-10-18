#!/usr/bin/env python3
"""Find candidate sentences for criterion 3. The scorer confirms the tier.

Text only: the article or a cited filing. This does not score the article.
A suggested tier is the highest ladder rung the sentence might support.
A stated share count is suggested at 0.5; if the same text shows the stake is
under 1% of the company, the ladder scores that stake 0.

  python3 scripts/ceo_stake_grep.py FILE
  python3 scripts/ceo_stake_grep.py self-test
"""
import re
import sys

PCT = r"\d+(?:\.\d+)?\s?(?:%|percent)"
COUNT = r"(?:\d[\d,]{3,}\s+(?:shares|units)|\$\s?\d[\d,]*)"
ROLE_CEO = r"(?:founder[- ]CEO|founder and CEO|chief executive|executive chair(?:man)?|\bCEO\b)"
OWN_VERB = r"(?:owns?|owned|owning|holds?|stake|beneficially|shareholder)"
SKIP_OWN = re.compile(r"\bformer\b|\bex-|from CEO to|together|collectively|as a group", re.I)
BUY_NOT = re.compile(r"buy[- ]?back|repurchas|capped call|\bno\b|absence|\bnot\b|\bsold\b|selling", re.I)
AGG_SKIP = re.compile(r"institution|addressable|market share", re.I)
PCT_NUM = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent)", re.I)

CEO_OWN = re.compile(
    rf"(?:{ROLE_CEO})[^.]{{0,90}}\b{OWN_VERB}\b[^.]{{0,60}}(?:{PCT}|{COUNT})"
    rf"|(?:{PCT}|{COUNT})[^.]{{0,60}}\b(?:owned|held|stake|of the company)\b[^.]{{0,60}}(?:{ROLE_CEO})",
    re.I,
)
BUY = re.compile(
    r"(?:CEO|insiders?|directors?|chair(?:man)?|executives?|president)[^.]{0,50}"
    r"\b(?:bought|purchased|acquired|buying|purchases)\b[^.]{0,50}"
    r"(?:shares|stock|units|\$|C\$|€|£)",
    re.I,
)
CEO_BUY = re.compile(r"\bCEO\b|chief executive|executive chair", re.I)
AGG = re.compile(
    rf"(?:insiders?|management|directors|officers|executives|board|founders?)[^.]{{0,50}}"
    rf"\b(?:own|owns|hold|holds|held|control|controls|collectively)\b[^.]{{0,50}}{PCT}"
    rf"|{PCT}\s+(?:insiders?|insider ownership|management)"
    rf"|insider ownership[^.]{{0,30}}{PCT}",
    re.I,
)
PAY = re.compile(
    r"(?:PSUs?|performance[- ](?:share|stock|option|unit)s?|options?(?:\s+that)?\s+vest|profits interests)"
    r"|(?:CEO|executive|management)[^.]{0,30}(?:compensation|pay|bonus|incentive)[^.]{0,50}"
    r"(?:tied|linked|based on|contingent|TSR|targets?)",
    re.I,
)
PAY_WHO = re.compile(r"\b(?:CEO|executive|management)\b", re.I)
SKIN = re.compile(r"skin in the game", re.I)
SKIN_WHO = re.compile(r"\b(?:CEO|founder)\b", re.I)
SKIN_NOT = re.compile(r"\b(?:no|not|isn't|is not|without)\b[^.]{0,40}skin in the game|skin in the game[^.]{0,20}\bbook\b", re.I)
FOUNDER_LED = re.compile(r"founder-led|founder and CEO|founder-CEO|owner-operator", re.I)
FOUNDER_STAKE = re.compile(
    rf"(?:founder|chair(?:man)?)[^.]{{0,90}}\b{OWN_VERB}\b[^.]{{0,60}}{PCT}"
    rf"|{PCT}[^.]{{0,60}}\b(?:owned|held|stake)\b[^.]{{0,40}}(?:founder|chair(?:man)?)",
    re.I,
)


def sentences(text):
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _pcts(sentence):
    return [float(match) for match in PCT_NUM.findall(sentence or "")]


def _ceo_own_tier(sentence):
    if SKIP_OWN.search(sentence):
        return None
    ceo_hit = CEO_OWN.search(sentence)
    founder_hit = FOUNDER_STAKE.search(sentence) and not re.search(
        r"\bCEO\b|chief executive|founder[- ]CEO|founder and CEO", sentence, re.I
    )
    if not ceo_hit and not founder_hit:
        return None
    percents = _pcts(sentence)
    if founder_hit and not ceo_hit:
        if percents and max(percents) >= 5:
            return 0.5
        return None
    if percents:
        pct = max(percents)
        if pct >= 5:
            return 1.0
        if pct >= 1:
            return 0.5
        return 0.0
    return 0.5


def _buy_tier(sentence):
    if not BUY.search(sentence) or BUY_NOT.search(sentence):
        return None
    if CEO_BUY.search(sentence):
        return 0.75
    return 0.25


def _agg_tier(sentence):
    if not AGG.search(sentence) or AGG_SKIP.search(sentence):
        return None
    percents = _pcts(sentence)
    if not percents or max(percents) < 10:
        return None
    return 0.25


def _pay_tier(sentence):
    if PAY.search(sentence) and PAY_WHO.search(sentence):
        return 0.25
    return None


def _skin_tier(sentence):
    if not SKIN.search(sentence) or SKIN_NOT.search(sentence):
        return None
    if SKIN_WHO.search(sentence):
        return 0.5
    return None


def _founder_led_tier(sentence):
    if not FOUNDER_LED.search(sentence):
        return None
    if _pcts(sentence) or SKIN.search(sentence) or CEO_OWN.search(sentence):
        return None
    return 0.0


RULES = (
    ("CEO_OWN", _ceo_own_tier),
    ("BUY", _buy_tier),
    ("AGG", _agg_tier),
    ("PAY", _pay_tier),
    ("SKIN", _skin_tier),
    ("FOUNDER_LED", _founder_led_tier),
)


def candidates(text):
    """Each item is (tier, rule, sentence). Highest tier wins when several match."""
    found = []
    for sentence in sentences(text):
        hits = []
        for name, fn in RULES:
            tier = fn(sentence)
            if tier is None:
                continue
            hits.append((tier, name))
        if not hits:
            continue
        tier, name = max(hits, key=lambda item: item[0])
        found.append((tier, name, sentence))
    return found


def format_tier(tier):
    return f"{tier:.2f}".rstrip("0").rstrip(".") if tier != 0 else "0"


def scan(text):
    lines = []
    for tier, name, sentence in candidates(text):
        lines.append(f"{format_tier(tier)}\t{name}\t{sentence}")
    return lines


def self_test():
    samples = [
        ("The CEO owns 12% of the company.", "1", "CEO_OWN"),
        ("The CEO owns 3% of the company.", "0.5", "CEO_OWN"),
        ("The CEO bought 10000 shares in the open market.", "0.75", "BUY"),
        ("The executive chair purchased $50000 of stock.", "0.75", "BUY"),
        ("The founder still owns 20% of the company.", "0.5", "CEO_OWN"),
        ("The CEO has skin in the game.", "0.5", "SKIN"),
        ("Insiders own 40% of the shares.", "0.25", "AGG"),
        ("A director bought 5000 shares.", "0.25", "BUY"),
        ("The CEO bonus is tied to TSR.", "0.25", "PAY"),
        ("Officers and directors own 16.6% of the stock.", "0.25", "AGG"),
        ("The CEO owns 2,850 shares.", "0.5", "CEO_OWN"),
        ("The former CEO owns 20% of the company.", None, None),
        ("The company bought back shares.", None, None),
        ("It is a founder-led business.", "0", "FOUNDER_LED"),
        ("There is no skin in the game for the CEO.", None, None),
    ]
    for sentence, tier, rule in samples:
        got = candidates(sentence)
        if tier is None:
            assert got == [], (sentence, got)
            continue
        assert len(got) == 1, (sentence, got)
        assert format_tier(got[0][0]) == tier, (sentence, got)
        assert got[0][1] == rule, (sentence, got)
    print("ceo_stake_grep self-test ok")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python3 scripts/ceo_stake_grep.py FILE")
        print("       python3 scripts/ceo_stake_grep.py self-test")
        return 2
    if argv[0] == "self-test":
        return self_test()
    text = open(argv[0], encoding="utf-8").read()
    lines = scan(text)
    if not lines:
        print("no candidate sentences")
        return 0
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
