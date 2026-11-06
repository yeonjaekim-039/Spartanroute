import json
from pathlib import Path

import pytest

from routing.otp_client import OTPError, dedupe, parse_plan

FIXTURE = Path(__file__).parent / "fixtures" / "plan_milpitas_to_sjsu.json"


@pytest.fixture
def itineraries():
    return parse_plan(json.loads(FIXTURE.read_text()))


def test_parses_all_itineraries(itineraries):
    assert len(itineraries) == 3


def test_route_and_stop_ids_use_collector_agency_codes(itineraries):
    for it in itineraries:
        for leg in it.transit_legs:
            assert leg.agency in {"SC", "BA"}
            assert leg.from_stop_id.split(":")[0] in {"SC", "BA"}


def test_walk_legs_have_no_route(itineraries):
    walks = [leg for it in itineraries for leg in it.legs if leg.mode == "WALK"]
    assert walks and all(leg.route_id is None and not leg.is_transit for leg in walks)


def test_origin_and_destination_have_no_stop(itineraries):
    it = itineraries[0]
    assert it.legs[0].from_stop_id is None
    assert it.legs[-1].to_stop_id is None


def test_transfers_and_duration(itineraries):
    bus, bart = itineraries[0], itineraries[1]
    assert bus.transfers == 0 and bus.duration_min == 40
    assert bart.transfers == 1
    assert [leg.route_id for leg in bart.transit_legs] == ["BA:Orange-S", "SC:Rapid 500"]


def test_times_are_pacific(itineraries):
    it = itineraries[0]
    assert (it.start.hour, it.start.minute) == (7, 40)
    assert it.start.utcoffset().total_seconds() == -8 * 3600


def test_dedupe_keeps_latest_trip_of_each_route(itineraries):
    unique = dedupe(itineraries)
    assert len(unique) == 2
    bus = next(it for it in unique if it.transit_legs[0].route_id == "SC:66")
    assert bus.transit_legs[0].trip_id == "SC:6601"  # the 7:40 trip, not 7:25


def test_summary(itineraries):
    assert itineraries[1].summary() == "07:48→08:26 (38 min, 1 transfer(s)): Orange-S → Rapid 500"


def test_graphql_errors_raise():
    with pytest.raises(OTPError, match="bad field"):
        parse_plan({"errors": [{"message": "bad field"}]})


def test_no_routes_found_returns_empty():
    assert parse_plan({"data": {"plan": {"itineraries": []}}}) == []
