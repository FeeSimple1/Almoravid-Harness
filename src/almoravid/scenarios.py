"""Scenario raw JSON loader + state builder.

Two entry points:

- `load_scenario_raw(name)` returns the parsed scenario JSON dict
  without further processing.
- `load_scenario(name, seed=0)` returns a fully populated `GameState`
  ready to play (Phase 1b state-build only; later phases refine).

Open work (will be logged as Q-NNN if it stays ambiguous):
  - Per-box turn_type encoding: each box is one "40 Days" period
    containing both Levy and Campaign sub-phases (SoP §2.2). Phase 1b
    sets all non-winter boxes to "campaign" (mostly a placeholder) and
    boxes 7-8 / 15-16 to "winter". Phase 2 (Levy mechanics) refines.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, cast

from almoravid.state import (
    Calendar,
    CalendarBox,
    CardInPlay,
    Cylinder,
    Decks,
    GameState,
    HistoryEntry,
    Locale,
    Lord,
    Meta,
    Score,
    ServiceMarker,
    Side,
    Taifa,
    Vassal,
    Way,
)
from almoravid.static_data import (
    load_cards,
    load_locales,
    load_lords,
    load_taifas,
    load_ways,
)

PACKAGE = "almoravid.data.scenarios"
SCENARIOS_DIR = Path(__file__).parent / "data" / "scenarios"


# Season for each Calendar box. Two boxes per season, four seasons per
# year, two years (1085-1086).
_SEASON_BY_BOX: dict[int, str] = {}
for _yr in range(2):
    for _i, _s in enumerate(("spring", "summer", "autumn", "winter")):
        _SEASON_BY_BOX[1 + _yr * 8 + _i * 2] = _s
        _SEASON_BY_BOX[2 + _yr * 8 + _i * 2] = _s


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def scenario_path(name: str) -> Path:
    p = SCENARIOS_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Unknown scenario: {name!r}. Known: {', '.join(list_scenarios())}"
        )
    return p


def load_scenario_raw(name: str) -> dict[str, Any]:
    """Parse a scenario JSON file by stem. No conversion."""
    text = resources.files(PACKAGE).joinpath(f"{name}.json").read_text(encoding="utf-8")
    return json.loads(text)


def load_scenario(name: str, seed: int = 0) -> GameState:
    """Build a fully populated GameState from a scenario id.

    Phase 1b implementation: assembles Calendar, Locales, Taifas, Ways,
    Lords (mustered/set-aside/calendar/removed), Decks (held events,
    capabilities in play, board-edge cards). Per-card effect logic and
    derived state (Lord-on-mat winter-disband, Curias trigger, etc.)
    is Phase 2+ work.
    """
    raw = load_scenario_raw(name)

    # ---- Meta -----------------------------------------------------
    meta = Meta(
        scenario_id=raw["scenario_id"],
        scenario_letter=raw["scenario_letter"],
        seed=seed,
        active_player=cast(Side, raw.get("active_player_at_start", "christian")),
        phase="setup",
        turn_index=0,
    )

    # ---- Calendar -------------------------------------------------
    boxes: list[CalendarBox] = []
    for box_n in range(1, 17):
        season = _SEASON_BY_BOX[box_n]
        # turn_type stub: Scenario F's winter sequence applies to 7-8;
        # 15-16 are also winter by season. Phase 2 will set this from
        # rules (Levy/Campaign sub-phases, Scenario F Winter, Curias).
        turn_type = "winter" if season == "winter" else "campaign"
        boxes.append(CalendarBox(
            number=box_n, season=season, turn_type=turn_type,
        ))

    # Apply scenario calendar decorations
    levy_box = raw["start_box"]
    service_markers: list[ServiceMarker] = []
    for entry in raw.get("calendar", []):
        b = entry["box"]
        box = boxes[b - 1]
        decorations: list[str] = []
        if entry.get("levy_campaign_marker"):
            decorations.append(f"levy_campaign:{entry['levy_campaign_marker']}")
            levy_box = b
        if entry.get("scenario_end"):
            decorations.append("scenario_end")
        if entry.get("victory_marker_color"):
            decorations.append(f"victory:{entry['victory_marker_color']}")
        for color in entry.get("victory_markers", []):
            decorations.append(f"victory:{color}")
        for cyl in entry.get("cylinders", []):
            box.cylinder_lord_ids.append(cyl)
        for sm in entry.get("service_markers", []):
            service_markers.append(ServiceMarker(lord_id=sm, box=b))
        box.decorations.extend(decorations)

    calendar = Calendar(
        boxes=boxes,
        current_box=levy_box,
        service_markers=service_markers,
    )

    # ---- Taifas ---------------------------------------------------
    taifa_static = load_taifas()
    taifas_state: dict[str, Taifa] = {}
    locale_taifa: dict[str, list[str]] = {}  # taifa_id -> [locale_id...]
    for loc_id, loc in load_locales()["locales"].items():
        if loc["territory"] in taifa_static["taifas"]:
            locale_taifa.setdefault(loc["territory"], []).append(loc_id)
    for tid, t in taifa_static["taifas"].items():
        status = raw.get("taifa_status", {}).get(tid, "independent")
        # Toledo can never be Independent (rule 1.4.1)
        if t.get("never_independent") and status == "independent":
            status = "parias"
        taifas_state[tid] = Taifa(
            id=tid,
            name=t["name"],
            locale_ids=locale_taifa.get(tid, []),
            status=status,
            status_marker_count=0 if status == "independent" else t["status_boxes"],
        )

    # ---- Locales --------------------------------------------------
    locales_state: dict[str, Locale] = {}
    for loc_id, loc in load_locales()["locales"].items():
        locales_state[loc_id] = Locale(
            id=loc_id,
            name=loc["name"],
            territory=loc["territory"],
            base_type=loc["base_type"],
            has_gardens=loc["gardens"],
            has_port=loc["port"],
            is_reconquista_target=loc["reconquista_target"],
            seat_marker_lord_ids=list(loc["printed_seats"]),
        )
    # Apply per-locale scenario markers
    for entry in raw.get("locale_markers", []):
        lid = entry["locale_id"]
        loc = locales_state[lid]
        if "conquered_yellow" in entry:
            loc.conquered_markers = entry["conquered_yellow"]
        if "conquered_green" in entry:
            # Christian-on-Muslim conquered_markers and Muslim-on-Christian
            # both store in conquered_markers; the side is encoded by where
            # the Locale lives. Phase 2 will refine if needed.
            loc.conquered_markers += entry["conquered_green"]
        if "jihad_markers" in entry:
            loc.jihad_markers = entry["jihad_markers"]
        if "ravaged" in entry:
            loc.ravaged = entry["ravaged"]
        if "siege_yellow" in entry:
            loc.siege_yellow = entry["siege_yellow"]
        if "siege_green" in entry:
            loc.siege_green = entry["siege_green"]
        if "bypass_yellow" in entry:
            loc.bypass_yellow = entry["bypass_yellow"]
        if "bypass_green" in entry:
            loc.bypass_green = entry["bypass_green"]
        if "seat_marker_lord_ids" in entry:
            for lord_id in entry["seat_marker_lord_ids"]:
                if lord_id not in loc.seat_marker_lord_ids:
                    loc.seat_marker_lord_ids.append(lord_id)

    # ---- Lords ----------------------------------------------------
    lord_static = load_lords()["lords"]
    lords_state: dict[str, Lord] = {}

    mustered_index = {m["lord_id"]: m for m in raw.get("mustered_lords", [])}
    set_aside = set(raw.get("set_aside_lord_ids", []))
    removed = set(raw.get("removed_from_play_lord_ids", []))
    on_calendar_box: dict[str, int] = {}
    for entry in raw.get("calendar", []):
        for cyl in entry.get("cylinders", []):
            on_calendar_box[cyl] = entry["box"]

    for lid, l in lord_static.items():
        # Pick cylinder location for this Lord
        if lid in mustered_index:
            m = mustered_index[lid]
            cylinder = Cylinder(kind="locale", locale_id=m["locale_id"])
            forces = dict(l["forces"])
            assets = dict(l["assets"])
            if "assets_override" in m:
                assets.update(m["assets_override"])
            capabilities = list(m.get("capabilities", []))
        elif lid in set_aside:
            cylinder = Cylinder(kind="set_aside")
            forces = {}
            assets = {}
            capabilities = []
        elif lid in removed:
            cylinder = Cylinder(kind="removed")
            forces = {}
            assets = {}
            capabilities = []
        elif lid in on_calendar_box:
            cylinder = Cylinder(kind="calendar", box=on_calendar_box[lid])
            forces = {}  # Lord not yet mustered
            assets = {}
            capabilities = []
        else:
            # Default: off-calendar / not yet in play
            cylinder = Cylinder(kind="set_aside")
            forces = {}
            assets = {}
            capabilities = []

        vassals = [
            Vassal(id=f"{lid}_v{i+1}",
                   name=v["name"],
                   forces=v["forces"],
                   service_cost=v["service_cost"])
            for i, v in enumerate(l["vassals"])
        ] if cylinder.kind == "locale" else []

        lords_state[lid] = Lord(
            id=lid,
            name=l["name"],
            side=l["side"],
            is_taifa=l["is_taifa"],
            home_taifa=l["home_taifa"],
            seats=list(l["seats"]),
            fealty=l["fealty"],
            service_rating=l["service"],
            lordship_rating=l["lordship"],
            command_rating=l["command"],
            cylinder=cylinder,
            forces=forces,
            assets=assets,
            capabilities=capabilities,
            vassals=vassals,
        )

    # ---- Ways -----------------------------------------------------
    ways_state = [
        Way(a=w["a"], b=w["b"], way_type=w["way_type"])
        for w in load_ways()["ways"]
    ]

    # ---- Decks ----------------------------------------------------
    held: dict[Side, list[str]] = {}
    for side_str, card_ids in raw.get("events_held", {}).items():
        side = cast(Side, side_str)
        held[side] = list(card_ids)
    board_edge: dict[Side, list[str]] = {}
    if raw.get("muslim_board_edge_cards"):
        board_edge["muslim"] = list(raw["muslim_board_edge_cards"])
    if raw.get("christian_board_edge_cards"):
        board_edge["christian"] = list(raw["christian_board_edge_cards"])

    # Build CardInPlay entries for capabilities sitting on Lord mats.
    cards_static = load_cards()["cards"]
    capabilities_in_play: list[CardInPlay] = []
    for lid, lord in lords_state.items():
        for cap_id in lord.capabilities:
            scope = cards_static.get(cap_id, {}).get("capability_scope") or "this_lord"
            capabilities_in_play.append(CardInPlay(
                card_id=cap_id,
                scope=scope,
                owner_side=lord.side,
                owner_lord_id=lid,
            ))

    decks = Decks(
        draw=[], discard=[], held=held,
        capabilities_in_play=capabilities_in_play,
        board_edge=board_edge,
    )

    # ---- Score ----------------------------------------------------
    sv = raw["starting_vp"]
    score = Score(christian=float(sv["christian"]), muslim=float(sv["muslim"]))

    state = GameState(
        meta=meta,
        calendar=calendar,
        lords=lords_state,
        locales=locales_state,
        taifas=taifas_state,
        ways=ways_state,
        decks=decks,
        history=[HistoryEntry(
            turn_index=0, actor="system", action="load_scenario",
            args={"scenario": name, "seed": seed},
            summary=f"Loaded scenario {raw['scenario_letter']}: {raw['name']}",
        )],
        score=score,
    )
    return state
