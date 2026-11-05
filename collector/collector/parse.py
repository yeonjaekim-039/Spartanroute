"""Turn a decoded GTFS-realtime TripUpdates feed into rows we can store.

The parser works on the plain-dict form of the feed (what
`google.protobuf.json_format.MessageToDict(feed, preserving_proto_field_name=True)`
returns). Keeping it dict-based means the logic is pure and easy to unit test
without protobuf fixtures.

Notes on the dict form:
  * 64-bit ints (timestamps, `time`) arrive as strings -> we cast with int().
  * Enums arrive as their names ("SCHEDULED", "SKIPPED", "CANCELED", ...).
  * Fields at their default value may be missing entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

# Trips that run after midnight still belong to the previous service day.
# When a feed omits start_date we shift the clock back this much before
# taking the local date, so a 1:30 AM trip lands on yesterday's service day.
SERVICE_DAY_ROLLOVER = timedelta(hours=3)


@dataclass(frozen=True)
class StopObservation:
    agency: str
    trip_id: str
    start_date: str  # YYYYMMDD service date
    stop_id: str
    stop_sequence: int  # -1 when the feed does not provide it
    route_id: str | None
    direction_id: int | None
    vehicle_id: str | None
    arrival_time: int | None  # unix seconds (predicted or actual)
    arrival_delay: int | None  # seconds vs schedule, if the feed provides it
    departure_time: int | None
    departure_delay: int | None
    stop_relationship: str  # SCHEDULED | SKIPPED
    feed_timestamp: int | None


@dataclass(frozen=True)
class TripCancellation:
    agency: str
    trip_id: str
    start_date: str
    route_id: str | None
    feed_timestamp: int | None


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def service_date_from(ts: int | None, fallback: datetime | None = None) -> str:
    """Best-guess GTFS service date (YYYYMMDD) for a moment in time."""
    if ts is not None:
        moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        moment = fallback or datetime.now(tz=timezone.utc)
    local = moment.astimezone(PACIFIC) - SERVICE_DAY_ROLLOVER
    return local.strftime("%Y%m%d")


def parse_trip_updates(
    feed: dict, agency: str
) -> tuple[list[StopObservation], list[TripCancellation]]:
    header = feed.get("header") or {}
    feed_ts = _to_int(header.get("timestamp"))

    observations: list[StopObservation] = []
    cancellations: list[TripCancellation] = []

    for entity in feed.get("entity") or []:
        if entity.get("is_deleted"):
            continue
        tu = entity.get("trip_update")
        if not tu:
            continue  # vehicle positions / alerts mixed into the feed

        trip = tu.get("trip") or {}
        trip_id = trip.get("trip_id")
        if not trip_id:
            continue  # can't join to the schedule without a trip_id

        entity_ts = _to_int(tu.get("timestamp")) or feed_ts
        start_date = trip.get("start_date") or service_date_from(entity_ts)
        route_id = trip.get("route_id")
        direction_id = _to_int(trip.get("direction_id"))
        vehicle_id = (tu.get("vehicle") or {}).get("id")

        if trip.get("schedule_relationship") in ("CANCELED", "DELETED"):
            cancellations.append(
                TripCancellation(agency, trip_id, start_date, route_id, entity_ts)
            )
            continue

        for stu in tu.get("stop_time_update") or []:
            relationship = stu.get("schedule_relationship") or "SCHEDULED"
            if relationship == "NO_DATA":
                continue
            stop_id = stu.get("stop_id")
            stop_sequence = _to_int(stu.get("stop_sequence"))
            if not stop_id and stop_sequence is None:
                continue

            arrival = stu.get("arrival") or {}
            departure = stu.get("departure") or {}
            arr_time = _to_int(arrival.get("time"))
            arr_delay = _to_int(arrival.get("delay"))
            dep_time = _to_int(departure.get("time"))
            dep_delay = _to_int(departure.get("delay"))

            nothing_measured = all(
                v is None for v in (arr_time, arr_delay, dep_time, dep_delay)
            )
            if relationship != "SKIPPED" and nothing_measured:
                continue

            observations.append(
                StopObservation(
                    agency=agency,
                    trip_id=trip_id,
                    start_date=start_date,
                    stop_id=stop_id or "",
                    stop_sequence=stop_sequence if stop_sequence is not None else -1,
                    route_id=route_id,
                    direction_id=direction_id,
                    vehicle_id=vehicle_id,
                    arrival_time=arr_time,
                    arrival_delay=arr_delay,
                    departure_time=dep_time,
                    departure_delay=dep_delay,
                    stop_relationship=relationship,
                    feed_timestamp=entity_ts,
                )
            )

    return observations, cancellations
