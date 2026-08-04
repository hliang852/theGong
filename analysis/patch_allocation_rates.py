"""
Patch pass: fills pool_a_1lot_allocation_rate_pct in output/hkex_ipo_full.csv
from the local allotment PDFs using the rebuilt BASIS-OF-ALLOCATION extractor.
--validate mode runs only the 12 recon-sample companies and compares against
hand-read expected values before the full pass is trusted.
"""
import sys
sys.path.insert(0, ".")
import pandas as pd
from scraper import local_docs, pdf_extract

OUT_CSV = "output/hkex_ipo_full.csv"
MAX_PAGES = 60  # basis table sits mid-document; 40 (the default) can fall short in mega-deal docs

# hand-read from the recon dump (analysis/recon_allotment.py output)
EXPECTED = {
    "03750": 10.00, "00300": 100.00, "02259": 50.00, "02476": 0.71,
    "02714": 100.00, "09660": 100.00, "06979": 100.00, "02268": 13.00,
    "09880": 40.02, "02587": 50.00, "02671": 0.75, "06715": 3.00,
}


def rate_for(code, manifest):
    docs = local_docs.get_company_docs(code, manifest)
    if not docs["allotment"]:
        return None, "no_allotment_doc"
    # try every allotment doc -- some companies file a short preliminary
    # announcement first (e.g. 00901) with the real basis table in a second
    # filing
    err = "no_text"
    for doc in docs["allotment"]:
        text = local_docs.extract_text(doc["local_path"], max_pages=MAX_PAGES)
        if not text:
            continue
        val = pdf_extract.extract_hk_1lot_allocation_rate(text)
        if val is not None:
            return val, None
        err = "no_match"
    return None, err


def main():
    manifest = local_docs.load_manifest()

    if "--validate" in sys.argv:
        ok = bad = 0
        for code, expected in EXPECTED.items():
            val, err = rate_for(code, manifest)
            status = "OK" if val == expected else f"MISMATCH (expected {expected}, got {val}, err={err})"
            if val == expected:
                ok += 1
            else:
                bad += 1
            print(f"{code}: {val} {status}", flush=True)
        print(f"\n{ok}/{ok+bad} validated")
        return

    df = pd.read_csv(OUT_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(5)
    patched, misses = 0, []
    for idx, row in df.iterrows():
        if pd.notna(row["pool_a_1lot_allocation_rate_pct"]):
            continue
        val, err = rate_for(row["stock_code"], manifest)
        if val is not None:
            df.at[idx, "pool_a_1lot_allocation_rate_pct"] = val
            patched += 1
        else:
            misses.append((row["stock_code"], err))
    print(f"Patched {patched} rows; {len(misses)} misses: {misses}")
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
