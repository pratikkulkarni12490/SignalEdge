"""SQLite schema and connection helper for the microcap analyzer."""

import os, sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol          TEXT PRIMARY KEY,      -- NSE trading symbol, e.g. 'MTARTECH'
    name            TEXT NOT NULL,
    sector          TEXT,
    index_name      TEXT NOT NULL,         -- which broad-based index this was seeded from
    market_cap_cr   REAL,                  -- as of seed time, informational only — not refreshed
    instrument_key  TEXT,                  -- Upstox instrument_key, filled in by resolve-keys
    source          TEXT,                  -- where this row's data came from (seed list, factsheet, etc.)
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    symbol   TEXT NOT NULL,
    date     TEXT NOT NULL,                -- YYYY-MM-DD
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   INTEGER,
    PRIMARY KEY (symbol, date),
    FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);

CREATE TABLE IF NOT EXISTS technical_signals (
    symbol              TEXT NOT NULL,
    as_of_date          TEXT NOT NULL,
    close               REAL,
    sma50               REAL,
    sma200              REAL,
    rsi14               REAL,
    week52_high         REAL,
    week52_low          REAL,
    range_position_pct  REAL,              -- 0 = at 52wk low, 100 = at 52wk high
    trend               TEXT,              -- GOLDEN_CROSS / DEATH_CROSS / ABOVE_BOTH / BELOW_BOTH / MIXED
    rsi_state           TEXT,              -- OVERSOLD / OVERBOUGHT / NEUTRAL
    PRIMARY KEY (symbol, as_of_date),
    FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Initialized DB at {DB_PATH}")


if __name__ == "__main__":
    init_db()
