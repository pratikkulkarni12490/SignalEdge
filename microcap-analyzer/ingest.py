"""Data ingestion — resolves Upstox instrument keys and pulls daily OHLCV history.

NOTE ON RUNNING THIS: it makes real HTTPS calls (Upstox API, Upstox's instrument
master file). It will NOT run inside a network-sandboxed Claude Code session —
only outbound access to a small allowlist (GitHub, PyPI, npm, Anthropic) is
permitted there. Run this on a machine with normal internet access and a valid
Upstox token at the path in config.UPSTOX_TOKEN_FILE — run `python
token_refresh.py` in this folder to get one (shared token file with the
parent SignalEdge engine).
"""

import csv, gzip, io, logging, os, sys, time
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from config import (
    INSTRUMENT_MASTER_URL, INSTRUMENT_MASTER_CACHE, USER_AGENT, LOOKBACK_DAYS,
)
from db import connect

log = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def download_instrument_master(force=False):
    """Cache Upstox's NSE instrument master locally (it's ~tens of MB, refreshed daily upstream)."""
    if os.path.exists(INSTRUMENT_MASTER_CACHE) and not force:
        age_hours = (time.time() - os.path.getmtime(INSTRUMENT_MASTER_CACHE)) / 3600
        if age_hours < 24:
            return INSTRUMENT_MASTER_CACHE

    os.makedirs(os.path.dirname(INSTRUMENT_MASTER_CACHE), exist_ok=True)
    req = urllib.request.Request(INSTRUMENT_MASTER_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        with open(INSTRUMENT_MASTER_CACHE, "wb") as f:
            f.write(resp.read())
    log.info(f"Instrument master cached at {INSTRUMENT_MASTER_CACHE}")
    return INSTRUMENT_MASTER_CACHE


def _load_master_index():
    """symbol -> instrument_key, for NSE cash-market equities only."""
    path = download_instrument_master()
    index = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("exchange") != "NSE_EQ" and row.get("instrument_type") != "EQ":
                continue
            symbol = row.get("tradingsymbol") or row.get("trading_symbol")
            key = row.get("instrument_key")
            if symbol and key:
                index[symbol.strip().upper()] = key
    return index


def resolve_keys():
    """Fill in stocks.instrument_key for any row that doesn't have one yet."""
    conn = connect()
    cur = conn.execute("SELECT symbol FROM stocks WHERE instrument_key IS NULL OR instrument_key = ''")
    pending = [r[0] for r in cur.fetchall()]
    if not pending:
        print("Nothing to resolve — every stock already has an instrument_key.")
        conn.close()
        return

    master = _load_master_index()
    resolved, unresolved = [], []
    for symbol in pending:
        key = master.get(symbol.upper())
        if key:
            conn.execute(
                "UPDATE stocks SET instrument_key = ?, updated_at = datetime('now') WHERE symbol = ?",
                (key, symbol),
            )
            resolved.append(symbol)
        else:
            unresolved.append(symbol)
    conn.commit()
    conn.close()

    print(f"Resolved {len(resolved)}/{len(pending)} symbols.")
    if unresolved:
        print(f"Could not match (check spelling / delisting / recent IPO symbol change): {unresolved}")


def ingest_prices(days=LOOKBACK_DAYS):
    """Pull daily candles for every stock that has an instrument_key and upsert them."""
    from upstox_api import get_historical_candles  # parent-repo module — same auth/retry logic

    conn = connect()
    cur = conn.execute(
        "SELECT symbol, instrument_key FROM stocks WHERE instrument_key IS NOT NULL AND instrument_key != ''"
    )
    stocks = cur.fetchall()
    if not stocks:
        print("No stocks have an instrument_key yet — run resolve-keys first.")
        conn.close()
        return

    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()

    total_rows = 0
    for symbol, instrument_key in stocks:
        candles = get_historical_candles(instrument_key, "day", from_date, to_date)
        if not candles:
            log.warning(f"{symbol}: no candles returned")
            continue

        rows = [
            (symbol, c[0][:10], c[1], c[2], c[3], c[4], c[5])
            for c in candles
        ]
        conn.executemany(
            """INSERT INTO price_history (symbol, date, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            rows,
        )
        conn.commit()
        total_rows += len(rows)
        log.info(f"{symbol}: upserted {len(rows)} daily candles")
        time.sleep(0.3)  # be polite to the API — this isn't the latency-sensitive live engine

    conn.close()
    print(f"Done. {total_rows} rows upserted across {len(stocks)} stocks.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "resolve-keys":
        resolve_keys()
    elif cmd == "prices":
        ingest_prices()
    else:
        print("Usage: python ingest.py [resolve-keys|prices]")
