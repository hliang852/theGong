"""Recon: dump the Basis-of-Allotment and Cornerstone sections from a sample
of allotment PDFs across years, to calibrate the patch extractors."""
import sys, re
sys.path.insert(0, ".")
import pandas as pd
from scraper import local_docs

manifest = local_docs.load_manifest()
df = pd.read_csv("output/analysis/ipo_analysis.csv", dtype={"stock_code": str}, parse_dates=["ipo_date"])

# sample: ~3 per year, mix of sizes
sample = (df.sort_values("total_ipo_size_usd", ascending=False)
            .groupby("year").head(2).stock_code.tolist())
sample += df.groupby("year").tail(1).stock_code.tolist()

out = []
for code in sample:
    docs = local_docs.get_company_docs(code, manifest)
    a = docs["allotment"][0] if docs["allotment"] else None
    if not a:
        continue
    text = local_docs.extract_text(a["local_path"], max_pages=60)
    if not text:
        out.append(f"##### {code}: NO TEXT")
        continue
    row = df[df.stock_code == code].iloc[0]
    out.append(f"\n##### {code} ({row['year']}, {row['company_name_en']}) file={a['local_path'].name}")
    # basis of allotment section
    m = re.search(r"BASIS OF ALLOTMENT|BASIS OF ALLOCATION|basis of allotment", text)
    if m:
        out.append("--- BASIS section (first 1800 chars) ---")
        out.append(text[m.start():m.start() + 1800])
    else:
        # look for the 1-lot ballot phrasing anywhere
        m2 = re.search(r".{300}board lot.{600}", text, re.S)
        out.append("--- no BASIS header; 'board lot' context ---")
        out.append(m2.group(0) if m2 else "(no 'board lot' text)")
    # cornerstone section
    m = re.search(r"CORNERSTONE", text)
    if m:
        out.append("--- CORNERSTONE section (first 1200 chars) ---")
        out.append(text[m.start():m.start() + 1200])
    else:
        out.append("--- no CORNERSTONE header ---")

open("/tmp/recon_allotment.txt", "w").write("\n".join(out))
print(f"wrote /tmp/recon_allotment.txt  ({len(sample)} companies sampled)")
