"""Source adapter: HKEX / SFC rule changes (listing rules, consultations, guidance).

Status & rationale (important): unlike HKEXnews A1 filings and the SSE eligible list —
both of which expose clean, stable data endpoints — HKEX's and the SFC's news,
consultation and guidance pages are JavaScript single-page apps whose data comes from
guarded / proxied APIs with no public RSS or stable JSON. Scraping them for a low-touch
daily job would be brittle and break silently.

So rule-change items are handled through the **curated** source for now (an editor adds
the occasional consultation / guidance letter / rule amendment to curated/entries.json
with type "rule" and the right tags — these are low-frequency and benefit from review).
This adapter is the placeholder for a *stable* automated source when one is available:

  candidates to wire here (each returning date + title + canonical url):
    * HKEX Market Consultations   https://www.hkex.com.hk/News/Market-Consultations
    * HKEX Guidance Letters        https://en-rules.hkex.com.hk/  (rulebook update notices)
    * SFC News & Consultations     https://www.sfc.hk/en/News-and-announcements
    * or a licensed regulatory-news API (cleanest, redistribution-safe)

`fetch()` returns [] until one of the above is wired; the interface is final so it drops
straight into the pipeline.
"""
from __future__ import annotations
from ..base import Source, RawItem, register


class HKEXRules(Source):
    name = "HKEX / SFC"
    enabled = True

    def fetch(self) -> list[RawItem]:
        # TODO(source): wire a stable HKEX/SFC endpoint or licensed feed here and map
        # each entry to RawItem(type_hint="rule", date=..., title=..., url=..., entity=...).
        return []


register(HKEXRules())
