import json
import logging
from enum import Enum
import asyncpg

logger = logging.getLogger(__name__)

class SupabaseOperation(Enum):
    INSERT = "insert"
    UPSERT = "upsert"
    UPDATE = "update"
    DELETE = "delete"

async def safe_execute(pool: asyncpg.Pool, schema: str, table: str, data: dict, operation: SupabaseOperation, filters: dict | None = None) -> None:
    table = f"{schema}.{table}"
    columns = list(data.keys())
    values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in data.values()]

    col_list = ", ".join(columns)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))

    try:
        async with pool.acquire() as conn:
            match operation:
                case SupabaseOperation.INSERT:
                    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
                    await conn.execute(sql, *values)

                case SupabaseOperation.UPSERT:
                    sql = (
                        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                        f"ON CONFLICT DO NOTHING"
                    )
                    await conn.execute(sql, *values)

                case SupabaseOperation.UPDATE:
                    if not filters:
                        raise ValueError("UPDATE requires filters for WHERE clause")
                    set_parts = [f"{col} = ${i + 1}" for i, col in enumerate(columns)]
                    set_clause = ", ".join(set_parts)
                    offset = len(columns)
                    where_parts = [f"{col} = ${i + offset + 1}" for i, col in enumerate(filters.keys())]
                    where_clause = " AND ".join(where_parts)
                    filter_values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in filters.values()]
                    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
                    await conn.execute(sql, *values, *filter_values)

        logger.info(f"{operation.value.upper()} into {table}: {data}")

    except asyncpg.PostgresError as e:
        logger.error(f"DB error in safe_execute ({operation.value} {table}): {e}")
    except Exception as e:
        logger.error(f"Unexpected error in safe_execute: {e}", exc_info=True)

async def safe_get_db_data(
    pool: asyncpg.Pool,
    schema: str,
    table: str,
    columns: str = "*",
    filters: dict | None = None,
    additional = ''
) -> list[dict] | None:
    sql_table = f"{schema}.{table}"
    sql = f"SELECT {columns} FROM {sql_table}"
    params: list = []

    if filters:
        conditions = [f"{col} = ${i + 1}" for i, col in enumerate(filters.keys())]
        params = list(filters.values())
        sql += " WHERE " + " AND ".join(conditions)
    
    if additional:
        sql += " " + additional

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(row) for row in rows]
    except asyncpg.PostgresError as e:
        logger.error(f"DB error in safe_get_db_data ({sql_table}): {e}")
    except Exception as e:
        logger.error(f"Unexpected error in safe_get_db_data: {e}", exc_info=True)
    return None
