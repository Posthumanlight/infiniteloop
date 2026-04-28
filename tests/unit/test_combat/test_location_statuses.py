from dataclasses import replace

import game.combat.effects as combat_effects
from game.combat.effects import get_effective_major_stat
from game.core.data_loader import CombatLocation, LocationStatusDef
from game.core.enums import LocationStatusAffects

from tests.unit.conftest import make_combat_state


def test_location_status_modifies_only_matching_entity_side(monkeypatch):
    def fake_load_location_status(status_id: str) -> LocationStatusDef:
        assert status_id == "player_attack_bonus"
        return LocationStatusDef(
            status_id=status_id,
            name="Player Attack Bonus",
            description="Players hit harder.",
            affects=LocationStatusAffects.PLAYERS,
            tags=("test",),
            stat_modifiers={"attack": 5},
        )

    monkeypatch.setattr(
        combat_effects,
        "load_location_status",
        fake_load_location_status,
    )
    state = replace(
        make_combat_state(),
        location=CombatLocation(
            location_id="test_location",
            name="Test Location",
            tags=("test",),
            status_ids=("player_attack_bonus",),
        ),
    )

    assert get_effective_major_stat(state, "p1", "attack") == 20
    assert get_effective_major_stat(state, "e1", "attack") == 8
