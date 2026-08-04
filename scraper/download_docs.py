"""
Downloads raw IPO document files (prospectus/listing document, allotment
results announcement, full exercise of over-allotment option notice,
stabilization notice) to output/pdfs/{stock_code}/ for a given set of
companies, and writes a manifest CSV recording what was found/fetched.

This decouples slow/flaky HKEXnews network fetches from PDF text-extraction
work -- once downloaded, extraction logic can be iterated on locally without
re-hitting the network each time.
"""
from __future__ import annotations
import sys
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from scraper import parse_nlr, hkexnews_docs
from scraper.build_pilot import pick_pilot_set

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
PDF_DIR = OUTPUT_DIR / "pdfs"

DOC_TYPES = ["prospectus", "allotment", "over_allotment_exercise", "stabilization"]


def _filename_for(url: str, doc_type: str, idx: int) -> str:
    ext = ".pdf" if url.lower().endswith(".pdf") else ".htm"
    return f"{doc_type}_{idx}{ext}"


def download_for_company(stock_code: str, company_name: str, ipo_date) -> list[dict]:
    manifest_rows = []
    docs = hkexnews_docs.find_ipo_documents(stock_code, ipo_date)
    if docs.get("error"):
        manifest_rows.append({
            "stock_code": stock_code, "company_name": company_name, "ipo_date": ipo_date,
            "doc_type": "ERROR", "headline": docs["error"], "url": None,
            "resolved_from_htm_index": None, "release_date": None, "local_path": None, "downloaded": False,
        })
        return manifest_rows

    company_dir = PDF_DIR / stock_code
    for doc_type in DOC_TYPES:
        rows = docs.get(doc_type, [])
        if not rows:
            manifest_rows.append({
                "stock_code": stock_code, "company_name": company_name, "ipo_date": ipo_date,
                "doc_type": doc_type, "headline": None, "url": None,
                "resolved_from_htm_index": None, "release_date": None, "local_path": None, "downloaded": False,
            })
            continue
        for idx, row in enumerate(rows):
            link = row["link"]
            resolved_from_htm = None
            if link.lower().endswith(".htm"):
                summary_pdf = hkexnews_docs.resolve_htm_to_summary_pdf(link)
                if summary_pdf:
                    resolved_from_htm = link
                    link = summary_pdf
                # else: no Summary sub-link found on the index page -- fall
                # back to downloading the .htm itself rather than silently
                # dropping the document.
            fname = _filename_for(link, doc_type, idx)
            dest = company_dir / fname
            ok = hkexnews_docs.download_raw(link, dest)
            try:
                release_date = datetime.strptime(row["datetime"], "%d/%m/%Y %H:%M").isoformat(sep=" ")
            except Exception:
                release_date = row["datetime"]
            manifest_rows.append({
                "stock_code": stock_code, "company_name": company_name, "ipo_date": ipo_date,
                "doc_type": doc_type, "headline": row["headline"], "url": link,
                "resolved_from_htm_index": resolved_from_htm,
                "release_date": release_date,
                "local_path": str(dest.relative_to(OUTPUT_DIR)) if ok else None,
                "downloaded": ok,
            })
    return manifest_rows


MANIFEST_FIELDS = ["stock_code", "company_name", "ipo_date", "doc_type", "headline", "url", "resolved_from_htm_index", "release_date", "local_path", "downloaded"]


def main():
    full = "--full" in sys.argv

    print("Loading NLR data and applying scope filters...")
    nlr = parse_nlr.load_all()
    kept, _excluded = parse_nlr.apply_scope_filters(nlr)

    if full:
        targets = kept.sort_values("ipo_date").reset_index(drop=True)
        manifest_path = OUTPUT_DIR / "pdf_manifest_full.csv"
    else:
        targets = pick_pilot_set(kept).sort_values("ipo_date").reset_index(drop=True)
        manifest_path = OUTPUT_DIR / "pdf_manifest_pilot.csv"
    print(f"{'Full' if full else 'Pilot'} set: {len(targets)} companies -> {manifest_path.name}")

    # already-processed companies (by stock_code) are skipped on rerun, so an
    # interrupted full-scale run can just be re-invoked to resume -- combined
    # with download_raw()'s own skip-if-file-exists check, this makes the
    # whole step safely restartable rather than needing to complete in one go.
    done_codes = set()
    if manifest_path.exists():
        done_codes = set(pd.read_csv(manifest_path, dtype={"stock_code": str})["stock_code"])
        print(f"  {len(done_codes)} companies already in manifest, will be skipped")

    write_header = not manifest_path.exists()
    with open(manifest_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()

        for i, (_, ipo) in enumerate(targets.iterrows(), start=1):
            code, name, ipo_date = ipo["stock_code"], ipo["company_name_en"], ipo["ipo_date"].date()
            if code in done_codes:
                continue
            print(f"\n[{i}/{len(targets)}] {code} {name} ({ipo_date})")
            try:
                rows = download_for_company(code, name, ipo_date)
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                rows = [{"stock_code": code, "company_name": name, "ipo_date": ipo_date,
                          "doc_type": "ERROR", "headline": f"{type(e).__name__}: {e}", "url": None,
                          "resolved_from_htm_index": None, "release_date": None, "local_path": None, "downloaded": False}]
            for r in rows:
                status = "OK" if r["downloaded"] else "MISSING"
                print(f"  [{status}] {r['doc_type']}: {r['headline']}")
            writer.writerows(rows)
            f.flush()

    print(f"\nManifest written to {manifest_path}")
    total_bytes = sum(f.stat().st_size for f in PDF_DIR.rglob("*") if f.is_file())
    print(f"Total downloaded: {total_bytes / 1e6:.1f} MB across {sum(1 for f in PDF_DIR.rglob('*') if f.is_file())} files")


if __name__ == "__main__":
    main()
