"""Background Book worked examples: "Use of Lordship for Levy Actions"
(Alfonso's Muster, p.10) and "March, Ravage, Feed" (Álvar Fáñez,
pp.12-14), encoded as exact-outcome anchors.

Companions to tests/test_background_book_examples.py (no-dice
examples) and tests/test_bgbook_jativa_storm.py (full Storm trace).
"""
from __future__ import annotations

import almoravid.actions as A
from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, ServiceMarker
from tests._plan_helpers import legal_pad, step_levy

# ---------------------------------------------------------------------------
# BB p.10 — Alfonso during Muster uses his Lordship of "3" for three
# Levy actions: 1) Muster a Vassal (the three-unit marker = Froila
# Bermúdez), 2) put the Milites Capability into play at the map edge —
# then immediately add three of its units for one of his two Provender,
# an Asset not an action — and 3) roll to Muster Pedro Ansúrez (Fealty
# 4): "The player rolls a '5': unsuccessful ... with three Levy actions
# spent, Alfonso is out of Lordship."
# ---------------------------------------------------------------------------

def test_bgbook_alfonso_muster_three_lordship_actions(monkeypatch) -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    alf = s.lords["alfonso"]
    ped = s.lords["pedro_ansurez"]
    alf.cylinder = Cylinder(kind="locale", locale_id="leon")
    alf.in_stronghold = False
    alf.assets = {"coin": 3, "prov": 2, "cart": 1, "mule": 1}
    alf.lordship_used = 0
    ped.cylinder = Cylinder(kind="calendar", box=s.calendar.current_box)
    s.meta.phase = "levy"
    s.meta.levy_step = "muster"
    s.meta.active_player = "christian"

    queue = [5]                       # Pedro's Fealty roll, as printed

    def scripted(state):
        v = queue.pop(0)
        state.meta.rng_state += 1
        return v

    monkeypatch.setattr(A, "roll_d6", scripted)

    # 1) Muster a Vassal: Froila Bermúdez, the three-unit marker.
    assert alf.vassals[0].name == "Froila Bermudez"
    apply_action(s, {"type": "levy_take_vassal", "side": "christian",
                     "lord_id": "alfonso", "vassal_index": 0})
    assert alf.forces == {"knights": 2, "men_at_arms": 2, "serfs": 1,
                          "sergeants": 1}
    assert alf.lordship_used == 1

    # 2) Add a card: Milites (C18) — side-wide, at the map edge.
    r = apply_action(s, {"type": "levy_take_capability",
                         "side": "christian", "lord_id": "alfonso",
                         "card_id": "C18"})
    assert r["scope"] == "side_wide"
    assert alf.lordship_used == 2
    # ... and immediately take three of its units for one Provender —
    # "cost him an Asset not an action" (free during Muster, 3.4.2).
    apply_action(s, {"type": "cap_milites", "side": "christian",
                     "lord_id": "alfonso",
                     "units": {"light_horse": 2, "militia": 1},
                     "asset": "prov"})
    assert alf.assets["prov"] == 1          # one of his two Provender
    assert alf.forces["light_horse"] == 2 and alf.forces["militia"] == 1
    assert alf.lordship_used == 2           # NO Levy action consumed

    # 3) Roll to Muster Pedro Ansúrez (Fealty 4): "5" — unsuccessful.
    r = apply_action(s, {"type": "muster_lord", "side": "christian",
                         "lord_id": "pedro_ansurez", "seat": "simancas",
                         "levying_lord_id": "alfonso"})
    assert r == {"success": False, "roll": 5, "fealty": 4,
                 "levying_lord_id": "alfonso"}
    assert ped.cylinder.kind == "calendar"   # nothing happens
    # Out of Lordship: Alfonso's Muster segment this turn is over.
    assert alf.lordship_used == 3 == alf.lordship_rating
    assert not queue


# ---------------------------------------------------------------------------
# BB pp.12-14 — Álvar Fáñez, Command "4": March Júcar -> Játiva (Neutral
# Town in Parias Valencia: no stop); Approach al-Mundir at Valencia,
# who Avoids to Burriana; Approach again at Burriana, he Avoids to
# Baniskula; Álvar must Besiege or Bypass the Enemy Castle — Bypasses
# to keep his 4th action; Ravages Burriana (+½ VP, +1 Loot +1 Prov,
# first yellow Ravaged in Independent Lérida -> al-Mundir's Service
# shifts one box left, 4.7.2 ENFORCING PARIAS); then Feeds: six units
# plus one Mule = 7 mouths -> 2 Provender/Loot, eating exactly the
# Ravage haul (the Mule is fed, not discarded — Greed, 4.8.1).
# ---------------------------------------------------------------------------

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


def test_bgbook_alvar_march_ravage_feed_chain() -> None:
    s = _activate("scenario_a_toledo_beset", "alvar_fanez", seed=1)
    alvar, mund, abu = (s.lords["alvar_fanez"], s.lords["al_mundir"],
                        s.lords["abu_bakr"])
    # Álvar in the Júcar Region with six units and one Mule; "neither
    # any Provender nor any Loot" -> Unladen, 1 action per Way.
    alvar.cylinder = Cylinder(kind="locale", locale_id="jucar")
    alvar.in_stronghold = False
    alvar.forces = {"knights": 1, "sergeants": 2, "men_at_arms": 1,
                    "serfs": 1, "militia": 1}
    alvar.assets = {"mule": 1}
    # Valencia Taifa at Parias (its Lord off-map); al-Mundir (Lérida,
    # Independent) stands at Valencia with Transport enough to Avoid.
    abu.cylinder = Cylinder(kind="calendar", box=5)
    s.taifas["valencia"].status = "parias"
    mund.cylinder = Cylinder(kind="locale", locale_id="valencia")
    mund.in_stronghold = False
    mund.forces = {"sergeants": 1, "light_horse": 1}
    mund.assets = {"cart": 1, "prov": 1}
    s.taifas["lerida"].status = "independent"
    s.calendar.service_markers = [
        m for m in s.calendar.service_markers if m.lord_id != "al_mundir"]
    s.calendar.service_markers.append(
        ServiceMarker(lord_id="al_mundir", box=10))
    assert s.meta.actions_remaining == 4     # Command rating "4"
    vp0 = s.score.christian

    # Action 1: March Júcar -> Játiva. Neutral Town (Parias Taifa):
    # no forced stop, no Besiege/Bypass question.
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "jativa", "way_type": "road"})
    assert s.meta.actions_remaining == 3 and s.pending is None

    # Action 2: Approach al-Mundir at Valencia -> he Avoids to
    # Burriana ("Another possible destination was Alpuente").
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "valencia", "way_type": "road"})
    assert s.pending is not None
    assert s.pending.kind == "march_arrival_response"
    r = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                         "target_locale_id": "burriana",
                         "way_type": "road"})
    assert r["avoided_to"] == "burriana"
    # Álvar alone at the still-Neutral City: no Besiege/Bypass.
    assert s.pending is None

    # Action 3: invade Lérida Taifa, Approach at Burriana -> al-Mundir
    # Avoids up the coast to Baniskula; Álvar now faces an Enemy
    # Castle: Besiege (forfeit action 4) or Bypass — he Bypasses.
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "burriana", "way_type": "road"})
    assert s.pending.kind == "march_arrival_response"
    r = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                         "target_locale_id": "baniskula",
                         "way_type": "road"})
    assert r["avoided_to"] == "baniskula"
    assert s.pending is not None
    assert s.pending.kind == "besiege_or_bypass"
    apply_action(s, {"type": "respond_bypass", "side": "christian"})
    assert s.meta.actions_remaining == 1     # 4th action retained

    # Action 4: Ravage Burriana (Enemy, not yet Ravaged; Bypassing is
    # irrelevant).
    r = apply_action(s, {"type": "cmd_ravage", "side": "christian"})
    assert s.locales["burriana"].ravaged == "yellow"
    assert s.score.christian - vp0 == 0.5          # 5.1
    assert alvar.assets == {"mule": 1, "loot": 1, "prov": 1}
    assert r["enforcing_parias"] is True
    # First yellow Ravaged in Lérida (odd) -> Service one box left.
    sm = next(m for m in s.calendar.service_markers
              if m.lord_id == "al_mundir" and m.vassal_id is None)
    assert sm.box == 9

    # Feed (4.8.1): 6 units + 1 Mule = 7 mouths -> 2 Prov/Loot. Álvar
    # has exactly 1 Prov + 1 Loot — both eaten; the Mule is fed, not
    # let go (Greed: "if he can Feed them, he must do so").
    r = apply_action(s, {"type": "end_card", "side": "christian"})
    fed = {e["lord_id"]: e for e in r["feed"]["fed"]}
    assert fed["alvar_fanez"]["needed"] == 2
    assert fed["alvar_fanez"]["use_prov"] == 1
    assert fed["alvar_fanez"]["use_loot"] == 1
    assert fed["alvar_fanez"]["short"] == 0
    assert fed["alvar_fanez"]["mules_discarded"] == 0
    assert alvar.assets == {"mule": 1, "loot": 0, "prov": 0}
    # al-Mundir (Moved on Álvar's card) Feeds too: 2 units -> 1 Prov.
    assert fed["al_mundir"]["needed"] == 1
    assert fed["al_mundir"]["use_prov"] == 1
    assert mund.assets == {"cart": 1, "prov": 0}
