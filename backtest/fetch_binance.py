"""
Real historical kline fetcher — Binance public REST API.
This is what backfill.py calls in production (GitHub Actions / Vercel cron,
anywhere with outbound internet). Local dev sandboxes without internet access
should use generate_sample_data.py instead — see backfill.py's --source flag.
"""

import json
import urllib.request

BASE_URL = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol, interval="1m", limit=1000, start_time=None, end_time=None):
    """Returns list of dicts: {open_time, open, high, low, close, volume}"""
    params = f"symbol={symbol}&interval={interval}&limit={limit}"
    if start_time:
        params += f"&startTime={start_time}"
    if end_time:
        params += f"&endTime={end_time}"
    url = f"{BASE_URL}?{params}"

    with urllib.request.urlopen(url, timeout=15) as resp:
        raw = json.loads(resp.read().decode())

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
