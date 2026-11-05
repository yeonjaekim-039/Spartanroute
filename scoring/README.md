# scoring (Phase 3)

Pure Python, no web framework. Input: candidate itineraries + user weights + arrival deadline.
Output: ranked itineraries with P(late), expected arrival, leave-by time, and a short explanation.
Reads delay history from the collector's `stop_observations` table.
