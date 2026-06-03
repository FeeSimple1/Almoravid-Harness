"""Multi-Lord Array tactical choices — rule 4.4.2 Reposition / Flanking.

The rules make several Array placements the owner's choice (DECISION-005):
a CENTER Flanker may Strike left or right; an empty Front-center is filled
from a chosen side Front slot; and which Reserve Lord Advances first is the
owner's pick. These were previously resolved deterministically. They are
now exposed via per-side standing policies (the `set_array_tactics` action /
`state.meta.array_*`), consumed by `_reposition_array` and
`_pick_flank_target`, with the historical behaviour as the default.

Also asserts the per-step Strike *order* (4.4.2 Initiative) is mechanically
inert in this engine: Hits aimed at the same target Lord are summed in
halves and rounded ONCE per target (B2), so permuting the striking Lords'
order cannot change the result — i.e. there is no outcome-bearing choice to
expose there.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    _pick_flank_target,
    _reposition_array,
    _resolve_step,
    battleside_for_lords,
)
from almoravid.scenarios import load_scenario


def _make_array_side(s, lord_ids, side_name, role, forces_per_lord):
    for lid in lord_ids:
        s.lords[lid].forces = forces_per_lord[lid]
    return battleside_for_lords(s, lord_ids, side_name, role,
                                active_lord_id=lord_ids[0])


def _muslims3(seed=11):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    muslims = [lid for lid, lo in s.lords.items() if lo.side == "muslim"][:3]
    return s, muslims


# ---------------------------------------------------------------------------
# Flanking direction (center Flanker, 4.4.2 "center may choose left or right")
# ---------------------------------------------------------------------------

def test_center_flank_choice_overrides_larger_default() -> None:
    s, muslims = _muslims3()
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},   # center
        muslims[1]: {"sergeants": 5},   # left  (larger)
        muslims[2]: {"sergeants": 3},   # right (smaller)
    })
    # Default "larger" -> left(5).
    assert _pick_flank_target(bs, "front_center").lord_id == muslims[1]
    # Explicit "right" -> right(3), even though left is larger.
    assert _pick_flank_target(
        bs, "front_center", flank_choice="right").lord_id == muslims[2]
    # Explicit "left" -> left.
    assert _pick_flank_target(
        bs, "front_center", flank_choice="left").lord_id == muslims[1]


def test_center_flank_choice_falls_back_when_chosen_side_absent() -> None:
    s, muslims = _muslims3()
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 1},
        muslims[1]: {"sergeants": 5},   # left present
        muslims[2]: {"sergeants": 0},   # right empty
    })
    bs.array[2].forces = {}
    bs.array[2].position = "routed"
    # Chose "right" but it's gone -> fall back to the larger present (left).
    assert _pick_flank_target(
        bs, "front_center", flank_choice="right").lord_id == muslims[1]


# ---------------------------------------------------------------------------
# Center-fill direction (4.4.2 Center)
# ---------------------------------------------------------------------------

def test_center_fill_direction_picks_chosen_side() -> None:
    s, muslims = _muslims3()
    # center empty; left + right present.
    for direction, expect_idx in (("left", 1), ("right", 2)):
        s2, m2 = _muslims3()
        bs = _make_array_side(s2, m2, "muslim", "defender", {
            m2[0]: {"sergeants": 2},
            m2[1]: {"sergeants": 2},
            m2[2]: {"sergeants": 2},
        })
        # Empty the center so reposition must fill it.
        center = next(lp for lp in bs.array if lp.position == "front_center")
        center.forces = {}
        center.position = "routed"
        _reposition_array(bs, center_fill=direction)
        filled = next(lp for lp in bs.array
                      if lp.position == "front_center")
        assert filled.lord_id == m2[expect_idx], direction


# ---------------------------------------------------------------------------
# Reserve advance priority (4.4.2 Advance)
# ---------------------------------------------------------------------------

def test_reserve_priority_controls_which_reserve_advances() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    muslims = [lid for lid, lo in s.lords.items() if lo.side == "muslim"][:4]
    bs = _make_array_side(s, muslims, "muslim", "defender", {
        muslims[0]: {"sergeants": 2},
        muslims[1]: {"sergeants": 2},
        muslims[2]: {"sergeants": 2},
        muslims[3]: {"sergeants": 2},
    })
    # muslims[3] is the Reserve (others fill the 3 Front slots). Rout the
    # center so one Front slot opens for a Reserve to Advance into.
    center = next(lp for lp in bs.array if lp.position == "front_center")
    center.forces = {}
    center.position = "routed"
    reserves = [lp.lord_id for lp in bs.array if lp.position == "reserve"]
    assert muslims[3] in reserves
    _reposition_array(bs, reserve_priority=[muslims[3]])
    advanced = [lp.lord_id for lp in bs.array
                if lp.position in ("front_center", "front_left",
                                   "front_right")]
    assert muslims[3] in advanced


# ---------------------------------------------------------------------------
# set_array_tactics action + validation
# ---------------------------------------------------------------------------

def test_set_array_tactics_action_sets_meta() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    r = apply_action(s, {"type": "set_array_tactics", "side": "christian",
                         "flank_choice": "right", "center_fill": "right",
                         "reserve_priority": ["alfonso"]})
    assert r["flank_choice"] == "right"
    assert s.meta.array_flank_choice["christian"] == "right"
    assert s.meta.array_center_fill["christian"] == "right"
    assert s.meta.array_reserve_priority["christian"] == ["alfonso"]


def test_set_array_tactics_validates_and_requires_one_key() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "set_array_tactics", "side": "christian",
                         "flank_choice": "sideways"})
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "set_array_tactics", "side": "christian"})
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "set_array_tactics", "side": "christian",
                         "reserve_priority": "alfonso"})  # not a list


# ---------------------------------------------------------------------------
# Strike order (4.4.2 Initiative) is mechanically inert here.
# ---------------------------------------------------------------------------

def test_strike_order_is_outcome_independent() -> None:
    """Permuting the striking side's Front Array order yields identical Hits
    against each target, because contributions to the same target are summed
    and rounded once (B2). So per-step Strike order carries no outcome and
    needs no interactive prompt."""
    def run(attacker_order):
        s = load_scenario("scenario_a_toledo_beset", seed=7)
        christians = [lid for lid, lo in s.lords.items()
                      if lo.side == "christian"][:3]
        muslims = [lid for lid, lo in s.lords.items()
                   if lo.side == "muslim"][:3]
        atk = _make_array_side(s, [christians[i] for i in attacker_order],
                               "christian", "attacker",
                               {christians[0]: {"knights": 2},
                                christians[1]: {"knights": 2},
                                christians[2]: {"knights": 2}})
        dfd = _make_array_side(s, muslims, "muslim", "defender",
                               {muslims[0]: {"sergeants": 4},
                                muslims[1]: {"sergeants": 4},
                                muslims[2]: {"sergeants": 4}})
        res = _resolve_step(s, "2.a", "attacker", "melee", "horse",
                            atk, dfd, round_index=1)
        return res.rounded_hits, res.units_routed

    base = run([0, 1, 2])
    for perm in ([2, 1, 0], [1, 0, 2], [1, 2, 0]):
        assert run(perm) == base


def test_array_tactics_discoverable_during_field_battle() -> None:
    """The Array choices must be discoverable via legal_moves while a field
    Battle is in progress (mirrors set_absorption_policy exposure)."""
    from almoravid.legal_moves import legal_moves
    from almoravid.state import Cylinder
    from tests.test_phase6b_approach import _activate_lord_at_locale
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=11)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sahagun")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "sahagun", "way_type": "road"})
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    at = [m for m in legal_moves(s) if m["type"] == "set_array_tactics"]
    flanks = {m.get("flank_choice") for m in at if "flank_choice" in m}
    fills = {m.get("center_fill") for m in at if "center_fill" in m}
    assert flanks == {"larger", "left", "right"}
    assert fills == {"left", "right"}
