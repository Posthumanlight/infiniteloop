from game.core.dice import SeededRNG
from game.core.selection import (
    has_tag_overlap,
    matches_tag_filter,
    weighted_choice,
    weighted_sample_unique,
)


def test_tag_overlap_helpers():
    assert has_tag_overlap(("cave", "dark"), ("dark", "fire")) is True
    assert has_tag_overlap(("forest",), ("cave",)) is False
    assert matches_tag_filter(("forest",), ()) is True
    assert matches_tag_filter(("forest",), ("cave", "forest")) is True


def test_weighted_choice_is_deterministic():
    rng1 = SeededRNG(42)
    rng2 = SeededRNG(42)
    weighted = (("low", 1.0), ("high", 10.0))

    assert weighted_choice(weighted, rng1) == weighted_choice(weighted, rng2)


def test_weighted_sample_unique_caps_to_available_items():
    rng = SeededRNG(1)
    sample = weighted_sample_unique(
        (("a", 1.0), ("b", 1.0)),
        5,
        rng,
    )

    assert len(sample) == 2
    assert set(sample) == {"a", "b"}
