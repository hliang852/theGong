"""
Cornerstone patch pass. For each company, locates the CORNERSTONE INVESTORS
chapter of the local full prospectus PDF via its outline (bookmarks), extracts
just those pages, and pulls:
  - has_cornerstone (chapter exists)
  - cornerstone_total_usd (aggregate amount from the lead paragraph;
    US$/HK$/RMB handled, HK$ converted at 7.8, RMB at 7.2)
  - num_cornerstone_investors (best-effort count of investor subsections)
  - cornerstone_lockup_months (6/12-month undertaking phrasing)

For the 28 companies whose local prospectus is a summary-only section PDF
(resolved from an .htm chapter index), fetches the CORNERSTONE INVESTORS
section PDF from the same index (small file, one request).

Writes output/analysis/cornerstone_patch.csv keyed by stock_code; the schema
columns num_cornerstone_investors / cornerstone_lockup_months in
hkex_ipo_full.csv are also backfilled where null.
"""
import sys, re, io
sys.path.insert(0, ".")
import pandas as pd
import pdfplumber
import requests
from pathlib import Path
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import resolve1
from scraper import local_docs, pdf_extract

OUT_CSV = "output/hkex_ipo_full.csv"
PATCH_CSV = Path("output/analysis/cornerstone_patch.csv")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
USD_HKD, USD_RMB = 7.8, 7.2


def outline_page_starts(path):
    """title -> 0-based start page, from PDF bookmarks. {} if no outline."""
    try:
        with open(path, "rb") as f:
            parser = PDFParser(f)
            doc = PDFDocument(parser)
            pageidx = {p.pageid: i for i, p in enumerate(PDFPage.create_pages(doc))}
            starts = []
            for level, title, dest, a, se in doc.get_outlines():
                target = None
                if dest:
                    d = resolve1(dest)
                    if isinstance(d, list) and d and hasattr(d[0], "objid"):
                        target = pageidx.get(d[0].objid)
                elif a:
                    act = resolve1(a)
                    if isinstance(act, dict) and "D" in act:
                        d = resolve1(act["D"])
                        if isinstance(d, list) and d and hasattr(d[0], "objid"):
                            target = pageidx.get(d[0].objid)
                if target is not None:
                    starts.append((title.strip().upper(), target))
            return starts
    except Exception:
        return []


def chapter_text_from_outline(path):
    starts = outline_page_starts(path)
    for i, (title, pg) in enumerate(starts):
        if "CORNERSTONE" in title:
            end = starts[i + 1][1] if i + 1 < len(starts) else pg + 15
            end = min(end, pg + 25)
            try:
                with pdfplumber.open(path) as pdf:
                    return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages[pg:end])
            except Exception:
                return None
    return None


def chapter_text_by_scan(path, max_page=650, step=6):
    """Fallback for PDFs with stub outlines (a handful of entries that don't
    list chapters): coarse-scan pages in steps looking for the chapter header
    at the top of a page, then fine-scan the neighborhood. Returns chapter
    text, or False if the scan completed without finding a header, or None
    on read failure."""
    try:
        with pdfplumber.open(path) as pdf:
            n = min(len(pdf.pages), max_page)
            hit = None
            for i in range(0, n, step):
                head = (pdf.pages[i].extract_text(x_tolerance=1.5) or "")[:300]
                if re.search(r"CORNERSTONE INVESTORS?", head):
                    hit = i
                    break
            if hit is None:
                return False
            # fine-scan backwards to the true chapter start
            start = hit
            for j in range(max(0, hit - step + 1), hit):
                head = (pdf.pages[j].extract_text(x_tolerance=1.5) or "")[:300]
                if re.search(r"CORNERSTONE INVESTORS?", head):
                    start = j
                    break
            return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages[start:start + 15])
    except Exception:
        return None


def chapter_text_from_htm_index(htm_url):
    """For summary-only locals: fetch the CORNERSTONE section PDF listed on
    the .htm chapter index."""
    try:
        r = requests.get(htm_url, headers={"User-Agent": UA}, timeout=20)
        links = re.findall(r'<a fileName="[^"]+" href="([^"]+)"[^>]*>([^<]+)</a>', r.text)
        target = next((href for href, label in links if "CORNERSTONE" in label.upper()), None)
        if not target:
            return "NO_CHAPTER"  # index exists but no cornerstone chapter listed
        url = target if target.startswith("http") else htm_url.rsplit("/", 1)[0] + "/" + target
        pr = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        with pdfplumber.open(io.BytesIO(pr.content)) as pdf:
            return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages[:25])
    except Exception:
        return None


AMT_RE = re.compile(
    r"aggregate (?:amount|sum) of\s+(?:approximately\s+)?(US\$|HK\$|RMB)\s*([\d,.]+)\s*(million|billion)",
    re.I)


def extract_cornerstone_fields(text):
    out = {"cornerstone_total_usd": None, "num_cornerstone_investors": None, "lockup_months": None}
    m = AMT_RE.search(text)
    if m:
        cur, val, unit = m.group(1).upper(), float(m.group(2).replace(",", "")), m.group(3).lower()
        val *= 1e9 if unit == "billion" else 1e6
        if cur == "HK$":
            val /= USD_HKD
        elif cur == "RMB":
            val /= USD_RMB
        out["cornerstone_total_usd"] = round(val, 0)
    # investor count: the chapter's investor list is usually numbered
    # subsections "1. Name", "2. Name", ... or "(a) ... (b) ..."; count the
    # highest consecutive integer heading followed by an uppercase-ish name
    nums = re.findall(r"\n(\d{1,2})\.\s+[A-Z(“]", text)
    if nums:
        seq = sorted({int(n) for n in nums})
        count = 0
        for i, v in enumerate(seq, start=1):
            if v == i:
                count = v
            else:
                break
        if count:
            out["num_cornerstone_investors"] = count
    if out["num_cornerstone_investors"] is None:
        # roman-numeral list variant: "(i) ... (ii) ... (iii) ..."
        romans = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
                  "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"]
        found = {r for r in romans if re.search(rf"\(({r})\)\s", text)}
        count = 0
        for i, r in enumerate(romans, start=1):
            if r in found:
                count = i
            else:
                break
        if count >= 2:
            out["num_cornerstone_investors"] = count
    lock = pdf_extract.extract_cornerstone_lockup_months(text)
    out["lockup_months"] = lock
    return out


def main():
    manifest = local_docs.load_manifest()
    m = pd.read_csv("output/pdf_manifest_full.csv", dtype={"stock_code": str})
    m["stock_code"] = m["stock_code"].str.zfill(5)
    pros = m[(m.doc_type == "prospectus") & (m.downloaded == True)].groupby("stock_code").first()  # noqa: E712

    rows = []
    codes = sorted(pros.index)
    for i, code in enumerate(codes, 1):
        rec = {"stock_code": code, "has_cornerstone": None, "cornerstone_total_usd": None,
               "num_cornerstone_investors": None, "cornerstone_lockup_months": None, "source": None}
        info = pros.loc[code]
        text = None
        if pd.notna(info.get("resolved_from_htm_index")):
            res = chapter_text_from_htm_index(info["resolved_from_htm_index"])
            if res == "NO_CHAPTER":
                rec["has_cornerstone"] = False
                rec["source"] = "htm_index_no_chapter"
            elif res:
                text, rec["source"] = res, "htm_section_pdf"
        else:
            docs = local_docs.get_company_docs(code, manifest)
            p = local_docs.pick_prospectus(docs)
            if p:
                path = p["local_path"]
                starts = outline_page_starts(path)
                # a stub outline (a couple of entries that don't list
                # chapters) proves nothing about chapter absence -- only a
                # real chapter-level outline can assert has_cornerstone=False
                if starts and len(starts) >= 5:
                    if any("CORNERSTONE" in t for t, _ in starts):
                        text, rec["source"] = chapter_text_from_outline(path), "outline"
                    else:
                        rec["has_cornerstone"] = False
                        rec["source"] = "outline_no_chapter"
                else:
                    res = chapter_text_by_scan(path)
                    if res is False:
                        rec["has_cornerstone"] = False
                        rec["source"] = "scan_no_chapter"
                    elif res:
                        text, rec["source"] = res, "page_scan"
                    else:
                        rec["source"] = "scan_failed"
        if text:
            rec["has_cornerstone"] = True
            fields = extract_cornerstone_fields(text)
            rec["cornerstone_total_usd"] = fields["cornerstone_total_usd"]
            rec["num_cornerstone_investors"] = fields["num_cornerstone_investors"]
            rec["cornerstone_lockup_months"] = fields["lockup_months"]
        rows.append(rec)
        if i % 25 == 0:
            print(f"{i}/{len(codes)}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(PATCH_CSV, index=False)
    print(out["source"].value_counts(dropna=False).to_string())
    print(f"has_cornerstone=True: {(out.has_cornerstone == True).sum()}, False: {(out.has_cornerstone == False).sum()}, unknown: {out.has_cornerstone.isna().sum()}")
    print(f"total_usd filled: {out.cornerstone_total_usd.notna().sum()}  investor count filled: {out.num_cornerstone_investors.notna().sum()}")

    # backfill schema columns in the full CSV where null
    df = pd.read_csv(OUT_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(5)
    merged = df.merge(out[["stock_code", "num_cornerstone_investors", "cornerstone_lockup_months"]],
                      on="stock_code", how="left", suffixes=("", "_patch"))
    for col in ["num_cornerstone_investors", "cornerstone_lockup_months"]:
        fill = df[col].isna() & merged[f"{col}_patch"].notna()
        df.loc[fill, col] = merged.loc[fill, f"{col}_patch"]
        print(f"backfilled {col}: +{fill.sum()}")
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV} and {PATCH_CSV}")


if __name__ == "__main__":
    main()
