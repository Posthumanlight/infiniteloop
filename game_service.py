import re
from dataclasses import dataclass, replace

from game.character.base_entity import BaseEntity
from game.combat.enemy_ai import build_ai_action
from game.combat.effects import (
    build_effective_expr_context,
    build_expr_context,
    get_effective_major_stat,
    get_effective_minor_stat,
    get_effective_skill_access,
)
from game.combat.targeting import is_ai_controlled, is_player_team
from game.combat.models import ActionRequest, ActionResult
from game.core.dice import SeededRNG
from game.core.data_loader import (
    ClassData,
    load_class,
    load_classes,
    load_constants,
    load_effect,
    load_item_dissolve_constants,
    load_item_sets,
    load_modifier,
    load_passive,
    load_skill,
)
from game.core.enums import (
    ActionType,
    DamageType,
    EffectActionType,
    EntityType,
    LevelRewardType,
    ModifierPhase,
    SessionPhase,
    TriggerType,
)
from game.core.formula_eval import ExprContext, evaluate_expr
from game.character.player_character import PlayerCharacter
from game.items.dissolve import (
    dissolve_currency_name,
    dissolve_rarity_values,
    dissolve_value_for_items,
)
from game.items.equipment_effects import (
    collect_equipped_item_set_counts,
    get_effective_passive_ids,
    get_effective_player_major_stat,
    get_effective_player_minor_stat,
    resolve_item_set_bonus_effects,
)
from game.items.item_generator import generate_item_from_blueprint_id
from game.items.items import ItemInstance
from game.session.factories import build_player
from game.session.models import ActiveSession
from lobby_service import ActiveSessionProvider
from game.core.game_models import (
    CharacterSheet,
    CombatSnapshot,
    EquipmentSlotInfo,
    EffectInfo,
    EntitySnapshot,
    InventorySnapshot,
    ItemEffectInfo,
    ItemInfo,
    ItemSetBonusInfo,
    ItemSetInfo,
    LootResolutionSnapshot,
    ModifierInfo,
    PendingRewardInfo,
    PassiveInfo,
    PlayerInfo,
    RewardNoticeInfo,
    RewardOfferInfo,
    SkillEffectDetail,
    SkillHitInfo,
    SkillHitDetail,
    SkillInfo,
    SkillSummaryPart,
    TurnBatch,
    parse_reward_key,
)


@dataclass(frozen=True)
class _DamagePreview:
    amount_non_crit: int
    amount_crit: int
    damage_type: str


_SKILL_TEMPLATE_RE = re.compile(r"\[([A-Za-z0-9_.]+)\]")
_PREVIEW_NOTE = "Preview vs neutral target, no crit chance, no variance, no target defense."
_DAMAGE_TYPE_NUMERIC: dict[DamageType, int] = {
    DamageType.SLASHING: 1,
    DamageType.PIERCING: 2,
    DamageType.ARCANE: 3,
    DamageType.FIRE: 4,
    DamageType.ICE: 5,
}


class GameService:
    """In-memory game orchestrator. One instance per server process.

    Knows nothing about Telegram — takes generic IDs, returns dataclasses.
    """

    def __init__(self, sessions: ActiveSessionProvider) -> None:
        self._sessions = sessions

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def get_session_players(self, session_id: str) -> list[PlayerInfo]:
        return self._sessions.get_session_players(session_id)

    def has_session(self, session_id: str) -> bool:
        return self._sessions.has_active_session(session_id)

    def is_in_combat(self, session_id: str) -> bool:
        try:
            session = self._get_session(session_id)
        except ValueError:
            return False
        return (
            session is not None
            and session.state is not None
            and session.state.combat is not None
        )

    def remove_session(self, session_id: str) -> None:
        close_session = getattr(self._sessions, "close_session", None)
        if close_session is not None:
            close_session(session_id)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def get_inventory(self, session_id: str, entity_id: str) -> InventorySnapshot:
        session = self._get_session(session_id)
        player = self._get_runtime_player(session, entity_id)
        return self.inventory_for_player(
            player,
            in_combat=session.state is not None and session.state.combat is not None,
        )

    def give_generated_item(
        self,
        session_id: str,
        entity_id: str,
        blueprint_id: str,
        *,
        quality: int = 1,
    ) -> str:
        session = self._get_session(session_id)
        player = self._get_runtime_player(session, entity_id)
        item = generate_item_from_blueprint_id(blueprint_id, quality=quality)
        updated = replace(
            player,
            inventory=player.inventory.add_item(item),
        )
        self._replace_runtime_player(session, updated)
        return item.instance_id

    def equip_item(
        self,
        session_id: str,
        entity_id: str,
        instance_id: str,
        relic_slot: int | None = None,
    ) -> None:
        session = self._get_session(session_id)
        self._assert_not_in_combat(session)
        player = self._get_runtime_player(session, entity_id)
        updated = replace(
            player,
            inventory=player.inventory.equip(instance_id, relic_slot=relic_slot),
        )
        updated = self._reconcile_current_resources(updated)
        self._replace_runtime_player(session, updated)

    def unequip_item(
        self,
        session_id: str,
        entity_id: str,
        instance_id: str,
    ) -> None:
        session = self._get_session(session_id)
        self._assert_not_in_combat(session)
        player = self._get_runtime_player(session, entity_id)
        updated = replace(
            player,
            inventory=player.inventory.unequip(instance_id),
        )
        updated = self._reconcile_current_resources(updated)
        self._replace_runtime_player(session, updated)

    def preview_dissolve_inventory_items(
        self,
        session_id: str,
        entity_id: str,
        instance_ids: tuple[str, ...],
    ) -> tuple[tuple[ItemInstance, ...], int]:
        session = self._get_session(session_id)
        self._assert_not_in_combat(session)
        player = self._get_runtime_player(session, entity_id)
        items = player.inventory.get_dissolvable_items(instance_ids)
        total = dissolve_value_for_items(items, load_item_dissolve_constants())
        return items, total

    def dissolve_inventory_items(
        self,
        session_id: str,
        entity_id: str,
        instance_ids: tuple[str, ...],
    ) -> tuple[PlayerCharacter, tuple[ItemInstance, ...], int]:
        session = self._get_session(session_id)
        self._assert_not_in_combat(session)
        player = self._get_runtime_player(session, entity_id)
        inventory, dissolved = player.inventory.dissolve_items(instance_ids)
        total = dissolve_value_for_items(dissolved, load_item_dissolve_constants())
        updated = replace(player, inventory=inventory)
        updated = self._reconcile_current_resources(updated)
        self._replace_runtime_player(session, updated)
        return updated, dissolved, total

    # ------------------------------------------------------------------
    # Class data
    # ------------------------------------------------------------------

    @staticmethod
    def get_available_classes() -> dict[str, ClassData]:
        return load_classes()

    # ------------------------------------------------------------------
    # Exploration run
    # ------------------------------------------------------------------

    def get_exploration_choices(self, session_id: str) -> tuple:
        session = self._get_session(session_id)
        if session.state is None or session.state.exploration is None:
            raise ValueError("Not in exploration")
        return session.state.exploration.current_options

    def submit_location_vote(
        self, session_id: str, player_id: str, location_index: int,
    ) -> None:
        session = self._get_session(session_id)
        session.state = session.manager.submit_location_vote(
            session.state, player_id, location_index,
        )

    def all_players_voted(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        if session.state is None or session.state.exploration is None:
            return False
        exploration = session.state.exploration
        return len(exploration.votes) >= len(exploration.player_ids)

    def resolve_location_choice(self, session_id: str) -> SessionPhase:
        """Resolve votes and enter the chosen location.

        Returns the new SessionPhase (IN_COMBAT, IN_EVENT, or ENDED).
        If combat starts with enemies first, auto-plays their turns.
        """
        session = self._get_session(session_id)
        session.state = session.manager.resolve_location_choice(session.state)

        if (
            session.state.phase == SessionPhase.IN_COMBAT
            and self._current_actor_is_ai_controlled(session)
        ):
            self._auto_play_ai_entities(session)

        return session.state.phase

    def continue_exploration(self, session_id: str) -> None:
        """After combat/event ends, generate new location choices."""
        session = self._get_session(session_id)
        session.state = session.manager.generate_choices(session.state)

    def get_pending_rewards(
        self,
        session_id: str,
    ) -> tuple[PendingRewardInfo, ...]:
        session = self._get_session(session_id)
        if session.state is None:
            raise ValueError("No active run")

        pending = session.manager.get_pending_rewards(session.state)
        result: list[PendingRewardInfo] = []
        for player_id, queue in sorted(pending.items(), key=lambda item: item[0]):
            if not queue.current_offer or queue.current_type is None:
                continue
            reward_type = queue.current_type
            offers = tuple(
                self._build_reward_offer_info(reward_key)
                for reward_key in queue.current_offer
            )
            result.append(PendingRewardInfo(
                player_id=player_id,
                reward_type=reward_type,
                pending_count=queue.pending_count,
                offers=offers,
            ))
        return tuple(result)

    def submit_reward_choice(
        self,
        session_id: str,
        player_id: str,
        reward_id: str,
    ) -> None:
        session = self._get_session(session_id)
        session.state = session.manager.submit_reward_choice(
            session.state, player_id, reward_id,
        )

    def consume_reward_notices(
        self,
        session_id: str,
    ) -> tuple[RewardNoticeInfo, ...]:
        session = self._get_session(session_id)
        if session.state is None:
            return ()
        session.state, notices = session.manager.consume_reward_notices(session.state)
        return tuple(
            RewardNoticeInfo(
                player_id=notice.player_id,
                reward_type=notice.reward_type,
                skipped_count=notice.skipped_count,
            )
            for notice in notices
        )

    def consume_pending_loot(
        self,
        session_id: str,
    ) -> LootResolutionSnapshot | None:
        session = self._get_session(session_id)
        if session.state is None:
            return None
        pending = session.state.pending_loot
        session.state = replace(session.state, pending_loot=None)
        return pending

    def get_session_phase(self, session_id: str) -> SessionPhase | None:
        try:
            session = self._get_session(session_id)
        except ValueError:
            return None
        if session is None or session.state is None:
            return None
        return session.state.phase

    def get_run_stats(self, session_id: str) -> object:
        session = self._get_session(session_id)
        if session.state is None:
            raise ValueError("No active run")
        return session.state.run_stats

    # ------------------------------------------------------------------
    # Event flow
    # ------------------------------------------------------------------

    def get_event_state(self, session_id: str):
        session = self._get_session(session_id)
        if session.state is None or session.state.event is None:
            raise ValueError("Not in event")
        return session.state.event

    def submit_event_vote(
        self, session_id: str, player_id: str, choice_index: int,
    ) -> None:
        session = self._get_session(session_id)
        session.state = session.manager.submit_event_vote(
            session.state, player_id, choice_index,
        )

    def all_event_votes_in(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        if session.state is None or session.state.event is None:
            return False
        event = session.state.event
        return len(event.votes) >= len(event.player_ids)

    def resolve_event(self, session_id: str) -> SessionPhase:
        """Resolve event votes, apply outcomes.

        Returns new SessionPhase. May chain into IN_COMBAT if
        a START_COMBAT outcome was triggered.
        """
        session = self._get_session(session_id)
        session.state = session.manager.resolve_event(session.state)

        if (
            session.state.phase == SessionPhase.IN_COMBAT
            and self._current_actor_is_ai_controlled(session)
        ):
            self._auto_play_ai_entities(session)

        return session.state.phase

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def submit_player_action(
        self,
        session_id: str,
        action: ActionRequest,
    ) -> TurnBatch:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        results: list[ActionResult] = []

        self._submit_and_capture(session, action, results)
        self._auto_play_ai_entities(session, results)

        return self._build_turn_batch(session, tuple(results))

    def skip_player_turn(
        self,
        session_id: str,
        actor_id: str,
    ) -> TurnBatch:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        results: list[ActionResult] = []

        action = ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=None,
        )
        self._submit_and_capture(session, action, results, skip=True)
        self._auto_play_ai_entities(session, results)

        return self._build_turn_batch(session, tuple(results))

    def get_combat_snapshot(self, session_id: str) -> CombatSnapshot:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return self._build_combat_snapshot(session)

    def get_available_skills(
        self, session_id: str, actor_id: str,
    ) -> list[tuple]:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return session.manager.get_combat_actions(session.state, actor_id)

    def get_alive_enemies(self, session_id: str) -> list[EntitySnapshot]:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return [
            self._entity_to_snapshot(e, session.state.combat)
            for e in session.state.combat.entities.values()
            if e.entity_type == EntityType.ENEMY and e.current_hp > 0
        ]

    def get_alive_allies(self, session_id: str) -> list[EntitySnapshot]:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return [
            self._entity_to_snapshot(e, session.state.combat)
            for e in session.state.combat.entities.values()
            if is_player_team(e.entity_type) and e.current_hp > 0
        ]

    def get_whose_turn(self, session_id: str) -> str | None:
        try:
            session = self._get_session(session_id)
        except ValueError:
            return None
        if session is None or session.state is None or session.state.combat is None:
            return None
        return self._current_turn_id(session)

    # ------------------------------------------------------------------
    # Character sheet
    # ------------------------------------------------------------------

    def get_character_sheet(
        self, session_id: str, entity_id: str,
    ) -> CharacterSheet:
        session = self._get_session(session_id)
        if entity_id not in session.players:
            raise ValueError("You are not in this game")

        player_info = session.players[entity_id]
        if player_info.class_id is None:
            raise ValueError("Choose a class first")

        # Resolve the entity with current HP/effects
        if session.state is None:
            # Lobby phase — use class template
            return self.sheet_from_class_template(player_info, player_info.class_id)

        player = next(
            (p for p in session.state.players if p.entity_id == entity_id),
            None,
        )
        if player is None:
            raise ValueError("You are not in this game")

        return self.sheet_for_player(
            player_info,
            player,
            combat_state=session.state.combat,
        )

    def sheet_for_player(
        self,
        player_info: PlayerInfo,
        player: PlayerCharacter,
        *,
        combat_state=None,
    ) -> CharacterSheet:
        if player_info.class_id is None:
            raise ValueError("Choose a class first")

        class_data = load_class(player_info.class_id)
        in_combat = combat_state is not None
        entity = (
            combat_state.entities.get(player.entity_id, player)
            if combat_state is not None else player
        )

        # Major stats — effective if in combat, raw otherwise
        major_stats: dict[str, float] = {}
        for stat_name in (
            "attack", "hp", "speed", "crit_chance", "crit_dmg",
            "resistance", "energy", "mastery",
        ):
            if combat_state is not None:
                major_stats[stat_name] = get_effective_major_stat(
                    combat_state, player.entity_id, stat_name,
                )
            else:
                major_stats[stat_name] = get_effective_player_major_stat(
                    entity,
                    stat_name,
                )

        # Minor stats — effective if in combat, raw otherwise
        minor_stats: dict[str, float] = {}
        for key in entity.minor_stats.values:
            if combat_state is not None:
                minor_stats[key] = get_effective_minor_stat(
                    combat_state, player.entity_id, key,
                )
            else:
                minor_stats[key] = get_effective_player_minor_stat(entity, key)

        # Skills
        access = get_effective_skill_access(entity, combat_state)
        granted_set = set(access.granted)
        skill_ids = access.available
        skills = tuple(
            self._build_skill_info(
                entity,
                sid,
                combat_state=combat_state,
                temporary=(sid in granted_set),
            )
            for sid in skill_ids
        )

        # Passives
        passives = tuple(
            self._build_passive_info(pid)
            for pid in get_effective_passive_ids(entity)
        )

        # Modifiers
        modifiers = tuple(
            self._build_modifier_info(mod)
            for mod in entity.skill_modifiers
        )

        # Active effects
        active_effects = tuple(
            self._build_effect_info(eff)
            for eff in entity.active_effects
        )

        return CharacterSheet(
            entity_id=player.entity_id,
            display_name=player_info.display_name,
            class_id=player_info.class_id,
            class_name=class_data.name,
            level=player.level,
            xp=player.xp,
            current_hp=entity.current_hp,
            max_hp=int(major_stats["hp"]),
            current_energy=entity.current_energy,
            max_energy=int(major_stats["energy"]),
            major_stats=major_stats,
            minor_stats=minor_stats,
            skills=skills,
            passives=passives,
            modifiers=modifiers,
            active_effects=active_effects,
            in_combat=in_combat,
        )

    def sheet_from_class_template(
        self,
        player_info: PlayerInfo,
        class_id: str,
    ) -> CharacterSheet:
        return self._sheet_from_class_template(
            replace(player_info, class_id=class_id),
            load_class(class_id),
        )

    def inventory_for_player(
        self,
        player: PlayerCharacter,
        *,
        in_combat: bool,
    ) -> InventorySnapshot:
        return self._build_inventory_snapshot(player, in_combat=in_combat)

    def _sheet_from_class_template(
        self,
        player_info: PlayerInfo,
        class_data: ClassData,
    ) -> CharacterSheet:
        """Build a character sheet from class template (lobby phase)."""
        major = class_data.major_stats
        template_player = build_player(
            class_data.class_id,
            entity_id=player_info.entity_id,
        )
        skills = tuple(
            self._build_skill_info(template_player, sid)
            for sid in class_data.starting_skills
        )
        passives = tuple(
            self._build_passive_info(pid)
            for pid in class_data.starting_passives
        )
        return CharacterSheet(
            entity_id=player_info.entity_id,
            display_name=player_info.display_name,
            class_id=class_data.class_id,
            class_name=class_data.name,
            level=1,
            xp=0,
            current_hp=int(major.get("hp", 0)),
            max_hp=int(major.get("hp", 0)),
            current_energy=int(major.get("energy", 0)),
            max_energy=int(major.get("energy", 0)),
            major_stats={k: float(v) for k, v in major.items()},
            minor_stats={k: float(v) for k, v in class_data.minor_stats.items()},
            skills=skills,
            passives=passives,
            modifiers=(),
            active_effects=(),
            in_combat=False,
        )

    @classmethod
    def _build_skill_info(
        cls,
        entity: BaseEntity,
        skill_id: str,
        *,
        combat_state=None,
        temporary: bool = False,
    ) -> SkillInfo:
        data = load_skill(skill_id)
        hit_details = tuple(
            cls._build_skill_hit_detail(
                entity,
                skill_id,
                hit,
                index=index,
                combat_state=combat_state,
            )
            for index, hit in enumerate(data.hits)
        )
        summary_context = cls._build_skill_summary_context(
            data,
            hit_details,
        )

        return SkillInfo(
            skill_id=data.skill_id,
            name=data.name,
            energy_cost=data.energy_cost,
            hits=tuple(
                SkillHitInfo(
                    target_type=hit.target_type,
                    damage_type=hit.damage_type.value if hit.damage_type else None,
                )
                for hit in data.hits
            ),
            temporary=temporary,
            summary_parts=cls._tokenize_skill_summary_template(
                data.summary,
                summary_context,
            ),
            preview_note=_PREVIEW_NOTE if hit_details else "",
            hit_details=hit_details,
            self_effects=tuple(
                cls._build_effect_detail(
                    effect.effect_id,
                    duration_override=effect.duration_override,
                )
                for effect in data.self_effects
            ),
        )

    @classmethod
    def _build_skill_hit_detail(
        cls,
        entity: BaseEntity,
        skill_id: str,
        hit,
        *,
        index: int,
        combat_state=None,
    ) -> SkillHitDetail:
        preview = cls._preview_skill_hit_damage(
            entity,
            skill_id,
            hit,
            combat_state=combat_state,
        )
        return SkillHitDetail(
            index=index,
            target_type=hit.target_type,
            damage_type=preview.damage_type if preview else (
                hit.damage_type.value if hit.damage_type else None
            ),
            preview_damage_non_crit=preview.amount_non_crit if preview else None,
            preview_damage_crit=preview.amount_crit if preview else None,
            formula=hit.formula,
            on_hit_effects=tuple(
                cls._build_effect_detail(
                    effect.effect_id,
                    chance=effect.chance,
                )
                for effect in hit.on_hit_effects
            ),
            shared_with=hit.share_with,
        )

    @staticmethod
    def _damage_type_constants() -> dict[str, int]:
        return {
            damage_type.name: numeric
            for damage_type, numeric in _DAMAGE_TYPE_NUMERIC.items()
        }

    @classmethod
    def _preview_skill_hit_damage(
        cls,
        entity: BaseEntity,
        skill_id: str,
        hit,
        *,
        combat_state=None,
    ) -> _DamagePreview | None:
        if hit.damage_type is None:
            return None

        if combat_state is not None:
            attacker_ctx = build_effective_expr_context(combat_state, entity.entity_id)
            crit_dmg = get_effective_major_stat(
                combat_state,
                entity.entity_id,
                "crit_dmg",
            )
        else:
            attacker_ctx = build_expr_context(entity)
            crit_dmg = (
                get_effective_player_major_stat(entity, "crit_dmg")
                if isinstance(entity, PlayerCharacter)
                else entity.major_stats.crit_dmg
            )

        neutral_target = ExprContext(
            attack=0,
            hp=100,
            current_hp=100,
            speed=0,
            crit_chance=0.0,
            crit_dmg=1.0,
            resistance=0,
            energy=0,
            mastery=0,
        )

        ctx: dict[str, object] = {
            "base_power": hit.base_power,
            "attacker": attacker_ctx,
            "target": neutral_target,
        }

        raw = evaluate_expr(hit.formula, ctx)
        resolved_damage_type = hit.damage_type
        for inst in entity.skill_modifiers:
            mod = load_modifier(inst.modifier_id)
            if mod.phase != ModifierPhase.PRE_HIT:
                continue
            if mod.skill_filter and mod.skill_filter != skill_id:
                continue
            if (
                mod.damage_type_filter is not None
                and mod.damage_type_filter != resolved_damage_type.value
            ):
                continue
            if mod.action == "bonus_damage":
                raw += evaluate_expr(mod.expr, ctx) * inst.stack_count
            elif mod.action == "change_type" and mod.damage_type_override is not None:
                resolved_damage_type = DamageType(mod.damage_type_override)

        if combat_state is not None:
            damage_bonus = get_effective_minor_stat(
                combat_state,
                entity.entity_id,
                f"{resolved_damage_type.value}_dmg_pct",
            )
        elif isinstance(entity, PlayerCharacter):
            damage_bonus = get_effective_player_minor_stat(
                entity,
                f"{resolved_damage_type.value}_dmg_pct",
            )
        else:
            damage_bonus = entity.minor_stats.values.get(
                f"{resolved_damage_type.value}_dmg_pct",
                0.0,
            )

        base_after_type = raw * (1.0 + damage_bonus)
        effect_multiplier = cls._preview_damage_multiplier(
            entity,
            resolved_damage_type,
            combat_state=combat_state,
        )
        min_damage = load_constants().get("min_damage", 0)
        amount_non_crit = max(
            min_damage,
            int(base_after_type * effect_multiplier),
        )
        amount_crit = max(
            min_damage,
            int(base_after_type * crit_dmg * effect_multiplier),
        )
        return _DamagePreview(
            amount_non_crit=amount_non_crit,
            amount_crit=amount_crit,
            damage_type=resolved_damage_type.value,
        )

    @classmethod
    def _preview_damage_multiplier(
        cls,
        entity: BaseEntity,
        damage_type: DamageType,
        *,
        combat_state=None,
    ) -> float:
        multiplier = 1.0
        for inst in entity.active_effects:
            effect_def = load_effect(inst.effect_id)
            if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
                continue

            target_ctx = (
                build_effective_expr_context(combat_state, entity.entity_id)
                if combat_state is not None
                else build_expr_context(entity)
            )
            source_ctx = target_ctx
            if (
                combat_state is not None
                and inst.source_id in combat_state.entities
            ):
                source_ctx = build_effective_expr_context(
                    combat_state,
                    inst.source_id,
                )

            ctx: dict[str, object] = {
                "target": target_ctx,
                "attacker": source_ctx,
                "damage_type": _DAMAGE_TYPE_NUMERIC[damage_type],
                **cls._damage_type_constants(),
            }

            if effect_def.tick_condition and not evaluate_expr(effect_def.tick_condition, ctx):
                continue

            for action in effect_def.actions:
                if action.action_type != EffectActionType.DAMAGE_DEALT_MULT:
                    continue
                value = evaluate_expr(action.expr, ctx)
                stack_mult = inst.stack_count if action.scales_with_stacks else 1
                if value != 0:
                    multiplier *= value ** stack_mult

        return multiplier

    @classmethod
    def _build_skill_summary_context(
        cls,
        skill,
        hit_details: tuple[SkillHitDetail, ...],
    ) -> dict[str, str | int]:
        context: dict[str, str | int] = {
            "hits.count": len(skill.hits),
            "target_type": cls._aggregate_target_type(hit_details),
            "damage_type": cls._aggregate_damage_type(hit_details),
            "damage_non_crit": cls._aggregate_damage_value(
                hit_details,
                crit=False,
            ),
            "damage_crit": cls._aggregate_damage_value(
                hit_details,
                crit=True,
            ),
            "summary_text": cls._build_summary_text(hit_details, skill.self_effects),
        }

        for index, detail in enumerate(hit_details):
            context[f"hits.{index}.target_type"] = cls._target_label(detail.target_type)
            context[f"hits.{index}.damage_type"] = detail.damage_type or ""
            context[f"hits.{index}.damage_non_crit"] = (
                str(detail.preview_damage_non_crit)
                if detail.preview_damage_non_crit is not None else ""
            )
            context[f"hits.{index}.damage_crit"] = (
                str(detail.preview_damage_crit)
                if detail.preview_damage_crit is not None else ""
            )
            context[f"hits.{index}.formula"] = detail.formula

        return context

    @classmethod
    def _tokenize_skill_summary_template(
        cls,
        template: str,
        context: dict[str, str | int],
    ) -> tuple[SkillSummaryPart, ...]:
        parts: list[SkillSummaryPart] = []
        last = 0

        for match in _SKILL_TEMPLATE_RE.finditer(template):
            if match.start() > last:
                parts.append(SkillSummaryPart(
                    kind="text",
                    value=template[last:match.start()],
                ))

            key = match.group(1)
            if key not in context:
                raise ValueError(f"Unknown skill template placeholder: {key}")

            kind = "text"
            if key.endswith("damage_non_crit") or key == "damage_non_crit":
                kind = "damage_non_crit"
            elif key.endswith("damage_crit") or key == "damage_crit":
                kind = "damage_crit"

            parts.append(SkillSummaryPart(
                kind=kind,
                value=str(context[key]),
            ))
            last = match.end()

        if last < len(template):
            parts.append(SkillSummaryPart(kind="text", value=template[last:]))

        return tuple(parts)

    @classmethod
    def _build_summary_text(
        cls,
        hit_details: tuple[SkillHitDetail, ...],
        self_effects,
    ) -> str:
        if hit_details:
            segments = [
                cls._format_hit_summary(detail)
                for detail in hit_details
            ]
            if len(segments) == 1:
                return segments[0]
            return ", then ".join(segments)

        if self_effects:
            effect_names = [
                load_effect(effect.effect_id).name
                for effect in self_effects
            ]
            if len(effect_names) == 1:
                return f"Applies {effect_names[0]} to yourself."
            return f"Applies {', '.join(effect_names[:-1])}, and {effect_names[-1]} to yourself."

        return "Utility skill."

    @classmethod
    def _format_hit_summary(cls, detail: SkillHitDetail) -> str:
        target = cls._target_label(detail.target_type)
        if detail.preview_damage_non_crit is None or detail.preview_damage_crit is None:
            return f"Targets {target}."
        damage_type = detail.damage_type or "damage"
        return (
            f"Hits {target} for "
            f"{detail.preview_damage_non_crit} / {detail.preview_damage_crit} "
            f"{damage_type} damage"
        )

    @classmethod
    def _aggregate_target_type(
        cls,
        hit_details: tuple[SkillHitDetail, ...],
    ) -> str:
        if not hit_details:
            return "yourself"
        labels = {
            cls._target_label(detail.target_type)
            for detail in hit_details
        }
        return labels.pop() if len(labels) == 1 else "mixed targets"

    @staticmethod
    def _aggregate_damage_type(
        hit_details: tuple[SkillHitDetail, ...],
    ) -> str:
        values = {
            detail.damage_type
            for detail in hit_details
            if detail.damage_type is not None
        }
        if not values:
            return ""
        return values.pop() if len(values) == 1 else "mixed"

    @staticmethod
    def _aggregate_damage_value(
        hit_details: tuple[SkillHitDetail, ...],
        *,
        crit: bool,
    ) -> str:
        values: list[str] = []
        seen: set[str] = set()
        for detail in hit_details:
            value = (
                detail.preview_damage_crit
                if crit else detail.preview_damage_non_crit
            )
            if value is None:
                continue
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            values.append(text)

        return " then ".join(values)

    @staticmethod
    def _target_label(target_type) -> str:
        labels = {
            "single_enemy": "single enemy",
            "all_enemies": "all enemies",
            "single_ally": "single ally",
            "all_allies": "all allies",
            "self": "yourself",
        }
        return labels.get(target_type.value, target_type.value.replace("_", " "))

    @classmethod
    def _build_effect_detail(
        cls,
        effect_id: str,
        *,
        chance: float | None = None,
        duration_override: int | None = None,
    ) -> SkillEffectDetail:
        effect = load_effect(effect_id)
        duration = duration_override if duration_override is not None else effect.duration
        return SkillEffectDetail(
            effect_id=effect_id,
            name=effect.name,
            summary=cls._describe_effect(effect, duration),
            chance=chance,
        )

    @classmethod
    def _describe_effect(cls, effect, duration: int) -> str:
        parts: list[str] = []
        for action in effect.actions:
            match action.action_type:
                case EffectActionType.DAMAGE:
                    damage_type = action.damage_type.value if action.damage_type else "damage"
                    parts.append(f"deals {damage_type} damage each turn")
                case EffectActionType.HEAL:
                    parts.append("restores health")
                case EffectActionType.SKIP_TURN:
                    parts.append("skips the target's next turn")
                case EffectActionType.DAMAGE_DEALT_MULT:
                    parts.append(f"changes damage dealt by {action.expr}")
                case EffectActionType.DAMAGE_TAKEN_MULT:
                    parts.append(f"changes damage taken by {action.expr}")
                case EffectActionType.STAT_MODIFY:
                    parts.append(f"modifies {action.stat} by {action.expr}")
                case EffectActionType.GRANT_ENERGY:
                    parts.append(f"restores energy by {action.expr}")
                case EffectActionType.GRANT_SKILL:
                    if action.skill_id is not None:
                        parts.append(f"grants {load_skill(action.skill_id).name}")
                case EffectActionType.BLOCK_SKILL:
                    if action.skill_id is not None:
                        parts.append(f"blocks {load_skill(action.skill_id).name}")

        body = ", ".join(parts) if parts else "applies an effect"
        turn_label = "turn" if duration == 1 else "turns"
        return f"{body} for {duration} {turn_label}."

    @staticmethod
    def _build_passive_info(passive_id: str) -> PassiveInfo:
        data = load_passive(passive_id)
        return PassiveInfo(
            skill_id=data.skill_id,
            name=data.name,
            triggers=tuple(trigger.value for trigger in data.triggers),
            action=data.action.value,
        )

    @staticmethod
    def _build_modifier_info(mod) -> ModifierInfo:
        data = load_modifier(mod.modifier_id)
        return ModifierInfo(
            modifier_id=mod.modifier_id,
            name=data.name,
            stack_count=mod.stack_count,
        )

    @staticmethod
    def _build_reward_offer_info(
        reward_key: str,
    ) -> RewardOfferInfo:
        reward_kind, reward_id = parse_reward_key(reward_key)

        if reward_kind == "modifier":
            data = load_modifier(reward_id)
            return RewardOfferInfo(
                reward_key=reward_key,
                reward_kind=reward_kind,
                reward_id=reward_id,
                name=data.name,
                description=getattr(data, "description", "") or "",
            )
        if reward_kind == "skill":
            skill = load_skill(reward_id)
            parts: list[str] = []
            for hit in skill.hits:
                target = hit.target_type.value.replace("_", " ")
                dmg = f" {hit.damage_type.value}" if hit.damage_type else ""
                parts.append(f"{target}{dmg}")
            description = " | ".join(parts)
            if skill.energy_cost > 0:
                description = f"{skill.energy_cost} energy - {description}"
            return RewardOfferInfo(
                reward_key=reward_key,
                reward_kind=reward_kind,
                reward_id=reward_id,
                name=skill.name,
                description=description,
            )
        if reward_kind == "passive":
            passive = load_passive(reward_id)
            return RewardOfferInfo(
                reward_key=reward_key,
                reward_kind=reward_kind,
                reward_id=reward_id,
                name=passive.name,
                description=GameService._build_passive_reward_description(passive),
            )
        raise ValueError(f"Unknown reward kind: {reward_kind}")

    @staticmethod
    def _build_passive_reward_description(passive) -> str:
        trigger_text = ", ".join(
            trigger.value.replace("_", " ")
            for trigger in passive.triggers
        )

        if passive.action.value == "grant_energy":
            action_text = f"grant {passive.expr} energy"
        elif passive.action.value == "apply_effect" and passive.effect_id is not None:
            action_text = f"apply {load_effect(passive.effect_id).name}"
        elif passive.action.value == "cast_skill" and passive.cast_skill_id is not None:
            action_text = f"cast {load_skill(passive.cast_skill_id).name}"
        elif passive.action.value == "consume_effect" and passive.consume_effect_id is not None:
            action_text = f"consume {load_effect(passive.consume_effect_id).name}"
        elif passive.action.value == "heal":
            action_text = "heal"
        elif passive.action.value == "damage":
            action_text = "deal damage"
        elif passive.action.value == "modify_stat":
            action_text = "modify stats"
        else:
            action_text = passive.action.value.replace("_", " ")

        return f"{trigger_text} | {action_text}"

    @staticmethod
    def _build_effect_info(eff) -> EffectInfo:
        data = load_effect(eff.effect_id)
        _BUFF_ACTIONS = frozenset({
            EffectActionType.HEAL,
            EffectActionType.STAT_MODIFY,
            EffectActionType.GRANT_ENERGY,
            EffectActionType.GRANT_SKILL,
            EffectActionType.DAMAGE_DEALT_MULT,
        })
        is_buff = all(a.action_type in _BUFF_ACTIONS for a in data.actions)
        granted_skills = tuple(
            action.skill_id
            for action in data.actions
            if action.action_type == EffectActionType.GRANT_SKILL
            and action.skill_id is not None
        )
        blocked_skills = tuple(
            action.skill_id
            for action in data.actions
            if action.action_type == EffectActionType.BLOCK_SKILL
            and action.skill_id is not None
        )
        return EffectInfo(
            effect_id=eff.effect_id,
            name=data.name,
            remaining_duration=eff.remaining_duration,
            stack_count=eff.stack_count,
            is_buff=is_buff,
            granted_skills=granted_skills,
            blocked_skills=blocked_skills,
        )

    @staticmethod
    def _item_effect_to_info(effect) -> ItemEffectInfo:
        return ItemEffectInfo(
            effect_type=effect.effect_type.value,
            stat=effect.stat,
            value=effect.value,
            skill_id=effect.skill_id,
            passive_id=effect.passive_id,
        )

    @staticmethod
    def _build_item_set_infos(player: PlayerCharacter) -> tuple[ItemSetInfo, ...]:
        item_sets = load_item_sets()
        counts = collect_equipped_item_set_counts(player.inventory)
        infos: list[ItemSetInfo] = []

        for set_id, equipped_count in sorted(counts.items()):
            item_set = item_sets.get(set_id)
            if item_set is None:
                continue

            bonuses: list[ItemSetBonusInfo] = []
            for bonus in item_set.bonuses:
                active = equipped_count >= bonus.required_count
                display_count = equipped_count if active else bonus.required_count
                effects = tuple(
                    GameService._item_effect_to_info(effect)
                    for effect in resolve_item_set_bonus_effects(
                        bonus,
                        equipped_count=display_count,
                    )
                )
                bonuses.append(ItemSetBonusInfo(
                    required_count=bonus.required_count,
                    active=active,
                    effects=effects,
                ))

            infos.append(ItemSetInfo(
                set_id=set_id,
                name=item_set.name,
                equipped_count=equipped_count,
                bonuses=tuple(bonuses),
            ))

        return tuple(infos)

    @staticmethod
    def _build_inventory_snapshot(
        player: PlayerCharacter,
        *,
        in_combat: bool,
    ) -> InventorySnapshot:
        item_sets = load_item_sets()
        items = sorted(
            player.inventory.items.values(),
            key=lambda item: (item.item_type.value, item.name, item.instance_id),
        )
        item_infos = tuple(
            ItemInfo(
                instance_id=item.instance_id,
                blueprint_id=item.blueprint_id,
                name=item.name,
                item_type=item.item_type.value,
                rarity=item.rarity,
                quality=item.quality,
                equipped_slot=player.inventory.equipped_slot(item.instance_id)[0],
                equipped_index=player.inventory.equipped_slot(item.instance_id)[1],
                effects=tuple(
                    GameService._item_effect_to_info(effect)
                    for effect in item.effects
                ),
                item_sets=item.item_sets,
                item_set_names=tuple(
                    item_sets[set_id].name
                    for set_id in item.item_sets
                    if set_id in item_sets
                ),
                unique=item.unique,
            )
            for item in items
        )
        by_id = {
            item_info.instance_id: item_info
            for item_info in item_infos
        }
        equipment = player.inventory.equipment
        equipment_slots = (
            EquipmentSlotInfo(
                slot_type="weapon",
                slot_index=None,
                label="Weapon",
                accepts_item_type="weapon",
                item=by_id.get(equipment.weapon_id) if equipment.weapon_id else None,
            ),
            EquipmentSlotInfo(
                slot_type="armor",
                slot_index=None,
                label="Armor",
                accepts_item_type="armor",
                item=by_id.get(equipment.armor_id) if equipment.armor_id else None,
            ),
            *tuple(
                EquipmentSlotInfo(
                    slot_type="relic",
                    slot_index=index,
                    label=f"Relic {index + 1}",
                    accepts_item_type="relic",
                    item=by_id.get(item_id) if item_id else None,
                )
                for index, item_id in enumerate(equipment.relic_ids)
            ),
        )
        unequipped_items = tuple(
            item_info
            for item_info in item_infos
            if item_info.equipped_slot is None
        )
        return InventorySnapshot(
            items=item_infos,
            unequipped_items=unequipped_items,
            equipment_slots=equipment_slots,
            can_manage_equipment=not in_combat,
            equipment_lock_reason=(
                "Equipment changes are disabled in combat."
                if in_combat else None
            ),
            item_sets=GameService._build_item_set_infos(player),
            dissolve_currency_name=dissolve_currency_name(
                load_item_dissolve_constants(),
            ),
            dissolve_rarity_values=dissolve_rarity_values(
                load_item_dissolve_constants(),
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> ActiveSession:
        return self._sessions.get_active_session(session_id)

    @staticmethod
    def _assert_in_combat(session: ActiveSession) -> None:
        if session.state is None or session.state.combat is None:
            raise ValueError("Not in combat")

    @staticmethod
    def _assert_not_in_combat(session: ActiveSession) -> None:
        if session.state is None:
            raise ValueError("No active run")
        if session.state.combat is not None:
            raise ValueError("Cannot change equipment during combat")

    @staticmethod
    def _get_runtime_player(
        session: ActiveSession,
        entity_id: str,
    ) -> PlayerCharacter:
        if session.state is None:
            raise ValueError("No active run")
        player = next(
            (candidate for candidate in session.state.players if candidate.entity_id == entity_id),
            None,
        )
        if player is None:
            raise ValueError("Player is not part of this run")
        return player

    @staticmethod
    def _replace_runtime_player(
        session: ActiveSession,
        player: PlayerCharacter,
    ) -> None:
        if session.state is None:
            raise ValueError("No active run")
        session.state = replace(
            session.state,
            players=tuple(
                player if current.entity_id == player.entity_id else current
                for current in session.state.players
            ),
        )

    @staticmethod
    def _reconcile_current_resources(player: PlayerCharacter) -> PlayerCharacter:
        max_hp = int(get_effective_player_major_stat(player, "hp"))
        max_energy = int(get_effective_player_major_stat(player, "energy"))
        return replace(
            player,
            current_hp=min(player.current_hp, max_hp),
            current_energy=min(player.current_energy, max_energy),
        )

    def _submit_and_capture(
        self,
        session: ActiveSession,
        action: ActionRequest,
        results: list[ActionResult],
        *,
        skip: bool = False,
    ) -> None:
        """Submit an action and capture the ActionResult before finalize can clear it."""
        log_len = len(session.state.combat.action_log)

        if skip:
            session.state = session.manager.skip_combat_turn(
                session.state, action.actor_id,
            )
        else:
            session.state = session.manager.submit_combat_action(
                session.state, action,
            )

        if session.state.combat is not None:
            results.extend(session.state.combat.action_log[log_len:])

    def _auto_play_ai_entities(
        self,
        session: ActiveSession,
        results: list[ActionResult] | None = None,
    ) -> None:
        """Process all consecutive AI-controlled turns, capturing results."""
        while (
            session.state.combat is not None
            and self._current_actor_is_ai_controlled(session)
        ):
            ai_action = self._build_ai_action(session)
            if ai_action is None:
                current_id = self._current_turn_id(session)
                skip_action = ActionRequest(
                    actor_id=current_id,
                    action_type=ActionType.ACTION,
                    skill_id=None,
                )
                if results is not None:
                    self._submit_and_capture(session, skip_action, results, skip=True)
                else:
                    session.state = session.manager.skip_combat_turn(
                        session.state, current_id,
                    )
            elif results is not None:
                self._submit_and_capture(session, ai_action, results)
            else:
                session.state = session.manager.submit_combat_action(
                    session.state, ai_action,
                )

    @staticmethod
    def _build_ai_action(session: ActiveSession) -> ActionRequest | None:
        combat = session.state.combat
        current_id = combat.turn_order[combat.current_turn_index]
        rng = SeededRNG(0)
        rng.set_state(combat.rng_state)
        action = build_ai_action(combat, current_id, rng)
        session.state = replace(
            session.state,
            combat=replace(combat, rng_state=rng.get_state()),
        )
        return action

    @staticmethod
    def _current_turn_id(session: ActiveSession) -> str | None:
        combat = session.state.combat
        if combat is None:
            return None
        return combat.turn_order[combat.current_turn_index]

    @staticmethod
    def _current_entity_type(session: ActiveSession) -> EntityType | None:
        combat = session.state.combat
        if combat is None:
            return None
        current_id = combat.turn_order[combat.current_turn_index]
        return combat.entities[current_id].entity_type

    @staticmethod
    def _current_actor_is_ai_controlled(session: ActiveSession) -> bool:
        combat = session.state.combat
        if combat is None or combat.current_turn_index >= len(combat.turn_order):
            return False
        current_id = combat.turn_order[combat.current_turn_index]
        entity = combat.entities.get(current_id)
        if entity is None:
            return False
        return is_ai_controlled(entity)

    def _build_turn_batch(
        self,
        session: ActiveSession,
        results: tuple[ActionResult, ...],
    ) -> TurnBatch:
        combat_ended = session.state.combat is None
        return TurnBatch(
            results=results,
            entities=self._build_entity_map(session),
            whose_turn=self._current_turn_id(session) if not combat_ended else None,
            combat_ended=combat_ended,
            victory=self._check_victory(session) if combat_ended else False,
        )

    def _check_victory(self, session: ActiveSession) -> bool:
        """Victory = at least one player alive after combat ends."""
        return any(p.current_hp > 0 for p in session.state.players)

    def _build_combat_snapshot(self, session: ActiveSession) -> CombatSnapshot:
        combat = session.state.combat
        return CombatSnapshot(
            entities=self._build_entity_map(session),
            turn_order=combat.turn_order,
            whose_turn=combat.turn_order[combat.current_turn_index],
            round_number=combat.round_number,
        )

    def _build_entity_map(
        self,
        session: ActiveSession,
    ) -> dict[str, EntitySnapshot]:
        if session.state.combat is not None:
            return {
                eid: self._entity_to_snapshot(e, session.state.combat)
                for eid, e in session.state.combat.entities.items()
            }
        # Combat ended — build from session players only
        return {
            p.entity_id: EntitySnapshot(
                entity_id=p.entity_id,
                name=p.entity_name,
                entity_type=p.entity_type,
                current_hp=p.current_hp,
                max_hp=int(get_effective_player_major_stat(p, "hp")),
                current_energy=p.current_energy,
                max_energy=int(get_effective_player_major_stat(p, "energy")),
                is_alive=p.current_hp > 0,
            )
            for p in session.state.players
        }

    @staticmethod
    def _entity_to_snapshot(
        entity: object,
        combat_state=None,
    ) -> EntitySnapshot:
        max_hp = entity.major_stats.hp
        max_energy = entity.major_stats.energy
        if combat_state is not None:
            max_hp = int(get_effective_major_stat(combat_state, entity.entity_id, "hp"))
            max_energy = int(get_effective_major_stat(
                combat_state,
                entity.entity_id,
                "energy",
            ))
        return EntitySnapshot(
            entity_id=entity.entity_id,
            name=entity.entity_name,
            entity_type=entity.entity_type,
            current_hp=entity.current_hp,
            max_hp=max_hp,
            current_energy=entity.current_energy,
            max_energy=max_energy,
            is_alive=entity.current_hp > 0,
        )
