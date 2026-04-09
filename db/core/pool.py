import asyncpg

async def create_db_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        min_size=2,
        max_size=10,
        command_timeout=30.0,
        timeout=10.0,
        server_settings={
            "search_path": "public",
            "application_name": "infiniteloop",
        },
    )
