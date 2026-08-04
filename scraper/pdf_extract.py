"""
Regex extraction from HKEX IPO filing text: prospectus ("Listing Documents -
[Offer for Subscription]"), allotment results Summary sub-document, and
stabilization notices. Calibrated against real filings (Fenbi 02469, Cutia
Therapeutics 02487) fetched via hkexnews_docs.py.

These are pattern matches against free-text legal-template disclosure, not a
structured API -- every extracted value is a candidate for human spot-check,
not ground truth. Functions return None (-> NULL in the final CSV) rather
than guessing when a pattern isn't found.
"""
from __future__ import annotations
import re
import pandas as pd

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _to_int(s):
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ---------------- Prospectus ("Listing Documents - Offer for Subscription") ----------------

def extract_offer_price_range(text: str):
    # newer (2024+) structured "Company information" summary format
    m = re.search(r"Offer Price Range\s*HK\$\s*([\d.]+)\s*-\s*HK\$\s*([\d.]+)", text, re.I)
    if m:
        return _to_float(m.group(1)), _to_float(m.group(2))
    # older free-text prospectus format: "HK$X to HK$Y per (Offer/H) Share"
    m = re.search(r"HK\$\s*([\d.]+)\s*to\s*HK\$\s*([\d.]+)\s*per\s*(?:Offer\s*|H\s*)?Share", text, re.I)
    if m:
        return _to_float(m.group(1)), _to_float(m.group(2))
    # "Offer Price : Not more than HK$Y per Offer Share and expected to be
    # (subject to a Downward Offer Price Adjustment) not less than HK$X per
    # Offer Share" -- high bound stated first, low bound second, with an
    # optional parenthetical clause wedged in between (28% of the 331-company
    # universe's prospectuses use this phrasing, found only at full scale --
    # the 8-company pilot sample happened not to include one).
    m = re.search(
        r"Not more than\s*HK\$\s*([\d.]+)\s*per\s*(?:Offer\s*|H\s*)?Share.{0,100}?"
        r"not less than\s*HK\$\s*([\d.]+)\s*per",
        text, re.I | re.S,
    )
    if m:
        return _to_float(m.group(2)), _to_float(m.group(1))  # (low, high)
    # "being HK$X per Share to HK$Y" / "HK$X per H Share to HK$Y" -- same
    # low-to-high range as the pattern above, but with the "per Share" unit
    # sitting between the two numbers instead of after both.
    m = re.search(r"HK\$\s*([\d.]+)\s*per\s*(?:Offer\s*|H\s*)?Share\s*to\s*HK\$\s*([\d.]+)", text, re.I)
    if m:
        return _to_float(m.group(1)), _to_float(m.group(2))
    # fixed single Offer Price, no range at all (this was actually the most
    # common of the previously-NULL cases: ~28% of the full universe) --
    # "Offer Price : HK$X per Share" with no "Maximum"/"Not more than"
    # qualifier before it. Represented as a range of one point (low == high)
    # rather than left NULL, since that's literally what was offered.
    # "per Share" doesn't always follow immediately (sometimes it's just
    # "Offer Price : HK$13.50, plus brokerage..."), so it's optional here.
    m = re.search(r"(?<!Maximum )(?<!maximum )Offer Price\s*:?\s*HK\$\s*([\d.]+)(?:\s*per\s*(?:Offer\s*|H\s*)?Share)?", text)
    if m:
        price = _to_float(m.group(1))
        return price, price
    return None, None


def extract_final_offer_price(text: str):
    m = re.search(r"Final Offer Price\s*HK\$\s*([\d.]+)", text, re.I)
    return _to_float(m.group(1)) if m else None


def extract_max_offer_price(text: str):
    """Cover-page 'Maximum Offer Price' cap -- e.g. 'Maximum Offer Price :
    HK$31.00 per Offer Share plus brokerage of...'. Some offerings (e.g.
    TUHU) only ever disclose this cap publicly, with no separate low-high
    range anywhere in the prospectus or allotment announcement.

    Two variants seen at full scale: a parenthetical qualifier can wedge
    itself between the label and the colon (pdfplumber column jumbling --
    "Maximum Offer Price (subject to a : HK$14.0 per H Share ... Downward
    Offer Price Adjustment)"), and depositary-receipt listings use "HDR"
    instead of "Share" as the unit."""
    m = re.search(r"Maximum Offer Price.{0,40}?:\s*HK\$\s*([\d.]+)\s*per\s*(?:Offer\s*|H\s*)?(?:Share|HDR)", text, re.I | re.S)
    if m:
        return _to_float(m.group(1))
    lo, hi = extract_offer_price_range(text)
    return hi


def extract_global_offering_shares(text: str):
    """Returns dict: shares_global_offering, shares_hk_offer, shares_intl_offer,
    from the prospectus cover page. Real cover pages vary in phrasing --
    "Total number of Offer Shares under : X Shares / the Global Offering"
    (label wraps around the value), "Number of Offer Shares under the
    Global Offering : X Offer Shares", "Number of Offer Shares under the :
    X H Shares" (with "Global Offering" landing on the next wrapped line
    entirely, jumbled by pdfplumber's column layout) -- all share the same
    "...Offer Shares under (the) (Global Offering) : X (H/Offer) Shares"
    skeleton with different optional pieces present."""
    out = {"shares_global_offering": None, "shares_hk_offer": None, "shares_intl_offer": None}
    m = re.search(
        r"(?:Total\s+)?[Nn]umber of Offer Shares under(?:\s+the)?(?:\s+Global Offering)?\s*:\s*"
        r"([\d,]{6,})\s*(?:H\s+)?(?:Offer\s+)?Shares",
        text,
    )
    if m:
        out["shares_global_offering"] = _to_int(m.group(1))
    m = re.search(r"([\d,]{5,})\s*(?:H\s+)?Hong Kong Offer Shares", text, re.I)
    if m:
        out["shares_hk_offer"] = _to_int(m.group(1))
    m = re.search(r"([\d,]{5,})\s*(?:H\s+)?International Offer Shares", text, re.I)
    if m:
        out["shares_intl_offer"] = _to_int(m.group(1))
    return out


def extract_sponsors_and_banks(text: str):
    """Returns dict of role -> raw text block (Sponsor / Bookrunner / Lead Manager),
    from the prospectus cover-page block. Each may contain multiple firm names
    separated by newlines/semicolons -- left as raw text for downstream
    broker-nationality classification, not split here."""
    out = {}
    patterns = {
        "sponsor": r"(?:Sole\s+Sponsor|Joint\s+Sponsors?)\s*[:\n]?\s*([A-Z][^\n]{5,300})",
        "bookrunner": r"Joint\s+Bookrunners?\s*[:\n]?\s*([A-Z][^\n]{5,300})",
        "lead_manager": r"Joint\s+Lead\s+Managers?\s*[:\n]?\s*([A-Z][^\n]{5,300})",
        "overall_coordinator": r"Joint\s+Overall\s+Coordinators?\s*[:\n]?\s*([A-Z][^\n]{5,300})",
    }
    role_words = re.compile(r"\b(sponsor|coordinator|bookrunner|lead manager|underwriter)s?\b", re.I)
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            candidate = m.group(1).strip()
            # reject captures that are themselves role-label text (happens when
            # a prospectus lists multiple role headings together before the
            # actual firm names, e.g. "Joint Sponsors, Joint Bookrunners" as
            # one combined heading) -- better NULL than a garbage value
            if not role_words.search(candidate):
                out[key] = candidate
    return out


def extract_total_shares_in_issue(text: str):
    m = re.search(r"([\d,]{6,})\s+Shares\s+(?:will be|are expected to be|in issue)", text, re.I)
    if m:
        return _to_int(m.group(1))
    return None


def extract_number_of_offer_shares(text: str):
    """Total shares actually sold in the IPO (HK Offer + International Offer
    tranches combined) -- from the 2024+ structured allotment-results format:
    'Number of Offer Shares 187,373,000' (also seen abbreviated as 'No. of
    Offer Shares under the : 144,974,000 H Shares', where pdfplumber's
    column extraction jumbles the wrapped 'Global Offering' sub-label after
    the number). Both patterns are tightly anchored -- no greedy wildcard
    between the label and the digits -- specifically to avoid matching into
    unrelated free-text sentences like '...the final number of Offer Shares
    under the International Offering is 14,000,000...' in older filings."""
    m = re.search(r"(?:Number|No\.) of Offer Shares\s+([\d,]{6,})", text)
    if m:
        return _to_int(m.group(1))
    m = re.search(r"(?:Number|No\.) of Offer Shares under the\s*:?\s*([\d,]{6,})", text, re.I)
    if m:
        return _to_int(m.group(1))
    return None


def extract_shares_upon_listing(text: str):
    """Post-IPO total issued shares. Tries, in order:
    1. 2024+ structured format: 'Number of issued shares upon Listing
       (Assuming the Over-allotment Option is not exercised) 3,406,772,761'
       (also seen abbreviated as 'No. of issued shares upon Listing 579,894,000').
    2. Older free-text format's SUMMARY paragraph (e.g. TUHU): 'the total
       issued share capital of the Company upon Listing (taking into
       account ...various parenthetical qualifiers...) will be 814,371,439
       Shares.'
    3. Older free-text format's PUBLIC FLOAT paragraph, which discloses an
       absolute share count together with its percentage of total issued
       share capital but never states the total directly (e.g. Fenbi:
       'an aggregate of 821,614,000 Shares or approximately 39.2% of the
       issued share capital ... will be held in the hands of the public') --
       back the total out via shares / (pct / 100). This is a genuine
       document-derived figure (not a Yahoo approximation), just requires
       one division; kept separate from tiers 1-2 since it's less precise
       (the disclosed percentage is rounded to 1 decimal place)."""
    m = re.search(r"(?:Number|No\.) of issued shares upon Listing.{0,80}?([\d,]{6,})", text, re.I | re.S)
    if m:
        return _to_int(m.group(1))
    m = re.search(
        r"total issued share capital of the Company upon Listing.{0,300}?will be\s+([\d,]{6,})\s+Shares",
        text, re.I | re.S,
    )
    if m:
        return _to_int(m.group(1))
    m = re.search(
        r"([\d,]{6,})\s+Shares,?\s*(?:or\s+)?(?:representing\s+)?approximately\s+([\d.]+)%\s+of\s+the\s*"
        r"(?:total\s+)?issued share capital",
        text, re.I,
    )
    if m:
        shares, pct = _to_int(m.group(1)), _to_float(m.group(2))
        if shares and pct:
            return round(shares / (pct / 100))
    return None


# ---------------- Allotment Results Summary ----------------

def extract_oversubscription(text: str):
    """Times oversubscribed, Hong Kong Public Offering (retail tranche)."""
    # newer (2024+) structured "ALLOTMENT RESULTS DETAILS" format
    m = re.search(r"Subscription level\s+([\d,.]+)\s*times", text, re.I)
    if m:
        return _to_float(m.group(1))
    # older free-text prospectus-era format
    m = re.search(r"total of\s+([\d,]+)\s+valid applications.{0,300}?representing approximately\s+([\d.]+)\s*times", text, re.I | re.S)
    if m:
        return _to_float(m.group(2))
    m = re.search(r"Hong Kong (?:Offer Shares|Public Offering).{0,200}?over-?subscribed.{0,300}?approximately\s+([\d.]+)\s*times", text, re.I | re.S)
    if m:
        return _to_float(m.group(1))
    return None


def extract_intl_oversubscription(text: str):
    m = re.search(r"International Offering.{0,150}?over-?subscribed.{0,150}?approximately\s+([\d.]+)\s*times", text, re.I | re.S)
    if m:
        return _to_float(m.group(1))
    return None


def extract_num_valid_retail_applicants(text: str):
    m = re.search(r"No\.\s*of valid applications\s+([\d,]+)", text, re.I)
    if m:
        return _to_int(m.group(1))
    m = re.search(r"total of\s+([\d,]+)\s+valid applications", text, re.I)
    if m:
        return _to_int(m.group(1))
    return None


def extract_num_placees(text: str):
    m = re.search(r"No\.\s*of placees\s+([\d,]+)", text, re.I)
    if m:
        return _to_int(m.group(1))
    m = re.search(r"total of\s+([\d,]+)\s+placees\s+under\s+the\s+International\s+Offering", text, re.I)
    if m:
        return _to_int(m.group(1))
    return None


def extract_clawback(text: str):
    """Returns dict: clawback_triggered (bool), final_hk_offer_pct (float),
    mechanism_description (str) -- based on the standard HKEX clawback
    disclosure paragraph triggered by the oversubscription tier reached.

    The retail tranche is labelled "Hong Kong Public Offering" in most
    filings but "Public Offer" in some (e.g. Biren, MiniMax) -- patterns
    below accept either via a shared alternation.
    """
    out = {"clawback_triggered": None, "final_hk_offer_pct": None, "mechanism_description": None}
    # A label PREFIX, not the full phrase: pdfplumber sometimes jumbles these
    # table cells so the number lands mid-label (e.g. "under the Hong Kong
    # Public 9,369,000\nOffering", with "Offering" pushed after the number),
    # so requiring the full "...Public Offering" phrase intact before the
    # number would miss it. Matching just the stable prefix and then hunting
    # for the number in a short following window is robust to either order.
    RETAIL = r"(?:Hong Kong Public|Public Offer)"

    # newer (2024+) structured "ALLOTMENT RESULTS DETAILS" format
    m = re.search(r"Claw-?back triggered\s+(Yes|No)", text, re.I)
    if m:
        out["clawback_triggered"] = m.group(1).strip().lower() == "yes"
    m2 = re.search(rf"% of Offer Shares under the {RETAIL}.{{0,20}}?to the.{{0,60}}?([\d.]+)%", text, re.I | re.S)
    if m2:
        out["final_hk_offer_pct"] = _to_float(m2.group(1))
    if out["clawback_triggered"] is not None:
        initial = re.search(rf"No\.? of Offer Shares initially available under the {RETAIL}.{{0,20}}?([\d,]{{4,}})", text, re.I | re.S)
        realloc = re.search(r"No\.? of Offer Shares reallocated from the International (?:Offering|Offer|Placing).{0,25}?([\d,]{4,})", text, re.I | re.S)
        final = re.search(rf"Final no\.? of Offer Shares under the {RETAIL}.{{0,40}}?([\d,]{{4,}})", text, re.I | re.S)
        if out["clawback_triggered"] and realloc:
            # "retail tranche" instead of guessing the exact defined term
            # ("Hong Kong Public Offering" vs "Public Offer") -- both labels
            # tend to appear somewhere in every filing (e.g. boilerplate
            # cross-references), so a whole-doc substring check isn't a
            # reliable way to tell which one is *this* filing's actual name.
            desc = f"{_to_int(realloc.group(1)):,} Offer Shares reallocated from the International Offering to the retail tranche via clawback"
            if initial and final:
                desc += f" ({_to_int(initial.group(1)):,} -> {_to_int(final.group(1)):,} Shares)"
            if out["final_hk_offer_pct"] is not None:
                desc += f", {out['final_hk_offer_pct']}% of the Global Offering"
            out["mechanism_description"] = desc
        elif out["clawback_triggered"] is False:
            out["mechanism_description"] = "Claw-back not triggered (subscription level below the reallocation threshold)"
        return out

    # older free-text prospectus-era format. The gap between "reallocation
    # procedure(s)" and "has/have (not) been applied" is often 100-150 chars
    # (a parenthetical cross-reference to the "Structure of the Global
    # Offering" section), so these need a wide window, not a short one.
    m = re.search(r"reallocation procedures?.{0,250}?has been applied and\s+([\d,]+)\s+Offer\s+Shares\s+have been reallocated", text, re.I | re.S)
    if m:
        out["clawback_triggered"] = True
        out["mechanism_description"] = f"{_to_int(m.group(1)):,} Offer Shares reallocated from the International Offering to the Hong Kong Public Offering via clawback"
    elif re.search(r"reallocation procedures?.{0,250}?(?:have not been applied|has not been applied|no reallocation)", text, re.I | re.S):
        out["clawback_triggered"] = False
        out["mechanism_description"] = "Claw-back/reallocation procedure not applied (over-subscription below the reallocation threshold)"
    m2 = re.search(
        r"final number of (?:the\s+)?(?:Hong Kong\s+)?Offer Shares(?:\s+under the Hong Kong Public Offering)?\s+"
        r"(?:has\s+been\s+increased\s+to|is)\s+[\d,]+\s+(?:H\s+)?(?:Offer\s+)?Shares,?\s*representing\s+(?:approximately\s+)?([\d.]+)%",
        text, re.I | re.S,
    )
    if m2:
        out["final_hk_offer_pct"] = _to_float(m2.group(1))
    return out


def extract_cornerstone_investors(text: str):
    """Returns list of dicts: {name, investment_amount_usd, shares, pct_of_shares}
    from the cornerstone allocation table, plus overall count/allocation pct.
    Table rows look like:
      'Harvest 20,000,000 7,158,600 33.64% 32.36% 2.35% 2.35%'
    (Name, USD amount, shares, %-of-cornerstone-tranche x2, %-of-total-shares-in-issue x2)
    We take the SMALLER of the two %-of-total-shares-in-issue figures (with/
    without over-allotment exercised) per the user's instruction to use the
    smaller number / larger denominator.

    Bounded to end BEFORE the separate "Top 1/5/10/20/25" placee/shareholder
    concentration tables (extract_top_concentration), which have a similar
    row shape and would otherwise bleed into this match.
    """
    investors = []
    # variant A (2022/2023-era prospectus format): Name, USD amount, shares, 4 pct columns
    table_section = re.search(
        r"Cornerstone Investors \(US\$\).{0,80}?exercised\)\s*(.*?)"
        r"(?:\n\s*\n|The aggregate|Save as disclosed|SHAREHOLDING CONCENTRATION|Top 1[, ])",
        text, re.S)
    block = table_section.group(1) if table_section else ""
    row_re = re.compile(
        r"([A-Z][A-Za-z0-9 .,()&'\-]{2,60}?)\s+([\d,]{6,})\s+([\d,]{4,})\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%"
    )
    for m in row_re.finditer(block):
        name, amount, shares, pct1, pct2, pct3, pct4 = m.groups()
        if name.strip().lower() in ("top", "total"):
            continue
        pcts_of_total = [p for p in (_to_float(pct3), _to_float(pct4)) if p is not None]
        investors.append({
            "name": name.strip(),
            "investment_amount_usd": _to_float(amount),
            "shares": _to_int(shares),
            "pct_of_total_shares_in_issue": min(pcts_of_total) if pcts_of_total else None,
        })

    # variant B (2024+ structured format): Name, shares, % of Offer Shares,
    # % of total issued share capital, Existing-shareholder Yes/No -- no USD column
    if not investors:
        table_section_b = re.search(
            r"Cornerstone Investors\s*.*?exercised\)\s*(.*?)(?:Note\s*1|SHAREHOLDING CONCENTRATION|Top 1[, ]|LOCK-UP)",
            text, re.S)
        block_b = table_section_b.group(1) if table_section_b else ""
        row_re_b = re.compile(
            r"([A-Z][A-Za-z0-9 .,()&'’\-]{2,70}?)\s+([\d,]{5,})\s+([\d.]+)%\s+([\d.]+)%\s+(Yes|No)"
        )
        for m in row_re_b.finditer(block_b):
            name, shares, pct_offer, pct_total, existing = m.groups()
            if name.strip().lower() in ("top", "total", "investor"):
                continue
            investors.append({
                "name": name.strip(),
                "investment_amount_usd": None,
                "shares": _to_int(shares),
                "pct_of_total_shares_in_issue": _to_float(pct_total),
            })

    total_pct_m = re.search(r"Cornerstone Investors has subscribed for a total of\s+[\d,]+\s+Offer Shares,\s*representing\s*\(a\)\s*approximately\s+([\d.]+)%", text, re.I)
    total_pct = _to_float(total_pct_m.group(1)) if total_pct_m else None

    count = len(investors) if investors else None
    if count is None:
        m = re.search(r"(\w+)\s+cornerstone investors?", text, re.I)
        if m and m.group(1).lower() in NUM_WORDS:
            count = NUM_WORDS[m.group(1).lower()]

    return {"investors": investors, "count": count, "total_pct_of_shares_in_issue": total_pct}


def extract_top_concentration(text: str, kind: str):
    """kind: 'placees' or 'shareholders'. Returns dict top1/top5/top10/top20
    -> % of total issued share capital upon listing (smaller of the
    not-exercised/exercised-over-allotment figures, i.e. larger denominator,
    per user instruction). Table format (both tables share this row shape):
      'Top 1 7,158,600 7,158,600 37.38% 35.80% 33.64% 32.36% 2.35% 2.35%'
    last two %-columns are the ones we want; en-dashes ('–') stand for 0."""
    if kind == "placees":
        header_pat = r"of the placees in the International Offering"
        end_pat = r"Shareholders upon Listing|Notes:"
    else:
        header_pat = r"Shareholders upon Listing"
        end_pat = r"Notes:"
    section = re.search(header_pat + r":?\s*(.*?)(?:" + end_pat + r"|\Z)", text, re.S)
    if not section:
        return {}
    block = section.group(1)
    row_re = re.compile(
        r"Top (1|5|10|20)\s+[\d,–\-]+\s+[\d,–\-]+\s+[\d.]+%\s+[\d.]+%\s+[\d.]+%\s+[\d.]+%\s+([\d.]+)%\s+([\d.]+)%"
    )
    out = {}
    for m in row_re.finditer(block):
        n, pct_a, pct_b = m.groups()
        vals = [_to_float(pct_a), _to_float(pct_b)]
        vals = [v for v in vals if v is not None]
        if vals:
            out[f"top{n}_pct"] = min(vals)
    return out


def extract_high_concentration_flag(text: str) -> bool:
    return bool(re.search(r"high concentration of shareholding.{0,60}should\s+(?:be\s+aware|exercise\s+extreme\s+caution)", text, re.I | re.S))


def extract_cornerstone_lockup_months(text: str):
    if re.search(r"Cornerstone Investors?.{0,200}?period of six months from the Listing Date", text, re.I | re.S):
        return 6
    if re.search(r"Cornerstone Investors?.{0,200}?period of twelve months from the Listing Date", text, re.I | re.S):
        return 12
    return None


def extract_placee_concentration(text: str):
    """Returns dict with the two standard placee-concentration disclosures
    HKEX requires (5-board-lot-or-less tier and 1-board-lot tier), each as
    (num_placees, pct_of_placees, shares, pct_of_offer_shares)."""
    out = {}
    m = re.search(
        r"total of\s+([\d,]+)\s+placees\s+have\s+been\s+allotted\s+five\s+board\s+lots.{0,40}?representing\s+approximately\s+([\d.]+)%\s+of\s+([\d,]+)\s+placees.{0,300}?allotted\s+([\d,]+)\s+Offer Shares,\s*representing\s+approximately\s+([\d.]+)%",
        text, re.I | re.S)
    if m:
        out["placees_5_lots_or_less_count"] = _to_int(m.group(1))
        out["placees_5_lots_or_less_pct_of_placees"] = _to_float(m.group(2))
        out["placees_5_lots_or_less_shares"] = _to_int(m.group(4))
        out["placees_5_lots_or_less_pct_of_offer_shares"] = _to_float(m.group(5))
    m2 = re.search(
        r"total of\s+([\d,]+)\s+placees\s+have\s+been\s+allotted\s+one\s+board\s+lot.{0,300}?representing\s+approximately\s+([\d.]+)%\s+of\s+([\d,]+)\s+placees.{0,300}?allotted\s+([\d,]+)\s+Offer Shares,\s*representing\s+approximately\s+([\d.]+)%",
        text, re.I | re.S)
    if m2:
        out["placees_1_lot_count"] = _to_int(m2.group(1))
        out["placees_1_lot_pct_of_placees"] = _to_float(m2.group(2))
        out["placees_1_lot_shares"] = _to_int(m2.group(4))
        out["placees_1_lot_pct_of_offer_shares"] = _to_float(m2.group(5))
    return out


def extract_hk_1lot_allocation_rate(text: str):
    """Pool A smallest-tier allocation rate, from the BASIS OF ALLOCATION /
    BASIS OF ALLOTMENT table every allotment-results announcement carries.

    Calibrated against a 12-doc sample spanning 2023-2026 formats: the table
    always lists tiers smallest-first under a "POOL A" marker, and the FIRST
    percentage figure after that marker is the smallest tier's "approximate
    percentage allotted of the total number of shares applied for" -- which
    for a 1-lot application equals the probability of receiving the lot.
    This holds even when pdfplumber jumbles the wrapped ballot text ("10,518
    out of\\n100 105,175 105,175 to receive 10.00%\\n100 Shares"), because the
    trailing percentage still lands at the end of the row chunk, and none of
    the observed column-header blocks between "POOL A" and the first row
    contain a literal '%' character.

    Falls back to the pre-existing narrow sentence pattern for the rare
    free-text phrasing, then None."""
    # The phrase "basis of allocation/allotment" also appears in prose
    # (expected-timetable, summary paragraphs), so a naive first-occurrence
    # match can land there and grab an unrelated percentage. Two passes:
    # first exhaust every header occurrence looking for one followed by a
    # "POOL A" marker (the actual table); only if NO occurrence anywhere has
    # one (single-pool tables) fall back to windows showing the table's own
    # column-header vocabulary.
    headers = list(re.finditer(r"BASIS OF ALLO(?:CATION|TMENT)", text, re.I))
    for m in headers:
        seg = text[m.end():m.end() + 3000]
        pa = re.search(r"POOL A", seg, re.I)
        if not pa:
            continue
        sub = seg[pa.end():pa.end() + 700]
        pm = re.search(r"(\d{1,3}(?:\.\d+)?)%", sub)
        if pm:
            val = _to_float(pm.group(1))
            if val is not None and 0 < val <= 100:
                return val
        # some tables omit the % sign entirely (bare "1.00" in the rate
        # column) -- compute the rate from the first row's ballot fraction
        # instead: "354 OUT OF 35,303 applicants to receive ..."
        bm = re.search(r"([\d,]+)\s+out of\s+([\d,]+)\s+(?:applicants\s+)?to receive", sub, re.I)
        if bm:
            won, total = _to_int(bm.group(1)), _to_int(bm.group(2))
            if won and total and won <= total:
                return round(won / total * 100, 2)
    for m in headers:
        seg = text[m.end():m.end() + 3000]
        if not re.search(r"ballot|applied for", seg[:600], re.I):
            continue
        pm = re.search(r"(\d{1,3}(?:\.\d+)?)%", seg[:1200])
        if pm:
            val = _to_float(pm.group(1))
            if val is not None and 0 < val <= 100:
                return val
    m = re.search(r"total number of successful applicants under the Hong Kong Public Offering is\s+([\d,]+),\s*among which\s+([\d,]+)\s+Shareholders were allocated with one board lot", text, re.I)
    if m:
        total = _to_int(m.group(1))
        one_lot = _to_int(m.group(2))
        if total:
            return round(one_lot / total * 100, 2)
    return None


def extract_lockup_periods(text: str):
    """Best-effort: pulls the free-text 'LOCK-UP UNDERTAKINGS' section (may
    span controlling shareholders / directors / cornerstone investors with
    different periods) as a single descriptive string rather than trying to
    fully structure it -- lock-up terms vary too much in phrasing per filing
    to reliably tabulate automatically."""
    m = re.search(r"LOCK-UP UNDERTAKINGS\s*(.{100,1500}?)(?:BASIS OF ALLOCATION|CONDITIONS OF THE|$)", text, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


# ---------------- Stabilization notices ----------------

def extract_stabilization_details(text: str):
    """Parses a "STABILIZING ACTIONS AND END OF STABILIZATION PERIOD" notice.

    Real filings never state a literal "average price" -- they disclose
    either a price range ("in the price range of HK$X to HK$Y ... on the
    market") or a single price ("at the price of HK$X per Share ... on the
    market") for the on-market purchases. avg_price_hkd is therefore the
    midpoint of the disclosed range (or the single price when only one is
    given) -- a computed figure, not a quoted one.

    When the notice explicitly states no on-market purchase/sale occurred
    (common when the over-allotment was covered entirely by borrowed/newly
    issued shares, e.g. MiniMax/Biren), net_purchases_shares is 0, not None.
    """
    out = {"broker": None, "net_purchases_shares": None, "avg_price_hkd": None, "last_exercise_date": None}
    # pdfplumber line-wraps mid-phrase ("China International Capital\nCorporation
    # Hong Kong Securities Limited"); collapse all whitespace so multi-word
    # names and "in connection with\nthe Global Offering"-style wraps match
    # as single-space text instead of silently failing on the raw newlines.
    norm = re.sub(r"\s+", " ", text)

    # Stabilizing Manager name -- either "undertaken by NAME, the/as the
    # Stabili[sz](ing|ation) Manager" (most common), or "NAME (the Stabili...
    # Manager)" (seen when the name is introduced earlier via the Stock
    # Borrowing Agreement paragraph, e.g. QuantumPharm/CLSA). Some notices
    # (e.g. Cutia) never name the manager at all -- broker stays None.
    m = re.search(
        r"undertaken by\s+([A-Z][A-Za-z0-9.,()&’'\-\s]{2,80}?),?\s+(?:as\s+)?(?:the\s+)?"
        r"Stabili[sz](?:ing|ation)\s+Manager",
        norm,
    )
    if not m:
        m = re.search(
            r"([A-Z][A-Za-z0-9.,()&’'\-\s]{2,80}?)\s*\(the Stabili[sz](?:ing|ation)\s+Manager\)",
            norm,
        )
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",")
        if name and "stabili" not in name.lower():
            out["broker"] = name

    # End of stabilization period date -- this IS the "last exercise date":
    # stabilizing actions can only occur during the (fixed-length) stabilization
    # period, so its end date is the latest date any action could have happened.
    m = re.search(
        r"stabili[sz]ation period in connection with the Global Offering\s+ended on\s+"
        r"(?:[A-Za-z]+,\s*)?(.+?),\s+being the 30th day",
        norm, re.I,
    )
    if m:
        raw = m.group(1).strip()
        try:
            out["last_exercise_date"] = pd.to_datetime(raw).date()
        except Exception:
            out["last_exercise_date"] = raw

    # On-market purchases during the stabilization period. Anchored tightly
    # ("...Shares in/at the price..." immediately after the share count) so
    # it can't skip past an unrelated intervening number to a later "on the
    # market" phrase elsewhere in the notice (e.g. QuantumPharm's borrowed-
    # shares paragraph, which is not itself a market purchase).
    m = re.search(
        r"purchases? of an aggregate of ([\d,]+)\s+(?:Class A |Class B |H )?Shares\s+"
        r"(?:in the price range of|at the price of)\s+HK\$[\d.]+(?:\s+to\s+HK\$[\d.]+)?"
        r".{0,200}?on the market",
        norm, re.I,
    )
    if m:
        out["net_purchases_shares"] = _to_int(m.group(1))
        span = m.group(0)
        rng = re.search(r"HK\$([\d.]+)\s+to\s+HK\$([\d.]+)", span)
        if rng:
            out["avg_price_hkd"] = round((float(rng.group(1)) + float(rng.group(2))) / 2, 4)
        else:
            single = re.search(r"at the price of\s+HK\$([\d.]+)", span)
            if single:
                out["avg_price_hkd"] = _to_float(single.group(1))
    elif re.search(r"no purchase or sale of any .{0,40}Shares on the market", norm, re.I):
        out["net_purchases_shares"] = 0

    return out
