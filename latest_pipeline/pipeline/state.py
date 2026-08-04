"""Dedupe state. `seen.json` records the id -> content-hash of every item the
pipeline has ever processed, so re-runs are idempotent and only genuinely new or
changed items are sent to the (potentially paid) enrichment step.
"""
from __future__ import annotations
import hashlib
import json
import os
from .base import RawItem, make_id

SEEN_PATH_DEFAULT = "site/data/seen.json"


def content_hash(r: RawItem) -> str:
    basis = f"{r.date}|{r.title}|{r.url}".encode("utf-8")
    return hashlib.sha1(basis).hexdigest()[:16]


class SeenStore:
    def __init__(self, path: str = SEEN_PATH_DEFAULT):
        self.path = path
        self.seen: dict[str, str] = {}
        if os.path.exists(path):
            try:
                self.seen = json.load(open(path))
            except Exception:
                self.seen = {}

    def is_new_or_changed(self, r: RawItem) -> bool:
        iid = make_id(r.source, r.source_id)
        return self.seen.get(iid) != content_hash(r)

    def mark(self, r: RawItem) -> None:
        self.seen[make_id(r.source, r.source_id)] = content_hash(r)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.seen, open(self.path, "w"), indent=0, sort_keys=True)
