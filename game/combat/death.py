from __future__ import annotations

from game.combat.models import CombatState, HitResult
from game.core.dice import SeededRNG


def resolve_death_event(
    state: CombatState,
    dead_id: str,
    *,
    killer_id: str | None,
    rng: SeededRNG | None,
    constants: dict | None,
) -> tuple[CombatState, list[HitResult]]:
    dead = state.entities.get(dead_id)
    if dead is None or dead.current_hp > 0:
        return state, []

    from game.combat.effects import build_effective_expr_context
    from game.combat.passives import PassiveEvent, check_death_passives, check_passives
    from game.combat.summons import despawn_owner_summons
    from game.combat.targeting import get_allies
    from game.core.enums import TriggerType

    dead_ctx = build_effective_expr_context(state, dead_id)
    killer_ctx = None
    if killer_id is not None and killer_id in state.entities:
        killer_ctx = build_effective_expr_context(state, killer_id)

    ally_ids = tuple(
        ally_id
        for ally_id in get_allies(state, dead_id)
        if ally_id != dead_id
    )

    results: list[HitResult] = []
    state, death_results = check_death_passives(
        state,
        dead_id,
        rng=rng,
        constants=constants,
        dead_ctx=dead_ctx,
        killer_ctx=killer_ctx,
    )
    results.extend(death_results)

    current_dead = state.entities.get(dead_id)
    if current_dead is not None and current_dead.current_hp > 0:
        return state, results

    state = despawn_owner_summons(state, dead_id)

    if killer_id is not None and killer_id != dead_id and killer_id in state.entities:
        state, kill_results = check_passives(
            state,
            killer_id,
            PassiveEvent(
                trigger=TriggerType.ON_KILL,
                payload={
                    "killed": dead_ctx,
                    "dead": dead_ctx,
                    **({"attacker": killer_ctx} if killer_ctx is not None else {}),
                },
            ),
            rng=rng,
            constants=constants,
        )
        results.extend(kill_results)

    ally_payload = {
        "dead": dead_ctx,
        **({"attacker": killer_ctx} if killer_ctx is not None else {}),
    }
    for ally_id in ally_ids:
        ally = state.entities.get(ally_id)
        if ally is None or ally.current_hp <= 0:
            continue
        state, ally_results = check_passives(
            state,
            ally_id,
            PassiveEvent(
                trigger=TriggerType.ON_ALLY_DEATH,
                payload=ally_payload,
            ),
            rng=rng,
            constants=constants,
        )
        results.extend(ally_results)

    return state, results
