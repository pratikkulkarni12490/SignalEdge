# Microcap Analyzer

Technical-signal tracker for the **Nifty Microcap 250** universe: daily moving
averages, RSI(14), 52-week range position, and golden/death cross detection,
stored in SQLite so the numbers are queryable rather than re-derived from a
chart every time.

This is v1-scoped to **technical signals only** — no fundamentals (P/E, ROE),
no corporate-action tracking. See `../` (the parent SignalEdge repo) for the
unrelated intraday Nifty-options engine this sits alongside; the two don't
share code beyond reusing the Upstox auth/token pattern.

## Schema

- **`stocks`** — reference data: symbol, name, sector, which index it was seeded from, and its Upstox `instrument_key` once resolved.
- **`price_history`** — daily OHLCV per symbol.
- **`technical_signals`** — one row per symbol per day it was computed: close, SMA50, SMA200, RSI14, 52-week high/low, range position (0–100%), trend label, RSI state.

## Setup

```
python run.py init-db        # create data/microcap.db
python run.py seed-universe  # load data/universe_seed.csv
```

Both of these are offline and run anywhere.

## The universe seed is a starter set, not the full 250

`seeds/universe_seed.csv` currently holds **10 verified names** (Sterlite
Technologies, MTAR Technologies, Cupid, Rubicon Research, TD Power Systems,
Kirloskar Brothers, KSB, Aether Industries, Garware Hitech Films, Apollo
Micro Systems) — the subset of Nifty Microcap 250 constituents confirmed via
web search when this project was built. `niftyindices.com` itself is blocked
by this environment's network egress policy, so the complete 250-name
factsheet couldn't be pulled programmatically from here.

To complete it: download the factsheet from
[niftyindices.com/indices/equity/broad-based-indices](https://niftyindices.com/indices/equity/broad-based-indices)
→ Nifty Microcap 250 (works fine from a normal machine), and append rows to
the CSV in the same `symbol,name,sector,market_cap_cr,source` format, then
re-run `seed-universe`.

## Ingesting price data — requires a machine with real internet access

`resolve-keys` and `ingest` make live HTTPS calls (Upstox's instrument master
file, Upstox's historical-candle API) and **will not run inside a
network-sandboxed Claude Code session** — only a small allowlist (GitHub,
PyPI, npm, Anthropic) is reachable from there. They were written and reviewed
here but not execution-tested against the live API. Run them from your own
machine or a CI runner with normal network access:

```
python run.py resolve-keys   # match stocks.symbol -> Upstox instrument_key
python run.py ingest         # pull ~400 days of daily candles per stock
python run.py analyze        # compute indicators, print the ranked report
```

or all three (plus resolve/ingest) in one go:

```
python run.py all
```

**Prerequisite:** a valid Upstox access token at `../data/.upstox_token.json`
— shared with the main SignalEdge engine (same Upstox account, same file).
Refresh it with `python token_refresh.py` (a local copy of the parent
project's Telegram-based auth flow — see the docstring at the top of that
file for the step-by-step). Either copy writes to the same `TOKEN_FILE`, so
run whichever is more convenient.

## Report

`python run.py analyze` prints the latest signal per stock, ranked by
52-week range position (ascending — names closest to their 52-week low
surface first, since that's usually the more interesting end of a screen for
mean-reversion setups; edit the `ORDER BY` in `analyze.py:report()` if you
want it ranked differently, e.g. by RSI or by recent golden crosses).

## What's intentionally not here yet

- Fundamentals (P/E, ROE, debt/equity, market cap refresh) — out of scope for this v1 by request.
- Corporate-action / demerger / holdco-discount tracking — the thing the earlier one-off research report covered by hand; not wired into this DB.
- Any scheduling/automation — `ingest` is manual; cron it yourself once it's proven to work end-to-end on your machine.
