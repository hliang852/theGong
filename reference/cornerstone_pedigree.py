"""
Rule-based classification of cornerstone investor pedigree against a
maintained name list. Applied mechanically to whatever cornerstone investor
names are extracted from the prospectus; flagged in the audit report as
rule-derived, not sourced per-filing.
"""
from __future__ import annotations

GLOBAL_FUNDS = [
    "BlackRock", "Fidelity", "Vanguard", "Capital Group", "Invesco",
    "T. Rowe Price", "Franklin Templeton", "Janus Henderson", "Schroders",
    "abrdn", "Wellington Management", "Baillie Gifford", "Amundi",
]

SOVEREIGN_WEALTH_FUNDS = [
    "GIC", "Temasek", "China Investment Corporation", "CIC", "Qatar Investment Authority",
    "QIA", "Abu Dhabi Investment Authority", "ADIA", "Mubadala", "Kuwait Investment Authority",
    "Norges Bank", "Khazanah", "Hong Kong Monetary Authority", "Exchange Fund",
]

LARGE_COMPANIES = [
    "Tencent", "Alibaba", "Xiaomi", "Meituan", "JD.com", "Baidu", "ByteDance",
    "Huawei", "Ping An", "China Mobile", "CATL", "BYD", "Sinopec", "PetroChina",
    "ICBC", "China Construction Bank", "Country Garden", "COSCO",
]


def classify_cornerstones(names: list[str]) -> dict:
    if not names:
        return {"global_fund": None, "sovereign_wealth": None, "large_company": None}
    joined = " | ".join(names).lower()
    return {
        "global_fund": any(g.lower() in joined for g in GLOBAL_FUNDS),
        "sovereign_wealth": any(s.lower() in joined for s in SOVEREIGN_WEALTH_FUNDS),
        "large_company": any(c.lower() in joined for c in LARGE_COMPANIES),
    }
