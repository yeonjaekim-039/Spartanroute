"""Download static GTFS schedules (stops, routes, timetables) from 511.org.

You need these to (a) load OpenTripPlanner and (b) compute delay for feeds
that only report predicted times. Schedules change a few times a year, so
run this occasionally, not on every poll.

Usage:
    python -m collector.fetch_static --out data/gtfs          # SC and BA
    python -m collector.fetch_static --out data/gtfs SC
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import requests

from .feed import BASE_URL, USER_AGENT


def download(api_key: str, operator_id: str, out_dir: str) -> str:
    resp = requests.get(
        f"{BASE_URL}/datafeeds",
        params={"api_key": api_key, "operator_id": operator_id},
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    resp.raise_for_status()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{operator_id}-{date.today():%Y%m%d}.zip")
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operators", nargs="*", default=["SC", "BA"])
    parser.add_argument("--out", default="data/gtfs")
    args = parser.parse_args(argv)

    api_key = os.environ.get("API_511_KEY", "").strip()
    if not api_key:
        print("API_511_KEY is not set", file=sys.stderr)
        return 1
    for op in args.operators:
        path = download(api_key, op, args.out)
        print(f"{op}: saved {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
