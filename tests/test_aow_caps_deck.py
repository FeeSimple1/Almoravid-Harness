"""Deck-manipulation caps: C25/M25 El Cid, C26/M26 Al-Faraj, M8 Dawud(b)."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _act(s, lord_id, side):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = 2


def test_el_cid_plays_event_from_deck() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    rod = s.lords.get("rodrigo_campeador")
    if rod is None:
        import pytest
        pytest.skip("Rodrigo Campeador not in this scenario")
    rod.capabilities.append("C25")
    rod.cylinder = Cylinder(kind="locale", locale_id="leon")
    # Ensure C3 (Swollen River) is available in the deck.
    for b in (s.decks.held, s.decks.this_levy_events, s.decks.this_campaign_events):
        b.get("christian", []) and b["christian"].remove("C3") if "C3" in b.get("christian", []) else None
    if "C3" in s.decks.discard:
        s.decks.discard.remove("C3")
    _act(s, "rodrigo_campeador", "christian")
    moves = [m for m in legal_moves(s) if m["type"] == "cap_play_event_from_deck"]
    assert any(m["card_id"] == "C3" for m in moves)
    apply_action(s, {"type": "cap_play_event_from_deck", "side": "christian",
                     "source": "elcid", "card_id": "C3"})
    # Swollen River (Hold) now sits in the Christian hold bucket.
    assert "C3" in s.decks.this_levy_events.get("christian", [])
    # Once per card.
    assert not any(m["type"] == "cap_play_event_from_deck" for m in legal_moves(s))


def test_al_faraj_forces_enemy_held_discard() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    rod = s.lords.get("rodrigo_campeador")
    if rod is None:
        import pytest
        pytest.skip("Rodrigo Campeador not in this scenario")
    rod.capabilities.append("C26")
    rod.cylinder = Cylinder(kind="locale", locale_id="leon")
    # An enemy Muslim Lord co-located; give the Muslim side a Held card.
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.decks.this_levy_events["muslim"] = ["M1"]
    _act(s, "rodrigo_campeador", "christian")
    assert any(m["type"] == "cap_al_faraj" for m in legal_moves(s))
    r = apply_action(s, {"type": "cap_al_faraj", "side": "christian"})
    assert r["discarded"] == "M1"
    assert "M1" in s.decks.discard
    assert s.meta.actions_remaining == 0          # entire card spent


def test_dawud_plays_battle_event_from_deck() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    yusuf = s.lords["yusuf"]
    yusuf.capabilities.append("M8")
    yusuf.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    _act(s, "yusuf", "muslim")
    moves = [m for m in legal_moves(s)
             if m["type"] == "cap_play_event_from_deck" and m["source"] == "dawud"]
    assert moves, "Dawud should offer M2/M6/M7 from deck"
    card = moves[0]["card_id"]
    apply_action(s, {"type": "cap_play_event_from_deck", "side": "muslim",
                     "source": "dawud", "card_id": card})
    in_play = (s.decks.this_levy_events.get("muslim", [])
               + s.decks.this_campaign_events.get("muslim", []))
    assert card in in_play
