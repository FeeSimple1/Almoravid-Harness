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


def list_campaign_scenarios() -> list[str]:
    """Scenario ids that run the full Levy/Campaign cycle (i.e. NOT the
    battle-only minigames like Sagrajas). Campaign-flow tests iterate this."""
    import json as _json
    out = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            if not _json.loads(p.read_text()).get("battle_minigame"):
                out.append(p.stem)
        except Exception:
            out.append(p.stem)
    return out


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
    if raw.get("battle_minigame") == "sagrajas":
        return build_sagrajas(seed)

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
            # Printed pennants -> printed_seat_lord_ids (no Friendliness,
            # 1.3.1). seat_marker_lord_ids holds only PLACED markers, set
            # below for special Lords actually on the map (playtest F4).
            printed_seat_lord_ids=list(loc["printed_seats"]),
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

    for lid, lord_obj in lord_static.items():
        # Pick cylinder location for this Lord
        in_stronghold = False
        if lid in mustered_index:
            m = mustered_index[lid]
            cylinder = Cylinder(kind="locale", locale_id=m["locale_id"])
            forces = dict(lord_obj["forces"])
            assets = dict(lord_obj["assets"])
            if "assets_override" in m:
                assets.update(m["assets_override"])
            capabilities = list(m.get("capabilities", []))
            # A Lord Besieged at scenario start sits INSIDE the Stronghold
            # (e.g. Scenario D: al-Mustain Besieged at Zaragoza, 4.5/1.3.1).
            in_stronghold = bool(m.get("in_stronghold", False))
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
            for i, v in enumerate(lord_obj["vassals"])
        ] if cylinder.kind == "locale" else []

        lords_state[lid] = Lord(
            id=lid,
            name=lord_obj["name"],
            side=lord_obj["side"],
            is_taifa=lord_obj["is_taifa"],
            home_taifa=lord_obj["home_taifa"],
            seats=list(lord_obj["seats"]),
            fealty=lord_obj["fealty"],
            service_rating=lord_obj["service"],
            lordship_rating=lord_obj["lordship"],
            command_rating=lord_obj["command"],
            cylinder=cylinder,
            forces=forces,
            assets=assets,
            capabilities=capabilities,
            vassals=vassals,
            in_stronghold=in_stronghold,
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

    # Place the Almoravid double-Seat MARKER (Yusuf/Sir, 1.8/3.5) at its
    # printed Seat (Algeciras) only if Yusuf or Sir is Mustered on the
    # map at setup. Set-aside Lords have NO Seat marker (playtest F4).
    # Other placed Seat markers (Rodrigo, Cathedrals) arrive via play or
    # explicit scenario `seat_marker_lord_ids` entries.
    for _sp in ("yusuf", "sir"):
        _spl = lords_state.get(_sp)
        if _spl is not None and _spl.cylinder.kind == "locale":
            for _lid, _loc in locales_state.items():
                if _sp in _loc.printed_seat_lord_ids:
                    if _sp not in _loc.seat_marker_lord_ids:
                        _loc.seat_marker_lord_ids.append(_sp)

    # ---- Score ----------------------------------------------------
    sv = raw["starting_vp"]
    score = Score(christian=float(sv["christian"]), muslim=float(sv["muslim"]))

    # Taifas box: green 1VP Conquered markers count for the Muslims at
    # scoring (rules 1.4.2 / 5.1). compute_final_vp() sums taifas_box_vp,
    # so it MUST be seeded from setup or those Muslim VP are dropped at
    # the final tally (playtest F8). starting_vp feeds only the running
    # display Score; the authoritative compute_final_vp recomputes from
    # board markers + taifas_box_vp, so this is not double-counted.
    tb = raw.get("taifas_box", {}) or {}
    taifas_box_vp = float(tb.get("conquered_green_1vp", 0))

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
        taifas_box_vp=taifas_box_vp,
    )
    return state


# ---------------------------------------------------------------------------
# Battle of Sagrajas minigame (Background Book pp.44-47)
# ---------------------------------------------------------------------------

# Battlefield Locale: the Sagrajas region, the open plain near Badajoz where
# the army awaited Alfonso (Background Book). "sagrajas" is a real map Locale
# (base_type "region", territory "badajoz"); using it keeps the minigame
# thematically accurate. Capacity is irrelevant for a battle-only game.
_SAGRAJAS_LOCALE = "sagrajas"

# Rosters (Background Book "Lords, Vassals, and Capabilities").
_SAGRAJAS_CHRISTIANS = ["alfonso", "pedro_ansurez", "garcia_ordonez",
                        "alvar_fanez", "sancho"]
_SAGRAJAS_MUSLIMS = ["yusuf", "sir", "al_mutamid", "al_mutawakkil", "abd_allah"]


def _add_units(lord, units: dict) -> None:
    for ut, n in units.items():
        lord.forces[ut] = lord.forces.get(ut, 0) + n


def build_sagrajas(seed: int = 0) -> GameState:
    """Build the Battle of Sagrajas minigame as a battle-only GameState
    (Background Book pp.44-47). Deterministic setup (the seed only drives
    the stochastic Battle resolution). The state begins in phase 'battle'
    with a pending Christian 'Who Attacks?' decision; choosing attack
    (historical) or defend adds that branch's forces/cards, then the
    Battle is resolved (4.4) and whoever wins the Battle wins the game.

    "Any N Lords" / "any Lord mat" assignments are made DETERMINISTICALLY
    (documented inline), since the Background Book's array diagram is an
    image; the seed is not used for setup.
    """
    from almoravid.state import CardInPlay, Cylinder, PendingDecision

    # Reuse Scenario F's full static assembly (map / lords / ways / taifas)
    # as a skeleton, then reset it to the battle-only configuration.
    s = load_scenario("scenario_f_reconquista", seed=seed)
    s.meta.scenario_id = "sagrajas_battle"
    s.meta.scenario_letter = "S"
    s.meta.phase = "battle"
    s.meta.active_player = "christian"
    s.meta.sagrajas_role = None
    s.meta.turn_index = 0
    # Replace the inherited "Loaded scenario F" history line (build reuses
    # the Scenario F skeleton) so logs/repros read as Sagrajas.
    if s.history:
        s.history[0].summary = "Loaded scenario S: Battle of Sagrajas (minigame)"
        s.history[0].action = "load_sagrajas"
    s.score.christian = 0.0
    s.score.muslim = 0.0
    s.score.winner = None
    s.score.victory_reason = None
    s.calendar.service_markers = []
    # Reset campaign clutter inherited from the Scenario F skeleton: a
    # battle-only minigame has no Taifa politics / VP markers / Sieges.
    s.taifas_box_vp = 0.0
    s.taifas_box_coin = 0.0
    for loc in s.locales.values():
        loc.siege_yellow = 0
        loc.siege_green = 0
        loc.bypass_yellow = False
        loc.bypass_green = False
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
        loc.seat_marker_lord_ids = []
    s.decks.this_levy_events = {}
    s.decks.this_campaign_events = {}
    s.decks.held = {}
    s.decks.board_edge = {}
    s.decks.capabilities_in_play = []
    s.decks.draw = []
    s.pending = None

    lord_static = load_lords()["lords"]

    # Everyone off the board first.
    for lid, lord in s.lords.items():
        lord.cylinder = Cylinder(kind="set_aside")
        lord.forces = {}
        lord.capabilities = []
        lord.in_stronghold = False
        lord.is_lieutenant = False
        lord.lieutenant_of = None
        lord.routed_units = {}

    def muster(lid: str, include_vassals: bool = True,
               exclude_vassal_names: tuple[str, ...] = ()) -> None:
        lord = s.lords[lid]
        st = lord_static[lid]
        lord.cylinder = Cylinder(kind="locale", locale_id=_SAGRAJAS_LOCALE)
        lord.in_stronghold = False
        lord.forces = dict(st["forces"])
        if include_vassals:
            for v in st.get("vassals", []):
                if v["name"] in exclude_vassal_names:
                    continue
                _add_units(lord, v["forces"])

    # --- Christians: all starting + all Vassal Forces (Sancho: no Vassals).
    for lid in ("alfonso", "pedro_ansurez", "garcia_ordonez", "alvar_fanez"):
        muster(lid, include_vassals=True)
    muster("sancho", include_vassals=False)

    # Bishoprics (C22): one Bishop Vassal to EACH of Alfonso, Pedro, Garcia
    # (Lords.txt Bishop markers: Edenoro 1K+1Mi, Pedro-of-Leon 1K+1MaA,
    # Vistuario 1K+1Mi). Card sits at the Christian board edge (side_wide).
    _add_units(s.lords["alfonso"], {"knights": 1, "militia": 1})
    _add_units(s.lords["pedro_ansurez"], {"knights": 1, "men_at_arms": 1})
    _add_units(s.lords["garcia_ordonez"], {"knights": 1, "militia": 1})
    s.decks.board_edge.setdefault("christian", []).append("C22")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C22", scope="side_wide", owner_side="christian",
        owner_lord_id=None))

    # Milites (C18, side_wide): any two Christian Lords add 4 Light Horse +
    # 2 Militia total (3 units each). Deterministic: Pedro & Garcia.
    _add_units(s.lords["pedro_ansurez"], {"light_horse": 2, "militia": 1})
    _add_units(s.lords["garcia_ordonez"], {"light_horse": 2, "militia": 1})
    s.decks.board_edge.setdefault("christian", []).append("C18")
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id="C18", scope="side_wide", owner_side="christian",
        owner_lord_id=None))

    # Arqueros Bowmen (C4 and C5): one copy at each of any two Christian
    # Lords. Deterministic: C4 -> Alfonso, C5 -> Sancho. (this_lord cap;
    # the resolver gates Bowmen rows on these card_ids.)
    s.lords["alfonso"].capabilities.append("C4")
    s.lords["sancho"].capabilities.append("C5")
    for lid, cid in (("alfonso", "C4"), ("sancho", "C5")):
        s.decks.capabilities_in_play.append(CardInPlay(
            card_id=cid, scope="this_lord", owner_side="christian",
            owner_lord_id=lid))

    # --- Muslims: all starting + all Vassal Forces, EXCEPT Abd Allah drops
    # his Light Horse Vassal (Al-Mutasim, Emir of Almeria).
    for lid in ("yusuf", "sir", "al_mutamid", "al_mutawakkil"):
        muster(lid, include_vassals=True)
    muster("abd_allah", include_vassals=True,
           exclude_vassal_names=("Al-Mutasim, Emir of Almeria",))

    # Alrama Bowmen (M4 and M5): one each at two Muslim Taifa Lords (not
    # Yusuf/Sir). Deterministic: M4 -> al-Mutamid, M5 -> al-Mutawakkil.
    s.lords["al_mutamid"].capabilities.append("M4")
    s.lords["al_mutawakkil"].capabilities.append("M5")
    for lid, cid in (("al_mutamid", "M4"), ("al_mutawakkil", "M5")):
        s.decks.capabilities_in_play.append(CardInPlay(
            card_id=cid, scope="this_lord", owner_side="muslim",
            owner_lord_id=lid))

    # Muslims hold M7 Spear Wall to play at the outset of Battle.
    s.decks.this_levy_events.setdefault("muslim", []).append("M7")

    # NOTE (documented limitation): the Background Book also gives Yusuf and
    # Sir a Javelins marker for their AFRICAN HORSE. The harness models
    # Javelins (C7/M3/M6) for Unarmored Foot/Light Horse only (forces.json
    # has no African-Horse Javelin row), so the African-Horse Javelins
    # marker is not represented. Recorded in RULES_QUESTIONS (Sagrajas note).

    # Pending: the Christian player decides Attack (historical) or Defend.
    s.meta.active_player = "christian"
    s.pending = PendingDecision(kind="sagrajas_who_attacks",
                                waiting_on="christian", payload={})
    return s
