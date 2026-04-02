from game.character.player_character import PlayerCharacter
from game.core.dice import SeededRNG
from game.core.enums import OutcomeAction, OutcomeTarget
from game.core.formula_eval import ExprContext, evaluate_expr
from game.events.models import ChoiceDef, OutcomeDef, OutcomeResult


def resolve_outcomes(
    choice: ChoiceDef,
    players: list[PlayerCharacter],
    rng: SeededRNG,
) -> tuple[OutcomeResult, ...]:
    """Evaluate all outcomes of a winning choice against the player list.

    Returns OutcomeResult descriptors — does NOT mutate players.
    The server layer interprets these and applies actual state changes.
    """
    results: list[OutcomeResult] = []
    for outcome in choice.outcomes:
        targets = _resolve_targets(outcome, players, rng)
        for player in targets:
            amount = _evaluate_amount(outcome, player)
            results.append(OutcomeResult(
                player_id=player.entity_id,
                action=outcome.action,
                amount=amount,
                item_id=outcome.item_id,
                effect_id=outcome.effect_id,
                enemy_group=outcome.enemy_group,
            ))
    return tuple(results)


def _resolve_targets(
    outcome: OutcomeDef,
    players: list[PlayerCharacter],
    rng: SeededRNG,
) -> list[PlayerCharacter]:
    """Determine which players are affected by an outcome."""
    match outcome.target:
        case OutcomeTarget.VOTER:
            return [players[0]]
        case OutcomeTarget.ALL:
            return list(players)
        case OutcomeTarget.RANDOM_ONE:
            index = rng.d(len(players)) - 1
            return [players[index]]
        case _:
            return []


def _evaluate_amount(outcome: OutcomeDef, player: PlayerCharacter) -> int:
    """Compute the numeric amount for an outcome.

    Uses expr (dynamic, evaluated against player stats) or value (static).
    Returns 0 for outcomes that don't have a numeric component (e.g. give_item).
    """
    if outcome.expr is not None:
        context = _build_expr_context(player)
        return int(evaluate_expr(outcome.expr, context))
    if outcome.value is not None:
        return outcome.value
    return 0


def _build_expr_context(player: PlayerCharacter) -> dict:
    """Build an expression context from a player for formula evaluation."""
    target = ExprContext(
        attack=player.major_stats.attack,
        hp=player.major_stats.hp,
        current_hp=player.current_hp,
        speed=player.major_stats.speed,
        crit_chance=player.major_stats.crit_chance,
        crit_dmg=player.major_stats.crit_dmg,
        resistance=player.major_stats.resistance,
        energy=player.major_stats.energy,
        mastery=player.major_stats.mastery,
    )
    return {"target": target}
