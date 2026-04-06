from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.character.progression import apply_xp
from game.character.stats import MajorStats
from game.combat.engine import (
    get_available_actions,
    start_combat,
    skip_turn,
    submit_action,
)
from game.combat.models import ActionRequest, CombatState
from game.core.data_loader import ProgressionConfig, load_event
from game.core.dice import SeededRNG
from game.core.enums import (
    CombatPhase,
    EntityType,
    OutcomeAction,
    SessionPhase,
)
from game.events.engine import (
    resolve_event as _resolve_event,
    start_event,
    submit_vote,
)
from game.events.models import OutcomeResult
from game.session.factories import build_enemies
from game.session.models import SessionState


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
    ):
        self._rng = rng
        self._progression = progression
        self._base_stats = base_stats  # keyed by class_id

    def _next_seed(self) -> int:
        return self._rng.d(2**31 - 1)

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def enter_combat(
        self,
        state: SessionState,
        enemy_ids: tuple[str, ...],
    ) -> SessionState:
        """Build enemies from TOML and start a combat encounter."""
        enemies = build_enemies(enemy_ids)
        combat_state = start_combat(
            session_id=state.session_id,
            players=list(state.players),
            enemies=enemies,
            seed=self._next_seed(),
        )
        return replace(
            state,
            phase=SessionPhase.IN_COMBAT,
            combat=combat_state,
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
    def get_combat_actions(state: SessionState, actor_id: str) -> list:
        return get_available_actions(state.combat, actor_id)

    def finalize_combat(self, state: SessionState) -> SessionState:
        """Apply combat results to players, clear combat sub-state."""
        state = self._apply_combat_results(state)
        return replace(
            state,
            combat=None,
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
    ) -> SessionState:
        """Load event from TOML and start an event encounter."""
        event_def = load_event(event_id)
        player_ids = [p.entity_id for p in state.players]
        event_state = start_event(
            session_id=state.session_id,
            event_def=event_def,
            player_ids=player_ids,
            seed=self._next_seed(),
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
    ) -> tuple[SessionState, tuple[str, ...]]:
        """Resolve event votes, apply outcomes, return combat enemies if any.

        Returns:
            (updated_state, combat_enemy_ids) — combat_enemy_ids is non-empty
            if a START_COMBAT outcome was triggered.
        """
        event_state, resolution = _resolve_event(
            state.event, list(state.players),
        )
        state = replace(
            state,
            event=event_state,
            run_stats=replace(
                state.run_stats,
                events_completed=state.run_stats.events_completed + 1,
            ),
        )

        # Apply outcomes to players
        state = self._apply_event_outcomes(state, resolution.outcomes)

        # Collect START_COMBAT enemy groups
        combat_enemy_ids: list[str] = []
        for outcome in resolution.outcomes:
            if outcome.action == OutcomeAction.START_COMBAT:
                combat_enemy_ids.extend(outcome.enemy_group)

        # Clear event sub-state
        state = replace(state, event=None)

        return state, tuple(combat_enemy_ids)

    # ------------------------------------------------------------------
    # Side-effect application
    # ------------------------------------------------------------------

    def _apply_combat_results(self, state: SessionState) -> SessionState:
        """Merge HP/energy/effects from combat entities back to session players."""
        combat_state = state.combat
        updated_players: list[PlayerCharacter] = []
        enemies_defeated = 0
        total_damage_dealt = 0
        total_damage_taken = 0
        total_xp = 0

        for entity in combat_state.entities.values():
            if entity.entity_type == EntityType.ENEMY and entity.current_hp <= 0:
                enemies_defeated += 1
                total_xp += getattr(entity, "xp_reward", 0)

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

            if total_xp > 0:
                base = self._base_stats.get(updated.player_class)
                if base is not None:
                    updated = apply_xp(
                        updated, total_xp, self._progression, base,
                    )

            updated_players.append(updated)

        new_stats = replace(
            state.run_stats,
            enemies_defeated=state.run_stats.enemies_defeated + enemies_defeated,
            total_damage_dealt=state.run_stats.total_damage_dealt + total_damage_dealt,
            total_damage_taken=state.run_stats.total_damage_taken + total_damage_taken,
            total_xp_gained=state.run_stats.total_xp_gained + total_xp,
        )
        return replace(state, players=tuple(updated_players), run_stats=new_stats)

    def _apply_event_outcomes(
        self,
        state: SessionState,
        outcomes: tuple[OutcomeResult, ...],
    ) -> SessionState:
        """Apply event outcome descriptors to player state."""
        player_map: dict[str, PlayerCharacter] = {
            p.entity_id: p for p in state.players
        }
        total_healing = 0
        total_damage = 0
        total_xp = 0

        for outcome in outcomes:
            player = player_map.get(outcome.player_id)
            if player is None:
                continue

            match outcome.action:
                case OutcomeAction.HEAL:
                    new_hp = min(
                        player.current_hp + outcome.amount,
                        player.major_stats.hp,
                    )
                    total_healing += new_hp - player.current_hp
                    player = replace(player, current_hp=new_hp)

                case OutcomeAction.DAMAGE:
                    new_hp = max(0, player.current_hp - outcome.amount)
                    total_damage += outcome.amount
                    player = replace(player, current_hp=new_hp)

                case OutcomeAction.RESTORE_ENERGY:
                    new_energy = min(
                        player.current_energy + outcome.amount,
                        player.major_stats.energy,
                    )
                    player = replace(player, current_energy=new_energy)

                case OutcomeAction.DRAIN_ENERGY:
                    new_energy = max(0, player.current_energy - outcome.amount)
                    player = replace(player, current_energy=new_energy)

                case OutcomeAction.GIVE_XP:
                    total_xp += outcome.amount
                    base = self._base_stats.get(player.player_class)
                    if base is not None:
                        player = apply_xp(
                            player, outcome.amount, self._progression, base,
                        )
                    else:
                        player = replace(player, xp=player.xp + outcome.amount)

                case OutcomeAction.APPLY_EFFECT:
                    if outcome.effect_id is not None:
                        player = replace(
                            player,
                            active_effects=player.active_effects + (outcome.effect_id,),
                        )

                case OutcomeAction.START_COMBAT:
                    pass  # Handled by resolve_event caller

                case (OutcomeAction.GIVE_ITEM
                      | OutcomeAction.GIVE_GOLD
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
        return replace(state, players=updated_players, run_stats=new_stats)
