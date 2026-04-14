import asyncio
from dataclasses import replace

from bot.handlers import game as game_handler
from bot.tools.run_persistence import persist_victory_progress
from game.combat.skill_modifiers import ModifierInstance
from game.core.enums import SessionEndReason
from game.session.models import RunStats

from tests.unit.conftest import make_warrior


class _FakeRepo:
    def __init__(self):
        self.saved: list[dict] = []

    async def save_character_progress(
        self,
        character_id: int,
        level: int,
        xp: int,
        skills: tuple[str, ...],
        skill_modifiers: tuple[ModifierInstance, ...],
    ) -> None:
        self.saved.append(
            {
                "character_id": character_id,
                "level": level,
                "xp": xp,
                "skills": skills,
                "skill_modifiers": tuple(
                    (modifier.modifier_id, modifier.stack_count)
                    for modifier in skill_modifiers
                ),
            },
        )


class _FakeSession:
    def __init__(self, state):
        self.state = state


class _FakeGameService:
    def __init__(self, state):
        self._state = state
        self.removed = False

    def has_session(self, session_id: str) -> bool:
        return self._state is not None

    def _get_session(self, session_id: str):
        return _FakeSession(self._state)

    def get_session_phase(self, session_id: str):
        return object() if self._state is not None else None

    def get_run_stats(self, session_id: str):
        return self._state.run_stats

    def remove_session(self, session_id: str) -> None:
        self.removed = True


class _FakeLobbyManager:
    def has_lobby(self, session_id: str) -> bool:
        return False

    def remove_lobby(self, session_id: str) -> None:
        raise AssertionError("remove_lobby should not be called")


class _FakeMessage:
    class _Chat:
        id = 123

    chat = _Chat()

    def __init__(self):
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


def test_persist_victory_progress_saves_all_party_members(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(
        "bot.tools.run_persistence.UserCharactersData",
        lambda pool: repo,
    )

    player_one = replace(
        make_warrior("101"),
        level=4,
        xp=420,
        skills=("slash", "cleave", "battle_cry"),
        skill_modifiers=(ModifierInstance("slash_power", 2),),
    )
    player_two = replace(
        make_warrior("202"),
        current_hp=0,
        level=3,
        xp=275,
        skill_modifiers=(ModifierInstance("battle_hardened", 1),),
    )
    state = type(
        "State",
        (),
        {
            "end_reason": SessionEndReason.MAX_DEPTH,
            "players": (player_one, player_two),
            "run_stats": object(),
        },
    )()
    game_service = _FakeGameService(state)

    asyncio.run(persist_victory_progress(game_service, "session-1", object()))

    assert repo.saved == [
        {
            "character_id": 101,
            "level": 4,
            "xp": 420,
            "skills": ("slash", "cleave", "battle_cry"),
            "skill_modifiers": (("slash_power", 2),),
        },
        {
            "character_id": 202,
            "level": 3,
            "xp": 275,
            "skills": ("slash",),
            "skill_modifiers": (("battle_hardened", 1),),
        },
    ]


def test_persist_victory_progress_skips_non_victory_states(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(
        "bot.tools.run_persistence.UserCharactersData",
        lambda pool: repo,
    )

    for end_reason in (
        SessionEndReason.PARTY_WIPED,
        SessionEndReason.RETREAT,
    ):
        player = replace(make_warrior("101"), level=2, xp=150)
        state = type(
            "State",
            (),
            {
                "end_reason": end_reason,
                "players": (player,),
                "run_stats": object(),
            },
        )()
        game_service = _FakeGameService(state)
        asyncio.run(persist_victory_progress(game_service, "session-1", object()))

    assert repo.saved == []


def test_leave_command_does_not_persist_character_progress(monkeypatch):
    monkeypatch.setattr(game_handler, "_get_lobby_manager", lambda db_pool: _FakeLobbyManager())

    state = type("State", (), {"run_stats": RunStats()})()
    game_service = _FakeGameService(state)
    message = _FakeMessage()

    asyncio.run(game_handler.cmd_flee(message, game_service, object()))

    assert game_service.removed is True
    assert any("The party flees!" in answer for answer in message.answers)
