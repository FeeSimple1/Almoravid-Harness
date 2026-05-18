"""Cached loaders for the static reference data under data/static/.

Each loader is decorated with @lru_cache so the JSON files are read
once per process. Phase 1b API; Phase 2+ may add typed wrappers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

PACKAGE = "almoravid.data.static"


def _read(name: str) -> Any:
    text = resources.files(PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def load_taifas() -> dict[str, Any]:
    """Return the parsed taifas.json. Cached."""
    return _read("taifas.json")


@lru_cache(maxsize=1)
def load_locales() -> dict[str, Any]:
    """Return the parsed locales.json. Cached."""
    return _read("locales.json")


@lru_cache(maxsize=1)
def load_ways() -> dict[str, Any]:
    """Return the parsed ways.json. Cached."""
    return _read("ways.json")


@lru_cache(maxsize=1)
def load_lords() -> dict[str, Any]:
    """Return the parsed lords.json. Cached."""
    return _read("lords.json")


@lru_cache(maxsize=1)
def load_cards() -> dict[str, Any]:
    """Return the parsed cards.json. Cached."""
    return _read("cards.json")


def neighbors(locale_id: str) -> list[tuple[str, str]]:
    """List (other_locale_id, way_type) tuples reachable from `locale_id`.

    Pattern 4 (parallel Ways): returns a tuple per (neighbor, way_type),
    not per neighbor — callers that need way-type-aware behaviour must
    consume the way_type. Almoravid's 1085-1086 map has no parallel
    pairs currently, but the API stays robust to a future change.
    """
    ways = load_ways()["ways"]
    out: list[tuple[str, str]] = []
    for w in ways:
        if w["a"] == locale_id:
            out.append((w["b"], w["way_type"]))
        elif w["b"] == locale_id:
            out.append((w["a"], w["way_type"]))
    return out
