"""Background Book pp.14-18 — "Storming a Stronghold" (Játiva) encoded
as an exact-dice, exact-outcome anchor.

GMT's own worked example, played die-for-die through the engine:
Álvar Fáñez (C2 Ballesteros + C7 Jabalinas, both Vassals mustered) and
Alfonso (C4 Arqueros + C6 Siege Towers, both Vassals) Storm the Town of
Játiva with three Siege markers; Abu Bakr (own forces + Játiva Militia
Vassal) defends with the Town Garrison (2 MaA-Crossbows, 1
Militia-Bowmen; Walls 1-4; Capacity 2).

Round 1 printed dice, all asserted here in engine order:
  1a  Defender Missiles: Garrison 1½ -> 2 Hits (1 Crossbow + 1 Bowmen);
      Siegeworks(3) rolls "4" (Crossbow through) and "3" (Bowmen
      canceled); the Muslim player selects a Men-at-Arms from Álvar's
      mat (crossbow targeting, DECISION-009 armored_first); reduced
      Armor 1-2, rolls "2" — stands.
  1b  Attacker Missiles: Álvar's three Crossbow units -> 2 Crossbow
      Hits; Walls 1-4 rolls "5" (through) and "3" (canceled); the
      Christians select a Garrison Men-at-Arms; Armor 1-2, rolls "6" —
      Routs. Javelins reserved: in Storm they are x½ and (4.4.2 TOTAL
      HITS) do not stack with the Militia's Crossbows, so declaring
      them adds no Hits ("adds no Hits", p.16).
  2a  Defender Melee: Garrison POOLS with Abu Bakr's units for a
      single round-up — 3 Armored + 4 Unarmored = exactly FIVE dice
      "1","3","3","4","6" vs Siegeworks 1-3 -> 2 Hits through; the
      Attacker absorbs with Armored first (rule-forced): Knights rolls
      "3" (stands) then "5" (Routs).
  2b  Attacker Melee: 6 Armored + 2 Unarmored = 7 raw, capped at 6;
      Walls 1-4 cancels four of six; the two Hits Rout both remaining
      Garrison units.

Round 2 (printed as counts/outcomes, dice chosen consistently):
  Reposition brings Alfonso to Front (Town Capacity 2); Siege Towers
  now count: Walls 1-3. Attacker Missiles = 2 Bowmen + 2 Crossbow Hits
  (per-Lord capability scoping: Álvar's Crossbows 1½ + Alfonso's
  Bowmen 2 -> 4, Crossbows taking the round-up). Defender Melee = 3
  Hits; the Attackers lose one more Knights unit. Attacker Melee = 12
  Hits (max 6 per Attacking Lord in Front); all remaining Defenders
  Rout.

End/Sack: Abu Bakr is permanently removed; his Assets (2 Coin, 2
Provender) plus the Town's Spoils (1 Coin, 2 Provender) go to the
victors; the Town is Conquered (Value 1 -> 1 Conquered marker, +1 VP).
Per 1.4.3 ("removal of a Lord"), Valencia flips Independent -> Parias
(+4 Parias Coin, +1 VP).
"""
from __future__ import annotations

import sys

import almoravid.battle as B
import almoravid.rng as R
from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy

# The full die queue: 3 Forage rolls, then the Storm exactly as above,
# then 4.4.4 Losses (the two Routed Knights need a "1"; both fail).
DICE = [
    2, 5, 3,                       # Forage x3: success, fail, success
    4, 3, 2,                       # R1 1a: Siegeworks x2; MaA save "2"
    5, 3, 6,                       # R1 1b: Walls x2; Garrison MaA "6"
    1, 3, 3, 4, 6, 3, 5,           # R1 2a: FIVE pooled dice; Knights "3","5"
    1, 2, 3, 4, 5, 6, 4, 6,        # R1 2b: Walls x6 (4 cancel); both Garrison
    1, 2, 3, 4, 5,                 # R2 1b: Walls(1-3) x4; MaA Routs "5"
    1, 2, 6, 5,                    # R2 2a: Siegeworks x3; Knights Routs "5"
    4, 5, 6, 4, 5, 6, 1, 2, 3,     # R2 2b: Walls(1-3) x12 (6 through) ...
    1, 2, 3, 4, 5, 6, 4,           # ... and 4 Protection rolls, all Rout
    3, 5,                          # Losses: both Routed Knights lost
]

# (caller-tag, count) run-length signature of the queue above — pins
# the printed HIT COUNTS: 2/1, 2/1, 5/2, 6/2 in Round 1; 4/1, 3/1,
# 12/4 in Round 2; 2 Losses rolls.
EXPECTED_PHASES = [
    ("_h_cmd_forage", 3),
    ("cancel", 2), ("protection", 1),     # 1a
    ("cancel", 2), ("protection", 1),     # 1b
    ("cancel", 5), ("protection", 2),     # 2a — five pooled Defender dice
    ("cancel", 6), ("protection", 2),     # 2b
    ("cancel", 4), ("protection", 1),     # R2 1b — 2 Bowmen + 2 Crossbow
    ("cancel", 3), ("protection", 1),     # R2 2a — 3 Melee Hits
    ("cancel", 12), ("protection", 4),    # R2 2b — 12 Hits, max 6/Lord
    ("apply_losses_rolls", 2),
]


def _activate(scenario: str, lord_id: str, seed: int = 1):
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    legal_pad(s, side)
    legal_pad(s, "muslim" if side == "christian" else "christian")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            return s
        apply_action(s, {"type": "command_reveal",
                         "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card",
                             "side": s.meta.active_player})
    raise RuntimeError(f"could not activate {lord_id}")


def _stage_jativa():
    s = _activate("scenario_a_toledo_beset", "alvar_fanez", seed=1)
    alvar, alfonso, abu = (s.lords["alvar_fanez"], s.lords["alfonso"],
                           s.lords["abu_bakr"])
    # Álvar: printed Forces + both Vassals (Pelayo Peláez, Fernando
    # Díaz) = 7 Armored + Serf + Militia; Ballesteros + Jabalinas.
    alvar.cylinder = Cylinder(kind="locale", locale_id="jativa")
    alvar.in_stronghold = False
    alvar.forces = {"knights": 2, "sergeants": 3, "men_at_arms": 2,
                    "serfs": 1, "militia": 1}
    alvar.capabilities = ["C2", "C7"]
    alvar.assets = {}   # "The Besiegers' food has run out"
    # Alfonso: printed Forces + both Vassals (Froila Bermúdez, Vela
    # Ovéquez); Arqueros + Siege Towers.
    alfonso.cylinder = Cylinder(kind="locale", locale_id="jativa")
    alfonso.in_stronghold = False
    alfonso.forces = {"knights": 2, "sergeants": 2, "men_at_arms": 2,
                      "serfs": 1, "militia": 1}
    alfonso.capabilities = ["C4", "C6"]
    alfonso.assets = {}
    # Abu Bakr: printed Forces + the Játiva Militia Vassal; "ample
    # provisions, both food and gold".
    abu.cylinder = Cylinder(kind="locale", locale_id="jativa")
    abu.in_stronghold = True
    abu.forces = {"sergeants": 1, "light_horse": 1, "men_at_arms": 1,
                  "militia": 2}
    abu.assets = {"coin": 2, "prov": 2}
    s.locales["jativa"].siege_yellow = 3   # "quite advanced" Siegeworks
    # DECISION-009: both sides play GMT's printed Crossbow targeting.
    s.meta.crossbow_target_policy["christian"] = "armored_first"
    s.meta.crossbow_target_policy["muslim"] = "armored_first"
    assert s.taifas["valencia"].status == "independent"
    assert s.locales["jativa"].base_type == "town"
    return s


def test_bgbook_jativa_storm_exact_trace(monkeypatch) -> None:
    s = _stage_jativa()
    alvar, alfonso, abu = (s.lords["alvar_fanez"], s.lords["alfonso"],
                           s.lords["abu_bakr"])
    christ0, musl0 = s.score.christian, s.score.muslim

    queue = list(DICE)
    log: list[tuple[str, int]] = []

    def scripted_roll(state):
        assert queue, f"die queue exhausted after {len(log)} rolls"
        v = queue.pop(0)
        log.append((sys._getframe(1).f_code.co_name, v))
        state.meta.rng_state += 1
        return v

    monkeypatch.setattr(B, "roll_d6", scripted_roll)
    monkeypatch.setattr(R, "roll_d6", scripted_roll)

    # Three Forage attempts: two Provender (p.15, rolls 1-3 succeed).
    for _ in range(3):
        apply_action(s, {"type": "cmd_forage", "side": "christian"})
    assert alvar.assets.get("prov") == 2

    r = apply_action(s, {"type": "cmd_storm", "side": "christian"})

    # The queue is consumed EXACTLY — any divergence in a Hit count,
    # cancellation count, or Protection-roll count breaks this.
    assert not queue, f"{len(queue)} dice left over"

    # Run-length signature: pins every printed count (five pooled
    # Defender Melee dice in R1 2a; 2+2 Missiles and 3 Melee in R2...).
    phases: list[tuple[str, int]] = []
    for caller, _v in log:
        kind = ("cancel" if caller == "<listcomp>" else
                "protection" if caller == "_resolve_protection_roll" else
                caller)
        if phases and phases[-1][0] == kind:
            phases[-1] = (kind, phases[-1][1] + 1)
        else:
            phases.append((kind, 1))
    assert phases == EXPECTED_PHASES

    # "the Attackers are able in Round 2 to Rout all of Abu Bakr's
    # units" — Storm over in 2 Rounds, Christians win.
    assert r["winner"] == "christian"
    assert r["rounds"] == 2

    # End, Sack, and Aftermath (p.18):
    # Abu Bakr permanently removed (cylinder, mat, Service marker).
    assert abu.cylinder.kind == "removed"
    assert abu.forces == {} and abu.assets == {}
    assert not any(m.lord_id == "abu_bakr"
                   for m in s.calendar.service_markers)
    # Spoils: Abu Bakr's Assets (2 Coin + 2 Prov) + Town Spoils
    # (1 Coin + 2 Prov) distributed among the Lords present.
    assert r["sack"]["spoils"] == {"coin": 3, "prov": 4}
    spoil_coin = (alvar.assets.get("coin", 0)
                  + alfonso.assets.get("coin", 0))
    spoil_prov = (alvar.assets.get("prov", 0)
                  + alfonso.assets.get("prov", 0))
    # Alfonso also holds the 4 Parias Coin (below): 3 + 4 = 7.
    assert spoil_coin == 7
    assert spoil_prov == 4 + 2    # 2 foraged + 4 Spoils
    # Conquest: Town Value 1 -> one Conquered marker, +1 VP (5.1).
    assert r["conquest"]["value"] == 1
    assert s.locales["jativa"].conquered_markers == 1
    assert s.locales["jativa"].siege_yellow == 0
    # 1.4.3 "removal of a Lord": Valencia Independent -> Parias,
    # +4 Parias Coin (Abu Bakr Service 4), +1 VP Christian.
    assert s.taifas["valencia"].status == "parias"
    pol = r["sack"]["removal_politics"]["abu_bakr"]
    assert pol["parias_coin"]["amount"] == 4
    assert s.score.christian - christ0 == 2.0   # Conquest 1 + Parias 1
    assert s.score.muslim == musl0

    # Losses (4.4.4): the two Routed Knights (one per Round) need a
    # "1" as Storm Attackers; "3" and "5" fail — two Knights lost.
    total_knights = (alvar.forces.get("knights", 0)
                     + alfonso.forces.get("knights", 0))
    assert total_knights == 2
    # "Álvar is fortunate not to lose some Men-at-Arms" (p.16) — both
    # survive, as do all other non-Knight units on both mats.
    assert alvar.forces == {"sergeants": 3, "men_at_arms": 2,
                            "serfs": 1, "militia": 1}
    assert alfonso.forces == {"knights": 2, "sergeants": 2,
                              "men_at_arms": 2, "serfs": 1, "militia": 1}
