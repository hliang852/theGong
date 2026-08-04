"""
Reads IPO document text from the local PDF corpus (output/pdfs/{stock_code}/)
built by download_docs.py, instead of re-querying HKEXnews over the network
on every extraction run. Manifest-driven -- output/pdf_manifest_pilot.csv
records which local file corresponds to which document type/headline for
each company, already resolved past any .htm index page to the actual
Summary PDF (see hkexnews_docs.resolve_htm_to_summary_pdf).

Falls back to None (caller decides whether to hit the network) when a
company/doc_type has no downloaded file -- this module never makes HTTP
requests itself.
"""
from __future__ import annotations
from pathlib import Path

import pandas as pd
import pdfplumber

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
PILOT_MANIFEST_PATH = OUTPUT_DIR / "pdf_manifest_pilot.csv"
FULL_MANIFEST_PATH = OUTPUT_DIR / "pdf_manifest_full.csv"
DOC_TYPES = ["prospectus", "allotment", "over_allotment_exercise", "stabilization"]

_TEXT_CACHE: dict[str, str] = {}
_MANIFEST_CACHE: pd.DataFrame | None = None
_MANIFEST_CACHE_PATH: Path | None = None

# Application-form variants that share the "prospectus" doc_type bucket but
# carry no extractable prose -- never prefer these over the main document.
_NON_PROSPECTUS_KEYWORDS = ("application form",)


def resolve_manifest_path() -> Path | None:
    """Prefers the full-scale (331-company) manifest when present, falling
    back to the pilot (8-company) one -- so callers don't need to know which
    mode a given run is in."""
    if FULL_MANIFEST_PATH.exists():
        return FULL_MANIFEST_PATH
    if PILOT_MANIFEST_PATH.exists():
        return PILOT_MANIFEST_PATH
    return None


# kept for backwards compatibility with existing `MANIFEST_PATH.exists()`
# call sites -- resolves at attribute-access time via module __getattr__
def __getattr__(name):
    if name == "MANIFEST_PATH":
        return resolve_manifest_path() or PILOT_MANIFEST_PATH
    raise AttributeError(name)


def load_manifest(path: Path | None = None) -> pd.DataFrame:
    global _MANIFEST_CACHE, _MANIFEST_CACHE_PATH
    path = path or resolve_manifest_path()
    if _MANIFEST_CACHE is None or _MANIFEST_CACHE_PATH != path:
        df = pd.read_csv(path, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(5)
        _MANIFEST_CACHE = df
        _MANIFEST_CACHE_PATH = path
    return _MANIFEST_CACHE


def get_company_docs(stock_code: str, manifest: pd.DataFrame | None = None) -> dict:
    """Mirrors hkexnews_docs.find_ipo_documents()'s bucket shape:
    {doc_type: [{"local_path": Path, "headline": str, "url": str, "release_date": str}, ...]}
    sourced entirely from the local manifest -- zero network calls."""
    manifest = manifest if manifest is not None else load_manifest()
    code = str(stock_code).zfill(5)
    sub = manifest[(manifest["stock_code"] == code) & (manifest["downloaded"] == True)]  # noqa: E712
    result = {dt: [] for dt in DOC_TYPES}
    for dt in DOC_TYPES:
        for _, r in sub[sub["doc_type"] == dt].iterrows():
            if pd.isna(r.get("local_path")):
                continue
            result[dt].append({
                "local_path": OUTPUT_DIR / r["local_path"],
                "headline": r.get("headline"),
                "url": r.get("url"),
                "release_date": r.get("release_date"),
            })
    return result


def has_local_docs(stock_code: str, manifest: pd.DataFrame | None = None) -> bool:
    docs = get_company_docs(stock_code, manifest)
    return any(docs[dt] for dt in DOC_TYPES)


def pick_prospectus(docs: dict) -> dict | None:
    """Prefers the main "GLOBAL OFFERING" document over application-form
    variants that happen to share the same doc_type bucket."""
    candidates = docs.get("prospectus", [])
    if not candidates:
        return None
    for c in candidates:
        h = (c.get("headline") or "").lower()
        if "global offering" in h:
            return c
    for c in candidates:
        h = (c.get("headline") or "").lower()
        if not any(k in h for k in _NON_PROSPECTUS_KEYWORDS):
            return c
    return candidates[0]


def extract_text(local_path: Path, max_pages: int = 40) -> str | None:
    key = str(local_path)
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    if not local_path.exists():
        return None
    try:
        text_parts = []
        with pdfplumber.open(local_path) as pdf:
            for page in pdf.pages[:max_pages]:
                # default x_tolerance (3) collapses spaces entirely on many
                # HKEX-generated PDFs (character-positioned text, not real
                # space glyphs) -- e.g. "HongKongExchangesandClearingLimited".
                # A tighter tolerance restores normal word spacing and was
                # the root cause of several fields (share counts, offer price
                # range, clawback %) silently failing to match on those docs.
                text_parts.append(page.extract_text(x_tolerance=1.5) or "")
        text = "\n".join(text_parts)
    except Exception:
        return None
    _TEXT_CACHE[key] = text
    return text
