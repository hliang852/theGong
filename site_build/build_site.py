"""Assemble the deployable static site (site/index.html) from its inputs.

The GONG site is a single self-contained HTML page. Two kinds of data feed it:

  * The **study dataset** (331 HK IPOs) is baked into the page at build time — it is
    the core of the study and changes only when the underlying research is revised.
    It lives in `site_build/study_data.js` and is injected in place of the template's
    `__DATA__` marker.
  * The **Latest feed** (`site/data/latest.json`) is fetched at runtime and refreshed
    daily by the pipeline (.github/workflows/latest.yml). It is NOT baked in.

This split keeps index.html stable while the daily feed updates independently.

Usage:
    python -m site_build.build_site            # build with defaults
    TEMPLATE=path OUT=path python -m site_build.build_site

The build is deterministic: same template + same study_data.js => byte-identical output.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(os.environ.get("TEMPLATE", ROOT / "analysis/scratch/gong3_template.html"))
STUDY_DATA = Path(os.environ.get("STUDY_DATA", ROOT / "site_build/study_data.js"))
OUT = Path(os.environ.get("OUT", ROOT / "site/index.html"))

MARKER = "__DATA__"


def build() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in template:
        sys.exit(f"[build_site] template {TEMPLATE} has no {MARKER} marker")
    if template.count(MARKER) != 1:
        sys.exit(f"[build_site] expected exactly one {MARKER}, found {template.count(MARKER)}")

    study = STUDY_DATA.read_text(encoding="utf-8").strip()
    # sanity: the study block must define the two arrays the frontend indexes into
    for need in ("const D=", "const A="):
        if need not in study:
            sys.exit(f"[build_site] study_data.js missing `{need}` — refusing to build")

    # str.replace would treat backslashes in the data as escapes; splice instead.
    page = template.replace(MARKER, study)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")

    n_rows = study.count("],[")
    print(f"[build_site] {TEMPLATE.name} + {STUDY_DATA.name} -> {OUT} "
          f"({len(page):,} bytes, ~{study[:study.find('const A=')].count('],[')} study rows)")

    _syntax_check(page)


def _syntax_check(page: str) -> None:
    """Extract the inline <script> and run `node -c` if node is available."""
    m = re.search(r"<script>(.*?)</script>", page, re.S)
    if not m:
        return
    if not _have("node"):
        print("[build_site] node not found — skipped JS syntax check")
        return
    tmp = ROOT / "site_build" / ".syntax_check.js"
    tmp.write_text(m.group(1), encoding="utf-8")
    try:
        r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            print("[build_site] JS SYNTAX ERROR in assembled page:\n" + r.stderr)
            sys.exit(1)
        print("[build_site] JS syntax OK (node --check)")
    finally:
        tmp.unlink(missing_ok=True)


def _have(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


if __name__ == "__main__":
    build()
