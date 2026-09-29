"""Microcap Analyzer — CLI entrypoint.

  python run.py init-db          — create the SQLite schema
  python run.py seed-universe    — load data/universe_seed.csv into the stocks table
  python run.py resolve-keys     — match stocks to Upstox instrument_keys      (needs network)
  python run.py ingest           — pull daily OHLCV history for resolved stocks (needs network)
  python run.py analyze          — compute indicators + print the ranked report (offline, DB-only)
  python run.py all              — resolve-keys + ingest + analyze, in order    (needs network)

`init-db`, `seed-universe` and `analyze` only touch the local SQLite file and
run anywhere. `resolve-keys` and `ingest` make real HTTPS calls to Upstox and
will not work inside a network-sandboxed session — see README.md.
"""

import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "init-db":
        from db import init_db
        init_db()

    elif cmd == "seed-universe":
        from seed_universe import seed
        seed()

    elif cmd == "resolve-keys":
        from ingest import resolve_keys
        resolve_keys()

    elif cmd == "ingest":
        from ingest import ingest_prices
        ingest_prices()

    elif cmd == "analyze":
        from analyze import compute_all, report
        compute_all()
        report()

    elif cmd == "all":
        from ingest import resolve_keys, ingest_prices
        from analyze import compute_all, report
        resolve_keys()
        ingest_prices()
        compute_all()
        report()

    else:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)


if __name__ == "__main__":
    main()
