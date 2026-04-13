import pytest

from game.core.data_loader import clear_cache, load_enemy
from game.core.enums import CombatLocationType, EnemyCombatType, LocationType
from game.world.generator import WorldGenerator
from game.world.models import GenerationConfig

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def players():
    return [make_warrior("p1")]


def _generate(seed: int, config: GenerationConfig, players, depth: int = 5):
    return WorldGenerator(seed).generate_locations(
        power=1,
        players=players,
        config=config,
        depth=depth,
    )


# ---------------------------------------------------------------------------
# Predetermined sets
# ---------------------------------------------------------------------------

def test_predetermined_set(players):
    config = GenerationConfig(predetermined_set_id="dark_cave_intro")

    locations = _generate(seed=42, config=config, players=players)
    assert len(locations) == 3
    assert locations[0].name == "Goblin Ambush"
    assert locations[0].combat_type == CombatLocationType.NORMAL


# ---------------------------------------------------------------------------
# Random generation
# ---------------------------------------------------------------------------

def test_random_generation_count_in_range(players):
    config = GenerationConfig(count_min=2, count_max=5)

    locations = _generate(seed=42, config=config, players=players)
    assert 2 <= len(locations) <= 5


def test_random_generation_deterministic(players):
    config = GenerationConfig(count_min=3, count_max=3)

    loc1 = _generate(seed=42, config=config, players=players)
    loc2 = _generate(seed=42, config=config, players=players)

    assert len(loc1) == len(loc2)
    for left, right in zip(loc1, loc2):
        assert left.location_type == right.location_type
        assert left.enemy_ids == right.enemy_ids
        assert left.event_id == right.event_id
        assert left.combat_type == right.combat_type


def test_random_generation_has_combat_and_event(players):
    config = GenerationConfig(count_min=5, count_max=5, combat_weight=0.5)

    types_seen: set[LocationType] = set()
    for seed in range(50):
        locations = _generate(seed=seed, config=config, players=players, depth=5)
        for loc in locations:
            types_seen.add(loc.location_type)

    assert LocationType.COMBAT in types_seen
    assert LocationType.EVENT in types_seen


def test_all_combat_weight(players):
    config = GenerationConfig(count_min=3, count_max=3, combat_weight=1.0)

    locations = _generate(seed=42, config=config, players=players)
    assert all(loc.location_type == LocationType.COMBAT for loc in locations)
    assert all(loc.combat_type is not None for loc in locations)


def test_event_locations_have_event_id(players):
    config = GenerationConfig(count_min=5, count_max=5, combat_weight=0.0)

    for seed in range(10):
        locations = _generate(seed=seed, config=config, players=players, depth=5)
        for loc in locations:
            if loc.location_type == LocationType.EVENT:
                assert loc.event_id is not None


# ---------------------------------------------------------------------------
# Combat type rules
# ---------------------------------------------------------------------------

def test_tag_filtering_fire_only_builds_fire_imp_elites(players):
    config = GenerationConfig(
        tags=("fire",),
        count_min=3,
        count_max=3,
        combat_weight=1.0,
    )

    locations = _generate(seed=42, config=config, players=players)
    assert all(loc.combat_type == CombatLocationType.ELITE for loc in locations)
    for loc in locations:
        assert loc.enemy_ids == ("fire_imp",)


def test_normal_rooms_only_use_normal_enemies(players):
    config = GenerationConfig(
        tags=("forest",),
        count_min=3,
        count_max=3,
        combat_weight=1.0,
        combat_type_weights={CombatLocationType.NORMAL: 1.0},
    )

    locations = _generate(seed=42, config=config, players=players)
    for loc in locations:
        assert loc.combat_type == CombatLocationType.NORMAL
        assert 1 <= len(loc.enemy_ids) <= 2
        assert all(load_enemy(eid).combat_type == EnemyCombatType.NORMAL for eid in loc.enemy_ids)


def test_elite_rooms_contain_exactly_one_elite(players):
    config = GenerationConfig(
        tags=("fire",),
        count_min=2,
        count_max=2,
        combat_weight=1.0,
        combat_type_weights={CombatLocationType.ELITE: 1.0},
    )

    locations = _generate(seed=7, config=config, players=players)
    for loc in locations:
        assert loc.combat_type == CombatLocationType.ELITE
        assert len(loc.enemy_ids) == 1
        assert load_enemy(loc.enemy_ids[0]).combat_type == EnemyCombatType.ELITE


def test_swarm_rooms_use_three_to_five_enemies_with_at_most_one_elite(players):
    config = GenerationConfig(
        tags=("cave",),
        count_min=2,
        count_max=2,
        combat_weight=1.0,
        combat_type_weights={CombatLocationType.SWARM: 1.0},
    )

    locations = _generate(seed=3, config=config, players=players)
    for loc in locations:
        elites = [eid for eid in loc.enemy_ids if load_enemy(eid).combat_type == EnemyCombatType.ELITE]
        bosses = [eid for eid in loc.enemy_ids if load_enemy(eid).combat_type == EnemyCombatType.BOSS]
        assert loc.combat_type == CombatLocationType.SWARM
        assert 3 <= len(loc.enemy_ids) <= 5
        assert len(elites) <= 1
        assert not bosses


def test_solo_boss_rooms_contain_exactly_one_boss(players):
    config = GenerationConfig(
        tags=("forest", "cave"),
        count_min=2,
        count_max=2,
        combat_weight=1.0,
        combat_type_weights={CombatLocationType.SOLO_BOSS: 1.0},
    )

    locations = _generate(seed=11, config=config, players=players)
    for loc in locations:
        assert loc.combat_type == CombatLocationType.SOLO_BOSS
        assert loc.enemy_ids == ("goblin_boss",)


def test_boss_group_rooms_use_one_boss_and_normal_adds(players):
    config = GenerationConfig(
        tags=("forest", "cave"),
        count_min=2,
        count_max=2,
        combat_weight=1.0,
        combat_type_weights={CombatLocationType.BOSS_GROUP: 1.0},
    )

    locations = _generate(seed=19, config=config, players=players)
    for loc in locations:
        boss_ids = [eid for eid in loc.enemy_ids if load_enemy(eid).combat_type == EnemyCombatType.BOSS]
        normal_ids = [eid for eid in loc.enemy_ids if load_enemy(eid).combat_type == EnemyCombatType.NORMAL]
        elite_ids = [eid for eid in loc.enemy_ids if load_enemy(eid).combat_type == EnemyCombatType.ELITE]
        assert loc.combat_type == CombatLocationType.BOSS_GROUP
        assert len(boss_ids) == 1
        assert 1 <= len(normal_ids) <= 2
        assert not elite_ids


def test_only_valid_room_type_is_rolled_even_if_other_weights_exist(players):
    config = GenerationConfig(
        tags=("fire",),
        count_min=3,
        count_max=3,
        combat_weight=1.0,
        combat_type_weights={
            CombatLocationType.NORMAL: 10.0,
            CombatLocationType.ELITE: 1.0,
            CombatLocationType.SWARM: 10.0,
            CombatLocationType.SOLO_BOSS: 10.0,
            CombatLocationType.BOSS_GROUP: 10.0,
        },
    )

    locations = _generate(seed=5, config=config, players=players)
    assert all(loc.combat_type == CombatLocationType.ELITE for loc in locations)
