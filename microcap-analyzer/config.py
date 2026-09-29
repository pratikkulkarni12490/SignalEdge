"""Microcap Analyzer — Configuration"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

# Reuse the same Upstox token file as the main SignalEdge engine — same broker account.
UPSTOX_TOKEN_FILE = os.path.join(REPO_ROOT, "data", ".upstox_token.json")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Upstox publishes the full tradable instrument master here (updated daily).
INSTRUMENT_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
INSTRUMENT_MASTER_CACHE = os.path.join(BASE_DIR, "data", "nse_instruments.csv.gz")

# Storage
DB_PATH = os.path.join(BASE_DIR, "data", "microcap.db")

# Universe
INDEX_NAME = "NIFTY MICROCAP 250"

# Technical parameters
SMA_SHORT = 50
SMA_LONG = 200
RSI_PERIOD = 14
LOOKBACK_DAYS = 400          # history to pull per stock (covers 200DMA + 52wk range with buffer)
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
