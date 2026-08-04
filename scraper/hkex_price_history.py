"""
Direct historical daily close price + volume from HKEX's own Equities Quote
page, via its "Export to Excel" chart download (Time / Closed Price / Volume).

Caveat (from the export itself): "Only data from the last two years is
available for export." So for IPOs older than ~2 years before scrape date,
this does NOT reach back to the IPO date -- only useful for latest-price
lookups on those, not Day-1 data. For IPOs within the last 2 years it covers
the full history including Day-1.

No Open/High/Low columns are provided by this export -- only Close and
Volume. Day-1 high/low still needs Yahoo Finance (or the AAStocks/
Investing.com fallback, not yet built -- see PILOT_REPORT.md).
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path
from datetime import date

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache" / "hkex_price_export"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

QUOTE_URL_TMPL = "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym={sym}&sc_lang=en"


def fetch_5y_history(page, stock_code: str) -> pd.DataFrame | None:
    """Requires an already-open Playwright page. Returns DataFrame with
    columns [date, close, volume] or None on failure."""
    sym = stock_code.lstrip("0") or "0"
    cache_path = CACHE_DIR / f"{sym}.csv"
    if cache_path.exists():
        try:
            return pd.read_csv(cache_path, parse_dates=["date"])
        except Exception:
            pass

    try:
        page.goto(QUOTE_URL_TMPL.format(sym=sym), wait_until="load", timeout=30000)
        page.wait_for_timeout(1500)
        try:
            page.click("button:has-text('Accept')", timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        page.click("text=5 Y", timeout=5000)
        page.wait_for_timeout(1500)
        with page.expect_download(timeout=15000) as dl_info:
            page.click("text=Export to Excel", timeout=5000)
        download = dl_info.value
        tmp_path = CACHE_DIR / f"{sym}_raw.xlsx"
        download.save_as(str(tmp_path))
        df = pd.read_excel(tmp_path, header=0)
        tmp_path.unlink(missing_ok=True)
    except Exception:
        return None

    df.columns = ["date", "close", "volume"]
    df = df[pd.to_datetime(df["date"], errors="coerce").notna()].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    df.to_csv(cache_path, index=False)
    return df


def price_on_or_before(df: pd.DataFrame, target: date):
    if df is None or df.empty:
        return None
    sub = df[df["date"] <= pd.Timestamp(target)]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["close"])
