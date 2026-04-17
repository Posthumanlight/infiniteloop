from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.bot_state import GameStates
from bot.handlers import combat as combat_handler
from game.core.data_loader import SkillData
from game.core.enums import ActionType, EntityType
from game.core.game_models import EntitySnapshot, PlayerInfo


def _make_skill(index: int) -> SkillData:
    return SkillData(
        skill_id=f"skill_{index}",
        name=f"Skill {index}",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=(),
        self_effects=(),
    )


class DummyState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state: str | None = None

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.state = state.state if hasattr(state, "state") else state

    async def get_state(self) -> str | None:
        return self.state


class FakeGameService:
    def __init__(self, skills: list[tuple[SkillData, int]]) -> None:
        self.skills = skills
        self.snapshot = SimpleNamespace(entities={
            "p1": EntitySnapshot(
                entity_id="p1",
                name="Hero",
                entity_type=EntityType.PLAYER,
                current_hp=100,
                max_hp=120,
                current_energy=50,
                max_energy=100,
                is_alive=True,
            ),
        })
        self.players = [
            PlayerInfo(
                entity_id="p1",
                tg_user_id=42,
                display_name="Hero",
                class_id="warrior",
            ),
        ]

    def get_whose_turn(self, session_id: str) -> str:
        return "p1"

    def get_combat_snapshot(self, session_id: str):
        return self.snapshot

    def get_session_players(self, session_id: str):
        return self.players

    def get_available_skills(self, session_id: str, actor_id: str):
        return self.skills

    def has_session(self, session_id: str) -> bool:
        return True

    def is_in_combat(self, session_id: str) -> bool:
        return True


def _make_callback(data: str):
    message = SimpleNamespace(
        chat=SimpleNamespace(id=777),
        answer=AsyncMock(),
        edit_text=AsyncMock(),
    )
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=42),
        message=message,
        answer=AsyncMock(),
    )


def _markup_texts(callback) -> list[list[str]]:
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    return [[button.text for button in row] for row in markup.inline_keyboard]


@pytest.mark.asyncio
async def test_cb_skill_page_clears_stale_selection_and_renders_requested_page(monkeypatch):
    state = DummyState()
    state.data.update(
        pending_skill="slash",
        pending_hit_queue=[0],
        collected_targets=[[0, "e1"]],
        pending_skill_page=0,
    )
    service = FakeGameService([(_make_skill(i), 0) for i in range(1, 9)])
    callback = _make_callback("g:skpg:1")

    monkeypatch.setattr(combat_handler, "entity_id_for_tg_user", lambda *_: "p1")

    await combat_handler.cb_skill_page(callback, service, state)

    assert state.data["pending_skill"] is None
    assert state.data["pending_hit_queue"] == []
    assert state.data["collected_targets"] == []
    assert state.data["pending_skill_page"] is None
    assert state.data["combat_skill_page"] == 1
    assert state.state == GameStates.combat_idle.state
    assert _markup_texts(callback) == [
        ["Skill 6"],
        ["Skill 7"],
        ["Skill 8"],
        ["⏭️ Skip"],
        ["← Prev"],
    ]


@pytest.mark.asyncio
async def test_cb_back_to_skills_clears_target_selection_and_restores_page(monkeypatch):
    state = DummyState()
    state.state = GameStates.combat_target.state
    state.data.update(
        pending_skill="volley",
        pending_hit_queue=[1, 2],
        collected_targets=[[0, "e1"]],
        pending_skill_page=1,
        combat_skill_page=1,
    )
    service = FakeGameService([(_make_skill(i), 0) for i in range(1, 9)])
    callback = _make_callback("g:back:skills:1")

    monkeypatch.setattr(combat_handler, "entity_id_for_tg_user", lambda *_: "p1")

    await combat_handler.cb_back_to_skills(callback, service, state)

    assert state.data["pending_skill"] is None
    assert state.data["pending_hit_queue"] == []
    assert state.data["collected_targets"] == []
    assert state.state == GameStates.combat_idle.state
    assert _markup_texts(callback) == [
        ["Skill 6"],
        ["Skill 7"],
        ["Skill 8"],
        ["⏭️ Skip"],
        ["← Prev"],
    ]


@pytest.mark.asyncio
async def test_restore_skill_prompt_preserves_current_page(monkeypatch):
    state = DummyState()
    state.state = GameStates.combat_target.state
    state.data.update(
        combat_skill_page=1,
        pending_skill_page=1,
        pending_skill="volley",
        pending_hit_queue=[0],
        collected_targets=[],
    )
    service = FakeGameService([(_make_skill(i), 0) for i in range(1, 11)])
    callback = _make_callback("g:tg:e1")

    monkeypatch.setattr(combat_handler, "entity_id_for_tg_user", lambda *_: "p1")

    await combat_handler._restore_skill_prompt(callback, service, "777", state)

    assert state.data["pending_skill"] is None
    assert state.data["pending_hit_queue"] == []
    assert state.data["collected_targets"] == []
    assert state.state == GameStates.combat_idle.state
    assert _markup_texts(callback) == [
        ["Skill 6"],
        ["Skill 7"],
        ["Skill 8"],
        ["Skill 9"],
        ["Skill 10"],
        ["← Prev", "Next →"],
    ]
