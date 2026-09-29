"""Loads data/universe_seed.csv into the stocks table.

This seed list is a STARTER SET, not the full Nifty Microcap 250. It's the
subset of constituents I could verify via web search in the session that
built this project (see the `source` column) — niftyindices.com itself is
blocked by this environment's network policy, so the full 250-name factsheet
couldn't be pulled programmatically. To complete the universe: download the
factsheet at niftyindices.com/indices/equity/broad-based-indices (Nifty
Microcap 250) from a machine with normal internet access, and append rows to
seeds/universe_seed.csv in the same format before re-running this script.
"""

import csv, os, sys
from config import INDEX_NAME
from db import connect, init_db

SEED_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds", "universe_seed.csv")


def seed():
    init_db()
    conn = connect()
    with open(SEED_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = [
            (
                row["symbol"].strip().upper(),
                row["name"].strip(),
                row.get("sector", "").strip() or None,
                INDEX_NAME,
                float(row["market_cap_cr"]) if row.get("market_cap_cr") else None,
                row.get("source", "").strip() or None,
            )
            for row in reader
        ]

    conn.executemany(
        """INSERT INTO stocks (symbol, name, sector, index_name, market_cap_cr, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(symbol) DO UPDATE SET
             name=excluded.name, sector=excluded.sector, index_name=excluded.index_name,
             market_cap_cr=excluded.market_cap_cr, source=excluded.source, updated_at=datetime('now')""",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
    conn.close()
    print(f"Seeded {len(rows)} stocks from {SEED_CSV}. Total in DB: {count}.")


if __name__ == "__main__":
    seed()
