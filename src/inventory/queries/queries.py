
from psycopg_pool import ConnectionPool

from inventory.domain.errors import NotFound
from inventory.projections.projector import PROJECTION_NAME


def _all(pool: ConnectionPool, sql: str, params=()) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def _one(pool: ConnectionPool, sql: str, params=()) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def list_products(pool: ConnectionPool, search: str | None = None, include_discontinued: bool = False) -> list[dict]:
    sql = "SELECT * FROM read.products WHERE TRUE"
    params: list = []
    if not include_discontinued:
        sql += " AND status = 'active'"
    if search:
        sql += " AND (sku ILIKE %s OR name ILIKE %s OR category ILIKE %s)"
        params += [f"%{search}%"] * 3
    return _all(pool, sql + " ORDER BY sku", params)


def get_product(pool: ConnectionPool, sku: str) -> dict:
    row = _one(pool, "SELECT * FROM read.products WHERE sku = %s", (sku.upper(),))
    if row is None:
        raise NotFound(f"product {sku.upper()} not found (if you just created it, the projector may still be catching up)")
    return row


def stock_history(pool: ConnectionPool, sku: str, limit: int = 50) -> list[dict]:
    get_product(pool, sku)
    return _all(
        pool,
        """
        SELECT * FROM (
            SELECT * FROM read.stock_movements WHERE sku = %s ORDER BY global_position DESC LIMIT %s
        ) latest ORDER BY global_position
        """,
        (sku.upper(), limit),
    )


def low_stock(pool: ConnectionPool) -> list[dict]:
    return _all(
        pool,
        """
        SELECT sku, name, quantity, reorder_level, reorder_level - quantity AS shortfall
        FROM read.products
        WHERE status = 'active' AND quantity <= reorder_level
        ORDER BY shortfall DESC, sku
        """,
    )


def stock_valuation(pool: ConnectionPool) -> dict:
    by_category = _all(
        pool,
        """
        SELECT COALESCE(category, '(none)') AS category,
               COUNT(*) AS products,
               SUM(quantity) AS units,
               SUM(quantity * unit_price) AS value
        FROM read.products
        WHERE status = 'active'
        GROUP BY 1 ORDER BY 1
        """,
    )
    total = sum((row["value"] for row in by_category), start=0)
    return {"categories": by_category, "total_value": total}


def list_users(pool: ConnectionPool) -> list[dict]:
    return _all(pool, "SELECT * FROM read.users ORDER BY username")


def event_log(pool: ConnectionPool, stream_id: str | None = None, limit: int = 50) -> list[dict]:
    """Raw events, newest last. Reads the event store directly: it is the audit log."""
    sql = "SELECT global_position, stream_id, version, event_type, data, metadata, occurred_at FROM events"
    params: list = []
    if stream_id:
        sql += " WHERE stream_id = %s"
        params.append(stream_id)
    sql = f"SELECT * FROM ({sql} ORDER BY global_position DESC LIMIT %s) latest ORDER BY global_position"
    params.append(limit)
    rows = _all(pool, sql, params)
    for row in rows:
        # User events carry password hashes; never send them to the read side.
        if "password_hash" in row["data"]:
            row["data"] = {**row["data"], "password_hash": "***"}
    return rows


def projection_status(pool: ConnectionPool) -> dict:
    """How far behind the read side is: the gap between the event store and the checkpoint."""
    row = _one(
        pool,
        """
        SELECT (SELECT COALESCE(MAX(global_position), 0) FROM events) AS head_position,
               COALESCE((SELECT last_position FROM read.projection_checkpoints
                         WHERE projection_name = %s), 0) AS checkpoint
        """,
        (PROJECTION_NAME,),
    )
    return {**row, "lag": row["head_position"] - row["checkpoint"]}
