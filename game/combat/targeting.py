from game.character.base_entity import BaseEntity
from game.combat.models import CombatState
from game.core.enums import EntityType, TargetType


_PLAYER_TEAM = frozenset({EntityType.PLAYER, EntityType.ALLY})


def is_alive(entity: BaseEntity) -> bool:
    return entity.current_hp > 0


def is_player_team(entity_type: EntityType) -> bool:
    return entity_type in _PLAYER_TEAM


def are_allies(a: BaseEntity, b: BaseEntity) -> bool:
    return is_player_team(a.entity_type) == is_player_team(b.entity_type)


def are_enemies(a: BaseEntity, b: BaseEntity) -> bool:
    return not are_allies(a, b)


def is_player_controlled(entity: BaseEntity) -> bool:
    return entity.entity_type == EntityType.PLAYER


def is_ai_controlled(entity: BaseEntity) -> bool:
    return entity.entity_type in {EntityType.ENEMY, EntityType.ALLY}


def get_allies(state: CombatState, entity_id: str) -> list[str]:
    entity = state.entities[entity_id]
    return [
        eid for eid, e in state.entities.items()
        if are_allies(entity, e) and is_alive(e)
    ]


def get_enemies(state: CombatState, entity_id: str) -> list[str]:
    entity = state.entities[entity_id]
    return [
        eid for eid, e in state.entities.items()
        if are_enemies(entity, e) and is_alive(e)
    ]


def resolve_targets(
    state: CombatState,
    actor_id: str,
    target_type: TargetType,
    selected_id: str | None,
) -> list[str]:
    match target_type:
        case TargetType.SINGLE_ENEMY:
            enemies = get_enemies(state, actor_id)
            if selected_id is None or selected_id not in enemies:
                raise ValueError(
                    f"Invalid target '{selected_id}'. "
                    f"Valid enemies: {enemies}"
                )
            return [selected_id]

        case TargetType.ALL_ENEMIES:
            return get_enemies(state, actor_id)

        case TargetType.SINGLE_ALLY:
            allies = get_allies(state, actor_id)
            if selected_id is None or selected_id not in allies:
                raise ValueError(
                    f"Invalid target '{selected_id}'. "
                    f"Valid allies: {allies}"
                )
            return [selected_id]

        case TargetType.ALL_ALLIES:
            return get_allies(state, actor_id)

        case TargetType.SELF:
            return [actor_id]
