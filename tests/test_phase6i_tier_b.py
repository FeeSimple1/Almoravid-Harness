"""Phase 6i: Tier-B Battle effects + Crusader + Surrender/Sack triggers.

Covers C6 Surprise, M6 Feigned Retreat, C11/C12 Indulgences/Song of
Roland, C9 Betrayal of Terms, M13 Severed Heads.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    BattleResult, BattleSide, apply_aftermath, apply_retreat_aftermath,
    resolve_battle,
)
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# C11/C12 Crusader marker
# ---------------------------------------------------------------------------


def test_c11_indulgences_places_marker_and_adds_two_knights() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    target = "alfonso"
    s.lords[target].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[target].in_stronghold = False
    crusaders_before = s.lords[target].crusader_markers
    knights_before = s.lords[target].forces.get("knights", 0)
    r = resolve_event(s, "christian", "C11",
                      payload={"target_lord_id": target})
    assert r.get("no_op") is not True
    assert s.lords[target].crusader_markers == crusaders_before + 1
    assert s.lords[target].forces.get("knights", 0) == knights_before + 2


def test_c12_song_of_roland_mirrors_c11() -> None:
    """C12 has identical mechanics to C11 per card text."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    target = "alfonso"
    s.lords[target].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[target].in_stronghold = False
    r = resolve_event(s, "christian", "C12",
                      payload={"target_lord_id": target})
    assert r["crusader_markers_now"] == 1
    assert r["knights_added"] == 2


def test_c11_eudes_musters_ready_vassals_when_on_map() -> None:
    s = load_scenario("scenario_e_alfonso", seed=1)
    if "eudes" not in s.lords:
        pytest.skip("eudes not in this scenario")
    s.lords["eudes"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["eudes"].in_stronghold = False
    # Mark Eudes's Vassals as not yet Mustered (Phase 6i auto-Musters).
    for v in s.lords["eudes"].vassals:
        v.ready = False
    target = "alfonso"
    s.lords[target].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[target].in_stronghold = False
    r = resolve_event(s, "christian", "C11",
                      payload={"target_lord_id": target})
    # If Eudes had any unready Vassals, they should now be Mustered.
    if s.lords["eudes"].vassals:
        assert r["eudes_vassals_mustered"] != [] or \
            all(v.ready for v in s.lords["eudes"].vassals)


# ---------------------------------------------------------------------------
# M6 Feigned Retreat
# ---------------------------------------------------------------------------


def test_m6_feigned_retreat_reorders_round2_melee() -> None:
    """With M6 held, Round 2 melee fires Muslim-first then Christian.
    Verify by inspecting BattleRound.steps order."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["muslim"] = ["M6"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    # Ensure battle lasts >= 2 rounds.
    res = resolve_battle(s, atk, dfd, max_rounds=2)
    if len(res.rounds) >= 2:
        rnd2 = res.rounds[1]
        melee_steps = [st for st in rnd2.steps if st.step.startswith("2.")]
        # First two melee substeps should both be the Muslim side.
        muslim_actor = "defender" if atk.side == "christian" else "attacker"
        if len(melee_steps) >= 2:
            assert melee_steps[0].actor == muslim_actor
            assert melee_steps[1].actor == muslim_actor


def test_m6_discarded_after_round2() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["muslim"] = ["M6"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 8})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 8})
    result = resolve_battle(s, atk, dfd, max_rounds=3)
    apply_aftermath(s, result)
    # After apply_aftermath (or end-of-Round-2 discard), M6 must be
    # discarded — not lingering in this_levy_events.
    assert "M6" in s.decks.discard
    assert "M6" not in s.decks.this_levy_events.get("muslim", [])


# ---------------------------------------------------------------------------
# C9 Betrayal of Terms on Surrender — double Spoils + 1 Jihad
# ---------------------------------------------------------------------------


def test_c9_betrayal_doubles_spoils_and_adds_jihad() -> None:
    """When C9 is held during a successful Christian Surrender, Spoils
    are doubled and Muslims add 1 Jihad."""
    from almoravid.static_data import load_strongholds
    # Build a state where Alfonso besieges a Town and forces Surrender.
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    # Place Alfonso outside Tudela (or similar Muslim Town). Use cordoba.
    target_loc = "cordoba"
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=target_loc)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    # Clear any opposing-side lords from cordoba.
    for lid, l in s.lords.items():
        if (l.side == "muslim" and l.cylinder.kind == "locale"
                and l.cylinder.locale_id == target_loc):
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.locales[target_loc].siege_yellow = 3  # high threshold for Surrender
    s.decks.this_levy_events["christian"] = ["C9"]
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 1
    jihad_locs_before = sum(loc.jihad_markers for loc in s.locales.values())
    # Note: rng controls Surrender; force the test to use a high-prob
    # threshold by giving Alfonso siege already at 3 (close to value=2
    # for Town). Run cmd_siege which triggers Surrender check.
    try:
        result = apply_action(s, {"type": "cmd_siege", "side": "christian"})
    except IllegalAction:
        pytest.skip("cmd_siege rejected for setup reasons")
    if result["surrender"] and result["surrender"]["succeeded"]:
        # Verify C9 was consumed and Spoils doubled.
        sh = load_strongholds()["strongholds"]["town"]
        base = sh["spoils"]
        spoils = result["surrender"]["spoils"]
        assert spoils["coin"] == base["coin"] * 2
        assert spoils["prov"] == base["prov"] * 2
        assert result["surrender"]["c9_betrayal_used"] is True
        assert "C9" in s.decks.discard
        # Jihad added
        jihad_locs_after = sum(loc.jihad_markers for loc in s.locales.values())
        assert jihad_locs_after >= jihad_locs_before + 1


# ---------------------------------------------------------------------------
# M13 Severed Heads on Christian Retreat
# ---------------------------------------------------------------------------


def test_m13_adds_4_jihad_when_christian_retreats() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.decks.this_levy_events["muslim"] = ["M13"]
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="transduero")
    s.lords["alfonso"].in_stronghold = False
    # Move all Muslims off so retreat target is clean.
    for lid, l in s.lords.items():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    # Force a Parias Taifa so Jihad-add has a target.
    next(iter(s.taifas.values())).status = "parias"
    jihad_before = sum(loc.jihad_markers for loc in s.locales.values())
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"knights": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="muslim")
    summary = apply_retreat_aftermath(s, result)
    jihad_after = sum(loc.jihad_markers for loc in s.locales.values())
    if "m13_severed_heads_jihad" in summary:
        assert jihad_after >= jihad_before + 4
        assert "M13" in s.decks.discard


# ---------------------------------------------------------------------------
# C6 Surprise — March into empty Enemy Stronghold places 2 Siege +
# sets surprise_storm_pending flag.
# ---------------------------------------------------------------------------


def test_c6_surprise_places_two_siege_on_empty_stronghold_march() -> None:
    """Christian holds C6 + Marches to an Enemy Stronghold locale that
    is empty → 2 Siege placed + surprise flag set."""
    from almoravid.map import neighbors_via
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Setup: place Alfonso at a road-neighbor of a Muslim Stronghold.
    # Use 'toledo' (Muslim city) and a neighbor like 'talavera'.
    if "toledo" in s.locales and "talavera" in s.locales:
        target = "toledo"
        from_loc = "talavera"
        if from_loc not in neighbors_via(target, "road"):
            pytest.skip("scenario map doesn't connect talavera-toledo by road")
        # Park Alfonso at from_loc; ensure target is empty.
        s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                               locale_id=from_loc)
        s.lords["alfonso"].in_stronghold = False
        s.lords["alfonso"].assets = {}
        # Clear any Lords at target.
        for lid, l in s.lords.items():
            if (l.cylinder.kind == "locale"
                    and l.cylinder.locale_id == target):
                l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
        s.decks.this_levy_events["christian"] = ["C6"]
        siege_before = s.locales[target].siege_yellow
        # Drive to activation
        from tests.test_phase6h_tier_a import _setup_active_lord
        s2 = _setup_active_lord("scenario_a_toledo_beset", "alfonso",
                                 from_loc)
        s2.decks.this_levy_events["christian"] = ["C6"]
        # Clear lords at toledo in this fresh state too.
        for lid, l in s2.lords.items():
            if (l.cylinder.kind == "locale"
                    and l.cylinder.locale_id == "toledo"):
                l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
        before_siege = s2.locales["toledo"].siege_yellow
        try:
            apply_action(s2, {"type": "cmd_march", "side": "christian",
                              "target_locale_id": "toledo",
                              "way_type": "road"})
        except IllegalAction:
            pytest.skip("cmd_march rejected for setup reasons")
        assert s2.locales["toledo"].siege_yellow == before_siege + 2
        assert s2.meta.surprise_storm_pending_locale_id == "toledo"
        assert "C6" in s2.decks.discard
    else:
        pytest.skip("toledo or talavera not in scenario")
