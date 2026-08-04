"""Re-derives the Phase 3 headline strategies with bootstrap CI, as structured
JSON for the dashboard (avoids hand-transcribing numbers from the text report)."""
import sys
sys.path.insert(0, ".")
import json
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(7)
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)

FEE_SUB = 0.010084
SIDE = 0.0025
df["prior5_day1_mean"] = df["day1_performance_pct"].shift(1).rolling(5, min_periods=3).mean()

d = df[df["board_lot_shares"].notna() & df["pool_a_1lot_allocation_rate_pct"].notna() & df["ipo_price_hkd"].notna()].copy()
d["p_alloc"] = d["pool_a_1lot_allocation_rate_pct"] / 100
d["capital"] = d["board_lot_shares"] * d["ipo_price_hkd"] * (1 + FEE_SUB)
d["lock_days"] = np.where(d["fini_platform_flag"] == "T+1", 2, 6)
d["carry"] = d["capital"] * (d["hibor_1m_on_ipo_pct"] / 100) * d["lock_days"] / 365


def sub_return(sub, exit_col):
    exit_px = sub["day1_closing_price_hkd"] if exit_col == "day1_close" else sub["ipo_price_hkd"] * (1 + sub[exit_col] / 100)
    win = sub["board_lot_shares"] * (exit_px * (1 - SIDE) - sub["ipo_price_hkd"] * (1 + FEE_SUB))
    return (sub["p_alloc"] * win - sub["carry"]) / sub["capital"]


def boot(s, n=5000):
    s = s.dropna().values
    if len(s) < 5:
        return {"mean_bps": None, "lo_bps": None, "hi_bps": None, "median_bps": None, "hit": None, "n": len(s)}
    means = [np.mean(rng.choice(s, len(s), replace=True)) for _ in range(n)]
    return {"mean_bps": round(float(s.mean()) * 1e4, 1), "lo_bps": round(float(np.percentile(means, 2.5)) * 1e4, 1),
            "hi_bps": round(float(np.percentile(means, 97.5)) * 1e4, 1), "median_bps": round(float(np.median(s)) * 1e4, 1),
            "hit": round(float((s > 0).mean()) * 100, 1), "n": int(len(s))}


train = d[d["split"] == "train"]
test = d[d["split"] == "test2026H1"]

out = []
out.append({"strategy": "S1: Subscribe all", "exit": "day1_close",
           "train": boot(sub_return(train, "day1_close")), "test": boot(sub_return(test, "day1_close"))})
out.append({"strategy": "S1: Subscribe all", "exit": "1m",
           "train": boot(sub_return(train, "perf_1m_pct")), "test": boot(sub_return(test, "perf_1m_pct"))})
out.append({"strategy": "S1: Subscribe all", "exit": "3m",
           "train": boot(sub_return(train, "perf_3m_pct")), "test": boot(sub_return(test, "perf_3m_pct"))})

rule_hsi = lambda x: x["hsi_return_30d_prior_pct"] > 0
out.append({"strategy": "S2: Subscribe only if HSI 30d>0", "exit": "day1_close",
           "train": boot(sub_return(train[rule_hsi(train)], "day1_close")),
           "test": boot(sub_return(test[rule_hsi(test)], "day1_close"))})

d3 = df.dropna(subset=["day1_open_hkd", "day1_closing_price_hkd"]).copy()
d3["oc"] = d3["day1_closing_price_hkd"] / d3["day1_open_hkd"] - 1 - 2 * SIDE
out.append({"strategy": "S3: Buy open, sell close", "exit": "day1", "unit": "notional",
           "train": boot(d3[d3.split == "train"]["oc"]), "test": boot(d3[d3.split == "test2026H1"]["oc"])})

d3["c20"] = (1 + df.loc[d3.index, "perf_20d_pct"] / 100) / (1 + df.loc[d3.index, "day1_performance_pct"] / 100) - 1 - 2 * SIDE
pop = d3[d3.day1_performance_pct > 20]
out.append({"strategy": "S3: Buy close, sell 20d (if day1 pop>20%)", "exit": "20d", "unit": "notional",
           "train": boot(pop[pop.split == "train"]["c20"]), "test": boot(pop[pop.split == "test2026H1"]["c20"])})

df["lock_short"] = -((1 + df["perf_lockup_dayplus1_vs_ipo_pct"] / 100) / (1 + df["perf_lockup_dayminus2_vs_ipo_pct"] / 100) - 1) - 2 * SIDE
out.append({"strategy": "S4: Short lockup expiry (-2d..+1d, ex-borrow)", "exit": "event", "unit": "notional",
           "train": boot(df[df.split == "train"]["lock_short"]), "test": boot(df[df.split == "test2026H1"]["lock_short"])})

(OUT_DIR / "phase3_export.json").write_text(json.dumps(out, indent=1))
print(f"Wrote {OUT_DIR/'phase3_export.json'}")
for o in out:
    print(o["strategy"], o["exit"], "| train", o["train"]["mean_bps"], "| test", o["test"]["mean_bps"])
