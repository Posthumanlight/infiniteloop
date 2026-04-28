from game.combat.models import ActionRequest, ActionResult, DamageResult, HitResult
from game.core.enums import ActionType, DamageType, EntityType
from game.core.game_models import (
    CombatSnapshot,
    EntitySnapshot,
    LocationStatusInfo,
    TurnBatch,
)
from bot.tools.combat_renderer import render_combat_end, render_combat_start, render_status


def test_render_combat_end_includes_final_round_recap_and_victory():
    batch = TurnBatch(
        results=(
            ActionResult(
                actor_id="p1",
                action=ActionRequest(
                    actor_id="p1",
                    action_type=ActionType.ACTION,
                    skill_id="slash",
                    target_ids=((0, "e1"),),
                ),
                hits=(
                    HitResult(
                        target_id="e1",
                        damage=DamageResult(
                            amount=12,
                            damage_type=DamageType.SLASHING,
                            is_crit=False,
                            formula_id="slash",
                        ),
                    ),
                ),
                round_number=3,
            ),
        ),
        entities={
            "p1": EntitySnapshot(
                entity_id="p1",
                name="Hero",
                entity_type=EntityType.PLAYER,
                current_hp=80,
                max_hp=120,
                current_energy=40,
                max_energy=100,
                is_alive=True,
            ),
            "e1": EntitySnapshot(
                entity_id="e1",
                name="Goblin",
                entity_type=EntityType.ENEMY,
                current_hp=0,
                max_hp=40,
                current_energy=0,
                max_energy=50,
                is_alive=False,
            ),
        },
        whose_turn=None,
        combat_ended=True,
        victory=True,
    )

    text = render_combat_end(batch, {})

    assert "Final round recap - Round 3" in text
    assert "Hero uses slash on Goblin for 12 damage" in text
    assert "Goblin is defeated" in text
    assert "Victory" in text
    assert "Survivors:" in text


def test_render_combat_start_and_status_include_location_context():
    snapshot = CombatSnapshot(
        entities={
            "p1": EntitySnapshot(
                entity_id="p1",
                name="Hero",
                entity_type=EntityType.PLAYER,
                current_hp=80,
                max_hp=120,
                current_energy=40,
                max_energy=100,
                is_alive=True,
            ),
        },
        turn_order=("p1",),
        whose_turn="p1",
        round_number=1,
        location_name="Burning Cavern",
        location_statuses=(
            LocationStatusInfo(
                status_id="burning_ground",
                name="Burning Ground",
                description="Hot floor.",
            ),
        ),
    )

    start_text = render_combat_start(snapshot, {})
    status_text = render_status(snapshot, {})

    assert "Location: Burning Cavern" in start_text
    assert "Statuses: Burning Ground" in start_text
    assert "Location: Burning Cavern" in status_text
    assert "Statuses: Burning Ground" in status_text
