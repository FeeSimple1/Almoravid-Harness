"""Phase 6a: Combat-event effects (C7 Baggage Parapet, M7 Spear Wall,
C8 Cantador).

Each test pairs a deterministic seed with a Hold-event injection and
asserts the per-card effect actually changed Battle behavior (Pattern 9
'rule-cite-but-no-enforce'), plus that the card was discarded after its
window expired (Pattern 13 lifecycle-leak).
"""

from __future__ import annotations

import copy

from almoravid.battle import (
    BattleSide,
    _consume_camp_attack,
    _discard_round1_events,
    _resolve_step,
    resolve_battle,
    resolve_storm,
)
from almoravid.scenarios import load_scenario


# ---------------------------------------------------------------------------
# C8 Cantador (Christian Round-1 Melee +1 on Knights/Sergeants, up to 4)
# ---------------------------------------------------------------------------


def test_c8_cantador_adds_round1_melee_hits() -> None:
    """With C8 in this_levy_events, attacker's Round-1 melee step
    deals strictly more Hits than without it (same seed)."""
    def _run(hold_c8: bool) -> int:
        s = load_scenario("scenario_a_toledo_beset", seed=11)
        if hold_c8:
            s.decks.this_levy_events["christian"] = ["C8"]
        atk = BattleSide(side="christian", role="attacker",
                         lord_ids=["alfonso"], forces={"knights": 4})
        dfd = BattleSide(side="muslim", role="defender",
                         lord_ids=["al_mutamid"], forces={"sergeants": 4})
        # Run Round 1 horse-melee step in isolation.
        res = _resolve_step(
            s, "2.b", "attacker", "melee", "horse",
            atk, dfd, round_index=1,
        )
        return res.rounded_hits

    without = _run(False)
    with_ = _run(True)
    # 4 Knights x2 = 8 base hits. +4 from C8 = 12. (Cap at 4 units.)
    assert with_ == without + 4, f"expected +4 hits, got {with_ - without}"


def test_c8_cantador_capped_at_four_units() -> None:
    """6 Knights: C8 only boosts 4 of them (cap per card text)."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["christian"] = ["C8"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 6})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=1)
    # 6 Knights x2 = 12 base. +4 cap = 16. (NOT 12+6=18.)
    assert res.rounded_hits == 16


def test_c8_cantador_inactive_after_round1() -> None:
    """Round 2 melee step: C8 should NOT add hits."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["christian"] = ["C8"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=2)
    assert res.rounded_hits == 8  # 4 Knights x2, no bonus


def test_c8_cantador_muslim_side_unaffected() -> None:
    """C8 is Christian-only — Muslim side holding it is a no-op."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["muslim"] = ["C8"]
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"knights": 4})
    res = _resolve_step(s, "2.b", "attacker", "melee", "horse",
                        atk, dfd, round_index=1)
    # Muslim has Sergeants but no C8 effect (wrong side).
    assert res.rounded_hits == 4  # 4 Sgts x1, no bonus


def test_c8_discarded_after_round1_in_battle() -> None:
    """After Round 1 ends in resolve_battle, C8 moves to discard."""
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.decks.this_levy_events["christian"] = ["C8"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 8})
    # max_rounds=2 so we still execute Round 2 even if Round 1 doesn't end it
    resolve_battle(s, atk, dfd, max_rounds=2)
    # C8 must have moved to discard
    assert "C8" in s.decks.discard
    assert "C8" not in s.decks.this_levy_events.get("christian", [])


# ---------------------------------------------------------------------------
# M7 Spear Wall (Muslim Armored Foot +1 Armor vs Christian Horse Melee)
# ---------------------------------------------------------------------------


def test_m7_spear_wall_extends_armor_against_horse_melee() -> None:
    """With M7 held, Muslim Men-at-Arms surviving Horse-Melee hits
    over many trials > without M7 held (same seed)."""
    survivors_with = 0
    survivors_without = 0
    trials = 30
    for seed in range(trials):
        for hold in (False, True):
            s = load_scenario("scenario_a_toledo_beset", seed=seed)
            if hold:
                s.decks.this_levy_events["muslim"] = ["M7"]
            atk = BattleSide(side="christian", role="attacker",
                             lord_ids=["alfonso"], forces={"knights": 1})
            dfd = BattleSide(side="muslim", role="defender",
                             lord_ids=["al_mutamid"],
                             forces={"men_at_arms": 8})
            _resolve_step(s, "2.b", "attacker", "melee", "horse",
                          atk, dfd, round_index=1)
            survivors = sum(dfd.forces.values())
            if hold:
                survivors_with += survivors
            else:
                survivors_without += survivors
    # +1 Armor (1-3 -> 1-4) means roughly 1/6 more cancels.
    # Over 30 trials we should see strictly more survivors.
    assert survivors_with > survivors_without, (
        f"M7 didn't reduce losses: with={survivors_with}, "
        f"without={survivors_without}"
    )


def test_m7_does_not_apply_against_foot_strikers() -> None:
    """M7 only fires vs Christian HORSE Melee. Foot strikers should
    see the unmodified 1-3 Armor range."""
    survivors_with = 0
    survivors_without = 0
    trials = 30
    for seed in range(trials):
        for hold in (False, True):
            s = load_scenario("scenario_a_toledo_beset", seed=seed)
            if hold:
                s.decks.this_levy_events["muslim"] = ["M7"]
            # Foot-melee step (2.d): Christian Men-at-Arms striking.
            atk = BattleSide(side="christian", role="attacker",
                             lord_ids=["alfonso"],
                             forces={"men_at_arms": 4})
            dfd = BattleSide(side="muslim", role="defender",
                             lord_ids=["al_mutamid"],
                             forces={"men_at_arms": 6})
            _resolve_step(s, "2.d", "attacker", "melee", "foot",
                          atk, dfd, round_index=1)
            survivors = sum(dfd.forces.values())
            if hold:
                survivors_with += survivors
            else:
                survivors_without += survivors
    # Foot vs Foot: M7 should have no effect.
    assert survivors_with == survivors_without


def test_m7_does_not_apply_in_storm() -> None:
    """M7 card text: 'not in Storm'. Storm Hits should never consult M7."""
    survivors_with = 0
    survivors_without = 0
    trials = 30
    for seed in range(trials):
        for hold in (False, True):
            s = load_scenario("scenario_a_toledo_beset", seed=seed)
            if hold:
                s.decks.this_levy_events["muslim"] = ["M7"]
            atk = BattleSide(side="christian", role="attacker",
                             lord_ids=["alfonso"], forces={"knights": 2})
            dfd = BattleSide(side="muslim", role="defender",
                             lord_ids=["al_mutamid"],
                             forces={"men_at_arms": 6})
            _resolve_step(s, "2.b", "attacker", "melee", "horse",
                          atk, dfd, round_index=1, context="storm")
            survivors = sum(dfd.forces.values())
            if hold:
                survivors_with += survivors
            else:
                survivors_without += survivors
    assert survivors_with == survivors_without


# ---------------------------------------------------------------------------
# C7 Baggage Parapet — Camp Attack cancellation
# ---------------------------------------------------------------------------


def test_c7_cancels_muslim_camp_attack() -> None:
    """C7 in this_levy_events on Christian side cancels M2 at Battle
    start. Both cards go to discard; neither remains in their bucket."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    s.decks.this_levy_events["christian"] = ["C7"]
    s.decks.this_campaign_events["muslim"] = ["M2"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 2})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 2})
    # Record Lord assets before the helper to confirm NO Spoils transfer.
    pre_christian = copy.deepcopy(s.lords["alfonso"].assets)
    pre_muslim = copy.deepcopy(s.lords["al_mutamid"].assets)
    from almoravid.battle import BattleResult
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    _consume_camp_attack(s, atk, dfd, result)
    assert "M2" in s.decks.discard
    assert "C7" in s.decks.discard
    assert "M2" not in s.decks.this_campaign_events.get("muslim", [])
    assert "C7" not in s.decks.this_levy_events.get("christian", [])
    # Cancelled: assets unchanged.
    assert s.lords["alfonso"].assets == pre_christian
    assert s.lords["al_mutamid"].assets == pre_muslim
    assert any("cancelled by Baggage Parapet" in n for n in result.notes)


def test_c7_does_not_cancel_christian_camp_attack() -> None:
    """C2 is Christian Camp Attack — C7 is the same side and per card
    text does NOT cancel it. C2 still fires."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    s.decks.this_levy_events["christian"] = ["C7"]
    s.decks.this_campaign_events["christian"] = ["C2"]
    # Reset both Lords' assets so the Spoils transfer is exactly
    # observable (scenario defaults vary).
    s.lords["al_mutamid"].assets = {"coin": 5}
    s.lords["alfonso"].assets = {}
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 2})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 2})
    from almoravid.battle import BattleResult
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    _consume_camp_attack(s, atk, dfd, result)
    assert "C2" in s.decks.discard
    # Muslim lost 4 coin (2 as Spoils + 2 removed).
    assert s.lords["al_mutamid"].assets.get("coin", 0) == 1
    # Christian Alfonso received 2 coin as Spoils.
    assert s.lords["alfonso"].assets.get("coin", 0) == 2
    # C7 still held — wasn't consumed because no M2 to cancel.
    assert "C7" in s.decks.this_levy_events.get("christian", [])


def test_muslim_camp_attack_fires_when_no_baggage_parapet() -> None:
    """Without C7, M2 fires: drains 4 coin from each Christian Lord."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    s.decks.this_campaign_events["muslim"] = ["M2"]
    s.lords["alfonso"].assets = {"coin": 5}
    s.lords["al_mutamid"].assets = {}
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"sergeants": 2})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"knights": 2})
    from almoravid.battle import BattleResult
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    _consume_camp_attack(s, atk, dfd, result)
    assert "M2" in s.decks.discard
    assert s.lords["alfonso"].assets.get("coin", 0) == 1
    assert s.lords["al_mutamid"].assets.get("coin", 0) == 2


# ---------------------------------------------------------------------------
# _discard_round1_events lifecycle
# ---------------------------------------------------------------------------


def test_discard_round1_events_moves_cards_to_discard() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["christian"] = ["C8", "C1"]
    s.decks.this_levy_events["muslim"] = ["M7", "M1"]
    _discard_round1_events(s, ["C8", "M7", "C1", "M1"])
    for cid in ("C8", "M7", "C1", "M1"):
        assert cid in s.decks.discard
    assert s.decks.this_levy_events == {}


def test_discard_skips_cards_not_held() -> None:
    """No-op for cards that aren't in this_levy_events (defensive)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.this_levy_events["christian"] = ["C8"]
    _discard_round1_events(s, ["C8", "M7"])
    assert s.decks.discard.count("C8") == 1
    assert "M7" not in s.decks.discard
