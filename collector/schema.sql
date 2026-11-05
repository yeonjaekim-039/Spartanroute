-- SpartanRoute collector schema (PostgreSQL). Safe to run repeatedly.

-- One row per (trip, service day, stop). Each poll overwrites the prediction,
-- so once the vehicle passes the stop and it drops out of the feed, the last
-- stored value is (approximately) what actually happened.
CREATE TABLE IF NOT EXISTS stop_observations (
    agency              TEXT        NOT NULL,
    trip_id             TEXT        NOT NULL,
    start_date          TEXT        NOT NULL,   -- GTFS service date, YYYYMMDD
    stop_id             TEXT        NOT NULL,
    stop_sequence       INTEGER     NOT NULL DEFAULT -1,
    route_id            TEXT,
    direction_id        SMALLINT,
    vehicle_id          TEXT,

    -- Latest prediction (becomes the observed value once the stop is passed)
    arrival_time        BIGINT,                 -- unix seconds
    arrival_delay       INTEGER,                -- seconds late (+) / early (-)
    departure_time      BIGINT,
    departure_delay     INTEGER,
    stop_relationship   TEXT        NOT NULL DEFAULT 'SCHEDULED',

    -- First prediction we ever saw, for measuring how good predictions are
    first_arrival_time  BIGINT,
    first_arrival_delay INTEGER,

    feed_timestamp      BIGINT,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_updates           INTEGER     NOT NULL DEFAULT 1,

    PRIMARY KEY (agency, trip_id, start_date, stop_id, stop_sequence)
);

CREATE INDEX IF NOT EXISTS stop_obs_route_idx
    ON stop_observations (agency, route_id, start_date);
CREATE INDEX IF NOT EXISTS stop_obs_stop_idx
    ON stop_observations (agency, stop_id, arrival_time);

-- Canceled trips count as "very late" for reliability, so keep them.
CREATE TABLE IF NOT EXISTS trip_cancellations (
    agency          TEXT        NOT NULL,
    trip_id         TEXT        NOT NULL,
    start_date      TEXT        NOT NULL,
    route_id        TEXT,
    feed_timestamp  BIGINT,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agency, trip_id, start_date)
);

-- One row per poll: lightweight monitoring ("is the collector alive?").
CREATE TABLE IF NOT EXISTS feed_polls (
    id              BIGSERIAL   PRIMARY KEY,
    agency          TEXT        NOT NULL,
    polled_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    feed_timestamp  BIGINT,
    status          TEXT        NOT NULL,   -- ok | unchanged | rate_limited | error
    n_entities      INTEGER,
    n_observations  INTEGER,
    n_cancellations INTEGER,
    duration_ms     INTEGER,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS feed_polls_time_idx ON feed_polls (agency, polled_at DESC);
