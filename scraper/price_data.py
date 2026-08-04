"""
Free daily OHLCV price data via Yahoo Finance's public chart JSON endpoint,
plus HSI index levels and 1-month HIBOR from HKMA's open API.

No auth required for either; Yahoo needs a browser User-Agent or it 403s.
"""
from __future__ import annotations
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache" / "prices"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def fetch_ohlcv(ticker: str, start: date, end: date, retries=3) -> pd.DataFrame | None:
    """ticker e.g. '0700.HK' or '%5EHSI' for HSI. Returns None on failure (flag for audit)."""
    cache_key = f"{ticker.replace('%5E','HSI').replace('.HK','')}_{start}_{end}.csv"
    cache_path = CACHE_DIR / cache_key
    if cache_path.exists():
        try:
            return pd.read_csv(cache_path, parse_dates=["date"])
        except Exception:
            pass

    period1 = int(pd.Timestamp(start).timestamp())
    period2 = int(pd.Timestamp(end + timedelta(days=1)).timestamp())
    url = YF_CHART_URL.format(ticker=ticker)
    params = {"period1": period1, "period2": period2, "interval": "1d"}

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=20)
            if resp.status_code != 200:
                time.sleep(1.5)
                continue
            data = resp.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            r = result[0]
            ts = r.get("timestamp")
            if not ts:
                return None
            quote = r["indicators"]["quote"][0]
            adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
            df = pd.DataFrame({
                "date": pd.to_datetime(ts, unit="s").normalize(),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
                "adjclose": adj if adj else quote.get("close"),
            })
            df = df.dropna(subset=["close"]).reset_index(drop=True)
            df.to_csv(cache_path, index=False)
            time.sleep(0.4)  # be polite / avoid rate limiting
            return df
        except Exception:
            time.sleep(1.5)
            continue
    return None


def stock_ticker(stock_code: str) -> str:
    code = stock_code.lstrip("0") or "0"
    return f"{code.zfill(4)}.HK"


_yahoo_session = None
_yahoo_crumb = None


def _get_yahoo_session():
    global _yahoo_session, _yahoo_crumb
    if _yahoo_session is not None:
        return _yahoo_session, _yahoo_crumb
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    try:
        s.get("https://fc.yahoo.com", timeout=15)
        crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).text.strip()
    except Exception:
        crumb = None
    _yahoo_session, _yahoo_crumb = s, crumb
    return s, crumb


def fetch_shares_and_marketcap(ticker: str, retries=3):
    """Current sharesOutstanding, floatShares, and marketCap via Yahoo's
    quoteSummary endpoint (a different API from the chart endpoint used for
    OHLCV; requires a session cookie + crumb). These are CURRENT/live values
    as of scrape time, not historical-as-of-IPO values -- used as the best
    available public proxy for 'current free float' and 'latest market cap'
    fields, and as an approximation for market cap at listing when the
    prospectus-derived exact post-IPO share count isn't available."""
    cache_path = CACHE_DIR / f"{ticker.replace('.', '_')}_keystats.csv"
    if cache_path.exists():
        row = pd.read_csv(cache_path).iloc[0]
        return {"shares_outstanding": row.get("shares_outstanding"), "float_shares": row.get("float_shares"), "market_cap": row.get("market_cap")}

    s, crumb = _get_yahoo_session()
    if not crumb:
        return None
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    params = {"modules": "defaultKeyStatistics,price", "crumb": crumb}
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=15)
            if r.status_code != 200:
                time.sleep(1.5)
                continue
            d = r.json()
            res = d.get("quoteSummary", {}).get("result")
            if not res:
                return None
            ks = res[0].get("defaultKeyStatistics", {})
            price = res[0].get("price", {})
            out = {
                "shares_outstanding": (ks.get("sharesOutstanding") or {}).get("raw"),
                "float_shares": (ks.get("floatShares") or {}).get("raw"),
                "market_cap": (price.get("marketCap") or {}).get("raw"),
            }
            pd.DataFrame([out]).to_csv(cache_path, index=False)
            time.sleep(0.4)
            return out
        except Exception:
            time.sleep(1.5)
    return None


HSI_TICKER = "%5EHSI"


def hibor_1m_on_date(target_date: date, retries=3) -> float | None:
    """1-month HIBOR fixing on/nearest-before target_date, via HKMA open API."""
    cache_path = CACHE_DIR.parent / "hibor_1m_series.csv"
    if not cache_path.exists():
        records = []
        offset = 0
        url = "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily"
        while True:
            for attempt in range(retries):
                try:
                    resp = requests.get(url, params={"segment": "hibor.fixing", "offset": offset}, timeout=20)
                    if resp.status_code == 200:
                        break
                    time.sleep(1.5)
                except Exception:
                    time.sleep(1.5)
            else:
                break
            payload = resp.json()
            recs = payload.get("result", {}).get("records", [])
            if not recs:
                break
            records.extend(recs)
            if len(recs) < 100:
                break
            offset += 100
        if not records:
            return None
        df = pd.DataFrame(records)
        df["end_of_day"] = pd.to_datetime(df["end_of_day"])
        df = df[["end_of_day", "ir_1m"]].dropna().sort_values("end_of_day")
        df.to_csv(cache_path, index=False)
    else:
        df = pd.read_csv(cache_path, parse_dates=["end_of_day"])

    target_ts = pd.Timestamp(target_date)
    prior = df[df["end_of_day"] <= target_ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1]["ir_1m"])
