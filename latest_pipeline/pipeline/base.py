"""Core types and the Source interface every adapter implements.

A `Source` fetches raw items from one provider; the pipeline normalizes, dedupes,
enriches and merges them. Keeping this contract tiny is what lets a new source be
added as a single self-contained file (see sources/).
"""
from __future__ import annotations
import dataclasses
import datetime as dt
import hashlib
from typing import Optional


@dataclasses.dataclass
class RawItem:
    """What a source adapter yields, before normalization/enrichment."""
    source: str                 # human-readable, e.g. "HKEXnews"
    source_id: str              # provider's own stable id for this document
    date: str                   # YYYY-MM-DD (event/publication date)
    title: str
    url: str
    entity: Optional[str] = None
    stock_code: Optional[str] = None
    type_hint: Optional[str] = None   # a source may already know the type (e.g. A1 listing => "a1")
    raw_text: Optional[str] = None    # optional excerpt used only for enrichment; never republished
    summary: Optional[str] = None     # curator-supplied one-liner (rumours); wins over generated summary


@dataclasses.dataclass
class Item:
    """The canonical, published shape (mirrors schema/latest.schema.json)."""
    id: str
    date: str
    type: str
    title: str
    url: str
    source: str
    tags: list[str]
    entity: Optional[str] = None
    stock_code: Optional[str] = None
    summary: Optional[str] = None
    ingested_at: Optional[str] = None
    confidence: Optional[float] = None

    def to_json(self) -> dict:
        d = dataclasses.asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def make_id(source: str, source_id: str) -> str:
    """Stable dedupe key. Prefer the provider id; hash as a fallback."""
    slug = source.lower().split()[0]
    sid = source_id.strip() or hashlib.sha1(source_id.encode()).hexdigest()[:12]
    return f"{slug}:{sid}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class Source:
    """Adapter interface. One subclass per provider.

    Contract:
      * `name` is the human-readable source label used on the card.
      * `fetch()` returns RawItems and MUST NOT raise for expected failures
        (network hiccups, markup drift) — log and return []. The orchestrator
        isolates each source so one failure never breaks the whole run.
    """
    name: str = "unnamed"
    enabled: bool = True

    def fetch(self) -> list[RawItem]:
        raise NotImplementedError


# --- source registry -------------------------------------------------------
# Adapters register themselves here so build.py stays agnostic of the source list.
REGISTRY: list[Source] = []


def register(source: Source) -> Source:
    REGISTRY.append(source)
    return source
