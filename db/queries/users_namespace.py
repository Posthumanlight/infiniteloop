import json
import logging

import asyncpg

from db.core.crud_operations import safe_get_db_data, safe_execute, SupabaseOperation
from game.session.lobby_manager import CharacterRecord, SavedCharacterSummary

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
            table="bot_users_id",
            filters=filters,
        )
        return results[0] if results else None


class UserCreatorDB(UserData):
    def __init__(self, pool):
        super().__init__(pool)

    async def register_user(self, user_data: dict):
        await safe_execute(
            pool=self.pool,
            schema=self.schema,
            table="bot_users_id",
            data=user_data,
            operation=SupabaseOperation.INSERT,
        )


class UserSettingsDB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.schema = "public"

    async def get_settings(self, tg_id: int) -> dict | None:
        result = await safe_get_db_data(
            pool=self.pool,
            schema=self.schema,
            table="bot_users_settings",
            filters={"tg_id": tg_id},
        )
        return result[0] if result else None

    async def upsert_settings(self, tg_id: int, data: dict) -> None:
        all_data = {"tg_id": tg_id, **data}
        columns = list(all_data.keys())
        values = list(all_data.values())
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        update_set = ", ".join(
            f"{col} = EXCLUDED.{col}" for col in columns if col != "tg_id"
        )
        sql = (
            f"INSERT INTO {self.schema}.bot_users_settings ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (tg_id) DO UPDATE SET {update_set}"
        )
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, *values)
        except Exception as exc:
            logger.error(f"DB error in upsert_settings for tg_id={tg_id}: {exc}")


class UserCharactersData(UserData):
    def __init__(self, pool):
        super().__init__(pool)

    @staticmethod
    def _parse_skills(raw_skills) -> tuple[str, ...]:
        if raw_skills is None:
            return ()
        if isinstance(raw_skills, str):
            try:
                decoded = json.loads(raw_skills)
            except json.JSONDecodeError:
                return ()
            if isinstance(decoded, list):
                return tuple(str(skill) for skill in decoded)
            return ()
        if isinstance(raw_skills, list):
            return tuple(str(skill) for skill in raw_skills)
        if isinstance(raw_skills, tuple):
            return tuple(str(skill) for skill in raw_skills)
        return ()

    async def get_user_characters(self, tg_id: int) -> list[SavedCharacterSummary]:
        sql = """
            SELECT
                gc.character_id AS character_id,
                gcd.class AS class_id,
                gcd.level AS level,
                gcd.xp AS xp,
                gc.created_at AS created_at
            FROM public.game_characters gc
            JOIN public.game_characters_data gcd
              ON gc.character_id::text = gcd.character_id::text
            WHERE gc.tg_id = $1
            ORDER BY gc.created_at DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, tg_id)
        except Exception as exc:
            logger.error(f"DB error in get_user_characters for tg_id={tg_id}: {exc}")
            return []

        return [
            SavedCharacterSummary(
                character_id=int(row["character_id"]),
                class_id=str(row["class_id"]),
                level=int(row["level"]),
                xp=int(row["xp"] or 0),
            )
            for row in rows
        ]

    async def get_character(self, character_id: int) -> CharacterRecord:
        sql = """
            SELECT
                gc.tg_id AS tg_id,
                gc.character_id AS character_id,
                gcd.class AS class_id,
                gcd.level AS level,
                gcd.xp AS xp,
                gcd.skills AS skills
            FROM public.game_characters gc
            JOIN public.game_characters_data gcd
              ON gc.character_id::text = gcd.character_id::text
            WHERE gc.character_id::text = $1
            LIMIT 1
        """
        inventory_sql = """
            SELECT item_id, amount
            FROM public.game_characters_inventory
            WHERE character_id::text = $1
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, int(character_id))
                if row is None:
                    raise KeyError(f"Unknown character: {character_id}")
                inventory_rows = await conn.fetch(inventory_sql, int(character_id))
        except KeyError:
            raise
        except Exception as exc:
            logger.error(f"DB error in get_character for character_id={character_id}: {exc}")
            raise

        inventory: dict[str, int] = {}
        for inv_row in inventory_rows:
            item_id = inv_row["item_id"]
            if item_id is None:
                continue
            inventory[str(item_id)] = inventory.get(str(item_id), 0) + int(inv_row["amount"] or 0)

        return CharacterRecord(
            character_id=int(row["character_id"]),
            tg_id=int(row["tg_id"]),
            class_id=str(row["class_id"]),
            level=int(row["level"]),
            xp=int(row["xp"] or 0),
            skills=self._parse_skills(row["skills"]),
            inventory=inventory,
        )

    async def create_character(
        self,
        tg_id: int,
        class_id: str,
        skills: tuple[str, ...],
        level: int = 1,
        xp: int = 0,
        inventory: dict[str, int] | None = None,
    ) -> CharacterRecord:
        inventory = inventory or {}
        skills_json = json.dumps(list(skills))

        sql_insert_data = """
            INSERT INTO public.game_characters_data (class, level, xp, skills)
            VALUES ($1, $2, $3, $4)
            RETURNING character_id
        """
        sql_insert_character = """
            INSERT INTO public.game_characters (tg_id, character_id)
            VALUES ($1, $2)
            ON CONFLICT (character_id) DO NOTHING
        """
        sql_insert_inventory = """
            INSERT INTO public.game_characters_inventory (character_id, item_id, amount)
            VALUES ($1, $2, $3)
        """

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(sql_insert_data, class_id, level, xp, skills_json)
                    if row is None:
                        raise RuntimeError("Failed to create character data row")
                    character_id = int(row["character_id"])
                    await conn.execute(sql_insert_character, tg_id, int(character_id))
                    for item_id, amount in inventory.items():
                        await conn.execute(sql_insert_inventory, int(character_id), item_id, amount)
        except Exception as exc:
            logger.error(f"DB error in create_character for tg_id={tg_id}: {exc}")
            raise

        return CharacterRecord(
            character_id=character_id,
            tg_id=tg_id,
            class_id=class_id,
            level=level,
            xp=xp,
            skills=tuple(skills),
            inventory=dict(inventory),
        )

    async def add_user_character(self, tg_id: int, character_id: str | int) -> None:
        sql = """
            INSERT INTO public.game_characters (tg_id, character_id)
            VALUES ($1, $2)
            ON CONFLICT (character_id) DO NOTHING
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, tg_id, int(character_id))
        except Exception as exc:
            logger.error(f"DB error in add_user_character for tg_id={tg_id}: {exc}")

    async def get_last_user_character(self, tg_id: int) -> dict | None:
        result = await safe_get_db_data(
            pool=self.pool,
            schema=self.schema,
            table="game_characters",
            filters={"tg_id": tg_id},
            additional="ORDER BY created_at DESC LIMIT 1",
        )
        return result[0] if result else None


UserСharactersData = UserCharactersData
UserРЎharactersData = UserCharactersData
