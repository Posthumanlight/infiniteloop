from settings.config import settings
import asyncpg
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message, BotCommand
from aiogram.fsm.context import FSMContext

from bot.logging.bot_log import setup_telegram_logging

from bot.bot_state import GeneralStates,  OnboardingStates

from db.core.crud_operations import SupabaseOperation, safe_execute
from db.queries.users_namespace import UserCreatorDB, UserData
from bot.handlers.onboarding import onboarding_language_keyboard, router as onboarding_router
from bot.tools.keyboards import main_menu_keyboard

BOT_TOKEN = settings.telegram_bot_token
logger, buffer_handler = setup_telegram_logging()
router = Router()

async def set_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="run", description="Create a new game session"),
        BotCommand(command="join", description="Join the current game session"),
        BotCommand(command="char", description="View your character"),
        BotCommand(command="combat", description="Show combat status"),
        BotCommand(command="leave", description="End the current session"),
    ]
    await bot.set_my_commands(commands)

@router.message(Command("start"))
async def cmd_start(message: Message, db_pool: asyncpg.Pool, state: FSMContext):
    await state.clear()
    logger.info(f"User {message.from_user.id} used command /start") # pyright: ignore[reportOptionalMemberAccess]
    user_id = await UserData(pool=db_pool).get_user_by_id(message.from_user.id) # pyright: ignore[reportOptionalMemberAccess]
    if user_id:
        await message.answer("Ти вже зареєстрований. Повертаю тебе в головне меню.", reply_markup=main_menu_keyboard())
        await state.set_state(GeneralStates.main_menu)
    else:
        await message.answer("Вітаю!")
        await UserCreatorDB(db_pool).register_user(
            user_data={"tg_id": str(message.from_user.id)} # pyright: ignore[reportOptionalMemberAccess]
    )
        await state.set_state(OnboardingStates.set_language)
        await message.answer('Вибери мову: \n Select your language:', reply_markup=onboarding_language_keyboard())

