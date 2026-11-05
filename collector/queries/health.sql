-- Quick checks. Run with:
--   docker compose exec -T db psql -U spartanroute < collector/queries/health.sql

-- 1. Is the collector alive? Last 10 polls.
SELECT agency, polled_at, status, n_observations, n_cancellations, duration_ms, error
FROM feed_polls ORDER BY polled_at DESC LIMIT 10;

-- 2. Poll success rate over the last 24 hours.
SELECT agency, status, count(*)
FROM feed_polls WHERE polled_at > now() - interval '24 hours'
GROUP BY agency, status ORDER BY agency, status;

-- 3. How much data do we have?
SELECT agency, count(DISTINCT start_date) AS service_days,
       count(DISTINCT trip_id) AS trips, count(*) AS stop_rows
FROM stop_observations GROUP BY agency;

-- 4. First look at reliability: arrival delay by route and hour of day
--    (only rows where the feed reports delay directly).
SELECT agency, route_id,
       extract(hour FROM to_timestamp(arrival_time) AT TIME ZONE 'America/Los_Angeles') AS hour,
       count(*) AS n,
       round(avg(arrival_delay) / 60.0, 1) AS avg_delay_min,
       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY arrival_delay) / 60.0)::numeric, 1)
           AS p90_delay_min
FROM stop_observations
WHERE arrival_delay IS NOT NULL AND arrival_time IS NOT NULL
GROUP BY 1, 2, 3
HAVING count(*) >= 20
ORDER BY p90_delay_min DESC
LIMIT 25;
