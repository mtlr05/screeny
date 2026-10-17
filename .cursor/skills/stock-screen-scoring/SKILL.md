---
name: stock-screen-scoring
description: >-
  Score a pitched stock article out of 6. Single source of truth for the six
  criteria and their evidence rules. Use when scoring for the stock screen.
---

# Stock screen scoring

## Score (out of 6; 1 point each, partial credit as stated). Small/mid cap and US/Canada listing are screening filters, not scored.
1. Thesis with a secular runway or growth driver; cheap but no growth (asset value, cash pile, wind-down, low multiple only) = 0.5.
2. Return ~40%/yr from the publish-day close using the author's target and timeframe (default 2 years); 25-40%/yr = 0.5; below 25%/yr = 0.
3. CEO is a large shareholder. Roughly 5%+ = 1; 1-5% = 0.5.
4. The higher of 4a and 4b. Each is scored from 0 to 1, and the total stays out of 6. An article is not dropped for lacking a moat or an edge; criterion 4 can be 0.
4a. Moat. Moat judged on the business model against the five types (intangibles, switching costs, network effects, cost advantage, efficient scale), with mechanism, trend and main threat: Strong 1 / Moderate 0.75 / Narrow 0.5. None described, or a type not among the five (for example correlation with bitcoin, a one-off contract, being cheap to book value, or a royalty/yield model with nothing else) = 0. The moat must be argued from the business model, not asserted by label.
4b. Edge. Edge is about the people running or backing the company, shown by named, checkable evidence in the article or a cited filing: past results they delivered (a named prior company, deal or turnaround with figures), a record of meeting or beating guidance across several periods, capital allocation outcomes (buybacks at good prices, accretive acquisitions, returns on capital), or a founder who built the product and still runs it. A good guidance record supports it.
   - Strong 1: at least two independent kinds of evidence above, with figures, and directly relevant to this company's thesis (e.g. a repeat dealmaker with a named multi-bagger and a multi-year guidance record).
   - Moderate 0.75: one kind of evidence with figures and relevant to the thesis.
   - Narrow 0.5: one kind of evidence that is partial, dated, or only loosely relevant (e.g. long tenure or an award without results).
   - 0: assertion without checkable evidence (talented, experienced, visionary), insiders buying or ownership alone (that belongs to criterion 3), or a track record in an unrelated business.
   - Edge is not credit for a cheap valuation, a funding advantage, or a high yield; those are not edge.
5. Differential view, synthesised by me: names the specific reason the market is wrong (stigma or category label, a temporary or mundane issue, neglect) and why it should correct, compared with what the price implies and other coverage. Both named with evidence = 1; one missing or vague = 0.5; matches consensus = 0. An overreaction to temporary news supports it.
6. Dated catalyst within ~24 months that could force a re-rating = 1; named but undated = 0.5; none = 0.

## Evidence rules (so two runs score the same text the same way; write one sentence of evidence per criterion in the one-pager)
- CEO stake (3): judged from the article or a cited filing only. If neither states it, score 0 and print 'not stated'. Never use unstated outside knowledge, and never invent a rule such as 'silent = 0' beyond this.
- Return (2): compute from the stated target and horizon with `px.py` (publish-day close) and print the formula; no stated target = 0 unless the article gives a clear valuation endpoint.
  - A "clear valuation endpoint" includes a target computed from a multiple the author says the stock should reach, using the author's own earnings, cash flow or asset figure; label it "implied". A current multiple alone ("trades at 5.8x forward earnings") is not an endpoint.
  - Price is the close on the publish date, or the next trading day if that date is a weekend or holiday. Horizon is the author's stated horizon, else 2 years; say which. A target range uses its midpoint; a bull case alone is used and labelled "bull case". Return per year = (target / price)^(1 / years) - 1.
- Differential view (5): 1 only if the article writes BOTH the cause of the mispricing and why it corrects; otherwise 0.5; consensus = 0.
- Dated catalyst (6): 1 only for a named dated event within 24 months; 0.5 for a named undated one.
  - A scheduled earnings report counts as dated only if the article ties it to the thesis; a routine report date otherwise gets 0.5.
- Moat and edge (4): always print 4a and 4b separately, each with one evidence sentence. Criterion 4 is the higher of the two. Store `c4a`, `c4b`, and that higher value (criterion 4). An older score that has only criterion 4 is 4a; 4b was not scored.
- Persist criterion scores and the evidence sentence per criterion; the report is regenerated from the stored scores so the same scores always give the same report.

## Worked examples

These five pitches show the rules above. Figures are the article's own targets and the publish-day closes used when the return was computed. The article's earlier close is not the price. Return per year = (target / price)^(1 / years) - 1. Nothing here is a quote of the write-up.

### PRPO

Published 2026-10-12. The stated endpoint is a 2031 price of $160, the probability-weighted case, not the bull case and not the $45–$52 figure. That $45–$52 range is $160 discounted back to today, so using it as the target counts the discount twice and lands near 16%/yr (score 0). Horizon is the author's 2031 date, about 5.22 years from the publish date, not the 2-year default. Price is the publish-day close ($22.59 in the scored pass; the article's $23.50 is the prior session). (160 / 22.59)^(1 / 5.22) - 1 ≈ 46%/yr, so criterion 2 is 1. Label the target stated, not implied.

Thesis is 1: on-site cancer testing with a growth path, not a no-growth asset. CEO stake is 0, and it is stated, so do not print "not stated": about 2,850 shares is well under 1% of the share count. The 16.6% officer-and-director figure is not the CEO's stake. 4a is narrow, 0.5: a razor-and-blade kit with switching costs from the instrument and training; the threat is slow conversion of new labs. 4b is narrow, 0.5: the founder built the product and still runs it, with no separate result that carries figures. Criterion 4 is the higher of the two, 0.5. Differential view is 1: the shares still carry the revenue multiple of the cash-burn years, and the correction is proof of new-lab sales plus cash flow. Catalyst is 1: November 2026 results are tied to pipeline conversion and cash flow, and the March 2027 annual report is tied to whether the substantial-doubt language comes off. Those are thesis-linked dates, not a routine earnings stamp.

### MGM

Published 2026-10-13. Fair value is the base sum of the parts, about $45. There is no horizon, so say the default of 2 years. Do not use the failed $48.30 bid; the text gives that bid no value. Price is the publish-day close ($29.40 in the scored pass; the article's $29.27 is three sessions earlier). (45 / 29.40)^(1 / 2) - 1 ≈ 24%/yr, which is below 25%, so criterion 2 is 0. The same formula on $29.27 is still about 24%.

Thesis is 0.5: a cheap lease-adjusted cash flow and buybacks, with softer room rates, not a secular growth driver. CEO stake is 0 and "not stated"; a 26.5% outside holder is not the CEO. 4a is moderate, 0.75: the Strip portfolio is efficient scale and an intangible, the mechanism is the resorts under the lease, the trend is weaker room revenue, and the threat is rent that does not fall. 4b is moderate, 0.75: about $9.7 billion of buybacks cut the share count by about half, at an average price under $40. Criterion 4 stays 0.75. Differential view is 1: the market is treating a financing failure as a broken business, and the correction is that rates, not the resorts, ended the bid. Catalyst is 1: the October 28 quarterly report is tied to the thesis (an easy Las Vegas comparison and whether buybacks resumed). A routine report date with no such tie would be 0.5.

### BLSH

Published 2026-10-13. The text gives a range of $40–$44 if the multiple re-rates, and a separate tokenization case near $50. A range uses its midpoint, so the target is $42, labelled implied (a multiple the text says the shares should reach). The $50 case is not used once a range exists; it would be the input only if it were the only case, and then it would be labelled "bull case". A current forward multiple is not an endpoint. No horizon is stated, so say 2 years. The article does not print a share price; the scored pass used the publish-day close of $31.77. (42 / 31.77)^(1 / 2) - 1 ≈ 15%/yr, so criterion 2 is 0. The unused $50 case would be about 25%/yr and would still not replace the midpoint.

Thesis is 1: tokenized assets and a shift toward subscription revenue are a growth driver. CEO stake is 0 and "not stated". 4a is 0: correlation with bitcoin and a transfer-agent deal are not one of the five moat types. 4b is 0: no named operating result, guidance record, or founder who built the product. Criterion 4 is 0. The other scores are 1, 0, 0, 0.5, and 0.5, so the total is 2. Differential view is 0.5: a discount to a historical multiple is named, but not a specific mispricing cause and a reason it corrects. Catalyst is 0.5: tokenization and the transfer-agent deal are named and undated. None would be 0; undated is 0.5.

### STNE

Published 2026-10-09. There is no price target and no valuation endpoint. A forward multiple of 5.8x is the current multiple, which the evidence rule says is not an endpoint, so criterion 2 is 0. Do not invent a target multiple the text never applies to an earnings figure.

Thesis is 1: the relaunched credit book is a growth driver, not a low-multiple-only story. CEO stake is 0 and "not stated". 4a is 0: a tighter credit process is not one of the five moat types. 4b is 0: no checkable record of the people running it. Criterion 4 is 0. The other scores are 1, 0, 0, 1, and 1, so the total is 3. Differential view is 1: the market is still pricing a repeat of the earlier credit failure, and the correction is more evidence that provisions and the receivables check are holding. Catalyst is 1: the October 25 runoff is a named date inside 24 months and the text ties it to a possible re-rating. It is not a routine earnings date.

### ONDS

Published 2026-10-12. The text builds bear, middle, and bull prices and says the bull case is the one it adopts: $20.87 at the end of 2027, from the author's revenue and a sales multiple. Label it "bull case". Do not average it with the middle case. Horizon is end-2027, about 1.22 years (14.6 months), not 2 years. Price is the publish-day close ($6.67 in the scored pass; the article's $6.73 is the prior session). (20.87 / 6.67)^(1 / 1.22) - 1 ≈ 155%/yr, so criterion 2 is 1. The middle case would also clear 40%/yr, but it is not the adopted target.

Thesis is 1: a defense-prime buildout with a stated revenue ramp, not a cash-pile story. CEO stake is 0 and "not stated"; insider selling without a share count is not a stake. 4a is moderate, 0.75: prime-contractor status is efficient scale (the firm owns the customer vehicle), the mechanism and the budget trend are described, and the threat is dilution plus execution. 4b is 0: insider selling is not an operating record. Criterion 4 stays 0.75. Differential view is 1: the market is pricing the share-count explosion rather than the cash and backlog, and the correction is revenue catching that share count. Catalyst is 1: platform EBITDA profitability in Q4 2026 is a named quarter inside 24 months and is the thesis. A later share issuance is dilution, not the re-rating event.
