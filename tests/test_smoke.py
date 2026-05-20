"""Phase 0 smoke tests.

These cover:
  - Package imports.
  - CLI `version` and `scenarios` commands work.
  - All bundled scenario JSONs parse.
  - GameState pydantic schema generates and matches the checked-in file.
  - State invariants the BRIEF / FUTURE_PROJECTS_LESSONS.md call out at
    the structural level can be expressed (off-edge lanes exist, Ways
    carry way_type, CardInPlay has scope, Lord declares cleanup
    contract).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from almoravid import __version__  # noqa: E402
from almoravid.scenarios import list_scenarios, load_scenario_raw  # noqa: E402
from almoravid.state import (  # noqa: E402
    Calendar,
    CardInPlay,
    GameState,
    Lord,
    Way,
)


def test_version_matches_pyproject() -> None:
    """__version__ in package matches pyproject.toml."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert f'version = "{__version__}"' in pyproject


def test_cli_version_subcommand_runs() -> None:
    """`python -m almoravid.cli version` prints __version__."""
    result = subprocess.run(
        [sys.executable, "-m", "almoravid.cli", "version"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def test_scenarios_inventory() -> None:
    """All 6 scenarios (A-F) are bundled."""
    names = list_scenarios()
    assert len(names) == 6, names
    letters = {load_scenario_raw(n)["scenario_letter"] for n in names}
    assert letters == {"A", "B", "C", "D", "E", "F"}


@pytest.mark.parametrize("name", list_scenarios())
def test_each_scenario_parses(name: str) -> None:
    """Every bundled scenario JSON is well-formed."""
    data = load_scenario_raw(name)
    assert "scenario_id" in data
    assert data["scenario_letter"] in {"A", "B", "C", "D", "E", "F"}
    assert "starting_vp" in data
    assert "christian" in data["starting_vp"]
    assert "muslim" in data["starting_vp"]


def test_schema_file_is_fresh() -> None:
    """state.schema.json on disk matches the live model.

    If this fails, regenerate with `python scripts/generate_schema.py`.
    """
    on_disk = json.loads(
        (REPO_ROOT / "src" / "almoravid" / "data" / "schema" / "state.schema.json").read_text()
    )
    live = GameState.model_json_schema()
    assert on_disk == live, (
        "state.schema.json is stale. "
        "Regenerate with `python scripts/generate_schema.py`."
    )


def test_schema_has_expected_top_keys() -> None:
    """JSON schema exposes the canonical GameState shape."""
    schema = GameState.model_json_schema()
    expected_props = {
        "meta",
        "calendar",
        "lords",
        "locales",
        "taifas",
        "ways",
        "decks",
        "pending",
        "taifas_box_coin",
        "taifas_box_vp",
        "cathedral_seat_locales",
        "history",
        "score",
    }
    assert set(schema["properties"].keys()) == expected_props
    # In Pydantic JSON Schema, only fields without defaults are 'required'.
    # meta and calendar have no defaults; the rest have default_factory.
    required = set(schema.get('required', []))
    assert 'pending' not in required, 'pending is Optional and must not be required'
    assert {'meta', 'calendar'} <= required, f'core fields must be required, got {required}'



def test_calendar_has_off_edge_lanes() -> None:
    """Pattern 6: Calendar exposes off-left/right lanes for cylinders AND service markers, separately."""
    fields = Calendar.model_fields
    assert "off_left" in fields
    assert "off_right" in fields
    assert "off_left_service" in fields
    assert "off_right_service" in fields


def test_way_carries_way_type() -> None:
    """Pattern 4: Way model includes an explicit way_type so parallel Ways are distinguishable."""
    fields = Way.model_fields
    assert "way_type" in fields
    # Verify it's the right Literal
    way = Way(a="x", b="y", way_type="road")
    assert way.way_type == "road"


def test_card_in_play_has_scope() -> None:
    """Pattern 14: CardInPlay has an explicit scope field."""
    fields = CardInPlay.model_fields
    assert "scope" in fields
    c1 = CardInPlay(card_id="C1", scope="this_lord", owner_side="christian", owner_lord_id="alfonso")
    c2 = CardInPlay(card_id="C2", scope="side_wide", owner_side="muslim")
    assert c1.scope == "this_lord"
    assert c2.scope == "side_wide"


def test_lord_declares_lifecycle_cleanup_contract() -> None:
    """Pattern 8: Lord enumerates the fields that must be cleared on removal."""
    contract = Lord.cleanup_on_removal_fields
    assert isinstance(contract, tuple)
    # Spot-check the fields SMOKE-001/035/036/095 cared about.
    assert "in_stronghold" in contract
    assert "moved_fought" in contract
    assert "routed_units" in contract
    assert "vassals" in contract


def test_lord_can_be_built() -> None:
    """Sanity: a minimal Lord instance constructs without error."""
    from almoravid.state import Cylinder

    lord = Lord(
        id="alfonso",
        name="Alfonso VI",
        side="christian",
        service_rating=6,
        lordship_rating=2,
        command_rating=3,
        cylinder=Cylinder(kind="calendar", box=4),
    )
    assert lord.side == "christian"
    assert lord.cylinder.box == 4
