"""Source adapter: index-inclusion changes (Hang Seng, MSCI, FTSE Russell).

Status & rationale: the index providers publish review results and consultations as
press releases on JavaScript SPA sites (Hang Seng Indexes) or behind licensing (MSCI,
FTSE). There is no clean public feed suitable for an unattended daily job, so
index-inclusion items are **curated** for now (an editor adds each quarterly review
outcome / consultation to curated/entries.json with type "rule" and tag "Index
Inclusion"). Index reviews are quarterly and few — a good fit for editorial review.

This adapter is the plug-in point for a stable/licensed source when available:

  candidates to wire here:
    * Hang Seng Indexes announcements   https://www.hsi.com.hk/eng/index-announcements
    * HSI index-change press releases    (quarterly review results)
    * MSCI / FTSE review notices          (licensed data)

`fetch()` returns [] until wired; the interface is final.
"""
from __future__ import annotations
from ..base import Source, RawItem, register


class IndexProviders(Source):
    name = "Index providers"
    enabled = True

    def fetch(self) -> list[RawItem]:
        # TODO(source): map each index announcement to
        # RawItem(type_hint="rule", date=..., title=..., url=..., entity="Hang Seng Indexes", ...)
        return []


register(IndexProviders())
