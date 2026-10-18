
CREATE SCHEMA IF NOT EXISTS read;

-- Current state of each product, one row per SKU.
CREATE TABLE IF NOT EXISTS read.products (
    sku            TEXT PRIMARY KEY,
    name           TEXT           NOT NULL,
    category       TEXT,
    unit_price     NUMERIC(12, 2) NOT NULL,
    reorder_level  INTEGER        NOT NULL,
    quantity       INTEGER        NOT NULL DEFAULT 0,
    status         TEXT           NOT NULL DEFAULT 'active',
    version        INTEGER        NOT NULL,
    created_at     TIMESTAMPTZ    NOT NULL,
    updated_at     TIMESTAMPTZ    NOT NULL
);

-- Every stock change as a ledger line, for the `history` command.
-- global_position as the key makes re-applying the same event a no-op (idempotent).
CREATE TABLE IF NOT EXISTS read.stock_movements (
    global_position BIGINT PRIMARY KEY,
    sku             TEXT        NOT NULL,
    movement_type   TEXT        NOT NULL,
    quantity_change INTEGER     NOT NULL,
    quantity_after  INTEGER     NOT NULL,
    reference       TEXT,
    performed_by    TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_movements_sku ON read.stock_movements (sku, global_position);

-- User list for the admin `users` command. Never stores password hashes.
CREATE TABLE IF NOT EXISTS read.users (
    username    TEXT PRIMARY KEY,
    role        TEXT        NOT NULL,
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);

-- How far the projector has read in the event log.
CREATE TABLE IF NOT EXISTS read.projection_checkpoints (
    projection_name TEXT PRIMARY KEY,
    last_position   BIGINT      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
