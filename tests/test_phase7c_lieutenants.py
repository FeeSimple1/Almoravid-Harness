"""Phase 7c: Lieutenants / Marshal / Group March (4.1.3, 4.3.1)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad


def _two_christian_lords_same_locale(s, loc="leon"):
    """Return two non-Marshal Christian lord_ids placed at `loc`."""
    ids = [lid for lid, l in s.lords.items()
           if l.side == "christian" and lid != "alfonso"]
    assert len(ids) >= 2, "need two non-Marshal Christian Lords"
    a, b = ids[0], ids[1]
    for lid in (a, b):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id=loc)
        s.lords[lid].in_stronghold = False
    return a, b


# ---------------------------------------------------------------------------
# Designation (Plan step)
# ---------------------------------------------------------------------------


def test_designate_lieutenant_stacks_lower_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.campaign_step = "plan"
    s.meta.active_player = "christian"
    sub, cmd = _two_christian_lords_same_locale(s)
    r = apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                         "lord_id": sub, "commander_id": cmd})
    assert r["lower_lord"] == sub
    assert s.lords[sub].is_lieutenant is True
    assert s.lords[sub].lieutenant_of == cmd


def test_marshal_cannot_be_lower_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.campaign_step = "plan"
    s.meta.active_player = "christian"
    # Try to make Alfonso (Marshal) a Lower Lord.
    other = next(lid for lid, l in s.lords.items()
                 if l.side == "christian" and lid != "alfonso")
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords[other].cylinder = Cylinder(kind="locale", locale_id="leon")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                         "lord_id": "alfonso", "commander_id": other})
    assert ei.value.code == "marshal_cannot_subordinate"


def test_designate_requires_same_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.campaign_step = "plan"
    s.meta.active_player = "christian"
    sub, cmd = _two_christian_lords_same_locale(s)
    s.lords[sub].cylinder = Cylinder(kind="locale", locale_id="burgos")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                         "lord_id": sub, "commander_id": cmd})
    assert ei.value.code == "not_same_locale"


def test_lieutenant_has_at_most_one_lower_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.campaign_step = "plan"
    s.meta.active_player = "christian"
    ids = [lid for lid, l in s.lords.items()
           if l.side == "christian" and lid != "alfonso"]
    if len(ids) < 3:
        pytest.skip("need 3 non-Marshal Christian Lords")
    cmd, s1, s2 = ids[0], ids[1], ids[2]
    for lid in (cmd, s1, s2):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="leon")
    apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                     "lord_id": s1, "commander_id": cmd})
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                         "lord_id": s2, "commander_id": cmd})
    assert ei.value.code == "lieutenant_full"


# ---------------------------------------------------------------------------
# Group March
# ---------------------------------------------------------------------------


def test_group_march_brings_lower_lord() -> None:
    from almoravid.map import neighbors_via
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    sub, cmd = _two_christian_lords_same_locale(s, loc="leon")
    s.lords[sub].is_lieutenant = True
    s.lords[sub].lieutenant_of = cmd
    s.lords[cmd].assets = {}  # Unladen
    # Hand-set activation with the commander active.
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = cmd
    s.meta.actions_remaining = 3
    target = neighbors_via("leon", "road")[0]
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": target, "way_type": "road"})
    # Both Lords moved together.
    assert s.lords[cmd].cylinder.locale_id == target
    assert s.lords[sub].cylinder.locale_id == target


# ---------------------------------------------------------------------------
# Lower Lord's own card is passed
# ---------------------------------------------------------------------------


def test_lower_lord_command_card_auto_passes() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    other = "muslim"
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        apply_action(s, {"type": "pass_step", "side": s.meta.active_player})
    # Build a Christian plan with two command cards; the second Lord
    # will be a Lower Lord.
    sub, cmd = _two_christian_lords_same_locale(s, loc="leon")
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": cmd})
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": sub})
    legal_pad(s, "christian")
    legal_pad(s, other)
    # Designate sub as Lower Lord of cmd during the Plan step (before
    # finalizing — the step leaves 'plan' once both sides finalize).
    apply_action(s, {"type": "designate_lieutenant", "side": "christian",
                     "lord_id": sub, "commander_id": cmd})
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    # Now reveal: cmd activates; later sub's card should auto-pass.
    saw_sub_pass = False
    for _ in range(12):
        before = s.meta.active_lord_id
        if s.meta.active_player == "christian" and before is None:
            r = apply_action(s, {"type": "command_reveal", "side": "christian"})
            if (r.get("auto_pass") and r["revealed"].get("lord_id") == sub):
                saw_sub_pass = True
                break
            if s.meta.active_lord_id:
                apply_action(s, {"type": "end_card", "side": "christian"})
        else:
            # advance muslim
            if s.meta.active_player == "muslim":
                apply_action(s, {"type": "command_reveal", "side": "muslim"})
                if s.meta.active_lord_id:
                    apply_action(s, {"type": "end_card", "side": "muslim"})
            else:
                break
    assert saw_sub_pass


# ---------------------------------------------------------------------------
# End-of-campaign unstack
# ---------------------------------------------------------------------------


def test_end_campaign_unstacks_lieutenants() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    sub, cmd = _two_christian_lords_same_locale(s)
    s.lords[sub].is_lieutenant = True
    s.lords[sub].lieutenant_of = cmd
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    s.meta.active_player = "christian"
    s.calendar.current_box = 1
    apply_action(s, {"type": "end_campaign", "side": "christian"})
    assert s.lords[sub].is_lieutenant is False
    assert s.lords[sub].lieutenant_of is None
