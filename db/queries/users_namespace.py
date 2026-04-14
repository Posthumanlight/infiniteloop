import json
import logging

import asyncpg

from db.core.crud_operations import safe_get_db_data, safe_execute, SupabaseOperation
from game.combat.skill_modifiers import ModifierInstance
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

    @staticmethod
    def _parse_modifiers(raw_modifiers) -> tuple[ModifierInstance, ...]:
        if raw_modifiers is None:
            return ()
        if isinstance(raw_modifiers, str):
            try:
                decoded = json.loads(raw_modifiers)
            except json.JSONDecodeError:
                return ()
        elif isinstance(raw_modifiers, (list, tuple)):
            decoded = raw_modifiers
        else:
            return ()

        result: list[ModifierInstance] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            modifier_id = item.get("modifier_id")
            if modifier_id is None:
                continue
            stack_count = item.get("stack_count", 1)
            try:
                parsed_stack_count = int(stack_count)
            except (TypeError, ValueError):
                parsed_stack_count = 1
            result.append(
                ModifierInstance(
                    modifier_id=str(modifier_id),
                    stack_count=max(1, parsed_stack_count),
                ),
            )
        return tuple(result)

    @staticmethod
    def _serialize_modifiers(
        modifiers: tuple[ModifierInstance, ...],
    ) -> str:
        payload = [
            {
                "modifier_id": modifier.modifier_id,
                "stack_count": modifier.stack_count,
            }
            for modifier in modifiers
        ]
        return json.dumps(payload)

    async def get_user_characters(self, tg_id: int) -> list[SavedCharacterSummary]:
        sql = """
            SELECT
                gc.character_id AS character_id,
                gc.character_name AS character_name,
                gcd.class AS class_id,
                gcd.level AS level,
                gcd.xp AS xp,
                gc.created_at AS created_at
            FROM public.game_characters gc
            JOIN public.game_characters_data gcd
              ON gc.character_id = gcd.character_id
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
                character_name=(
                    str(row["character_name"])
                    if row["character_name"] is not None
                    else None
                ),
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
                gc.character_name AS character_name,
                gcd.class AS class_id,
                gcd.level AS level,
                gcd.xp AS xp,
                gcd.skills AS skills,
                gcd.modifiers AS modifiers
            FROM public.game_characters gc
            JOIN public.game_characters_data gcd
              ON gc.character_id = gcd.character_id
            WHERE gc.character_id = $1
            LIMIT 1
        """
        inventory_sql = """
            SELECT item_id, amount
            FROM public.game_characters_inventory
            WHERE character_id = $1
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
            character_name=(
                str(row["character_name"])
                if row["character_name"] is not None
                else None
            ),
            class_id=str(row["class_id"]),
            level=int(row["level"]),
            xp=int(row["xp"] or 0),
            skills=self._parse_skills(row["skills"]),
            skill_modifiers=self._parse_modifiers(row["modifiers"]),
            inventory=inventory,
        )

    async def create_saved_character(
        self,
        tg_id: int,
        character_name: str,
        class_id: str,
        skills: tuple[str, ...],
        level: int = 1,
        xp: int = 0,
        skill_modifiers: tuple[ModifierInstance, ...] = (),
        inventory: dict[str, int] | None = None,
    ) -> CharacterRecord:
        inventory = inventory or {}
        skills_json = json.dumps(list(skills))
        modifiers_json = self._serialize_modifiers(skill_modifiers)

        sql_insert_data = """
            INSERT INTO public.game_characters_data (class, level, xp, skills, modifiers)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING character_id
        """
        sql_insert_character = """
            INSERT INTO public.game_characters (tg_id, character_id, character_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (character_id) DO NOTHING
        """
        sql_insert_inventory = """
            INSERT INTO public.game_characters_inventory (character_id, item_id, amount)
            VALUES ($1, $2, $3)
        """

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        sql_insert_data,
                        class_id,
                        level,
                        xp,
                        skills_json,
                        modifiers_json,
                    )
                    if row is None:
                        raise RuntimeError("Failed to create character data row")
                    character_id = int(row["character_id"])
                    await conn.execute(
                        sql_insert_character,
                        tg_id,
                        int(character_id),
                        character_name,
                    )
                    for item_id, amount in inventory.items():
                        await conn.execute(sql_insert_inventory, int(character_id), item_id, amount)
        except Exception as exc:
            logger.error(
                f"DB error in create_saved_character for tg_id={tg_id}: {exc}",
            )
            raise

        return CharacterRecord(
            character_id=character_id,
            tg_id=tg_id,
            character_name=character_name,
            class_id=class_id,
            level=level,
            xp=xp,
            skills=tuple(skills),
            skill_modifiers=tuple(skill_modifiers),
            inventory=dict(inventory),
        )

    async def character_name_exists(
        self,
        character_name: str,
        exclude_character_id: int | None = None,
    ) -> bool:
        sql = """
            SELECT 1
            FROM public.game_characters
            WHERE lower(character_name) = lower($1)
        """
        params: list[object] = [character_name]
        if exclude_character_id is not None:
            sql += " AND character_id <> $2"
            params.append(int(exclude_character_id))
        sql += " LIMIT 1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
        except Exception as exc:
            logger.error(
                "DB error in character_name_exists "
                f"for character_name={character_name}: {exc}",
            )
            raise
        return row is not None

    async def save_character_progress(
        self,
        character_id: int,
        character_name: str,
        level: int,
        xp: int,
        skills: tuple[str, ...],
        skill_modifiers: tuple[ModifierInstance, ...],
    ) -> None:
        skills_json = json.dumps(list(skills))
        modifiers_json = self._serialize_modifiers(skill_modifiers)
        sql_update_data = """
            UPDATE public.game_characters_data
            SET level = $2,
                xp = $3,
                skills = $4,
                modifiers = $5
            WHERE character_id = $1
        """
        sql_update_meta = """
            UPDATE public.game_characters
            SET character_name = $2
            WHERE character_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        sql_update_data,
                        int(character_id),
                        int(level),
                        int(xp),
                        skills_json,
                        modifiers_json,
                    )
                    await conn.execute(
                        sql_update_meta,
                        int(character_id),
                        character_name,
                    )
        except Exception as exc:
            logger.error(
                "DB error in save_character_progress "
                f"for character_id={character_id}: {exc}",
            )
            raise

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


