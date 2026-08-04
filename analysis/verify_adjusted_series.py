"""
Verifies suspected Yahoo split-adjusted price series against HKEX's own raw
prices and produces output/analysis/price_adjustment_factors.csv with a
per-company factor F such that:

    true price on original (listing-day) share basis = yahoo price x F

vs-offer returns then repair as (1 + r_yahoo) x F - 1 for every horizon.
(A post-listing subdivision multiplies share count by F, so the position's
value is F x new price -- the same formula fixes both pre- and post-action
exit dates uniformly.)

Reference sources, in order:
  1. HKEX chart "Export to Excel" via Playwright (listings within the export
     window, roughly mid-2024 onward) -- daily closes, raw exchange basis.
  2. HKEX daily quotation sheet for the listing date
     (https://www.hkex.com.hk/eng/stat/smstat/dayquot/dYYMMDDe.htm) for
     older listings.

Candidates: sub-cent-decimal series (impossible under any HK tick regime)
plus round-factor day-1 open/offer ratios at plunge factors (0.1-0.5) or
extreme pop factors (>=4) where a split could masquerade as a return.
"""
import sys, re
sys.path.insert(0, ".")
import numpy as np, pandas as pd
import requests
from datetime import date, timedelta
from pathlib import Path
from scraper import price_data, hkex_price_history

OUT = Path("output/analysis/price_adjustment_factors.csv")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
REPORT_DATE = date(2026, 6, 30)

CANDIDATES = ["02402", "02459", "02473", "02477", "02490", "02497", "02881", "00917",
              "06086", "02591", "03881", "02691", "02650", "09980", "02768", "03296",
              "01879", "06810", "01392", "02672"]


def factor_from_export(page, code, ipo_d, yahoo):
    hk = hkex_price_history.fetch_5y_history(page, code)
    if hk is None or hk.empty:
        return None, None
    m = hk.merge(yahoo[["date", "close"]], on="date", suffixes=("_hkex", "_yahoo")).dropna()
    m = m[m["close_yahoo"] > 0]
    if len(m) < 5:
        return None, None
    m["ratio"] = m["close_hkex"] / m["close_yahoo"]
    # factor at listing time = ratio on the earliest overlapping dates
    early = m.nsmallest(5, "date")["ratio"].median()
    return early, f"hkex_export({len(m)}d overlap, first {m['date'].min().date()})"


def close_from_dayquot(code, d):
    """Closing price for `code` from HKEX's daily quotation sheet for date d."""
    url = f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{d.strftime('%y%m%d')}e.htm"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            return None
        # sheet rows look like: " 2402 SINOHYTEC-H        57.10 ..." -- code,
        # name, then CLOSING PRICE column; formats vary slightly by era, so
        # capture the first decimal number after the name field
        pat = re.compile(rf"^\s*0?{int(code)}\s+\S.{{0,30}}?\s+([\d,]+\.\d+)", re.M)
        m = pat.search(r.text)
        return float(m.group(1).replace(",", "")) if m else None
    except Exception:
        return None


def main():
    df = pd.read_csv("output/analysis/ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])
    rows = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for code in CANDIDATES:
            row = df[df.stock_code == code].iloc[0]
            ipo_d = row["ipo_date"].date()
            yahoo = price_data.fetch_ohlcv(price_data.stock_ticker(code), ipo_d - timedelta(days=200), REPORT_DATE)
            if yahoo is None or yahoo.empty:
                rows.append({"stock_code": code, "factor": None, "source": "no_yahoo"})
                continue
            yahoo = yahoo.sort_values("date")
            factor, src = factor_from_export(page, code, ipo_d, yahoo)
            if factor is None:
                # fall back: day-1 close from the daily quotation sheet
                raw_close = close_from_dayquot(code, ipo_d)
                y1 = yahoo[yahoo["date"] >= pd.Timestamp(ipo_d)].head(1)
                if raw_close and not y1.empty:
                    factor = raw_close / float(y1.iloc[0]["close"])
                    src = f"dayquot({ipo_d}, raw_close={raw_close})"
            rows.append({"stock_code": code, "factor": round(factor, 4) if factor else None, "source": src})
            print(rows[-1], flush=True)
        browser.close()

    out = pd.DataFrame(rows)
    # snap near-1 factors to exactly 1 (no adjustment); keep others
    out["factor"] = out["factor"].apply(lambda f: 1.0 if f is not None and abs(f - 1) < 0.03 else f)
    out.to_csv(OUT, index=False)
    print(f"\nWrote {OUT}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
