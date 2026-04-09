from contextlib import asynccontextmanager
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from config import settings
from db.core.pool import create_db_pool
from game_service import GameService

from bot.bot import router as bot_router, set_bot_commands, onboarding_router as bot_onboarding_router
from bot.handlers.game import router as game_router
from bot.handlers.character import router as character_router
from bot.handlers.combat import router as combat_router
from bot.handlers.exploration import router as exploration_router



#Telegram bot
BOT_TOKEN = settings.telegram_bot_token
logging.basicConfig(level=logging.INFO)

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
port = int(os.getenv("PORT", 8000))
config = uvicorn.Config(app, host="0.0.0.0", port=port)
server = uvicorn.Server(config)  

@app.post(settings.telegram_webhook_path)
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    task = asyncio.create_task(dp.feed_update(bot, update))
    task.add_done_callback(lambda t: t.exception() and logging.error("Unhandled error in update task", exc_info=t.exception()))
    return {"ok": True}
