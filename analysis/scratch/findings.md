<!-- Hong Kong IPO Trading Strategy Study — written findings -->
# Hong Kong IPO Trading Strategy Study
### 331 Main Board listings, January 2023 – June 2026

*Companion document to the [interactive dashboard](#) — this is the narrative; the dashboard is for exploration and live calculation.*

---

## 1. The question, answered up front

**Does it make sense to participate in the HK IPO rush?** Yes, but the answer depends entirely on which seat you sit in, and the honest expected value is far smaller than the headlines suggest.

- **Institutional / placement**: this is where the return lives. Full allocation at offer captures a mean day-1 pop of **+28.8%** (rising through the period). Access, not stock-picking, is the scarce resource.
- **Retail (Pool A, 1-lot subscription)**: a genuine but *tiny* edge since 2025 — **+46 bps expected return per deal** on committed capital at day-1-close exit, after allocation odds, fees, and financing carry. It was **expected-value-negative in 2023–24**. The edge exists because of adverse selection working in the subscriber's favor at the margin, not because "IPOs pop."
- **Secondary market, chasing the open**: no edge. Buying the day-1 open and selling the close lost money on average in both the design and test periods.
- **Secondary market, buying confirmed winners**: the one live, both-periods-positive secondary strategy — buy the day-1 close only after a confirmed **>+20% pop**, hold to 20 trading days.

Everything below is the evidence for these four claims.

---

## 2. The rush, in numbers

| | 2023 | 2024 | 2025 | 2026 H1 |
|---|---:|---:|---:|---:|
| Deals | 68 | 67 | 113 | 83 (~166 ann.) |
| Capital raised | $5.9B | $11.2B | $36.8B | $26.8B |
| Median deal size | $43M | $56M | $125M | $164M |
| Median retail oversubscription | 7x | 21x | 328x | 1,422x |
| Median day-1 return (offer→close) | +0.8% | +2.8% | +9.3% | +37.5% |

The composition shifted alongside the volume: H-share listings rose from 31% of deals (2023) to 59% (2024–26), and deals priced at the top of their disclosed range rose from 15% to 40%. This is the offshore-listing wave the question refers to — real, accelerating, and increasingly demand-driven rather than supply-driven.

## 3. Performance anatomy — pop, then fade

Median return vs. offer price by horizon (all 331 deals): **Day 1 +7.1% → 1 month +11.0% → 3 months +5.5% → 6 months −2.4% → 1 year −22.0%** (only 34% of deals positive at one year). The mean stays strongly positive throughout because a small number of enormous winners carry it — this is a right-skewed, lottery-shaped distribution, not a steady drift.

**Practical read:** the median investor holding past ~1–3 months has been on the losing side of the median outcome in every cohort we can measure, including the hot 2025–26 vintage. There is no persistent "buy and hold the IPO" edge at the median.

**Demand tier dominates day-1 outcomes**, unsurprisingly: deals oversubscribed >500x return a day-1 median of +55.9% (85% positive); undersubscribed deals return −1.6% (25% positive). The catch: final oversubscription isn't known before the subscription deadline, so this can't drive a subscription decision — but it is fully knowable before the market open the next morning, which is exactly what the secondary-market strategies below use it for.

**Lockup expiry (6 months) shows no exploitable pattern.** Median 1-day return on the expiry date itself: −0.1%, mean −0.6%. Whatever "lockup overhang" story exists in narrative form does not survive contact with the data — and this is *before* the (likely prohibitive) cost of borrowing stock to short a name that's only been trading six months.

## 4. A data-integrity finding worth flagging on its own

Yahoo Finance — the primary price source — silently back-adjusts its entire historical series whenever a company does a post-listing split, bonus issue, or consolidation. This corrupts every return measured against the IPO offer price for the affected names, and it is not visible unless you specifically check for it.

We cross-checked all 331 companies against Tencent's explicitly *unadjusted* daily bars and found **20 companies** with corrupted return histories. Some examples:
- **Midea Group**: reported day-1 return was **+70%**; the true figure, from the raw exchange price, is **+7.8%**.
- **Zhengwei Group** (2023): reported **+1,547%**; true figure **−17.6%**.
- **CiDi Inc.**: reported **−91%**; true figure **−13.7%**.

All 331 companies' returns in this study — and every figure in this document — are corrected. The correction also filled in one company (MiniMax) whose day-1 trading data was simply missing from Yahoo entirely. **Day-1 return coverage is now 331/331.** This is a durable lesson for anyone building HK-market return series on Yahoo data: verify against an unadjusted source before trusting any single-name return that looks unusually large.

## 5. Participation math — what a retail subscriber actually earns

The headline day-1 pop is not what a Pool A subscriber earns — it's what a subscriber earns *if fully allocated*, which essentially never happens. The real number weights the pop by the probability of actually receiving shares, nets out subscription/sale costs (~1.0% and ~0.25% respectively) and the HIBOR carry cost on capital locked for the settlement window, and expresses the result on capital actually committed.

| Exit | Mean return on capital | Median | % of deals profitable |
|---|---:|---:|---:|
| Day-1 open | +54 bps | +20 bps | 58% |
| Day-1 close | **+46 bps** | +22 bps | 59% |
| 5 trading days | +157 bps | +24 bps | 56% |
| 1 month | +269 bps | +37 bps | 57% |
| 3 months | +817 bps | +22 bps | 54% |

Two things matter more than the headline number:

**The edge is regime-dependent, not structural.** By year, mean return on capital at day-1-close exit: 2023 **−138 bps**, 2024 **−86 bps**, 2025 **+124 bps**, 2026H1 **+208 bps**. Subscribing to everything lost money in the pre-rush years. The positive expected value reported above is a 2025–26 phenomenon.

**Adverse selection works against the subscriber exactly where it matters.** Correlation between a deal's allocation probability and its day-1 return: **−0.35**. The deals you're most likely to actually receive shares in are systematically the ones that perform worst — you get filled on what nobody else wanted. This is the mechanical reason the allocation-adjusted edge is a small fraction of the headline pop, not just a fee-and-carry haircut.

**Capacity is real and small.** A 1-lot cash subscriber applying to every one of the 318 modeled deals over 3.5 years earns roughly **HK$19,500** in total expected profit at day-1-close exit (about HK$99,000 at a 3-month exit) — against a median capital commitment per ballot of HK$3,745. This is a genuine, low-risk, low-capital-efficiency strategy, not a source of meaningful capital deployment. Scaling it requires multi-lot applications, whose allocation curves (which fall at higher tiers, per every allotment table we examined) are not modeled here — treat multi-lot outcomes as *worse* than this analysis implies, not better.

## 6. Strategy backtests — designed on 2023–2025, tested untouched on 2026H1

*(Full detail, confidence intervals, and hit rates are in the dashboard's Strategies tab; this section is the summary read.)*

**S1 — Subscribe to everything.** Train-period mean: −5 bps (statistically indistinguishable from zero). Test-period mean: +208 bps (CI [+107, +337], 78% hit rate). The strategy "worked" in 2026H1 purely because the whole test period was a hot regime.

**S2 — Subscribe only when the Hang Seng's trailing 30-day return is positive.** Train: +154 bps. Test: +189 bps. This looks similar to S1 on the test period — because 2026H1 was uniformly hot, no filter could differentiate within it. **The rule's real value is what it excludes in a cold regime (2023–24), not alpha it adds in a hot one.** We recommend it as a simple, cheap-to-implement regime gate, not as a source of test-period outperformance — the two periods can't currently distinguish those two claims from each other, and we're not overclaiming what the data can't yet show.

**S3a — Buy the day-1 open, sell the close.** Train: **−191 bps** (CI excludes zero — reliably unprofitable). Test: −6 bps. Dead at every demand-tier cut we checked. The pop is captured entirely by whoever holds allocation at the open; a secondary buyer chasing the open pays for it.

**S3b — Buy the day-1 close only after a confirmed >+20% pop, hold to 20 trading days.** Train: **+1,112 bps** (CI [+232, +2,021]). Test: **+407 bps** (median +244, 62% hit rate, CI includes zero at n=32). This is the one secondary-market result that is directionally consistent, economically large, and survives into the untouched test period. It is also the one we hardened for production use — see Section 6a, because the pooled number materially overstates what's tradable.

**S4 — Short the lockup expiry window.** +6.5 bps train, before any borrow cost. Not worth pursuing.

## 6a. Hardening S3b for production

A backtested mean is not a trading plan. Before treating S3b as tradable, we stress-tested it — full detail and charts in the dashboard's Strategies tab, under "S3b hardening checks."

- **Concentration**: the top 3 of 79 train-period trades contributed **47%** of the total summed return. Trimmed mean (dropping the 2 best and 2 worst trades): +916 bps, still positive — this is a right-tail-driven edge, not a smooth one. **The median (+546 bps) is the more honest planning number than the mean.**
- **Capacity is the binding constraint.** At a HK$1M position, 63% of qualifying deals would have that position exceed 1% of the deal's own day-1 dollar turnover — past that point the backtest's flat cost assumption stops standing in for real market impact. At HK$100K, only 11% breach that line. **Realistic capacity: roughly HK$100–200K per trade.** This is a real-money strategy, not a scalable allocation.
- **The equity curve is the most important number in this section.** Compounding one unit per qualifying trade with no diversification cap: max drawdown **−92.9%**, longest losing streak **8 consecutive trades**. Whatever the mean says, this is high-variance — size it as a small, capped-per-trade satellite position, never concentrated.
- **Year-by-year, only 2025 clears statistical significance on its own** (mean +1,240 bps, CI excludes zero, n=52). 2023, 2024, and the 2026H1 test period are each individually inconclusive at their sample sizes (CIs include zero) — directionally consistent, not independently confirmed.
- **Costs are not the binding constraint**: the edge survives up to ~2%/leg in train before its CI touches zero.
- **We tested acting earlier** — entering at the day-1 open on an oversubscription threshold instead of waiting for the confirmed close pop. It underperforms (train +195–203 bps vs. S3b's +1,112 bps). The wait for a *confirmed, realized* pop is doing real filtering work; don't front-run it.

**Bottom line: the edge is real and cost-robust, but must be run as a small, hard-capped-size, diversified-across-many-trades position, planned around the median outcome and the observed drawdown — not the headline mean.**

## 6b. Follow-on correlation scan — what else predicts returns

Beyond the five pre-registered strategies, we ran a systematic scan for other point-in-time-legal correlations: every feature bucketed by when it's actually knowable (subscription-time / day-1-eve / post-day-1), correlations computed on **train only**, and anything clearing `|r|≥0.15, p<0.01` checked exactly once against test. Full methodology and all 100 tests are in `output/analysis/correlation_scan_full.csv`.

**Replicated (real, both periods):**
- Day-1 pop → 5-day/20-day/1-month return is a strong **continuous** relationship (train r = +0.88/+0.81/+0.80, test r = +0.87/+0.81/+0.80) — this is the quantitative backbone confirming S3b is a real continuation effect, not an artifact of the +20% cutoff.
- **Retail oversubscription level → forward returns** (r ≈ +0.30 to +0.41, both periods) — notably, this is knowable at **day-1-eve, before the market even opens**, earlier than S3b's signal. We tested using it as an earlier entry trigger (see 6a) — it underperforms waiting for the confirmed pop, but it's a genuine, independently-confirmed demand signal worth monitoring.

**Did not replicate (reported, not discarded quietly):**
- "Hot streak" cross-deal momentum (average day-1 pop of the prior 5 IPOs predicting this one): looked real in train (r +0.23 to +0.28), **vanished in test** (r +0.03 to +0.08, p > 0.47). A plausible-sounding story that a test split kills — exactly what this discipline is for.
- Global-bank lead underwriter → 3-month return: train −42pp, test **+41pp** — sign flip. Discard.
- Pool A allocation rate → longer-horizon returns: directionally consistent with the day-1 adverse-selection finding (Section 5) but not independently significant in test at 5d/20d/1m.

## 7. What we did not do (and why)

Per the agreed scope, three ML tasks — a regularized day-1-return driver model, a walk-forward subscribe/skip classifier, and unsupervised deal-archetype clustering — were deliberately **parked**, not attempted. At n≈330, a linear/regularized model can be defensible; anything more flexible risks fitting noise that a bootstrap or train/test split won't reliably catch. These are available as a next phase on request.

Two known model limitations, stated rather than hidden: multi-lot Pool A allocation curves are not modeled (Section 5); and the lockup-expiry short (S4) and any inferred short exposure elsewhere in this study is reported gross of borrow costs, which for a stock six months post-listing in Hong Kong are frequently prohibitive or unavailable — treat any short-side number here as an optimistic upper bound, not a tradable estimate.

## 8. Data & methodology summary

- **Universe**: 331 Hong Kong Main Board IPOs, Jan 2023–Jun 2026, excluding GEM-to-Main transfers, listings by introduction, and de-SPAC mergers.
- **Sources**: HKEX New Listing Reports, prospectuses, allotment-results announcements, and stabilization notices (full-text extracted, ~1,000 filings); Yahoo Finance and Tencent daily price bars (cross-validated per Section 4); HKMA HIBOR series.
- **Split**: designed on 2023–2025 (n=248), tested once, untouched, on 2026H1 (n=83).
- **Costs modeled**: subscription 1.0084% (brokerage + SFC levy + AFRC levy + trading fee) on allotted shares; sale-side 0.25% (stamp duty + brokerage + slippage) per transaction; HIBOR 1-month carry on capital locked for settlement (6 calendar days pre-FINI/T+5 era, 2 days post-FINI/T+1 era).
- **Statistical approach**: 5,000-resample bootstrap confidence intervals on all strategy means; a fixed train/test split rather than repeated cross-validation, since the object of interest is regime-dependence over calendar time, which cross-validation would average away.

---

*All figures reproducible from the underlying scrape and analysis scripts. See the dashboard's Deal Explorer for per-company detail and the Allocation Calculator for scenario-specific P&L.*
