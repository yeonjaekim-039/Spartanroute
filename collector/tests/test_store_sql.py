"""Integration test against a real Postgres. Skipped unless TEST_DATABASE_URL is set
(CI sets it; locally: `docker compose up -d db` and export the URL)."""

import os

import pytest

from collector.parse import parse_trip_updates

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


def feed(delay, ts):
    return {
        "header": {"timestamp": str(ts)},
        "entity": [
            {"id": "1", "trip_update": {
                "trip": {"trip_id": "T1", "route_id": "22", "start_date": "20261105"},
                "stop_time_update": [{"stop_sequence": 1, "stop_id": "S1",
                                      "arrival": {"delay": delay, "time": str(ts + 600)}}],
            }},
            {"id": "2", "trip_update": {
                "trip": {"trip_id": "T2", "start_date": "20261105",
                         "schedule_relationship": "CANCELED"}}},
        ],
    }


@pytest.fixture
def store():
    psycopg = pytest.importorskip("psycopg")
    from collector.store import Store

    s = Store(DB_URL)
    with s._conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS stop_observations, trip_cancellations, feed_polls")
    s._conn.commit()
    s.init_schema()
    s.init_schema()  # idempotent
    yield s
    s.close()


def test_upsert_keeps_first_and_latest_prediction(store):
    store.save(*parse_trip_updates(feed(60, 1000), "SC"))
    store.save(*parse_trip_updates(feed(240, 1100), "SC"))
    with store._conn.cursor() as cur:
        cur.execute("SELECT arrival_delay, first_arrival_delay, n_updates FROM stop_observations")
        assert cur.fetchall() == [(240, 60, 2)]
        cur.execute("SELECT count(*) FROM trip_cancellations")
        assert cur.fetchone() == (1,)


def test_log_poll(store):
    store.log_poll(agency="SC", status="ok", n_observations=3, duration_ms=12)
    with store._conn.cursor() as cur:
        cur.execute("SELECT agency, status, n_observations FROM feed_polls")
        assert cur.fetchall() == [("SC", "ok", 3)]
