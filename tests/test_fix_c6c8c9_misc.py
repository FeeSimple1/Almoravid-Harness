"""FIX-C / C6 Capability Discard (4.0), C8 Lieutenant disband-orphan
cleanup (4.1.3), C9 Lt/Lower must Withdraw together (4.1.3/4.3.4)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _apply_capability_discard
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


def test_c6_discards_capabilities_beyond_mustered_lord_count() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    n_chr = sum(1 for l in s.lords.values()
                if l.side == "christian" and l.cylinder.kind == "locale")
    s.decks.board_edge["christian"] = [f"C{i}" for i in range(n_chr + 2)]
    s.decks.discard = []
    out = _apply_capability_discard(s)
    assert len(s.decks.board_edge["christian"]) == n_chr
    assert out["christian"]["discarded"] == [f"C{i}" for i in (n_chr, n_chr + 1)]
    assert set(s.decks.discard) >= {f"C{n_chr}", f"C{n_chr+1}"}


def test_c6_keeps_when_not_in_excess() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.board_edge["muslim"] = ["M0"]
    out = _apply_capability_discard(s)
    assert s.decks.board_edge["muslim"] == ["M0"]
    assert "muslim" not in out


def test_c8_disbanding_lieutenant_frees_lower_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Build a Lt (alvar_fanez) over Lower (garcia_ordonez) at sahagun.
    up, low = "alvar_fanez", "garcia_ordonez"
    for lid in (up, low):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords[up].is_lieutenant = True
    s.lords[low].lieutenant_of = up
    # Drive to the Levy service_disband step and disband the Lieutenant.
    s.meta.phase = "levy"
    s.meta.levy_step = "service_disband"
    s.meta.active_player = "christian"
    cur = s.calendar.current_box
    # Put the Lieutenant's Service marker at-limit (box <= current).
    sm = next((m for m in s.calendar.service_markers if m.lord_id == up), None)
    if sm is not None:
        sm.box = cur
    apply_action(s, {"type": "disband_lord", "side": "christian",
                     "lord_id": up})
    # Lower Lord is no longer tied to the (gone) Lieutenant.
    assert s.lords[low].lieutenant_of is None


def test_c9_withdraw_rejects_splitting_lt_pair() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    # Muslim Lt pair at zaragoza; Christian approacher outside.
    up, low = "al_mustain", "abu_bakr"
    for lid in (up, low):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zaragoza")
        s.lords[lid].in_stronghold = False
    s.lords[up].is_lieutenant = True
    s.lords[low].lieutenant_of = up
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = False
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    # Pending: only the Lower Lord withdraws (splitting the pair).
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "zaragoza", "from_locale_id": "calatayud",
                 "via_way_type": "road", "active_lord_id": "alvar_fanez",
                 "active_side": "christian", "defender_lord_ids": [low]})
    s.meta.active_player = "muslim"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "respond_withdraw", "side": "muslim"})
    assert ei.value.code == "lt_pair_split"
