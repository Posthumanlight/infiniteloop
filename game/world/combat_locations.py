from game.core.data_loader import (
    CombatLocation,
    CombatLocationDef,
    LocationOption,
    load_location_statuses,
)
from game.core.dice import SeededRNG
from game.core.selection import has_tag_overlap, weighted_choice, weighted_sample_unique


def roll_combat_location_statuses(
    location: CombatLocationDef,
    rng: SeededRNG,
) -> tuple[str, ...]:
    status_count = weighted_choice(
        tuple(location.status_count_weights.items()),
        rng,
        label="status count",
    )
    if status_count <= 0 or not location.status_weights:
        return ()

    status_defs = load_location_statuses()
    weighted_statuses = tuple(
        (status_id, weight)
        for status_id, weight in location.status_weights.items()
        if has_tag_overlap(location.tags, status_defs[status_id].tags)
    )
    return weighted_sample_unique(
        weighted_statuses,
        status_count,
        rng,
        label="location status",
    )


def combat_location_from_def(
    location: CombatLocationDef,
    rng: SeededRNG,
) -> CombatLocation:
    return CombatLocation(
        location_id=location.location_id,
        name=location.name,
        tags=location.tags,
        status_ids=roll_combat_location_statuses(location, rng),
    )


def combat_location_from_option(location: LocationOption) -> CombatLocation:
    return CombatLocation(
        location_id=location.combat_location_id or location.location_id,
        name=location.name,
        tags=location.tags,
        status_ids=location.status_ids,
    )


def fallback_combat_location(
    name: str,
    *,
    location_id: str = "fallback_combat",
) -> CombatLocation:
    return CombatLocation(
        location_id=location_id,
        name=name,
        tags=(),
        status_ids=(),
    )
