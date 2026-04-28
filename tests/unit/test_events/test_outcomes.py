import pytest

from game.core.dice import SeededRNG
from game.core.enums import OutcomeAction, OutcomeTarget
from game.events.models import ChoiceDef, OutcomeDef, OutcomeResult
from game.events.outcomes import resolve_outcomes

from tests.unit.conftest import make_warrior


def _make_choice(outcomes: list[OutcomeDef]) -> ChoiceDef:
    return ChoiceDef(
        index=0,
        label="Test Choice",
        description="A test choice",
        outcomes=tuple(outcomes),
    )


# ---------------------------------------------------------------------------
# expr-based outcomes
# ---------------------------------------------------------------------------


def test_expr_heal():
    outcome = OutcomeDef(
        action=OutcomeAction.HEAL,
        target=OutcomeTarget.ALL,
        expr="target.hp * 0.25",
    )
    choice = _make_choice([outcome])
    player = make_warrior("p1")  # hp=120
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, [player], rng)
    assert len(results) == 1
    assert results[0].player_id == "p1"
    assert results[0].action == OutcomeAction.HEAL
    assert results[0].amount == 30  # 120 * 0.25


def test_expr_static_damage():
    outcome = OutcomeDef(
        action=OutcomeAction.DAMAGE,
        target=OutcomeTarget.VOTER,
        expr="15",
    )
    choice = _make_choice([outcome])
    player = make_warrior("p1")
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, [player], rng)
    assert len(results) == 1
    assert results[0].amount == 15


# ---------------------------------------------------------------------------
# value-based outcomes
# ---------------------------------------------------------------------------


def test_static_value():
    outcome = OutcomeDef(
        action=OutcomeAction.GIVE_GOLD,
        target=OutcomeTarget.ALL,
        value=50,
    )
    choice = _make_choice([outcome])
    players = [make_warrior("p1"), make_warrior("p2")]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    assert len(results) == 2
    assert all(r.amount == 50 for r in results)
    assert all(r.action == OutcomeAction.GIVE_GOLD for r in results)


# ---------------------------------------------------------------------------
# Target types
# ---------------------------------------------------------------------------


def test_target_voter():
    outcome = OutcomeDef(
        action=OutcomeAction.GIVE_XP,
        target=OutcomeTarget.VOTER,
        value=100,
    )
    choice = _make_choice([outcome])
    players = [make_warrior("p1"), make_warrior("p2")]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    # VOTER targets only the first player
    assert len(results) == 1
    assert results[0].player_id == "p1"


def test_target_all():
    outcome = OutcomeDef(
        action=OutcomeAction.HEAL,
        target=OutcomeTarget.ALL,
        value=20,
    )
    choice = _make_choice([outcome])
    players = [make_warrior(f"p{i}") for i in range(4)]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    assert len(results) == 4
    assert {r.player_id for r in results} == {"p0", "p1", "p2", "p3"}


def test_target_random_one():
    outcome = OutcomeDef(
        action=OutcomeAction.APPLY_EFFECT,
        target=OutcomeTarget.RANDOM_ONE,
        effect_id="fortify",
    )
    choice = _make_choice([outcome])
    players = [make_warrior(f"p{i}") for i in range(4)]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    assert len(results) == 1
    assert results[0].player_id in {"p0", "p1", "p2", "p3"}
    assert results[0].effect_id == "fortify"


def test_random_one_deterministic():
    """Same seed should pick the same random target."""
    outcome = OutcomeDef(
        action=OutcomeAction.GIVE_GOLD,
        target=OutcomeTarget.RANDOM_ONE,
        value=10,
    )
    choice = _make_choice([outcome])
    players = [make_warrior(f"p{i}") for i in range(4)]

    rng1 = SeededRNG(42)
    results1 = resolve_outcomes(choice, players, rng1)
    rng2 = SeededRNG(42)
    results2 = resolve_outcomes(choice, players, rng2)

    assert results1[0].player_id == results2[0].player_id


# ---------------------------------------------------------------------------
# Multiple outcomes per choice
# ---------------------------------------------------------------------------


def test_multiple_outcomes():
    outcomes = [
        OutcomeDef(action=OutcomeAction.TAKE_GOLD, target=OutcomeTarget.ALL, value=10),
        OutcomeDef(action=OutcomeAction.GIVE_XP, target=OutcomeTarget.ALL, value=50),
    ]
    choice = _make_choice(outcomes)
    players = [make_warrior("p1"), make_warrior("p2")]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    # 2 outcomes * 2 players = 4 results
    assert len(results) == 4
    gold_results = [r for r in results if r.action == OutcomeAction.TAKE_GOLD]
    xp_results = [r for r in results if r.action == OutcomeAction.GIVE_XP]
    assert len(gold_results) == 2
    assert len(xp_results) == 2


# ---------------------------------------------------------------------------
# Empty outcomes
# ---------------------------------------------------------------------------


def test_empty_outcomes():
    choice = _make_choice([])
    players = [make_warrior("p1")]
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, players, rng)
    assert results == ()


# ---------------------------------------------------------------------------
# Item and combat outcomes
# ---------------------------------------------------------------------------


def test_give_item_outcome():
    outcome = OutcomeDef(
        action=OutcomeAction.GIVE_ITEM,
        target=OutcomeTarget.VOTER,
        item_id="health_potion",
    )
    choice = _make_choice([outcome])
    player = make_warrior("p1")
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, [player], rng)
    assert len(results) == 1
    assert results[0].item_id == "health_potion"
    assert results[0].amount == 0  # No numeric amount for items


def test_start_combat_outcome():
    outcome = OutcomeDef(
        action=OutcomeAction.START_COMBAT,
        target=OutcomeTarget.ALL,
        enemy_group=("water_elemental",),
        combat_location_id="dark_cave",
    )
    choice = _make_choice([outcome])
    player = make_warrior("p1")
    rng = SeededRNG(42)

    results = resolve_outcomes(choice, [player], rng)
    assert len(results) == 1
    assert results[0].action == OutcomeAction.START_COMBAT
    assert results[0].enemy_group == ("water_elemental",)
    assert results[0].combat_location_id == "dark_cave"
