from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from game.combat.skill_modifiers import ModifierInstance
from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats
from game.core.data_loader import load_classes, load_progression
from game.core.game_models import PlayerInfo
from game.session.factories import build_player_from_saved

if TYPE_CHECKING:
    from game_service import GameService


class LobbySelectionMode(Enum):
    UNSET = "unset"
    SAVED = "saved"
    NEW = "new"


@dataclass(frozen=True)
class SavedCharacterSummary:
    character_id: int
    class_id: str
    level: int
    xp: int


@dataclass(frozen=True)
class CharacterRecord:
    character_id: int
    tg_id: int
    class_id: str
    level: int
    xp: int
    skills: tuple[str, ...]
    skill_modifiers: tuple[ModifierInstance, ...]
    inventory: dict[str, int]


@dataclass
class LobbyPlayer:
    tg_user_id: int
    display_name: str
    selection_mode: LobbySelectionMode = LobbySelectionMode.UNSET
    selected_character_id: int | None = None
    selected_class_id: str | None = None
    available_characters: tuple[SavedCharacterSummary, ...] = ()

    @property
    def is_ready(self) -> bool:
        if self.selection_mode == LobbySelectionMode.SAVED:
            return self.selected_character_id is not None
        if self.selection_mode == LobbySelectionMode.NEW:
            return self.selected_class_id is not None
        return False


@dataclass
class LobbySession:
    session_id: str
    players: dict[int, LobbyPlayer] = field(default_factory=dict)


class CharacterRepository(Protocol):
    async def get_user_characters(self, tg_id: int) -> list[SavedCharacterSummary]: ...

    async def get_character(self, character_id: int) -> CharacterRecord: ...

    async def create_character(
        self,
        tg_id: int,
        class_id: str,
        skills: tuple[str, ...],
        level: int = 1,
        xp: int = 0,
        inventory: dict[str, int] | None = None,
    ) -> CharacterRecord: ...

    async def save_character_progress(
        self,
        character_id: int,
        level: int,
        xp: int,
        skills: tuple[str, ...],
        skill_modifiers: tuple[ModifierInstance, ...],
    ) -> None: ...


@dataclass(frozen=True)
class LaunchPayload:
    player_infos: tuple[PlayerInfo, ...]
    players: tuple[PlayerCharacter, ...]


def _build_base_stats_map() -> dict[str, MajorStats]:
    classes = load_classes()
    result: dict[str, MajorStats] = {}
    for class_id, cls in classes.items():
        result[class_id] = MajorStats(
            attack=int(cls.major_stats["attack"]),
            hp=int(cls.major_stats["hp"]),
            speed=int(cls.major_stats["speed"]),
            crit_chance=cls.major_stats["crit_chance"],
            crit_dmg=cls.major_stats["crit_dmg"],
            resistance=int(cls.major_stats.get("resistance", 0)),
            energy=int(cls.major_stats.get("energy", 50)),
            mastery=int(cls.major_stats.get("mastery", 0)),
        )
    return result


class LobbyManager:
    """Owns the pre-run lobby flow.

    This manager is intentionally independent from Telegram handlers and from
    GameService's current in-memory session implementation. It tracks joined
    players, their saved/new character choice, and can materialize ready
    runtime players for launch once integration points exist.
    """

    def __init__(self, chars_db: CharacterRepository) -> None:
        self._chars_db = chars_db
        self._lobbies: dict[str, LobbySession] = {}
        self._progression = load_progression()
        self._base_stats = _build_base_stats_map()

    def has_lobby(self, session_id: str) -> bool:
        return session_id in self._lobbies

    def remove_lobby(self, session_id: str) -> None:
        self._lobbies.pop(session_id, None)

    def get_lobby(self, session_id: str) -> LobbySession:
        lobby = self._lobbies.get(session_id)
        if lobby is None:
            raise ValueError("No active lobby")
        return lobby

    async def create_lobby(
        self,
        session_id: str,
        tg_user_id: int,
        display_name: str,
    ) -> LobbySession:
        if session_id in self._lobbies:
            raise ValueError("Lobby already exists for this chat")

        lobby = LobbySession(session_id=session_id)
        lobby.players[tg_user_id] = LobbyPlayer(
            tg_user_id=tg_user_id,
            display_name=display_name,
        )
        self._lobbies[session_id] = lobby
        await self.refresh_player_characters(session_id, tg_user_id)
        return lobby

    async def join_lobby(
        self,
        session_id: str,
        tg_user_id: int,
        display_name: str,
    ) -> LobbySession:
        lobby = self.get_lobby(session_id)
        if tg_user_id in lobby.players:
            raise ValueError("Player already joined this lobby")

        lobby.players[tg_user_id] = LobbyPlayer(
            tg_user_id=tg_user_id,
            display_name=display_name,
        )
        await self.refresh_player_characters(session_id, tg_user_id)
        return lobby

    async def refresh_player_characters(
        self,
        session_id: str,
        tg_user_id: int,
    ) -> LobbyPlayer:
        lobby = self.get_lobby(session_id)
        player = self._get_player(lobby, tg_user_id)
        available = await self._chars_db.get_user_characters(tg_user_id)
        player.available_characters = tuple(available)

        if (
            player.selection_mode == LobbySelectionMode.SAVED
            and player.selected_character_id is not None
            and not any(
                char.character_id == player.selected_character_id
                for char in player.available_characters
            )
        ):
            player.selection_mode = LobbySelectionMode.UNSET
            player.selected_character_id = None

        return player

    def choose_saved_character(
        self,
        session_id: str,
        tg_user_id: int,
        character_id: int,
    ) -> None:
        lobby = self.get_lobby(session_id)
        player = self._get_player(lobby, tg_user_id)

        if not any(
            char.character_id == character_id for char in player.available_characters
        ):
            raise ValueError("Character does not belong to this player")

        player.selection_mode = LobbySelectionMode.SAVED
        player.selected_character_id = character_id
        player.selected_class_id = None

    def choose_create_new(self, session_id: str, tg_user_id: int) -> None:
        lobby = self.get_lobby(session_id)
        player = self._get_player(lobby, tg_user_id)
        player.selection_mode = LobbySelectionMode.NEW
        player.selected_character_id = None
        player.selected_class_id = None

    def choose_new_class(
        self,
        session_id: str,
        tg_user_id: int,
        class_id: str,
    ) -> None:
        if class_id not in load_classes():
            raise ValueError(f"Unknown class: {class_id}")

        lobby = self.get_lobby(session_id)
        player = self._get_player(lobby, tg_user_id)
        if player.selection_mode != LobbySelectionMode.NEW:
            raise ValueError("Player is not creating a new character")

        player.selected_class_id = class_id

    def all_players_ready(self, session_id: str) -> bool:
        lobby = self.get_lobby(session_id)
        return bool(lobby.players) and all(
            player.is_ready for player in lobby.players.values()
        )

    async def build_launch_payload(self, session_id: str) -> LaunchPayload:
        lobby = self.get_lobby(session_id)
        if not self.all_players_ready(session_id):
            raise ValueError("Not all lobby players are ready")

        player_infos: list[PlayerInfo] = []
        players: list[PlayerCharacter] = []

        for tg_user_id, lobby_player in lobby.players.items():
            if lobby_player.selection_mode == LobbySelectionMode.SAVED:
                if lobby_player.selected_character_id is None:
                    raise ValueError("Saved character is not selected")
                record = await self._chars_db.get_character(
                    lobby_player.selected_character_id,
                )
            elif lobby_player.selection_mode == LobbySelectionMode.NEW:
                if lobby_player.selected_class_id is None:
                    raise ValueError("New character class is not selected")
                cls = load_classes()[lobby_player.selected_class_id]
                record = await self._chars_db.create_character(
                    tg_id=tg_user_id,
                    class_id=lobby_player.selected_class_id,
                    skills=tuple(cls.starting_skills),
                    level=1,
                    xp=0,
                    inventory={},
                )
            else:
                raise ValueError("Player has not selected a character")

            runtime_player = build_player_from_saved(
                record,
                self._progression,
                self._base_stats,
            )
            player_infos.append(PlayerInfo(
                entity_id=str(record.character_id),
                tg_user_id=tg_user_id,
                display_name=lobby_player.display_name,
                class_id=record.class_id,
            ))
            players.append(runtime_player)

        return LaunchPayload(
            player_infos=tuple(player_infos),
            players=tuple(players),
        )

    async def launch_game(
        self,
        session_id: str,
        game_service: GameService,
    ) -> None:
        payload = await self.build_launch_payload(session_id)

        launch_session = getattr(game_service, "launch_session", None)
        if launch_session is None:
            raise NotImplementedError(
                "GameService.launch_session() must be implemented before "
                "LobbyManager.launch_game() can be used.",
            )

        launch_session(
            session_id=session_id,
            player_infos=list(payload.player_infos),
            players=list(payload.players),
        )

    @staticmethod
    def _get_player(lobby: LobbySession, tg_user_id: int) -> LobbyPlayer:
        player = lobby.players.get(tg_user_id)
        if player is None:
            raise ValueError("Player is not in this lobby")
        return player
