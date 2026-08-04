"""
Systematic correlation scan across every point-in-time-legal feature we have,
against forward returns at multiple horizons. Methodology (stated up front
because "how did you find them" is as important as what was found):

1. POINT-IN-TIME BUCKETING. Features are split into three buckets by when
   they're actually knowable, and only ever tested against decisions made at
   or after that moment:
     A. Subscription-time  -- prospectus facts, calendar, macro regime,
        prior-deal history. Knowable before the subscription deadline.
     B. Day-1-eve          -- everything in A, plus the allotment-results
        announcement (oversubscription, clawback, allocation rate,
        concentration). Published the evening before listing.
     C. Post-day-1         -- everything in B, plus the day's own trading
        (pop size, volume, open-to-close). Knowable only after the close.
   A feature is never tested against a target that occurs before the
   feature would have been known.

2. TRAIN-ONLY SCANNING. Every correlation in this scan is computed on the
   2023-2025 train split ONLY. The 2026H1 test split is touched exactly
   once, at the end, to bootstrap-validate whatever survives step 3 -- the
   same discipline as the Phase 3 strategy backtests.

3. MULTIPLE-TESTING AWARENESS. ~30 features x ~4 targets per bucket is
   ~100+ tests; at p<0.05 naively, several "significant" correlations are
   expected by chance alone. Candidates are ranked by |r| but only reported
   as findings if they clear a stricter bar (|r|>=0.15 and p<0.01) AND
   survive the test-period bootstrap with a CI that excludes zero. Anything
   that clears the train bar but not the test bar is reported as "did not
   replicate," not quietly dropped -- a null result after a promising train
   read is itself informative about overfitting risk in this dataset.

4. STATISTIC PER FEATURE TYPE. Continuous x continuous: Pearson r (and
   Spearman as a robustness check, since return distributions are skewed).
   Binary/categorical x continuous: mean difference between groups +
   Welch's t-test p-value.
"""
import sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from scipy import stats
from pathlib import Path

rng = np.random.default_rng(11)
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)

# pull in is_wvr, dropped from the production schema but present in the NLR source
from scraper import parse_nlr
nlr = parse_nlr.load_all()
kept, _ = parse_nlr.apply_scope_filters(nlr)
kept["stock_code"] = kept["stock_code"].astype(str).str.zfill(5)
df = df.merge(kept[["stock_code", "is_wvr"]].drop_duplicates("stock_code"), on="stock_code", how="left")
df["prior5_day1_mean"] = df["day1_performance_pct"].shift(1).rolling(5, min_periods=3).mean()

train = df[df["split"] == "train"].copy()
test = df[df["split"] == "test2026H1"].copy()

CONTINUOUS_A = ["total_ipo_size_usd", "pricing_position", "hsi_return_30d_prior_pct",
                "hsi_return_90d_prior_pct", "prior5_day1_mean", "hibor_1m_on_ipo_pct",
                "cornerstone_pct_of_deal"]
BINARY_A = ["priced_at_floor", "priced_at_cap", "is_chapter_18a", "is_chapter_18c",
            "is_h_share", "secondary_listing", "is_wvr", "has_cornerstone",
            "cornerstone_pedigree_global_fund", "cornerstone_pedigree_sovereign_wealth",
            "cornerstone_pedigree_large_company", "lead_broker_is_global_bank",
            "lead_broker_is_chinese_bank", "multiple_lead_brokers"]
CONTINUOUS_B = ["times_oversubscribed_retail", "clawback_pct_triggered",
                "pool_a_1lot_allocation_rate_pct", "top1_placee_concentration_pct",
                "top20_placee_concentration_pct", "top1_shareholder_concentration_pct",
                "top20_shareholder_concentration_pct", "num_valid_retail_applicants"]
BINARY_B = ["clawback_triggered_flag", "hkex_high_concentration_flag"]
CONTINUOUS_C = ["day1_performance_pct", "day1_open_premium_pct", "day1_open_to_close_pct",
                "day1_traded_volume_usd", "day1_volume_vs_free_float_pct"]

TARGETS_A = ["day1_performance_pct", "perf_1m_pct", "perf_3m_pct", "ipo_perf_1y_pct"]
TARGETS_B = ["day1_open_to_close_pct", "perf_5d_pct", "perf_20d_pct", "perf_1m_pct"]
TARGETS_C = ["perf_5d_pct", "perf_20d_pct", "perf_1m_pct", "perf_3m_pct"]


def scan_continuous(data, features, targets, bucket):
    rows = []
    for f in features:
        for t in targets:
            if f == t:
                continue
            sub = data[[f, t]].dropna()
            if len(sub) < 30:
                continue
            r, p = stats.pearsonr(sub[f], sub[t])
            rs, ps = stats.spearmanr(sub[f], sub[t])
            rows.append({"bucket": bucket, "feature": f, "target": t, "type": "continuous",
                        "n": len(sub), "pearson_r": r, "pearson_p": p, "spearman_r": rs, "spearman_p": ps})
    return rows


def scan_binary(data, features, targets, bucket):
    rows = []
    for f in features:
        for t in targets:
            sub = data[[f, t]].dropna()
            sub = sub[sub[f].isin([True, False, 0, 1])]
            if len(sub) < 30:
                continue
            g1 = sub[sub[f].astype(bool)][t]
            g0 = sub[~sub[f].astype(bool)][t]
            if len(g1) < 10 or len(g0) < 10:
                continue
            tstat, p = stats.ttest_ind(g1, g0, equal_var=False)
            rows.append({"bucket": bucket, "feature": f, "target": t, "type": "binary",
                        "n": len(sub), "n_true": len(g1), "n_false": len(g0),
                        "mean_true": g1.mean(), "mean_false": g0.mean(),
                        "diff": g1.mean() - g0.mean(), "pearson_p": p})
    return rows


all_rows = []
all_rows += scan_continuous(train, CONTINUOUS_A, TARGETS_A, "A: subscription-time")
all_rows += scan_binary(train, BINARY_A, TARGETS_A, "A: subscription-time")
all_rows += scan_continuous(train, CONTINUOUS_B, TARGETS_B, "B: day-1-eve")
all_rows += scan_binary(train, BINARY_B, TARGETS_B, "B: day-1-eve")
all_rows += scan_continuous(train, CONTINUOUS_C, TARGETS_C, "C: post-day-1")

res = pd.DataFrame(all_rows)
res.to_csv(OUT_DIR / "correlation_scan_full.csv", index=False)

# ---- rank candidates ----
cont = res[res.type == "continuous"].copy()
cont["score"] = cont.pearson_r.abs()
cont_hits = cont[(cont.pearson_r.abs() >= 0.15) & (cont.pearson_p < 0.01)].sort_values("score", ascending=False)

binr = res[res.type == "binary"].copy()
# effect size proxy: diff / pooled std of target within bucket
binr["score"] = binr["diff"].abs()
bin_hits = binr[(binr.pearson_p < 0.01)].copy()
# require a "meaningful" diff too -- at least 300bps for pct-point targets
bin_hits = bin_hits[bin_hits["diff"].abs() >= 3.0].sort_values("score", ascending=False)

print(f"Continuous scan: {len(cont)} tests run, {len(cont_hits)} clear |r|>=0.15 & p<0.01")
print(cont_hits[["bucket", "feature", "target", "n", "pearson_r", "pearson_p", "spearman_r"]].to_string(index=False))
print()
print(f"Binary/group scan: {len(binr)} tests run, {len(bin_hits)} clear diff>=3pp & p<0.01")
print(bin_hits[["bucket", "feature", "target", "n_true", "n_false", "mean_true", "mean_false", "diff", "pearson_p"]].to_string(index=False))


# ---- bootstrap-validate top candidates on TEST ----
def boot_mean_ci(s, n=5000):
    s = s.dropna().values
    if len(s) < 5:
        return None, None
    means = [np.mean(rng.choice(s, len(s), replace=True)) for _ in range(n)]
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


print("\n" + "=" * 100)
print("TEST-PERIOD VALIDATION of train-period candidates")
print("=" * 100)
validated = []
for _, row in cont_hits.iterrows():
    f, t = row.feature, row.target
    sub = test[[f, t]].dropna()
    if len(sub) < 15:
        print(f"{row.bucket} | {f} -> {t}: test n={len(sub)} (too small to validate)")
        continue
    r, p = stats.pearsonr(sub[f], sub[t])
    print(f"{row.bucket} | {f} -> {t}: TRAIN r={row.pearson_r:+.2f} (p={row.pearson_p:.4f})  |  TEST r={r:+.2f} (p={p:.4f}, n={len(sub)})  {'SAME SIGN' if np.sign(r)==np.sign(row.pearson_r) else 'SIGN FLIPPED'}")
    validated.append({**row.to_dict(), "test_r": r, "test_p": p, "test_n": len(sub)})

for _, row in bin_hits.iterrows():
    f, t = row.feature, row.target
    sub = test[[f, t]].dropna()
    sub = sub[sub[f].isin([True, False, 0, 1])]
    g1, g0 = sub[sub[f].astype(bool)][t], sub[~sub[f].astype(bool)][t]
    if len(g1) < 8 or len(g0) < 8:
        print(f"{row.bucket} | {f} -> {t}: test groups too small (n_true={len(g1)}, n_false={len(g0)})")
        continue
    diff = g1.mean() - g0.mean()
    lo1, hi1 = boot_mean_ci(g1)
    lo0, hi0 = boot_mean_ci(g0)
    print(f"{row.bucket} | {f} -> {t}: TRAIN diff={row['diff']:+.1f}pp  |  TEST diff={diff:+.1f}pp (true n={len(g1)} CI[{lo1:.1f},{hi1:.1f}], false n={len(g0)} CI[{lo0:.1f},{hi0:.1f}])")
    validated.append({**row.to_dict(), "test_diff": diff, "test_n_true": len(g1), "test_n_false": len(g0)})

pd.DataFrame(validated).to_csv(OUT_DIR / "correlation_candidates_validated.csv", index=False)
print(f"\nWrote {OUT_DIR/'correlation_scan_full.csv'} (all {len(res)} tests) and correlation_candidates_validated.csv ({len(validated)} candidates)")
