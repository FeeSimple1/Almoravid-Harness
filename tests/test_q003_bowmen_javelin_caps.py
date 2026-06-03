"""Q-003: the dual-half Bowmen/Javelin capability cards (C4/C5 Arqueros,
M4/M5 Alrama, M3/M6 Harbah) must be deployable/Levyable as This-Lord
Capabilities in normal play -- not just applied by the combat resolver
when already in play. Previously their card data had null capability
metadata, making them unreachable as Levy Capabilities."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.static_data import load_cards


def test_six_cards_have_thislord_capability_metadata() -> None:
    cards = load_cards()["cards"]
    expect = {"C4": "Arqueros", "C5": "Arqueros", "M4": "Alrama",
              "M5": "Alrama", "M3": "Harbah", "M6": "Harbah"}
    for cid, name in expect.items():
        c = cards[cid]
        assert c["no_capability"] is False, f"{cid} still no_capability"
        assert c["capability_scope"] == "this_lord", cid
        assert c["capability_name"] == name, cid


def test_harbah_deploys_to_a_lord_and_one_per_title_cap_applies() -> None:
    """Deploy M3 Harbah onto a Muslim Lord; a second Harbah (M6) cannot
    join the same Lord (3.4.4 one-per-title)."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    apply_action(s, {"type": "begin_levy"})
    assert s.meta.levy_step == "arts_of_war"
    # Advance to the Muslim player's Arts-of-War sub-step.
    apply_action(s, {"type": "aow_draw", "side": "christian"})
    for cid in list(s.decks.pending_draw.get("christian", [])):
        apply_action(s, {"type": "aow_deploy_capability", "side": "christian",
                         "card_id": cid, "lord_id": "alfonso"})
    apply_action(s, {"type": "pass_step", "side": "christian"})
    apply_action(s, {"type": "aow_draw", "side": "muslim"})

    # Pick a Mustered Muslim Lord to receive the capability.
    target = next(lid for lid, lo in s.lords.items()
                  if lo.side == "muslim" and lo.cylinder.kind == "locale")
    # Inject M3 and M6 (Harbah) into the Muslim pending draw to exercise
    # the deploy + one-per-title cap deterministically.
    s.decks.pending_draw["muslim"] = ["M3", "M6"]

    apply_action(s, {"type": "aow_deploy_capability", "side": "muslim",
                     "card_id": "M3", "lord_id": target})
    assert "M3" in s.lords[target].capabilities, "M3 Harbah did not deploy"

    # Second Harbah (M6) to the SAME Lord must be refused (discarded), not
    # added -- one card per title (3.4.4).
    apply_action(s, {"type": "aow_deploy_capability", "side": "muslim",
                     "card_id": "M6", "lord_id": target})
    assert "M6" not in s.lords[target].capabilities, (
        "one-per-title cap failed: M6 Harbah stacked on a Lord already "
        "holding M3 Harbah")
    assert "M6" in s.decks.discard
