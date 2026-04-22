from game.combat.models import ActionRequest, ActionResult, DamageResult, HitResult
from game.core.enums import ActionType, DamageType, EntityType
from game.core.game_models import EntitySnapshot, TurnBatch
from bot.tools.combat_renderer import render_combat_end


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
