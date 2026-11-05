from collector.parse import parse_trip_updates, service_date_from

# Shape matches MessageToDict(feed, preserving_proto_field_name=True):
# 64-bit ints are strings, enums are names, default fields are omitted.
FEED = {
    "header": {"gtfs_realtime_version": "2.0", "timestamp": "1762380000"},
    "entity": [
        {   # normal trip with two stops, delay given
            "id": "1",
            "trip_update": {
                "trip": {"trip_id": "T22-1", "route_id": "22", "start_date": "20261105",
                         "direction_id": 1},
                "vehicle": {"id": "bus-4021"},
                "stop_time_update": [
                    {"stop_sequence": 5, "stop_id": "S100",
                     "arrival": {"delay": 120, "time": "1762380120"},
                     "departure": {"delay": 130, "time": "1762380130"}},
                    {"stop_sequence": 6, "stop_id": "S101",
                     "arrival": {"time": "1762380300"}},  # time only, no delay
                ],
            },
        },
        {   # canceled trip
            "id": "2",
            "trip_update": {
                "trip": {"trip_id": "T23-9", "route_id": "23", "start_date": "20261105",
                         "schedule_relationship": "CANCELED"},
            },
        },
        {   # skipped stop + NO_DATA stop
            "id": "3",
            "trip_update": {
                "trip": {"trip_id": "T500-2", "route_id": "500"},  # no start_date
                "timestamp": "1762400000",
                "stop_time_update": [
                    {"stop_sequence": 1, "stop_id": "A", "schedule_relationship": "SKIPPED"},
                    {"stop_sequence": 2, "stop_id": "B", "schedule_relationship": "NO_DATA"},
                    {"stop_sequence": 3, "stop_id": "C"},  # no times at all
                    {"stop_id": "D", "departure": {"delay": -30}},  # no stop_sequence
                ],
            },
        },
        {"id": "4", "vehicle": {"trip": {"trip_id": "X"}}},          # not a trip update
        {"id": "5", "trip_update": {"trip": {"route_id": "22"}}},     # no trip_id
        {"id": "6", "is_deleted": True, "trip_update": {"trip": {"trip_id": "gone"}}},
    ],
}


def by_key(observations):
    return {(o.trip_id, o.stop_id): o for o in observations}


def test_parses_normal_stops():
    obs, _ = parse_trip_updates(FEED, "SC")
    s100 = by_key(obs)[("T22-1", "S100")]
    assert s100.agency == "SC"
    assert s100.start_date == "20261105"
    assert s100.stop_sequence == 5
    assert s100.arrival_delay == 120
    assert s100.arrival_time == 1762380120  # string -> int
    assert s100.departure_delay == 130
    assert s100.vehicle_id == "bus-4021"
    assert s100.direction_id == 1
    assert s100.feed_timestamp == 1762380000


def test_time_only_update_keeps_delay_none():
    obs, _ = parse_trip_updates(FEED, "SC")
    s101 = by_key(obs)[("T22-1", "S101")]
    assert s101.arrival_time == 1762380300
    assert s101.arrival_delay is None


def test_cancellations_are_separate():
    obs, cancels = parse_trip_updates(FEED, "SC")
    assert [c.trip_id for c in cancels] == ["T23-9"]
    assert cancels[0].route_id == "23"
    assert all(o.trip_id != "T23-9" for o in obs)


def test_skipped_kept_no_data_and_empty_dropped():
    obs, _ = parse_trip_updates(FEED, "SC")
    keys = by_key(obs)
    assert keys[("T500-2", "A")].stop_relationship == "SKIPPED"
    assert ("T500-2", "B") not in keys  # NO_DATA
    assert ("T500-2", "C") not in keys  # nothing measured


def test_missing_stop_sequence_defaults_to_minus_one():
    obs, _ = parse_trip_updates(FEED, "SC")
    d = by_key(obs)[("T500-2", "D")]
    assert d.stop_sequence == -1
    assert d.departure_delay == -30


def test_missing_start_date_uses_entity_timestamp():
    obs, _ = parse_trip_updates(FEED, "SC")
    a = by_key(obs)[("T500-2", "A")]
    assert a.start_date == service_date_from(1762400000)
    assert a.feed_timestamp == 1762400000


def test_ignores_non_trip_entities_and_deleted():
    obs, cancels = parse_trip_updates(FEED, "SC")
    trip_ids = {o.trip_id for o in obs} | {c.trip_id for c in cancels}
    assert trip_ids == {"T22-1", "T23-9", "T500-2"}


def test_empty_feed():
    assert parse_trip_updates({}, "BA") == ([], [])


def test_service_date_rolls_back_after_midnight():
    # 2026-11-06 01:30 Pacific belongs to the 11/05 service day
    assert service_date_from(1793957400) == "20261105"
    # 2026-11-06 08:00 Pacific belongs to 11/06
    assert service_date_from(1793980800) == "20261106"
