from bot.logging.bot_log import setup_telegram_logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from db.queries.users_namespace import UserSettingsDB
from bot.bot_state import  GeneralStates, OnboardingStates
from bot.tools.keyboards import confirm_keyboard, main_menu_keyboard
from db.queries.users_namespace import UserCreatorDB

import asyncpg


router = Router(name="onboarding_router")
logger, buffer_handler = setup_telegram_logging()


def onboarding_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="settings_lang_uk"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="settings_lang_en"),
            ],

        ]
    )

@router.callback_query(OnboardingStates.set_language, F.data.in_({"settings_lang_uk", "settings_lang_en"}))
async def onboarding_set_language(callback: CallbackQuery, state: FSMContext, db_pool: asyncpg.Pool):
    await callback.answer()
    lang = "uk" if callback.data == "settings_lang_uk" else "en"
    tg_id = callback.from_user.id  # pyright: ignore[reportOptionalMemberAccess]
    await UserSettingsDB(db_pool).upsert_settings(tg_id, {"language": lang})
    await state.set_state(OnboardingStates.set_reminders)
    assert isinstance(callback.message, Message)
    logger.info(f"User {tg_id} set language to {lang}")
    await callback.message.answer("Чудово! Давай увімкнемо нагадування для твоїх цілей? \n Жодного спаму, лише завдання.", reply_markup=confirm_keyboard('settings_reminders_yes', 'settings_reminders_no'))
    await state.set_state(OnboardingStates.set_reminders)

@router.callback_query(OnboardingStates.set_reminders, F.data == 'settings_reminders_yes')
async def onboarding_set_reminders_yes(callback: CallbackQuery, state: FSMContext, db_pool: asyncpg.Pool):
    assert isinstance(callback.message, Message)
    await callback.answer()
    tg_id = callback.from_user.id  # pyright: ignore[reportOptionalMemberAccess]
    await UserSettingsDB(db_pool).upsert_settings(tg_id, {"notifications": 'True'})
    logger.info(f"User {callback.from_user.id} finished registration")
    await callback.message.answer("Головне меню:", reply_markup= main_menu_keyboard())
    logger.info(f"User {callback.from_user.id} set reminders to True")

@router.callback_query(OnboardingStates.set_reminders, F.data == 'settings_reminders_no')
async def onboarding_set_reminders_no(callback: CallbackQuery, state: FSMContext, db_pool: asyncpg.Pool):
    assert isinstance(callback.message, Message)
    await callback.answer()
    await state.set_state(GeneralStates.main_menu)
    await callback.message.answer("Зрозумів, якщо передумаєш - опція у налаштуваннях")
    await UserCreatorDB(pool=db_pool).register_user({"tg_id": callback.from_user.id})
    logger.info(f"User {callback.from_user.id} finished registration")
    await callback.message.answer("Головне меню:", reply_markup= main_menu_keyboard())
    logger.info(f"User {callback.from_user.id} set reminders to False")