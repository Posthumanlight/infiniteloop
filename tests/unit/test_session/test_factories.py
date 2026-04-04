import pytest

from game.core.data_loader import clear_cache
from game.core.enums import EntityType
from game.session.factories import build_enemy, build_enemies, build_player


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_build_enemy_from_toml():
    enemy = build_enemy("goblin")
    assert enemy.entity_type == EntityType.ENEMY
    assert enemy.entity_name == "Goblin"
    assert enemy.current_hp == enemy.major_stats.hp
    assert enemy.current_energy == enemy.major_stats.energy
    assert "slash" in enemy.skills


def test_build_enemy_unique_ids():
    e1 = build_enemy("goblin")
    e2 = build_enemy("goblin")
    assert e1.entity_id != e2.entity_id


def test_build_enemy_unknown_raises():
    with pytest.raises(KeyError):
        build_enemy("nonexistent_monster")


def test_build_enemies_list():
    enemies = build_enemies(("goblin", "skeleton"))
    assert len(enemies) == 2
    assert enemies[0].entity_name == "Goblin"
    assert enemies[1].entity_name == "Skeleton"


def test_build_player_from_toml():
    player = build_player("warrior", "p1")
    assert player.entity_type == EntityType.PLAYER
    assert player.entity_name == "Warrior"
    assert player.entity_id == "p1"
    assert player.player_class == "warrior"
    assert player.current_hp == player.major_stats.hp
    assert "slash" in player.skills
