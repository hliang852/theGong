"""
A1 filing date proxy: HKEXnews publishes a consolidated index of every Main
Board listing application (active/inactive/listed/returned/withdrawn/
rejected/lapsed) going back to the mid-1990s, as a downloadable Excel file:
https://www1.hkexnews.hk/app/documents/sehkconsolidatedindex.xlsx

Column "Date of First Posting" is the date the Application Proof was first
published -- the standard public proxy for "A1 filing date" (the A1 form
itself is filed confidentially; first posting is what becomes public, and
happens shortly after). Matched to our IPO population by company name
(normalized), status == 'Listed'. Companies with multiple attempts (e.g. an
earlier Lapsed application followed by a renewal that listed) are matched to
the 'Listed' status row specifically.
"""
from __future__ import annotations
import re
import requests
import pandas as pd
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
INDEX_URL = "https://www1.hkexnews.hk/app/documents/sehkconsolidatedindex.xlsx"


def _normalize(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"-\s*(h\s*shares?|[a-z](\s*,\s*[a-z])*)\s*$", "", name)  # strip rule/class suffixes
    name = re.sub(r"[^\w\s]", "", name)  # strip punctuation
    name = re.sub(r"\s+", " ", name).strip()
    return name


def load_index() -> pd.DataFrame:
    cache_path = CACHE_DIR / "sehkconsolidatedindex.xlsx"
    if not cache_path.exists():
        resp = requests.get(INDEX_URL, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)
    df = pd.read_excel(cache_path, header=0)
    df.columns = ["date_first_posting", "applicant", "status"]
    df = df.dropna(subset=["applicant"])
    df["norm_name"] = df["applicant"].apply(_normalize)
    return df


def find_a1_date(company_name_en: str, index_df: pd.DataFrame) -> dict:
    """Returns {'date': 'DD/MM/YYYY' or None, 'match_status': str, 'matched_name': str or None}"""
    target = _normalize(company_name_en)
    matches = index_df[index_df["norm_name"] == target]
    listed = matches[matches["status"] == "Listed"]
    if len(listed) >= 1:
        row = listed.iloc[0]
        return {"date": row["date_first_posting"], "match_status": "matched_listed", "matched_name": row["applicant"]}
    if len(matches) >= 1:
        # no 'Listed' row found under this exact name (e.g. name changed between
        # application and listing) -- flag for manual check rather than guess
        return {"date": None, "match_status": f"matched_but_no_listed_status ({matches.iloc[0]['status']})", "matched_name": matches.iloc[0]["applicant"]}
    return {"date": None, "match_status": "no_match", "matched_name": None}
