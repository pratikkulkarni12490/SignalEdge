"""Premium Divergence Strategy — Configuration

⚠ REAL MONEY AT STAKE — every parameter here directly affects trade entry/exit/sizing.
Change with caution and backtest before going live.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Upstox API
UPSTOX_TOKEN_FILE = os.path.join(os.path.dirname(BASE_DIR), "data", ".upstox_token.json")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Strategy parameters
POLL_INTERVAL_SEC = 60          # 1 minute between ticks
LOOKBACK_CANDLES = 5            # 5-min rolling change window
IGNORE_FIRST_MINUTES = 10       # Skip 9:15-9:25 opening noise
SIGNAL_WINDOW_END = "10:30"     # Stop generating NEW signals after this (existing signal stays)
CONSECUTIVE_FOR_CONFIRM = 4     # Need 4 consecutive same-direction divergences

# Signal thresholds (% change in 5-min window)
CE_SURGE_PCT = 3.0              # CE must rise > 3% for BULL signal
PE_SURGE_PCT = 3.0              # PE must rise > 3% for BEAR signal
OPPOSITE_DECAY_PCT = -1.0       # Other side must FALL > 1% (prevents vol-expansion false signals)
VOL_EXPANSION_PCT = 2.0         # Both rising > 2% = vol expansion = IGNORE

# Nifty lot size
NIFTY_LOT_SIZE = 65             # 1 lot = 75 qty

# Stop loss / target (% of entry premium)
SL_PCT = 0.30                   # 30% SL on premium (entry × 0.70)
TGT1_PCT = 0.30                 # 30% profit target 1
TGT2_PCT = 0.50                 # 50% profit target 2

# Data storage
DB_PATH = os.path.join(BASE_DIR, "data", "divergence.db")
