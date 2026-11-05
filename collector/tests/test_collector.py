import pytest
import requests

from collector import main as collector_main
from collector.config import load_config
from collector.feed import RateLimited

ENV = {"API_511_KEY": "test-key", "DATABASE_URL": "postgresql://x/y"}

FEED = {
    "header": {"timestamp": "1762380000"},
    "entity": [{
        "id": "1",
        "trip_update": {
            "trip": {"trip_id": "T1", "start_date": "20261105"},
            "stop_time_update": [{"stop_id": "S1", "arrival": {"delay": 60}}],
        },
    }],
}


class FakeStore:
    def __init__(self):
        self.saved = []
        self.polls = []
        self.rollbacks = 0

    def save(self, observations, cancellations):
        self.saved.append((observations, cancellations))

    def log_poll(self, **fields):
        self.polls.append(fields)

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(collector_main, "fetch_trip_updates_bytes", lambda *a, **k: b"raw")
    monkeypatch.setattr(collector_main, "decode_feed", lambda raw: FEED)
    return collector_main.Collector(load_config(ENV), FakeStore(), session=object())


def test_poll_saves_and_logs(collector):
    assert collector.poll("SC") == "ok"
    obs, cancels = collector.store.saved[0]
    assert len(obs) == 1 and obs[0].arrival_delay == 60
    assert collector.store.polls[0]["status"] == "ok"
    assert collector.store.polls[0]["n_observations"] == 1


def test_unchanged_feed_is_not_saved_twice(collector):
    collector.poll("SC")
    assert collector.poll("SC") == "unchanged"
    assert len(collector.store.saved) == 1
    # a different agency with the same timestamp is still saved
    assert collector.poll("BA") == "ok"


def test_rate_limit_is_reported(collector, monkeypatch):
    def limited(*a, **k):
        raise RateLimited("429")
    monkeypatch.setattr(collector_main, "fetch_trip_updates_bytes", limited)
    assert collector.poll("SC") == "rate_limited"
    assert collector.store.polls[-1]["status"] == "rate_limited"


def test_network_error_is_survivable(collector, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(collector_main, "fetch_trip_updates_bytes", boom)
    assert collector.poll("SC") == "error"


def test_bad_feed_rolls_back(collector, monkeypatch):
    def bad(raw):
        raise ValueError("corrupt protobuf")
    monkeypatch.setattr(collector_main, "decode_feed", bad)
    assert collector.poll("SC") == "error"
    assert collector.store.rollbacks == 1


def test_config_rejects_polling_too_fast():
    with pytest.raises(SystemExit, match="POLL_INTERVAL_SECONDS >="):
        load_config({**ENV, "POLL_INTERVAL_SECONDS": "60"})  # 2 x 60/hr = 120


def test_config_defaults():
    cfg = load_config(ENV)
    assert cfg.agencies == ("SC", "BA")
    assert cfg.poll_interval_seconds == 180  # 40 requests/hour


def test_config_requires_key():
    with pytest.raises(SystemExit, match="511.org/open-data/token"):
        load_config({"DATABASE_URL": "postgresql://x/y"})
