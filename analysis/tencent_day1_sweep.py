"""
Sweeps ALL companies against Tencent's unadjusted (bfq) HK daily bars to:
  1. compute per-company adjustment factor = tencent_day1_close / yahoo_day1_close
     (Yahoo back-adjusts its whole series after splits/bonuses -- factor != 1
     means every vs-offer return for that company needs (1+r) x F - 1 repair)
  2. record TRUE day-1 OHLC + volume from the unadjusted source, which also
     fills companies where Yahoo has no history at all (e.g. 00100 MiniMax)

Writes output/analysis/tencent_day1.csv. Idempotent: skips codes already in
the output file, so an interrupted run resumes.
"""
import sys, time, json
sys.path.insert(0, ".")
import numpy as np, pandas as pd
import requests
from datetime import date, timedelta
from pathlib import Path
from scraper import price_data

OUT = Path("output/analysis/tencent_day1.csv")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
REPORT_DATE = date(2026, 6, 30)


def tencent_bars(code, start, end, retries=3):
    sym = f"hk{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{start},{end},50,bfq"
    for _ in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=15)
            if r.status_code != 200:
                time.sleep(1); continue
            data = r.json().get("data", {}).get(sym, {})
            bars = data.get("bfqday") or data.get("day") or []
            return [(b[0], float(b[1]), float(b[2]), float(b[3]), float(b[4]),
                     float(b[5]) if len(b) > 5 else np.nan) for b in bars]
        except Exception:
            time.sleep(1)
    return None


def main():
    df = pd.read_csv("output/analysis/ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
    done = set()
    if OUT.exists():
        done = set(pd.read_csv(OUT, dtype={"stock_code": str})["stock_code"].str.zfill(5))
        print(f"resuming: {len(done)} already done")
    header_needed = not OUT.exists()
    with open(OUT, "a") as f:
        if header_needed:
            f.write("stock_code,t_day1_date,t_open,t_close,t_high,t_low,t_volume,yahoo_day1_close,factor\n")
        for i, (_, row) in enumerate(df.iterrows(), 1):
            code = row["stock_code"]
            if code in done:
                continue
            ipo_d = row["ipo_date"].date()
            bars = tencent_bars(code, ipo_d.isoformat(), (ipo_d + timedelta(days=14)).isoformat())
            rec = [code, "", "", "", "", "", "", "", ""]
            if bars:
                b0 = next((b for b in bars if b[0] >= ipo_d.isoformat()), None)
                if b0:
                    d0, o, c, h, l, v = b0
                    rec[1:7] = [d0, o, c, h, l, v]
                    # yahoo comparison
                    ypx = price_data.fetch_ohlcv(price_data.stock_ticker(code), ipo_d - timedelta(days=200), REPORT_DATE)
                    if ypx is not None and not ypx.empty:
                        y1 = ypx[ypx["date"] >= pd.Timestamp(d0)].head(1)
                        if not y1.empty and float(y1.iloc[0]["close"]) > 0:
                            yc = float(y1.iloc[0]["close"])
                            rec[7] = yc
                            rec[8] = round(c / yc, 4)
            f.write(",".join(str(x) for x in rec) + "\n")
            f.flush()
            if i % 25 == 0:
                print(f"{i}/331", flush=True)
            time.sleep(0.25)
    out = pd.read_csv(OUT, dtype={"stock_code": str})
    fac = pd.to_numeric(out["factor"], errors="coerce")
    print(f"\nDone. day1 bars: {out['t_close'].notna().sum()}/331; factor computed: {fac.notna().sum()}")
    flagged = out[(fac - 1).abs() > 0.03]
    print(f"companies needing repair (|factor-1|>3%): {len(flagged)}")
    print(flagged[["stock_code", "factor"]].to_string(index=False))


if __name__ == "__main__":
    main()
