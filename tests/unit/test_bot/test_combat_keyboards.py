from bot.tools.keyboards import skill_keyboard, target_keyboard
from game.core.data_loader import SkillData
from game.core.enums import ActionType, EntityType
from game.core.game_models import EntitySnapshot


def _make_skill(index: int) -> SkillData:
    return SkillData(
        skill_id=f"skill_{index}",
        name=f"Skill {index}",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=(),
        self_effects=(),
    )


def _texts(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _callbacks(markup) -> list[list[str]]:
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def test_skill_keyboard_single_page_with_skip_and_no_pager():
    skills = [(_make_skill(i), 0) for i in range(1, 4)]

    markup = skill_keyboard(skills, page=0)

    assert _texts(markup) == [
        ["Skill 1"],
        ["Skill 2"],
        ["Skill 3"],
        ["⏭️ Skip"],
    ]
    assert _callbacks(markup) == [
        ["g:sk:skill_1"],
        ["g:sk:skill_2"],
        ["g:sk:skill_3"],
        ["g:skip"],
    ]


def test_skill_keyboard_five_skills_adds_extra_skip_page():
    skills = [(_make_skill(i), 0) for i in range(1, 6)]

    first_page = skill_keyboard(skills, page=0)
    second_page = skill_keyboard(skills, page=1)

    assert _texts(first_page) == [
        ["Skill 1"],
        ["Skill 2"],
        ["Skill 3"],
        ["Skill 4"],
        ["Skill 5"],
        ["Next →"],
    ]
    assert _callbacks(first_page)[-1] == ["g:skpg:1"]

    assert _texts(second_page) == [
        ["⏭️ Skip"],
        ["← Prev"],
    ]
    assert _callbacks(second_page) == [
        ["g:skip"],
        ["g:skpg:0"],
    ]


def test_skill_keyboard_eight_skills_second_page_has_skip_and_prev_only():
    skills = [(_make_skill(i), 0) for i in range(1, 9)]

    markup = skill_keyboard(skills, page=1)

    assert _texts(markup) == [
        ["Skill 6"],
        ["Skill 7"],
        ["Skill 8"],
        ["⏭️ Skip"],
        ["← Prev"],
    ]
    assert _callbacks(markup) == [
        ["g:sk:skill_6"],
        ["g:sk:skill_7"],
        ["g:sk:skill_8"],
        ["g:skip"],
        ["g:skpg:0"],
    ]


def test_skill_keyboard_twenty_skills_uses_prev_and_next_on_middle_page():
    skills = [(_make_skill(i), 0) for i in range(1, 21)]

    middle_page = skill_keyboard(skills, page=3)
    last_page = skill_keyboard(skills, page=4)

    assert _texts(middle_page) == [
        ["Skill 16"],
        ["Skill 17"],
        ["Skill 18"],
        ["Skill 19"],
        ["Skill 20"],
        ["← Prev", "Next →"],
    ]
    assert _callbacks(middle_page)[-1] == ["g:skpg:2", "g:skpg:4"]

    assert _texts(last_page) == [
        ["⏭️ Skip"],
        ["← Prev"],
    ]


def test_target_keyboard_appends_back_button():
    targets = [
        EntitySnapshot(
            entity_id="e1",
            name="Goblin",
            entity_type=EntityType.ENEMY,
            current_hp=30,
            max_hp=40,
            current_energy=10,
            max_energy=10,
            is_alive=True,
        ),
        EntitySnapshot(
            entity_id="e2",
            name="Dead Goblin",
            entity_type=EntityType.ENEMY,
            current_hp=0,
            max_hp=40,
            current_energy=0,
            max_energy=10,
            is_alive=False,
        ),
    ]

    markup = target_keyboard(targets, back_page=2)

    assert _texts(markup) == [
        ["Goblin (30/40 HP)"],
        ["Back"],
    ]
    assert _callbacks(markup) == [
        ["g:tg:e1"],
        ["g:back:skills:2"],
    ]
