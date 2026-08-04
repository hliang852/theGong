"""Source adapter: curated entries.

For content that is not auto-crawled from an official filing — primarily **rumours**,
which come from news media whose text is copyrighted. An editor appends an entry with
a headline, a link to the original report, a date and a neutral one-line note; we never
store the article body. This is the "headline + link + our one-liner" model.

Entries live in `latest_pipeline/curated/entries.json` (committed, reviewable):

    [
      {
        "date": "2026-07-21",
        "type": "rumor",
        "entity": "Example Group",
        "title": "Example Group said to weigh a Hong Kong listing",
        "url": "https://source.example/report",
        "source": "Wire report",
        "note": "Reported to be exploring a spin-off listing; no filing confirmed."
      }
    ]

The enricher still assigns tags; the curator's `note` is used as the summary verbatim.
"""
from __future__ import annotations
import json
import os
from ..base import Source, RawItem, register

CURATED_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "curated", "entries.json")


class Curated(Source):
    name = "Curated"
    enabled = True

    def fetch(self) -> list[RawItem]:
        if not os.path.exists(CURATED_PATH):
            return []
        entries = json.load(open(CURATED_PATH, encoding="utf-8"))
        out = []
        for i, e in enumerate(entries):
            sid = e.get("id") or f"{e.get('date','')}-{i}-{(e.get('title') or '')[:24]}"
            out.append(RawItem(
                source=e.get("source", "Curated"),
                source_id=sid,
                date=e["date"],
                title=e["title"],
                url=e.get("url", "#"),
                entity=e.get("entity"),
                stock_code=e.get("stock_code"),
                type_hint=e.get("type", "rumor"),
                summary=e.get("note"),          # curator one-liner → item summary
                raw_text=e.get("note"),
            ))
        return out


register(Curated())
