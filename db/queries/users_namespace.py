import logging

import asyncpg

from db.core.crud_operations import safe_get_db_data, safe_execute, SupabaseOperation

logger = logging.getLogger(__name__)

class UserData:
    def __init__(self, pool):
        self.pool = pool
        self.schema = "public"

    async def get_user_by_id(self, user_id: int):
        
        filters = {"tg_id": user_id}
        results = await safe_get_db_data(
            pool=self.pool,
            schema=self.schema,
            table='bot_users_id',
            filters=filters
        )
        return results[0] if results else None


class UserCreatorDB(UserData):
    def __init__(self, pool):
        super().__init__(pool)

    async def register_user(self, user_data: dict):
        
        await safe_execute(
            pool=self.pool,
            schema=self.schema,
            table='bot_users_id',
            data=user_data,
            operation=SupabaseOperation.INSERT
        )

class UserSettingsDB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.schema = "public"

    async def get_settings(self, tg_id: int) -> dict | None:
        result = await safe_get_db_data(
            pool=self.pool,
            schema=self.schema,
            table='bot_users_settings',
            filters={"tg_id": tg_id}
        )
        return result[0] if result else None

    async def upsert_settings(self, tg_id: int, data: dict) -> None:
        all_data = {"tg_id": tg_id, **data}
        columns = list(all_data.keys())
        values = list(all_data.values())
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        update_set = ", ".join(
            f"{col} = EXCLUDED.{col}" for col in columns if col != 'tg_id'
        )
        sql = (
            f"INSERT INTO {self.schema}.bot_users_settings ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (tg_id) DO UPDATE SET {update_set}"
        )
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, *values)
        except Exception as e:
            logger.error(f"DB error in upsert_settings for tg_id={tg_id}: {e}")