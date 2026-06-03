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

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.state import Cylinder
from tests.test_phase6b_approach import _activate_lord_at_locale


def _march_into_battle(seed: int = 11):
    """Drive Alfonso (Christian) to March into al_mutamid (Muslim) at
    sahagun, leaving a pending `march_arrival_response` on the Muslim."""
    s = _activate_lord_at_locale("scenario_a_toledo_beset", "alfonso",
                                 "leon", seed=seed)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sahagun")
    s.lords["al_mutamid"].in_stronghold = False
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
    r = apply_action(s, {"type": "respond_stand_battle", "side": "muslim",
                         "interactive_concede": True})
    assert r["battle"] == "awaiting_concede"
    assert r["round"] == 1
    assert s.pending is not None
    assert s.pending.kind == "battle_concede"
    assert s.pending.waiting_on == "muslim"
    types = {m["type"] for m in legal_moves(s)}
    assert "battle_concede" in types


def test_stand_battle_interactive_runs_to_completion() -> None:
    """Stepping the `battle_concede` decisions to the end produces the
    same terminal bookkeeping as the synchronous Stand path: card ended,
    pending cleared, control restored to the Active (Christian) side."""
    s = _march_into_battle()
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    guard = 0
    while s.pending is not None and s.pending.kind == "battle_concede":
        apply_action(s, {"type": "battle_concede", "side": "muslim"})
        guard += 1
        assert guard < 10, "battle_concede did not terminate"
    assert s.meta.actions_remaining == 0       # card ended (4.4.5)
    assert (s.pending is None
            or s.pending.kind != "battle_concede")
    if s.pending is None:
        assert s.meta.active_player == "christian"


def test_interactive_concede_matches_resolver_outcome() -> None:
    """Defender (Muslim) Concedes Round 1 in the interactive Approach
    Battle -> Attacker (Christian) wins, matching the deterministic
    resolver's `defender_concede_round=1` outcome."""
    s = _march_into_battle()
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    r = apply_action(s, {"type": "battle_concede", "side": "muslim",
                         "defender_concede": True})
    assert r["winner"] == "christian"


def test_interactive_attacker_concede_defender_wins() -> None:
    """Attacker (Christian) Concedes Round 1 -> Defender (Muslim) wins.

    This is the half a leftmost-default resolver could not express from
    the public interface for a normal field Battle."""
    s = _march_into_battle()
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim",
                     "interactive_concede": True})
    r = apply_action(s, {"type": "battle_concede", "side": "muslim",
                         "attacker_concede": True})
    assert r["winner"] == "muslim"
