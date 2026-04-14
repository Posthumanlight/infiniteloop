import asyncio

from game.combat.skill_modifiers import ModifierInstance
from game.session.lobby_manager import (
    CharacterRecord,
    LobbyManager,
    SavedCharacterSummary,
)


class _FakeRepo:
    def __init__(self):
        self.get_character_record = CharacterRecord(
            character_id=42,
            tg_id=1001,
            character_name="OldName",
            class_id="warrior",
            level=3,
            xp=250,
            skills=("slash", "cleave"),
            skill_modifiers=(ModifierInstance("slash_power", 2),),
            inventory={"potion": 1},
        )
        self.user_characters: list[SavedCharacterSummary] = [
            SavedCharacterSummary(
                character_id=42,
                character_name="OldName",
                class_id="warrior",
                level=3,
                xp=250,
            ),
        ]
        self.create_saved_called = False

    async def get_user_characters(self, tg_id: int):
        return list(self.user_characters)

    async def get_character(self, character_id: int):
        return self.get_character_record

    async def create_saved_character(self, *args, **kwargs):
        self.create_saved_called = True
        raise AssertionError("create_saved_character should not be called in lobby launch")

    async def character_name_exists(self, character_name: str, exclude_character_id=None):
        return False

    async def save_character_progress(self, *args, **kwargs):
        return None


def test_build_launch_payload_new_class_is_transient():
    repo = _FakeRepo()
    repo.user_characters = []
    mgr = LobbyManager(repo)

    async def _run():
        await mgr.create_lobby("sid", 1, "PlayerOne")
        mgr.choose_create_new("sid", 1)
        mgr.choose_new_class("sid", 1, "warrior")
        return await mgr.build_launch_payload("sid")

    payload = asyncio.run(_run())

    assert payload.players[0].entity_id == "tmp:1"
    assert payload.save_origins[0].is_transient is True
    assert payload.save_origins[0].character_id is None
    assert repo.create_saved_called is False


def test_build_launch_payload_saved_character_keeps_origin():
    repo = _FakeRepo()
    mgr = LobbyManager(repo)

    async def _run():
        await mgr.create_lobby("sid", 1001, "PlayerOne")
        mgr.choose_saved_character("sid", 1001, 42)
        return await mgr.build_launch_payload("sid")

    payload = asyncio.run(_run())

    assert payload.players[0].entity_id == "42"
    assert payload.save_origins[0].is_transient is False
    assert payload.save_origins[0].character_id == 42
    assert payload.save_origins[0].character_name == "OldName"
