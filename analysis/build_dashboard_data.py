"""
Exports a compact JSON bundle for the Phase 4 dashboard artifact: per-deal
records (only the fields the dashboard needs) + pre-aggregated chart/strategy
results, so the HTML artifact can be a static self-contained file with no
Python runtime.
"""
import sys
sys.path.insert(0, ".")
import json
import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)
df["prior5_day1_mean"] = df["day1_performance_pct"].shift(1).rolling(5, min_periods=3).mean()

FEE_SUB = 0.010084
SIDE = 0.0025


def clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        if np.isnan(v) or np.isinf(v):
            return None
        return round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if pd.isna(v):
        return None
    return v


DEAL_COLS = [
    "stock_code", "company_name_en", "ipo_date", "year", "quarter", "sector",
    "listing_regime", "size_bucket", "total_ipo_size_usd", "ipo_price_hkd",
    "offer_price_range_low_hkd", "offer_price_range_high_hkd", "pricing_position",
    "priced_at_floor", "priced_at_cap", "times_oversubscribed_retail", "demand_tier",
    "clawback_triggered_flag", "has_cornerstone", "greenshoe_exercised",
    "pool_a_1lot_allocation_rate_pct", "board_lot_shares", "hibor_1m_on_ipo_pct",
    "fini_platform_flag", "day1_open_hkd", "day1_closing_price_hkd",
    "day1_performance_pct", "day1_open_premium_pct", "day1_open_to_close_pct",
    "perf_3d_pct", "perf_5d_pct", "perf_20d_pct", "perf_1m_pct", "perf_3m_pct",
    "perf_lockup_day0_vs_ipo_pct", "perf_on_lockup_expiry_pct", "ipo_perf_1y_pct",
    "hsi_return_30d_prior_pct", "split", "prior5_day1_mean",
]

deals = []
for _, r in df.iterrows():
    rec = {c: clean(r[c]) for c in DEAL_COLS if c in df.columns}
    rec["ipo_date"] = r["ipo_date"].strftime("%Y-%m-%d")
    deals.append(rec)

# ---- pre-aggregated series for charts ----
def q(s, p):
    s = s.dropna()
    return float(np.percentile(s, p)) if len(s) else None


agg = {}

# 1. issuance wave by quarter
w = df.groupby("quarter").agg(deals=("stock_code", "count"),
                               raised_usd_m=("total_ipo_size_usd", lambda s: s.sum() / 1e6))
agg["issuance_wave"] = [{"quarter": k, "deals": int(v.deals), "raised_usd_m": round(v.raised_usd_m, 1)}
                        for k, v in w.iterrows()]

# 2. return distribution by year (median + IQR) per horizon
horizons = [("day1_performance_pct", "Day 1"), ("perf_5d_pct", "5d"), ("perf_20d_pct", "20d"),
            ("perf_1m_pct", "1m"), ("perf_3m_pct", "3m"), ("ipo_perf_1y_pct", "1y")]
by_year_horizon = []
for y, grp in df.groupby("year"):
    row = {"year": int(y)}
    for col, lbl in horizons:
        s = grp[col].dropna()
        row[lbl] = {"median": q(s, 50), "p25": q(s, 25), "p75": q(s, 75), "n": int(len(s))}
    by_year_horizon.append(row)
agg["return_by_year_horizon"] = by_year_horizon

# 3. day-1 return by demand tier
tier_order = ["undersubscribed(<1x)", "1-15x", "15-50x", "50-100x", "100-500x", ">500x"]
by_tier = []
for t in tier_order:
    s = df[df.demand_tier == t]["day1_performance_pct"].dropna()
    if len(s):
        by_tier.append({"tier": t, "median": q(s, 50), "mean": round(float(s.mean()), 2), "n": int(len(s))})
agg["day1_by_demand_tier"] = by_tier

# 4. lockup event path
path_cols = [("perf_lockup_dayminus2_vs_ipo_pct", -2), ("perf_lockup_dayminus1_vs_ipo_pct", -1),
             ("perf_lockup_day0_vs_ipo_pct", 0), ("perf_lockup_dayplus1_vs_ipo_pct", 1),
             ("perf_lockup_dayplus2_vs_ipo_pct", 2)]
agg["lockup_event_path"] = [{"offset": off, "median": q(df[c], 50), "n": int(df[c].notna().sum())}
                            for c, off in path_cols]

# 5. Phase 2 participation (recompute here so JSON matches the report exactly)
d = df[df["board_lot_shares"].notna() & df["pool_a_1lot_allocation_rate_pct"].notna() & df["ipo_price_hkd"].notna()].copy()
d["p_alloc"] = d["pool_a_1lot_allocation_rate_pct"] / 100
d["capital"] = d["board_lot_shares"] * d["ipo_price_hkd"] * (1 + FEE_SUB)
d["lock_days"] = np.where(d["fini_platform_flag"] == "T+1", 2, 6)
d["carry"] = d["capital"] * (d["hibor_1m_on_ipo_pct"] / 100) * d["lock_days"] / 365

exits = {"Day-1 open": ("day1_open_hkd", None), "Day-1 close": ("day1_closing_price_hkd", None),
         "5d": (None, "perf_5d_pct"), "1m": (None, "perf_1m_pct"), "3m": (None, "perf_3m_pct")}
p2 = []
for name, (pxcol, perfcol) in exits.items():
    exit_px = d[pxcol] if pxcol else d["ipo_price_hkd"] * (1 + d[perfcol] / 100)
    win = d["board_lot_shares"] * (exit_px * (1 - SIDE) - d["ipo_price_hkd"] * (1 + FEE_SUB))
    e_ret = (d["p_alloc"] * win - d["carry"]) / d["capital"]
    e_ret = e_ret.dropna()
    p2.append({"exit": name, "mean_bps": round(float(e_ret.mean()) * 1e4, 1),
              "median_bps": round(float(e_ret.median()) * 1e4, 1),
              "pct_positive": round(float((e_ret > 0).mean()) * 100, 1), "n": int(len(e_ret))})
agg["phase2_participation"] = p2

by_year_p2 = []
d1 = d.dropna(subset=["day1_closing_price_hkd"])
win = d1["board_lot_shares"] * (d1["day1_closing_price_hkd"] * (1 - SIDE) - d1["ipo_price_hkd"] * (1 + FEE_SUB))
d1 = d1.assign(e_ret=(d1["p_alloc"] * win - d1["carry"]) / d1["capital"])
for y, grp in d1.groupby("year"):
    by_year_p2.append({"year": int(y), "mean_bps": round(float(grp.e_ret.mean()) * 1e4, 1), "n": int(len(grp))})
agg["phase2_by_year"] = by_year_p2

# 6. Phase 3 strategy summary (train vs test, with bootstrap CI) -- computed
# by phase3_export.py so figures are never hand-transcribed
p3_path = OUT_DIR / "phase3_export.json"
agg["phase3_strategies"] = json.loads(p3_path.read_text()) if p3_path.exists() else []

# 6b. S3b hardening checks -- computed by phase3b_export.py
p3b_path = OUT_DIR / "phase3b_hardening.json"
agg["phase3b_hardening"] = json.loads(p3b_path.read_text()) if p3b_path.exists() else {}

meta = {
    "n_deals": int(len(df)), "date_range": [df.ipo_date.min().strftime("%Y-%m-%d"), df.ipo_date.max().strftime("%Y-%m-%d")],
    "n_train": int((df.split == "train").sum()), "n_test": int((df.split == "test2026H1").sum()),
    "total_raised_usd_bn": round(float(df.total_ipo_size_usd.sum()) / 1e9, 1),
    "corrected_companies": 20,
}

bundle = {"meta": meta, "deals": deals, "agg": agg}
out_path = OUT_DIR / "dashboard_data.json"
out_path.write_text(json.dumps(bundle, separators=(",", ":")))
print(f"Wrote {out_path} ({out_path.stat().st_size/1024:.0f} KB, {len(deals)} deals)")
