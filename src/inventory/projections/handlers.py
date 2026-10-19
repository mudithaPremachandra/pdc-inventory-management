"""Project stored events into the inventory read models."""

from datetime import datetime, timezone


def _occurred_at(event):
    return event.occurred_at or datetime.now(timezone.utc)


def _actor(event):
    return (event.metadata or {}).get("user")


def apply_event(cur, event):
    """Apply one stored event to the appropriate read model."""
    data = event.data
    event_type = event.event_type
    occurred_at = _occurred_at(event)
    actor = _actor(event)

    if event_type == "ProductRegistered":
        cur.execute(
            """
            INSERT INTO read.products
                (sku, name, category, unit_price, reorder_level,
                 quantity, status, version, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 0, 'active', %s, %s, %s)
            ON CONFLICT (sku) DO NOTHING
            """,
            (
                data["sku"], data["name"], data.get("category"),
                data["unit_price"], data["reorder_level"],
                event.version, occurred_at, occurred_at,
            ),
        )

    elif event_type == "ProductDetailsUpdated":
        cur.execute(
            """
            UPDATE read.products
            SET name = COALESCE(%s, name),
                category = COALESCE(%s, category),
                unit_price = COALESCE(%s, unit_price),
                reorder_level = COALESCE(%s, reorder_level),
                version = %s,
                updated_at = %s
            WHERE sku = %s AND version < %s
            """,
            (
                data.get("name"), data.get("category"),
                data.get("unit_price"), data.get("reorder_level"),
                event.version, occurred_at, data["sku"], event.version,
            ),
        )

    elif event_type in (
        "StockReceived", "StockDispatched", "StockAdjusted"
    ):
        if event_type == "StockReceived":
            movement_type = "received"
            quantity_change = data["quantity"]
        elif event_type == "StockDispatched":
            movement_type = "dispatched"
            quantity_change = -data["quantity"]
        else:
            movement_type = "adjusted"
            quantity_change = data["quantity_change"]

        cur.execute(
            """
            UPDATE read.products
            SET quantity = quantity + %s,
                version = %s,
                updated_at = %s
            WHERE sku = %s AND version < %s
            RETURNING quantity
            """,
            (
                quantity_change, event.version, occurred_at,
                data["sku"], event.version,
            ),
        )
        row = cur.fetchone()

        if row is not None:
            cur.execute(
                """
                INSERT INTO read.stock_movements
                    (global_position, sku, movement_type,
                     quantity_change, quantity_after, reference,
                     performed_by, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (global_position) DO NOTHING
                """,
                (
                    event.global_position, data["sku"], movement_type,
                    quantity_change, row["quantity"],
                    data.get("reference"), actor, occurred_at,
                ),
            )

    elif event_type == "ProductDiscontinued":
        cur.execute(
            """
            UPDATE read.products
            SET status = 'discontinued',
                version = %s,
                updated_at = %s
            WHERE sku = %s AND version < %s
            """,
            (
                event.version, occurred_at, data["sku"], event.version,
            ),
        )

    elif event_type == "UserRegistered":
        cur.execute(
            """
            INSERT INTO read.users
                (username, role, active, created_at, updated_at)
            VALUES (%s, %s, TRUE, %s, %s)
            ON CONFLICT (username) DO NOTHING
            """,
            (
                data["username"], data["role"],
                occurred_at, occurred_at,
            ),
        )

    elif event_type == "UserRoleChanged":
        cur.execute(
            """
            UPDATE read.users
            SET role = %s, updated_at = %s
            WHERE username = %s
            """,
            (data["new_role"], occurred_at, data["username"]),
        )

    elif event_type == "UserDeactivated":
        cur.execute(
            """
            UPDATE read.users
            SET active = FALSE, updated_at = %s
            WHERE username = %s
            """,
            (occurred_at, data["username"]),
        )

    elif event_type == "UserReactivated":
        cur.execute(
            """
            UPDATE read.users
            SET active = TRUE, updated_at = %s
            WHERE username = %s
            """,
            (occurred_at, data["username"]),
        )

    elif event_type == "UserPasswordChanged":
        # Password hashes must never be copied into the read model.
        pass

    else:
        raise ValueError(f"Unsupported projection event: {event_type}")