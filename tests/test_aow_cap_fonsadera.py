"""C23 Fonsadera: exchange Ready non-Bishop Vassals for 1 Coin or 3 Transport."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder, Vassal


def _setup():
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id="C23", scope="side_wide", owner_side="christian"))
    al = s.lords["alvar_fanez"]
    al.cylinder = Cylinder(kind="locale", locale_id="leon")
    al.in_stronghold = False
    al.vassals = [Vassal(id="v1", name="Mesnaderos", forces={"knights": 1},
                         service_cost=2, ready=True)]
    al.assets = {}
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    return s, al


def test_fonsadera_exchange_for_coin() -> None:
    s, al = _setup()
    assert any(m["type"] == "cap_fonsadera" for m in legal_moves(s))
    apply_action(s, {"type": "cap_fonsadera", "side": "christian",
                     "lord_id": "alvar_fanez", "vassal_index": 0, "mode": "coin"})
    assert al.assets.get("coin", 0) == 1
    assert al.vassals[0].ready is False        # set aside


def test_fonsadera_exchange_for_three_transport() -> None:
    s, al = _setup()
    apply_action(s, {"type": "cap_fonsadera", "side": "christian",
                     "lord_id": "alvar_fanez", "vassal_index": 0,
                     "mode": "transport", "transport_type": "mule"})
    assert al.assets.get("mule", 0) == 3
    assert al.vassals[0].ready is False


def test_fonsadera_rejects_bishop_vassal() -> None:
    s, al = _setup()
    al.vassals = [Vassal(id="bishop_1", name="Bishop", forces={"knights": 1},
                         service_cost=0, ready=True)]
    try:
        apply_action(s, {"type": "cap_fonsadera", "side": "christian",
                         "lord_id": "alvar_fanez", "vassal_index": 0,
                         "mode": "coin"})
        assert False, "Bishops cannot be exchanged"
    except Exception as e:
        assert "bishop" in str(e).lower() or "Bishop" in str(e)
