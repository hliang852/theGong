# The GONG — "Latest" feed pipeline

Infrastructure & architecture for the chronological, tagged feed of **A1 filings,
IPO rumours, and rule changes** that powers the site's **Latest** tab.

The guiding constraint: **the live site is static (GitHub Pages).** A static host
cannot run a crawler, hold a secret, or do inference on request. So all the "work"
happens **at build time** in a scheduled job, which produces a plain JSON file the
static site reads. Nothing dynamic runs when a visitor loads the page.

## 0. Decisions (locked)

| Decision | Choice |
|---|---|
| **Rumours** | Included as **headline + link + our neutral one-liner**, curated by an editor (`curated/entries.json`). Never republish article text. Auto-crawled sources are official filings/announcements only. |
| **Classifier** | **Build-time LLM** (`LLM_API_KEY` secret) constrained to the taxonomy, with the deterministic **rules engine as automatic fallback**. |
| **Repo** | **Same repo as the website** — site, pipeline, committed data (`site/data/`) and the Action all live together. |
| **Cadence** | **Once daily**, 09:00 HKT (`cron: 0 1 * * *`), plus manual `workflow_dispatch`. |

---

## 1. The shape of the system

```
                         ┌──────────────────────── scheduled (GitHub Actions, cron) ───────────────────────┐
                         │                                                                                  │
  ┌────────────┐        │   ┌───────────┐   ┌───────────┐   ┌────────────┐   ┌──────────┐   ┌───────────┐  │
  │  SOURCES   │        │   │  fetch    │   │ normalize │   │  dedupe    │   │  enrich  │   │  build /  │  │
  │            │  ────► │   │ (adapters)│──►│ to canon. │──►│ vs. state  │──►│ tag +    │──►│  emit     │  │
  │ HKEXnews   │        │   │  per src  │   │  schema   │   │ (seen.json)│   │ summarise│   │ latest.json│ │
  │ HKEX/SFC   │        │   └───────────┘   └───────────┘   └────────────┘   └──────────┘   └─────┬─────┘  │
  │ Index prov.│        │        │ one module per source, isolated failures         ▲             │        │
  │ Connect    │        └────────┼──────────────────────────────────────────────────┼─────────────┼────────┘
  │ (rumours?) │                 │                                                   │             │
  └────────────┘                 │                              controlled taxonomy ┘             ▼
                                 │                              (fixed vocabulary)         git commit data/
                                 ▼                                                         latest.json + seen.json
                          respects robots.txt,                                                    │
                          rate limits, caches raw                                                 ▼
                                                                                    ┌───────────────────────────┐
                                                                                    │  GitHub Pages (static)    │
                                                                                    │  site fetches latest.json │
                                                                                    │  renders the Latest tab   │
                                                                                    └───────────────────────────┘
```

**One-line summary:** a cron job scrapes official sources, converts each item to a
common shape, drops duplicates, tags + summarises the *new* ones, appends them to a
rolling `latest.json`, and commits it. GitHub Pages serves that file; the browser
renders it. The "AI" (tagging/summarising) is done once at build time, never per request.

---

## 2. Components

| Stage | Module | Responsibility |
|---|---|---|
| **Sources** | `pipeline/sources/*.py` | One adapter per source. Each exposes `fetch() -> list[RawItem]`. Isolated: a failing source never breaks the build; it logs and yields nothing. |
| **Normalize** | `pipeline/normalize.py` | Map each `RawItem` to the canonical `Item` (schema §3). Assigns a **stable id** (hash of source + document id) so the same filing is never ingested twice. |
| **Dedupe / state** | `pipeline/state.py` | Maintains `data/seen.json` (set of ids + content hashes). Only genuinely new/changed items proceed to enrichment (which may cost money/time). |
| **Enrich** | `pipeline/enrich.py` | Assigns `type`, `tags` (from the controlled taxonomy only), and a neutral one-line `summary`. Pluggable engine: LLM (build-time, key from repo secret) **or** deterministic rules. Always falls back to rules if the LLM is unavailable. |
| **Build / emit** | `pipeline/build.py` | Orchestrates the above, merges new items into the rolling feed (window + cap, §5), sorts newest-first, writes `data/latest.json`, updates `seen.json`. |
| **Orchestration** | `.github/workflows/latest.yml` | Cron schedule → run `python -m pipeline.build` → commit changed data files. |
| **Frontend** | the site's Latest tab | `fetch('data/latest.json')` → render (the prototype's `LATEST` array becomes this file, unchanged shape). |

**Why isolate sources.** Exchange/regulator sites change markup and go down. Each
adapter is a small, independently-testable unit behind one interface, so onboarding a
new source or fixing a broken one is a local change, and one bad source degrades
gracefully instead of failing the whole run.

**Why build-time enrichment.** Doing tagging/summaries in the scheduled job (not on
the visitor's request) keeps the site 100% static and free, keeps any API key server-
side (never shipped to the browser), and makes the output cacheable and reviewable in
git history before it goes live.

---

## 3. The data contract (canonical `Item`)

The single source of truth the whole system agrees on. The site already renders this
exact shape (the prototype's sample array). Full JSON Schema in `schema/latest.schema.json`.

```jsonc
{
  "id":        "hkexnews:2026072400012",   // stable, dedupe key (source:docId)
  "date":      "2026-07-24",               // event / publication date (ISO)
  "type":      "a1",                        // a1 | rumor | rule  (the coloured badge)
  "title":     "…",                         // headline
  "entity":    "Chery Automobile",          // issuer / regulator / index provider
  "stock_code": "09973",                    // optional — present when it's a company
  "source":    "HKEXnews",                  // human-readable source name
  "url":       "https://www1.hkexnews.hk/…",// canonical link to the primary document
  "tags":      ["Automotive", "A-to-H"],    // controlled vocabulary only (§4)
  "summary":   "…",                         // neutral 1–2 sentence summary (ours)
  "ingested_at": "2026-07-24T09:14:00Z",    // when the pipeline first saw it
  "confidence": 0.92                          // optional classifier confidence
}
```

The published file is `{ "generated_at": ISO, "count": N, "items": [ Item, … ] }`.

**Editorial rule (important):** we store a **link to the source + our own neutral
summary** — never the copyrighted full text of a filing or news article. This keeps us
clear of redistribution issues and is the standard for a link-out aggregator.

---

## 4. Controlled taxonomy (why a fixed vocabulary matters)

Free-form tags drift ("18C", "Ch. 18C", "chapter-18c") and make filtering unreliable.
The taxonomy (`schema/taxonomy.json`) is a **closed list** grouped into facets:

- **Type** (the badge, one per item): `a1` · `rumor` · `rule` — extensible to
  `hearing`, `listing`, `withdrawal`.
- **Regulatory theme**: Listing Rules, Chapter 18A, Chapter 18C, Chapter 19C,
  Index Inclusion, Southbound, Connect Eligibility, FINI / Settlement, Public Float,
  Cornerstone, Disclosure, SPAC / De-SPAC.
- **Market / structure**: A-to-H, Secondary Listing, Dual-Primary, Spin-off, Refiling.
- **Sector**: Technology, AI, Biotech / Healthcare, Consumer, Financials / Fintech,
  Industrials, Energy / Materials, Property, Auto / Mobility, Semiconductors, Robotics.

The classifier is only ever allowed to pick from this list, which (a) keeps the filter
UI clean, (b) gives the LLM a bounded target, and (c) lets the frontend pin "frequent"
tags (currently **Index Inclusion · Listing Rules · A-to-H**) and hide the rest behind
the Advanced dropdown. Changing the vocabulary is a one-file edit.

---

## 5. State, rolling window & idempotency

- **Idempotent by id.** Re-running the job never duplicates an item; `seen.json` is the
  guard. Safe to run as often as we like.
- **Rolling window.** `latest.json` keeps a bounded set (proposed: last **24 months**,
  hard-capped at **N=1000** items) so the file the browser downloads stays small.
  Older items age out of the feed (they remain in git history / an archive file).
- **Incremental & cheap.** Only new items hit the enricher, so a typical run touches a
  handful of items and costs cents (or nothing, with rules).
- **Last-good on failure.** If a run errors, the previously-committed `latest.json`
  stays live; the site never sees a broken feed.

---

## 6. Scheduling & operations

- **Cron:** a few times per business day (proposed: every 3 hours, 08:00–20:00 HKT,
  Mon–Fri) so new A1 filings surface within hours; lighter on weekends.
- **Runtime:** GitHub Actions (free tier is ample for this cadence). Commits only when
  data changed, so no empty-diff noise.
- **Secrets:** if LLM enrichment is chosen, one repo secret (`LLM_API_KEY`). No secret
  ever reaches the browser.
- **Observability:** the job logs per-source counts; on failure it annotates the run
  (and can open an issue). A small `data/status.json` records last-run time + per-source
  health for a footer indicator on the Latest tab.
- **Politeness:** respect `robots.txt`, set a descriptive User-Agent, throttle requests,
  cache raw responses to avoid re-hitting sources.

---

## 7. Sourcing & legal notes (per content type)

| Type | Primary source | Mode | Notes |
|---|---|---|---|
| **A1 filings** | HKEXnews Active Application Proofs JSON (`appactive_app_sehk_e.json`) | **Automated** | Clean public JSON: applicant, first-posting date, status, document URL. Keyed by HKEXnews id. |
| **Southbound / eligibility** | SSE Southbound eligible-securities query API | **Automated (diff)** | No change-feed exists, so we snapshot the eligible set each run and diff it; additions/removals become items. Shanghai leg now; Shenzhen (SZSE) is an easy add. |
| **Rule changes** | HKEX consultations / guidance, SFC news | **Curated** (endpoint pending) | These pages are JS SPAs with guarded APIs and no public RSS/JSON — brittle to scrape unattended. Editor adds items to `curated/entries.json` (type `rule`); `hkex_rules.py` is the plug-in point for a stable/licensed feed. |
| **Index inclusion** | Hang Seng Indexes, MSCI, FTSE review/consultation notices | **Curated** (endpoint pending) | Same SPA/licensing constraint; quarterly and low-volume, so editorial review fits. `index_providers.py` is the plug-in point. |
| **Rumours** | Editor-curated (`curated/entries.json`) | **Curated** | **Headline + link + our neutral one-liner**, attributed to the reporting source. Media text is copyrighted, so we never store article bodies. A licensed news API can feed the same file later. |

*Automated sources have clean, stable data endpoints. The curated categories are low-frequency and lack a reliable public feed; each has a final-interface adapter shell so a licensed/stable source drops in without touching the rest of the pipeline.*

---

## 8. Extensibility

- **New source** → drop a `sources/<name>.py` implementing `Source.fetch()`, register it.
  Nothing else changes.
- **New tag** → add to `taxonomy.json`. The classifier and filter pick it up automatically.
- **New content type** → add to the `type` enum + a badge colour on the frontend.
- **Future chat/RAG** (separate, later phase) reuses the same archived links + summaries
  as its retrieval corpus; it is the only feature that needs a small live endpoint, and
  it is deliberately out of scope here.

---

## 9. Repository layout (proposed)

```
repo/
├─ site/                      # the static website (built later)
│  └─ data/
│     ├─ latest.json          # ← the feed the Latest tab fetches (committed by CI)
│     ├─ seen.json            # dedupe state
│     └─ status.json          # last-run health
├─ latest_pipeline/          # this pipeline (portable; can move into the site repo)
│  ├─ schema/
│  │  ├─ latest.schema.json
│  │  └─ taxonomy.json
│  └─ pipeline/
│     ├─ base.py              # Item dataclass + Source interface + registry
│     ├─ normalize.py
│     ├─ state.py             # dedupe / seen.json
│     ├─ enrich.py            # tag + summarise (LLM or rules)
│     ├─ build.py             # orchestrator (entrypoint)
│     └─ sources/
│        ├─ hkexnews_a1.py
│        ├─ hkex_rules.py
│        ├─ sfc.py
│        ├─ index_providers.py
│        └─ connect_eligibility.py
└─ .github/workflows/latest.yml
```
