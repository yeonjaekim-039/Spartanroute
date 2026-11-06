"""Ask OpenTripPlanner for candidate itineraries and turn them into clean objects.

Phase 2 output. Phase 3 (scoring) takes the Itinerary objects from here, looks up
each transit leg's delay history by (route_id, stop_id, hour) in stop_observations,
and computes P(late).

Uses only the standard library so it runs anywhere without extra installs.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_URL = "http://localhost:8080/otp/gtfs/v1"
TRANSIT_MODES = {"BUS", "SUBWAY", "RAIL", "TRAM", "FERRY"}

PLAN_QUERY = """
query Plan($fromLat: Float!, $fromLon: Float!, $toLat: Float!, $toLon: Float!,
           $date: String!, $time: String!, $arriveBy: Boolean!, $n: Int!) {
  plan(from: {lat: $fromLat, lon: $fromLon}, to: {lat: $toLat, lon: $toLon},
       date: $date, time: $time, arriveBy: $arriveBy, numItineraries: $n) {
    itineraries {
      startTime
      endTime
      duration
      walkDistance
      legs {
        mode
        startTime
        endTime
        distance
        route { gtfsId shortName }
        trip { gtfsId }
        from { name stop { gtfsId } }
        to { name stop { gtfsId } }
      }
    }
  }
}
"""


class OTPError(RuntimeError):
    """OTP was unreachable or returned GraphQL errors."""


@dataclass(frozen=True)
class Leg:
    mode: str                  # WALK, BUS, SUBWAY, ...
    start: datetime            # scheduled departure (Pacific time)
    end: datetime              # scheduled arrival (Pacific time)
    distance_m: float
    from_name: str
    to_name: str
    route_id: str | None = None      # "SC:66", "BA:Orange-S"; None for walking
    route_name: str | None = None    # "66", "Rapid 500"
    trip_id: str | None = None
    from_stop_id: str | None = None  # "SC:12345"; None at origin/destination
    to_stop_id: str | None = None

    @property
    def is_transit(self) -> bool:
        return self.mode in TRANSIT_MODES

    @property
    def agency(self) -> str | None:
        """Feed prefix: "SC" or "BA". Matches the collector's agency codes."""
        return self.route_id.split(":", 1)[0] if self.route_id else None

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass(frozen=True)
class Itinerary:
    start: datetime
    end: datetime
    walk_m: float
    legs: tuple[Leg, ...] = field(default_factory=tuple)

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    @property
    def transit_legs(self) -> tuple[Leg, ...]:
        return tuple(leg for leg in self.legs if leg.is_transit)

    @property
    def transfers(self) -> int:
        return max(len(self.transit_legs) - 1, 0)

    @property
    def signature(self) -> tuple:
        """Same routes boarded at the same stops = the same option at a different time."""
        return tuple((leg.route_id, leg.from_stop_id) for leg in self.transit_legs)

    def summary(self) -> str:
        parts = [leg.route_name or leg.mode for leg in self.transit_legs] or ["WALK"]
        return (f"{self.start:%H:%M}→{self.end:%H:%M} "
                f"({self.duration_min:.0f} min, {self.transfers} transfer(s)): "
                + " → ".join(parts))


def _ms_to_local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(PACIFIC)


def _stop_id(place: dict) -> str | None:
    stop = place.get("stop")
    return stop["gtfsId"] if stop else None


def parse_leg(raw: dict) -> Leg:
    route = raw.get("route") or {}
    trip = raw.get("trip") or {}
    return Leg(
        mode=raw["mode"],
        start=_ms_to_local(raw["startTime"]),
        end=_ms_to_local(raw["endTime"]),
        distance_m=raw.get("distance") or 0.0,
        from_name=raw["from"]["name"],
        to_name=raw["to"]["name"],
        route_id=route.get("gtfsId"),
        route_name=route.get("shortName"),
        trip_id=trip.get("gtfsId"),
        from_stop_id=_stop_id(raw["from"]),
        to_stop_id=_stop_id(raw["to"]),
    )


def parse_plan(response: dict) -> list[Itinerary]:
    """Turn OTP's raw JSON response into Itinerary objects."""
    if response.get("errors"):
        raise OTPError("; ".join(e.get("message", str(e)) for e in response["errors"]))
    raw_its = ((response.get("data") or {}).get("plan") or {}).get("itineraries") or []
    return [
        Itinerary(
            start=_ms_to_local(it["startTime"]),
            end=_ms_to_local(it["endTime"]),
            walk_m=it.get("walkDistance") or 0.0,
            legs=tuple(parse_leg(leg) for leg in it["legs"]),
        )
        for it in raw_its
    ]


def dedupe(itineraries: list[Itinerary]) -> list[Itinerary]:
    """Keep only the latest-departing trip of each distinct route option.

    For an arrive-by query OTP often returns the same route on two different
    trips. The later one is the one a student would actually take.
    """
    best: dict[tuple, Itinerary] = {}
    for it in itineraries:
        current = best.get(it.signature)
        if current is None or it.start > current.start:
            best[it.signature] = it
    return sorted(best.values(), key=lambda it: it.start, reverse=True)


def plan(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float,
    arrive_by: datetime, *, n: int = 5, url: str = DEFAULT_URL, timeout: float = 30,
) -> list[Itinerary]:
    """Candidate itineraries arriving by `arrive_by` (Pacific time), duplicates removed."""
    local = arrive_by.astimezone(PACIFIC) if arrive_by.tzinfo else arrive_by.replace(tzinfo=PACIFIC)
    body = json.dumps({
        "query": PLAN_QUERY,
        "variables": {
            "fromLat": from_lat, "fromLon": from_lon, "toLat": to_lat, "toLon": to_lon,
            "date": local.strftime("%Y-%m-%d"), "time": local.strftime("%H:%M"),
            "arriveBy": True, "n": n,
        },
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response = json.load(resp)
    except OSError as e:
        raise OTPError(f"could not reach OTP at {url}: {e}") from e
    return dedupe(parse_plan(response))


if __name__ == "__main__":
    # Smoke test: Milpitas BART → SJSU, arriving by 8:30 next Monday.
    from datetime import timedelta
    today = datetime.now(PACIFIC)
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    target = monday.replace(hour=8, minute=30, second=0, microsecond=0)
    for it in plan(37.4103, -121.8913, 37.3374, -121.8817, target):
        print(it.summary())
        for leg in it.transit_legs:
            print(f"    {leg.route_id:<14} board {leg.from_stop_id} at {leg.start:%H:%M}")
