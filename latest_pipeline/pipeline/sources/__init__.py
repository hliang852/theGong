"""Importing this package registers every source adapter with base.REGISTRY.

Add a new source by creating `sources/<name>.py` that defines a Source subclass and
calls `register(TheAdapter())`, then importing it here. build.py stays untouched.
"""
from . import hkexnews_a1         # noqa: F401  A1 filings (Application Proofs / PHIPs) — automated
from . import connect_eligibility # noqa: F401  Southbound eligibility changes (SSE diff) — automated
from . import curated             # noqa: F401  rumours + rule/index entries (headline + link + one-liner)
from . import hkex_rules          # noqa: F401  HKEX/SFC rule changes — endpoint pending (curated meanwhile)
from . import index_providers     # noqa: F401  Hang Seng / MSCI / FTSE — endpoint pending (curated meanwhile)
