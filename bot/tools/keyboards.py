from settings.config import settings

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, WebAppInfo

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚙️ Налаштування", callback_data="open_settings"),
            ],
        ]
    )

def confirm_keyboard(yes_callback, no_callback) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так", callback_data=yes_callback),
                InlineKeyboardButton(text="❌ Ні", callback_data=no_callback),
            ]
        ]
    )