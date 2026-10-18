

CREATE TABLE IF NOT EXISTS events (
    -- Position in the global log. The projector reads events in this order.
    global_position BIGSERIAL PRIMARY KEY,
    -- Which aggregate instance the event belongs to, e.g. 'product-SKU-001' or 'user-admin'.
    stream_id       TEXT        NOT NULL,
    stream_type     TEXT        NOT NULL,
    -- 1, 2, 3, ... within one stream. Used for optimistic concurrency.
    version         INTEGER     NOT NULL CHECK (version > 0),
    event_type      TEXT        NOT NULL,
    data            JSONB       NOT NULL,
    -- Who/why: user, command name, correlation id. Not part of the domain state.
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Two writers cannot both append version N to the same stream:
    -- the second INSERT fails, which is how optimistic concurrency is enforced.
    CONSTRAINT uq_stream_version UNIQUE (stream_id, version)
);

CREATE INDEX IF NOT EXISTS ix_events_type ON events (event_type);

-- Append-only: refuse UPDATE, DELETE and TRUNCATE. History cannot be rewritten.
CREATE OR REPLACE FUNCTION events_are_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'events table is append-only (% is not allowed)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_events_no_update_delete ON events;
CREATE TRIGGER trg_events_no_update_delete
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION events_are_immutable();

DROP TRIGGER IF EXISTS trg_events_no_truncate ON events;
CREATE TRIGGER trg_events_no_truncate
    BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION events_are_immutable();

-- Wake the projector as soon as something is appended (it also polls as a fallback).
CREATE OR REPLACE FUNCTION notify_event_appended() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('events_appended', NEW.global_position::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_events_notify ON events;
CREATE TRIGGER trg_events_notify
    AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION notify_event_appended();
