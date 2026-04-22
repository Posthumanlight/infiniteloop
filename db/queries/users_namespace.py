import json
import logging
from dataclasses import dataclass

import asyncpg

from db.core.crud_operations import safe_get_db_data, safe_execute, SupabaseOperation
from game.character.flags import CharacterFlag
from game.character.inventory import EquipmentLoadout, Inventory
from game.combat.skill_modifiers import ModifierInstance
from game.core.enums import ItemEffect, ItemType
from game.items.items import GeneratedItemEffect, ItemInstance
from game.session.lobby_manager import CharacterRecord, SavedCharacterSummary

logger = logging.getLogger(__name__)

FORTUNA_MOTES = "Fortuna Motes"


@dataclass(frozen=True)
class UserCurrencyBalance:
    currency_name: str
    current_value: int


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


class UserCurrenciesDB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_currency(
        self,
        tg_id: int,
        currency_name: str,
    ) -> UserCurrencyBalance:
        sql = """
            SELECT currency_name, current_value
            FROM public.game_user_currencies
            WHERE tg_id = $1 AND currency_name = $2
            LIMIT 1
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, int(tg_id), currency_name)
        except Exception as exc:
            logger.error(
                "DB error in get_currency "
                f"for tg_id={tg_id}, currency_name={currency_name}: {exc}",
            )
            raise

        if row is None:
            return UserCurrencyBalance(currency_name=currency_name, current_value=0)
        return UserCurrencyBalance(
            currency_name=str(row["currency_name"]),
            current_value=int(row["current_value"] or 0),
        )

    async def add_currency(
        self,
        tg_id: int,
        currency_name: str,
        amount: int,
    ) -> UserCurrencyBalance:
        if amount < 0:
            raise ValueError("Currency amount must be non-negative")

        sql = """
            INSERT INTO public.game_user_currencies (
                tg_id,
                currency_name,
                current_value
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (tg_id, currency_name)
            DO UPDATE SET current_value =
                COALESCE(game_user_currencies.current_value, 0)
                + EXCLUDED.current_value
            RETURNING currency_name, current_value
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    sql,
                    int(tg_id),
                    currency_name,
                    int(amount),
                )
        except Exception as exc:
            logger.error(
                "DB error in add_currency "
                f"for tg_id={tg_id}, currency_name={currency_name}: {exc}",
            )
            raise

        if row is None:
            raise RuntimeError("Currency update did not return a row")
        return UserCurrencyBalance(
            currency_name=str(row["currency_name"]),
            current_value=int(row["current_value"] or 0),
        )


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

    @staticmethod
    def _parse_flags(raw_flags) -> dict[str, CharacterFlag]:
        if raw_flags is None:
            return {}
        if isinstance(raw_flags, str):
            try:
                decoded = json.loads(raw_flags)
            except json.JSONDecodeError:
                return {}
        elif isinstance(raw_flags, dict):
            decoded = raw_flags
        else:
            return {}

        result: dict[str, CharacterFlag] = {}
        for key, raw in decoded.items():
            if isinstance(raw, dict) and "flag_value" in raw:
                name = str(raw.get("flag_name") or key)
                persistence = bool(
                    raw.get("flag_persistence", raw.get("flag_persistance", True)),
                )
                value = raw.get("flag_value")
            else:
                name = str(key)
                value = raw
                persistence = True

            try:
                flag = CharacterFlag(
                    flag_name=name,
                    flag_value=value,
                    flag_persistence=persistence,
                )
            except ValueError:
                continue
            if flag.flag_persistence:
                result[flag.flag_name] = flag
        return result

    @staticmethod
    def _serialize_flags(flags: dict[str, CharacterFlag]) -> str:
        payload = {
            name: {
                "flag_name": flag.flag_name,
                "flag_value": flag.flag_value,
                "flag_persistence": flag.flag_persistence,
            }
            for name, flag in flags.items()
            if flag.flag_persistence
        }
        return json.dumps(payload)

    @staticmethod
    def _parse_generated_effects(raw_effects) -> tuple[GeneratedItemEffect, ...]:
        if raw_effects is None:
            return ()
        if isinstance(raw_effects, str):
            try:
                decoded = json.loads(raw_effects)
            except json.JSONDecodeError:
                return ()
        elif isinstance(raw_effects, (list, tuple)):
            decoded = raw_effects
        else:
            return ()

        effects: list[GeneratedItemEffect] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            effect_type = item.get("effect_type")
            if effect_type is None:
                continue
            try:
                parsed_type = ItemEffect(str(effect_type))
            except ValueError:
                continue
            value = item.get("value")
            parsed_value: float | None
            if value is None:
                parsed_value = None
            else:
                try:
                    parsed_value = float(value)
                except (TypeError, ValueError):
                    parsed_value = None
            effects.append(GeneratedItemEffect(
                effect_type=parsed_type,
                stat=item.get("stat"),
                value=parsed_value,
                skill_id=item.get("skill_id"),
                passive_id=item.get("passive_id"),
            ))
        return tuple(effects)

    @staticmethod
    def _serialize_generated_effects(
        effects: tuple[GeneratedItemEffect, ...],
    ) -> str:
        payload = [
            {
                "effect_type": effect.effect_type.value,
                "stat": effect.stat,
                "value": effect.value,
                "skill_id": effect.skill_id,
                "passive_id": effect.passive_id,
            }
            for effect in effects
        ]
        return json.dumps(payload)

    @classmethod
    def _deserialize_item_instance(cls, row) -> ItemInstance:
        additional_data = row["additional_data"]
        if isinstance(additional_data, str):
            try:
                parsed_additional = json.loads(additional_data)
            except json.JSONDecodeError:
                parsed_additional = {}
        elif isinstance(additional_data, dict):
            parsed_additional = additional_data
        else:
            parsed_additional = {}
        raw_item_sets = parsed_additional.get("item_sets", ())
        if isinstance(raw_item_sets, (list, tuple)):
            item_sets = tuple(str(set_id) for set_id in raw_item_sets)
        else:
            item_sets = ()
        return ItemInstance(
            instance_id=str(row["instance_id"]),
            blueprint_id=str(row["blueprint_id"]),
            name=str(parsed_additional.get("name", row["blueprint_id"])),
            item_type=ItemType(str(row["item_type"])),
            quality=int(row["quality"] or 1),
            effects=cls._parse_generated_effects(row["generated_effects"]),
            item_sets=item_sets,
            unique=bool(parsed_additional.get("unique", False)),
            rarity=str(parsed_additional.get("rarity", "common") or "common"),
        )

    @staticmethod
    def _serialize_item_instance(item: ItemInstance) -> dict[str, object]:
        return {
            "instance_id": item.instance_id,
            "blueprint_id": item.blueprint_id,
            "item_type": item.item_type.value,
            "quality": item.quality,
            "generated_effects": UserCharactersData._serialize_generated_effects(
                item.effects,
            ),
            "additional_data": json.dumps({
                "name": item.name,
                "item_sets": list(item.item_sets),
                "unique": item.unique,
                "rarity": item.rarity,
            }),
        }

    @classmethod
    def _build_inventory_from_rows(cls, rows) -> Inventory:
        items: dict[str, ItemInstance] = {}
        weapon_id: str | None = None
        armor_id: str | None = None
        relic_ids: list[str | None] = [None, None, None, None, None]

        for row in rows:
            item = cls._deserialize_item_instance(row)
            items[item.instance_id] = item
            slot = row["equipped_slot"]
            index = row["equipped_index"]
            if slot == "weapon":
                weapon_id = item.instance_id
            elif slot == "armor":
                armor_id = item.instance_id
            elif slot == "relic":
                if index is None:
                    continue
                idx = int(index)
                if 0 <= idx < len(relic_ids):
                    relic_ids[idx] = item.instance_id

        return Inventory(
            items=items,
            equipment=EquipmentLoadout(
                weapon_id=weapon_id,
                armor_id=armor_id,
                relic_ids=tuple(relic_ids),
            ),
        )

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
                gcd.modifiers AS modifiers,
                gcd.character_flags AS character_flags
            FROM public.game_characters gc
            JOIN public.game_characters_data gcd
              ON gc.character_id = gcd.character_id
            WHERE gc.character_id = $1
            LIMIT 1
        """
        inventory_sql = """
            SELECT
                instance_id,
                blueprint_id,
                item_type,
                quality,
                generated_effects,
                equipped_slot,
                equipped_index,
                additional_data
            FROM public.game_characters_item_instances
            WHERE character_id = $1
            ORDER BY instance_id
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
            inventory=self._build_inventory_from_rows(inventory_rows),
            flags=self._parse_flags(row["character_flags"]),
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
        inventory: Inventory | None = None,
        flags: dict[str, CharacterFlag] | None = None,
    ) -> CharacterRecord:
        inventory = inventory or Inventory()
        skills_json = json.dumps(list(skills))
        modifiers_json = self._serialize_modifiers(skill_modifiers)
        flags_json = self._serialize_flags(flags or {})

        sql_insert_data = """
            INSERT INTO public.game_characters_data (
                class,
                level,
                xp,
                skills,
                modifiers,
                character_flags
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING character_id
        """
        sql_insert_character = """
            INSERT INTO public.game_characters (tg_id, character_id, character_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (character_id) DO NOTHING
        """
        sql_insert_inventory = """
            INSERT INTO public.game_characters_item_instances (
                instance_id,
                character_id,
                blueprint_id,
                item_type,
                quality,
                generated_effects,
                equipped_slot,
                equipped_index,
                additional_data
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb)
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
                        flags_json,
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
                    for item in inventory.items.values():
                        slot, index = inventory.equipped_slot(item.instance_id)
                        payload = self._serialize_item_instance(item)
                        await conn.execute(
                            sql_insert_inventory,
                            payload["instance_id"],
                            int(character_id),
                            payload["blueprint_id"],
                            payload["item_type"],
                            payload["quality"],
                            payload["generated_effects"],
                            slot,
                            index,
                            payload["additional_data"],
                        )
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
            inventory=inventory,
            flags=self._parse_flags(flags_json),
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
        inventory: Inventory | None = None,
        flags: dict[str, CharacterFlag] | None = None,
    ) -> None:
        skills_json = json.dumps(list(skills))
        modifiers_json = self._serialize_modifiers(skill_modifiers)
        flags_json = (
            self._serialize_flags(flags)
            if flags is not None
            else None
        )
        sql_update_data = """
            UPDATE public.game_characters_data
            SET level = $2,
                xp = $3,
                skills = $4,
                modifiers = $5,
                character_flags = COALESCE($6::jsonb, character_flags)
            WHERE character_id = $1
        """
        sql_update_meta = """
            UPDATE public.game_characters
            SET character_name = $2
            WHERE character_id = $1
        """
        sql_delete_inventory = """
            DELETE FROM public.game_characters_item_instances
            WHERE character_id = $1
        """
        sql_insert_inventory = """
            INSERT INTO public.game_characters_item_instances (
                instance_id,
                character_id,
                blueprint_id,
                item_type,
                quality,
                generated_effects,
                equipped_slot,
                equipped_index,
                additional_data
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb)
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
                        flags_json,
                    )
                    await conn.execute(
                        sql_update_meta,
                        int(character_id),
                        character_name,
                    )
                    if inventory is not None:
                        await conn.execute(sql_delete_inventory, int(character_id))
                        for item in inventory.items.values():
                            slot, index = inventory.equipped_slot(item.instance_id)
                            payload = self._serialize_item_instance(item)
                            await conn.execute(
                                sql_insert_inventory,
                                payload["instance_id"],
                                int(character_id),
                                payload["blueprint_id"],
                                payload["item_type"],
                                payload["quality"],
                                payload["generated_effects"],
                                slot,
                                index,
                                payload["additional_data"],
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


