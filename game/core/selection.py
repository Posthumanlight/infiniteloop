from collections.abc import Iterable, Sequence
from typing import TypeVar

from game.core.dice import SeededRNG

T = TypeVar("T")


def has_tag_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    return bool(set(left) & set(right))


def matches_tag_filter(candidate_tags: Iterable[str], filter_tags: Iterable[str]) -> bool:
    required = tuple(filter_tags)
    return not required or has_tag_overlap(candidate_tags, required)


def weighted_choice(
    weighted_items: Sequence[tuple[T, float]],
    rng: SeededRNG,
    *,
    label: str = "item",
) -> T:
    eligible = tuple((item, float(weight)) for item, weight in weighted_items if weight > 0)
    if not eligible:
        raise ValueError(f"No {label}s with positive weight")

    total = sum(weight for _, weight in eligible)
    roll = rng.uniform(0.0, total)
    running = 0.0
    for item, weight in eligible:
        running += weight
        if roll <= running:
            return item
    return eligible[-1][0]


def weighted_sample_unique(
    weighted_items: Sequence[tuple[T, float]],
    count: int,
    rng: SeededRNG,
    *,
    label: str = "item",
) -> tuple[T, ...]:
    if count <= 0:
        return ()

    remaining = [(item, float(weight)) for item, weight in weighted_items if weight > 0]
    result: list[T] = []
    target_count = min(count, len(remaining))

    for _ in range(target_count):
        picked = weighted_choice(remaining, rng, label=label)
        result.append(picked)
        remaining = [(item, weight) for item, weight in remaining if item != picked]

    return tuple(result)
