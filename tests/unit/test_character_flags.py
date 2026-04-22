import pytest

from game.character.flags import CharacterFlag
from tests.unit.conftest import make_warrior


def test_character_flag_rejects_empty_names_and_non_json_values():
    with pytest.raises(ValueError, match="flag_name cannot be empty"):
        CharacterFlag("   ", True)

    with pytest.raises(ValueError, match="JSON-compatible"):
        CharacterFlag("bad", object())

    with pytest.raises(ValueError, match="dict keys must be strings"):
        CharacterFlag("bad", {1: "not-json-key"})


def test_apply_flag_returns_copy_and_does_not_mutate_original():
    warrior = make_warrior()

    updated = warrior.apply_flag(
        " chose_event313_option_2 ",
        {"choice": 2, "tags": ["event313"]},
        flag_persistence=True,
    )

    assert updated is not warrior
    assert warrior.flags == {}
    assert "chose_event313_option_2" in updated.flags
    assert updated.flags["chose_event313_option_2"] == CharacterFlag(
        flag_name="chose_event313_option_2",
        flag_value={"choice": 2, "tags": ["event313"]},
        flag_persistence=True,
    )


def test_apply_flag_overwrites_existing_flag_by_name():
    warrior = make_warrior()
    warrior = warrior.apply_flag("door_opened", False)

    updated = warrior.apply_flag("door_opened", True, flag_persistence=True)

    assert updated.flags["door_opened"].flag_value is True
    assert updated.flags["door_opened"].flag_persistence is True


def test_remove_flag_returns_copy_or_noops_for_missing_flag():
    warrior = make_warrior().apply_flag("temporary_buff", 3)

    unchanged = warrior.remove_flag("missing")
    updated = warrior.remove_flag("temporary_buff")

    assert unchanged is warrior
    assert updated is not warrior
    assert updated.flags == {}
    assert "temporary_buff" in warrior.flags
