# HKEX Main Board IPO Scraper — Pilot Report

**Scope:** Main Board IPOs, 1 Jan 2023 – 30 Jun 2026. Excludes listing-by-introduction, de-SPAC transactions, and GEM-to-Main Board transfers.
**Pilot run date:** 2 Jul 2026 (data as observed at run time; "latest" fields reflect prices as of the run date, not literally 30 Jun 2026, for the two Jan-2026 IPOs where the lock-up window hasn't occurred yet).

## 1. Universe sizing (full population, not just pilot)

Source: HKEX's own yearly "New Listing Report" (NLR) Excel files — the authoritative Main Board new-listing register.

| Step | Count |
|---|---|
| Total Main Board NLR rows, 2023–2026 (partial) | 346 |
| Excluded — listing by introduction | 4 |
| Excluded — de-SPAC transaction | 3 |
| Excluded — GEM-to-Main Board transfer | 7 |
| **In-scope IPOs (final population)** | **331** |

These exclusions are pulled directly from HKEX's own remarks column ("N/A – By Introduction" / "N/A – By De-SPAC Transaction" / "N/A – Transfer of Listing from GEM to Main Board"), not a heuristic — reliable.

## 2. Pilot batch

8 companies were sampled across years and rule types to validate the pipeline before scaling to all 331:

| Code | Company | IPO Date | 18A | 18C | WVR |
|---|---|---|---|---|---|
| 02469 | Fenbi Ltd. | 09/01/2023 | | | |
| 02487 | Cutia Therapeutics | 12/06/2023 | ✓ | | |
| 02105 | Laekna, Inc. | 29/06/2023 | ✓ | | |
| 09690 | TUHU Car Inc. | 26/09/2023 | | | ✓ |
| 02228 | QuantumPharm Inc. | 13/06/2024 | | ✓ | |
| 02560 | Anhui Conch Material Technology | 09/01/2025 | | | |
| 06082 | Shanghai Biren Technology | 02/01/2026 | | | |
| 00100 | MiniMax Group Inc. | 09/01/2026 | | ✓ | ✓ |

No genuine Chapter 19C secondary listings occurred in this window (0 found in the full 331-company population), so none appear in the pilot.

Output: `output/hkex_ipo_pilot.csv` (75 columns per the requested schema). Full error log: `output/pilot_errors.json`. Exclusion audit: `output/pilot_scope_audit.json`.

## 3. Field-tier fill rates in the pilot

| Tier | Description | Filled |
|---|---|---|
| **T1** (structured public sources: HKEX NLR, Yahoo Finance, HKMA HIBOR) | 80.0% (160/200 cells) |
| **CALC** (derived: returns, ratios, lock-up dates) | 77.5% (93/120 cells) |
| **T2** (requires prospectus/allotment PDF text) | 13.8% (32/232 cells) — see §4, blocked |
| **T3** (not reliably public) | 0.0% (0/256 cells) — by design, always NULL |

## 4. Key finding: Tier 2 fields are blocked by a JS-rendered search page, not organic data absence

The plan assumed HKEXnews' document title-search (`titlesearch.xhtml`) could be queried with a plain HTTP GET to locate each company's prospectus and allotment-results PDFs. **Verified during the pilot: it cannot.** The page is a JSF (JavaServer Faces) application — a GET returns only the page shell; actual results are rendered via a stateful AJAX POST tied to a server-side ViewState token, which in turn requires either a real browser session or reverse-engineering the JSF component protocol (fragile, session-bound, likely rate-limited at 331×2 requests).

Net effect: every Tier-2 field that depends on locating and parsing the prospectus or allotment-results PDF — **ISIN, offer price range, post-IPO share count, market cap at listing, oversubscription %, clawback %, cornerstone investor count/allocation, greenshoe exercised, PE/PB, HKEX high-concentration flag, Pool A allocation rate** — came back NULL in the pilot, not because the data isn't public, but because my request-based scraper can't reach it. The lead-broker/underwriter fields *did* fill successfully because those come straight from the NLR sponsor column, not the PDF search.

**This is the difficulty flag for a human decision.** Two paths forward:

- **(a) Headless-browser automation** (Playwright/Selenium) to drive the JSF search and download each PDF, then run the same regex extraction already built and pilot-tested in `pdf_extract.py`. This unlocks ~15 more columns. Cost: materially slower (~2 page-loads + 2 PDF fetches per company × 331 companies), more brittle (breaks if HKEX changes the JSF page), and needs a browser runtime in the execution environment.
- **(b) Accept Tier 2 as NULL for now**, ship the 331-row CSV with T1/CALC fields populated (roughly half the schema, the most quantitatively load-bearing half — prices, returns, dates, sizing), and flag all Tier-2/3 columns for manual/paid-terminal follow-up.

I have not built the browser-automation path yet — it's a real scope increase, not a small tweak, and I want your call before investing in it.

## 5. Other confirmed gaps (independent of the above)

- **A1 filing date**: HKEXnews only publishes a *rolling* window of pending "Application Proof" filings; once a company lists, its proof is no longer listed on that page, and there is no yearly archive analogous to the NLR report. Reconstructing this historically would require Wayback Machine snapshots per company (labor-intensive, incomplete coverage) or a paid terminal. **Recommend NULL + audit flag for all 331 rows**, consistent with your Tier-3 decision.
- **HSICS industry code**: owned by Hang Seng Indexes Company, not HKEX; no bulk stock→code mapping found, only a taxonomy PDF. Would need per-company lookup on Hang Seng's site (not yet confirmed scrapable).
- **Yahoo Finance gaps for very recently listed/reused stock codes**: `00100.HK` (MiniMax Group, listed 9 Jan 2026) returned no price history at all from Yahoo — likely a symbol-mapping lag for a reused low stock code. 1 of 8 pilot companies hit this. At scale, expect a handful of such gaps requiring a fallback source (AAStocks or Investing.com) or manual patch.
- **Index inclusion dates (MSCI/HSI/FTSE/Southbound)**: each index provider publishes its own quarterly review announcements on separate sites with no unified, scrapable per-stock history; confirmed T3, left NULL as agreed.
- One pilot data point worth a manual sanity check: Anhui Conch Material Technology (02560) shows a **-47.7% Day-1 return**, unusually large for a Main Board IPO — worth spot-checking against a second source before trusting it at scale (could be correct — 2025 saw several weak industrial IPOs — but flagging per your audit request).

## 6. Update: both proposed fixes hit hard blockers

Two follow-ups were attempted after the initial pilot, both dead-ended:

- **Playwright automation for Tier 2 documents**: the JSF search page's autocomplete/search API returned empty, no-cache `application/json` responses to a headless Chromium session even after correctly filling the stock-code field and clicking Search — consistent with bot-fingerprint detection (headless browsers expose `navigator.webdriver` and other automation signals by default) rather than simple JS-rendering. Making this reliable would require fingerprint-spoofing/stealth techniques, which crosses from "scrape public disclosure documents" into "evade anti-bot detection" — a call I'm not making unilaterally given HKEX's terms of service likely restrict automated access. **Stopped here; not attempted.**
- **Wayback Machine reconstruction for A1 filing dates**: archive.org is unreachable from this sandboxed execution environment at the network level (TLS connection resets on every attempt, while all other tested sites — including hkexnews.hk itself — work normally). This isn't a data-availability problem, it's an environment restriction. The same limitation also closes off a promising workaround I'd identified (using Wayback snapshots of the *static, ungated* "New Listing Information" HTML table, which does carry direct prospectus/allotment PDF links for recent listings, to reconstruct historical coverage).

## 6b. Post-review fixes (user-flagged issues, 2 Jul 2026)

User review of the pilot caught two real bugs and one mis-scoping on my part:

1. **`latest_market_cap_20260630_usd` / `current_free_float_*` were wrongly wired to the blocked prospectus-PDF path.** Yahoo Finance actually exposes current shares outstanding, float shares, and market cap through a *different* endpoint (`quoteSummary`, crumb-authenticated) than the OHLCV `chart` endpoint I'd been using. Wired this in — these are now T1 fields. Reclassified `current_free_float_shares`/`current_free_float_pct` from T3 to T1 accordingly (they're current, not as-of-listing, values — noted as a caveat, not a limitation of availability).
2. **Bug: historical price downloads were capped at `ipo_date + 430 days`**, so "latest price" for a 2023 IPO was actually a stale ~14-months-post-IPO price, not the true current one. Fixed to always fetch through the report date.
3. **`total_shares_issued_at_ipo` / `total_ipo_size_shares` were simply never implemented** — an omission, not a data gap. Both are directly computable from data already in hand (funds raised ÷ IPO price, from the NLR report). Added as CALC fields.
4. **`market_cap_at_listing_usd` / `post_ipo_total_issued_shares`**: exact values still require the (blocked) prospectus; now fall back to current Yahoo shares outstanding × IPO price as an approximation, explicitly flagged as approximate (may differ from the true listing-date figure if the company issued or bought back shares since).
5. **MiniMax (0100.HK) Day-1 fields confirmed as a genuine Yahoo data gap, not a bug**: Yahoo's live quote works for this ticker (current price, shares outstanding all present), but its historical daily-bar endpoint reports `validRanges: ["1d","5d"]` only — no OHLCV history has been backfilled for this specific recently-listed/recycled stock code. Would need a fallback source (AAStocks/Investing.com) to fill this one company's Day-1/lock-up/multi-day performance fields.

**Result: Tier-1 fill rate improved from 80.0% to 92.3%** after these fixes (re-measured on the same 8-company pilot). Tier 2 rose slightly (17.9%, from the newly-added approximate market-cap-at-listing fallback) but remains blocked for the fields that genuinely require the prospectus/allotment PDFs (see §4/§6).

## 6c. Second round of user-flagged issues (2 Jul 2026) — found a new, unblocked HKEX data source

User review caught five more gaps. Investigating them turned up something important: **HKEX's own "Equities Quote" widget** (the page behind `hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=XXXX`, the URL the user pointed at directly for point 7) calls a JSON API that — unlike the HKEXnews document-search tool — is **not** bot-gated. It just needs a page-embedded token grabbed via one lightweight Playwright page load per stock code. This single source resolved four of the five points at once:

1. **`company_name_zh`**: solved. The widget takes `sc_lang=zh-hk` and returns the Chinese name directly (e.g. `安徽海螺材料科技股份有限公司`). Reclassified T2→T1. Also stripped the same rule/class-code suffixes from the Chinese name that were already being stripped from the English name, for consistency. Note: a few issuers (e.g. MiniMax, pure Cayman-incorporated tech companies) genuinely have no distinct registered Chinese name — that's real absence, not a scrape failure, and is now logged as such rather than silently blank.
2. **New column `is_h_share`**: added. H-share issuers carry a literal `- H Shares` text suffix in HKEX's own company name field (separate from the B/P/S/W legend-coded system) — detected directly from the authoritative NLR data, no extra source needed. Cross-checked against the widget's `incorpin` (place of incorporation) field as a sanity signal.
3. **ISIN**: solved. Directly in the widget response (`isin` field). Reclassified T2→T1.
4. **`hsics_industry_code`**: solved. The widget exposes `hsic_ind_classification` + `hsic_sub_sector_classification` (e.g. "Materials - Basic Materials / Specialty Chemicals") for every Main Board stock. This is HKEX's own human-readable classification label, not the raw numeric HSICS code (no bulk numeric-code mapping was found) — flagged as a labelling nuance, not a gap. Reclassified T3→T1. Also populated `company_industry_description` from the widget's free-text `summary` field (business description).
5. **New column `issued_shares_excl_treasury`**: added, sourced from the widget's `amt_os` field — this is a current (scrape-date) figure, not as-of-listing.
6. **New column `primary_listing`**: added, sourced from the widget's `listing_category` field ("Primary Listing" / "Secondary Listing"), cross-checked against the existing secondary-listing flag from the NLR suffix.

**Offer price range (point 4)** was *not* solved by the widget — its `original_offer_price` field was empty across every stock tested (Anhui Conch, MiniMax, Fenbi), suggesting it's not populated for ordinary equity IPOs. This field still requires the prospectus PDF, which remains blocked by the bot-gated HKEXnews search tool (§4/§6, unchanged). The extraction logic (`pdf_extract.extract_offer_price_range`) is already written and tested — it just has nothing to read yet.

**MiniMax's missing fields (point 3)** turned out to be two separate issues, now split apart:
- `lockup_6m_expiry_date` was a **bug**: it's a pure calendar calculation (IPO date + 182 days) that had been incorrectly nested inside the price-history code path, so it silently went NULL whenever a ticker had no Yahoo price data. Fixed — it's now always computed.
- `last_price_20260630_hkd`: partially recovered via the widget's live current price as a fallback when Yahoo has no history (flagged as "scrape-date price, not literally 30 Jun 2026" since the two are only ~3 days apart here).
- `day1_closing_price_hkd` / `day1_high_hkd` / `day1_low_hkd`: **still genuinely missing** — this needs actual historical daily bars from 9 Jan 2026, which the widget doesn't provide (only current snapshot) and Yahoo doesn't have for this ticker (confirmed in the prior round: `validRanges: ["1d","5d"]` only). Would need a fallback historical-data source (AAStocks/Investing.com) to fill this one company's Day-1 fields.

**Result: Tier-1 fill rate now 93.8%** (up from 92.3%), Tier-2 rose to 23.1% (still capped by the blocked prospectus search).

## 6d. Major update (3 Jul 2026): the document-search blocker was wrong, and three new sources unlocked

The user supplied three additional links and pushed back on the earlier "bot-gated" conclusion for the HKEXnews document search. Re-investigating properly overturned that conclusion and unlocked most of the remaining schema:

**HKEXnews document search is NOT bot-gated.** The original finding (empty JSON from the autocomplete widget) was real, but the conclusion drawn from it was wrong. The actual search is a stateless JSF form POST to `titlesearch.xhtml` with specific field names (`stockId`, `from`, `to`, `title`, etc.) — a plain `requests.post()` with no browser, cookies, or session at all returns full real results. The stock-name-to-internal-ID resolution (`stockId`, a different number from the public stock code) is done via a second plain endpoint, `search/prefix.do`. Rebuilt `hkexnews_docs.py` around this — it's now faster and more reliable than the Playwright approach would have been, and doesn't need a browser at all for this part.

**A1 filing date (§5 gap, now solved):** the user's `app/appindex.html` link led to its backing data file, `app/documents/sehkconsolidatedindex.xlsx` — a downloadable, historical (back to the 1990s) index of every Main Board listing application with a "Date of First Posting" column, status-tagged (Listed/Lapsed/Withdrawn/Rejected/Active). Matched to our IPO population by normalized company name, filtered to `status == 'Listed'`. Reclassified T3 → T1.

**Southbound eligibility (partially solved):** the user's SSE link led to a live JSON query API (`query.sse.com.cn/commonQuery.do`) giving the *current* Shanghai-Connect southbound-eligible securities list — plain `requests`, no auth. Gives a reliable current Yes/No (`southbound_included`, now T1). It does **not** include a "date added" field, so `southbound_inclusion_date` remains unresolved (T3) — would need to mine SSE/SZSE's periodic quarterly-review bulletins to reconstruct historical addition dates, a separate effort. Also note this covers the Shanghai leg only; a Shenzhen-Connect southbound list exists too and wasn't located — likely a small residual gap since eligibility criteria mostly overlap.

**Prospectus / allotment-results / stabilization documents (the big one):** now located reliably via the fixed search, and the actual document *content* matches exactly what the user described — verified against real filings (Fenbi, Cutia Therapeutics, Beijing Luzhu, QuantumPharm). Two distinct filing formats exist across the 2023–2026 window and both are now handled:
- **2022–2023 era**: free-text legal-prose disclosure (e.g. "the Hong Kong Offer Shares... have been over-subscribed... representing approximately 33.88 times").
- **2024+ era**: a cleaner structured "ALLOTMENT RESULTS DETAILS" template with labelled fields (e.g. "Subscription level 103.35 times", "Claw-back triggered Yes"), which is more reliably parseable.

Newly unlocked/improved fields: offer price range, oversubscription multiple, number of valid retail applicants, clawback % triggered, greenshoe/over-allotment exercised, cornerstone investor count/allocation %/lock-up months (two table format variants handled), **Top 1/5/10/20 placee concentration and shareholder concentration %** (found under a "SHAREHOLDING CONCENTRATION ANALYSIS" heading — reclassified T3 → T2), HKEX high-concentration warning flag (detected via the standard boilerplate caution paragraph), Pool A 1-lot allocation rate, and stabilization notice details (net purchases, average price, exercise date) where a notice exists.

Known remaining limitations in this extraction, honestly stated:
- Cornerstone investor **table** extraction is regex-based against two known formats; multi-line-wrapped investor names (e.g. a name that wraps across a PDF line break) can cause a row to be missed — count/total % are more reliable than the full per-investor list.
- `lead_brokers_underwriters` merges the NLR-sourced sponsor list (reliable) with prospectus-parsed bookrunner/lead-manager names (best-effort, validated to reject obviously-wrong header-text matches but not immune to format variance).
- Some very large oversubscription multiples in the pilot (e.g. ~2,300x, ~1,800x for early-2026 tech IPOs) look extreme but are plausible given the documented 2025–2026 Hong Kong IPO demand environment — flagged for a sanity spot-check rather than treated as a bug.

**Result: Tier-1 96.7%, Tier-2 40.5% (up from 23.1%), CALC 84.6%** on the same 8-company pilot.

## 7. Decision, per your direction

- **Tier 2 fields** (ISIN, offer price range, market cap at listing, oversubscription, cornerstone investors, greenshoe, etc.): ship as NULL for this pass. Revisit later if these matter enough to justify either (a) running the scraper from an unrestricted, non-headless environment, or (b) manual/semi-manual link collection that feeds the already-built `pdf_extract.py` regex logic (that part was never blocked — only *finding* the PDFs was).
- **A1 filing date**: NULL across all rows for this pass, dropped rather than reconstructed.
- **Next step**: awaiting your review of `output/hkex_ipo_pilot.csv` and this report before scaling the validated T1/CALC pipeline to the full 331-company population.
