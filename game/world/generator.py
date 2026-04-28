import uuid
from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.core.data_loader import (
    CombatLocationDef,
    EnemyData,
    LocationOption,
    load_combat_locations,
    load_enemies,
    load_events,
    load_location_set,
)
from game.core.dice import SeededRNG
from game.core.enums import CombatLocationType, EnemyCombatType, LocationType
from game.core.selection import matches_tag_filter, weighted_choice
from game.events.engine import select_event
from game.world.combat_locations import roll_combat_location_statuses
from game.world.difficulty import RoomDifficultyModifier, build_room_difficulty
from game.world.models import GenerationConfig

_ALLOWED_ROOM_TYPES: dict[EnemyCombatType, tuple[CombatLocationType, ...]] = {
    EnemyCombatType.NORMAL: (
        CombatLocationType.NORMAL,
        CombatLocationType.SWARM,
        CombatLocationType.BOSS_GROUP,
    ),
    EnemyCombatType.ELITE: (
        CombatLocationType.ELITE,
        CombatLocationType.SWARM,
    ),
    EnemyCombatType.BOSS: (
        CombatLocationType.SOLO_BOSS,
        CombatLocationType.BOSS_GROUP,
    ),
}


class WorldGenerator:
    def __init__(self, seed: int = 0):
        self.rng = SeededRNG(seed)

    def load_predetermined(self, set_id: str) -> tuple[LocationOption, ...]:
        location_set = load_location_set(set_id)
        return location_set.locations

    def _attach_room_difficulty(
        self,
        locations: tuple[LocationOption, ...],
        room_difficulty: RoomDifficultyModifier,
    ) -> tuple[LocationOption, ...]:
        return tuple(
            replace(loc, room_difficulty=room_difficulty)
            if loc.location_type == LocationType.COMBAT
            else loc
            for loc in locations
        )

    def _get_tag_filtered_enemies(self, tags: tuple[str, ...]) -> dict[str, EnemyData]:
        all_enemies = load_enemies()
        if not tags:
            return all_enemies
        return {
            eid: edata for eid, edata in all_enemies.items()
            if matches_tag_filter(edata.tags, tags)
        }

    def _get_tag_filtered_combat_locations(
        self,
        tags: tuple[str, ...],
    ) -> tuple[CombatLocationDef, ...]:
        return tuple(
            location
            for location in load_combat_locations().values()
            if matches_tag_filter(location.tags, tags)
        )

    def _enemy_ids_by_type(
        self,
        enemies: dict[str, EnemyData],
        enemy_type: EnemyCombatType,
    ) -> list[str]:
        return [eid for eid, enemy in enemies.items() if enemy.combat_type == enemy_type]

    def _enemy_ids_allowed_for_room_type(
        self,
        enemies: dict[str, EnemyData],
        room_type: CombatLocationType,
    ) -> list[str]:
        return [
            eid for eid, enemy in enemies.items()
            if room_type in _ALLOWED_ROOM_TYPES[enemy.combat_type]
        ]

    def _can_build_room_type(
        self,
        room_type: CombatLocationType,
        enemies: dict[str, EnemyData],
    ) -> bool:
        allowed = self._enemy_ids_allowed_for_room_type(enemies, room_type)
        normals = self._enemy_ids_by_type(enemies, EnemyCombatType.NORMAL)
        bosses = self._enemy_ids_by_type(enemies, EnemyCombatType.BOSS)

        match room_type:
            case CombatLocationType.NORMAL:
                return len(allowed) >= 1
            case CombatLocationType.ELITE:
                return len(allowed) >= 1
            case CombatLocationType.SWARM:
                return len(normals) >= 1
            case CombatLocationType.SOLO_BOSS:
                return len(allowed) >= 1
            case CombatLocationType.BOSS_GROUP:
                return len(bosses) >= 1 and len(normals) >= 1

    def _valid_combat_location_types(
        self,
        tags: tuple[str, ...],
    ) -> tuple[CombatLocationType, ...]:
        locations = self._get_tag_filtered_combat_locations(tags)
        return tuple(
            room_type for room_type in CombatLocationType
            if any(
                room_type in location.combat_types
                and self._can_build_room_type(
                    room_type,
                    self._get_tag_filtered_enemies(location.tags),
                )
                for location in locations
            )
        )

    def _roll_combat_location_type(
        self,
        valid_types: tuple[CombatLocationType, ...],
        weights: dict[CombatLocationType, float],
    ) -> CombatLocationType:
        return weighted_choice(
            tuple(
                (room_type, weights.get(room_type, 0.0))
                for room_type in valid_types
            ),
            self.rng,
            label="combat location type",
        )

    def _eligible_combat_locations(
        self,
        room_type: CombatLocationType,
        tags: tuple[str, ...],
    ) -> tuple[CombatLocationDef, ...]:
        return tuple(
            location for location in self._get_tag_filtered_combat_locations(tags)
            if room_type in location.combat_types
            and self._can_build_room_type(
                room_type,
                self._get_tag_filtered_enemies(location.tags),
            )
        )

    def _roll_combat_location(
        self,
        room_type: CombatLocationType,
        tags: tuple[str, ...],
    ) -> CombatLocationDef:
        return weighted_choice(
            tuple(
                (location, location.weight)
                for location in self._eligible_combat_locations(room_type, tags)
            ),
            self.rng,
            label="combat location",
        )

    def _randint_inclusive(self, low: int, high: int) -> int:
        return self.rng.d(high - low + 1) + low - 1

    def _sample_one(self, pool: list[str]) -> str:
        idx = self.rng.d(len(pool)) - 1
        return pool[idx]

    def _sample_with_replacement(self, pool: list[str], count: int) -> tuple[str, ...]:
        return tuple(self._sample_one(pool) for _ in range(count))

    def _build_enemy_group(
        self,
        room_type: CombatLocationType,
        enemies: dict[str, EnemyData],
    ) -> tuple[str, ...]:
        normals = self._enemy_ids_by_type(enemies, EnemyCombatType.NORMAL)
        elites = self._enemy_ids_by_type(enemies, EnemyCombatType.ELITE)
        bosses = self._enemy_ids_by_type(enemies, EnemyCombatType.BOSS)

        match room_type:
            case CombatLocationType.NORMAL:
                count = 1 if len(normals) == 1 else self._randint_inclusive(1, 2)
                return self._sample_with_replacement(normals, count)

            case CombatLocationType.ELITE:
                return (self._sample_one(elites),)

            case CombatLocationType.SWARM:
                count = self._randint_inclusive(3, 5)
                elite_count = 1 if elites and count >= 4 and self.rng.random_float() < 0.35 else 0
                normal_count = count - elite_count
                return (
                    *self._sample_with_replacement(normals, normal_count),
                    *self._sample_with_replacement(elites, elite_count),
                )

            case CombatLocationType.SOLO_BOSS:
                return (self._sample_one(bosses),)

            case CombatLocationType.BOSS_GROUP:
                add_count = self._randint_inclusive(1, 2)
                return (
                    self._sample_one(bosses),
                    *self._sample_with_replacement(normals, add_count),
                )

    def _generate_combat_location(
        self,
        tags: tuple[str, ...],
        combat_type_weights: dict[CombatLocationType, float],
    ) -> LocationOption:
        valid_types = self._valid_combat_location_types(tags)
        combat_type = self._roll_combat_location_type(valid_types, combat_type_weights)
        location = self._roll_combat_location(combat_type, tags)
        enemies = self._get_tag_filtered_enemies(location.tags)
        enemy_ids = self._build_enemy_group(combat_type, enemies)
        status_ids = roll_combat_location_statuses(location, self.rng)

        return LocationOption(
            location_id=uuid.uuid4().hex,
            name=location.name,
            location_type=LocationType.COMBAT,
            tags=location.tags,
            enemy_ids=enemy_ids,
            status_ids=status_ids,
            combat_type=combat_type,
            combat_location_id=location.location_id,
        )

    def _generate_event_location(
        self,
        counter: int,
        players: list[PlayerCharacter],
        tags: tuple[str, ...],
        depth: int,
    ) -> LocationOption | None:
        all_events = list(load_events().values())
        event_def = select_event(all_events, depth, players, self.rng)

        if event_def is None:
            return None

        return LocationOption(
            location_id=uuid.uuid4().hex,
            name=f"Event {counter}",
            location_type=LocationType.EVENT,
            tags=tags,
            event_id=event_def.event_id,
        )

    def generate_random(
        self,
        power: int,
        players: list[PlayerCharacter],
        config: GenerationConfig,
        depth: int,
    ) -> tuple[LocationOption, ...]:
        count = self.rng.d(config.count_max - config.count_min + 1) + config.count_min - 1

        locations: list[LocationOption] = []
        event_counter = 0

        for _ in range(count):
            is_combat = self.rng.random_float() < config.combat_weight

            if is_combat:
                loc = self._generate_combat_location(
                    config.tags,
                    config.combat_type_weights,
                )
            else:
                event_counter += 1
                loc = self._generate_event_location(
                    event_counter, players, config.tags, depth,
                )

            if loc is None:
                loc = self._generate_combat_location(
                    config.tags,
                    config.combat_type_weights,
                )
            locations.append(loc)

        return tuple(locations)

    def generate_locations(
        self,
        power: int,
        players: list[PlayerCharacter],
        config: GenerationConfig,
        depth: int = 0,
    ) -> tuple[LocationOption, ...]:
        room_difficulty = build_room_difficulty(players, power)

        if config.predetermined_set_id is not None:
            base = self.load_predetermined(config.predetermined_set_id)
            return self._attach_room_difficulty(base, room_difficulty)

        base = self.generate_random(power, players, config, depth)
        return self._attach_room_difficulty(base, room_difficulty)
