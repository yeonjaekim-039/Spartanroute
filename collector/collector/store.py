"""PostgreSQL storage for collector output."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .parse import StopObservation, TripCancellation

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

UPSERT_OBSERVATION = """
INSERT INTO stop_observations (
    agency, trip_id, start_date, stop_id, stop_sequence,
    route_id, direction_id, vehicle_id,
    arrival_time, arrival_delay, departure_time, departure_delay,
    stop_relationship, first_arrival_time, first_arrival_delay, feed_timestamp
) VALUES (
    %(agency)s, %(trip_id)s, %(start_date)s, %(stop_id)s, %(stop_sequence)s,
    %(route_id)s, %(direction_id)s, %(vehicle_id)s,
    %(arrival_time)s, %(arrival_delay)s, %(departure_time)s, %(departure_delay)s,
    %(stop_relationship)s, %(arrival_time)s, %(arrival_delay)s, %(feed_timestamp)s
)
ON CONFLICT (agency, trip_id, start_date, stop_id, stop_sequence) DO UPDATE SET
    route_id          = COALESCE(EXCLUDED.route_id, stop_observations.route_id),
    direction_id      = COALESCE(EXCLUDED.direction_id, stop_observations.direction_id),
    vehicle_id        = COALESCE(EXCLUDED.vehicle_id, stop_observations.vehicle_id),
    arrival_time      = COALESCE(EXCLUDED.arrival_time, stop_observations.arrival_time),
    arrival_delay     = COALESCE(EXCLUDED.arrival_delay, stop_observations.arrival_delay),
    departure_time    = COALESCE(EXCLUDED.departure_time, stop_observations.departure_time),
    departure_delay   = COALESCE(EXCLUDED.departure_delay, stop_observations.departure_delay),
    stop_relationship = EXCLUDED.stop_relationship,
    first_arrival_time  = COALESCE(stop_observations.first_arrival_time, EXCLUDED.arrival_time),
    first_arrival_delay = COALESCE(stop_observations.first_arrival_delay, EXCLUDED.arrival_delay),
    feed_timestamp    = EXCLUDED.feed_timestamp,
    last_seen_at      = now(),
    n_updates         = stop_observations.n_updates + 1
"""

UPSERT_CANCELLATION = """
INSERT INTO trip_cancellations (agency, trip_id, start_date, route_id, feed_timestamp)
VALUES (%(agency)s, %(trip_id)s, %(start_date)s, %(route_id)s, %(feed_timestamp)s)
ON CONFLICT (agency, trip_id, start_date) DO UPDATE SET
    route_id       = COALESCE(EXCLUDED.route_id, trip_cancellations.route_id),
    feed_timestamp = EXCLUDED.feed_timestamp,
    last_seen_at   = now()
"""

INSERT_POLL = """
INSERT INTO feed_polls (
    agency, feed_timestamp, status, n_entities, n_observations,
    n_cancellations, duration_ms, error
) VALUES (
    %(agency)s, %(feed_timestamp)s, %(status)s, %(n_entities)s, %(n_observations)s,
    %(n_cancellations)s, %(duration_ms)s, %(error)s
)
"""


class Store:
    def __init__(self, database_url: str):
        import psycopg  # imported lazily so parser tests don't need it

        self._conn = psycopg.connect(database_url, autocommit=False)

    def init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text())
        self._conn.commit()

    def save(
        self,
        observations: list[StopObservation],
        cancellations: list[TripCancellation],
    ) -> None:
        with self._conn.cursor() as cur:
            if observations:
                cur.executemany(UPSERT_OBSERVATION, [asdict(o) for o in observations])
            if cancellations:
                cur.executemany(UPSERT_CANCELLATION, [asdict(c) for c in cancellations])
        self._conn.commit()

    def log_poll(self, **fields) -> None:
        row = {
            "agency": None, "feed_timestamp": None, "status": "error",
            "n_entities": None, "n_observations": None, "n_cancellations": None,
            "duration_ms": None, "error": None,
        }
        row.update(fields)
        try:
            with self._conn.cursor() as cur:
                cur.execute(INSERT_POLL, row)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
