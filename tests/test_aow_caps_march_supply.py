"""March/Supply caps: Adalides/War Drums Bypass-without-stopping,
M19 Guadalquivir, M12 Al-Yazirat al-Hadra (double Supply Source)."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _bypass_without_stopping, _guadalquivir_targets
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def test_adalides_allows_march_after_bypass() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    al = s.lords["alvar_fanez"]
    al.capabilities.append("C3")          # Adalides (this_lord)
    al.bypassed_this_card = True
    assert _bypass_without_stopping(s, "alvar_fanez", "christian") is True
    # Without Adalides, blocked.
    al.capabilities.remove("C3")
    assert _bypass_without_stopping(s, "alvar_fanez", "christian") is False


def test_war_drums_bypass_for_yusuf() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="M22", scope="side_wide", owner_side="muslim"))
    assert _bypass_without_stopping(s, "yusuf", "muslim") is True
    # A non-Lieutenant Taifa Lord does NOT get War Drums Bypass.
    assert _bypass_without_stopping(s, "al_mundir", "muslim") is False


def test_guadalquivir_network_march() -> None:
    s = load_scenario("scenario_f_reconquista", seed=1)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="M19", scope="side_wide", owner_side="muslim"))
    al = s.lords["al_mutamid"]            # Taifa Lord (Sevilla)
    al.cylinder = Cylinder(kind="locale", locale_id="sevilla")  # a Port
    # No Christian lords on the network for a clean test.
    for L in s.lords.values():
        if L.side == "christian":
            L.cylinder = Cylinder(kind="calendar", box=1)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "al_mutamid"
    s.meta.actions_remaining = 2
    tgts = _guadalquivir_targets(s, "al_mutamid")
    assert "cordoba" in tgts and "almeria" in tgts   # named city + a port
    assert any(m["type"] == "cmd_guadalquivir" for m in legal_moves(s))
    apply_action(s, {"type": "cmd_guadalquivir", "side": "muslim",
                     "target_locale_id": "cordoba"})
    assert al.cylinder.locale_id == "cordoba"
    assert s.meta.actions_remaining == 1             # normal cost (1 action)


def test_m12_doubles_yusuf_supply_source() -> None:
    s = load_scenario("scenario_f_reconquista", seed=1)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="M12", scope="side_wide", owner_side="muslim"))
    yusuf = s.lords["yusuf"]
    seat = yusuf.seats[0] if yusuf.seats else "algeciras"
    yusuf.cylinder = Cylinder(kind="locale", locale_id=seat)  # at his Seat
    yusuf.assets = {"prov": 0}
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "muslim"
    s.meta.active_lord_id = "yusuf"
    s.meta.actions_remaining = 2
    r = apply_action(s, {"type": "cmd_supply", "side": "muslim",
                         "source_seats": [seat]})
    # At-Seat Supply with M12 = 2 Sources => +2 Provender (no transport).
    assert r["prov_gained"] == 2
    assert yusuf.assets["prov"] == 2
