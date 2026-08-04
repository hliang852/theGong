"""Orchestrator / entrypoint:  fetch -> dedupe -> enrich -> merge -> emit.

Run:  python -m latest_pipeline.pipeline.build
Env:
  LATEST_ENGINE   "rules" (default) | "llm"
  LLM_API_KEY     required only when LATEST_ENGINE=llm
  LATEST_OUT      output path (default site/data/latest.json)

Design guarantees: idempotent (safe to run any number of times), source-isolated
(one bad adapter never fails the run), and last-good-on-failure (only rewrites the
feed when it built successfully).
"""
from __future__ import annotations
import json
import os
import datetime as dt

from .base import REGISTRY, Item, now_iso
from .state import SeenStore
from .enrich import get_enricher
from . import sources  # noqa: F401  (importing registers the adapters)

WINDOW_MONTHS = 24
MAX_ITEMS = 1000
OUT_PATH = os.environ.get("LATEST_OUT", "site/data/latest.json")
STATUS_PATH = os.path.join(os.path.dirname(OUT_PATH), "status.json")


def _load_existing(path: str) -> list[dict]:
    if os.path.exists(path):
        try:
            return json.load(open(path)).get("items", [])
        except Exception:
            return []
    return []


def _within_window(date_str: str) -> bool:
    try:
        d = dt.date.fromisoformat(date_str)
    except Exception:
        return True
    cutoff = dt.date.today() - dt.timedelta(days=WINDOW_MONTHS * 31)
    return d >= cutoff


def run() -> dict:
    engine = os.environ.get("LATEST_ENGINE", "rules")
    enricher = get_enricher(engine, os.environ.get("LLM_API_KEY"))
    seen = SeenStore(os.path.join(os.path.dirname(OUT_PATH), "seen.json"))

    existing = {it["id"]: it for it in _load_existing(OUT_PATH)}
    status = {"generated_at": now_iso(), "engine": engine, "sources": {}}
    new_count = 0

    for src in REGISTRY:
        if not src.enabled:
            continue
        try:
            raw = src.fetch()
            status["sources"][src.name] = {"ok": True, "fetched": len(raw)}
        except Exception as e:                      # source isolation
            status["sources"][src.name] = {"ok": False, "error": str(e)[:200]}
            continue
        for r in raw:
            if not seen.is_new_or_changed(r):
                continue
            item: Item = enricher.enrich(r)
            existing[item.id] = item.to_json()
            seen.mark(r)
            new_count += 1

    # rolling window + cap, newest first
    items = [it for it in existing.values() if _within_window(it.get("date", ""))]
    items.sort(key=lambda it: (it.get("date", ""), it.get("id", "")), reverse=True)
    items = items[:MAX_ITEMS]

    feed = {"generated_at": now_iso(), "schema_version": "1.0", "count": len(items), "items": items}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(feed, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
    seen.save()
    status["new_items"] = new_count
    status["total_items"] = len(items)
    json.dump(status, open(STATUS_PATH, "w"), indent=2)

    print(f"[build] engine={engine} new={new_count} total={len(items)} -> {OUT_PATH}")
    return status


if __name__ == "__main__":
    run()
