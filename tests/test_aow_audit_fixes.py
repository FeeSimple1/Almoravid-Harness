"""Regression tests for bugs surfaced by the Arts of War card-by-card
audit (see AOW_AUDIT.md). Each pins a specific card's corrected behavior.

  * M6  Feigned Retreat — resolver must park it in the bucket the Battle
        readers consult (this_levy_events), else it is a no-op in real play.
  * C9/M7 Slingers — max 3 Militia per Lord; x1 in Battle, x1/2 in Storm (4.5.2).
  * C7/M3/M6 Javelins — x1/2 (not x1) in Storm (4.5.2).
  * C20 Al-Qadir — the two Jihad removed must come from ONE eligible Taifa.
  * C4/M4 Arid Terrain — a group March feeds up to 2 Marching Lords, not 1.
"""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.battle import BattleSide, build_strike_rows
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy


# --- M6 Feigned Retreat: correct Hold bucket -------------------------------

def test_m6_resolves_into_battle_readable_bucket() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    resolve_event(s, "muslim", "M6")
    # Battle/Sally Round-2 readers and _discard_round1_events look in
    # this_levy_events — M6 must land there, not this_campaign_events.
    assert "M6" in s.decks.this_levy_events.get("muslim", [])
    assert "M6" not in s.decks.this_campaign_events.get("muslim", [])


# --- C9/M7 Slingers + C7 Javelins: cap and Storm halving (4.5.2) -----------

def _side(caps, forces):
    return BattleSide(side="christian", role="attacker",
                      lord_ids=["alvar_fanez"], forces=forces,
                      capabilities_in_play=caps)

def test_slingers_capped_at_three_per_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    rows = build_strike_rows(s, _side(["C9"], {"militia": 5}), context="battle")
    sl = [r for r in rows if r.kind == "slingers"]
    assert len(sl) == 1 and sl[0].count == 3      # capped from 5 to 3
    assert sl[0].rate == "x1"

def test_slingers_half_rate_in_storm() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    rows = build_strike_rows(s, _side(["C9"], {"militia": 3}), context="storm")
    sl = [r for r in rows if r.kind == "slingers"]
    assert sl and sl[0].rate == "x1/2"            # 4.5.2 Storm halving

def test_javelins_half_rate_in_storm() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    rows = build_strike_rows(s, _side(["C7"], {"militia": 2}), context="storm")
    jv = [r for r in rows if r.kind == "javelins"]
    assert jv and all(r.rate == "x1/2" for r in jv)
    # In Battle the same units fire javelins at x1.
    rows_b = build_strike_rows(s, _side(["C7"], {"militia": 2}), context="battle")
    assert any(r.kind == "javelins" and r.rate == "x1" for r in rows_b)


# --- C20 Al-Qadir: removal confined to a single Taifa ----------------------

def test_c20_al_qadir_removes_within_one_taifa() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Find two distinct Parias/Reconquista Taifas free of Muslim Lords,
    # each with exactly one Jihad marker on one Locale.
    picks = []
    for t in s.taifas.values():
        if t.status not in ("parias", "reconquista"):
            continue
        if any(L.side == "muslim" and L.cylinder.kind == "locale"
               and L.cylinder.locale_id in t.locale_ids
               for L in s.lords.values()):
            continue
        # zero out then seed one marker
        for lid in t.locale_ids:
            s.locales[lid].jihad_markers = 0
        s.locales[t.locale_ids[0]].jihad_markers = 1
        picks.append(t.id)
        if len(picks) == 2:
            break
    assert len(picks) == 2, "need two eligible Taifas for this test"
    total_before = sum(s.locales[l].jihad_markers
                       for t in picks for l in s.taifas[t].locale_ids)
    assert total_before == 2
    r = resolve_event(s, "christian", "C20")
    # Only ONE Taifa's single marker may be removed (can't span Taifas).
    assert r["jihad_removed"] == 1
    remaining = sum(s.locales[l].jihad_markers
                    for t in picks for l in s.taifas[t].locale_ids)
    assert remaining == 1


def test_c20_al_qadir_removes_two_from_same_taifa() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for t in s.taifas.values():
        if t.status not in ("parias", "reconquista"):
            continue
        if any(L.side == "muslim" and L.cylinder.kind == "locale"
               and L.cylinder.locale_id in t.locale_ids
               for L in s.lords.values()):
            continue
        for lid in t.locale_ids:
            s.locales[lid].jihad_markers = 0
        s.locales[t.locale_ids[0]].jihad_markers = 3   # 3 in one Taifa
        target = t.id
        break
    r = resolve_event(s, "christian", "C20")
    assert r["jihad_removed"] == 2                       # two from one Taifa
    assert sum(s.locales[l].jihad_markers
               for l in s.taifas[target].locale_ids) == 1


# --- C4/M4 Arid Terrain: group March feeds up to 2 Lords -------------------

def _setup_group_march(seed=11):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == "alfonso":
            break
        apply_action(s, {"type": "command_reveal", "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != "alfonso":
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    assert s.meta.active_lord_id == "alfonso"
    return s


def test_arid_terrain_group_march_feeds_two_lords() -> None:
    s = _setup_group_march()
    here = "leon"
    for lid in ("alfonso", "garcia_ordonez"):
        L = s.lords[lid]
        L.cylinder = Cylinder(kind="locale", locale_id=here)
        L.in_stronghold = False
        L.moved_fought = False
        L.first_march_used_this_card = False
        L.forces = {"knights": 2, "men_at_arms": 2}
        L.assets = {"prov": 3}
    s.decks.this_levy_events["muslim"] = ["M4"]
    prov_before = {lid: s.lords[lid].assets.get("prov", 0)
                   for lid in ("alfonso", "garcia_ordonez")}
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "sahagun", "way_type": "road",
                     "group_lord_ids": ["garcia_ordonez"]})
    # BOTH marching Lords fed (each lost Provender), not just the leader.
    assert s.lords["alfonso"].assets.get("prov", 0) < prov_before["alfonso"]
    assert s.lords["garcia_ordonez"].assets.get("prov", 0) < prov_before["garcia_ordonez"]
    assert "M4" in s.decks.discard
