"""
Rule-based classification of lead broker/underwriter nationality, per user
direction: mechanical lookup against a maintained list, flagged in the audit
report as rule-derived (not sourced per-filing) so it can be spot-checked.
Match is substring/case-insensitive against the sponsor/broker name string
pulled from the NLR report or prospectus cover page.
"""

import re

GLOBAL_INTERNATIONAL_BANKS = [
    "Morgan Stanley", "Goldman Sachs", "J.P. Morgan", "JPMorgan", "Merrill Lynch",
    "Bank of America", "Citigroup", "UBS", "Credit Suisse", "Deutsche Bank",
    "HSBC", "Standard Chartered", "BNP Paribas", "Barclays", "Nomura",
    "Mizuho", "Jefferies",
]

CHINESE_BANKS_AND_SECURITIES = [
    "CICC", "China International Capital Corporation", "CITIC Securities",
    "ICBC International", "CCB International", "China Merchants Bank",
    "CMB International", "Bank of China", "BOCI", "China Renaissance",
    "Haitong International", "GF Securities", "GF Capital", "Guotai Junan",
    "China Securities", "Huatai", "ABC International", "AVIC",
    "Zheshang", "Shenwan Hongyuan", "Essence International", "Zhongtai",
    "Soochow Securities", "China Galaxy",
]


def classify_broker(name: str) -> dict:
    if not name:
        return {"is_global_bank": None, "is_chinese_bank": None, "multiple": None}
    lowered = name.lower()
    parts = [p.strip() for p in re.split(r"[/;,\n]", name) if p.strip()]
    is_global = any(g.lower() in lowered for g in GLOBAL_INTERNATIONAL_BANKS)
    is_chinese = any(c.lower() in lowered for c in CHINESE_BANKS_AND_SECURITIES)
    return {
        "is_global_bank": is_global,
        "is_chinese_bank": is_chinese,
        "multiple": len(parts) > 1,
        "count": len(parts),
    }
