"""Battle of Sagrajas battle-only minigame (Background Book pp.44-47):
first-class, LLM-playable through the same public interface as the campaign
scenarios. (Req 1-5 of the Sagrajas task.)"""
from __future__ import annotations

import copy

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import (list_campaign_scenarios, list_scenarios,
                                 load_scenario)


# --- 1. appears in the scenario list, startable by a stable key -----------
def test_sagrajas_in_scenario_list():
    assert "sagrajas" in list_scenarios()
    assert "sagrajas" not in list_campaign_scenarios()   # battle-only


def test_sagrajas_starts_into_battle_not_levy():
    s = load_scenario("sagrajas", seed=1)
    assert s.meta.scenario_letter == "S"
    assert s.meta.phase == "battle"          # not Levy/Campaign
    assert s.pending is not None and s.pending.kind == "sagrajas_who_attacks"
    # Round-trips through pydantic.
    from almoravid.state import GameState
    GameState.model_validate(s.model_dump())


def test_setup_is_deterministic():
    a = load_scenario("sagrajas", seed=1)
    b = load_scenario("sagrajas", seed=2)   # seed only affects resolution
    fa = {lid: dict(l.forces) for lid, l in a.lords.items()
          if l.cylinder.kind == "locale"}
    fb = {lid: dict(l.forces) for lid, l in b.lords.items()
          if l.cylinder.kind == "locale"}
    assert fa == fb


# --- 3. render is clear and does not crash --------------------------------
def test_show_identifies_sagrajas():
    from almoravid.render import render_summary, render_verbose
    s = load_scenario("sagrajas", seed=1)
    out = render_summary(s)
    assert "Sagrajas" in out
    assert "Christian army" in out and "Muslim army" in out
    # both Marshals' armies and the decision are described
    assert "alfonso" in out and "yusuf" in out
    assert "sagrajas_attack" in out and "sagrajas_defend" in out
    assert render_verbose(s)  # does not crash


# --- 4. legal()/apply() work; validated palette has no rejected actions ---
def test_legal_offers_role_then_resolve_and_palette_is_clean():
    s = load_scenario("sagrajas", seed=1)
    m1 = legal_moves(s)
    assert {x["type"] for x in m1} == {"sagrajas_attack", "sagrajas_defend"}
    for m in m1:                              # validated palette: all apply
        apply_action(copy.deepcopy(s), m)
    apply_action(s, {"type": "sagrajas_attack", "side": "christian"})
    m2 = legal_moves(s)
    assert [x["type"] for x in m2] == ["resolve_battle"]
    apply_action(copy.deepcopy(s), m2[0])     # resolve probes clean


# --- 2/4. both branches resolve to completion across seeds ----------------
@pytest.mark.parametrize("role", ["sagrajas_attack", "sagrajas_defend"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_resolves_to_completion(role, seed):
    s = load_scenario("sagrajas", seed=seed)
    apply_action(s, {"type": role, "side": "christian"})
    r = apply_action(s, {"type": "resolve_battle",
                         "side": s.pending.waiting_on})
    assert s.meta.phase == "ended"
    assert r["winner"] in ("christian", "muslim")
    # No leftover co-location: the loser left the field.
    by: dict[str, set] = {}
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and not l.in_stronghold:
            by.setdefault(l.cylinder.locale_id, set()).add(l.side)
    assert not [loc for loc, sd in by.items()
                if "christian" in sd and "muslim" in sd]


# --- 5. final result is recorded in a normal harness-readable way ---------
def test_final_result_recorded():
    s = load_scenario("sagrajas", seed=1)
    apply_action(s, {"type": "sagrajas_attack", "side": "christian"})
    apply_action(s, {"type": "resolve_battle", "side": "christian"})
    assert s.score.winner in ("christian", "muslim")
    assert "Sagrajas" in (s.score.victory_reason or "")
    assert s.meta.phase == "ended"


def test_defend_branch_makes_muslims_attacker():
    s = load_scenario("sagrajas", seed=1)
    apply_action(s, {"type": "sagrajas_defend", "side": "christian"})
    assert s.meta.sagrajas_role == "defend"
    assert s.meta.active_player == "muslim"       # Yusuf attacks
    r = apply_action(s, {"type": "resolve_battle", "side": "muslim"})
    assert r["attacker"] == "muslim"


# --- Regression: 6-round safety cap must not decide the result -----------
@pytest.mark.parametrize("seed", [57, 96])
def test_defend_branch_resolves_past_six_rounds_no_colocation(seed):
    """ChatGPT-found bug: the defend branch could hit the resolver's 6-Round
    safety cap with winner=None, leaving Christian+Muslim Lords co-located at
    Badajoz. The Battle must resolve naturally (these run 7 Rounds) and never
    end in an illegal co-located state."""
    s = load_scenario("sagrajas", seed=seed)
    apply_action(s, {"type": "sagrajas_defend", "side": "christian"})
    r = apply_action(s, {"type": "resolve_battle", "side": "muslim"})
    assert r["winner"] in ("christian", "muslim"), r   # not None
    assert r["rounds"] > 6                              # ran past the old cap
    by: dict[str, set] = {}
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and not l.in_stronghold:
            by.setdefault(l.cylinder.locale_id, set()).add(l.side)
    assert not [loc for loc, sd in by.items()
                if "christian" in sd and "muslim" in sd]


@pytest.mark.parametrize("seed", list(range(1, 41)))
@pytest.mark.parametrize("role", ["sagrajas_attack", "sagrajas_defend"])
def test_sagrajas_never_ends_co_located(seed, role):
    """Seed sweep: every Sagrajas battle ends decisively (or, defensively,
    clears the field) with no opposing field Lords co-located."""
    s = load_scenario("sagrajas", seed=seed)
    apply_action(s, {"type": role, "side": "christian"})
    apply_action(s, {"type": "resolve_battle", "side": s.pending.waiting_on})
    assert s.meta.phase == "ended"
    by: dict[str, set] = {}
    for lid, l in s.lords.items():
        if l.cylinder.kind == "locale" and not l.in_stronghold:
            by.setdefault(l.cylinder.locale_id, set()).add(l.side)
    assert not [loc for loc, sd in by.items()
                if "christian" in sd and "muslim" in sd]


def test_sagrajas_history_labels_as_scenario_s():
    s = load_scenario("sagrajas", seed=1)
    assert s.history and "Battle of Sagrajas" in s.history[0].summary
    assert "Scenario F" not in s.history[0].summary
