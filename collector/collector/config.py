from __future__ import annotations

import os
from dataclasses import dataclass

# 511.org default limit: 60 requests per rolling hour, per API key.
DEFAULT_HOURLY_LIMIT = 60

# 511 operator IDs: SC = VTA (Santa Clara VTA), BA = BART.
DEFAULT_AGENCIES = "SC,BA"


@dataclass(frozen=True)
class Config:
    api_key: str
    database_url: str
    agencies: tuple[str, ...]
    poll_interval_seconds: int
    hourly_limit: int
    archive_dir: str | None


def requests_per_hour(n_agencies: int, interval_seconds: int) -> float:
    return n_agencies * 3600 / interval_seconds


def load_config(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)

    api_key = env.get("API_511_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "API_511_KEY is not set. Get a free token at https://511.org/open-data/token "
            "and put it in your .env file."
        )

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not set (e.g. postgresql://user:pass@host:5432/db).")

    agencies = tuple(
        a.strip().upper()
        for a in env.get("AGENCIES", DEFAULT_AGENCIES).split(",")
        if a.strip()
    )
    interval = int(env.get("POLL_INTERVAL_SECONDS", "180"))
    limit = int(env.get("HOURLY_REQUEST_LIMIT", str(DEFAULT_HOURLY_LIMIT)))

    rph = requests_per_hour(len(agencies), interval)
    # Keep ~25% headroom for static-GTFS downloads and manual testing.
    if rph > limit * 0.75:
        min_interval = int(len(agencies) * 3600 / (limit * 0.75)) + 1
        raise SystemExit(
            f"{len(agencies)} agencies every {interval}s = {rph:.0f} requests/hour, "
            f"too close to the 511 limit of {limit}/hour. "
            f"Use POLL_INTERVAL_SECONDS >= {min_interval}, fewer agencies, "
            "or ask 511 for a higher limit and set HOURLY_REQUEST_LIMIT."
        )

    return Config(
        api_key=api_key,
        database_url=database_url,
        agencies=agencies,
        poll_interval_seconds=interval,
        hourly_limit=limit,
        archive_dir=env.get("ARCHIVE_DIR") or None,
    )
