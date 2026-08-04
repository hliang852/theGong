"""
Column schema for the HKEX Main Board IPO dataset.

Each column is tagged with a source tier:
  T1 = reliably scrapable from structured public sources (HKEXnews NLR reports,
       Yahoo Finance price data, HKMA HIBOR API)
  T2 = obtainable but requires parsing prospectus / allotment-result PDFs;
       best-effort regex extraction, may legitimately come back NULL per filing
  T3 = not reliably available from free public sources for most issuers;
       always NULL in this pipeline, flagged for manual/paid-terminal audit
  CALC = derived/computed from other fields (dates, ratios) rather than scraped
"""

COLUMNS = [
    ("a1_filing_date", "T1"),          # HKEXnews consolidated application index (Date of First Posting), matched by company name
    ("ipo_date", "T1"),
    ("stock_code", "T1"),
    ("isin", "T1"),                    # HKEX equity-quote widget
    ("company_name_en", "T1"),
    ("company_name_zh", "T1"),         # HKEX equity-quote widget (sc_lang=zh-hk)
    ("hsics_category", "T1"),          # HKEX equity-quote widget hsic_ind_classification, text before "-"
    ("hsics_subcategory_1", "T1"),     # hsic_ind_classification, text after "-"
    ("hsics_subcategory_2", "T1"),     # hsic_sub_sector_classification
    ("is_chapter_18a", "T1"),
    ("is_chapter_18c", "T1"),
    ("is_chapter_19c", "T1"),
    ("is_h_share", "T1"),              # NLR company-name suffix + widget incorpin cross-check
    ("primary_listing", "T1"),         # HKEX equity-quote widget listing_category
    ("adr_relisting", "T3"),
    ("adr_code", "T3"),
    ("a_to_h_listing", "T2"),
    ("a_share_stock_code", "T2"),
    ("share_class", "T2"),
    ("dual_primary_listing", "T2"),
    ("secondary_listing", "T1"),
    ("fini_platform_flag", "CALC"),
    ("company_industry_description", "T2"),
    ("market_cap_at_listing_hkd", "T2"),   # shares-at-listing (scraped, see post_ipo_total_issued_shares) x IPO price
    ("market_cap_at_listing_usd", "CALC"),  # = market_cap_at_listing_hkd / 7.8
    ("latest_market_cap_hkd", "T1"),        # HKEX equity-quote widget mkt_cap field (native HKD, not a conversion)
    ("latest_market_cap_20260630_usd", "CALC"),  # = latest_market_cap_hkd / 7.8
    ("current_free_float_shares", "T1"),   # Yahoo quoteSummary floatShares (current, not at-listing)
    ("current_free_float_pct", "T1"),
    ("last_price_20260630_hkd", "T1"),      # HKEX chart-export daily close (primary) or Yahoo/widget fallback
    ("total_shares_issued_at_ipo", "T2"),   # scraped: prospectus/allotment "Number of Offer Shares"
    ("total_ipo_size_hkd", "T1"),           # from HKEX NLR report (HK Offer + International Offer tranches)
    ("total_ipo_size_usd", "CALC"),         # = total_ipo_size_hkd / 7.8
    ("total_ipo_size_shares", "T2"),        # scraped: prospectus/allotment "Number of Offer Shares"
    ("post_ipo_total_issued_shares", "T2"), # scraped: allotment "Number of issued shares upon Listing"
    ("issued_shares_excl_treasury", "T1"),   # HKEX equity-quote widget amt_os (current, not as-of-listing)
    ("offer_price_range_low_hkd", "T2"),
    ("offer_price_range_high_hkd", "T2"),
    ("ipo_price_hkd", "T1"),
    ("ipo_price_vs_range_pct", "CALC"),
    ("pe_at_ipo", "T3"),
    ("pb_at_ipo", "T3"),
    ("day1_performance_pct", "CALC"),
    ("day1_traded_volume_usd", "T1"),
    ("day1_volume_vs_free_float_pct", "CALC"),  # = day1_traded_volume_usd / market_cap_at_listing_usd, per user's formula
    ("day1_open_hkd", "T1"),
    ("day1_closing_price_hkd", "T1"),
    ("day1_high_hkd", "T1"),
    ("day1_low_hkd", "T1"),
    ("hsi_return_30d_prior_pct", "T1"),
    ("hsi_return_90d_prior_pct", "T1"),
    ("hibor_1m_on_ipo_pct", "T1"),
    ("avg_day1_perf_last_5_ipos_pct", "CALC"),
    ("oversubscribed", "T2"),
    ("times_oversubscribed_retail", "T2"),
    ("clawback_mechanism", "T2"),
    ("clawback_pct_triggered", "T2"),
    ("perf_3d_pct", "CALC"),
    ("volume_3d_usd", "T1"),
    ("perf_5d_pct", "CALC"),
    ("volume_5d_usd", "T1"),
    ("perf_20d_pct", "CALC"),
    ("volume_20d_usd", "T1"),
    ("lockup_6m_expiry_date", "CALC"),
    ("perf_on_lockup_expiry_pct", "CALC"),
    ("perf_lockup_day0_vs_ipo_pct", "CALC"),
    ("perf_lockup_dayminus2_vs_ipo_pct", "CALC"),
    ("perf_lockup_dayminus1_vs_ipo_pct", "CALC"),
    ("perf_lockup_dayplus1_vs_ipo_pct", "CALC"),
    ("perf_lockup_dayplus2_vs_ipo_pct", "CALC"),
    ("ipo_perf_1y_pct", "CALC"),
    ("num_cornerstone_investors", "T2"),
    ("cornerstone_allocation_pct", "T2"),
    ("cornerstone_pedigree_global_fund", "T2"),   # rule-based classification, see reference/cornerstone_pedigree.py
    ("cornerstone_pedigree_sovereign_wealth", "T2"),
    ("cornerstone_pedigree_large_company", "T2"),
    ("cornerstone_lockup_months", "T2"),
    ("top1_placee_concentration_pct", "T2"),
    ("top5_placee_concentration_pct", "T2"),
    ("top10_placee_concentration_pct", "T2"),
    ("top20_placee_concentration_pct", "T2"),
    ("top1_shareholder_concentration_pct", "T2"),
    ("top5_shareholder_concentration_pct", "T2"),
    ("top10_shareholder_concentration_pct", "T2"),
    ("top20_shareholder_concentration_pct", "T2"),
    ("hkex_high_concentration_flag", "T2"),
    ("pool_a_1lot_allocation_rate_pct", "T2"),
    ("num_valid_retail_applicants", "T2"),
    ("greenshoe_exercised", "T2"),
    ("greenshoe_broker", "T2"),         # Stabilizing Manager name, from the stabilization notice
    ("greenshoe_net_secondary_purchases_shares", "T2"),
    ("greenshoe_avg_stabilization_price_hkd", "T2"),
    ("greenshoe_last_exercise_date", "T2"),
    ("prospectus_link", "T1"),
    ("hkex_ipo_documentation_link", "T1"),
    ("lead_brokers_underwriters", "T2"),
    ("lead_broker_is_global_bank", "T2"),          # rule-based classification, see reference/broker_nationality.py
    ("lead_broker_is_chinese_bank", "T2"),
    ("multiple_lead_brokers", "T2"),
    ("lead_broker_initiated_coverage", "T3"),
    ("base_underwriting_commission_pct", "T3"),
    ("discretionary_incentive_fee_pct", "T3"),
    ("msci_included", "T3"),
    ("msci_inclusion_date", "T3"),
    ("hsi_included", "T3"),
    ("hsi_inclusion_date", "T3"),
    ("ftse_included", "T3"),
    ("ftse_inclusion_date", "T3"),
    ("southbound_included", "T1"),      # SSE live eligible-securities query (current membership only)
    ("southbound_inclusion_date", "T3"),  # no "date added" field in the live feed; would need quarterly bulletin history
]

COLUMN_NAMES = [c[0] for c in COLUMNS]
COLUMN_TIER = dict(COLUMNS)
