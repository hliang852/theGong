"""
Southbound (Hong Kong Stock Connect, Shanghai leg) eligible-securities list,
via SSE's live query API -- plain requests, no auth, no browser needed:
https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L

Gives CURRENT (scrape-date) membership only -- there is no "date added" field
in this feed, so southbound_inclusion_date is NOT resolved by this source
(would need to mine SSE/SZSE's periodic quarterly-review bulletin PDFs to
reconstruct historical addition dates, which is a separate, larger effort).

Note: this is the Shanghai-Connect southbound list only. A Shenzhen-Connect
southbound list also exists (equivalent SZSE endpoint, not yet located) and
in principle a stock eligible only via the Shenzhen leg would be missed here
-- flagged as a residual gap, likely small in practice since eligibility
criteria mostly overlap between the two.
"""
from __future__ import annotations
import re
import json
import requests
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
URL = "https://query.sse.com.cn/commonQuery.do"


def load_current_list() -> set:
    cache_path = CACHE_DIR / "southbound_sse_list.json"
    if cache_path.exists():
        return set(json.loads(cache_path.read_text()))
    r = requests.get(URL, params={
        "jsonCallBack": "jsonpCallback1", "sqlId": "COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L",
        "isPagination": "true", "pageHelp.pageSize": "1000", "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1", "pageHelp.endPage": "1", "keyword": "",
    }, headers={"User-Agent": UA, "Referer": "https://www.sse.com.cn/"}, timeout=20)
    m = re.search(r"jsonpCallback1\((.*)\)$", r.text.strip())
    if not m:
        return set()
    data = json.loads(m.group(1))
    codes = {row["SECURITY_CODE"] for row in data.get("pageHelp", {}).get("data", [])}
    cache_path.write_text(json.dumps(sorted(codes)))
    return codes


def is_southbound_eligible(stock_code: str, current_list: set) -> bool:
    return stock_code.zfill(5) in current_list
