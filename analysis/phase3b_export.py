"""Structured JSON export of the S3b hardening checks, for the dashboard."""
import sys
sys.path.insert(0, ".")
import json
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(23)
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)
BASE_SIDE = 0.0025


def compute_c20(side):
    d = df.dropna(subset=["day1_open_hkd", "day1_closing_price_hkd", "day1_performance_pct", "perf_20d_pct"]).copy()
    d["c20"] = (1 + d["perf_20d_pct"] / 100) / (1 + d["day1_performance_pct"] / 100) - 1 - 2 * side
    return d


def boot_ci(s, n=5000):
    s = s.dropna().values
    if len(s) < 5:
        return {"mean_bps": None, "lo_bps": None, "hi_bps": None, "n": len(s)}
    means = [np.mean(rng.choice(s, len(s), replace=True)) for _ in range(n)]
    return {"mean_bps": round(float(np.mean(s)) * 1e4, 1), "lo_bps": round(float(np.percentile(means, 2.5)) * 1e4, 1),
            "hi_bps": round(float(np.percentile(means, 97.5)) * 1e4, 1),
            "median_bps": round(float(np.median(s)) * 1e4, 1), "hit": round(float((s > 0).mean()) * 100, 1), "n": int(len(s))}


d = compute_c20(BASE_SIDE)
pop = d[d.day1_performance_pct > 20].copy()

out = {}

# concentration
tr = pop[pop.split == "train"].sort_values("c20", ascending=False)
top3_share = tr.nlargest(3, "c20")["c20"].sum() / tr["c20"].sum()
trimmed_mean = tr["c20"].iloc[2:-2].mean() if len(tr) > 8 else tr["c20"].mean()
out["concentration"] = {
    "n_train": int(len(tr)), "top3_share_pct": round(float(top3_share) * 100, 1),
    "trimmed_mean_bps": round(float(trimmed_mean) * 1e4, 1),
    "untrimmed_mean_bps": round(float(tr["c20"].mean()) * 1e4, 1),
    "median_bps": round(float(tr["c20"].median()) * 1e4, 1),
    "top_deals": [{"code": r.stock_code, "name": r.company_name_en, "date": r.ipo_date.strftime("%Y-%m-%d"),
                  "day1_pct": round(float(r.day1_performance_pct), 1), "c20_pct": round(float(r.c20) * 100, 1)}
                 for r in tr.head(5).itertuples()],
    "bottom_deals": [{"code": r.stock_code, "name": r.company_name_en, "date": r.ipo_date.strftime("%Y-%m-%d"),
                      "day1_pct": round(float(r.day1_performance_pct), 1), "c20_pct": round(float(r.c20) * 100, 1)}
                     for r in tr.tail(5).itertuples()],
}

# cost sensitivity
cost_rows = []
for side in [0.0, 0.0025, 0.005, 0.0075, 0.01, 0.02]:
    dd = compute_c20(side)
    p = dd[dd.day1_performance_pct > 20]
    cost_rows.append({"side_pct": side * 100, "train": boot_ci(p[p.split == "train"]["c20"]),
                      "test": boot_ci(p[p.split == "test2026H1"]["c20"])})
out["cost_sensitivity"] = cost_rows

# capacity
cap_rows = []
for cap_usd in [10_000, 50_000, 100_000, 250_000, 1_000_000, 5_000_000]:
    pct = (cap_usd / pop["day1_traded_volume_usd"]).dropna()
    cap_rows.append({"position_usd": cap_usd, "median_pct_of_day1_turnover": round(float(pct.median()) * 100, 3),
                     "pct_deals_breaching_1pct": round(float((pct > 0.01).mean()) * 100, 1)})
out["capacity"] = cap_rows

# sub-period stability
year_rows = []
for y, grp in pop[pop.split == "train"].groupby(pop[pop.split == "train"].ipo_date.dt.year):
    year_rows.append({"year": int(y), **boot_ci(grp["c20"])})
year_rows.append({"year": "2026H1 (test)", **boot_ci(pop[pop.split == "test2026H1"]["c20"])})
out["sub_period_stability"] = year_rows

# earlier-entry variant
d2 = df.dropna(subset=["day1_open_hkd", "perf_20d_pct", "day1_performance_pct", "times_oversubscribed_retail", "day1_closing_price_hkd"]).copy()
d2["open_to_20d"] = (1 + d2["perf_20d_pct"] / 100) / (1 + d2["day1_performance_pct"] / 100) * \
                     (d2["day1_closing_price_hkd"] / d2["day1_open_hkd"]) - 1 - 2 * BASE_SIDE
variants = []
for thresh, label in [(100, ">100x oversub, enter at open"), (500, ">500x oversub, enter at open")]:
    sub = d2[d2.times_oversubscribed_retail > thresh]
    variants.append({"label": label, "train": boot_ci(sub[sub.split == "train"]["open_to_20d"]),
                     "test": boot_ci(sub[sub.split == "test2026H1"]["open_to_20d"])})
variants.append({"label": "S3b: confirmed >20% pop, enter at close", "train": boot_ci(pop[pop.split == "train"]["c20"]),
                 "test": boot_ci(pop[pop.split == "test2026H1"]["c20"])})
out["entry_timing_variants"] = variants

# equity curve
chrono = pop.sort_values("ipo_date").copy()
equity = (1 + chrono["c20"]).cumprod()
running_max = equity.cummax()
drawdown = (equity / running_max - 1)
dd_min_idx = drawdown.values.argmin()
losing_streak = int((chrono["c20"] < 0).astype(int).groupby((chrono["c20"] >= 0).cumsum()).sum().max())
out["equity_curve"] = {
    "points": [{"date": r.ipo_date.strftime("%Y-%m-%d"), "equity": round(float(eq), 4), "drawdown_pct": round(float(dd) * 100, 1)}
              for r, eq, dd in zip(chrono.itertuples(), equity, drawdown)],
    "final_equity": round(float(equity.iloc[-1]), 2),
    "max_drawdown_pct": round(float(drawdown.min()) * 100, 1),
    "max_drawdown_deal": chrono.iloc[dd_min_idx]["company_name_en"],
    "max_drawdown_date": chrono.iloc[dd_min_idx]["ipo_date"].strftime("%Y-%m-%d"),
    "longest_losing_streak": losing_streak,
    "n_trades": int(len(chrono)),
}

(OUT_DIR / "phase3b_hardening.json").write_text(json.dumps(out, indent=1))
print(f"Wrote {OUT_DIR/'phase3b_hardening.json'}")
print(json.dumps(out["concentration"], indent=1))
print(json.dumps(out["equity_curve"], indent=1)[:400])
