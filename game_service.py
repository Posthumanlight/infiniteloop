from dataclasses import dataclass, replace

from game.combat.effects import get_effective_major_stat, get_effective_minor_stat
from game.combat.models import ActionRequest, ActionResult
from game.core.data_loader import (
    ClassData,
    load_class,
    load_classes,
    load_effect,
    load_modifier,
    load_passive,
    load_skill,
)
from game.core.enums import ActionType, EffectActionType, EntityType, SessionPhase, TargetType
from game.session.factories import build_player
from game.session.session_manager import SessionManager
from game.session.models import SessionState
from game.core.game_models import (
    CharacterSheet,
    CombatSnapshot,
    EffectInfo,
    EntitySnapshot,
    ModifierChoiceNoticeInfo,
    ModifierInfo,
    ModifierOfferInfo,
    PendingModifierChoiceInfo,
    PassiveInfo,
    PlayerInfo,
    SkillHitInfo,
    SkillInfo,
    TurnBatch,
)


@dataclass
class _ActiveSession:
    session_id: str
    players: dict[str, PlayerInfo]  # entity_id -> PlayerInfo
    manager: SessionManager
    state: SessionState | None


class GameService:
    """In-memory game orchestrator. One instance per server process.

    Knows nothing about Telegram — takes generic IDs, returns dataclasses.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ActiveSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, session_id: str, creator: PlayerInfo) -> None:
        if session_id in self._sessions:
            raise ValueError("Session already exists for this chat")

        manager = SessionManager(seed=hash(session_id) & 0x7FFFFFFF)
        self._sessions[session_id] = _ActiveSession(
            session_id=session_id,
            players={creator.entity_id: creator},
            manager=manager,
            state=None,
        )

    def join_session(self, session_id: str, player: PlayerInfo) -> None:
        session = self._get_session(session_id)
        if player.entity_id in session.players:
            raise ValueError("Player already in session")
        session.players[player.entity_id] = player

    def get_session_players(self, session_id: str) -> list[PlayerInfo]:
        session = self._get_session(session_id)
        return list(session.players.values())

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def is_in_combat(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        return (
            session is not None
            and session.state is not None
            and session.state.combat is not None
        )

    def remove_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Class selection
    # ------------------------------------------------------------------

    @staticmethod
    def get_available_classes() -> dict[str, ClassData]:
        return load_classes()

    def select_class(
        self, session_id: str, entity_id: str, class_id: str,
    ) -> None:
        session = self._get_session(session_id)
        if entity_id not in session.players:
            raise ValueError("Player not in session")

        classes = load_classes()
        if class_id not in classes:
            raise ValueError(f"Unknown class: {class_id}")

        old_info = session.players[entity_id]
        session.players[entity_id] = replace(old_info, class_id=class_id)

    def all_players_ready(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        return all(p.class_id is not None for p in session.players.values())

    # ------------------------------------------------------------------
    # Exploration run
    # ------------------------------------------------------------------

    def start_exploration_run(self, session_id: str) -> None:
        session = self._get_session(session_id)
        if not session.players:
            raise ValueError("No players in session")
        if not self.all_players_ready(session_id):
            raise ValueError("Not all players have chosen a class")

        players = [
            build_player(info.class_id, entity_id=info.entity_id)
            for info in session.players.values()
        ]

        session.state = session.manager.start_run(session_id, players)
        session.state = session.manager.generate_choices(session.state)

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
            and self._current_entity_type(session) == EntityType.ENEMY
        ):
            self._auto_play_enemies(session)

        return session.state.phase

    def continue_exploration(self, session_id: str) -> None:
        """After combat/event ends, generate new location choices."""
        session = self._get_session(session_id)
        session.state = session.manager.generate_choices(session.state)

    def get_pending_modifier_choices(
        self,
        session_id: str,
    ) -> tuple[PendingModifierChoiceInfo, ...]:
        session = self._get_session(session_id)
        if session.state is None:
            raise ValueError("No active run")

        pending = session.manager.get_pending_modifier_choices(session.state)
        result: list[PendingModifierChoiceInfo] = []
        for player_id, choice in sorted(pending.items(), key=lambda item: item[0]):
            if not choice.current_offer:
                continue
            offers = tuple(
                self._build_modifier_offer_info(modifier_id)
                for modifier_id in choice.current_offer
            )
            result.append(PendingModifierChoiceInfo(
                player_id=player_id,
                pending_count=choice.pending_count,
                offers=offers,
            ))
        return tuple(result)

    def submit_modifier_choice(
        self,
        session_id: str,
        player_id: str,
        modifier_id: str,
    ) -> None:
        session = self._get_session(session_id)
        session.state = session.manager.submit_modifier_choice(
            session.state, player_id, modifier_id,
        )

    def consume_modifier_choice_notices(
        self,
        session_id: str,
    ) -> tuple[ModifierChoiceNoticeInfo, ...]:
        session = self._get_session(session_id)
        if session.state is None:
            return ()
        session.state, notices = session.manager.consume_modifier_notices(session.state)
        return tuple(
            ModifierChoiceNoticeInfo(
                player_id=notice.player_id,
                skipped_count=notice.skipped_count,
            )
            for notice in notices
        )

    def get_session_phase(self, session_id: str) -> SessionPhase | None:
        session = self._sessions.get(session_id)
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
            and self._current_entity_type(session) == EntityType.ENEMY
        ):
            self._auto_play_enemies(session)

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
        self._auto_play_enemies(session, results)

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
        self._auto_play_enemies(session, results)

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
            self._entity_to_snapshot(e)
            for e in session.state.combat.entities.values()
            if e.entity_type == EntityType.ENEMY and e.current_hp > 0
        ]

    def get_alive_allies(self, session_id: str) -> list[EntitySnapshot]:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return [
            self._entity_to_snapshot(e)
            for e in session.state.combat.entities.values()
            if e.entity_type == EntityType.PLAYER and e.current_hp > 0
        ]

    def get_whose_turn(self, session_id: str) -> str | None:
        session = self._sessions.get(session_id)
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

        class_data = load_class(player_info.class_id)
        in_combat = (
            session.state is not None
            and session.state.combat is not None
        )

        # Resolve the entity with current HP/effects
        if session.state is None:
            # Lobby phase — use class template
            return self._sheet_from_class_template(
                player_info, class_data,
            )

        player = next(
            (p for p in session.state.players if p.entity_id == entity_id),
            None,
        )
        if player is None:
            raise ValueError("You are not in this game")

        if in_combat:
            entity = session.state.combat.entities.get(entity_id, player)
            combat_state = session.state.combat
        else:
            entity = player
            combat_state = None

        # Major stats — effective if in combat, raw otherwise
        major_stats: dict[str, float] = {}
        for stat_name in (
            "attack", "hp", "speed", "crit_chance", "crit_dmg",
            "resistance", "energy", "mastery",
        ):
            if combat_state is not None:
                major_stats[stat_name] = get_effective_major_stat(
                    combat_state, entity_id, stat_name,
                )
            else:
                major_stats[stat_name] = float(
                    getattr(entity.major_stats, stat_name),
                )

        # Minor stats — effective if in combat, raw otherwise
        minor_stats: dict[str, float] = {}
        for key, val in entity.minor_stats.values.items():
            if combat_state is not None:
                minor_stats[key] = get_effective_minor_stat(
                    combat_state, entity_id, key,
                )
            else:
                minor_stats[key] = val

        # Skills
        skill_ids = player.skills
        skills = tuple(
            self._build_skill_info(sid) for sid in skill_ids
        )

        # Passives
        passives = tuple(
            self._build_passive_info(pid) for pid in entity.passive_skills
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
            entity_id=entity_id,
            display_name=player_info.display_name,
            class_id=player_info.class_id,
            class_name=class_data.name,
            level=player.level,
            xp=player.xp,
            current_hp=entity.current_hp,
            max_hp=entity.major_stats.hp,
            current_energy=entity.current_energy,
            max_energy=entity.major_stats.energy,
            major_stats=major_stats,
            minor_stats=minor_stats,
            skills=skills,
            passives=passives,
            modifiers=modifiers,
            active_effects=active_effects,
            in_combat=in_combat,
        )

    def _sheet_from_class_template(
        self,
        player_info: PlayerInfo,
        class_data: ClassData,
    ) -> CharacterSheet:
        """Build a character sheet from class template (lobby phase)."""
        major = class_data.major_stats
        skills = tuple(
            self._build_skill_info(sid) for sid in class_data.starting_skills
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

    @staticmethod
    def _build_skill_info(skill_id: str) -> SkillInfo:
        data = load_skill(skill_id)
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
        )

    @staticmethod
    def _build_passive_info(passive_id: str) -> PassiveInfo:
        data = load_passive(passive_id)
        return PassiveInfo(
            skill_id=data.skill_id,
            name=data.name,
            trigger=data.trigger.value,
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
    def _build_modifier_offer_info(modifier_id: str) -> ModifierOfferInfo:
        data = load_modifier(modifier_id)
        return ModifierOfferInfo(
            modifier_id=modifier_id,
            name=data.name,
        )

    @staticmethod
    def _build_effect_info(eff) -> EffectInfo:
        data = load_effect(eff.effect_id)
        _BUFF_ACTIONS = frozenset({
            EffectActionType.HEAL,
            EffectActionType.STAT_MODIFY,
            EffectActionType.GRANT_ENERGY,
            EffectActionType.DAMAGE_DEALT_MULT,
        })
        is_buff = all(a.action_type in _BUFF_ACTIONS for a in data.actions)
        return EffectInfo(
            effect_id=eff.effect_id,
            name=data.name,
            remaining_duration=eff.remaining_duration,
            stack_count=eff.stack_count,
            is_buff=is_buff,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> _ActiveSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("No active session")
        return session

    @staticmethod
    def _assert_in_combat(session: _ActiveSession) -> None:
        if session.state is None or session.state.combat is None:
            raise ValueError("Not in combat")

    def _submit_and_capture(
        self,
        session: _ActiveSession,
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

    def _auto_play_enemies(
        self,
        session: _ActiveSession,
        results: list[ActionResult] | None = None,
    ) -> None:
        """Process all consecutive enemy turns, capturing results."""
        while (
            session.state.combat is not None
            and self._current_entity_type(session) == EntityType.ENEMY
        ):
            enemy_action = self._build_enemy_action(session)
            if results is not None:
                self._submit_and_capture(session, enemy_action, results)
            else:
                session.state = session.manager.submit_combat_action(
                    session.state, enemy_action,
                )

    @staticmethod
    def _build_enemy_action(session: _ActiveSession) -> ActionRequest:
        """MVP enemy AI: first skill, first alive player/ally per single-target hit."""
        combat = session.state.combat
        current_id = combat.turn_order[combat.current_turn_index]
        enemy = combat.entities[current_id]
        skill_id = enemy.skills[0]
        skill = load_skill(skill_id)

        alive_players = [
            eid
            for eid in combat.turn_order
            if combat.entities[eid].entity_type == EntityType.PLAYER
            and combat.entities[eid].current_hp > 0
        ]
        alive_allies = [
            eid
            for eid in combat.turn_order
            if eid != current_id
            and combat.entities[eid].entity_type == EntityType.ENEMY
            and combat.entities[eid].current_hp > 0
        ]

        pairs: list[tuple[int, str]] = []
        for hit_index, hit in enumerate(skill.hits):
            if hit.share_with is not None:
                continue
            if hit.target_type == TargetType.SINGLE_ENEMY and alive_players:
                pairs.append((hit_index, alive_players[0]))
            elif hit.target_type == TargetType.SINGLE_ALLY and alive_allies:
                pairs.append((hit_index, alive_allies[0]))

        return ActionRequest(
            actor_id=current_id,
            action_type=ActionType.ACTION,
            skill_id=skill_id,
            target_ids=tuple(pairs),
        )

    @staticmethod
    def _current_turn_id(session: _ActiveSession) -> str | None:
        combat = session.state.combat
        if combat is None:
            return None
        return combat.turn_order[combat.current_turn_index]

    @staticmethod
    def _current_entity_type(session: _ActiveSession) -> EntityType | None:
        combat = session.state.combat
        if combat is None:
            return None
        current_id = combat.turn_order[combat.current_turn_index]
        return combat.entities[current_id].entity_type

    def _build_turn_batch(
        self,
        session: _ActiveSession,
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

    def _check_victory(self, session: _ActiveSession) -> bool:
        """Victory = at least one player alive after combat ends."""
        return any(p.current_hp > 0 for p in session.state.players)

    def _build_combat_snapshot(self, session: _ActiveSession) -> CombatSnapshot:
        combat = session.state.combat
        return CombatSnapshot(
            entities=self._build_entity_map(session),
            turn_order=combat.turn_order,
            whose_turn=combat.turn_order[combat.current_turn_index],
            round_number=combat.round_number,
        )

    def _build_entity_map(
        self,
        session: _ActiveSession,
    ) -> dict[str, EntitySnapshot]:
        if session.state.combat is not None:
            return {
                eid: self._entity_to_snapshot(e)
                for eid, e in session.state.combat.entities.items()
            }
        # Combat ended — build from session players only
        return {
            p.entity_id: EntitySnapshot(
                entity_id=p.entity_id,
                name=p.entity_name,
                entity_type=p.entity_type,
                current_hp=p.current_hp,
                max_hp=p.major_stats.hp,
                current_energy=p.current_energy,
                max_energy=p.major_stats.energy,
                is_alive=p.current_hp > 0,
            )
            for p in session.state.players
        }

    @staticmethod
    def _entity_to_snapshot(entity: object) -> EntitySnapshot:
        return EntitySnapshot(
            entity_id=entity.entity_id,
            name=entity.entity_name,
            entity_type=entity.entity_type,
            current_hp=entity.current_hp,
            max_hp=entity.major_stats.hp,
            current_energy=entity.current_energy,
            max_energy=entity.major_stats.energy,
            is_alive=entity.current_hp > 0,
        )
