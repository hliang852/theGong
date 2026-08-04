"""
Phase 0: builds the analysis dataset for the IPO trading-strategy study from
the scraped output/hkex_ipo_full.csv.

- Parses/derives analysis fields (cohorts, buckets, pricing position, demand
  tiers, train/test split flag: train 2023-2025, test 2026H1 per user spec)
- QC: recomputes day-1 return from raw price fields and cross-checks the
  stored day1_performance_pct; reports disagreements instead of silently
  trusting either
- Writes output/analysis/ipo_analysis.csv + a coverage report
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv("output/hkex_ipo_full.csv", dtype={"stock_code": str})
df["stock_code"] = df["stock_code"].str.zfill(5)
df["ipo_date"] = pd.to_datetime(df["ipo_date"], format="%d/%m/%Y")

# ---- split-adjustment repair (Tencent unadjusted-bars sweep) ----
# Yahoo back-adjusts its entire price series after a post-listing
# split/bonus/consolidation, silently corrupting every vs-offer return (a
# 10:1 subdivision makes day-1 look like -90%). tencent_day1_sweep.py
# compares Yahoo's day-1 close against Tencent's explicitly-unadjusted (bfq)
# bars; factor F = true/yahoo. Repair: true_return = (1+r_yahoo) x F - 1 --
# valid uniformly across horizons because post-action exit dates hold F x
# as many shares, exactly offsetting the price rebasing.
_VS_OFFER_COLS = ["day1_performance_pct", "perf_3d_pct", "perf_5d_pct", "perf_20d_pct",
                  "ipo_perf_1y_pct", "perf_lockup_day0_vs_ipo_pct",
                  "perf_lockup_dayminus1_vs_ipo_pct", "perf_lockup_dayminus2_vs_ipo_pct",
                  "perf_lockup_dayplus1_vs_ipo_pct", "perf_lockup_dayplus2_vs_ipo_pct"]
_t_path = Path(__file__).resolve().parent.parent / "output" / "analysis" / "tencent_day1.csv"
df["split_adj_factor"] = 1.0
if _t_path.exists():
    _t = pd.read_csv(_t_path, dtype={"stock_code": str})
    _t["stock_code"] = _t["stock_code"].str.zfill(5)
    for c in ["t_open", "t_close", "t_high", "t_low", "t_volume", "factor"]:
        _t[c] = pd.to_numeric(_t[c], errors="coerce")
    df = df.merge(_t[["stock_code", "t_open", "t_close", "t_high", "t_low", "t_volume", "factor"]],
                  on="stock_code", how="left")
    needs_fix = df["factor"].notna() & ((df["factor"] - 1).abs() > 0.03)
    df.loc[needs_fix, "split_adj_factor"] = df.loc[needs_fix, "factor"]
    F = df["split_adj_factor"]
    for c in _VS_OFFER_COLS:
        df.loc[needs_fix, c] = ((1 + df.loc[needs_fix, c] / 100) * F[needs_fix] - 1) * 100
    # replace day-1 OHLC with the true unadjusted bars where the series was
    # adjusted, and FILL them where Yahoo had no history at all (e.g. 00100
    # MiniMax, whose ticker Yahoo never backfilled)
    fill = (needs_fix | df["day1_closing_price_hkd"].isna()) & df["t_close"].notna()
    df.loc[fill, "day1_open_hkd"] = df.loc[fill, "t_open"]
    df.loc[fill, "day1_closing_price_hkd"] = df.loc[fill, "t_close"]
    df.loc[fill, "day1_high_hkd"] = df.loc[fill, "t_high"]
    df.loc[fill, "day1_low_hkd"] = df.loc[fill, "t_low"]
    df.loc[fill, "day1_traded_volume_usd"] = (df.loc[fill, "t_volume"] * df.loc[fill, "t_close"] / 7.8).round(2)
    # recompute day-1 return from the now-trusted close for every filled row
    df.loc[fill, "day1_performance_pct"] = ((df.loc[fill, "day1_closing_price_hkd"] / df.loc[fill, "ipo_price_hkd"] - 1) * 100).round(2)
    df = df.drop(columns=["t_open", "t_close", "t_high", "t_low", "t_volume", "factor"])
    print(f"split-adjustment repair: {needs_fix.sum()} companies rescaled, day-1 OHLC replaced/filled for {fill.sum()}")

# ---- cohorts & split ----
df["year"] = df["ipo_date"].dt.year
df["quarter"] = df["ipo_date"].dt.to_period("Q").astype(str)
df["cohort"] = np.where(df["year"] == 2023, "2023 (baseline)", "2024-26 (rush)")
df["split"] = np.where(df["year"] <= 2025, "train", "test2026H1")

# ---- size buckets (USD, at listing) ----
size = df["total_ipo_size_usd"]
df["size_bucket"] = pd.cut(
    size,
    bins=[0, 50e6, 150e6, 500e6, 1.5e9, np.inf],
    labels=["<50M", "50-150M", "150-500M", "500M-1.5B", ">1.5B (mega)"],
)

# ---- pricing position within range (0=floor, 1=cap; NaN if no true range) ----
lo, hi, px = df["offer_price_range_low_hkd"], df["offer_price_range_high_hkd"], df["ipo_price_hkd"]
rng = hi - lo
df["has_price_range"] = rng.notna() & (rng > 0)
df["pricing_position"] = np.where(df["has_price_range"], (px - lo) / rng, np.nan)
df["priced_at_floor"] = df["has_price_range"] & (px <= lo + 1e-9)
df["priced_at_cap"] = df["has_price_range"] & (px >= hi - 1e-9)

# ---- demand tiers ----
over = df["times_oversubscribed_retail"]
df["demand_tier"] = pd.cut(
    over,
    bins=[-np.inf, 1, 15, 50, 100, 500, np.inf],
    labels=["undersubscribed(<1x)", "1-15x", "15-50x", "50-100x", "100-500x", ">500x"],
)
df["clawback_triggered_flag"] = df["clawback_pct_triggered"].notna() & (df["clawback_pct_triggered"] > 10)

# ---- cornerstone ----
df["has_cornerstone"] = df["num_cornerstone_investors"].notna() & (df["num_cornerstone_investors"] > 0)

# ---- sector groups (collapse HSICS categories into trader-familiar groups) ----
df["sector"] = df["hsics_category"].fillna("Unknown")

# ---- listing regime ----
def regime(row):
    if row.get("secondary_listing") is True or str(row.get("secondary_listing")) == "True":
        return "19C secondary"
    if str(row.get("is_chapter_18a")) == "True":
        return "18A biotech"
    if str(row.get("is_chapter_18c")) == "True":
        return "18C specialist tech"
    if str(row.get("is_h_share")) == "True":
        return "H-share"
    return "Standard"
df["listing_regime"] = df.apply(regime, axis=1)

# ---- returns: QC day-1 against raw prices ----
recomputed_d1 = (df["day1_closing_price_hkd"] / df["ipo_price_hkd"] - 1) * 100
stored_d1 = df["day1_performance_pct"]
disagree = (recomputed_d1 - stored_d1).abs() > 0.5  # >0.5pp difference
qc_bad = df.loc[disagree & recomputed_d1.notna() & stored_d1.notna(),
                ["stock_code", "company_name_en", "ipo_price_hkd", "day1_closing_price_hkd",
                 "day1_performance_pct"]]

# open-to-close day-1 (secondary seat entry at open)
df["day1_open_to_close_pct"] = (df["day1_closing_price_hkd"] / df["day1_open_hkd"] - 1) * 100
# open premium vs offer (what you pay up to enter at the open)
df["day1_open_premium_pct"] = (df["day1_open_hkd"] / df["ipo_price_hkd"] - 1) * 100

# ---- 1m / 3m exit horizons (user-requested subscription exit conventions) ----
# Computed from the cached daily OHLCV series (populated during the full
# scrape run: ipo_date-200d .. 2026-06-30, so these calls are pure cache
# hits, no network). Calendar-based: first close on/after ipo_date+30d /
# +91d, NaN if the listing is too recent for the horizon to have elapsed
# before the 2026-06-30 report date.
from datetime import date as _date, timedelta as _timedelta
from scraper import price_data

REPORT_DATE = _date(2026, 6, 30)

def _horizon_returns(row):
    ipo_d = row["ipo_date"].date()
    out = {"perf_1m_pct": np.nan, "perf_3m_pct": np.nan}
    if pd.isna(row["ipo_price_hkd"]):
        return pd.Series(out)
    ticker = price_data.stock_ticker(row["stock_code"])
    px = price_data.fetch_ohlcv(ticker, ipo_d - _timedelta(days=200), REPORT_DATE)
    if px is None or px.empty:
        return pd.Series(out)
    px = px.sort_values("date")
    F = row.get("split_adj_factor", 1.0) or 1.0
    for key, days in (("perf_1m_pct", 30), ("perf_3m_pct", 91)):
        target = pd.Timestamp(ipo_d + _timedelta(days=days))
        if target > pd.Timestamp(REPORT_DATE):
            continue  # horizon hasn't elapsed within our data window
        after = px[px["date"] >= target]
        if not after.empty:
            r = float(after.iloc[0]["close"]) / row["ipo_price_hkd"] - 1
            out[key] = ((1 + r) * F - 1) * 100  # split-adjustment repair, see above
    return pd.Series(out)

df[["perf_1m_pct", "perf_3m_pct"]] = df.apply(_horizon_returns, axis=1)

# ---- board lot size (HKEX widget cache, 'lot' field) ----
import json
def _board_lot(code):
    p = Path("output/cache/hkex_widget") / f"{code.lstrip('0') or '0'}_en.json"
    if p.exists():
        try:
            v = json.load(open(p)).get("lot")
            return int(str(v).replace(",", "")) if v else np.nan
        except Exception:
            return np.nan
    return np.nan
df["board_lot_shares"] = df["stock_code"].map(_board_lot)

# ---- cornerstone patch (chapter-level extraction; see patch_cornerstone.py) ----
# num_cornerstone_investors from that pass failed validation (footnote roman
# numerals miscounted as investors) and is deliberately NOT merged; the
# aggregate USD amount and presence flag validated well and are.
cs_path = Path("output/analysis/cornerstone_patch.csv")
if cs_path.exists():
    cs = pd.read_csv(cs_path, dtype={"stock_code": str})
    cs["stock_code"] = cs["stock_code"].str.zfill(5)
    df = df.merge(
        cs[["stock_code", "has_cornerstone", "cornerstone_total_usd"]].rename(
            columns={"has_cornerstone": "has_cornerstone_v2"}),
        on="stock_code", how="left")
    df["cornerstone_pct_of_deal"] = np.where(
        (df["cornerstone_total_usd"].notna()) & (df["total_ipo_size_usd"] > 0),
        df["cornerstone_total_usd"] / df["total_ipo_size_usd"] * 100, np.nan)
    # a cornerstone amount larger than the deal means the prospectus quoted a
    # scenario we mis-read -- cap and flag rather than carry nonsense
    df.loc[df["cornerstone_pct_of_deal"] > 100, "cornerstone_pct_of_deal"] = np.nan
    df["has_cornerstone"] = df["has_cornerstone_v2"].fillna(df["has_cornerstone"])

# ---- mask invalid 1y returns ----
# The scraper's ipo_perf_1y_pct fell back to the latest available price when
# a full year hadn't elapsed yet -- silently reporting a ~6-month return as
# "1 year" for anything listed after mid-2025. Mask those: a 1y figure is
# only valid if ipo_date + 365d falls within the data window.
invalid_1y = df["ipo_date"] + pd.Timedelta(days=365) > pd.Timestamp(REPORT_DATE)
n_masked = (invalid_1y & df["ipo_perf_1y_pct"].notna()).sum()
df.loc[invalid_1y, "ipo_perf_1y_pct"] = np.nan

# ---- coverage report ----
horizons = {
    "day1_performance_pct": "Day 1",
    "perf_3d_pct": "3d",
    "perf_5d_pct": "5d",
    "perf_20d_pct": "20d",
    "perf_1m_pct": "1m",
    "perf_3m_pct": "3m",
    "perf_lockup_day0_vs_ipo_pct": "~6m (lockup)",
    "ipo_perf_1y_pct": "1y",
}
cov_lines = []
for col, label in horizons.items():
    by_year = df.groupby("year")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)}")
    cov_lines.append(f"{label:14s} " + "  ".join(f"{y}:{v}" for y, v in by_year.items()))

key_inputs = ["times_oversubscribed_retail", "pool_a_1lot_allocation_rate_pct",
              "cornerstone_allocation_pct", "pricing_position", "hibor_1m_on_ipo_pct",
              "day1_open_hkd", "clawback_pct_triggered"]
input_lines = [f"{c:36s} {df[c].notna().sum()}/331" for c in key_inputs]

report = []
report.append(f"Rows: {len(df)}   train(2023-25): {(df['split']=='train').sum()}   test(2026H1): {(df['split']=='test2026H1').sum()}")
report.append("\nHorizon coverage by listing year (non-null/total):")
report.extend("  " + l for l in cov_lines)
report.append("\nKey strategy-input coverage:")
report.extend("  " + l for l in input_lines)
report.append(f"\nDay-1 QC: {disagree.sum()} rows where stored vs recomputed day-1 return differ by >0.5pp")
report.append(f"1y-return mask: {n_masked} rows had a bogus '1y' value (horizon not yet elapsed; scraper had fallen back to latest price) -- now NaN")
if len(qc_bad):
    report.append(qc_bad.to_string(index=False))

df.to_csv(OUT_DIR / "ipo_analysis.csv", index=False)
(OUT_DIR / "phase0_coverage_report.txt").write_text("\n".join(report))
print("\n".join(report))
print(f"\nWrote {OUT_DIR/'ipo_analysis.csv'}")
