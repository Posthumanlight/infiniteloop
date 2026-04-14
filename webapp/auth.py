"""Telegram Mini App authentication helpers."""

from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data


def parse_telegram_init_data(token: str, init_data: str) -> WebAppInitData:
    """Validate and parse raw Telegram init data."""
    return safe_parse_webapp_init_data(token=token, init_data=init_data)
