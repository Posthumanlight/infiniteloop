from contextlib import asynccontextmanager
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from config import settings
from db.core.pool import create_db_pool
from game_service import GameService
from webapp import router as webapp_router

from bot.bot import router as bot_router, set_bot_commands, onboarding_router as bot_onboarding_router
from bot.handlers.game import router as game_router
from bot.handlers.character import router as character_router
from bot.handlers.combat import router as combat_router
from bot.handlers.exploration import router as exploration_router



#Telegram bot
BOT_TOKEN = settings.telegram_bot_token
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(bot_router)
dp.include_router(bot_onboarding_router)
dp.include_router(game_router)
dp.include_router(character_router)
dp.include_router(combat_router)
dp.include_router(exploration_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_pool = await create_db_pool(settings.supabase_url)
    dp["db_pool"] = db_pool
    app.state.db_pool = db_pool
    game_service = GameService()
    dp["game_service"] = game_service
    app.state.game_service = game_service
    await bot.delete_webhook()
    await bot.set_webhook(settings.telegram_webhook_url)
    await set_bot_commands(bot)
    yield
    # Shutdown
    await bot.delete_webhook()
    await bot.session.close()
    await db_pool.close()

#FastAPI app
app = FastAPI(lifespan=lifespan)
app.include_router(webapp_router)
app.mount(
    "/webapp",
    StaticFiles(
        directory=str(Path(__file__).parent / "frontend" / "build"),
        html=True,
        check_dir=False,
    ),
    name="webapp",
)
port = int(os.getenv("PORT", 8000))
config = uvicorn.Config(app, host="0.0.0.0", port=port)
server = uvicorn.Server(config)  


def _trim_log_value(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    value = value.replace("\n", "\\n")
    return value if len(value) <= limit else f"{value[:limit]}..."


def _telegram_user_label(user) -> str:
    if user is None:
        return "unknown"

    username = f"@{user.username}" if getattr(user, "username", None) else "no_username"
    full_name = getattr(user, "full_name", "") or ""
    return f"{user.id} {username} {full_name}".strip()


def _telegram_chat_label(chat) -> str:
    if chat is None:
        return "unknown"

    title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or ""
    return f"{chat.id} {chat.type} {title}".strip()


def log_telegram_update(update: Update) -> None:
    message = update.message or update.edited_message
    if message is not None:
        user = _telegram_user_label(message.from_user)
        chat = _telegram_chat_label(message.chat)
        message_type = getattr(message, "content_type", "unknown")
        text = _trim_log_value(message.text or message.caption)
        logger.info(
            "Telegram message: update_id=%s message_id=%s type=%s user=%s chat=%s text=%r",
            update.update_id,
            message.message_id,
            message_type,
            user,
            chat,
            text,
        )
        return

    if update.callback_query is not None:
        callback = update.callback_query
        user = _telegram_user_label(callback.from_user)
        message_id = callback.message.message_id if callback.message else "unknown"
        chat = _telegram_chat_label(callback.message.chat) if callback.message else "unknown"
        data = _trim_log_value(callback.data)
        logger.info(
            "Telegram callback: update_id=%s callback_id=%s message_id=%s user=%s chat=%s data=%r",
            update.update_id,
            callback.id,
            message_id,
            user,
            chat,
            data,
        )
        return

    logger.info("Telegram update: update_id=%s type=other", update.update_id)


def log_update_task_error(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        logger.info("Update task was cancelled")
        return

    if exc is not None:
        logger.error("Unhandled error in update task", exc_info=(type(exc), exc, exc.__traceback__))

@app.post(settings.telegram_webhook_path)
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    log_telegram_update(update)
    task = asyncio.create_task(dp.feed_update(bot, update))
    task.add_done_callback(log_update_task_error)
    return {"ok": True}


if __name__ == "__main__":
    try:
        logger.info("Starting uvicorn on 0.0.0.0:%s", port)
        server.run()
    except Exception:
        logger.exception("Application crashed during startup/runtime")
        raise
