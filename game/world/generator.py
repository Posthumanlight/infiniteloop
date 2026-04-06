import uuid

from game.core.data_loader import (
    LocationOption,
    load_enemies,
    load_events,
    load_location_set,
    load_location_statuses,
)
from game.core.dice import SeededRNG
from game.core.enums import LocationType
from game.events.engine import select_event
from game.character.player_character import PlayerCharacter
from game.world.models import GenerationConfig

class WorldGenerator:
    def __init__(self, seed: int = 0):
        self.rng = SeededRNG(seed)
        pass

    #Load a hand-crafted location set from TOML.
    def load_predetermined(self, set_id: str) -> tuple[LocationOption, ...]:
        location_set = load_location_set(set_id)
        return location_set.locations
    
    #Return enemy IDs that match at least one of the given tags.
    def _get_eligible_enemies(self, tags: tuple[str, ...]) -> list[str]:
        all_enemies = load_enemies()
        if not tags:
            return list(all_enemies.keys())
        return [
            eid for eid, edata in all_enemies.items()
            if set(edata.tags) & set(tags)
        ]

    #Return status IDs that match at least one of the given tags.
    def _get_eligible_statuses(self, tags: tuple[str, ...]) -> list[str]:
        all_statuses = load_location_statuses()
        if not tags:
            return list(all_statuses.keys())
        return [
            sid for sid, sdata in all_statuses.items()
            if set(sdata.tags) & set(tags)
        ]

    #Generate a random combat location.
    def _generate_combat_location(self, counter: int, tags: tuple[str, ...],) -> LocationOption:
        enemy_pool = self._get_eligible_enemies(tags)
        status_pool = self._get_eligible_statuses(tags)

        # Pick 1-n enemies from the pool
        enemy_count = self.rng.d(3)
        enemy_ids: list[str] = []
        if enemy_pool:
            for _ in range(enemy_count):
                idx = self.rng.d(len(enemy_pool)) - 1
                enemy_ids.append(enemy_pool[idx])

        #Random status application
        status_ids: list[str] = []
        if status_pool and self.rng.random_float() < 0.5:
            idx = self.rng.d(len(status_pool)) - 1
            status_ids.append(status_pool[idx])

        return LocationOption(
            location_id=uuid.uuid4().hex,
            name=f"Combat {counter}",
            location_type=LocationType.COMBAT,
            tags=tags,
            enemy_ids=tuple(enemy_ids),
            status_ids=tuple(status_ids),
        )


    def _generate_event_location(self,counter: int, players: list[PlayerCharacter], tags: tuple[str, ...], 
                                 depth: int) -> LocationOption | None:
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

       #"Randomly generate location options.
    def generate_random(self, power: int, players: list[PlayerCharacter],
        config: GenerationConfig, depth: int,) -> tuple[LocationOption, ...]:

        count = self.rng.d(config.count_max - config.count_min + 1) + config.count_min - 1

        locations: list[LocationOption] = []
        combat_counter = 0
        event_counter = 0

        for _ in range(count):
            is_combat = self.rng.random_float() < config.combat_weight

            if is_combat:
                combat_counter += 1
                loc = self._generate_combat_location(combat_counter, config.tags)
            else:
                event_counter += 1
                loc = self._generate_event_location(
                    event_counter, players, config.tags, depth,
                )

            if loc is None:
                # Event generation failed (no eligible events) — fall back to combat
                combat_counter += 1
                loc = self._generate_combat_location(combat_counter, config.tags)
            locations.append(loc)

        return tuple(locations)
    
    def generate_locations(self, power: int, players: list[PlayerCharacter],
        config: GenerationConfig, depth: int = 0) -> tuple[LocationOption, ...]:

        if config.predetermined_set_id is not None:
            return self.load_predetermined(config.predetermined_set_id)

        return self.generate_random(power, players, config, depth)