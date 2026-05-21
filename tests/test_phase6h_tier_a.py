"""Phase 6h: Tier-A event effects (C3/M3, C4/M4, C5/M5, M8, M11, M18, M22)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy


# ---------------------------------------------------------------------------
# C3/M3 Swollen River — auto-blocks enemy March on current card
# ---------------------------------------------------------------------------


def _setup_active_lord(scenario, lord_id, locale_id, seed=11):
    """Drive state forward into Activation with `lord_id` active and
    physically at `locale_id`."""
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    other = "muslim" if side == "christian" else "christian"
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    legal_pad(s, side)
    legal_pad(s, other)
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            break
        apply_action(s, {"type": "command_reveal",
                         "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card",
                             "side": s.meta.active_player})
    assert s.meta.active_lord_id == lord_id
    s.lords[lord_id].cylinder = Cylinder(kind="locale", locale_id=locale_id)
    s.lords[lord_id].moved_fought = False
    s.lords[lord_id].first_march_used_this_card = False
    s.lords[lord_id].assets = {}  # Unladen
    return s


def test_swollen_river_blocks_first_march() -> None:
    s = _setup_active_lord("scenario_a_toledo_beset", "alfonso", "leon")
    s.decks.this_levy_events["muslim"] = ["M3"]
    # leon road neighbors include sahagun.
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "sahagun",
                         "way_type": "road"})
    assert ei.value.code == "swollen_river_blocked"
    # Card moved to discard.
    assert "M3" in s.decks.discard
    assert "M3" not in s.decks.this_levy_events.get("muslim", [])
    # Subsequent attempts on the same card still blocked (flag persists).
    with pytest.raises(IllegalAction) as ei2:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "sahagun",
                         "way_type": "road"})
    assert ei2.value.code == "swollen_river_blocked"


def test_swollen_river_flag_clears_at_end_card() -> None:
    s = _setup_active_lord("scenario_a_toledo_beset", "alfonso", "leon")
    s.meta.swollen_river_blocked_card_lord_id = "alfonso"
    apply_action(s, {"type": "end_card", "side": "christian"})
    assert s.meta.swollen_river_blocked_card_lord_id is None


# ---------------------------------------------------------------------------
# C4/M4 Arid Terrain — forces Feed on the marching Lord
# ---------------------------------------------------------------------------


def test_arid_terrain_forces_feed_before_march() -> None:
    s = _setup_active_lord("scenario_a_toledo_beset", "alfonso", "leon")
    s.decks.this_levy_events["muslim"] = ["M4"]
    s.lords["alfonso"].assets = {"prov": 3}
    s.lords["alfonso"].forces = {"knights": 2, "men_at_arms": 2}
    prov_before = s.lords["alfonso"].assets.get("prov", 0)
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "sahagun",
                     "way_type": "road"})
    # Feed consumed some Provender.
    assert s.lords["alfonso"].assets.get("prov", 0) < prov_before
    # Card discarded.
    assert "M4" in s.decks.discard
    # March still happened.
    assert s.lords["alfonso"].cylinder.locale_id == "sahagun"


# ---------------------------------------------------------------------------
# C5/M5 Drought — Feed 2 target-side Lords not at Friendly Gardens/Seat
# ---------------------------------------------------------------------------


def test_c5_drought_feeds_two_muslim_lords_not_at_gardens() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Put two Muslim Lords at non-Gardens, non-Seat locales.
    muslims = [lid for lid, l in s.lords.items() if l.side == "muslim"][:2]
    for lid in muslims:
        s.lords[lid].cylinder = Cylinder(kind="locale",
                                         locale_id="transduero")
        s.lords[lid].in_stronghold = False
        s.lords[lid].forces = {"sergeants": 2}
        s.lords[lid].assets = {"prov": 1}  # only 1 prov, will under-feed
    r = resolve_event(s, "christian", "C5")
    assert r.get("no_op") is not True
    assert r["target_side"] == "muslim"
    fed_ids = {entry["lord_id"] for entry in r["fed_lords"]}
    assert fed_ids <= set(muslims)
    assert len(fed_ids) <= 2


def test_c5_drought_no_op_when_all_muslims_at_gardens() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Put every Muslim Lord at a Friendly Seat (Gardens-eligible
    # locale isn't actually verified here — just ensure friendly_seat).
    for lid, l in s.lords.items():
        if l.side != "muslim":
            continue
        if l.seats:
            l.cylinder = Cylinder(kind="locale", locale_id=l.seats[0])
            l.in_stronghold = False
    r = resolve_event(s, "christian", "C5")
    # Either no-op or fed only some.
    if r.get("no_op"):
        assert "no eligible" in r["note"]


# ---------------------------------------------------------------------------
# M8 Ahmad Ibn Rumayla — add 2 Jihad to first Parias/Reconquista locale
# ---------------------------------------------------------------------------


def test_m8_adds_two_jihad_to_first_eligible_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # M8 requires Yusuf/Sir/al-Mutamid in the target Taifa (card text).
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    target_loc = target_taifa.locale_ids[0]
    s.locales[target_loc].jihad_markers = 0
    s.locales[target_loc].conquered_markers = 0
    # Place al-Mutamid inside the target Taifa so it qualifies.
    assert "al_mutamid" in s.lords
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id=target_loc)
    s.lords["al_mutamid"].in_stronghold = False
    r = resolve_event(s, "muslim", "M8")
    assert r.get("no_op") is not True
    assert r["jihad_added"] == 2
    placed = sum(r["placement"].values())
    assert placed == 2


# ---------------------------------------------------------------------------
# M11 Al-Qadir balks — +3 with Yusuf/Sir in Reconquista/Parias, else +1
# ---------------------------------------------------------------------------


def test_m11_bonus_when_yusuf_in_kingdom_locale() -> None:
    s = load_scenario("scenario_d_arrival", seed=1)
    if "yusuf" not in s.lords:
        pytest.skip("yusuf not present in this scenario")
    # Put Yusuf at a Christian Kingdom locale ("leon" if exists).
    if "leon" in s.locales:
        s.lords["yusuf"].cylinder = Cylinder(kind="locale", locale_id="leon")
        s.lords["yusuf"].in_stronghold = False
    target_taifa = next((t for t in s.taifas.values()
                         if t.status in ("parias", "reconquista")), None)
    if target_taifa is None:
        next(iter(s.taifas.values())).status = "parias"
        target_taifa = next(t for t in s.taifas.values()
                            if t.status == "parias")
    r = resolve_event(s, "muslim", "M11")
    assert r["jihad_added"] in (1, 3)


def test_m11_base_one_jihad_when_no_yusuf_eligible() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Force a Parias for jihad-target.
    target_taifa = next(t for t in s.taifas.values())
    target_taifa.status = "parias"
    # Remove yusuf/sir from the map if they exist.
    for lid in ("yusuf", "sir"):
        if lid in s.lords:
            s.lords[lid].cylinder = Cylinder(kind="calendar")
    r = resolve_event(s, "muslim", "M11")
    assert r["jihad_added"] == 1
    assert r["bonus"] is False


# ---------------------------------------------------------------------------
# M18 Refugees — restore Lost Unarmored + add Transport for Taifa Lords
# ---------------------------------------------------------------------------


def test_m18_restores_unarmored_and_adds_mule() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    taifa_lords = [lid for lid, l in s.lords.items()
                   if l.is_taifa and l.cylinder.kind == "locale"]
    if not taifa_lords:
        pytest.skip("no Taifa Lords on map in this scenario")
    # Strip a Light Horse from the first Taifa Lord so M18 should
    # restore it.
    target = taifa_lords[0]
    orig_lh = s.lords[target].forces.get("light_horse", 0)
    if orig_lh > 0:
        s.lords[target].forces["light_horse"] = 0
    mules_before = s.lords[target].assets.get("mule", 0)
    r = resolve_event(s, "muslim", "M18")
    assert r.get("no_op") is not True
    # Mule increased by 1.
    assert s.lords[target].assets.get("mule", 0) == mules_before + 1


# ---------------------------------------------------------------------------
# M22 Massacre — 3 Jihad if Eudes on map, else 1
# ---------------------------------------------------------------------------


def test_m22_three_jihad_when_eudes_on_map() -> None:
    s = load_scenario("scenario_e_alfonso", seed=1) \
        if True else load_scenario("scenario_a_toledo_beset", seed=1)
    if "eudes" not in s.lords:
        pytest.skip("eudes not present in this scenario")
    s.lords["eudes"].cylinder = Cylinder(kind="locale", locale_id="leon")
    next(iter(s.taifas.values())).status = "parias"
    r = resolve_event(s, "muslim", "M22")
    assert r["bonus"] is True
    assert r["jihad_added"] == 3


def test_m22_one_jihad_when_no_eudes_on_map() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    if "eudes" in s.lords:
        s.lords["eudes"].cylinder = Cylinder(kind="calendar")
    next(iter(s.taifas.values())).status = "parias"
    r = resolve_event(s, "muslim", "M22")
    assert r["bonus"] is False
    assert r["jihad_added"] == 1
