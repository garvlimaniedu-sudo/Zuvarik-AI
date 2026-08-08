"""
Real historical kline fetcher — Binance public REST API.
This is what backfill.py calls in production (GitHub Actions / Vercel cron,
anywhere with outbound internet). Local dev sandboxes without internet access
should use generate_sample_data.py instead — see backfill.py's --source flag.
"""

import json
import time
import urllib.request
import urllib.error

BASE_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000  # Binance hard cap per call


def _parse(raw):
    return [
        {
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        for k in raw
    ]


def fetch_klines(symbol, interval="1m", limit=1000, start_time=None, end_time=None, retries=3):
    """Single Binance API call. Returns list of dicts: {open_time, open, high, low, close, volume}"""
    limit = min(limit, MAX_LIMIT)
    params = f"symbol={symbol}&interval={interval}&limit={limit}"
    if start_time:
        params += f"&startTime={start_time}"
    if end_time:
        params += f"&endTime={end_time}"
    url = f"{BASE_URL}?{params}"

    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = json.loads(resp.read().decode())
            return _parse(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Binance fetch failed after {retries} attempts: {last_err}")


def fetch_klines_paginated(symbol, interval="1m", start_time=None, end_time=None, total_limit=None, sleep_between=0.25):
    """
    Walks forward from start_time to end_time (or to now), pulling MAX_LIMIT
    candles per call, to build a real multi-day/week/month history beyond
    Binance's single-call 1000-candle cap.

    - start_time / end_time: ms epoch. If start_time is None, defaults to
      total_limit candles back from end_time (or now).
    - total_limit: optional cap on total candles returned (safety valve).
    - Binance rate limit is generous for klines but we sleep briefly between
      calls to stay well under it.
    """
    interval_ms = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }.get(interval, 60_000)

    now_ms = int(time.time() * 1000)
    if end_time is None:
        end_time = now_ms
    if start_time is None:
        if total_limit is None:
            raise ValueError("fetch_klines_paginated needs either start_time or total_limit")
        start_time = end_time - (total_limit * interval_ms)

    all_klines = []
    cursor = start_time

    while cursor < end_time:
        batch = fetch_klines(symbol, interval=interval, limit=MAX_LIMIT, start_time=cursor, end_time=end_time)
        if not batch:
            break
        all_klines.extend(batch)
        last_open = batch[-1]["open_time"]
        next_cursor = last_open + interval_ms
        if next_cursor <= cursor:
            break  # safety: avoid infinite loop if Binance returns something odd
        cursor = next_cursor

        if total_limit is not None and len(all_klines) >= total_limit:
            all_klines = all_klines[:total_limit]
            break
        if len(batch) < MAX_LIMIT:
            break  # fewer than max returned means we reached the end of available data

        time.sleep(sleep_between)

    return all_klines
