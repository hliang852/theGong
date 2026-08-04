"""
HKEX's own "Equities Quote" widget (the page behind
https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=XXXX)
calls a JSON API (www1.hkex.com.hk/hkexwidget/data/getequityquote) that is
gated by a token embedded as static HTML in the page (not a bot-detection
challenge -- confirmed accessible via a plain rendered page load, unlike the
HKEXnews document-search tool). Requires JS execution to grab the token, so
this uses Playwright, but is a single lightweight page load per stock/lang
(no autocomplete/search-widget interaction needed).

Gives us, per stock code: ISIN, HSICS industry classification, issued shares
(excl. treasury), listing category (Primary/Secondary), place of
incorporation, and current price/market cap -- all directly from HKEX,
without going through the blocked prospectus/allotment PDF search.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache" / "hkex_widget"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

QUOTE_URL_TMPL = "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym={sym}&sc_lang={lang}"


def _parse_jsonp(body: str):
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", body.strip(), re.S)
    if not m:
        return None
    return json.loads(m.group(1))


def fetch_quote(page, stock_code: str, lang: str = "en"):
    """lang: 'en' or 'zh-hk'. Returns the 'quote' dict or None. Requires an
    already-open Playwright page (caller manages browser lifecycle so we
    don't spin up a new browser per stock code across 331 companies)."""
    sym = stock_code.lstrip("0") or "0"
    cache_path = CACHE_DIR / f"{sym}_{lang}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    captured = {}

    def on_resp(res):
        if "getequityquote" in res.url:
            try:
                captured["body"] = res.text()
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        page.goto(QUOTE_URL_TMPL.format(sym=sym, lang=lang), wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
    finally:
        page.remove_listener("response", on_resp)

    body = captured.get("body")
    if not body:
        return None
    data = _parse_jsonp(body)
    if not data:
        return None
    quote = data.get("data", {}).get("quote")
    if quote:
        cache_path.write_text(json.dumps(quote))
    return quote
