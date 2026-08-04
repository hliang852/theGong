# The GONG — build review & open decisions

Status of the site build and everything that needs a human decision before/around
going live. Written 2026-08-03. Nothing here blocks local preview; the flagged items
block *public launch* or *full automation*.

---

## What is now built and wired

| Piece | State |
|---|---|
| **Deployable site** | `site/index.html` (self-contained) + `site/data/` feed. Serves over HTTP with 200s; verified locally. |
| **Reproducible build** | `site_build/build_site.py` assembles `index.html` from the template + `study_data.js` (deterministic; `node --check` gate). |
| **Study dataset** | Real — 331 HK Main Board IPOs from `output/analysis/ipo_analysis.csv`, with the split/VWAP repairs already applied. Baked into `index.html`. |
| **Latest feed** | Real — `site/data/latest.json`, 350 items: **346 live HKEXnews A1 filings** + 4 curated. Fetched at runtime; refreshes daily via `.github/workflows/latest.yml`. |
| **Southbound** | SSE snapshot baseline set (`southbound_sse.json`); adds/removals surface from the 2nd run onward. |
| **Pages deploy** | `.github/workflows/pages.yml` builds + publishes `site/` on push and after each feed refresh. |

---

## Blockers for public launch (need a human)

1. **Repository is not yet a git repo / has no GitHub remote.**
   The two workflows assume a git repo pushed to GitHub with Pages enabled. Before
   anything deploys:
   - `git init`, commit, create the GitHub repo, push to `main`.
   - Settings → Pages → **Source: GitHub Actions**.
   - (Decision) is this repo public? A1 filings and the study data are public
     information, but confirm before publishing the whole repo.

2. **Curated content is placeholder — remove before launch.**
   `latest_pipeline/curated/entries.json` still contains **fake rumours**
   ("Example Robotics Group", "Placeholder Retail Group") and example rule URLs.
   These render as real feed items. Replace with genuine editorial entries (or clear
   the file) so the live site never shows invented rumours.

3. **LLM enrichment key not set.**
   The feed was generated with the **rules engine** (no `LLM_API_KEY` locally), so A1
   items carry only coarse sector tags and templated summaries. For richer tags +
   neutral one-line summaries, add the repo secret `LLM_API_KEY` (and optionally
   `LLM_API_BASE` / `LLM_MODEL` vars). CI already defaults to `engine=llm` and falls
   back to rules per-item if the key is missing — so it's safe either way, just less rich.

4. **Auth / subscribe / paywall are prototype-only.**
   Login, subscribe, and the "Data" paywall persist via `localStorage` with **no
   backend and no payment**. The paywall is cosmetic — anyone can bypass it. A real
   subscription needs a backend (out of scope for a static site); decide whether to
   (a) drop the paywall for launch, (b) gate with a real auth provider, or (c) keep it
   as a visual placeholder clearly labelled "prototype".

---

## Data-pipeline gaps (automation completeness)

5. **`study_data.js` is not regenerated from CSV in the build.**
   It is the validated data block preserved from the prior assembled page (real, but
   frozen). A generator (`analysis/build_gong_data.py`) that re-derives `const D` /
   `const A` from `output/analysis/ipo_analysis.csv` would close the loop.
   **Risk:** re-deriving must reproduce the split/VWAP repairs exactly, or it will
   reintroduce the corruption fixed earlier — validate any regenerated block against
   the current `study_data.js` before swapping. Until then, updating the study means
   editing `study_data.js` (or re-extracting from a new assembled page).

6. **Rule-change & index-inclusion adapters are shells.**
   `hkex_rules.py` and `index_providers.py` return `[]`; those items come only from
   the curated file. HKEX/SFC/HSI pages are JS SPAs with no public feed — wiring a
   **licensed regulatory/index news API** is the clean path. Endpoints are documented
   in each adapter.

7. **Southbound is Shanghai-only.**
   SSE (Shanghai Connect) leg is live. Shenzhen (SZSE) Connect is a one-adapter add.

8. **A1 feed volume.**
   346 active application proofs is the full live set; the feed caps at 1000 over a
   24-month window. If the Latest tab feels heavy, consider frontend pagination or a
   default "last 90 days" view (data already supports it via `date`).

---

## Smaller notes

- **Domain/branding.** The feed bot commits as `bot@thegong.hk`; no `CNAME` is
  configured. Decide the real domain (or use the default `*.github.io`).
- **Study "as of" date.** Dataset covers through **2026-06-30** (test window 2026 H1).
  6-month / 1-year VWAP columns are intentionally null for future dates.
- **Editorial/legal model.** Feed stores **link + our neutral summary**, never
  copyrighted article text — keep this rule for any new source. Terms/disclaimer page
  is present.
- **`index.html` is committed but also rebuilt in CI** from its inputs, so the
  deployed page always matches `template + study_data.js`. Editing the committed
  `index.html` by hand will be overwritten — edit the template instead.

---

## How to rebuild / refresh locally

```bash
# rebuild the page after editing the template or study data
python -m site_build.build_site

# refresh the Latest feed (rules engine; set LLM_API_KEY + LATEST_ENGINE=llm for rich tags)
LATEST_ENGINE=rules LATEST_OUT=site/data/latest.json python -m latest_pipeline.pipeline.build

# preview
cd site && python -m http.server 8000   # -> http://localhost:8000
```
