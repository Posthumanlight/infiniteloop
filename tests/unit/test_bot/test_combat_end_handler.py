from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import combat as combat_handler


class _State:
    async def update_data(self, **kwargs) -> None:
        return None

    async def set_state(self, state) -> None:
        return None


class _GameService:
    def consume_pending_loot(self, session_id: str):
        return None

    def get_session_phase(self, session_id: str):
        return None


class _LobbyService:
    def __init__(self) -> None:
        self.closed = False

    def close_session(self, session_id: str) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_combat_end_handler_sends_combined_end_message_without_batch(monkeypatch):
    callback = SimpleNamespace(
        answer=AsyncMock(),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=123),
            answer=AsyncMock(),
        ),
    )
    batch = SimpleNamespace(combat_ended=True)
    lobby_service = _LobbyService()
    batch_renderer_called = False

    def _render_turn_batch(*args, **kwargs):
        nonlocal batch_renderer_called
        batch_renderer_called = True
        return "BATCH"

    monkeypatch.setattr(combat_handler, "render_turn_batch", _render_turn_batch)
    monkeypatch.setattr(combat_handler, "render_combat_end", lambda *_: "END")

    await combat_handler._render_batch_and_prompt(
        callback,
        _GameService(),
        lobby_service,
        "123",
        batch,
        {},
        _State(),
        object(),
    )

    callback.message.answer.assert_awaited_once_with("END")
    assert batch_renderer_called is False
    assert lobby_service.closed is True
