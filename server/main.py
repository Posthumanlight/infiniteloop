from contextlib import asynccontextmanager
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from settings.config import settings
from db.core.pool import create_db_pool

from bot.bot import router as bot_router, set_bot_commands, onboarding_router as bot_onboarding_router



#Telegram bot
BOT_TOKEN = settings.telegram_bot_token
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(bot_router)
dp.include_router(bot_onboarding_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_pool = await create_db_pool()
    dp["db_pool"] = db_pool
    app.state.db_pool = db_pool
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
port = int(os.getenv("PORT", 10000))
config = uvicorn.Config(app, host="0.0.0.0", port=port)
server = uvicorn.Server(config)  