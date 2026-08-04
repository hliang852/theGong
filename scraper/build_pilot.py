from __future__ import annotations
import sys
import re
import math
import csv
import json
import traceback
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import pandas as pd
from scraper import parse_nlr, price_data, hkexnews_docs, pdf_extract, hkex_widget, a1_filing_dates, southbound, hkex_price_history, local_docs, excel_export
from scraper.fields import COLUMN_NAMES, COLUMN_TIER
from reference.broker_nationality import classify_broker
from reference.cornerstone_pedigree import classify_cornerstones

USD_HKD = 7.8
REPORT_DATE = date(2026, 6, 30)
FINI_CUTOVER = date(2023, 11, 22)  # HKEX FINI platform went live this date

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
errors_log = []


def log_error(stock_code, field, msg):
    errors_log.append({"stock_code": stock_code, "field": field, "error": msg})


def pick_pilot_set(kept: pd.DataFrame) -> pd.DataFrame:
    kept = kept.sort_values("ipo_date").reset_index(drop=True)
    picks = []

    def add(mask, n=1):
        cand = kept[mask & ~kept["stock_code"].isin([p["stock_code"] for p in picks])]
        for _, row in cand.head(n).iterrows():
            picks.append(row.to_dict())

    add(kept["is_chapter_18a"], 2)   # biotech, different years
    add(kept["is_chapter_18c"], 2)   # specialist tech
    add(kept["secondary_listing"], 2)  # 19C secondary
    add(kept["is_wvr"], 1)
    add((~kept["is_chapter_18a"]) & (~kept["is_chapter_18c"]) & (~kept["secondary_listing"]) & (~kept["is_wvr"]) & (kept["ipo_date"].dt.year == 2023), 1)
    add((~kept["is_chapter_18a"]) & (~kept["is_chapter_18c"]) & (~kept["secondary_listing"]) & (~kept["is_wvr"]) & (kept["ipo_date"].dt.year == 2025), 1)
    add((~kept["is_chapter_18a"]) & (~kept["is_chapter_18c"]) & (~kept["secondary_listing"]) & (~kept["is_wvr"]) & (kept["ipo_date"].dt.year == 2026), 1)

    return pd.DataFrame(picks)


def nearest_on_or_before(df: pd.DataFrame, target: pd.Timestamp, col="close"):
    sub = df[df["date"] <= target]
    if sub.empty:
        return None, None
    row = sub.iloc[-1]
    return float(row[col]), row["date"]


def nearest_on_or_after(df: pd.DataFrame, target: pd.Timestamp, col="close"):
    sub = df[df["date"] >= target]
    if sub.empty:
        return None, None
    row = sub.iloc[0]
    return float(row[col]), row["date"]


def build_row(ipo: dict, prior_day1_perfs: list, widget_page=None, a1_index=None, southbound_list=None) -> dict:
    code = ipo["stock_code"]
    ipo_date = ipo["ipo_date"].date()
    ticker = price_data.stock_ticker(code)

    row = {c: None for c in COLUMN_NAMES}
    share_count_source = {"value": None}  # tracks provenance of market_cap_at_listing_hkd / post_ipo_total_issued_shares

    if a1_index is not None:
        a1 = a1_filing_dates.find_a1_date(ipo["company_name_en"], a1_index)
        if a1["date"]:
            row["a1_filing_date"] = a1["date"]
        else:
            log_error(code, "a1_filing_date", f"{a1['match_status']} (matched_name={a1['matched_name']!r})")

    row["ipo_date"] = ipo_date.strftime("%d/%m/%Y")
    row["stock_code"] = code
    row["company_name_en"] = ipo["company_name_en"]
    row["is_chapter_18a"] = ipo["is_chapter_18a"]
    row["is_chapter_18c"] = ipo["is_chapter_18c"]
    row["is_chapter_19c"] = ipo["secondary_listing"]  # 19C governs secondary listings
    row["secondary_listing"] = ipo["secondary_listing"]
    row["primary_listing"] = not ipo["secondary_listing"]
    row["is_h_share"] = ipo["is_h_share"]
    row["fini_platform_flag"] = "T+1" if ipo_date >= FINI_CUTOVER else "T+5"
    if southbound_list is not None:
        row["southbound_included"] = southbound.is_southbound_eligible(code, southbound_list)
    row["ipo_price_hkd"] = ipo["ipo_price_hkd"]
    row["total_ipo_size_hkd"] = ipo["total_ipo_size_hkd"]
    row["total_ipo_size_usd"] = round(ipo["total_ipo_size_hkd"] / USD_HKD, 2) if ipo["total_ipo_size_hkd"] else None
    row["lead_brokers_underwriters"] = ipo["sponsors"]

    # total_ipo_size_shares / total_shares_issued_at_ipo / post_ipo_total_issued_shares
    # / market_cap_at_listing_hkd are populated later in this function from the
    # scraped prospectus/allotment-results documents (Tier 2), per user
    # instruction to source share counts directly rather than calculate them.
    # (total_ipo_size_hkd / ipo_price_hkd) is deliberately NOT used as a stand-in:
    # it approximates offer shares but the scraped "Number of Offer Shares"
    # figure below is the authoritative one.

    if ipo["sponsors"]:
        cls = classify_broker(ipo["sponsors"])
        row["lead_broker_is_global_bank"] = cls["is_global_bank"]
        row["lead_broker_is_chinese_bank"] = cls["is_chinese_bank"]
        row["multiple_lead_brokers"] = cls["multiple"]

    row["hkex_ipo_documentation_link"] = f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en&stockId={int(code)}"

    # 6-month lockup expiry date is a pure calendar calculation (IPO date + 182
    # days) -- must NOT depend on price-history availability. Previously this
    # was incorrectly nested inside the price-series block, so it silently
    # came back NULL whenever Yahoo had no OHLCV for a ticker (e.g. MiniMax).
    lockup_date = ipo_date + timedelta(days=182)
    row["lockup_6m_expiry_date"] = lockup_date.strftime("%d/%m/%Y")

    # ---- price series ----
    # NOTE: price_end must always reach REPORT_DATE (not capped near the IPO
    # date) since latest price / 1yr performance need the full history
    # through the report date regardless of how old the IPO is.
    price_start = ipo_date - timedelta(days=200)
    price_end = REPORT_DATE
    px = price_data.fetch_ohlcv(ticker, price_start, price_end)
    hsi = price_data.fetch_ohlcv(price_data.HSI_TICKER, ipo_date - timedelta(days=140), min(REPORT_DATE, ipo_date + timedelta(days=430)))

    if px is None or px.empty:
        log_error(code, "price_series", "Yahoo Finance returned no data for this ticker")
    else:
        px = px.sort_values("date").reset_index(drop=True)
        ipo_ts = pd.Timestamp(ipo_date)
        day1 = px[px["date"] == ipo_ts]
        if day1.empty:
            day1 = px[px["date"] >= ipo_ts].head(1)
        if not day1.empty:
            d1 = day1.iloc[0]
            row["day1_open_hkd"] = float(d1["open"])
            row["day1_closing_price_hkd"] = float(d1["close"])
            row["day1_high_hkd"] = float(d1["high"])
            row["day1_low_hkd"] = float(d1["low"])
            vol_shares = d1["volume"]
            if pd.notna(vol_shares) and row["ipo_price_hkd"]:
                row["day1_traded_volume_usd"] = round(vol_shares * float(d1["close"]) / USD_HKD, 2)
            if row["ipo_price_hkd"]:
                row["day1_performance_pct"] = round((float(d1["close"]) / row["ipo_price_hkd"] - 1) * 100, 2)

            for n, perf_key, vol_key in [(3, "perf_3d_pct", "volume_3d_usd"), (5, "perf_5d_pct", "volume_5d_usd"), (20, "perf_20d_pct", "volume_20d_usd")]:
                idx = px.index[px["date"] == d1["date"]]
                if len(idx) and idx[0] + n < len(px):
                    target_row = px.iloc[idx[0] + n]
                    if row["ipo_price_hkd"]:
                        row[perf_key] = round((float(target_row["close"]) / row["ipo_price_hkd"] - 1) * 100, 2)
                    window = px.iloc[idx[0] + 1: idx[0] + n + 1]
                    if not window.empty and window["volume"].notna().any():
                        usd_vol = (window["volume"] * window["close"]).sum() / USD_HKD
                        row[vol_key] = round(float(usd_vol), 2)

        # latest close on/before report date
        last_price, last_date = nearest_on_or_before(px, pd.Timestamp(REPORT_DATE))
        row["last_price_20260630_hkd"] = last_price

        # 1yr performance
        one_yr = ipo_ts + pd.Timedelta(days=365)
        p1y, _ = nearest_on_or_after(px, one_yr)
        if p1y is None:
            p1y, _ = nearest_on_or_before(px, one_yr)
        if p1y and row["ipo_price_hkd"]:
            row["ipo_perf_1y_pct"] = round((p1y / row["ipo_price_hkd"] - 1) * 100, 2)

        # 6-month lockup window performance (needs price data; the date itself
        # is already set above regardless of price availability)
        lockup_ts = pd.Timestamp(lockup_date)
        idxs = px.index[px["date"] >= lockup_ts]
        if len(idxs):
            base_idx = idxs[0]
            offsets = {
                "perf_lockup_dayminus2_vs_ipo_pct": -2, "perf_lockup_dayminus1_vs_ipo_pct": -1,
                "perf_lockup_day0_vs_ipo_pct": 0,
                "perf_lockup_dayplus1_vs_ipo_pct": 1, "perf_lockup_dayplus2_vs_ipo_pct": 2,
            }
            for key, off in offsets.items():
                j = base_idx + off
                if 0 <= j < len(px) and row["ipo_price_hkd"]:
                    row[key] = round((float(px.iloc[j]["close"]) / row["ipo_price_hkd"] - 1) * 100, 2)
            # perf_on_lockup_expiry_pct is a plain 1-day return ON the expiry
            # date itself (vs. the prior trading day's close) -- distinct
            # from perf_lockup_day0_vs_ipo_pct above, which measures
            # cumulative performance since the IPO offer price.
            if base_idx - 1 >= 0:
                prev_close = float(px.iloc[base_idx - 1]["close"])
                expiry_close = float(px.iloc[base_idx]["close"])
                if prev_close:
                    row["perf_on_lockup_expiry_pct"] = round((expiry_close / prev_close - 1) * 100, 2)
        else:
            log_error(code, "lockup_window", "6-month lockup date is after available price history (too recent)")

    # ---- current shares outstanding / float via Yahoo quoteSummary ----
    # These are CURRENT (scrape-time) values, not historical-as-of-IPO values.
    # Used for "current free float" (there is no other public source for this),
    # and as a weak fallback for market cap at listing / post-IPO shares --
    # overwritten below by the scraped HKEX prospectus/allotment figures
    # whenever those are found (this Yahoo-based number is an approximation:
    # current share count x IPO price, which can drift from the true
    # at-listing figure if the company issued/bought back shares since).
    current_shares_out = None  # captured here for latest_market_cap_hkd, computed at the end of this function
    try:
        keystats = price_data.fetch_shares_and_marketcap(ticker)
    except Exception as e:
        keystats = None
        log_error(code, "yahoo_keystats", str(e))
    if not keystats:
        log_error(code, "current_free_float", "Yahoo quoteSummary returned no data for this ticker")
    else:
        shares_out = keystats.get("shares_outstanding")
        current_shares_out = shares_out
        float_shares = keystats.get("float_shares")
        if float_shares:
            row["current_free_float_shares"] = int(float_shares)
        if float_shares and shares_out:
            row["current_free_float_pct"] = round(float_shares / shares_out * 100, 2)
        if shares_out and row["ipo_price_hkd"]:
            row["market_cap_at_listing_hkd"] = round(shares_out * row["ipo_price_hkd"], 2)
            row["post_ipo_total_issued_shares"] = int(shares_out)
            share_count_source["value"] = "yahoo_approx"

    if hsi is None or hsi.empty:
        log_error(code, "hsi_series", "Yahoo Finance returned no HSI data")
    else:
        hsi = hsi.sort_values("date").reset_index(drop=True)
        for days, key in [(30, "hsi_return_30d_prior_pct"), (90, "hsi_return_90d_prior_pct")]:
            end_px, _ = nearest_on_or_before(hsi, pd.Timestamp(ipo_date))
            start_px, _ = nearest_on_or_before(hsi, pd.Timestamp(ipo_date) - pd.Timedelta(days=days))
            if end_px and start_px:
                row[key] = round((end_px / start_px - 1) * 100, 2)

    # HIBOR
    try:
        row["hibor_1m_on_ipo_pct"] = price_data.hibor_1m_on_date(ipo_date)
    except Exception as e:
        log_error(code, "hibor_1m_on_ipo_pct", str(e))

    # ---- HKEX's own historical daily-close export (chart "Export to Excel"):
    # the authoritative direct source for last_price_20260630_hkd, used ahead
    # of Yahoo. NOTE the export itself only covers the last 2 years, so for
    # IPOs older than that this returns None and we fall back to Yahoo/widget
    # below -- it cannot reach a 2023 IPO's price as of a date in 2026.
    if widget_page is not None:
        try:
            hkex_hist = hkex_price_history.fetch_5y_history(widget_page, code)
            hkex_price = hkex_price_history.price_on_or_before(hkex_hist, REPORT_DATE)
            if hkex_price is not None:
                row["last_price_20260630_hkd"] = hkex_price
            else:
                log_error(code, "hkex_price_export", "HKEX chart export unavailable or IPO older than its 2-year export window; using Yahoo/widget fallback")
        except Exception as e:
            log_error(code, "hkex_price_export", f"{type(e).__name__}: {e}")

    # ---- HKEX equity-quote widget: ISIN, Chinese name, HSICS industry,
    # issued shares (excl. treasury), listing category, current price fallback ----
    widget_mkt_cap_hkd = None
    if widget_page is not None:
        try:
            q_en = hkex_widget.fetch_quote(widget_page, code, lang="en")
        except Exception as e:
            q_en = None
            log_error(code, "hkex_widget_en", str(e))
        try:
            q_zh = hkex_widget.fetch_quote(widget_page, code, lang="zh-hk")
        except Exception as e:
            q_zh = None
            log_error(code, "hkex_widget_zh", str(e))

        if q_en:
            row["isin"] = q_en.get("isin")
            # HSICS classification: "Materials - Basic Materials" (category -
            # subcategory1) plus a separate sub-sector field (subcategory2)
            ind = q_en.get("hsic_ind_classification") or ""
            sub2 = q_en.get("hsic_sub_sector_classification")
            if "-" in ind:
                cat, sub1 = ind.split("-", 1)
                row["hsics_category"] = cat.strip()
                row["hsics_subcategory_1"] = sub1.strip()
            elif ind:
                row["hsics_category"] = ind.strip()
            row["hsics_subcategory_2"] = sub2
            row["company_industry_description"] = q_en.get("summary")
            amt_os = q_en.get("amt_os")
            if amt_os:
                try:
                    row["issued_shares_excl_treasury"] = int(str(amt_os).replace(",", ""))
                except ValueError:
                    pass
            listing_category = q_en.get("listing_category")
            if listing_category:
                row["primary_listing"] = listing_category.strip().lower() == "primary listing"
            # cross-check H-share flag via place-of-incorporation signal
            incorpin = q_en.get("incorpin")
            if incorpin and incorpin.strip().upper() == "PRC" and not row["is_h_share"]:
                log_error(code, "is_h_share_crosscheck", f"NLR name suffix said not H-share, but widget incorpin='PRC' -- worth a manual check")
            # fallback for latest price when neither the HKEX export nor
            # Yahoo have historical bars at all (confirmed gap for some
            # recently-listed/reused tickers, e.g. MiniMax)
            if row["last_price_20260630_hkd"] is None:
                ls = q_en.get("ls")
                if ls:
                    try:
                        row["last_price_20260630_hkd"] = float(ls)
                        log_error(code, "last_price_20260630_hkd", "Neither HKEX export nor Yahoo had history; used HKEX widget's current live price as of scrape date (not literally 30 Jun 2026) as fallback")
                    except ValueError:
                        pass
            # HKEX widget's own live market cap figure -- kept only as a
            # fallback (used at the end of this function) for when Yahoo has
            # no shares-outstanding figure at all. Not used as the primary
            # source: it's computed from HKEX's live scrape-time price and
            # share count, which don't necessarily match last_price_20260630_hkd
            # (which may come from the HKEX historical export or Yahoo
            # instead) -- mixing sources like that is exactly what produced
            # an inconsistent-looking latest_market_cap_hkd previously.
            mkt_cap = q_en.get("mkt_cap")
            mkt_cap_u = q_en.get("mkt_cap_u")
            if mkt_cap:
                try:
                    val = float(str(mkt_cap).replace(",", ""))
                    mult = {"M": 1e6, "B": 1e9, "K": 1e3}.get(mkt_cap_u, 1)
                    widget_mkt_cap_hkd = round(val * mult, 2)
                except ValueError:
                    pass
        if q_zh:
            zh_name = q_zh.get("nm")
            if zh_name:
                # strip the same trailing rule/class suffixes HKEX appends in
                # Chinese too (e.g. '- B', '- W', '- H股'), which can stack
                # (e.g. '- B - H股'), mirroring the English-name cleanup in
                # parse_nlr._extract_suffix_flags
                while True:
                    new_name = re.sub(r"\s*-\s*(H\s*股|[A-Z](?:\s*,\s*[A-Z])*)\s*$", "", zh_name).strip()
                    if new_name == zh_name:
                        break
                    zh_name = new_name
                if zh_name == ipo["company_name_en"].strip():
                    log_error(code, "company_name_zh", "HKEX widget returned no distinct Chinese name (issuer has none registered)")
                else:
                    row["company_name_zh"] = zh_name

    # avg day1 perf of last 5 IPOs prior
    if prior_day1_perfs:
        last5 = [p for p in prior_day1_perfs[-5:] if p is not None]
        if last5:
            row["avg_day1_perf_last_5_ipos_pct"] = round(sum(last5) / len(last5), 2)

    # ---- Tier 2: prospectus / allotment-results / stabilization documents ----
    # Prefer the local PDF corpus (output/pdfs/, built by download_docs.py --
    # already resolved past any .htm index page to the actual Summary PDF)
    # over live network calls. Falls back to hkexnews_docs' live search only
    # for companies not yet present in the local manifest.
    manifest = local_docs.load_manifest() if local_docs.MANIFEST_PATH.exists() else None
    use_local = manifest is not None and local_docs.has_local_docs(code, manifest)

    if use_local:
        docs_local = local_docs.get_company_docs(code, manifest)
        prospectus_doc = local_docs.pick_prospectus(docs_local)
        allotment_doc = docs_local["allotment"][0] if docs_local["allotment"] else None
        stabilization_doc = docs_local["stabilization"][0] if docs_local["stabilization"] else None
    else:
        try:
            docs = hkexnews_docs.find_ipo_documents(code, ipo_date)
        except Exception as e:
            docs = {"error": str(e), "prospectus": [], "allotment": [], "stabilization": []}
            log_error(code, "find_ipo_documents", f"{type(e).__name__}: {e}")
        if docs.get("error"):
            log_error(code, "find_ipo_documents", docs["error"])
        prospectus_doc = {"local_path": None, "url": docs["prospectus"][0]["link"], "headline": docs["prospectus"][0]["headline"]} if docs["prospectus"] else None
        allotment_doc = {"local_path": None, "url": docs["allotment"][0]["link"], "headline": docs["allotment"][0]["headline"]} if docs["allotment"] else None
        stabilization_doc = {"local_path": None, "url": docs["stabilization"][0]["link"], "headline": docs["stabilization"][0]["headline"]} if docs.get("stabilization") else None

    def get_text(doc):
        if doc is None:
            return None
        if doc.get("local_path"):
            return local_docs.extract_text(doc["local_path"])
        return hkexnews_docs.fetch_document_text(doc["url"])

    if prospectus_doc:
        row["prospectus_link"] = prospectus_doc.get("url") or str(prospectus_doc.get("local_path"))
        text = get_text(prospectus_doc)
        if text:
            lo, hi = pdf_extract.extract_offer_price_range(text)
            row["offer_price_range_low_hkd"], row["offer_price_range_high_hkd"] = lo, hi
            if lo and hi and row["ipo_price_hkd"]:
                rng = hi - lo
                if rng > 0:
                    row["ipo_price_vs_range_pct"] = round((row["ipo_price_hkd"] - lo) / rng * 100, 1)
            shares = pdf_extract.extract_total_shares_in_issue(text)
            if shares:
                row["post_ipo_total_issued_shares"] = shares
                share_count_source["value"] = "scraped_prospectus"
                if row["ipo_price_hkd"]:
                    row["market_cap_at_listing_hkd"] = round(shares * row["ipo_price_hkd"], 2)
            offering_shares = pdf_extract.extract_global_offering_shares(text)
            scraped_offer_shares = offering_shares.get("shares_global_offering")
            if scraped_offer_shares:
                row["total_ipo_size_shares"] = scraped_offer_shares
                row["total_shares_issued_at_ipo"] = scraped_offer_shares
            # NLR's own "Sponsor(s)" column (already in row["lead_brokers_underwriters"]
            # from the NLR data, set earlier in this function) is the reliable base.
            # Only ADD bookrunner/lead-manager names extracted here if they're
            # cleanly captured and not already implied by the sponsor list --
            # never overwrite the NLR-sourced value with a prospectus-parse result.
            banks = pdf_extract.extract_sponsors_and_banks(text)
            extra = [v for k, v in banks.items() if k != "sponsor" and v]
            if extra and row["lead_brokers_underwriters"]:
                row["lead_brokers_underwriters"] = row["lead_brokers_underwriters"] + " | Bookrunners/Lead Managers: " + " / ".join(extra)
            elif not row["lead_brokers_underwriters"] and banks.get("sponsor"):
                row["lead_brokers_underwriters"] = banks["sponsor"]
            if row["lead_brokers_underwriters"]:
                cls = classify_broker(row["lead_brokers_underwriters"])
                row["lead_broker_is_global_bank"] = cls["is_global_bank"]
                row["lead_broker_is_chinese_bank"] = cls["is_chinese_bank"]
                row["multiple_lead_brokers"] = cls["multiple"]
        else:
            log_error(code, "prospectus_pdf_text", "Prospectus document found but text extraction failed")
    else:
        log_error(code, "prospectus_link", "No prospectus/Global Offering listing document found in +/-60 day search window")

    if allotment_doc:
        row["hkex_ipo_documentation_link"] = allotment_doc.get("url") or str(allotment_doc.get("local_path"))
        if allotment_doc.get("local_path"):
            # local corpus already resolved past any .htm index page to the
            # Summary PDF at download time (see hkexnews_docs.resolve_htm_to_summary_pdf)
            text = local_docs.extract_text(allotment_doc["local_path"])
        else:
            # the "Allotment Results" headline can link to an index .htm page
            # with sub-document links (Cover/Summary/...) -- resolve the
            # Summary PDF, which carries the oversubscription/clawback/
            # cornerstone detail
            allotment_url = allotment_doc["url"]
            summary_url = None
            if allotment_url.lower().endswith(".htm"):
                try:
                    summary_url = hkexnews_docs.resolve_htm_to_summary_pdf(allotment_url)
                except Exception as e:
                    log_error(code, "allotment_summary_link", f"{type(e).__name__}: {e}")
            text = hkexnews_docs.fetch_document_text(summary_url) if summary_url else hkexnews_docs.fetch_document_text(allotment_url)
        if text:
            # newer (2024+) allotment announcements use a structured "Company
            # information" summary that includes offer price range directly --
            # older prospectus-only extraction (above) may have already found
            # it; don't overwrite a good value, just fill the gap
            if row["offer_price_range_low_hkd"] is None:
                lo, hi = pdf_extract.extract_offer_price_range(text)
                row["offer_price_range_low_hkd"], row["offer_price_range_high_hkd"] = lo, hi
                if lo and hi and row["ipo_price_hkd"]:
                    rng = hi - lo
                    if rng > 0:
                        row["ipo_price_vs_range_pct"] = round((row["ipo_price_hkd"] - lo) / rng * 100, 1)

            # 2024+ allotment announcements state offer/post-listing share
            # counts directly in a labelled "Offer Shares and Share Capital"
            # block -- this is the most authoritative source when present,
            # takes priority over the prospectus-based / Yahoo-approximated
            # figures set earlier in this function.
            offer_shares_direct = pdf_extract.extract_number_of_offer_shares(text)
            if offer_shares_direct:
                row["total_ipo_size_shares"] = offer_shares_direct
                row["total_shares_issued_at_ipo"] = offer_shares_direct
            shares_upon_listing = pdf_extract.extract_shares_upon_listing(text)
            if shares_upon_listing:
                row["post_ipo_total_issued_shares"] = shares_upon_listing
                share_count_source["value"] = "scraped_allotment"
                if row["ipo_price_hkd"]:
                    row["market_cap_at_listing_hkd"] = round(shares_upon_listing * row["ipo_price_hkd"], 2)

            times_over = pdf_extract.extract_oversubscription(text)
            row["times_oversubscribed_retail"] = times_over
            row["oversubscribed"] = True if (times_over and times_over > 1) else (False if times_over is not None else None)
            row["num_valid_retail_applicants"] = pdf_extract.extract_num_valid_retail_applicants(text)
            row["pool_a_1lot_allocation_rate_pct"] = pdf_extract.extract_hk_1lot_allocation_rate(text)

            clawback = pdf_extract.extract_clawback(text)
            row["clawback_pct_triggered"] = clawback["final_hk_offer_pct"]
            row["clawback_mechanism"] = clawback["mechanism_description"]

            cornerstones = pdf_extract.extract_cornerstone_investors(text)
            row["num_cornerstone_investors"] = cornerstones["count"]
            row["cornerstone_allocation_pct"] = cornerstones["total_pct_of_shares_in_issue"]
            row["cornerstone_lockup_months"] = pdf_extract.extract_cornerstone_lockup_months(text)
            if cornerstones["investors"]:
                names = [inv["name"] for inv in cornerstones["investors"]]
                pedigree = classify_cornerstones(names)
                row["cornerstone_pedigree_global_fund"] = pedigree["global_fund"]
                row["cornerstone_pedigree_sovereign_wealth"] = pedigree["sovereign_wealth"]
                row["cornerstone_pedigree_large_company"] = pedigree["large_company"]

            top_placee = pdf_extract.extract_top_concentration(text, "placees")
            row["top1_placee_concentration_pct"] = top_placee.get("top1_pct")
            row["top5_placee_concentration_pct"] = top_placee.get("top5_pct")
            row["top10_placee_concentration_pct"] = top_placee.get("top10_pct")
            row["top20_placee_concentration_pct"] = top_placee.get("top20_pct")

            top_sh = pdf_extract.extract_top_concentration(text, "shareholders")
            row["top1_shareholder_concentration_pct"] = top_sh.get("top1_pct")
            row["top5_shareholder_concentration_pct"] = top_sh.get("top5_pct")
            row["top10_shareholder_concentration_pct"] = top_sh.get("top10_pct")
            row["top20_shareholder_concentration_pct"] = top_sh.get("top20_pct")

            row["hkex_high_concentration_flag"] = pdf_extract.extract_high_concentration_flag(text)
        else:
            log_error(code, "allotment_pdf_text", "Allotment results document found but text extraction failed")
    else:
        log_error(code, "allotment_link", "No allotment results document found in +/-60 day search window")

    # Some offerings (e.g. TUHU) never publicly disclose a low-high price
    # range at all -- only a "Maximum Offer Price" cap on the prospectus
    # cover. In that case populate the high end from the cap and leave the
    # low end NULL, rather than leaving both NULL when we do have a partial
    # data point. get_text() is cached so re-fetching the prospectus here is
    # cheap (no repeat network/parse cost).
    if row["offer_price_range_low_hkd"] is None and row["offer_price_range_high_hkd"] is None and prospectus_doc:
        ptext = get_text(prospectus_doc)
        if ptext:
            max_price = pdf_extract.extract_max_offer_price(ptext)
            if max_price:
                row["offer_price_range_high_hkd"] = max_price
                log_error(code, "offer_price_range_low_hkd", "This offering only publicly disclosed a Maximum Offer Price cap, no low-high range -- high populated from the cap, low left NULL")
            else:
                log_error(code, "offer_price_range_low_hkd", "No low-high range or Maximum Offer Price cap found in prospectus or allotment documents")

    # greenshoe_exercised, per user instruction, tracks whether a stabilization
    # notice was filed at all (i.e. a Stabilizing Manager was appointed and ran
    # the process) rather than the narrower "was the Over-allotment Option
    # itself exercised" question -- those notices are filed even when the
    # option ultimately lapsed (e.g. Fenbi/Luzhu/Cutia), since stabilizing
    # actions can occur independently of the option being exercised.
    row["greenshoe_exercised"] = bool(stabilization_doc)
    if stabilization_doc:
        text = get_text(stabilization_doc)
        if text:
            stab = pdf_extract.extract_stabilization_details(text)
            row["greenshoe_broker"] = stab["broker"]
            row["greenshoe_net_secondary_purchases_shares"] = stab["net_purchases_shares"]
            row["greenshoe_avg_stabilization_price_hkd"] = stab["avg_price_hkd"]
            row["greenshoe_last_exercise_date"] = stab["last_exercise_date"]
        else:
            log_error(code, "stabilization_pdf_text", "Stabilization document found but text extraction failed")
    # absence of a stabilization notice is not logged as an error -- some IPOs
    # have no over-allotment provision at all, so it's frequently correct for
    # there to be none

    if row["total_ipo_size_shares"] is None and ipo["total_ipo_size_hkd"] and row["ipo_price_hkd"]:
        row["total_ipo_size_shares"] = round(ipo["total_ipo_size_hkd"] / row["ipo_price_hkd"])
        row["total_shares_issued_at_ipo"] = row["total_ipo_size_shares"]
        log_error(code, "total_ipo_size_shares", "Not found in prospectus/allotment text; approximated from total_ipo_size_hkd / ipo_price_hkd instead")

    if share_count_source["value"] == "yahoo_approx":
        log_error(code, "market_cap_at_listing_hkd", "No prospectus/allotment share count found; approximated from current Yahoo shares outstanding x IPO price -- may drift from the true at-listing figure")
    elif share_count_source["value"] is None:
        log_error(code, "market_cap_at_listing_hkd", "No share count available from any source (Yahoo, prospectus, or allotment results)")

    # ---- final CALC fields that depend on values only available after Tier 2 ----
    if row["market_cap_at_listing_hkd"] is not None:
        row["market_cap_at_listing_usd"] = round(row["market_cap_at_listing_hkd"] / USD_HKD, 2)
    if row["day1_traded_volume_usd"] is not None and row["market_cap_at_listing_usd"]:
        # per user's specified formula: Day-1 USD volume / market cap at listing (USD)
        row["day1_volume_vs_free_float_pct"] = round(row["day1_traded_volume_usd"] / row["market_cap_at_listing_usd"] * 100, 2)

    # latest_market_cap_hkd = last_price_20260630_hkd x shares outstanding as
    # of 30 Jun 2026, both from Yahoo -- computed here (end of function) so it
    # uses the FINAL last_price_20260630_hkd value after all upstream
    # overwrites (HKEX historical export / widget fallback), keeping price
    # and share count internally consistent. Falls back to the HKEX widget's
    # own live market cap only if Yahoo has no shares-outstanding figure.
    if row["last_price_20260630_hkd"] is not None and current_shares_out:
        row["latest_market_cap_hkd"] = round(row["last_price_20260630_hkd"] * current_shares_out, 2)
        row["latest_market_cap_20260630_usd"] = round(row["latest_market_cap_hkd"] / USD_HKD, 2)
    elif widget_mkt_cap_hkd is not None:
        row["latest_market_cap_hkd"] = widget_mkt_cap_hkd
        row["latest_market_cap_20260630_usd"] = round(widget_mkt_cap_hkd / USD_HKD, 2)
        log_error(code, "latest_market_cap_hkd", "No Yahoo shares-outstanding figure available; used HKEX widget's own live market cap (native HKD) as fallback instead of last_price x shares_outstanding")
    else:
        log_error(code, "latest_market_cap_hkd", "Neither last_price_20260630_hkd nor Yahoo shares outstanding nor HKEX widget market cap available")

    return row


def main():
    full = "--full" in sys.argv

    print("Loading NLR yearly reports 2023-2026...")
    df = parse_nlr.load_all()
    kept, scope_audit = parse_nlr.apply_scope_filters(df)
    print(f"Total in-scope Main Board IPOs (2023-01-01 to 2026-06-30): {len(kept)}")

    kept_sorted = kept.sort_values("ipo_date").reset_index(drop=True)
    targets = kept_sorted if full else pick_pilot_set(kept).sort_values("ipo_date").reset_index(drop=True)
    out_stem = "hkex_ipo_full" if full else "hkex_ipo_pilot"
    print(f"{'Full' if full else 'Pilot'} set: {len(targets)} companies -> {out_stem}.csv")
    if not full:
        print(targets[["stock_code", "company_name_en", "ipo_date", "is_chapter_18a", "is_chapter_18c", "secondary_listing", "is_wvr"]].to_string())

    print("Loading A1 filing date index...")
    a1_index = a1_filing_dates.load_index()

    print("Loading Southbound eligible-securities list...")
    southbound_list = southbound.load_current_list()

    out_csv = OUTPUT_DIR / f"{out_stem}.csv"
    # resumable: a row already written for a stock_code is skipped on rerun,
    # so an interrupted full-scale run (network hiccup, Playwright crash,
    # etc.) can just be re-invoked rather than starting over from row 1.
    done_codes = set()
    if out_csv.exists():
        done_codes = set(pd.read_csv(out_csv, dtype={"stock_code": str})["stock_code"].str.zfill(5))
        print(f"  {len(done_codes)} companies already in {out_csv.name}, will be skipped")

    write_header = not out_csv.exists()
    rows_written = 0

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p, open(out_csv, "a", newline="", encoding="utf-8") as f:
        browser = p.chromium.launch()
        widget_page = browser.new_page()
        writer = csv.DictWriter(f, fieldnames=COLUMN_NAMES)
        if write_header:
            writer.writeheader()

        for i, (_, ipo) in enumerate(targets.iterrows(), start=1):
            code = str(ipo["stock_code"]).zfill(5)
            if code in done_codes:
                continue
            print(f"\n--- [{i}/{len(targets)}] Processing {code} {ipo['company_name_en']} ({ipo['ipo_date'].date()}) ---")
            idx_in_full = kept_sorted.index[kept_sorted["stock_code"] == code]
            prior_perfs = []
            if len(idx_in_full):
                start = max(0, idx_in_full[0] - 5)
                for j in range(start, idx_in_full[0]):
                    # cheap day1 perf lookup for the 5 prior IPOs, from cache if available
                    prior_ipo = kept_sorted.iloc[j]
                    pt = price_data.stock_ticker(prior_ipo["stock_code"])
                    pdate = prior_ipo["ipo_date"].date()
                    ppx = price_data.fetch_ohlcv(pt, pdate - timedelta(days=3), pdate + timedelta(days=3))
                    if ppx is not None and not ppx.empty and prior_ipo["ipo_price_hkd"]:
                        ppx = ppx.sort_values("date")
                        d1 = ppx[ppx["date"] >= pd.Timestamp(pdate)].head(1)
                        if not d1.empty:
                            prior_perfs.append((float(d1.iloc[0]["close"]) / prior_ipo["ipo_price_hkd"] - 1) * 100)
            try:
                row = build_row(ipo.to_dict(), prior_perfs, widget_page=widget_page, a1_index=a1_index, southbound_list=southbound_list)
            except Exception as e:
                log_error(code, "build_row", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
                row = {c: None for c in COLUMN_NAMES}
                row["stock_code"] = code
                row["company_name_en"] = ipo["company_name_en"]
            writer.writerow(row)
            f.flush()
            rows_written += 1

        browser.close()

    print(f"\nWrote {rows_written} new rows to {out_csv}")

    # xlsx / error / scope-audit outputs are regenerated in full from the
    # complete CSV on every run (cheap), so they always reflect everything
    # written so far even across multiple resumed invocations.
    all_df = pd.read_csv(out_csv, dtype={"stock_code": str})
    all_df = all_df.astype(object).where(pd.notna(all_df), None)  # NaN -> None, not a numeric NaN cell in the xlsx
    all_rows = all_df.to_dict("records")
    out_xlsx = OUTPUT_DIR / f"{out_stem}.xlsx"
    excel_export.write_xlsx(all_rows, COLUMN_NAMES, out_xlsx)
    print(f"Wrote {out_xlsx} (use this one in Excel -- preserves stock code leading zeros and applies #,##0.00 number formatting, unlike the CSV)")

    errors_suffix = "full" if full else "pilot"
    with open(OUTPUT_DIR / f"{errors_suffix}_errors.json", "w") as f:
        json.dump(errors_log, f, indent=2, default=str)

    with open(OUTPUT_DIR / f"{errors_suffix}_scope_audit.json", "w") as f:
        json.dump(scope_audit, f, indent=2, default=str)

    print(f"Errors logged this run: {len(errors_log)}")


if __name__ == "__main__":
    main()
