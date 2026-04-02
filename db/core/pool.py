import asyncpg
from settings.config import settings


async def create_db_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30.0,
        timeout=10.0,
        server_settings={
            "search_path": "public",
            "application_name": "infiniteloop",
        },
    )
