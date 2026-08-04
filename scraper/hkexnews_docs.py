"""
HKEXnews document search, rebuilt as a plain requests-based POST to
titlesearch.xhtml -- no browser/session needed. (Earlier investigation
wrongly concluded this page was bot-gated; the actual issue was calling the
wrong endpoint with wrong field names. The real search is a stateless JSF
form POST; a bare `requests.post` with the right field names works with no
prior GET/cookies/ViewState at all -- confirmed against live data.)

Flow per company:
  1. resolve_stock_id(stock_code) -> internal numeric stockId via prefix.do
     (NOT the same as the public stock code -- required by the search form)
  2. search(stock_id, from_date, to_date) -> list of (datetime, headline, link)
  3. Filter the returned headlines for the specific IPO document types.
"""
from __future__ import annotations
import re
import time
import json
import io
import requests
import pdfplumber
from pathlib import Path
from datetime import date, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"
SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"
CACHE_DIR = Path(__file__).resolve().parent.parent / "output" / "cache" / "docsearch"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ROW_RE = re.compile(
    r'release-time">.*?>([\d/]+ [\d:]+)</td>.*?'
    r'stock-short-code">.*?>(\d+)</td>.*?'
    r'headline">([^<]+)<br/>\s*</div>\s*<div class="doc-link">\s*'
    r'<a href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)


def resolve_stock_id(stock_code: str, retries=3) -> int | None:
    cache_path = CACHE_DIR / f"stockid_{stock_code}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text()).get("stockId")

    code = stock_code.lstrip("0") or "0"
    for attempt in range(retries):
        try:
            r = requests.get(PREFIX_URL, params={"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"},
                              headers={"User-Agent": UA}, timeout=15)
            m = re.search(r"callback\((.*)\);?$", r.text.strip())
            if not m:
                time.sleep(1)
                continue
            data = json.loads(m.group(1))
            for entry in data.get("stockInfo", []):
                if entry.get("code", "").lstrip("0") == code:
                    cache_path.write_text(json.dumps(entry))
                    return entry["stockId"]
            return None
        except Exception:
            time.sleep(1.5)
    return None


def search(stock_id: int, from_date: date, to_date: date, title: str = "", retries=3):
    """Returns list of dicts: {datetime, stock_code, headline, link}"""
    cache_key = f"search_{stock_id}_{from_date}_{to_date}_{title or 'all'}.json"
    cache_path = CACHE_DIR / cache_key
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    data = {
        "lang": "EN", "category": "0", "market": "SEHK", "searchType": "0",
        "documentType": "", "t1code": "", "t2Gcode": "", "t2code": "",
        "stockId": str(stock_id), "from": from_date.strftime("%Y%m%d"), "to": to_date.strftime("%Y%m%d"),
        "MB-Daterange": "0", "title": title,
    }
    for attempt in range(retries):
        try:
            r = requests.post(SEARCH_URL, data=data, headers={"User-Agent": UA}, timeout=20)
            if r.status_code != 200:
                time.sleep(1.5)
                continue
            rows = []
            for dt, code, category, link, title_html in ROW_RE.findall(r.text):
                title = re.sub(r"<[^>]+>", " ", title_html)
                title = re.sub(r"\s+", " ", title).strip()
                category = category.strip()
                # The document title (e.g. "STABILIZING ACTIONS AND END OF
                # STABILIZATION PERIOD") lives in the link anchor text, not
                # the generic category label -- combine both so downstream
                # keyword matching sees the real title.
                headline = f"{category} - {title}" if title else category
                rows.append({
                    "datetime": dt.strip(),
                    "stock_code": code.strip(),
                    "category": category,
                    "title": title,
                    "headline": headline,
                    "link": link if link.startswith("http") else f"https://www1.hkexnews.hk{link}",
                })
            cache_path.write_text(json.dumps(rows))
            time.sleep(0.3)
            return rows
        except Exception:
            time.sleep(1.5)
    return []


def find_ipo_documents(stock_code: str, ipo_date: date):
    """Searches a window around the IPO date and buckets results into the
    three document types the user asked for. Window: 60 days before listing
    (covers prospectus/global offering + allotment results) through 60 days
    after (covers stabilization notices, which post up to 30 days post-listing)."""
    stock_id = resolve_stock_id(stock_code)
    if stock_id is None:
        return {"error": "stock_id_not_resolved", "prospectus": [], "allotment": [], "stabilization": []}

    rows = search(stock_id, ipo_date - timedelta(days=60), ipo_date + timedelta(days=60))
    # search() returns newest-first; sort ascending so "first match" below is
    # the earliest (i.e. original) filing of each type, not a later
    # clarification/correction/supplemental notice referencing the same headline
    rows_asc = sorted(rows, key=lambda r: r["datetime"])
    result = {"prospectus": [], "allotment": [], "over_allotment_exercise": [], "stabilization": [], "all_rows": rows}
    excluded_kw = ("clarification", "correction", "supplemental", "reminder")
    for row in rows_asc:
        h = row["headline"].lower()
        if any(k in h for k in excluded_kw):
            continue
        if "offer for subscription" in h or ("listing documents" in h and "introduction" not in h):
            result["prospectus"].append(row)
        elif "stabili" in h:
            result["stabilization"].append(row)
        elif "over-allotment" in h:
            result["over_allotment_exercise"].append(row)
        elif "allotment results" in h or "final offer price" in h:
            result["allotment"].append(row)
    return result


SUMMARY_LINK_RE = re.compile(
    r'<a fileName="[^"]+" href="([^"]+)"[^>]*>\s*SUMMARY\s*</a>', re.I
)


def resolve_htm_to_summary_pdf(htm_url: str, retries=3) -> str | None:
    """Some HKEXnews headlines link to an .htm index page (chaptered
    prospectus, or an allotment-results package) that lists per-section PDFs
    rather than a single document. Resolve one layer deeper to the "Summary"
    section's PDF, which is the section that actually carries the figures
    this pipeline extracts. Returns None if no Summary link is found."""
    for attempt in range(retries):
        try:
            resp = requests.get(htm_url, headers={"User-Agent": UA}, timeout=20)
            if resp.status_code != 200:
                time.sleep(1.5)
                continue
            m = SUMMARY_LINK_RE.search(resp.text)
            if not m:
                return None
            href = m.group(1)
            if href.startswith("http"):
                return href
            base = htm_url.rsplit("/", 1)[0] + "/"
            return base + href
        except Exception:
            time.sleep(1.5)
    return None


def download_raw(url: str, dest_path: Path, retries=3) -> bool:
    """Downloads the raw file (PDF or HTM) to dest_path. Returns True on success.
    Skips re-download if dest_path already exists and is non-empty."""
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            if resp.status_code != 200 or not resp.content:
                time.sleep(1.5)
                continue
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(resp.content)
            time.sleep(0.3)
            return True
        except Exception:
            time.sleep(1.5)
    return False


def fetch_document_text(url: str, retries=3) -> str | None:
    """Handles both PDF filings and the occasional plain-HTML announcement
    (some older allotment-results notices are .htm, not .pdf)."""
    cache_path = CACHE_DIR / (re.sub(r"[^A-Za-z0-9]", "_", url)[-150:] + ".txt")
    if cache_path.exists():
        return cache_path.read_text(errors="ignore")

    is_pdf = url.lower().endswith(".pdf")
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if resp.status_code != 200:
                time.sleep(1.5)
                continue
            if is_pdf:
                text_parts = []
                with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                    for page in pdf.pages[:40]:
                        # see local_docs.extract_text -- default x_tolerance
                        # collapses spaces on many HKEX-generated PDFs
                        text_parts.append(page.extract_text(x_tolerance=1.5) or "")
                text = "\n".join(text_parts)
            else:
                text = re.sub(r"<[^>]+>", " ", resp.text)
                text = re.sub(r"\s+", " ", text)
            cache_path.write_text(text)
            time.sleep(0.3)
            return text
        except Exception:
            time.sleep(1.5)
    return None
