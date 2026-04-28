import asyncio
from types import SimpleNamespace

from bot.handlers import game as game_handler
from bot.tools.save_flow import clear_save_flow, get_save_flow, start_save_flow
from bot.bot_state import GameStates
from game.core.game_models import PlayerInfo
from game.session.lobby_manager import PlayerSaveOrigin
from game.session.models import RunStats


class _FakeSession:
    def __init__(self, players, save_origins, state=None):
        self.players = players
        self.save_origins = save_origins
        self.state = state


class _FakeGameService:
    def __init__(self, session=None):
        self._session = session

    def has_session(self, session_id: str) -> bool:
        return self._session is not None

    def get_active_session(self, session_id: str):
        return self._session

    def _get_session(self, session_id: str):
        return self._session

    def get_session_phase(self, session_id: str):
        return object() if self._session is not None else None

    def get_run_stats(self, session_id: str):
        return self._session.state.run_stats


class _FakeLobbyService:
    def __init__(self, session=None):
        self._session = session
        self.closed = False

    def has_lobby(self, session_id: str) -> bool:
        return False

    def has_active_session(self, session_id: str) -> bool:
        return self._session is not None and not self.closed

    def get_active_session(self, session_id: str):
        return self._session

    def close_session(self, session_id: str) -> None:
        self.closed = True


class _FakeMessage:
    class _Chat:
        id = 123

    chat = _Chat()

    def __init__(self):
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=1)

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


class _FakeCallback:
    def __init__(self, data: str, user_id: int = 1):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()
        self.answers: list[tuple[str | None, dict]] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class _FakeState:
    def __init__(self):
        self.states: list[object] = []

    async def set_state(self, state) -> None:
        self.states.append(state)


class _FakeCharactersData:
    def __init__(self):
        self.saved_progress: list[dict] = []
        self.created_characters: list[dict] = []
        self.name_exists = False

    async def character_name_exists(self, character_name: str, exclude_character_id=None):
        return self.name_exists

    async def save_character_progress(self, **kwargs):
        self.saved_progress.append(kwargs)

    async def create_saved_character(self, **kwargs):
        self.created_characters.append(kwargs)


def _runtime_player(entity_id: str, player_class: str = "warrior"):
    return SimpleNamespace(
        entity_id=entity_id,
        player_class=player_class,
        skills=("slash",),
        passive_skills=(),
        level=4,
        xp=320,
        skill_modifiers=(),
        inventory=None,
        flags={},
    )


def _session_with_player(
    entity_id: str,
    tg_user_id: int,
    *,
    character_id: int | None,
    character_name: str | None,
):
    players = {
        entity_id: PlayerInfo(
            entity_id=entity_id,
            tg_user_id=tg_user_id,
            display_name="A",
            class_id="warrior",
        ),
    }
    origins = {
        entity_id: PlayerSaveOrigin(
            tg_user_id=tg_user_id,
            entity_id=entity_id,
            character_id=character_id,
            character_name=character_name,
        ),
    }
    state = SimpleNamespace(
        players=[_runtime_player(entity_id)],
        run_stats=RunStats(),
    )
    return _FakeSession(players=players, save_origins=origins, state=state)


def test_start_save_flow_tracks_saved_and_transient_players():
    sid = "123"
    clear_save_flow(sid)
    players = {
        "42": PlayerInfo(entity_id="42", tg_user_id=1, display_name="A", class_id="warrior"),
        "tmp:2": PlayerInfo(entity_id="tmp:2", tg_user_id=2, display_name="B", class_id="mage"),
    }
    origins = {
        "42": PlayerSaveOrigin(
            tg_user_id=1,
            entity_id="42",
            character_id=42,
            character_name="LegacyA",
        ),
        "tmp:2": PlayerSaveOrigin(
            tg_user_id=2,
            entity_id="tmp:2",
        ),
    }
    service = _FakeGameService(_FakeSession(players=players, save_origins=origins))

    flow = start_save_flow(service, sid)

    assert set(flow.choices.keys()) == {"42", "tmp:2"}
    assert flow.choices["42"].is_transient is False
    assert flow.choices["42"].source_character_name == "LegacyA"
    assert flow.choices["42"].existing_character_name == "LegacyA"
    assert flow.choices["tmp:2"].is_transient is True
    assert flow.choices["tmp:2"].existing_character_name is None
    clear_save_flow(sid)
    assert get_save_flow(sid) is None


def test_saved_character_with_existing_name_saves_without_name_prompt(monkeypatch):
    sid = "123"
    clear_save_flow(sid)
    session = _session_with_player(
        "42",
        1,
        character_id=42,
        character_name="LegacyA",
    )
    game_service = _FakeGameService(session)
    lobby_service = _FakeLobbyService(session)
    repo = _FakeCharactersData()
    monkeypatch.setattr(game_handler, "UserCharactersData", lambda pool: repo)
    flow = start_save_flow(lobby_service, sid)
    callback = _FakeCallback("g:save:yes:42")
    state = _FakeState()

    asyncio.run(
        game_handler.cb_save_decision(
            callback,
            game_service,
            lobby_service,
            state,
            object(),
        ),
    )

    choice = flow.choices["42"]
    assert choice.resolved is True
    assert choice.awaiting_name is False
    assert repo.saved_progress == [
        {
            "character_id": 42,
            "character_name": "LegacyA",
            "class_id": "warrior",
            "level": 4,
            "xp": 320,
            "skills": ("slash",),
            "passive_skills": (),
            "skill_modifiers": (),
            "inventory": None,
            "flags": {},
        },
    ]
    assert repo.created_characters == []
    assert callback.answers[-1][0] == "Character saved."
    assert "Character saved." in callback.message.answers
    assert state.states[-1] == GameStates.run_ended
    assert lobby_service.closed is True
    clear_save_flow(sid)


def test_saved_character_without_existing_name_still_prompts_for_name(monkeypatch):
    sid = "123"
    clear_save_flow(sid)
    session = _session_with_player("42", 1, character_id=42, character_name="  ")
    game_service = _FakeGameService(session)
    lobby_service = _FakeLobbyService(session)
    repo = _FakeCharactersData()
    monkeypatch.setattr(game_handler, "UserCharactersData", lambda pool: repo)
    flow = start_save_flow(lobby_service, sid)
    callback = _FakeCallback("g:save:yes:42")
    state = _FakeState()

    asyncio.run(
        game_handler.cb_save_decision(
            callback,
            game_service,
            lobby_service,
            state,
            object(),
        ),
    )

    choice = flow.choices["42"]
    assert choice.resolved is False
    assert choice.awaiting_name is True
    assert repo.saved_progress == []
    assert callback.answers[-1][0] == "Send a character name in chat."
    assert state.states[-1] == GameStates.save_name
    assert lobby_service.closed is False
    clear_save_flow(sid)


def test_transient_character_still_prompts_for_name(monkeypatch):
    sid = "123"
    clear_save_flow(sid)
    session = _session_with_player(
        "tmp:1",
        1,
        character_id=None,
        character_name=None,
    )
    game_service = _FakeGameService(session)
    lobby_service = _FakeLobbyService(session)
    repo = _FakeCharactersData()
    monkeypatch.setattr(game_handler, "UserCharactersData", lambda pool: repo)
    flow = start_save_flow(lobby_service, sid)
    callback = _FakeCallback("g:save:yes:tmp:1")
    state = _FakeState()

    asyncio.run(
        game_handler.cb_save_decision(
            callback,
            game_service,
            lobby_service,
            state,
            object(),
        ),
    )

    choice = flow.choices["tmp:1"]
    assert choice.resolved is False
    assert choice.awaiting_name is True
    assert repo.saved_progress == []
    assert repo.created_characters == []
    assert callback.answers[-1][0] == "Send a character name in chat."
    assert state.states[-1] == GameStates.save_name
    assert lobby_service.closed is False
    clear_save_flow(sid)


def test_save_flow_closes_only_after_all_choices_resolve(monkeypatch):
    sid = "123"
    clear_save_flow(sid)
    players = {
        "42": PlayerInfo(entity_id="42", tg_user_id=1, display_name="A", class_id="warrior"),
        "tmp:2": PlayerInfo(entity_id="tmp:2", tg_user_id=2, display_name="B", class_id="mage"),
    }
    origins = {
        "42": PlayerSaveOrigin(
            tg_user_id=1,
            entity_id="42",
            character_id=42,
            character_name="LegacyA",
        ),
        "tmp:2": PlayerSaveOrigin(tg_user_id=2, entity_id="tmp:2"),
    }
    state_obj = SimpleNamespace(
        players=[_runtime_player("42"), _runtime_player("tmp:2", "mage")],
        run_stats=RunStats(),
    )
    session = _FakeSession(players=players, save_origins=origins, state=state_obj)
    game_service = _FakeGameService(session)
    lobby_service = _FakeLobbyService(session)
    repo = _FakeCharactersData()
    monkeypatch.setattr(game_handler, "UserCharactersData", lambda pool: repo)
    start_save_flow(lobby_service, sid)
    state = _FakeState()

    asyncio.run(
        game_handler.cb_save_decision(
            _FakeCallback("g:save:yes:42", user_id=1),
            game_service,
            lobby_service,
            state,
            object(),
        ),
    )

    assert lobby_service.closed is False

    no_callback = _FakeCallback("g:save:no:tmp:2", user_id=2)
    asyncio.run(
        game_handler.cb_save_decision(
            no_callback,
            game_service,
            lobby_service,
            state,
            object(),
        ),
    )

    assert lobby_service.closed is True
    assert "All save choices resolved. Session closed." in no_callback.message.answers
    clear_save_flow(sid)


def test_leave_command_closes_pending_save_flow(monkeypatch):
    monkeypatch.setattr(game_handler, "get_save_flow", lambda sid: object())
    clear_called = {"value": False}

    def _clear(_sid: str) -> None:
        clear_called["value"] = True

    monkeypatch.setattr(game_handler, "clear_save_flow", _clear)

    state = type("State", (), {"run_stats": RunStats()})()
    session = _FakeSession(players={}, save_origins={}, state=state)
    game_service = _FakeGameService(session)
    lobby_service = _FakeLobbyService(session)
    message = _FakeMessage()

    asyncio.run(game_handler.cmd_flee(message, game_service, lobby_service))

    assert clear_called["value"] is True
    assert lobby_service.closed is True
    assert any("Pending save prompts were closed" in answer for answer in message.answers)
