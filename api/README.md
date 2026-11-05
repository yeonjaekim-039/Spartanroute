# api (Phase 4)

FastAPI service. `POST /recommend` takes origin, destination building, class start time, and
preferences; calls OpenTripPlanner for candidates and `scoring/` to rank them.
