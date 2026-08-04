"""Enrichment: assign `type`, `tags` (controlled vocabulary only) and a neutral
one-line `summary` to each new item.

Two interchangeable engines behind one function:
  * `RulesEnricher`  — deterministic keyword -> tag mapping + templated summary.
    No external dependency; the always-available fallback.
  * `LLMEnricher`    — a single build-time model call that must return only tags
    from the taxonomy (validated here). Better nuance; needs LLM_API_KEY.

The engine is chosen in build.py; enrichment always degrades to rules on any error,
so a run never fails because the model was unavailable.
"""
from __future__ import annotations
import json
import os
import re
from .base import RawItem, Item, make_id, now_iso

_TAX = json.load(open(os.path.join(os.path.dirname(__file__), "..", "schema", "taxonomy.json")))
ALL_TAGS = {t for f in _TAX["facets"].values() for t in f["tags"]}
ALIASES = _TAX.get("aliases", {})
VALID_TYPES = {t["id"] for t in _TAX["types"]}

# keyword -> canonical tag, for the rules engine and as LLM guardrails
_KEYWORDS = {
    r"\b18a\b|biotech": "Chapter 18A",
    r"\b18c\b|specialist tech": "Chapter 18C",
    r"\b19c\b|secondary listing": "Chapter 19C",
    r"index inclusion|hang seng index|msci|ftse|rebalanc": "Index Inclusion",
    r"southbound": "Southbound",
    r"stock connect|connect eligib": "Connect Eligibility",
    r"\bfini\b|settlement": "FINI",
    r"cornerstone": "Cornerstone",
    r"public float": "Public Float",
    r"\ba\+h\b|a-share|dual[- ]?primary|a-to-h": "A-to-H",
    r"spin-?off": "Spin-off",
    r"\bsecondary listing\b|\s-\s*s\b": "Secondary Listing",
    r"\s-\s*b\b": "Chapter 18A",                          # HKEXnews -B pre-revenue biotech marker
    r"therapeut|pharm|biosci|biotech|life scienc|\bmedical\b|\bhealth": "Biotech / Healthcare",
    r"semiconduct|interconnect|\bchip\b|wafer|integrated circuit": "Semiconductors",
    r"robot": "Robotics",
    r"\bai\b|artificial intelligence|large model|\bllm\b": "AI",
    r"technolog|software|\bdata\b|cloud|internet|network techn|digital": "Technology",
    r"auto|vehicle|\bev\b|mobility|battery|batteries": "Auto / Mobility",
    r"materials|metallic|\bmetal\b|steel|chemical|new energy": "Energy / Materials",
    r"consumer|retail|food|beverage|apparel|restaurant": "Consumer",
    r"\bbank\b|insur|securities|asset manag|fintech|payments": "Financials / Fintech",
    r"listing rule|guidance letter|consultation": "Listing Rules",
}


def _canon(tag: str) -> str | None:
    tag = ALIASES.get(tag.lower(), tag)
    return tag if tag in ALL_TAGS else None


def _valid_tags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        c = _canon(t)
        if c and c not in out:
            out.append(c)
    return out[:8]


class RulesEnricher:
    """Deterministic, dependency-free. Good enough to ship; refined by the LLM engine."""

    def enrich(self, r: RawItem) -> Item:
        text = f"{r.title} {r.entity or ''} {r.raw_text or ''}".lower()
        tags = []
        for pat, tag in _KEYWORDS.items():
            if re.search(pat, text) and tag not in tags:
                tags.append(tag)
        typ = r.type_hint if r.type_hint in VALID_TYPES else _infer_type(text)
        summary = r.summary or _template_summary(r, typ)   # curator one-liner wins
        return _assemble(r, typ, _valid_tags(tags), summary, confidence=0.5)


_SYSTEM = (
    "You classify Hong Kong IPO and listing-related news items for a research feed. "
    "Return STRICT JSON only, no prose. Use a neutral, factual tone. Never copy the "
    "source's wording verbatim; write an original one-to-two sentence summary."
)


def _prompt(r: RawItem) -> str:
    return (
        f"Item:\n"
        f"- title: {r.title}\n"
        f"- entity: {r.entity or ''}\n"
        f"- source: {r.source}\n"
        f"- source suggests type: {r.type_hint or 'unknown'}\n"
        f"- excerpt: {(r.raw_text or '')[:800]}\n\n"
        f"Allowed types: {sorted(VALID_TYPES)}\n"
        f"Allowed tags (choose 1-6, ONLY from this list): {sorted(ALL_TAGS)}\n\n"
        "Respond as JSON: {\"type\": <one type>, \"tags\": [<tags>], "
        "\"summary\": <=2 neutral sentences, \"confidence\": 0..1}"
    )


class LLMEnricher:
    """One build-time chat-completions call, constrained to the taxonomy and validated
    here. Provider-agnostic (OpenAI-compatible endpoint). Falls back to rules on any error.

    Env:  LLM_API_KEY (required), LLM_API_BASE (default OpenAI), LLM_MODEL.
    """

    def __init__(self, api_key: str | None):
        self.api_key = api_key
        self.base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._fallback = RulesEnricher()

    def enrich(self, r: RawItem) -> Item:
        if not self.api_key:
            return self._fallback.enrich(r)
        try:
            import requests
            resp = requests.post(
                f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": _prompt(r)},
                    ],
                },
                timeout=40,
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["choices"][0]["message"]["content"])
            typ = data.get("type") if data.get("type") in VALID_TYPES else (r.type_hint or "rule")
            tags = _valid_tags(data.get("tags", []))
            summary = r.summary or (data.get("summary") or _template_summary(r, typ))
            conf = float(data.get("confidence", 0.8))
            return _assemble(r, typ, tags, summary, confidence=conf)
        except Exception:
            return self._fallback.enrich(r)


def _infer_type(text: str) -> str:
    if "application proof" in text or re.search(r"\ba1\b", text):
        return "a1"
    if any(w in text for w in ("consultation", "guidance letter", "rule", "eligib", "index")):
        return "rule"
    if any(w in text for w in ("said to", "reported", "considering", "mulls", "weighs")):
        return "rumor"
    return "rule"


def _template_summary(r: RawItem, typ: str) -> str:
    if typ == "a1":
        return f"{r.entity or 'The company'} submitted an application proof to list on the Hong Kong Main Board."
    if typ == "rumor":
        return f"{r.entity or 'A company'} is reported to be considering a Hong Kong listing; no filing has been confirmed."
    return r.title


def _assemble(r: RawItem, typ: str, tags: list[str], summary: str, confidence: float) -> Item:
    return Item(
        id=make_id(r.source, r.source_id),
        date=r.date, type=typ, title=r.title, url=r.url, source=r.source,
        entity=r.entity, stock_code=r.stock_code, tags=tags, summary=summary,
        ingested_at=now_iso(), confidence=confidence,
    )


def get_enricher(engine: str, api_key: str | None):
    return LLMEnricher(api_key) if engine == "llm" else RulesEnricher()
