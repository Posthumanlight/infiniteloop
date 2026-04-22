from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Protocol

from game.character.player_character import PlayerCharacter
from game.combat.models import CombatState
from game.core.game_models import (
    CharacterSheet,
    InventorySnapshot,
    PlayerInfo,
)
from game.items.dissolve import dissolve_value_for_items
from game.items.items import ItemInstance
from game.items.equipment_effects import get_effective_player_major_stat
from game.session.factories import build_player, build_player_from_saved
from game.session.lobby_manager import (
    CharacterRepository,
    LobbyManager,
    LobbyPlayer,
    LobbySelectionMode,
    LobbySession,
    PlayerSaveOrigin,
    SavedCharacterSummary,
    _build_base_stats_map,
)
from game.session.models import ActiveSession
from game.session.session_manager import SessionManager
from game.core.data_loader import load_item_dissolve_constants, load_progression


class ActiveSessionProvider(Protocol):
    def has_active_session(self, session_id: str) -> bool: ...

    def get_active_session(self, session_id: str) -> ActiveSession: ...

    def get_session_players(self, session_id: str) -> list[PlayerInfo]: ...


class CharacterViewBuilder(Protocol):
    def sheet_for_player(
        self,
        info: PlayerInfo,
        player: PlayerCharacter,
        *,
        combat_state: CombatState | None = None,
    ) -> CharacterSheet: ...

    def sheet_from_class_template(
        self,
        info: PlayerInfo,
        class_id: str,
    ) -> CharacterSheet: ...

    def inventory_for_player(
        self,
        player: PlayerCharacter,
        *,
        in_combat: bool,
    ) -> InventorySnapshot: ...


@dataclass(frozen=True)
class CharacterTarget:
    kind: Literal["run", "lobby", "saved"]
    tg_user_id: int
    session_id: str | None = None
    entity_id: str | None = None
    character_id: int | None = None


@dataclass(frozen=True)
class CharacterSelection:
    target: CharacterTarget
    sheet: CharacterSheet
    inventory: InventorySnapshot


class LobbyService(ActiveSessionProvider):
    """Owns lobby lifecycle, active run sessions, and non-combat character access."""

    def __init__(
        self,
        chars_db: CharacterRepository,
        *,
        view_builder: CharacterViewBuilder | None = None,
    ) -> None:
        self._chars_db = chars_db
        self._lobby_manager = LobbyManager(chars_db)
        self._active_sessions: dict[str, ActiveSession] = {}
        self._selected_cache: dict[tuple[str, int], PlayerCharacter] = {}
        self._view_builder = view_builder
        self._progression = load_progression()
        self._base_stats = _build_base_stats_map()

    @property
    def lobby_manager(self) -> LobbyManager:
        return self._lobby_manager

    def set_view_builder(self, view_builder: CharacterViewBuilder) -> None:
        self._view_builder = view_builder

    def has_active_session(self, session_id: str) -> bool:
        return session_id in self._active_sessions

    def has_session(self, session_id: str) -> bool:
        return self.has_active_session(session_id)

    def has_lobby(self, session_id: str) -> bool:
        return self._lobby_manager.has_lobby(session_id)

    def get_active_session(self, session_id: str) -> ActiveSession:
        session = self._active_sessions.get(session_id)
        if session is None:
            raise ValueError("No active session")
        return session

    def get_lobby(self, session_id: str) -> LobbySession:
        return self._lobby_manager.get_lobby(session_id)

    def get_session_players(self, session_id: str) -> list[PlayerInfo]:
        return list(self.get_active_session(session_id).players.values())

    async def create_lobby(
        self,
        session_id: str,
        tg_user_id: int,
        display_name: str,
    ) -> LobbySession:
        if self.has_active_session(session_id):
            raise ValueError("Session already exists for this chat")
        return await self._lobby_manager.create_lobby(
            session_id,
            tg_user_id,
            display_name,
        )

    async def join_lobby(
        self,
        session_id: str,
        tg_user_id: int,
        display_name: str,
    ) -> LobbySession:
        if self.has_active_session(session_id):
            raise ValueError("The run has already started in this chat")
        return await self._lobby_manager.join_lobby(
            session_id,
            tg_user_id,
            display_name,
        )

    async def refresh_player_characters(
        self,
        session_id: str,
        tg_user_id: int,
    ) -> LobbyPlayer:
        player = await self._lobby_manager.refresh_player_characters(
            session_id,
            tg_user_id,
        )
        self._selected_cache.pop((session_id, tg_user_id), None)
        return player

    def choose_saved_character(
        self,
        session_id: str,
        tg_user_id: int,
        character_id: int,
    ) -> None:
        self._lobby_manager.choose_saved_character(
            session_id,
            tg_user_id,
            character_id,
        )
        self._selected_cache.pop((session_id, tg_user_id), None)

    def choose_create_new(self, session_id: str, tg_user_id: int) -> None:
        self._lobby_manager.choose_create_new(session_id, tg_user_id)
        self._selected_cache.pop((session_id, tg_user_id), None)

    def choose_new_class(
        self,
        session_id: str,
        tg_user_id: int,
        class_id: str,
    ) -> None:
        self._lobby_manager.choose_new_class(session_id, tg_user_id, class_id)
        self._selected_cache.pop((session_id, tg_user_id), None)

    def all_players_ready(self, session_id: str) -> bool:
        return self._lobby_manager.all_players_ready(session_id)

    async def launch_run(self, session_id: str) -> None:
        if self.has_active_session(session_id):
            raise ValueError("Session already exists for this chat")

        payload = await self._build_launch_payload_from_lobby(session_id)
        manager = SessionManager(seed=hash(session_id) & 0x7FFFFFFF)
        state = manager.start_run(session_id, list(payload.players))
        state = manager.generate_choices(state)
        self._active_sessions[session_id] = ActiveSession(
            session_id=session_id,
            players={info.entity_id: info for info in payload.player_infos},
            manager=manager,
            state=state,
            save_origins={
                origin.entity_id: origin for origin in payload.save_origins
            },
        )
        self._lobby_manager.remove_lobby(session_id)
        self._drop_lobby_cache(session_id)

    def close_session(self, session_id: str) -> None:
        self._lobby_manager.remove_lobby(session_id)
        self._active_sessions.pop(session_id, None)
        self._drop_lobby_cache(session_id)

    def remove_session(self, session_id: str) -> None:
        self.close_session(session_id)

    async def list_user_characters(
        self,
        tg_user_id: int,
    ) -> tuple[SavedCharacterSummary, ...]:
        return tuple(await self._chars_db.get_user_characters(tg_user_id))

    def target_for_session_user(
        self,
        session_id: str,
        tg_user_id: int,
    ) -> CharacterTarget | None:
        if self.has_active_session(session_id):
            session = self.get_active_session(session_id)
            for info in session.players.values():
                if info.tg_user_id == tg_user_id:
                    return CharacterTarget(
                        kind="run",
                        tg_user_id=tg_user_id,
                        session_id=session_id,
                        entity_id=info.entity_id,
                    )
            return None

        if not self.has_lobby(session_id):
            return None

        lobby = self.get_lobby(session_id)
        lobby_player = lobby.players.get(tg_user_id)
        if lobby_player is None:
            return None
        return self._target_for_lobby_player(session_id, lobby_player)

    async def get_character_selection(
        self,
        target: CharacterTarget,
    ) -> CharacterSelection:
        info, player, combat_state, in_combat = await self._resolve_target_player(target)
        builder = self._require_view_builder()
        return CharacterSelection(
            target=target,
            sheet=builder.sheet_for_player(
                info,
                player,
                combat_state=combat_state,
            ),
            inventory=builder.inventory_for_player(player, in_combat=in_combat),
        )

    async def get_character_sheet(
        self,
        target: CharacterTarget,
    ) -> CharacterSheet:
        selection = await self.get_character_selection(target)
        return selection.sheet

    async def get_inventory(
        self,
        target: CharacterTarget,
    ) -> InventorySnapshot:
        selection = await self.get_character_selection(target)
        return selection.inventory

    async def equip_item(
        self,
        target: CharacterTarget,
        instance_id: str,
        relic_slot: int | None = None,
    ) -> None:
        info, player, _combat_state, in_combat = await self._resolve_target_player(
            target,
        )
        self._assert_editable_target(target, in_combat=in_combat)
        updated = replace(
            player,
            inventory=player.inventory.equip(instance_id, relic_slot=relic_slot),
        )
        await self._replace_target_player(target, info, self._reconcile_resources(updated))

    async def unequip_item(
        self,
        target: CharacterTarget,
        instance_id: str,
    ) -> None:
        info, player, _combat_state, in_combat = await self._resolve_target_player(
            target,
        )
        self._assert_editable_target(target, in_combat=in_combat)
        updated = replace(player, inventory=player.inventory.unequip(instance_id))
        await self._replace_target_player(target, info, self._reconcile_resources(updated))

    async def preview_dissolve_inventory_items(
        self,
        target: CharacterTarget,
        instance_ids: tuple[str, ...],
    ) -> tuple[tuple[ItemInstance, ...], int]:
        _info, player, _combat_state, in_combat = await self._resolve_target_player(
            target,
        )
        self._assert_editable_target(target, in_combat=in_combat)
        items = player.inventory.get_dissolvable_items(instance_ids)
        total = dissolve_value_for_items(items, load_item_dissolve_constants())
        return items, total

    async def dissolve_inventory_items(
        self,
        target: CharacterTarget,
        instance_ids: tuple[str, ...],
    ) -> tuple[PlayerCharacter, tuple[ItemInstance, ...], int]:
        info, player, _combat_state, in_combat = await self._resolve_target_player(
            target,
        )
        self._assert_editable_target(target, in_combat=in_combat)
        inventory, dissolved = player.inventory.dissolve_items(instance_ids)
        total = dissolve_value_for_items(dissolved, load_item_dissolve_constants())
        updated = self._reconcile_resources(replace(player, inventory=inventory))
        await self._replace_target_player(target, info, updated)
        return updated, dissolved, total

    async def _build_launch_payload_from_lobby(self, session_id: str):
        payload = await self._lobby_manager.build_launch_payload(session_id)
        players = tuple(
            self._selected_cache.get((session_id, info.tg_user_id), player)
            for info, player in zip(payload.player_infos, payload.players)
        )
        return replace(payload, players=players)

    async def _resolve_target_player(
        self,
        target: CharacterTarget,
    ) -> tuple[PlayerInfo, PlayerCharacter, CombatState | None, bool]:
        if target.kind == "run":
            return self._resolve_active_player(target)
        if target.kind == "lobby":
            return await self._resolve_lobby_player(target)
        if target.kind == "saved":
            return await self._resolve_saved_player(target)
        raise ValueError("Unsupported character target")

    def _resolve_active_player(
        self,
        target: CharacterTarget,
    ) -> tuple[PlayerInfo, PlayerCharacter, CombatState | None, bool]:
        if target.session_id is None or target.entity_id is None:
            raise ValueError("Invalid run character target")
        session = self.get_active_session(target.session_id)
        info = session.players.get(target.entity_id)
        if info is None or info.tg_user_id != target.tg_user_id:
            raise ValueError("You are not in the current game")
        if session.state is None:
            raise ValueError("No active run")
        player = next(
            (
                candidate
                for candidate in session.state.players
                if candidate.entity_id == target.entity_id
            ),
            None,
        )
        if player is None:
            raise ValueError("Player is not part of this run")
        combat_state = session.state.combat
        in_combat = combat_state is not None
        return info, player, combat_state, in_combat

    async def _resolve_lobby_player(
        self,
        target: CharacterTarget,
    ) -> tuple[PlayerInfo, PlayerCharacter, None, bool]:
        if target.session_id is None:
            raise ValueError("Invalid lobby character target")
        lobby = self.get_lobby(target.session_id)
        lobby_player = lobby.players.get(target.tg_user_id)
        if lobby_player is None:
            raise ValueError("You are not in this lobby")

        selected_target = self._target_for_lobby_player(
            target.session_id,
            lobby_player,
        )
        player = await self._get_or_build_lobby_player(
            target.session_id,
            lobby_player,
        )
        return (
            self._player_info_for_lobby_player(lobby_player, selected_target),
            player,
            None,
            False,
        )

    async def _resolve_saved_player(
        self,
        target: CharacterTarget,
    ) -> tuple[PlayerInfo, PlayerCharacter, None, bool]:
        if target.character_id is None:
            raise ValueError("Invalid saved character target")
        record = await self._chars_db.get_character(target.character_id)
        if record.tg_id != target.tg_user_id:
            raise ValueError("Character does not belong to this player")
        player = build_player_from_saved(record, self._progression, self._base_stats)
        return (
            PlayerInfo(
                entity_id=player.entity_id,
                tg_user_id=target.tg_user_id,
                display_name=record.character_name or f"#{record.character_id}",
                class_id=record.class_id,
            ),
            player,
            None,
            False,
        )

    async def _get_or_build_lobby_player(
        self,
        session_id: str,
        lobby_player: LobbyPlayer,
    ) -> PlayerCharacter:
        cache_key = (session_id, lobby_player.tg_user_id)
        cached = self._selected_cache.get(cache_key)
        if cached is not None:
            return cached

        if lobby_player.selection_mode == LobbySelectionMode.SAVED:
            if lobby_player.selected_character_id is None:
                raise ValueError("Choose a character first")
            record = await self._chars_db.get_character(
                lobby_player.selected_character_id,
            )
            if record.tg_id != lobby_player.tg_user_id:
                raise ValueError("Character does not belong to this player")
            player = build_player_from_saved(record, self._progression, self._base_stats)
        elif lobby_player.selection_mode == LobbySelectionMode.NEW:
            if lobby_player.selected_class_id is None:
                raise ValueError("Choose a class first")
            player = build_player(
                lobby_player.selected_class_id,
                entity_id=f"tmp:{lobby_player.tg_user_id}",
            )
        else:
            raise ValueError("Choose a character first")

        self._selected_cache[cache_key] = player
        return player

    async def _replace_target_player(
        self,
        target: CharacterTarget,
        info: PlayerInfo,
        player: PlayerCharacter,
    ) -> None:
        if target.kind == "run":
            if target.session_id is None:
                raise ValueError("Invalid run character target")
            session = self.get_active_session(target.session_id)
            if session.state is None:
                raise ValueError("No active run")
            session.state = replace(
                session.state,
                players=tuple(
                    player if current.entity_id == player.entity_id else current
                    for current in session.state.players
                ),
            )
            return

        if target.kind == "lobby":
            if target.session_id is None:
                raise ValueError("Invalid lobby character target")
            self._selected_cache[(target.session_id, target.tg_user_id)] = player
            if target.character_id is not None:
                await self._persist_saved_player(target.character_id, player)
            return

        if target.kind == "saved":
            if target.character_id is None:
                raise ValueError("Invalid saved character target")
            await self._persist_saved_player(target.character_id, player)
            return

        raise ValueError("Unsupported character target")

    async def _persist_saved_player(
        self,
        character_id: int,
        player: PlayerCharacter,
    ) -> None:
        record = await self._chars_db.get_character(character_id)
        await self._chars_db.save_character_progress(
            character_id=character_id,
            character_name=record.character_name or f"#{character_id}",
            level=player.level,
            xp=player.xp,
            skills=player.skills,
            skill_modifiers=player.skill_modifiers,
            inventory=player.inventory,
            flags=player.flags,
        )

    def _target_for_lobby_player(
        self,
        session_id: str,
        lobby_player: LobbyPlayer,
    ) -> CharacterTarget:
        if lobby_player.selection_mode == LobbySelectionMode.SAVED:
            if lobby_player.selected_character_id is None:
                raise ValueError("Choose a character first")
            return CharacterTarget(
                kind="lobby",
                tg_user_id=lobby_player.tg_user_id,
                session_id=session_id,
                entity_id=str(lobby_player.selected_character_id),
                character_id=lobby_player.selected_character_id,
            )
        if lobby_player.selection_mode == LobbySelectionMode.NEW:
            if lobby_player.selected_class_id is None:
                raise ValueError("Choose a class first")
            return CharacterTarget(
                kind="lobby",
                tg_user_id=lobby_player.tg_user_id,
                session_id=session_id,
                entity_id=f"tmp:{lobby_player.tg_user_id}",
            )
        raise ValueError("Choose a character first")

    @staticmethod
    def _player_info_for_lobby_player(
        lobby_player: LobbyPlayer,
        target: CharacterTarget,
    ) -> PlayerInfo:
        if target.entity_id is None:
            raise ValueError("Invalid lobby character target")
        class_id: str | None = None
        if lobby_player.selection_mode == LobbySelectionMode.SAVED:
            selected = next(
                (
                    char
                    for char in lobby_player.available_characters
                    if char.character_id == lobby_player.selected_character_id
                ),
                None,
            )
            class_id = selected.class_id if selected is not None else None
        elif lobby_player.selection_mode == LobbySelectionMode.NEW:
            class_id = lobby_player.selected_class_id
        return PlayerInfo(
            entity_id=target.entity_id,
            tg_user_id=lobby_player.tg_user_id,
            display_name=lobby_player.display_name,
            class_id=class_id,
        )

    def _require_view_builder(self) -> CharacterViewBuilder:
        if self._view_builder is None:
            raise RuntimeError("Character view builder is not configured")
        return self._view_builder

    @staticmethod
    def _assert_editable_target(
        target: CharacterTarget,
        *,
        in_combat: bool,
    ) -> None:
        if target.kind == "run" and in_combat:
            raise ValueError("Cannot change equipment during combat")

    @staticmethod
    def _reconcile_resources(player: PlayerCharacter) -> PlayerCharacter:
        max_hp = int(get_effective_player_major_stat(player, "hp"))
        max_energy = int(get_effective_player_major_stat(player, "energy"))
        return replace(
            player,
            current_hp=min(player.current_hp, max_hp),
            current_energy=min(player.current_energy, max_energy),
        )

    def _drop_lobby_cache(self, session_id: str) -> None:
        self._selected_cache = {
            key: value
            for key, value in self._selected_cache.items()
            if key[0] != session_id
        }
