"""
Phase 2: allocation-adjusted participation math -- the retail Pool A seat.

Models the classic 1-lot cash subscription per deal ("da xin"):
  capital committed = board_lot x offer price x (1 + subscription fees)
  P(win 1 lot)      = pool_a_1lot_allocation_rate_pct / 100
  subscription fees = 1% brokerage + 0.0027% SFC + 0.00015% AFRC + 0.00565%
                      trading fee (refunded pro-rata on unallotted shares, so
                      effectively borne on allotted shares only)
  sell costs        = 0.1% stamp duty + 0.05% brokerage + 0.10% slippage
  opportunity cost  = HIBOR 1M x lock days / 365 on committed capital
                      (lock: 6 calendar days pre-FINI, 2 post-FINI)

E[net P&L per deal] = p x lot x (P_exit x (1 - sell) - P_ipo x (1 + fee))
                      - capital x hibor x days/365
E[return on committed capital] = E[net P&L] / capital

Exits: day-1 open, day-1 close, 5d, 1m, 3m.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "analysis"
df = pd.read_csv(OUT_DIR / "ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])

FEE_SUB = 0.01 + 0.000027 + 0.0000015 + 0.0000565   # ~1.0084% on subscription
FEE_SELL = 0.001 + 0.0005 + 0.001                     # 0.25% on sale

d = df[df["board_lot_shares"].notna() & df["pool_a_1lot_allocation_rate_pct"].notna()
       & df["ipo_price_hkd"].notna()].copy()
d["p_alloc"] = d["pool_a_1lot_allocation_rate_pct"] / 100
d["lot"] = d["board_lot_shares"]
d["capital_hkd"] = d["lot"] * d["ipo_price_hkd"] * (1 + FEE_SUB)
d["lock_days"] = np.where(d["fini_platform_flag"] == "T+1", 2, 6)
d["opp_cost_hkd"] = d["capital_hkd"] * (d["hibor_1m_on_ipo_pct"] / 100) * d["lock_days"] / 365

EXITS = {
    "day1_open": ("day1_open_hkd", None),
    "day1_close": ("day1_closing_price_hkd", None),
    "5d": (None, "perf_5d_pct"),
    "1m": (None, "perf_1m_pct"),
    "3m": (None, "perf_3m_pct"),
}

rows = []
for name, (price_col, perf_col) in EXITS.items():
    if price_col:
        exit_px = d[price_col]
    else:
        exit_px = d["ipo_price_hkd"] * (1 + d[perf_col] / 100)
    win_pnl = d["lot"] * (exit_px * (1 - FEE_SELL) - d["ipo_price_hkd"] * (1 + FEE_SUB))
    e_pnl = d["p_alloc"] * win_pnl - d["opp_cost_hkd"]
    e_ret = e_pnl / d["capital_hkd"]
    valid = e_ret.notna()
    sub = pd.DataFrame({"e_pnl": e_pnl[valid], "e_ret": e_ret[valid],
                        "year": d.loc[valid, "year"], "tier": d.loc[valid, "demand_tier"]})
    rows.append({
        "exit": name, "n": int(valid.sum()),
        "mean_ret_bps": sub.e_ret.mean() * 1e4,
        "median_ret_bps": sub.e_ret.median() * 1e4,
        "pct_deals_positive": (sub.e_ret > 0).mean() * 100,
        "total_E_pnl_hkd": sub.e_pnl.sum(),
        "mean_E_pnl_hkd": sub.e_pnl.mean(),
    })
    if name == "day1_close":
        by_year = sub.groupby("year").agg(n=("e_ret", "size"), mean_ret_bps=("e_ret", lambda s: s.mean() * 1e4),
                                          pct_pos=("e_ret", lambda s: (s > 0).mean() * 100),
                                          total_E_pnl=("e_pnl", "sum"))
        by_tier = sub.groupby("tier", observed=True).agg(n=("e_ret", "size"),
                                                          mean_ret_bps=("e_ret", lambda s: s.mean() * 1e4),
                                                          total_E_pnl=("e_pnl", "sum"))

res = pd.DataFrame(rows)

L = []
L.append(f"Deals modeled: {len(d)}/331 (excluded: missing board lot / allocation rate / price)")
L.append(f"Capital per deal: median HK${d.capital_hkd.median():,.0f}  p10 HK${d.capital_hkd.quantile(.1):,.0f}  p90 HK${d.capital_hkd.quantile(.9):,.0f}")
L.append(f"Median allocation probability (1 lot): {d.p_alloc.median()*100:.1f}%   mean: {d.p_alloc.mean()*100:.1f}%")
L.append("")
L.append("=== EXPECTED RETURN ON COMMITTED CAPITAL, PER DEAL (1-lot cash subscription) ===")
L.append(res.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
L.append("")
L.append("=== DAY-1-CLOSE EXIT, BY YEAR ===")
L.append(by_year.to_string(float_format=lambda x: f"{x:,.1f}"))
L.append("")
L.append("=== DAY-1-CLOSE EXIT, BY DEMAND TIER ===")
L.append(by_tier.to_string(float_format=lambda x: f"{x:,.1f}"))
L.append("")
# the honest comparison: headline (full allocation) vs allocation-adjusted
d1 = d[d.day1_closing_price_hkd.notna()]
headline = (d1.day1_closing_price_hkd / d1.ipo_price_hkd - 1)
L.append("=== HEADLINE vs REALITY (day-1 close) ===")
L.append(f"Headline mean day-1 return (full allocation fantasy): {headline.mean()*100:+.1f}%")
adj = (d1.p_alloc * d1.lot * (d1.day1_closing_price_hkd * (1 - FEE_SELL) - d1.ipo_price_hkd * (1 + FEE_SUB)) - d1.opp_cost_hkd) / d1.capital_hkd
L.append(f"Allocation-adjusted mean return on committed capital:  {adj.mean()*1e4:+,.0f} bps per deal")
L.append(f"Correlation(allocation prob, day-1 return): {d1.p_alloc.corr(headline):+.2f}  <- hot deals allocate least")

report = "\n".join(L)
(OUT_DIR / "phase2_report.txt").write_text(report)
print(report)
