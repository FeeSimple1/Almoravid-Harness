"""Scenario raw JSON loader.

Phase 0: raw loader only. Phase 1 will add a scenario -> GameState
converter alongside `static_data.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).parent / "data" / "scenarios"


def list_scenarios() -> list[str]:
    """Return the canonical names of bundled scenarios (no extension)."""
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def scenario_path(name: str) -> Path:
    """Resolve a scenario name to its JSON path."""
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Unknown scenario: {name!r}. "
            f"Known scenarios: {', '.join(list_scenarios())}"
        )
    return path


def load_scenario_raw(name: str) -> dict[str, Any]:
    """Load a scenario's raw JSON without converting to GameState."""
    return json.loads(scenario_path(name).read_text())
