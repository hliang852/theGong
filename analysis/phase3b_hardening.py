"""
Hardening pass on S3b ("buy the day-1 close only after a confirmed >+20% pop,
sell at 20 trading days") before treating it as production-ready. Checks,
in order:

1. Concentration risk -- is the mean driven by one or two outlier deals?
2. Cost/slippage sensitivity -- where does the edge break even?
3. Capacity -- would the position actually be fillable against real day-1/
   20-day turnover, at a few candidate absolute position sizes?
4. Sub-period stability -- year-by-year within train, not just the pooled figure.
5. An earlier-entry variant using the day-1-eve oversubscription signal found
   in the correlation scan, entering at the OPEN instead of waiting for the
   close+confirmed-pop signal -- does earlier entry help or hurt?
6. Chronological equity curve (compounding, one unit staked per trade) across
   train+test combined, to see drawdown shape rather than just a mean.
"""
import sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(23)
OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
df = df.sort_values("ipo_date").reset_index(drop=True)

BASE_SIDE = 0.0025  # per side: stamp duty + brokerage + slippage, as used throughout


def compute_c20(side):
    d = df.dropna(subset=["day1_open_hkd", "day1_closing_price_hkd", "day1_performance_pct", "perf_20d_pct"]).copy()
    d["c20"] = (1 + d["perf_20d_pct"] / 100) / (1 + d["day1_performance_pct"] / 100) - 1 - 2 * side
    return d


def boot_ci(s, n=5000):
    s = s.dropna().values
    if len(s) < 5:
        return None, None, None
    means = [np.mean(rng.choice(s, len(s), replace=True)) for _ in range(n)]
    return np.percentile(means, 2.5), np.percentile(means, 97.5), np.mean(s)


L = []
def sec(t):
    L.append("\n" + "=" * 96); L.append(t); L.append("=" * 96)

d = compute_c20(BASE_SIDE)
pop = d[d.day1_performance_pct > 20].copy()

# ---------------- 1. concentration risk ----------------
sec("1. CONCENTRATION RISK -- per-deal contribution to the mean")
tr = pop[pop.split == "train"].sort_values("c20", ascending=False)
L.append(f"Train qualifying deals: n={len(tr)}")
L.append(tr[["stock_code", "company_name_en", "ipo_date", "day1_performance_pct", "c20"]].head(8).to_string(index=False))
L.append("...")
L.append(tr[["stock_code", "company_name_en", "ipo_date", "day1_performance_pct", "c20"]].tail(5).to_string(index=False))
top3_share = tr.nlargest(3, "c20")["c20"].sum() / tr["c20"].sum() if tr["c20"].sum() != 0 else float("nan")
L.append(f"\nTop-3-of-{len(tr)} deals' share of total summed return: {top3_share*100:.0f}%")
trimmed = tr["c20"].iloc[2:-2] if len(tr) > 8 else tr["c20"]  # drop top-2/bottom-2
L.append(f"Mean with 2 highest & 2 lowest trimmed: {trimmed.mean()*1e4:+.0f} bps (untrimmed mean: {tr['c20'].mean()*1e4:+.0f} bps)")
L.append(f"Median (robust to outliers by construction): {tr['c20'].median()*1e4:+.0f} bps")

# ---------------- 2. cost sensitivity ----------------
sec("2. COST SENSITIVITY -- per-side round-trip cost assumption vs edge")
for side in [0.0, 0.0025, 0.005, 0.0075, 0.01, 0.02]:
    dd = compute_c20(side)
    p = dd[dd.day1_performance_pct > 20]
    tr_s, te_s = p[p.split == "train"]["c20"], p[p.split == "test2026H1"]["c20"]
    lo_t, hi_t, m_t = boot_ci(tr_s)
    lo_s, hi_s, m_s = boot_ci(te_s)
    L.append(f"side cost {side*100:.2f}%/leg | TRAIN mean {m_t*1e4:+7.0f} bps CI[{lo_t*1e4:+.0f},{hi_t*1e4:+.0f}]  |  TEST mean {m_s*1e4:+7.0f} bps CI[{lo_s*1e4:+.0f},{hi_s*1e4:+.0f}]")

# ---------------- 3. capacity ----------------
sec("3. CAPACITY -- position size vs actual day-1 and 20-day turnover")
pop["day1_usd_turnover"] = pop["day1_traded_volume_usd"]
for cap_usd in [10_000, 100_000, 1_000_000, 5_000_000]:
    pct_of_day1 = (cap_usd / pop["day1_usd_turnover"]).dropna()
    breach = (pct_of_day1 > 0.01).mean() * 100  # position > 1% of day-1 turnover
    L.append(f"Position HK${cap_usd:>9,}: median = {pct_of_day1.median()*100:.3f}% of day-1 turnover; "
             f"{breach:.0f}% of qualifying deals would have this position exceed 1% of day-1 turnover")

# ---------------- 4. sub-period stability ----------------
sec("4. SUB-PERIOD STABILITY (within train, year by year)")
for y, grp in pop[pop.split == "train"].groupby(pop[pop.split == "train"].ipo_date.dt.year):
    lo, hi, m = boot_ci(grp["c20"])
    L.append(f"{y}: n={len(grp):3d}  mean={m*1e4:+.0f} bps  CI=[{lo*1e4:+.0f},{hi*1e4:+.0f}]  hit={ (grp.c20>0).mean()*100:.0f}%")
lo, hi, m = boot_ci(pop[pop.split == "test2026H1"]["c20"])
L.append(f"2026H1 (test): n={len(pop[pop.split=='test2026H1']):3d}  mean={m*1e4:+.0f} bps  CI=[{lo*1e4:+.0f},{hi*1e4:+.0f}]  hit={(pop[pop.split=='test2026H1'].c20>0).mean()*100:.0f}%")

# ---------------- 5. earlier-entry variant using oversubscription ----------------
sec("5. EARLIER-ENTRY VARIANT -- trigger on day-1-eve oversubscription instead of waiting for the confirmed pop")
d2 = df.dropna(subset=["day1_open_hkd", "perf_20d_pct", "day1_performance_pct", "times_oversubscribed_retail"]).copy()
d2["open_to_20d"] = (1 + d2["perf_20d_pct"] / 100) / (1 + d2["day1_performance_pct"] / 100) * \
                     (d2["day1_closing_price_hkd"] / d2["day1_open_hkd"]) - 1 - 2 * BASE_SIDE
for thresh, label in [(100, ">100x"), (500, ">500x")]:
    sub = d2[d2.times_oversubscribed_retail > thresh]
    tr_e, te_e = sub[sub.split == "train"]["open_to_20d"], sub[sub.split == "test2026H1"]["open_to_20d"]
    lo_t, hi_t, m_t = boot_ci(tr_e)
    lo_s, hi_s, m_s = boot_ci(te_e)
    L.append(f"Enter at OPEN if oversubscribed {label}, hold to 20d | TRAIN n={len(tr_e)} mean={m_t*1e4 if m_t else float('nan'):+.0f} bps CI[{lo_t*1e4 if lo_t else 0:+.0f},{hi_t*1e4 if hi_t else 0:+.0f}]  |  TEST n={len(te_e)} mean={m_s*1e4 if m_s else float('nan'):+.0f} bps")
L.append("\nCompare to S3b (enter at CLOSE after confirmed >20% pop, hold to 20d):")
lo_t, hi_t, m_t = boot_ci(pop[pop.split == "train"]["c20"])
lo_s, hi_s, m_s = boot_ci(pop[pop.split == "test2026H1"]["c20"])
L.append(f"  TRAIN n={len(pop[pop.split=='train'])} mean={m_t*1e4:+.0f} bps CI[{lo_t*1e4:+.0f},{hi_t*1e4:+.0f}]  |  TEST n={len(pop[pop.split=='test2026H1'])} mean={m_s*1e4:+.0f} bps CI[{lo_s*1e4:+.0f},{hi_s*1e4:+.0f}]")

# ---------------- 6. equity curve ----------------
sec("6. CHRONOLOGICAL EQUITY CURVE (1 unit staked per qualifying trade, compounding)")
chrono = pop.sort_values("ipo_date")
equity = (1 + chrono["c20"]).cumprod()
chrono = chrono.assign(equity=equity.values)
running_max = equity.cummax()
drawdown = (equity / running_max - 1)
L.append(f"Trades: {len(chrono)}  Final equity (from 1.0): {equity.iloc[-1]:.2f}")
L.append(f"Max drawdown: {drawdown.min()*100:.1f}%  (at {chrono.iloc[drawdown.values.argmin()]['company_name_en']}, {chrono.iloc[drawdown.values.argmin()]['ipo_date'].date()})")
L.append(f"Longest losing streak (consecutive negative trades): {(chrono['c20']<0).astype(int).groupby((chrono['c20']>=0).cumsum()).sum().max()}")

report = "\n".join(L)
(OUT_DIR / "phase3b_hardening_report.txt").write_text(report)
print(report)
