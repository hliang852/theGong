"""Source adapter: Southbound (Stock Connect) eligibility changes.

There is no official "eligibility change" feed with dates. But the *current* eligible
list is available as a clean query API, so we detect changes the robust way: snapshot
the eligible set each run, diff against the previously-committed snapshot, and emit an
item whenever a security is **added to** or **removed from** Southbound trading.

  source:  SSE query API (Shanghai-Connect Southbound eligible securities)
           https://query.sse.com.cn/commonQuery.do  (sqlId COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L)
  state:   site/data/southbound_sse.json  (committed, so the diff survives across CI runs)

First run establishes the baseline and emits nothing (avoids a spurious 600+ item dump).
Note: Shanghai leg only for now; the Shenzhen-Connect (SZSE) list is an easy addition
once its equivalent endpoint is wired.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
from ..base import Source, RawItem, register

SSE_URL = "https://query.sse.com.cn/commonQuery.do"
INFO_URL = "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Eligible-Stocks-and-ETFs?sc_lang=en"
UA = "Mozilla/5.0 (compatible; TheGONG-latest/1.0; research aggregator)"


def _state_path() -> str:
    data_dir = os.path.dirname(os.environ.get("LATEST_OUT", "site/data/latest.json"))
    return os.path.join(data_dir, "southbound_sse.json")


def _fetch_current() -> tuple[dict[str, str], str]:
    """Returns ({code: english_name}, list_update_date_iso)."""
    import requests
    r = requests.get(SSE_URL, params={
        "jsonCallBack": "cb", "sqlId": "COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L",
        "isPagination": "true", "pageHelp.pageSize": "2000", "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1", "pageHelp.endPage": "1", "keyword": "",
    }, headers={"User-Agent": UA, "Referer": "https://www.sse.com.cn/"}, timeout=25)
    m = re.search(r"cb\((.*)\)\s*$", r.text.strip())
    data = json.loads(m.group(1))
    rows = data.get("pageHelp", {}).get("data", [])
    current = {str(row["SECURITY_CODE"]): (row.get("ABBR_EN") or "").strip().title() for row in rows}
    updated = rows[0].get("UPDATE_DATE") if rows else None
    return current, (updated or dt.date.today().isoformat())


class SouthboundSSE(Source):
    name = "SSE / HKEX"
    enabled = True

    def fetch(self) -> list[RawItem]:
        current, eff_date = _fetch_current()
        if not current:
            return []
        path = _state_path()
        prev = {}
        if os.path.exists(path):
            try:
                prev = json.load(open(path))
            except Exception:
                prev = {}
        # persist the new snapshot for next time
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(current, open(path, "w"), ensure_ascii=False, sort_keys=True)

        if not prev:                      # first run: baseline only
            return []

        out: list[RawItem] = []
        for code in sorted(set(current) - set(prev)):
            name = current[code] or code
            out.append(RawItem(
                source="SSE / HKEX", source_id=f"sbadd:{code}:{eff_date}", date=eff_date,
                title=f"{name} ({code}) added to Southbound trading (Shanghai Connect)",
                entity=name, stock_code=code if re.fullmatch(r"\d{4,5}", code) else None,
                url=INFO_URL, type_hint="rule",
                raw_text=f"{name} became eligible for Southbound Stock Connect trading (Shanghai leg).",
            ))
        for code in sorted(set(prev) - set(current)):
            name = prev[code] or code
            out.append(RawItem(
                source="SSE / HKEX", source_id=f"sbdrop:{code}:{eff_date}", date=eff_date,
                title=f"{name} ({code}) removed from Southbound trading (Shanghai Connect)",
                entity=name, stock_code=code if re.fullmatch(r"\d{4,5}", code) else None,
                url=INFO_URL, type_hint="rule",
                raw_text=f"{name} was removed from Southbound Stock Connect eligibility (Shanghai leg).",
            ))
        return out


register(SouthboundSSE())
