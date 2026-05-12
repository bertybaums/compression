"""Shared rate-limiter + time-of-day rate scheduler for MindRouter callers.

Used by both generate_reasoning.py and generate_forms.py to enforce a global
process-wide token bucket. The bucket's refill rate can be updated on the fly
via `set_rate()`; the `rate_schedule_ticker` coroutine reads a schedule config
and switches between day/night rates based on wall-clock time, so multiple
RCDS users can share the MR endpoint without contention during business hours.

Config schema (lives under `mindrouter.rate_schedule` in corpus/generation/config.yaml):

    rate_schedule:
        enabled: true
        timezone: America/Los_Angeles
        night_start: "17:00"  # HH:MM in that timezone
        day_start:   "05:00"
        night_rate:  200      # req/min during night window
        day_rate:    100      # req/min during day window
"""

import asyncio
import datetime
import time
import zoneinfo


class AsyncTokenBucket:
    """Shared async token bucket. `acquire()` blocks until one token is available."""

    def __init__(self, rate_per_sec: float, burst: float):
        self.rate = rate_per_sec
        self.burst = max(1.0, burst)
        self._tokens = self.burst
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def set_rate(self, rate_per_sec: float) -> None:
        """Update the refill rate. Safe to call from any coroutine — the next
        `acquire()` picks up the new rate. Token count is preserved across the
        switch so in-flight callers aren't penalized when the rate drops."""
        self.rate = rate_per_sec

    async def acquire(self) -> None:
        while True:
            wait_time = 0.0
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait_time)


# ---------------------------------------------------------------------------
# Time-of-day rate schedule
# ---------------------------------------------------------------------------

def _is_night_hour(now: datetime.datetime, night_start: str, day_start: str) -> bool:
    """Return True iff `now` falls inside the night window [night_start, day_start).

    Times are HH:MM strings in the timezone of `now`. The window wraps midnight
    when night_start > day_start (the usual case): 'night' is the half of the
    day that does NOT contain the day_start time.
    """
    h, m = now.hour, now.minute
    cur_min = h * 60 + m

    def to_min(s: str) -> int:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)

    night_min = to_min(night_start)
    day_min = to_min(day_start)
    if night_min < day_min:
        return night_min <= cur_min < day_min
    return cur_min >= night_min or cur_min < day_min


def scheduled_rate_per_min(schedule: dict) -> tuple[float, str]:
    """Look up the configured req/min rate for the current wall-clock time.
    Returns (rate, label) where label is 'day' or 'night'."""
    tz = zoneinfo.ZoneInfo(schedule["timezone"])
    now = datetime.datetime.now(tz)
    night = _is_night_hour(now, schedule["night_start"], schedule["day_start"])
    if night:
        return float(schedule["night_rate"]), "night"
    return float(schedule["day_rate"]), "day"


async def rate_schedule_ticker(bucket: AsyncTokenBucket, schedule: dict, tick_seconds: int = 60):
    """Background coroutine: every `tick_seconds`, recompute the desired rate
    from `schedule` and update the bucket. Logs each rate change."""
    last_rate: float | None = None
    while True:
        rate_per_min, label = scheduled_rate_per_min(schedule)
        rate_per_sec = rate_per_min / 60.0
        if rate_per_sec != last_rate:
            print(f"  [rate-schedule] switching to {label} rate: {rate_per_min:.0f} req/min", flush=True)
            bucket.set_rate(rate_per_sec)
            last_rate = rate_per_sec
        await asyncio.sleep(tick_seconds)


def make_bucket(config: dict) -> tuple[AsyncTokenBucket, dict | None]:
    """Construct an AsyncTokenBucket from `config["mindrouter"]`. If a
    rate_schedule is present and enabled, the bucket starts at the
    currently-appropriate rate and the schedule dict is returned (so the
    caller can launch `rate_schedule_ticker(bucket, schedule)` as a task)."""
    mr = config.get("mindrouter", config)
    burst = mr.get("burst_capacity", 10)
    sched = mr.get("rate_schedule")
    if sched and sched.get("enabled"):
        rate_per_min, label = scheduled_rate_per_min(sched)
        bucket = AsyncTokenBucket(rate_per_sec=rate_per_min / 60.0, burst=burst)
        print(f"Rate limit (scheduled, {sched['timezone']}): {rate_per_min:.0f} req/min "
              f"[{label} — {sched['day_rate']}/{sched['night_rate']} day/night, "
              f"switches at {sched['day_start']}/{sched['night_start']}], "
              f"burst {burst}")
        return bucket, sched
    rate_per_min = mr.get("max_req_per_minute", 100)
    bucket = AsyncTokenBucket(rate_per_sec=rate_per_min / 60.0, burst=burst)
    print(f"Rate limit (fixed): {rate_per_min} req/min, burst {burst}")
    return bucket, None
