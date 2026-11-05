"""Poll 511.org GTFS-realtime TripUpdates and store them in Postgres.

Usage:
    python -m collector.main          # run forever
    python -m collector.main --once   # poll each agency once, then exit
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

import requests

from .config import load_config
from .feed import RateLimited, archive_raw, decode_feed, fetch_trip_updates_bytes
from .parse import parse_trip_updates
from .store import Store

log = logging.getLogger("collector")

RATE_LIMIT_BACKOFF_SECONDS = 600


class Collector:
    def __init__(self, config, store: Store, session: requests.Session | None = None):
        self.config = config
        self.store = store
        self.session = session or requests.Session()
        self._last_feed_ts: dict[str, int] = {}

    def poll(self, agency: str) -> str:
        """Fetch, parse and store one agency's feed. Returns the poll status."""
        started = time.monotonic()
        feed_ts = None
        try:
            raw = fetch_trip_updates_bytes(self.session, self.config.api_key, agency)
            if self.config.archive_dir:
                archive_raw(self.config.archive_dir, agency, raw)
            feed = decode_feed(raw)
            feed_ts = int(feed.get("header", {}).get("timestamp") or 0) or None

            if feed_ts is not None and self._last_feed_ts.get(agency) == feed_ts:
                self._log(agency, started, "unchanged", feed_timestamp=feed_ts)
                return "unchanged"

            observations, cancellations = parse_trip_updates(feed, agency)
            self.store.save(observations, cancellations)
            if feed_ts is not None:
                self._last_feed_ts[agency] = feed_ts

            self._log(
                agency, started, "ok",
                feed_timestamp=feed_ts,
                n_entities=len(feed.get("entity") or []),
                n_observations=len(observations),
                n_cancellations=len(cancellations),
            )
            log.info("%s: %d stop updates, %d cancellations",
                     agency, len(observations), len(cancellations))
            return "ok"

        except RateLimited as exc:
            log.warning("%s", exc)
            self._log(agency, started, "rate_limited", error=str(exc))
            return "rate_limited"
        except requests.RequestException as exc:
            log.warning("%s: request failed: %s", agency, exc)
            self._log(agency, started, "error", error=f"request: {exc}")
            return "error"
        except Exception as exc:  # bad feed, parse bug, constraint error...
            log.exception("%s: poll failed", agency)
            self.store.rollback()
            self._log(agency, started, "error", feed_timestamp=feed_ts, error=repr(exc))
            return "error"

    def _log(self, agency: str, started: float, status: str, **fields) -> None:
        duration_ms = int((time.monotonic() - started) * 1000)
        self.store.log_poll(agency=agency, status=status, duration_ms=duration_ms, **fields)


def run_forever(collector: Collector) -> None:
    agencies = collector.config.agencies
    # Spread polls evenly: with 2 agencies every 180s, poll one every 90s.
    gap = collector.config.poll_interval_seconds / len(agencies)

    stopping = False

    def _stop(signum, _frame):
        nonlocal stopping
        log.info("received signal %s, shutting down", signum)
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    i = 0
    while not stopping:
        agency = agencies[i % len(agencies)]
        status = collector.poll(agency)
        i += 1
        wait = RATE_LIMIT_BACKOFF_SECONDS if status == "rate_limited" else gap
        deadline = time.monotonic() + wait
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="poll each agency once and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    log.info(
        "agencies=%s interval=%ss (%.0f requests/hour of %d allowed)",
        ",".join(config.agencies), config.poll_interval_seconds,
        len(config.agencies) * 3600 / config.poll_interval_seconds, config.hourly_limit,
    )

    store = Store(config.database_url)
    store.init_schema()
    collector = Collector(config, store)
    try:
        if args.once:
            results = [collector.poll(a) for a in config.agencies]
            return 0 if all(r in ("ok", "unchanged") for r in results) else 1
        run_forever(collector)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
