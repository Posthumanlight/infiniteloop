from dataclasses import replace

from game.world.difficulty import (
    RoomDifficultyModifier,
    apply_room_difficulty,
    build_room_difficulty,
)

from tests.unit.conftest import make_warrior


def test_build_room_difficulty_identity_for_level_one_solo():
    diff = build_room_difficulty([make_warrior("p1")], power=1)

    assert diff == RoomDifficultyModifier.identity()


def test_build_room_difficulty_increases_with_average_level():
    player = replace(make_warrior("p1"), level=5)

    diff = build_room_difficulty([player], power=5)

    assert diff.scalar > 1.0
    assert diff.hp_mult > 1.0
    assert diff.attack_mult > 1.0


def test_build_room_difficulty_increases_with_party_size():
    players = [
        replace(make_warrior("p1"), level=3),
        replace(make_warrior("p2"), level=3),
    ]

    solo = build_room_difficulty([players[0]], power=3)
    party = build_room_difficulty(players, power=6)

    assert party.scalar > solo.scalar
    assert party.party_size == 2


def test_build_room_difficulty_clamps_scalar():
    players = [
        replace(make_warrior("p1"), level=50),
        replace(make_warrior("p2"), level=50),
        replace(make_warrior("p3"), level=50),
        replace(make_warrior("p4"), level=50),
    ]

    diff = build_room_difficulty(players, power=200)

    assert diff.scalar == 2.25


def test_apply_room_difficulty_scales_only_selected_major_stats():
    diff = RoomDifficultyModifier(
        scalar=1.5,
        average_level=5.0,
        party_size=3,
        power=15,
        hp_mult=1.5,
        attack_mult=1.3,
        speed_mult=1.1,
        resistance_mult=1.2,
        mastery_mult=1.2,
    )
    major = make_warrior("p1").major_stats

    scaled = apply_room_difficulty(major, diff)

    assert scaled.hp == round(major.hp * 1.5)
    assert scaled.attack == round(major.attack * 1.3)
    assert scaled.speed == round(major.speed * 1.1)
    assert scaled.resistance == round(major.resistance * 1.2)
    assert scaled.mastery == round(major.mastery * 1.2)
    assert scaled.crit_chance == major.crit_chance
    assert scaled.crit_dmg == major.crit_dmg
    assert scaled.energy == major.energy
