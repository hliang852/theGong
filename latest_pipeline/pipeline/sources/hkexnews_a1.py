"""Source adapter: HKEXnews — Main Board Application Proofs (A1 filings).

HKEXnews drives its "Application Proofs and Post Hearing Information Packs" page from
a plain JSON file (the same data the page renders), so no HTML scraping or browser is
needed. We read the *Active* Main Board list — the live IPO application pipeline — and
emit one item per application, keyed by HKEXnews's stable internal id.

  data:   https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_e.json
  docs:   https://www1.hkexnews.hk/app/<relative-path-from-json>

Each JSON record:
  id           stable HKEXnews application id      -> dedupe key
  d            first-posting date (DD/MM/YYYY)     -> the public "A1 date"
  a            applicant name                       -> entity (may carry a -B/-H/-W/-S class marker)
  s            status ("A" = Active)
  ls[]         documents; the "Application Proof (1st submission)" entry holds the link
  postingDate  human-readable posting date (fallback)
"""
from __future__ import annotations
import datetime as dt
from ..base import Source, RawItem, register

DATA_URL = "https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_e.json"
DOC_BASE = "https://www1.hkexnews.hk/app/"
UA = "Mozilla/5.0 (compatible; TheGONG-latest/1.0; research aggregator)"


def _iso(ddmmyyyy: str) -> str | None:
    try:
        return dt.datetime.strptime(ddmmyyyy.strip(), "%d/%m/%Y").date().isoformat()
    except Exception:
        return None


def _proof_url(rec: dict) -> str:
    """Pick the best document link: the first Application-Proof submission, else the
    warning statement, else the HKEXnews new-listings page."""
    for doc in rec.get("ls", []):
        name = (doc.get("nF") or "") + " " + (doc.get("nS1") or "")
        if "application proof" in name.lower() and doc.get("u1"):
            return DOC_BASE + doc["u1"]
    for doc in rec.get("ls", []):
        if doc.get("u1"):
            return DOC_BASE + doc["u1"]
    if rec.get("w"):
        return DOC_BASE + rec["w"]
    return "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"


class HKEXNewsA1(Source):
    name = "HKEXnews"
    enabled = True

    def fetch(self) -> list[RawItem]:
        import requests  # imported here so a missing dep never breaks module import
        r = requests.get(DATA_URL, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        apps = r.json().get("app", [])
        out: list[RawItem] = []
        for rec in apps:
            date = _iso(rec.get("d", ""))
            applicant = (rec.get("a") or "").strip()
            if not date or not applicant:
                continue
            out.append(RawItem(
                source="HKEXnews",
                source_id=str(rec.get("id")),
                date=date,
                title=f"{applicant} — Application Proof (A1) posted",
                entity=applicant,
                url=_proof_url(rec),
                type_hint="a1",
                # class markers in the applicant name (-B 18A biotech, -W WVR, -S secondary,
                # -H H-share) give the enricher useful signal without republishing any text.
                raw_text=f"{applicant}. Main Board application proof, status {rec.get('s','')}.",
            ))
        return out


register(HKEXNewsA1())
