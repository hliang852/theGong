"""
Phase 1: descriptive analysis -- the 2024-26 offshore-listing rush in context,
and IPO performance anatomy. Pure pandas over output/analysis/ipo_analysis.csv.
Writes a readable report to output/analysis/phase1_report.txt.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])

L = []
def sec(title):
    L.append("\n" + "=" * 72)
    L.append(title)
    L.append("=" * 72)

def stats(s, label):
    s = s.dropna()
    if not len(s):
        return f"{label:28s} n=0"
    return (f"{label:28s} n={len(s):3d}  mean={s.mean():+7.1f}%  median={s.median():+7.1f}%  "
            f"%pos={(s > 0).mean()*100:4.0f}%  p10={s.quantile(.1):+7.1f}%  p90={s.quantile(.9):+7.1f}%")

# ---------- 1. issuance wave ----------
sec("1. THE ISSUANCE WAVE")
g = df.groupby("year").agg(
    deals=("stock_code", "count"),
    raised_usd_bn=("total_ipo_size_usd", lambda s: s.sum() / 1e9),
    median_size_usd_m=("total_ipo_size_usd", lambda s: s.median() / 1e6),
    mega=("size_bucket", lambda s: (s == ">1.5B (mega)").sum()),
)
L.append(g.to_string(float_format=lambda x: f"{x:,.1f}"))
L.append("\n(2026 is H1 only -- annualized pace ~%d deals)" % (df[df.year == 2026].shape[0] * 2))

# ---------- 2. composition ----------
sec("2. COMPOSITION SHIFT (2023 baseline vs 2024-26 rush)")
comp = pd.crosstab(df["listing_regime"], df["cohort"], normalize="columns") * 100
L.append(comp.round(1).to_string())
L.append("")
sect = pd.crosstab(df["sector"], df["cohort"], normalize="columns") * 100
L.append(sect.round(1).sort_values("2024-26 (rush)", ascending=False).head(8).to_string())

# ---------- 3. demand & pricing ----------
sec("3. DEMAND & PRICING BEHAVIOR")
d = df.groupby("year").agg(
    med_oversub=("times_oversubscribed_retail", "median"),
    pct_over100x=("times_oversubscribed_retail", lambda s: (s > 100).mean() * 100),
    pct_clawback=("clawback_triggered_flag", lambda s: s.mean() * 100),
)
L.append(d.to_string(float_format=lambda x: f"{x:,.1f}"))
L.append("")
ranged = df[df["has_price_range"] == True]  # noqa: E712
L.append(f"Deals with a true price range: {len(ranged)}/331 (rest fixed-price or cap-only)")
L.append(f"  priced at cap: {ranged['priced_at_cap'].mean()*100:.0f}%   at floor: {ranged['priced_at_floor'].mean()*100:.0f}%   in between: {(~ranged['priced_at_cap'] & ~ranged['priced_at_floor']).mean()*100:.0f}%")
for y, grp in ranged.groupby("year"):
    L.append(f"  {y}: cap {grp['priced_at_cap'].mean()*100:3.0f}%  floor {grp['priced_at_floor'].mean()*100:3.0f}%  (n={len(grp)})")

# ---------- 4. performance anatomy ----------
sec("4. RETURN DISTRIBUTIONS VS OFFER PRICE (all deals)")
horizons = [("day1_performance_pct", "Day 1"), ("perf_5d_pct", "5d"), ("perf_20d_pct", "20d"),
            ("perf_1m_pct", "1m"), ("perf_3m_pct", "3m"),
            ("perf_lockup_day0_vs_ipo_pct", "~6m"), ("ipo_perf_1y_pct", "1y")]
for col, label in horizons:
    L.append(stats(df[col], label))
L.append("\nBy cohort, Day 1:")
for c, grp in df.groupby("cohort"):
    L.append("  " + stats(grp["day1_performance_pct"], c))
L.append("\nBy year, Day 1:")
for y, grp in df.groupby("year"):
    L.append("  " + stats(grp["day1_performance_pct"], str(y)))
L.append("\nBy year, 3m:")
for y, grp in df.groupby("year"):
    L.append("  " + stats(grp["perf_3m_pct"], str(y)))

# ---------- 5. day-1 by demand tier ----------
sec("5. DAY-1 RETURN BY DEMAND TIER (retail oversubscription)")
for tier, grp in df.groupby("demand_tier", observed=True):
    L.append(stats(grp["day1_performance_pct"], str(tier)))
L.append("\nDay-1 by size bucket:")
for b, grp in df.groupby("size_bucket", observed=True):
    L.append(stats(grp["day1_performance_pct"], str(b)))

# ---------- 6. the secondary seat preview ----------
sec("6. SECONDARY SEAT: WHAT'S LEFT AFTER THE OPEN")
L.append(stats(df["day1_open_premium_pct"], "Open premium vs offer"))
L.append(stats(df["day1_open_to_close_pct"], "Open -> close (day 1)"))
L.append("\nOpen->close by demand tier:")
for tier, grp in df.groupby("demand_tier", observed=True):
    L.append("  " + stats(grp["day1_open_to_close_pct"], str(tier)))

# ---------- 7. lockup event study ----------
sec("7. LOCKUP EXPIRY (6-month) EVENT STUDY")
L.append(stats(df["perf_on_lockup_expiry_pct"], "1-day return on expiry day"))
# path around expiry vs IPO price: day-2, day-1, day0, day+1, day+2
path_cols = [("perf_lockup_dayminus2_vs_ipo_pct", "-2d"), ("perf_lockup_dayminus1_vs_ipo_pct", "-1d"),
             ("perf_lockup_day0_vs_ipo_pct", "0"), ("perf_lockup_dayplus1_vs_ipo_pct", "+1d"),
             ("perf_lockup_dayplus2_vs_ipo_pct", "+2d")]
L.append("\nMedian cumulative-vs-IPO around expiry: " +
         "  ".join(f"{lbl}:{df[c].median():+.1f}%" for c, lbl in path_cols))

# ---------- 8. stabilization ----------
sec("8. STABILIZATION / GREENSHOE AS A DEMAND SIGNAL")
for flag, grp in df.groupby("greenshoe_exercised"):
    label = "Stabilization notice filed" if flag else "No stabilization notice"
    L.append(stats(grp["day1_performance_pct"], f"D1 | {label}"))
for flag, grp in df.groupby("greenshoe_exercised"):
    label = "Stabilization notice filed" if flag else "No stabilization notice"
    L.append(stats(grp["perf_1m_pct"], f"1m | {label}"))

# ---------- 9. market regime ----------
sec("9. HSI REGIME AT PRICING")
df["hsi30_up"] = df["hsi_return_30d_prior_pct"] > 0
for flag, grp in df.groupby("hsi30_up"):
    L.append(stats(grp["day1_performance_pct"], f"D1 | HSI 30d prior {'UP' if flag else 'DOWN'}"))

report = "\n".join(L)
(OUT_DIR / "phase1_report.txt").write_text(report)
print(report)
