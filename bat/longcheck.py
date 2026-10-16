"""Regex check: does a post's author disclose being long? is_long(text)->(label,snippet)."""
import re
I=re.I
# overrides: explicit non-long statements

OBJ=r"(?:position|positions|shares|stake|holding|holdings)"
NEG=[
 r"\b(?:i|we)\s+(?:do\s*n[o']?t|don't|do not|did not|didn't|currently do not|have not|haven't)\s+(?:currently\s+)?(?:own|hold|owned|held)\b(?!\s+(?:my|our|your)?\s*(?:own\s+)?(?:due|research|opinion|view|judg))(?!\s+(?:a\s+)?(?:market|crystal))[^.\n]{0,40}",
 r"\b(?:i|we)\s+(?:do\s*n[o']?t|don't|do not|did not|didn't|currently do not|have not|haven't)\s+(?:currently\s+)?have\s+(?:a\s+|any\s+|an\s+)?(?:\w+\s+)?"+OBJ,
 r"\b(?:i|we)\s+(?:have|hold|own|currently have)\s+(?:no|zero)\s+(?:current\s+)?"+OBJ,
 r"\bno\s+(?:current\s+|long\s+)?(?:position|positions|stake)\b",
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+not\s+(?:currently\s+)?(?:long|invested|a\s+shareholder|an?\s+owner)",
 r"\bnot\s+(?:currently\s+)?long\b(?![\s-]*(?:after|ago|term|before|since|enough|time|run|been|story|as))",
 r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+(?:currently\s+)?short\b",
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+)?(?:shorted|am\s+short|are\s+short)\b",
 r"\bshort\s+position\b",
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+|just\s+|recently\s+|also\s+)*(?:sold|exited|closed|dumped|liquidated)\s+(?:all\s+of\s+|out\s+of\s+|half\s+of\s+|my\s+|our\s+)?(?:the\s+|this\s+)?(?:entire\s+|whole\s+|remaining\s+)?"+OBJ,
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+)?(?:sold|exited)\s+(?:out|completely|entirely)\b",
 r"\b(?:i|we)\s+(?:no longer|don't anymore)\s+(?:own|hold|have)\b",
 r"\bnot\s+(?:a\s+)?(?:current\s+)?(?:shareholder|owner)\b",
]
POS=[
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+(?:currently\s+|also\s+|still\s+|personally\s+|now\s+|very\s+)*(?:long|a\s+(?:shareholder|stockholder|holder)|an?\s+(?:owner|investor)\s+in)\b",
 r"\b(?:i|we)\s+(?:currently\s+|also\s+|still\s+|personally\s+|do\s+)*(?:own|hold)\b(?!\s+(?:up|back|that|the\s+view|a\s+view|no\b|my\b|our\b|your\b|due|research))(?![^.\n]{0,12}\bdue diligence)[^.\n]{0,50}",
 r"\b(?:i|we)\s+(?:have|hold|own|'ve)\s+(?:a\s+|an\s+|our\s+|my\s+|some\s+|large\s+|small\s+|meaningful\s+|significant\s+|sizeable\s+|sizable\s+|material\s+|substantial\s+|starter\s+|full\s+|core\s+|long\s+|tiny\s+|\d+(?:\.\d+)?%\s+)*(?:position|stake|shares|holding|exposure)\b",
 r"\b(?:my|our)\s+(?:(?:new|current|small|large|total|entire|remaining|full|core|existing|first|initial|starter|long|tiny|\d+(?:\.\d+)?%)\s+){0,2}(?:position|stake|holding)s?\s+(?:in|is|are|was|has|now|of|here)\b",
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+|also\s+|recently\s+|just\s+|then\s+|later\s+|first\s+|slowly\s+)*(?:bought|purchased|added|initiated|trimmed|accumulated|increased|scaled|doubled)\b[^.\n]{0,40}(?:shares|position|stake|stock|(?-i:\$?[A-Z]{2,5}\b)|(?:my|our)\s+holdings)",
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+)?(?:bought|purchased)\s+(?:some|more|a\s+(?:few|small|starter))?\s*(?:shares|stock)\b",
 r"\blong\s+(?:-\s*)?\$[A-Za-z]{1,6}\b",
 r"\b(?:disclosure|disclosures|disclaimer|positions?)\s*[:\-]\s*(?:the author\s+|i\s+|we\s+|author\s+)?(?:is\s+|am\s+|are\s+|has\s+|have\s+)?(?:currently\s+)?(?:long|own|owns|holds?|a position|a shareholder)\b",
 r"\bbeneficial(?:ly)?\s+(?:long|owns?|owner)\b",
 r"\b(?:the author|this author|author|writer)\s+(?:is|are|has|have|owns|holds)\s+(?:currently\s+)?(?:a\s+)?(?:long|position|shares|beneficially)\b",
 r"(?<!that )(?<!which )(?<!stocks )(?<!companies )\b(?:i|we)\s*(?:am|are|'m|'re)\s+(?:now\s+)?(?:buying|accumulating)\b(?!\s+(?:for|when|if|them|those))",
 r"\b(?:one of\s+)?(?:my|our)\s+(?:portfolio\s+(?:companies|holdings|positions)|holdings)\b",
 # implicit long (weaker): ~ prefix on snippet
 r"\b(?:i|we)\s+(?:will|'ll|am going to|plan to)\s+(?:add|buy|start|initiate)\b[^.\n]{0,25}\b(?:to\s+(?:my|the|our)\s+portfolio|position|shares)",
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+(?:now\s+)?back\s+in\b",
 r"\bbuying\s+(?:shares|stock)\s+in\s+(?-i:[A-Z$]{2,6}|[A-Z][a-z]+)",
 r"\b(?:to|for)\s+me[, ]+(?:this|it)\s+is\s+a\s+(?:strong\s+)?buy\b",

]
# generic boilerplate is stripped before matching (carries no information)
BOILER=re.compile(r"\b(?:may or may not\s+(?:hold|own|have)|may|might|could)\s+(?:from time to time\s+|at any time\s+)?(?:hold|own|have|buy|sell|be\s+(?:long|short)|initiate|acquire|take)\b[^.\n]{0,160}\.?",I)
REL=re.compile(r"\b(?:companies|stocks|names|positions|businesses|what|why|that|which|ones|those|all|many|most|any|everything|whatever|things|assets|securities|holdings|of the|know|compani\w+)\s+(?:that\s+)?(?:i|we)\s+(?:currently\s+|personally\s+)?(?:own|hold)\b",I)
REL2=re.compile(r"\b(?:stock|stocks|ones|companies|names|company|one|security|securities|thing)\s+(?:that\s+)?(?:i|we)\s+(?:currently\s+)?(?:don't|do not|do\s*n't)\s+(?:own|hold)\b",I)
EXTRA=re.compile(r"\b(?:hold|own)\s+(?:ourselves|myself|back|onto)\b|\bwe own portions\b|\bbuying or selling\b",I)
NEGR=[re.compile(p,I) for p in NEG]; POSR=[re.compile(p,I) for p in POS]
# strip things that cause false positives: quoted legalese about "may hold"
def _snip(t,m,w=60):
    a=max(0,m.start()-w); b=min(len(t),m.end()+w); return re.sub(r'\s+',' ',t[a:b]).strip()
# 'own' false positives: "I own up", "own use", "my own" don't match since need I/we own; filter "i own up/ my"
FP=re.compile(r"\b(?:i|we)\s+(?:own|hold)\s+(?:up|back|that|the\s+view|onto\s+the\s+view)\b",I)
def is_long(text):
    if not text: return ('unclear','')
    t=EXTRA.sub(' ',REL2.sub(' ',REL.sub(' ',BOILER.sub(' ',text.replace('’',"'")))))
    # specific negatives first (but only those not generic "may hold")
    negm=None
    for r in NEGR:
        m=r.search(t)
        if m: negm=(r,m); break
    posm=None; 
    for r in POSR:
        for m in r.finditer(t):
            if FP.search(t[m.start():m.end()+12]): continue
            posm=m; break
        if posm: break
    if posm and negm:
        if posm.start()>negm[1].start() and re.search(r"sold|exited|closed|short",negm[1].group(0),I): return ('long',_snip(t,posm))
        return ('unclear','CONFLICT: '+_snip(t,posm,30)+' || '+_snip(t,negm[1],30))
    if posm: return ('long',_snip(t,posm))   # generic 'may hold' boilerplate does not override concrete 'I own'
    if negm: return ('not_long',_snip(t,negm[1]))
    return ('unclear','')


# ===================== exclusion check: short / sell / hold =====================
# exclude_reason(title,text)->(reason|None,snippet). reason in {'short','sell','hold'}.
# Inclusion rule: a post counts as a pitch unless exclude_reason fires. short/sell always exclude;
# hold excludes only when is_long(text) is not 'long' (author clearly owns -> keep). Unclear stance with
# no signal -> still counts.
# Two kinds of pattern: STRONG = first-person / explicit rating statements (searched in the whole body + title);
# ZONE = softer phrases, searched only in title + first 700 + last 1600 chars (intro and conclusion).
_LBL=r"(?:(?:my\s+|our\s+|final\s+|overall\s+|investment\s+|analyst\s+)?(?:rating|verdict|recommendation|conclusion|stance|bottom line|takeaway|opinion)s?)"
_TK=r"(?-i:\$?[A-Z]{2,5}\b)"
_TERM=r"(?![\s-]*(?:term|side|seller|interest|squeeze|selling))"
STRONG={
'short':[
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+(?:currently\s+|now\s+|also\s+|still\s+)?(?:short|shorting)\b(?!\s*(?:of|on)\b)(?!\s+(?:the\s+)?[^.]{0,40}\bputs?\b)"+_TERM,
 r"\b(?:i|we)\s+(?:have\s+|'ve\s+|just\s+|recently\s+|also\s+)*(?:shorted|initiated\s+a\s+short|opened\s+a\s+short|started\s+a\s+short)\b",
 r"\b(?:i|we)\s+(?:have|hold|own|took|initiated|opened|put on|started|established)\s+(?:a\s+|an\s+|our\s+|my\s+)?(?:small\s+|tiny\s+|large\s+|starter\s+|new\s+)?short\s+(?:position|stake|bet)\b",
 r"\b(?:my|our|pet)\s+(?:new\s+|small\s+)?short\s+(?:position|thesis|idea|bet|trade|pitch)\b",
 r"\b"+_LBL+r"\s*[:\-–=]\s*(?:strong\s+)?short\b"+_TERM,
 r"\b(?:i|we)\s*(?:'d|would)\s+(?:be\s+)?short\s+(?:this|the|it|"+_TK+")",
],
'sell':[
 r"\b"+_LBL+r"\s*[:\-–=]\s*(?:is\s+)?(?:a\s+)?(?:strong\s+|outright\s+)?(?:sell|underweight|underperform|avoid|reduce|bearish)\b"+_TERM,
 r"\b(?:i|we)\s+(?:rate|rated|am\s+rating|'m\s+rating)\s+(?:the\s+stock\s+|this\s+stock\s+|it\s+|this\s+|shares\s+|"+_TK+r"\s+)?(?:a\s+|as\s+)?(?:strong\s+)?(?:sell|underweight|underperform)\b"+_TERM,
 r"\b(?:i|we)\s+(?:downgrade|am\s+downgrading|'m\s+downgrading)\b[^.]{0,40}\bto\s+(?:a\s+)?(?:strong\s+)?(?:sell|underweight)\b",
 r"\b(?:this|it|the\s+stock|the\s+shares|"+_TK+r")\s+is\s+(?:currently\s+|now\s+)?a\s+(?:strong\s+)?sell\b",
 r"\bnot\s+(?:really\s+|currently\s+|even\s+|exactly\s+)?a\s+(?:strong\s+)?buy\b(?!\s*(?:or|/|nor|and)\s)(?!\s*(?:/|-)\s*sell)(?!\s*(?:recommendation|signal|call|list|advice|indicator|on\s+its\s+own))",
 r"\b(?:i|we)\s*(?:would|'d)\s+(?:be\s+a\s+)?(?:sell\s+(?:here|now|this|the\s+stock|the\s+shares|at\s+(?:this|current))|avoid\s+(?:this|the|it|"+_TK+r")|stay\s+away\s+from\s+(?:this|the|it|"+_TK+r"))",
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+(?:very\s+|decidedly\s+|currently\s+|now\s+|quite\s+|increasingly\s+)?bearish\s+(?:on\s+(?:this|the|it|"+_TK+r"|[A-Z][a-z]+)|about)\b",
 r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+(?:a\s+)?(?:seller|selling\s+(?:my|our|all|the)\s+(?:entire\s+)?(?:position|shares|stake|holding))",
 r"\bovervalued[,;:\s\-–]+(?:so\s+|and\s+)?(?:a\s+)?(?:sell|avoid)\b",
],
'hold':[
 r"\b"+_LBL+r"\s*[:\-–=]\s*(?:is\s+)?(?:a\s+)?(?:strong\s+)?(?:hold|neutral|market\s+perform|equal[\s-]weight|wait|fairly\s+valued)\b",
 r"\b(?:i|we)\s+(?:rate|rated|am\s+rating|'m\s+rating)\s+(?:the\s+stock\s+|this\s+stock\s+|it\s+|this\s+|shares\s+|"+_TK+r"\s+)?(?:a\s+|as\s+)?hold\b",
 r"\b(?:this|it|the\s+stock|the\s+shares|"+_TK+r")\s+is\s+(?:currently\s+|now\s+)?a\s+hold\b",
 r"\bfairly\s+valued\b[,;:\s\-–]+(?:so\s+|and\s+)?(?:i\s+(?:would|will|am|'m)\s+)?(?:a\s+)?(?:hold|neutral|wait|pass|not\s+buy)",
 r"\b(?:i|we)\s*(?:am|are|'m|'re)\s+not\s+(?:buying|adding)\s+(?:yet|here|now|at\s+this)\b|\bnot\s+buying\s+(?:it\s+)?yet\b|\bnot\s+yet\s+a\s+buy\b",
],
}
ZONE={
'short':[],   # short title patterns are in TITLE_SHORT (title only, to avoid roundups/"weak short thesis")
'sell':[
 r"\b(?:remain|stay|turn(?:ed)?|turning)\s+bearish\b",
 r"\bbearish\s+(?:thesis|case|stance|call)\s+on\b",
 r"\bi\s+(?:would|'d)\s+(?:not|never)\s+(?:buy|own)\b|\bi\s+would\s+(?:rather\s+)?avoid\b",
 r"\bnot\s+worth\s+buying\b|\bno\s+margin\s+of\s+safety\b[^.]{0,30}\b(?:avoid|pass|sell)\b",
],
'hold':[
 r"\b(?:i|we)\s*(?:'ll|will|am|'m|are)\s+(?:taking\s+a\s+|in\s+)?wait[\s-]and[\s-]see\b",
 r"\bi\s+(?:would|will|'d)\s+wait\s+(?:for|until)\s+(?:a\s+)?(?:better|lower|cheaper|pullback|dip|more\s+clarity|confirmation|a\s+lower|the\s+price)\b",
 r"\bi\s+(?:would|will|'d)\s+(?:hold\s+off|stay\s+on\s+the\s+sidelines|stay\s+on\s+the\s+sideline)\b",
 r"\b(?:i|we)\s+(?:remain|am|are|'m|'re|stay)\s+(?:neutral\s+(?:on|about)\s+(?:this|the\s+stock|it|"+_TK+r")|on\s+the\s+sidelines|on\s+the\s+fence)\b",
 r"\b(?:remain|stay)\s+on\s+the\s+sidelines\b",
],
}
TITLE_SHORT=[re.compile(p,I) for p in (r"\bshort\s+(?:thesis|idea|pitch|report|case)\b",r"\bthe\s+short\s+case\b",r"^\s*short\s+"+_TK,r"\bshort[\s-]seller\s+report\b",r"\bshorting\s+"+_TK)]
_S={k:[re.compile(p,I) for p in v] for k,v in STRONG.items()}
_Z={k:[re.compile(p,I) for p in v] for k,v in ZONE.items()}
def _zone(t,head=700,tail=1600):
    return t if len(t)<=head+tail else t[:head]+' || '+t[-tail:]
def exclude_reason(title,text):
    title=(title or '').replace('’',"'")
    t=(text or '').replace('’',"'")
    tz=re.sub(r'[-_]+',' ',title)
    body=tz+' || '+t
    zone=tz+' || '+_zone(t)
    for reason in ('short','sell','hold'):
        hit=None
        if reason=='short':
            for rx in TITLE_SHORT:
                m=rx.search(tz)
                if m: hit='TITLE: '+tz[:100]; break
        for rx in _S[reason]:
            m=rx.search(body)
            if m: hit=_snip(body,m); break
        if not hit:
            for rx in _Z[reason]:
                m=rx.search(zone)
                if m: hit=_snip(zone,m); break
        if not hit: continue
        if reason=='hold' and is_long(t)[0]=='long': continue
        return (reason,hit)
    return (None,'')


def _self_test():
    assert exclude_reason("I am short XYZ", "")[0] == "short"
    assert exclude_reason("Rating: Sell", "")[0] == "sell"
    assert exclude_reason("Recommendation: Hold", "")[0] == "hold"
    # Ownership is read from the post body. A hold in the title stays in when the body says the author owns shares.
    assert exclude_reason("Recommendation: Hold", "I own shares.")[0] is None
    assert exclude_reason("A note about the business.", "Revenue grew.")[0] is None
    assert exclude_reason("I do not own it. Rating: Hold", "")[0] == "hold"
    assert is_long("I may hold this someday")[0] == "unclear"
    assert is_long("I own shares")[0] == "long"
    assert is_long("I do not own it")[0] == "not_long"
    print("longcheck self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
