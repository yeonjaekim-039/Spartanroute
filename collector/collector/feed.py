"""Download and decode GTFS-realtime feeds from 511.org."""

from __future__ import annotations

import gzip
import os
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.511.org/transit"
USER_AGENT = "SpartanRoute-collector/0.1"


class RateLimited(Exception):
    """511 returned HTTP 429."""


def fetch_trip_updates_bytes(
    session: requests.Session, api_key: str, agency: str, timeout: float = 30
) -> bytes:
    resp = session.get(
        f"{BASE_URL}/tripupdates",
        params={"api_key": api_key, "agency": agency},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    if resp.status_code == 429:
        raise RateLimited(f"511 rate limit hit for agency {agency}")
    resp.raise_for_status()
    return resp.content


def decode_feed(raw: bytes) -> dict:
    """Protobuf bytes -> plain dict (see parse.py for the dict shape)."""
    # Imported here so the parser and its tests don't need the bindings.
    from google.protobuf.json_format import MessageToDict
    from google.transit import gtfs_realtime_pb2

    msg = gtfs_realtime_pb2.FeedMessage()
    msg.ParseFromString(raw)
    return MessageToDict(msg, preserving_proto_field_name=True)


def archive_raw(archive_dir: str, agency: str, raw: bytes) -> str:
    """Save the raw feed (gzipped) so it can be re-parsed later if needed."""
    now = datetime.now(tz=timezone.utc)
    folder = os.path.join(archive_dir, agency, now.strftime("%Y-%m-%d"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, now.strftime("%H%M%S") + ".pb.gz")
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return path
