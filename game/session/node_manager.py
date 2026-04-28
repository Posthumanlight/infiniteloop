from dataclasses import replace

from game.character.enemy import Enemy
from game.character.player_character import PlayerCharacter
from game.character.progression import apply_xp
from game.character.stats import MajorStats
from game.combat.effects import StatusEffectInstance
from game.combat.skill_modifiers import add_modifier
from game.combat.engine import (
    get_available_actions,
    start_combat,
    skip_turn,
    submit_action,
)
from game.combat.models import ActionRequest, CombatState
from game.core.data_loader import (
    CombatLocation,
    ProgressionConfig,
    is_passive_offerable,
    is_skill_offerable,
    load_combat_location,
    load_effect,
    load_enemy_loot,
    load_event,
    load_loot_constants,
    load_modifiers,
    load_passives,
    load_skills,
)
from game.core.formula_eval import evaluate_expr
from game.core.dice import SeededRNG
from game.core.enums import (
    CombatPhase,
    EntityType,
    EventPhase,
    LevelRewardType,
    OutcomeAction,
    SessionPhase,
)
from game.core.game_models import (
    LootAwardInfo,
    LootResolutionSnapshot,
    LootRollInfo,
    LootRoundInfo,
    build_reward_key,
    parse_reward_key,
)
from game.events.engine import (
    resolve_event as _resolve_event,
    start_event,
    submit_vote,
)
from game.events.models import OutcomeResult
from game.items.equipment_effects import get_effective_player_major_stat
from game.items.item_generator import generate_item_from_blueprint_id
from game.session.factories import build_enemies
from game.session.experience_rewards import build_combat_xp_award
from game.session.models import (
    CompletedCombat,
    PendingReward,
    PendingRewardQueue,
    RewardNotice,
    SessionState,
)
from game.world.combat_locations import combat_location_from_def, fallback_combat_location
from game.world.difficulty import RoomDifficultyModifier


def resolve_loot_item_quality(
    room_difficulty: RoomDifficultyModifier | None,
) -> int:
    constants = load_loot_constants()
    formula = constants["item_quality_formula"]
    scalar = room_difficulty.scalar if room_difficulty is not None else 1.0
    raw = evaluate_expr(formula, {
        "room_difficulty_scalar": scalar,
    })
    return max(1, round(float(raw)))


def roll_public_item_contest(
    players: list[PlayerCharacter],
    rng: SeededRNG,
) -> tuple[str, tuple[LootRoundInfo, ...]]:
    if not players:
        raise ValueError("Cannot roll loot contest without players")

    contenders = list(players)
    rounds: list[LootRoundInfo] = []
    round_index = 1

    while True:
        rolls = tuple(
            LootRollInfo(player_id=player.entity_id, roll=rng.d(100))
            for player in contenders
        )
        rounds.append(LootRoundInfo(round_index=round_index, rolls=rolls))

        highest_roll = max(entry.roll for entry in rolls)
        winner_ids = [
            entry.player_id
            for entry in rolls
            if entry.roll == highest_roll
        ]
        if len(winner_ids) == 1:
            return winner_ids[0], tuple(rounds)

        contenders = [
            player
            for player in players
            if player.entity_id in winner_ids
        ]
        round_index += 1


def resolve_and_award_combat_loot(
    players: list[PlayerCharacter],
    defeated_enemies: list[Enemy],
    room_difficulty: RoomDifficultyModifier | None,
    rng: SeededRNG,
) -> tuple[list[PlayerCharacter], LootResolutionSnapshot]:
    updated_players = list(players)
    player_indices = {
        player.entity_id: index
        for index, player in enumerate(updated_players)
    }
    awards: list[LootAwardInfo] = []

    for enemy in defeated_enemies:
        template_id = (
            enemy.enemy_template_id
            or enemy.entity_id.rsplit("_", 1)[0]
        )
        for drop in load_enemy_loot(template_id):
            if rng.random_float() >= drop.drop_rate:
                continue

            quantity = drop.min_quantity
            if drop.max_quantity > drop.min_quantity:
                quantity += rng.d(drop.max_quantity - drop.min_quantity + 1) - 1

            for copy_number in range(1, quantity + 1):
                quality = resolve_loot_item_quality(room_difficulty)
                winner_id, rounds = roll_public_item_contest(updated_players, rng)
                item = generate_item_from_blueprint_id(drop.item_id, quality=quality)

                winner_index = player_indices[winner_id]
                winner = updated_players[winner_index]
                updated_players[winner_index] = replace(
                    winner,
                    inventory=winner.inventory.add_item(item),
                )

                awards.append(LootAwardInfo(
                    source_enemy_id=template_id,
                    item_blueprint_id=drop.item_id,
                    item_name=item.name,
                    quality=quality,
                    winner_id=winner_id,
                    winner_item_instance_id=item.instance_id,
                    copy_number=copy_number,
                    rounds=rounds,
                ))

    return updated_players, LootResolutionSnapshot(awards=tuple(awards))


class NodeManager:
    """Controls what happens inside a room node (combat or event).

    Sole responsibility: entering, progressing, and finalizing encounters.
    Applies combat results and event outcomes back to player state.
    """

    def __init__(
        self,
        rng: SeededRNG,
        progression: ProgressionConfig,
        base_stats: dict[str, MajorStats],
        restoration_formula: str,
    ):
        self._rng = rng
        self._progression = progression
        self._base_stats = base_stats  # keyed by class_id
        self._restoration_formula = restoration_formula

    def _next_seed(self) -> int:
        return self._rng.d(2**31 - 1)

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def enter_combat(
        self,
        state: SessionState,
        enemy_ids: tuple[str, ...],
        location: CombatLocation | None = None,
        room_difficulty: RoomDifficultyModifier | None = None,
    ) -> SessionState:
        """Build enemies from TOML and start a combat encounter."""
        enemies = build_enemies(enemy_ids, room_difficulty=room_difficulty)
        combat_state = start_combat(
            session_id=state.session_id,
            players=list(state.players),
            enemies=enemies,
            seed=self._next_seed(),
            location=location or fallback_combat_location("Combat"),
            room_difficulty=room_difficulty,
        )
        return replace(
            state,
            phase=SessionPhase.IN_COMBAT,
            combat=combat_state,
            last_combat=None,
        )

    def submit_combat_action(
        self,
        state: SessionState,
        action: ActionRequest,
    ) -> SessionState:
        """Submit a player or enemy action. Auto-finalizes if combat ends."""
        combat_state, _result = submit_action(state.combat, action)
        state = replace(state, combat=combat_state)

        if combat_state.phase == CombatPhase.ENDED:
            return self.finalize_combat(state)
        return state

    def skip_combat_turn(
        self,
        state: SessionState,
        actor_id: str,
    ) -> SessionState:
        """Skip actor's turn (timeout / stun). Auto-finalizes if combat ends."""
        combat_state, _result = skip_turn(state.combat, actor_id)
        state = replace(state, combat=combat_state)

        if combat_state.phase == CombatPhase.ENDED:
            return self.finalize_combat(state)
        return state

    @staticmethod
    def get_combat_actions(
        state: SessionState, actor_id: str,
    ) -> list[tuple]:
        return get_available_actions(state.combat, actor_id)

    def finalize_combat(self, state: SessionState) -> SessionState:
        """Apply combat results to players, clear combat sub-state."""
        combat_state = state.combat
        assert combat_state is not None
        completed = CompletedCombat(
            combat_id=combat_state.combat_id,
            final_round_number=combat_state.round_number,
            action_log=combat_state.action_log,
            entities=dict(combat_state.entities),
            location=combat_state.location,
        )

        state = self._apply_combat_results(state)
        loot_snapshot: LootResolutionSnapshot | None = None

        if any(player.current_hp > 0 for player in state.players):
            rng = SeededRNG(0)
            if combat_state.rng_state is not None:
                rng.set_state(combat_state.rng_state)

            defeated_enemies = [
                entity
                for entity in combat_state.entities.values()
                if isinstance(entity, Enemy)
                and entity.entity_type == EntityType.ENEMY
                and entity.current_hp <= 0
            ]
            players, loot_snapshot = resolve_and_award_combat_loot(
                players=list(state.players),
                defeated_enemies=defeated_enemies,
                room_difficulty=combat_state.room_difficulty,
                rng=rng,
            )
            state = replace(
                state,
                players=tuple(players),
                pending_loot=loot_snapshot,
            )
        else:
            state = replace(state, pending_loot=None)

        state = self._restore_between_nodes(state, self._restoration_formula)
        return replace(
            state,
            combat=None,
            last_combat=completed,
            run_stats=replace(
                state.run_stats,
                combats_completed=state.run_stats.combats_completed + 1,
            ),
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def enter_event(
        self,
        state: SessionState,
        event_id: str,
        room_difficulty: RoomDifficultyModifier | None = None,
    ) -> SessionState:
        """Load event from TOML and start an event encounter."""
        event_def = load_event(event_id)
        player_ids = [p.entity_id for p in state.players]
        event_state = start_event(
            session_id=state.session_id,
            event_def=event_def,
            player_ids=player_ids,
            seed=self._next_seed(),
            room_difficulty=room_difficulty,
        )
        return replace(
            state,
            phase=SessionPhase.IN_EVENT,
            event=event_state,
        )

    @staticmethod
    def submit_event_vote(
        state: SessionState,
        player_id: str,
        choice_index: int,
    ) -> SessionState:
        event_state = submit_vote(state.event, player_id, choice_index)
        return replace(state, event=event_state)

    def resolve_event(
        self,
        state: SessionState,
    ) -> tuple[
        SessionState,
        tuple[str, ...],
        RoomDifficultyModifier | None,
        CombatLocation | None,
    ]:
        """Resolve event votes, apply outcomes, and preserve combat difficulty."""
        event = state.event
        if event is None:
            raise ValueError("No active event to resolve.")

        room_difficulty = event.room_difficulty
        event_state, resolution = _resolve_event(
            event, list(state.players),
        )
        state = replace(
            state,
            event=event_state,
        )

        # Apply only the newly resolved stage's outcomes.
        state = self._apply_event_outcomes(state, resolution.outcomes)

        if event_state.phase == EventPhase.PRESENTING:
            return state, (), room_difficulty, None

        state = replace(
            state,
            run_stats=replace(
                state.run_stats,
                events_completed=state.run_stats.events_completed + 1,
            ),
        )

        # Collect START_COMBAT enemy groups
        combat_enemy_ids: list[str] = []
        combat_location_id: str | None = None
        for outcome in resolution.outcomes:
            if outcome.action == OutcomeAction.START_COMBAT:
                combat_enemy_ids.extend(outcome.enemy_group)
                combat_location_id = combat_location_id or outcome.combat_location_id

        # Clear event sub-state
        state = replace(state, event=None)

        # Restore HP between nodes (skip if chaining into combat)
        if not combat_enemy_ids:
            state = self._restore_between_nodes(state, self._restoration_formula)

        combat_location = None
        if combat_enemy_ids:
            if combat_location_id is not None:
                combat_location = combat_location_from_def(
                    load_combat_location(combat_location_id),
                    self._rng,
                )
            else:
                combat_location = fallback_combat_location(
                    f"{event.event_def.name} Combat",
                    location_id=f"event:{event.event_def.event_id}",
                )

        return state, tuple(combat_enemy_ids), room_difficulty, combat_location

    # ------------------------------------------------------------------
    # Level-up rewards (modifier or ability)
    # ------------------------------------------------------------------

    @staticmethod
    def has_pending_reward(state: SessionState, player_id: str) -> bool:
        queue = state.pending_rewards.get(player_id)
        return queue is not None and queue.pending_count > 0

    @staticmethod
    def clear_reward_notices(state: SessionState) -> SessionState:
        return replace(state, reward_notices=())

    def prepare_reward_choices(self, state: SessionState) -> SessionState:
        """Roll offers for the front entry of each player's reward queue."""
        queues = dict(state.pending_rewards)
        notices = list(state.reward_notices)
        players = {p.entity_id: p for p in state.players}

        for player_id, queue in list(queues.items()):
            player = players.get(player_id)
            if player is None:
                queues.pop(player_id, None)
                continue

            rolled_entries, skipped_by_type = self._roll_front_entry(player, queue)
            for reward_type, skipped in skipped_by_type.items():
                if skipped > 0:
                    notices.append(
                        RewardNotice(
                            player_id=player_id,
                            reward_type=reward_type,
                            skipped_count=skipped,
                        ),
                    )

            if not rolled_entries:
                queues.pop(player_id, None)
            else:
                queues[player_id] = PendingRewardQueue(entries=tuple(rolled_entries))

        return replace(
            state,
            pending_rewards=queues,
            reward_notices=tuple(notices),
        )

    def apply_reward_choice(
        self,
        state: SessionState,
        player_id: str,
        reward_id: str,
    ) -> SessionState:
        queue = state.pending_rewards.get(player_id)
        if queue is None or queue.pending_count <= 0:
            raise ValueError("No pending reward for this player.")
        front = queue.entries[0]
        if not front.offer:
            raise ValueError("No reward offer available for this player.")
        if reward_id not in front.offer:
            raise ValueError("Reward is not part of the current offer.")

        updated_players: list[PlayerCharacter] = []
        found = False
        for player in state.players:
            if player.entity_id == player_id:
                updated_players.append(
                    self._apply_reward_to_player(player, front.reward_type, reward_id),
                )
                found = True
            else:
                updated_players.append(player)

        if not found:
            raise ValueError("Player is not part of this run.")

        queues = dict(state.pending_rewards)
        remaining = queue.entries[1:]
        if remaining:
            queues[player_id] = PendingRewardQueue(entries=remaining)
        else:
            queues.pop(player_id, None)

        state = replace(
            state,
            players=tuple(updated_players),
            pending_rewards=queues,
        )
        return self.prepare_reward_choices(state)

    @staticmethod
    def _apply_reward_to_player(
        player: PlayerCharacter,
        reward_type: LevelRewardType,
        reward_key: str,
    ) -> PlayerCharacter:
        reward_kind, reward_id = parse_reward_key(reward_key)

        if reward_type == LevelRewardType.MODIFIER:
            if reward_kind != "modifier":
                raise ValueError("Modifier reward expected a modifier key.")
            return add_modifier(player, reward_id)
        if reward_type == LevelRewardType.ABILITY:
            if reward_kind == "skill":
                if reward_id in player.skills:
                    raise ValueError("Skill already known.")
                return replace(player, skills=player.skills + (reward_id,))
            if reward_kind == "passive":
                if reward_id in player.passive_skills:
                    raise ValueError("Passive already known.")
                return replace(
                    player,
                    passive_skills=player.passive_skills + (reward_id,),
                )
            raise ValueError("Ability reward expected a skill or passive key.")
        raise ValueError(f"Unknown reward type: {reward_type}")

    def _enqueue_level_rewards(
        self,
        state: SessionState,
        crossed_levels: dict[str, list[int]],
    ) -> SessionState:
        queues = dict(state.pending_rewards)
        skill_reward_levels = set(self._progression.skill_reward_levels)
        for player_id, levels in crossed_levels.items():
            if not levels:
                continue
            current = queues.get(player_id, PendingRewardQueue()).entries
            new_entries = list(current)
            for level in levels:
                reward_type = (
                    LevelRewardType.ABILITY
                    if level in skill_reward_levels
                    else LevelRewardType.MODIFIER
                )
                new_entries.append(PendingReward(reward_type=reward_type))
            queues[player_id] = PendingRewardQueue(entries=tuple(new_entries))
        return replace(state, pending_rewards=queues)

    def _eligible_modifier_ids(self, player: PlayerCharacter) -> list[str]:
        all_mods = load_modifiers()
        owned = {inst.modifier_id for inst in player.skill_modifiers}
        eligible: list[str] = []

        for modifier_id, modifier in all_mods.items():
            has_skill_filter = bool(modifier.skill_filter)
            has_class_tags = bool(modifier.class_tags)
            if has_skill_filter or has_class_tags:
                skill_match = (
                    modifier.skill_filter is not None
                    and modifier.skill_filter in player.skills
                )
                class_match = player.player_class in modifier.class_tags
                if not (skill_match or class_match):
                    continue

            if modifier_id in owned and not modifier.stackable:
                continue

            eligible.append(modifier_id)

        return eligible

    @staticmethod
    def _eligible_skill_ids(player: PlayerCharacter) -> list[str]:
        all_skills = load_skills()
        owned = set(player.skills)
        eligible: list[str] = []
        for skill_id, skill in all_skills.items():
            if skill_id in owned:
                continue
            if is_skill_offerable(skill, player.level, player.player_class):
                eligible.append(skill_id)
        return eligible

    @staticmethod
    def _eligible_passive_ids(player: PlayerCharacter) -> list[str]:
        all_passives = load_passives()
        owned = set(player.passive_skills)
        eligible: list[str] = []
        for passive_id, passive in all_passives.items():
            if passive_id in owned:
                continue
            if is_passive_offerable(passive, player.level, player.player_class):
                eligible.append(passive_id)
        return eligible

    def _eligible_ability_keys(self, player: PlayerCharacter) -> list[str]:
        skills = [
            build_reward_key("skill", skill_id)
            for skill_id in self._eligible_skill_ids(player)
        ]
        passives = [
            build_reward_key("passive", passive_id)
            for passive_id in self._eligible_passive_ids(player)
        ]
        return skills + passives

    def _sample_ids(self, pool: list[str], count: int) -> tuple[str, ...]:
        remaining = list(pool)
        selected: list[str] = []
        for _ in range(min(count, len(remaining))):
            idx = self._rng.d(len(remaining)) - 1
            selected.append(remaining.pop(idx))
        return tuple(selected)

    def _roll_front_entry(
        self,
        player: PlayerCharacter,
        queue: PendingRewardQueue,
    ) -> tuple[list[PendingReward], dict[LevelRewardType, int]]:
        """Roll offers for entries starting from the front, skipping empty pools.

        Returns the remaining entries (front entry has a rolled offer, or the
        queue is empty) and a per-type count of skipped rolls for notices.
        """
        entries = list(queue.entries)
        skipped: dict[LevelRewardType, int] = {
            LevelRewardType.MODIFIER: 0,
            LevelRewardType.ABILITY: 0,
        }

        while entries:
            front = entries[0]
            if front.offer:
                return entries, skipped

            if front.reward_type == LevelRewardType.MODIFIER:
                pool = [
                    build_reward_key("modifier", modifier_id)
                    for modifier_id in self._eligible_modifier_ids(player)
                ]
                offer_size = 2
            else:
                pool = self._eligible_ability_keys(player)
                offer_size = self._progression.skill_reward_offer_size

            if not pool:
                skipped[front.reward_type] += 1
                entries.pop(0)
                continue

            offer = self._sample_ids(pool, offer_size)
            entries[0] = PendingReward(reward_type=front.reward_type, offer=offer)
            return entries, skipped

        return entries, skipped

    # ------------------------------------------------------------------
    # Side-effect application
    # ------------------------------------------------------------------

    @staticmethod
    def _restore_between_nodes(
        state: SessionState,
        restoration_formula: str,
    ) -> SessionState:
        """Restore HP to alive players between nodes using a data-driven formula."""
        updated: list[PlayerCharacter] = []
        total_healing = 0
        for player in state.players:
            if player.current_hp <= 0:
                updated.append(player)
                continue
            max_hp = int(get_effective_player_major_stat(player, "hp"))
            ctx: dict[str, object] = {
                "max_hp": max_hp,
                "current_hp": player.current_hp,
                "level": player.level,
                "attack": player.major_stats.attack,
                "speed": player.major_stats.speed,
                "crit_chance": player.major_stats.crit_chance,
                "crit_dmg": player.major_stats.crit_dmg,
                "resistance": player.major_stats.resistance,
                "energy": player.major_stats.energy,
                "mastery": player.major_stats.mastery,
            }
            heal = max(0, int(evaluate_expr(restoration_formula, ctx)))
            new_hp = min(player.current_hp + heal, max_hp)
            total_healing += new_hp - player.current_hp
            updated.append(replace(player, current_hp=new_hp))
        new_stats = replace(
            state.run_stats,
            total_healing=state.run_stats.total_healing + total_healing,
        )
        return replace(state, players=tuple(updated), run_stats=new_stats)

    def _apply_player_xp(
        self,
        player: PlayerCharacter,
        xp_gained: int,
        crossed_levels: dict[str, list[int]],
    ) -> PlayerCharacter:
        if xp_gained <= 0:
            return player

        base = self._base_stats.get(player.player_class)
        if base is None:
            return replace(player, xp=player.xp + xp_gained)

        updated, crossed = apply_xp(
            player,
            xp_gained,
            self._progression,
            base,
        )
        if crossed:
            crossed_levels[updated.entity_id] = (
                crossed_levels.get(updated.entity_id, []) + crossed
            )
        return updated

    def _apply_combat_results(self, state: SessionState) -> SessionState:
        """Merge HP/energy/effects from combat entities back to session players."""
        combat_state = state.combat
        updated_players: list[PlayerCharacter] = []
        crossed_levels: dict[str, list[int]] = {}
        defeated_enemies: list[Enemy] = []
        total_damage_dealt = 0
        total_damage_taken = 0

        for entity in combat_state.entities.values():
            if (
                isinstance(entity, Enemy)
                and entity.entity_type == EntityType.ENEMY
                and entity.current_hp <= 0
            ):
                defeated_enemies.append(entity)

        xp_award = build_combat_xp_award(
            defeated_enemies,
            state.players,
            combat_state.room_difficulty,
        )

        for action_result in combat_state.action_log:
            actor = combat_state.entities.get(action_result.actor_id)
            if actor is None:
                continue
            for hit in action_result.hits:
                if hit.damage is not None:
                    if actor.entity_type == EntityType.PLAYER:
                        total_damage_dealt += hit.damage.amount
                    elif actor.entity_type == EntityType.ENEMY:
                        total_damage_taken += hit.damage.amount

        for player in state.players:
            combat_entity = combat_state.entities.get(player.entity_id)
            if combat_entity is not None:
                updated = replace(
                    player,
                    current_hp=max(0, combat_entity.current_hp),
                    current_energy=max(0, combat_entity.current_energy),
                    active_effects=combat_entity.active_effects,
                )
            else:
                updated = player

            updated = self._apply_player_xp(
                updated,
                xp_award.per_player.get(updated.entity_id, 0),
                crossed_levels,
            )

            updated_players.append(updated)

        new_stats = replace(
            state.run_stats,
            enemies_defeated=state.run_stats.enemies_defeated + len(defeated_enemies),
            total_damage_dealt=state.run_stats.total_damage_dealt + total_damage_dealt,
            total_damage_taken=state.run_stats.total_damage_taken + total_damage_taken,
            total_xp_gained=(
                state.run_stats.total_xp_gained + xp_award.total_awarded_xp
            ),
        )
        state = replace(state, players=tuple(updated_players), run_stats=new_stats)
        return self._enqueue_level_rewards(state, crossed_levels)

    def _apply_event_outcomes(
        self,
        state: SessionState,
        outcomes: tuple[OutcomeResult, ...],
    ) -> SessionState:
        """Apply event outcome descriptors to player state."""
        player_map: dict[str, PlayerCharacter] = {
            p.entity_id: p for p in state.players
        }
        crossed_levels: dict[str, list[int]] = {}
        total_healing = 0
        total_damage = 0
        total_xp = 0

        for outcome in outcomes:
            player = player_map.get(outcome.player_id)
            if player is None:
                continue

            match outcome.action:
                case OutcomeAction.HEAL:
                    max_hp = int(get_effective_player_major_stat(player, "hp"))
                    new_hp = min(
                        player.current_hp + outcome.amount,
                        max_hp,
                    )
                    total_healing += new_hp - player.current_hp
                    player = replace(player, current_hp=new_hp)

                case OutcomeAction.DAMAGE:
                    new_hp = max(0, player.current_hp - outcome.amount)
                    total_damage += outcome.amount
                    player = replace(player, current_hp=new_hp)

                case OutcomeAction.RESTORE_ENERGY:
                    max_energy = int(get_effective_player_major_stat(player, "energy"))
                    new_energy = min(
                        player.current_energy + outcome.amount,
                        max_energy,
                    )
                    player = replace(player, current_energy=new_energy)

                case OutcomeAction.DRAIN_ENERGY:
                    new_energy = max(0, player.current_energy - outcome.amount)
                    player = replace(player, current_energy=new_energy)

                case OutcomeAction.GIVE_XP:
                    total_xp += outcome.amount
                    player = self._apply_player_xp(
                        player,
                        outcome.amount,
                        crossed_levels,
                    )

                case OutcomeAction.APPLY_EFFECT:
                    if outcome.effect_id is not None:
                        effect_def = load_effect(outcome.effect_id)
                        instance = StatusEffectInstance(
                            effect_id=outcome.effect_id,
                            source_id="event",
                            remaining_duration=effect_def.duration,
                        )
                        player = replace(
                            player,
                            active_effects=player.active_effects + (instance,),
                        )

                case OutcomeAction.START_COMBAT:
                    pass  # Handled by resolve_event caller

                case OutcomeAction.GIVE_ITEM:
                    if outcome.item_id is not None:
                        item = generate_item_from_blueprint_id(
                            outcome.item_id,
                            quality=1,
                        )
                        player = replace(
                            player,
                            inventory=player.inventory.add_item(item),
                        )

                case (OutcomeAction.GIVE_GOLD
                      | OutcomeAction.TAKE_GOLD):
                    pass  # TODO: stubbed until inventory/gold systems exist

            player_map[outcome.player_id] = player

        updated_players = tuple(
            player_map[p.entity_id] for p in state.players
        )
        new_stats = replace(
            state.run_stats,
            total_healing=state.run_stats.total_healing + total_healing,
            total_damage_taken=state.run_stats.total_damage_taken + total_damage,
            total_xp_gained=state.run_stats.total_xp_gained + total_xp,
        )
        state = replace(state, players=updated_players, run_stats=new_stats)
        return self._enqueue_level_rewards(state, crossed_levels)
