"""
Parses HKEX's official "New Listing Report" (NLR) yearly Excel files for the
Main Board. This is the authoritative backbone list of new listings — each
row pair (a)=Hong Kong Offer tranche, (b)=International Offer tranche gives
stock code, company name (with rule-suffix flags), date of prospectus, date
of listing, sponsor(s), and funds raised per tranche.

Source: https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board
Yearly files: .../New-Listing-Report/Main/NLR{YEAR}_Eng.xlsx
"""
from __future__ import annotations
import re
import requests
import pandas as pd
from pathlib import Path
from datetime import date

CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NLR_BASE = "https://www2.hkexnews.hk/-/media/HKEXnews/Homepage/New-Listings/New-Listing-Information/New-Listing-Report/Main"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

SUFFIX_MEANINGS = {
    "B": "chapter_18a",       # Biotech company listed under Chapter 18A
    "P": "chapter_18c",       # Pre-commercial company listed under Chapter 18C
    "S": "secondary_listing", # Secondary listing in Hong Kong
    "W": "wvr",                # Weighted voting rights structure
}


def _download_year(year: int) -> Path:
    fname = f"NLR{year}_Eng.xlsx"
    dest = CACHE_DIR / fname
    if dest.exists():
        return dest
    url = f"{NLR_BASE}/{fname}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _extract_suffix_flags(raw_name: str):
    """Company names carry one or more trailing ' - X' suffix codes, e.g.
    'Guangdong True Health Medical Technology Development Co., Ltd.- B' or
    compound suffixes like 'MiniMax Group Inc. - W - P' (WVR + Chapter 18C).
    Strip trailing suffix groups repeatedly since multiple can stack.

    Separately, H-share issuers carry a literal '- H Shares' / '- H share'
    text suffix (not part of the B/P/S/W legend-coded system) -- this is
    HKEX's own convention for PRC-incorporated issuers whose H-share class is
    listed in Hong Kong, approved by CSRC. Detected and stripped the same way."""
    flags = {"chapter_18a": False, "chapter_18c": False, "secondary_listing": False, "wvr": False, "is_h_share": False}
    name = raw_name.strip().replace("\n", " ").strip()

    h_share_match = re.search(r"-\s*H\s*[Ss]hares?\s*$", name)
    if h_share_match:
        flags["is_h_share"] = True
        name = name[: h_share_match.start()].strip()

    while True:
        m = re.search(r"-\s*([A-Z](?:,\s*[A-Z])*)\s*$", name)
        if not m:
            break
        codes = [c.strip() for c in m.group(1).split(",")]
        if not all(c in SUFFIX_MEANINGS for c in codes):
            break
        for c in codes:
            flags[SUFFIX_MEANINGS[c]] = True
        name = name[: m.start()].strip().rstrip("-").strip()
    return name, flags


def parse_year(year: int) -> list[dict]:
    path = _download_year(year)
    xl = pd.ExcelFile(path)
    df = xl.parse(xl.sheet_names[0], header=None)

    records = []
    i = 0
    n = len(df)
    while i < n:
        row = df.iloc[i]
        seq = row[0]
        if pd.notna(seq) and str(seq).strip().replace(".0", "").isdigit():
            stock_code = str(row[1]).strip()
            raw_name = str(row[2])
            date_prospectus = row[3]
            date_listing = row[4]
            sponsors = str(row[5]) if pd.notna(row[5]) else None

            raw_funds_a = row[8]
            raw_price_a = row[9]
            exclusion_reason = None
            for raw in (raw_funds_a, raw_price_a):
                if isinstance(raw, str) and "N/A" in raw:
                    text = raw.replace("\n", " ")
                    if "By Introduction" in text:
                        exclusion_reason = "listing_by_introduction"
                    elif "De-SPAC" in text:
                        exclusion_reason = "despac_transaction"
                    elif "Transfer of Listing" in text:
                        exclusion_reason = "gem_to_main_transfer"
                    else:
                        exclusion_reason = "other_na_remark"

            funds_a = pd.to_numeric(raw_funds_a, errors="coerce")
            funds_a = None if pd.isna(funds_a) else float(funds_a)
            price_a = pd.to_numeric(raw_price_a, errors="coerce")
            price_a = None if pd.isna(price_a) else float(price_a)

            funds_b = None
            price_b = None
            if i + 1 < n and pd.isna(df.iloc[i + 1][0]) and str(df.iloc[i + 1][2]).strip() == '"':
                fb = pd.to_numeric(df.iloc[i + 1][8], errors="coerce")
                funds_b = None if pd.isna(fb) else float(fb)
                pb = pd.to_numeric(df.iloc[i + 1][9], errors="coerce")
                price_b = None if pd.isna(pb) else float(pb)
                i += 1

            name, flags = _extract_suffix_flags(raw_name)
            total_funds_raised_hkd = (funds_a or 0) + (funds_b or 0) if (funds_a or funds_b) else None
            ipo_price = price_a if price_a is not None else price_b

            records.append({
                "stock_code": stock_code.zfill(5) if stock_code.isdigit() else stock_code,
                "company_name_en": name,
                "date_prospectus": pd.to_datetime(date_prospectus, errors="coerce"),
                "ipo_date": pd.to_datetime(date_listing, errors="coerce"),
                "sponsors": sponsors.replace("\n", " ").strip() if sponsors else None,
                "funds_raised_hk_offer_hkd": funds_a,
                "funds_raised_intl_offer_hkd": funds_b,
                "total_ipo_size_hkd": total_funds_raised_hkd,
                "ipo_price_hkd": ipo_price,
                "is_chapter_18a": flags["chapter_18a"],
                "is_chapter_18c": flags["chapter_18c"],
                "secondary_listing": flags["secondary_listing"],
                "is_wvr": flags["wvr"],
                "is_h_share": flags["is_h_share"],
                "nlr_year": year,
                "exclusion_reason": exclusion_reason,
            })
        i += 1
    return records


def load_all(start=2023, end=2026) -> pd.DataFrame:
    all_records = []
    for y in range(start, end + 1):
        all_records.extend(parse_year(y))
    df = pd.DataFrame(all_records)
    return df


def apply_scope_filters(df: pd.DataFrame, start_date=date(2023, 1, 1), end_date=date(2026, 6, 30)):
    """
    Scope: Main Board IPOs, ipo_date in [start_date, end_date].

    HKEX's own NLR report explicitly tags rows that are not a genuine IPO
    (in the "Funds Raised" / "IPO Subscription Price" columns) with one of:
      - "N/A - By Introduction"
      - "N/A - By De-SPAC Transaction"
      - "N/A - Transfer of Listing from GEM to Main Board"
    These are used directly (exclusion_reason field) rather than a heuristic,
    since HKEX's own labelling is authoritative and catches every case
    (confirmed: no unlabelled zero-funds-raised rows exist in 2023-2026 data).
    """
    df = df.copy()
    df["ipo_date_only"] = df["ipo_date"].dt.date
    in_range = (df["ipo_date_only"] >= start_date) & (df["ipo_date_only"] <= end_date)
    df = df[in_range]

    excluded = df["exclusion_reason"].notna()

    audit = {}
    for reason in ["listing_by_introduction", "despac_transaction", "gem_to_main_transfer", "other_na_remark"]:
        audit[f"excluded_{reason}"] = df[df["exclusion_reason"] == reason][
            ["stock_code", "company_name_en", "ipo_date_only"]
        ].to_dict("records")

    kept = df[~excluded].reset_index(drop=True)
    return kept, audit


if __name__ == "__main__":
    df = load_all()
    kept, audit = apply_scope_filters(df)
    print(f"Total NLR rows 2023-2026: {len(df)}")
    print(f"Kept after scope filters: {len(kept)}")
    for k, v in audit.items():
        print(f"{k}: {len(v)}")
        for r in v:
            print("  ", r)
