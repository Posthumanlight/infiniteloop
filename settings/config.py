from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import load_dotenv
import os

_env_parent = Path(__file__).parents[2] / ".env"

if _env_parent.exists():
    load_dotenv(_env_parent)
    env_file = _env_parent
    print (f"Loaded environment variables from {_env_parent}")
else:
    env_file = None

class Settings(BaseSettings):
    telegram_bot_token: str
    supabase_url: str
    supabase_secret_key: str
    database_url: str
    telegram_webhook_url: str
    telegram_webhook_path: str

    model_config = SettingsConfigDict(
        env_file=str(env_file) if env_file is not None else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

_required_env = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_URL",
    "SUPABASE_URL",
    "SUPABASE_SECRET_KEY",
    "DATABASE_URL",
]
_env_presence = {k: (k in os.environ) for k in _required_env}

if env_file:
    print("Loading env file from:", env_file)
else:
    print("No .env file found — using process environment.")

print("Required env vars present:", ", ".join(f"{k}=YES" if v else f"{k}=NO" for k, v in _env_presence.items()))

settings = Settings() # pyright: ignore[reportCallIssue]
