from aiogram.fsm.state import State, StatesGroup

class GeneralStates(StatesGroup):
    main_menu = State()

class OnboardingStates(StatesGroup):
    set_language = State()
    set_reminders = State()


class GameStates(StatesGroup):
    lobby = State()
    class_select = State()
    exploring = State()
    combat_idle = State()
    combat_skill = State()
    combat_target = State()
    event_voting = State()
    run_ended = State()
    save_decision = State()
    save_name = State()
