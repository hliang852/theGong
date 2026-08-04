"""
Phase 3: strategy backtests. Train/design on 2023-2025, untouched test on
2026H1. Bootstrap CIs on means (5,000 resamples). All costs per the approved
assumptions:
  subscription: 1.0084% fees on allotted shares; HIBOR carry on committed
                capital (6 days pre-FINI, 2 post)
  secondary:    per side 0.1% stamp + 0.05% brokerage + 0.10% slippage

Point-in-time discipline:
  - Subscription decisions (S1/S2) may use: prospectus facts (cornerstone,
    size, sector, regime), calendar facts (FINI era, HIBOR), market state
    (HSI 30d/90d), and the corrected day-1 performance of the PRIOR 5
    listings. NOT oversubscription/clawback/final price (published later).
  - Day-1 secondary decisions (S3) may additionally use the allotment
    results published the evening before listing: oversubscription tier,
    clawback, allocation rate, final pricing position -- and the open
    premium itself at the open.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(7)
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)

FEE_SUB = 0.010084
SIDE = 0.001 + 0.0005 + 0.001          # 0.25% per side, secondary

# corrected prior-5-IPO day-1 mean (the stored column predates the
# split-adjustment repair, so recompute from the corrected day1 column)
df["prior5_day1_mean"] = (
    df["day1_performance_pct"].shift(1).rolling(5, min_periods=3).mean())

d = df[df["board_lot_shares"].notna() & df["pool_a_1lot_allocation_rate_pct"].notna()
       & df["ipo_price_hkd"].notna()].copy()
d["p_alloc"] = d["pool_a_1lot_allocation_rate_pct"] / 100
d["capital"] = d["board_lot_shares"] * d["ipo_price_hkd"] * (1 + FEE_SUB)
d["lock_days"] = np.where(d["fini_platform_flag"] == "T+1", 2, 6)
d["carry"] = d["capital"] * (d["hibor_1m_on_ipo_pct"] / 100) * d["lock_days"] / 365


def sub_return(sub: pd.DataFrame, exit_col: str) -> pd.Series:
    """expected return on committed capital for a 1-lot subscription."""
    if exit_col == "day1_close":
        exit_px = sub["day1_closing_price_hkd"]
    else:
        exit_px = sub["ipo_price_hkd"] * (1 + sub[exit_col] / 100)
    win = sub["board_lot_shares"] * (exit_px * (1 - SIDE) - sub["ipo_price_hkd"] * (1 + FEE_SUB))
    return (sub["p_alloc"] * win - sub["carry"]) / sub["capital"]


def boot_ci(s: pd.Series, n=5000):
    s = s.dropna().values
    if len(s) < 5:
        return np.nan, np.nan
    means = [np.mean(rng.choice(s, len(s), replace=True)) for _ in range(n)]
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def line(label, s: pd.Series, unit="bps"):
    s = s.dropna()
    if not len(s):
        return f"{label:44s} n=0"
    k = 1e4 if unit == "bps" else 100
    lo, hi = boot_ci(s)
    return (f"{label:44s} n={len(s):3d}  mean={s.mean()*k:+8.1f}  CI95=[{lo*k:+8.1f},{hi*k:+8.1f}]  "
            f"median={s.median()*k:+7.1f}  hit={((s>0).mean()*100):3.0f}%")

L = []
def sec(t):
    L.append("\n" + "=" * 100)
    L.append(t)
    L.append("=" * 100)

train = d[d["split"] == "train"]
test = d[d["split"] == "test2026H1"]

# ---------------- S1: subscribe everything ----------------
sec("S1: SUBSCRIBE EVERYTHING (1-lot cash), expected return on committed capital [bps]")
for exit_col, lbl in [("day1_close", "exit day-1 close"), ("perf_1m_pct", "exit 1m"), ("perf_3m_pct", "exit 3m")]:
    L.append(line(f"TRAIN 2023-25 | {lbl}", sub_return(train, exit_col)))
    L.append(line(f"TEST  2026H1  | {lbl}", sub_return(test, exit_col)))

# ---------------- S2: conditional subscription ----------------
sec("S2: CONDITIONAL SUBSCRIPTION -- pre-registered rules, chosen on train, frozen for test")
RULES = {
    "R1 HSI30d>0":                lambda x: x["hsi_return_30d_prior_pct"] > 0,
    "R2 prior5 day1 mean>+10%":   lambda x: x["prior5_day1_mean"] > 10,
    "R3 has cornerstone":         lambda x: x["has_cornerstone"] == True,  # noqa: E712
    "R4 R2 & R3":                 lambda x: (x["prior5_day1_mean"] > 10) & (x["has_cornerstone"] == True),  # noqa: E712
    "R5 R1 & R2":                 lambda x: (x["hsi_return_30d_prior_pct"] > 0) & (x["prior5_day1_mean"] > 10),
}
scores = {}
for name, rule in RULES.items():
    tr = sub_return(train[rule(train)], "day1_close")
    te = sub_return(test[rule(test)], "day1_close")
    scores[name] = tr.mean()
    L.append(line(f"TRAIN | {name}", tr))
    L.append(line(f"TEST  | {name}", te))
    L.append("")
best = max(scores, key=lambda k: scores[k] if not np.isnan(scores[k]) else -9)
L.append(f">>> chosen on train: {best} (train mean {scores[best]*1e4:+.1f} bps) -- its TEST row above is the honest out-of-sample read")

# ---------------- S3: day-1 secondary entry ----------------
sec("S3: SECONDARY SEAT, day-1 entries [bps on notional]")
d3 = df.dropna(subset=["day1_open_hkd", "day1_closing_price_hkd"]).copy()
d3["oc"] = d3["day1_closing_price_hkd"] / d3["day1_open_hkd"] - 1 - 2 * SIDE
tr3, te3 = d3[d3["split"] == "train"], d3[d3["split"] == "test2026H1"]
L.append(line("TRAIN | buy open, sell close (all deals)", tr3["oc"]))
L.append(line("TEST  | buy open, sell close (all deals)", te3["oc"]))
L.append("")
L.append("conditioned on allotment-results info (knowable pre-open):")
for name, cond in [
    (">500x oversubscribed", lambda x: x["times_oversubscribed_retail"] > 500),
    ("clawback triggered", lambda x: x["clawback_triggered_flag"] == True),  # noqa: E712
    ("undersubscribed", lambda x: x["times_oversubscribed_retail"] < 1),
]:
    L.append(line(f"TRAIN | open->close | {name}", tr3[cond(tr3)]["oc"]))
    L.append(line(f"TEST  | open->close | {name}", te3[cond(te3)]["oc"]))
# hold day1 close -> 20d (momentum)
d3["c20"] = (1 + df.loc[d3.index, "perf_20d_pct"] / 100) / (1 + df.loc[d3.index, "day1_performance_pct"] / 100) - 1 - 2 * SIDE
L.append("")
L.append(line("TRAIN | buy day1 close, sell 20d", d3[d3.split == 'train']["c20"]))
L.append(line("TEST  | buy day1 close, sell 20d", d3[d3.split == 'test2026H1']["c20"]))
L.append(line("TRAIN | ...only if day1 pop > +20%", d3[(d3.split == 'train') & (d3.day1_performance_pct > 20)]["c20"]))
L.append(line("TEST  | ...only if day1 pop > +20%", d3[(d3.split == 'test2026H1') & (d3.day1_performance_pct > 20)]["c20"]))

# ---------------- S4: lockup expiry ----------------
sec("S4: LOCKUP EXPIRY EVENT (6m) -- hypothetical short day-2 -> day+1, NO borrow costs modeled")
df["lock_short"] = -((1 + df["perf_lockup_dayplus1_vs_ipo_pct"] / 100) / (1 + df["perf_lockup_dayminus2_vs_ipo_pct"] / 100) - 1) - 2 * SIDE
L.append(line("TRAIN | short -2d..+1d around expiry", df[(df.split == 'train')]["lock_short"]))
L.append(line("TEST  | short -2d..+1d around expiry", df[(df.split == 'test2026H1')]["lock_short"]))
L.append("NOTE: gross of borrow fees; HK IPO borrow in month 6 typically expensive-to-unavailable -- treat as an upper bound.")

# ---------------- S5: stabilization ----------------
sec("S5: STABILIZATION-PERIOD (day1 close -> 20d, by whether a stabilization notice was later filed)")
for flag, lbl in [(True, "stabilized (weak-demand proxy)"), (False, "never needed support")]:
    sub5 = d3[d3["greenshoe_exercised"] == flag]
    L.append(line(f"TRAIN | {lbl}", sub5[sub5.split == 'train']["c20"]))
    L.append(line(f"TEST  | {lbl}", sub5[sub5.split == 'test2026H1']["c20"]))
L.append("NOTE: the notice itself publishes ~30d post-listing; usable ex-ante only via its pre-listing proxy (pricing at floor, low oversubscription).")

report = "\n".join(L)
(OUT_DIR / "phase3_report.txt").write_text(report)
print(report)
