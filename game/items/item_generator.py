import uuid

from game.core.data_loader import load_item_blueprint
from game.core.enums import ItemEffect
from game.core.formula_eval import evaluate_expr
from game.items.items import GeneratedItemEffect, ItemBlueprint, ItemInstance


def generate_item(
    blueprint: ItemBlueprint,
    *,
    quality: int = 1,
    instance_id: str | None = None,
) -> ItemInstance:
    effects: list[GeneratedItemEffect] = []

    for effect in blueprint.effects:
        if effect.effect_type == ItemEffect.MODIFY_STAT:
            value = evaluate_expr(effect.expr or "0", {"quality": quality})
            effects.append(GeneratedItemEffect(
                effect_type=effect.effect_type,
                stat=effect.stat,
                value=value,
            ))
            continue

        effects.append(GeneratedItemEffect(
            effect_type=effect.effect_type,
            skill_id=effect.skill_id,
            passive_id=effect.passive_id,
        ))

    return ItemInstance(
        instance_id=instance_id or uuid.uuid4().hex,
        blueprint_id=blueprint.blueprint_id,
        name=blueprint.name,
        item_type=blueprint.item_type,
        quality=int(quality),
        effects=tuple(effects),
    )


def generate_item_from_blueprint_id(
    blueprint_id: str,
    *,
    quality: int = 1,
    instance_id: str | None = None,
) -> ItemInstance:
    return generate_item(
        load_item_blueprint(blueprint_id),
        quality=quality,
        instance_id=instance_id,
    )
