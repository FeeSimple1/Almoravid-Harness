"""Interactive (round-stepped) Concede for a March-triggered Approach
(Stand & Fight) Battle — rule 4.3.4 / 4.4.2.

Before this fix, an ordinary field Battle reached through a March
Approach (`respond_stand_battle`) always resolved synchronously inside
`resolve_battle`, so an agent using the public action interface could
only pre-declare Concede via `*_concede_round` and otherwise fell back
to the deterministic resolver. The end-of-card Battle (`cmd_battle`) and
the Relief Sally already exposed the reactive `interactive_concede`
driver; these tests assert the standard Approach Battle now does too,
and that the interactive and synchronous paths agree on outcomes.
"""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder, GameState
from tests.test_phase6b_approach import _activate_lord_at_locale
from tests.combat_choices import apply_combat_choices


def _march_into_battle(seed: int = 11, *, relief: bool = False):
    """Drive Alfonso (Christian) to March into al_mutamid (Muslim) at
    sahagun, leaving a pending `march_arrival_response` on the Muslim."""
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=seed)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sahagun")
    s.lords["al_mutamid"].in_stronghold = False
    if relief:
        s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
        s.lords["alvar_fanez"].in_stronghold = True
        s.locales["sahagun"].siege_green = 1
    s.lords["alfonso"].assets = {}
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "sahagun", "way_type": "road"})
    assert s.pending is not None
    assert s.pending.kind == "march_arrival_response"
    return s


def test_stand_battle_opt_in_pends_concede() -> None:
    """`respond_stand_battle` with `interactive_concede` pauses on a
    per-Round `battle_concede` decision instead of auto-resolving."""
    s = _march_into_battle()
    r = apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                         "interactive_concede": True})
    assert r["battle"] == "awaiting_concede"
    assert r["round"] == 1
    assert s.pending is not None
    assert s.pending.kind == "battle_concede"
    assert s.pending.waiting_on == "christian" == s.meta.active_player
    types = {m["type"] for m in legal_moves(s)}
    assert "battle_concede" in types


@pytest.mark.parametrize("relief", [False, True])
def test_stand_battle_interactive_runs_to_completion(relief) -> None:
    """Stepping the `battle_concede` decisions to the end produces the
    same terminal bookkeeping as the synchronous Stand path: card ended,
    pending cleared, control restored to the Active (Christian) side."""
    s = _march_into_battle(relief=relief)
    synchronous = s.model_copy(deep=True)
    stand = {"type": "respond_stand_battle", "side": "muslim"}
    sallyers = ("alvar_fanez",) if relief else ()
    expected = apply_combat_choices(synchronous, stand, sallyers=sallyers)
    result = apply_combat_choices(s, {**stand, "interactive_concede": True}, sallyers=sallyers)
    kind = "relief_concede" if relief else "battle_concede"
    guard = 0
    while s.pending is not None and s.pending.kind == kind:
        result = apply_action(s, {"type": kind, "side": s.pending.waiting_on})
        guard += 1
        assert guard < 20, f"{kind} did not terminate"
    assert (result["winner"], result["rounds"]) == (expected["winner"], expected["rounds"])
    assert s.meta.rng_state == synchronous.meta.rng_state
    assert s.meta.actions_remaining == 0       # card ended (4.4.5)
    assert (s.pending is None
            or s.pending.kind != kind)
    if s.pending is None:
        assert s.meta.active_player == "christian"


def test_interactive_concede_matches_resolver_outcome() -> None:
    """Defender (Muslim) Concedes Round 1 in the interactive Approach
    Battle -> Attacker (Christian) wins, matching the deterministic
    resolver's `defender_concede_round=1` outcome."""
    s = _march_into_battle()
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    apply_action(s, {"type": "battle_concede", "side": "christian"})
    r = apply_action(s, {"type": "battle_concede", "side": "muslim",
                         "defender_concede": True})
    assert r["winner"] == "christian"


def test_interactive_attacker_concede_defender_wins() -> None:
    """Attacker (Christian) Concedes Round 1 -> Defender (Muslim) wins.

    This is the half a leftmost-default resolver could not express from
    the public interface for a normal field Battle."""
    s = _march_into_battle()
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    r = apply_action(s, {"type": "battle_concede", "side": "christian",
                         "attacker_concede": True})
    assert r["winner"] == "muslim"


def test_hit_absorption_choice_discoverable_during_battle() -> None:
    """4.4.2 ASSIGN HITS is a player choice. The owner's Hit-absorption
    policy works at any time, but must also be *discoverable* via
    legal_moves while a field Battle is in progress so an agent on the
    public interface can use it (and re-set it between Rounds)."""
    s = _march_into_battle()
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    sap = [m for m in legal_moves(s)
           if m["type"] == "set_absorption_policy"]
    assert {m["policy"] for m in sap} == {"weakest_first", "armored_first"}
    # And applying one mid-Battle is accepted (does not consume the
    # pending Concede decision).
    apply_action(s, {"type": "set_absorption_policy", "side": "muslim",
                     "policy": "armored_first"})
    assert s.pending is not None and s.pending.kind == "battle_concede"
    assert s.meta.absorption_policy["muslim"] == "armored_first"


@pytest.mark.parametrize("relief", [False, True])
def test_approach_concede_prompts_only_authorize_the_waiting_owner(relief):
    s = _march_into_battle(relief=relief)
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True}, sallyers=("alvar_fanez",) if relief else ())
    kind = "relief_concede" if relief else "battle_concede"
    assert s.pending.kind == kind
    rng_before = s.meta.rng_state
    combat_before = s.pending.payload.copy()

    for role, side, opposing_side, opposing_role in (
        ("attacker", "christian", "muslim", "defender"),
        ("defender", "muslim", "christian", "attacker"),
    ):
        assert s.pending.waiting_on == s.meta.active_player == side
        assert [m for m in legal_moves(s) if m["type"] == kind] == [
            {"type": kind, "side": side}, {"type": kind, "side": side,
                                         f"{role}_concede": True},
        ]
        saved = s.model_dump_json()
        for action, code in (
            ({"type": kind, "side": opposing_side, f"{opposing_role}_concede": True},
             "not_responder"),
            ({"type": kind, "side": side, f"{opposing_role}_concede": True}, "wrong_side"),
            ({"type": kind, "side": side, f"{role}_concede": "false"}, "bad_arg"),
            ({"type": "end_card", "side": side}, "pending_decision"),
        ):
            with pytest.raises(IllegalAction) as exc:
                apply_action(s, action)
            assert exc.value.code == code
            assert s.model_dump_json() == saved

        if role == "attacker":
            apply_action(s, {"type": kind, "side": side})
            assert s.pending.payload == {**combat_before, "concede_role": "defender"}
            assert s.meta.rng_state == rng_before
            # The defender's election is still owed after a save and reload.
            s = GameState.model_validate_json(s.model_dump_json())

    result = apply_action(s, {"type": kind, "side": "muslim", "defender_concede": True})
    assert result["winner"] == "christian" and result["rounds"] == 1
    assert s.meta.active_player == "christian"


def test_relief_attacker_can_concede_before_the_besiegers():
    s = _march_into_battle(relief=True)
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True}, sallyers=("alvar_fanez",))
    result = apply_action(s, {"type": "relief_concede", "side": "christian",
                             "attacker_concede": True})
    assert result["winner"] == "muslim" and result["rounds"] == 1
    assert result["retreat_summary"]["pursuit"]["conceder"] == "christian"


@pytest.mark.parametrize("relief", [False, True])
def test_legacy_combat_save_resumes_at_the_current_rounds_attacker(relief):
    s = _march_into_battle(relief=relief)
    apply_combat_choices(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True}, sallyers=("alvar_fanez",) if relief else ())
    saved = s.model_dump()
    saved["pending"]["payload"].pop("concede_role", None)
    # The old Approach driver assigned its combined election to the defender.
    if not relief:
        saved["pending"]["waiting_on"] = saved["meta"]["active_player"] = "muslim"
    loaded = GameState.model_validate(saved)
    assert loaded.pending.waiting_on == loaded.meta.active_player == "christian"
    assert loaded.pending.payload["concede_role"] == "attacker"
    assert loaded.model_dump() == s.model_dump()
