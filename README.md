# SpartanRoute

A commute reliability optimizer for SJSU students. You tell it where you're starting, which building you need to reach, and when class starts. It recommends the route **least likely to make you late**, plus a backup route and a "leave by" time, and explains why it picked them.

Google Maps answers "what's the fastest route right now?" SpartanRoute answers "which route gets me there on time 95% of the time, given how these buses and trains have actually performed?"

## Architecture

```
spartanroute/
  collector/   Polls 511.org GTFS-realtime feeds → Postgres   (done: Phase 1)
  scoring/     Reliability model + route scoring (pure Python, tested)
  api/         FastAPI: POST /recommend
  web/         Next.js frontend
  docker-compose.yml
```

```
511.org GTFS-RT ──► collector ──► Postgres ◄── scoring ◄── api ◄── web
511.org GTFS (static) ──► OpenTripPlanner ──► candidate routes ──┘
```

## Phase 1: start collecting delay data (do this first)

The reliability model needs weeks of real delay history, and the only way to get it is to collect it yourself. Get the collector running before you build anything else.

1. **Get a 511 API token** (free): https://511.org/open-data/token
2. **Configure:**
   ```bash
   cp .env.example .env    # then paste your token into API_511_KEY
   ```
3. **Smoke test.** This polls VTA and BART once and exits:
   ```bash
   docker compose up -d db
   docker compose run --rm collector python -m collector.main --once
   ```
   You should see lines like `SC: 4210 stop updates, 3 cancellations`.
4. **Run it for real:**
   ```bash
   docker compose up -d
   docker compose logs -f collector
   ```
5. **Check on it** any time:
   ```bash
   docker compose exec -T db psql -U spartanroute < collector/queries/health.sql
   ```

### Keep it running 24/7

A laptop that sleeps leaves gaps in the data. Once the smoke test passes, move the stack to a small always-on Linux VM: Oracle Cloud's free tier, or a $4–6/month VPS. The GitHub Student Developer Pack includes cloud credits that cover this. On the VM, install Docker, clone the repo, copy `.env` over, and run `docker compose up -d`. The `restart: unless-stopped` setting brings it back up after reboots and crashes.

### Rate limits

511 allows **60 requests per hour** per key by default. Two agencies polled every 180 s uses 40 requests per hour, which leaves room for static downloads and manual testing. The collector refuses to start with a config that would go over about 75% of the limit. If you need faster polling, email 511 and ask for a higher limit, then set `HOURLY_REQUEST_LIMIT`.

### What gets stored

| Table | One row per | Why |
|---|---|---|
| `stop_observations` | trip × service day × stop | Each poll overwrites the prediction. Once the vehicle passes, the last value ≈ what actually happened. Keeps the *first* prediction too, so you can measure how accurate 511 predictions are. |
| `trip_cancellations` | canceled trip | A canceled bus is the worst kind of "late", so the model has to count it. |
| `feed_polls` | poll | Monitoring: status, row counts, latency, errors. |

### Static schedules

You'll need these for OpenTripPlanner (Phase 2) and to compute delay when a feed only reports predicted times:
```bash
docker compose run --rm -v "$PWD/data:/data" collector \
  python -m collector.fetch_static --out /data/gtfs
```

## Development

```bash
cd collector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest              # unit tests

# Postgres integration tests (CI runs these automatically):
docker compose up -d db
TEST_DATABASE_URL=postgresql://spartanroute:change-me@localhost:5432/spartanroute python -m pytest
```

## Roadmap

- [x] **Phase 1: Collector.** GTFS-RT → Postgres, tests, Docker, CI
- [ ] **Phase 2: Routing.** Self-hosted OpenTripPlanner loaded with VTA + BART GTFS; returns candidate itineraries
- [ ] **Phase 3: Scoring (the ISE core).** Delay distributions per route × stop × hour; P(late) per itinerary; weighted score:
      `travel_time + λ_late·P(late) + λ_xfer·transfers + λ_walk·walk + λ_cost·cost`; buffer chosen to meet the user's lateness tolerance
- [ ] **Phase 4: API.** FastAPI `POST /recommend` → best route, backup, leave-by time, explanation
- [ ] **Phase 5: Web.** Next.js form + results page
- [ ] **Phase 6: Hardening.** Deployment, logging and alerts, user accounts, saved class schedules
