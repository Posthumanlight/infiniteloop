import asyncio

from bot.handlers import game as game_handler
from bot.tools.save_flow import clear_save_flow, get_save_flow, start_save_flow
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
        self.removed = False

    def has_session(self, session_id: str) -> bool:
        return self._session is not None

    def _get_session(self, session_id: str):
        return self._session

    def get_session_phase(self, session_id: str):
        return object() if self._session is not None else None

    def get_run_stats(self, session_id: str):
        return self._session.state.run_stats

    def remove_session(self, session_id: str) -> None:
        self.removed = True
        self._session = None


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
    assert flow.choices["tmp:2"].is_transient is True
    clear_save_flow(sid)
    assert get_save_flow(sid) is None


def test_leave_command_closes_pending_save_flow(monkeypatch):
    monkeypatch.setattr(game_handler, "_get_lobby_manager", lambda db_pool: _FakeLobbyManager())
    monkeypatch.setattr(game_handler, "get_save_flow", lambda sid: object())
    clear_called = {"value": False}

    def _clear(_sid: str) -> None:
        clear_called["value"] = True

    monkeypatch.setattr(game_handler, "clear_save_flow", _clear)

    state = type("State", (), {"run_stats": RunStats()})()
    session = _FakeSession(players={}, save_origins={}, state=state)
    game_service = _FakeGameService(session)
    message = _FakeMessage()

    asyncio.run(game_handler.cmd_flee(message, game_service, object()))

    assert clear_called["value"] is True
    assert game_service.removed is True
    assert any("Pending save prompts were closed" in answer for answer in message.answers)
