"""Premium Divergence Detection Engine.

Detects directional conviction by tracking ITM CE/PE premium divergence.
When one side surges while the other decays, it signals institutional flow.

Critical safety rules:
- No signals in first 10 minutes (opening auction noise)
- Requires 4 consecutive same-direction divergences to confirm
- Confidence score determines position size (1-5 lots)
- All positions exit by 2:30 PM
"""

import time, os, sqlite3, logging
from datetime import datetime
from collections import deque

from config import (
    POLL_INTERVAL_SEC, LOOKBACK_CANDLES, IGNORE_FIRST_MINUTES,
    SIGNAL_WINDOW_END, CONSECUTIVE_FOR_CONFIRM,
    CE_SURGE_PCT, PE_SURGE_PCT, OPPOSITE_DECAY_PCT, VOL_EXPANSION_PCT,
    NIFTY_LOT_SIZE, SL_PCT, TGT1_PCT, TGT2_PCT, DB_PATH,
)
from upstox_api import (
    get_nifty_ltp, get_option_quote, find_itm_options, get_next_expiry,
)
import telegram_bot as tg

log = logging.getLogger("engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS ticks (
        timestamp TEXT, nifty REAL,
        ce_strike REAL, ce_premium REAL, ce_volume INTEGER,
        pe_strike REAL, pe_premium REAL, pe_volume INTEGER,
        ce_chg5 REAL, pe_chg5 REAL, divergence REAL,
        signal TEXT, consecutive INTEGER, date TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        timestamp TEXT, date TEXT, direction TEXT,
        ce_strike REAL, pe_strike REAL,
        ce_premium REAL, pe_premium REAL,
        ce_chg5 REAL, pe_chg5 REAL, divergence REAL,
        consecutive INTEGER, strength TEXT,
        nifty_at_signal REAL, confidence_score INTEGER, confidence_tier TEXT, lots INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY, nifty_open REAL, nifty_close REAL,
        day_change REAL, actual_direction TEXT,
        confirmed_signal_time TEXT, confirmed_signal_dir TEXT,
        total_bull_signals INTEGER, total_bear_signals INTEGER,
        total_vol_signals INTEGER, dominant_direction TEXT, result TEXT
    )""")
    conn.commit()
    return conn


# ─── Signal Classification ───────────────────────────────────────────────────

def classify_signal(ce_chg5, pe_chg5):
    """Classify tick into BULL/BEAR/VOL/NONE based on 5-min premium changes."""
    if ce_chg5 > CE_SURGE_PCT and pe_chg5 < OPPOSITE_DECAY_PCT:
        return "BULL"
    if pe_chg5 > PE_SURGE_PCT and ce_chg5 < OPPOSITE_DECAY_PCT:
        return "BEAR"
    if ce_chg5 > VOL_EXPANSION_PCT and pe_chg5 > VOL_EXPANSION_PCT:
        return "VOL"
    return "NONE"


def signal_strength(consecutive):
    if consecutive >= 5: return "FULL_CONFIRMATION"
    if consecutive >= 4: return "CONFIRMED"
    if consecutive >= 3: return "STRONG"
    if consecutive >= 2: return "DIVERGENCE"
    if consecutive >= 1: return "EARLY"
    return "NONE"


def safe_pct_change(new, old):
    """Percentage change, safe against zero/None."""
    if not old or old == 0:
        return 0.0
    return (new - old) / old * 100


# ─── Confidence Scoring ──────────────────────────────────────────────────────

def compute_confidence(direction, ce_chg5, pe_chg5, divergence, consecutive, ce_prices, pe_prices, tick_idx):
    """Score 0-100 based on 4 factors. Determines lot sizing.

    Factor 1: Divergence magnitude (0-25)
    Factor 2: Consecutive count (0-20)
    Factor 3: Acceleration (0-20)
    Factor 4: One-sidedness (0-20)
    Reserved: VIX filter (0-15) — not yet implemented
    """
    score = 0
    reasons = []

    # 1. Divergence magnitude — how far apart are CE and PE moving
    abs_div = abs(divergence)
    if abs_div >= 20:
        score += 25; reasons.append(f"Extreme divergence ({divergence:+.1f})")
    elif abs_div >= 15:
        score += 20; reasons.append(f"Strong divergence ({divergence:+.1f})")
    elif abs_div >= 10:
        score += 15; reasons.append(f"Good divergence ({divergence:+.1f})")
    elif abs_div >= 5:
        score += 8; reasons.append(f"Mild divergence ({divergence:+.1f})")
    else:
        reasons.append(f"Weak divergence ({divergence:+.1f})")

    # 2. Consecutive — how sustained is the signal
    if consecutive >= 8:
        score += 20; reasons.append(f"Sustained {consecutive} consecutive")
    elif consecutive >= 6:
        score += 15; reasons.append(f"Strong {consecutive} consecutive")
    elif consecutive >= 4:
        score += 10; reasons.append(f"Confirmed {consecutive} consecutive")
    elif consecutive >= 2:
        score += 5

    # 3. Acceleration — is the move GETTING STRONGER each candle
    if len(ce_prices) >= 3 and tick_idx >= 2:
        try:
            ce_now, ce_1, ce_2 = ce_prices[tick_idx], ce_prices[tick_idx-1], ce_prices[tick_idx-2]
            pe_now, pe_1, pe_2 = pe_prices[tick_idx], pe_prices[tick_idx-1], pe_prices[tick_idx-2]

            if direction == "BULL":
                ce_accel = (ce_now - ce_1) > (ce_1 - ce_2)  # CE rising faster
                pe_accel = (pe_now - pe_1) < (pe_1 - pe_2)  # PE falling faster
            else:
                ce_accel = (ce_now - ce_1) < (ce_1 - ce_2)  # CE falling faster
                pe_accel = (pe_now - pe_1) > (pe_1 - pe_2)  # PE rising faster

            if ce_accel and pe_accel:
                score += 20; reasons.append("Accelerating on both sides")
            elif ce_accel or pe_accel:
                score += 10; reasons.append("Accelerating on one side")
        except IndexError:
            pass  # Not enough data, skip acceleration

    # 4. One-sidedness — is the signal clean or messy
    surge = ce_chg5 if direction == "BULL" else pe_chg5
    decay = pe_chg5 if direction == "BULL" else ce_chg5

    if surge > 5 and decay < -3:
        score += 20; reasons.append(f"Clean: surge {surge:+.1f}%, decay {decay:+.1f}%")
    elif surge > 3 and decay < -2:
        score += 15; reasons.append(f"Good: surge {surge:+.1f}%, decay {decay:+.1f}%")
    elif surge > 3 and decay < -1:
        score += 8; reasons.append(f"Mild: surge {surge:+.1f}%, decay {decay:+.1f}%")

    score = min(score, 100)

    # Tier → lot sizing
    if score >= 80:   return score, "VERY HIGH", 5, reasons
    if score >= 60:   return score, "HIGH",      3, reasons
    if score >= 40:   return score, "MEDIUM",    2, reasons
    return score, "LOW", 1, reasons


# ─── Trade Recommendation ────────────────────────────────────────────────────

def print_trade_recommendation(direction, nifty, ce_strike, pe_strike, ce_premium, pe_premium, expiry, confidence=None):
    """Print actionable trade rec with entry/SL/targets and confidence-based sizing."""

    atm = round(nifty / 50) * 50
    conf_score, conf_tier, rec_lots, conf_reasons = confidence if confidence else (50, "MEDIUM", 2, [])
    conf_bar = "█" * (conf_score // 10) + "░" * (10 - conf_score // 10)

    if direction == "BULL":
        entry_opt, entry_p = f"{ce_strike}CE", ce_premium
        spread = f"Bull Call: Buy {atm}CE + Sell {atm+100}CE"
        income = f"Sell {atm-100}PE"
        watch = "PE premium starts surging"
    else:
        entry_opt, entry_p = f"{pe_strike}PE", pe_premium
        spread = f"Bear Put: Buy {atm}PE + Sell {atm-100}PE"
        income = f"Sell {atm+100}CE"
        watch = "CE premium starts surging"

    sl = round(entry_p * (1 - SL_PCT), 1)
    tgt1 = round(entry_p * (1 + TGT1_PCT), 1)
    tgt2 = round(entry_p * (1 + TGT2_PCT), 1)
    risk_per_lot = (entry_p - sl) * NIFTY_LOT_SIZE
    total_risk = risk_per_lot * rec_lots
    tgt1_profit = (tgt1 - entry_p) * NIFTY_LOT_SIZE * rec_lots
    tgt2_profit = (tgt2 - entry_p) * NIFTY_LOT_SIZE * rec_lots

    icon = "🟢" if direction == "BULL" else "🔴"
    label = "BULLISH" if direction == "BULL" else "BEARISH"

    print(f"\n  ┌───────────────────────────────────────────────────────────┐")
    print(f"  │  {icon} {label} TRADE RECOMMENDATION                        │")
    print(f"  ├───────────────────────────────────────────────────────────┤")
    print(f"  │  CONFIDENCE: {conf_bar} {conf_score}/100 ({conf_tier})")
    for r in conf_reasons:
        print(f"  │    • {r}")
    print(f"  │")
    print(f"  │  SIZE: {rec_lots} lots ({rec_lots * NIFTY_LOT_SIZE} qty)")
    print(f"  │  Nifty: {nifty:.1f} | Expiry: {expiry}")
    print(f"  │")
    print(f"  │  BUY {entry_opt} @ ₹{entry_p:.1f}")
    print(f"  │    SL:   ₹{sl:.1f} (-{SL_PCT*100:.0f}%) | Risk: ₹{total_risk:,.0f}")
    print(f"  │    TGT1: ₹{tgt1:.1f} (+{TGT1_PCT*100:.0f}%) | Profit: ₹{tgt1_profit:,.0f}")
    print(f"  │    TGT2: ₹{tgt2:.1f} (+{TGT2_PCT*100:.0f}%) | Profit: ₹{tgt2_profit:,.0f}")
    print(f"  │    R:R = 1:{tgt1_profit/total_risk:.1f} / 1:{tgt2_profit/total_risk:.1f}")
    print(f"  │")
    print(f"  │  HEDGE: {spread}")
    print(f"  │  ALT:   {income}")
    print(f"  │")
    print(f"  │  EXIT: Trail SL to cost after TGT1 | Exit by 2:30 PM")
    print(f"  │        Exit if {watch}")
    if conf_tier == "LOW":
        print(f"  │  ⚠ LOW CONFIDENCE — paper trade only")
    print(f"  └───────────────────────────────────────────────────────────┘\n")


# ─── Live Engine ─────────────────────────────────────────────────────────────

class DivergenceEngine:
    def __init__(self):
        self.conn = init_db()
        self.ce_prices = deque(maxlen=100)
        self.pe_prices = deque(maxlen=100)
        self.tick_count = 0
        self.consecutive = 0
        self.current_dir = None
        self.confirmed_signal = None
        self.bull_count = 0
        self.bear_count = 0
        self.vol_count = 0
        self.today = datetime.now().strftime("%Y-%m-%d")

        # Setup
        self.expiry = get_next_expiry()
        nifty = get_nifty_ltp()
        if nifty <= 0:
            raise RuntimeError("Cannot start: Nifty LTP is 0. Market may be closed.")

        self.nifty_open = nifty
        self.ce_strike, self.ce_key, self.pe_strike, self.pe_key = find_itm_options(nifty, self.expiry)

        log.info(f"{'='*60}")
        log.info(f"  Premium Divergence Engine")
        log.info(f"  Date: {self.today} | Expiry: {self.expiry}")
        log.info(f"  Nifty: {nifty:.1f} | ATM: {round(nifty/50)*50}")
        log.info(f"  CE: {self.ce_strike} ({self.ce_key})")
        log.info(f"  PE: {self.pe_strike} ({self.pe_key})")
        log.info(f"  Params: {LOOKBACK_CANDLES}-min lookback, {CONSECUTIVE_FOR_CONFIRM} to confirm")
        log.info(f"  Skip first {IGNORE_FIRST_MINUTES} min | Window ends {SIGNAL_WINDOW_END}")
        log.info(f"{'='*60}")

    def tick(self):
        """Fetch prices, analyze, return tick data or None on error."""
        self.tick_count += 1
        now = datetime.now()
        ts = now.strftime("%H:%M:%S")
        mins_since_open = (now.hour * 60 + now.minute) - (9 * 60 + 15)

        # Fetch — if API fails, skip this tick (don't crash)
        try:
            nifty = get_nifty_ltp()
            ce_q = get_option_quote(self.ce_key)
            pe_q = get_option_quote(self.pe_key)
        except Exception as e:
            log.warning(f"{ts} | API error, skipping tick: {e}")
            return None

        ce_p = ce_q.get("last_price", 0)
        pe_p = pe_q.get("last_price", 0)
        ce_v = ce_q.get("volume", 0)
        pe_v = pe_q.get("volume", 0)

        # Safety: skip if prices are 0 (market closed or bad data)
        if ce_p <= 0 or pe_p <= 0:
            log.warning(f"{ts} | Zero premium: CE={ce_p} PE={pe_p}. Skipping.")
            return None

        self.ce_prices.append(ce_p)
        self.pe_prices.append(pe_p)

        # 5-min rolling change
        ce_chg5 = pe_chg5 = 0.0
        if len(self.ce_prices) > LOOKBACK_CANDLES:
            ce_chg5 = safe_pct_change(ce_p, self.ce_prices[-LOOKBACK_CANDLES - 1])
            pe_chg5 = safe_pct_change(pe_p, self.pe_prices[-LOOKBACK_CANDLES - 1])

        divergence = ce_chg5 - pe_chg5

        # Classify — only within signal window and after warm-up
        sig = "NONE"
        if mins_since_open >= IGNORE_FIRST_MINUTES and ts <= SIGNAL_WINDOW_END:
            sig = classify_signal(ce_chg5, pe_chg5)

        # Track consecutive
        strength = "NONE"
        if sig in ("BULL", "BEAR"):
            if sig == self.current_dir:
                self.consecutive += 1
            else:
                self.consecutive = 1
                self.current_dir = sig

            if sig == "BULL": self.bull_count += 1
            else: self.bear_count += 1

            strength = signal_strength(self.consecutive)

            # Confirmed signal — fire once
            if self.consecutive >= CONSECUTIVE_FOR_CONFIRM and not self.confirmed_signal:
                conf = compute_confidence(sig, ce_chg5, pe_chg5, divergence, self.consecutive,
                                         list(self.ce_prices), list(self.pe_prices), len(self.ce_prices)-1)
                self.confirmed_signal = {
                    "time": ts, "direction": sig, "nifty": nifty,
                    "ce": ce_p, "pe": pe_p, "confidence": conf,
                }
                self._save_signal(ts, sig, ce_p, pe_p, ce_chg5, pe_chg5, divergence, self.consecutive, strength, nifty, conf)

        elif sig == "VOL":
            self.vol_count += 1
            self.consecutive = 0
            self.current_dir = None
            strength = "VOL_EXPANSION"
        else:
            if not self.confirmed_signal:
                self.consecutive = 0
                self.current_dir = None

        # Save tick
        self.conn.execute(
            "INSERT INTO ticks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, nifty, self.ce_strike, ce_p, ce_v, self.pe_strike, pe_p, pe_v,
             round(ce_chg5, 2), round(pe_chg5, 2), round(divergence, 2),
             sig, self.consecutive, self.today)
        )
        self.conn.commit()

        # Print
        sig_str = ""
        if sig == "BULL":
            sig_str = f"{'🟢' * min(self.consecutive, 5)} BULL ({strength})"
        elif sig == "BEAR":
            sig_str = f"{'🔴' * min(self.consecutive, 5)} BEAR ({strength})"
        elif sig == "VOL":
            sig_str = "⚪ VOL EXPANSION"

        print(f"  {ts} | Nifty {nifty:>8.1f} | CE {ce_p:>7.1f} ({ce_chg5:>+5.1f}%) | PE {pe_p:>7.1f} ({pe_chg5:>+5.1f}%) | Div {divergence:>+6.1f} | {sig_str}")

        return {"time": ts, "nifty": nifty, "ce": ce_p, "pe": pe_p,
                "ce_chg5": ce_chg5, "pe_chg5": pe_chg5, "divergence": divergence,
                "signal": sig, "consecutive": self.consecutive, "strength": strength}

    def _save_signal(self, ts, direction, ce_p, pe_p, ce_chg5, pe_chg5, div, consec, strength, nifty, conf):
        score, tier, lots, reasons = conf
        self.conn.execute(
            "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, self.today, direction, self.ce_strike, self.pe_strike,
             ce_p, pe_p, round(ce_chg5, 2), round(pe_chg5, 2), round(div, 2),
             consec, strength, nifty, score, tier, lots)
        )
        self.conn.commit()
        log.info(f"{'🟢🟢' if direction == 'BULL' else '🔴🔴'} CONFIRMED {direction} at {ts} | Confidence: {score}/100 ({tier}) | {lots} lots")
        print_trade_recommendation(direction, nifty, self.ce_strike, self.pe_strike, ce_p, pe_p, self.expiry, confidence=conf)

        # Telegram alert
        try:
            tg.send_signal_alert(direction, conf, self.ce_strike, self.pe_strike, ce_p, pe_p, nifty, self.expiry, lots)
            log.info("Telegram alert sent. Waiting for confirmation...")
            response = tg.wait_for_confirmation(timeout_sec=120)
            if response == "confirm":
                log.info("USER CONFIRMED — would place order here")
                # TODO: Place Upstox GTT order here
            else:
                log.info(f"User response: {response} — no order placed")
        except Exception as e:
            log.error(f"Telegram error: {e}")

    def save_daily_summary(self):
        try:
            nifty_close = get_nifty_ltp()
        except:
            nifty_close = self.nifty_open  # Fallback if API fails at EOD

        day_chg = nifty_close - self.nifty_open
        actual = "BULLISH" if day_chg > 0 else "BEARISH"
        dominant = "BULLISH" if self.bull_count > self.bear_count else "BEARISH" if self.bear_count > self.bull_count else "NEUTRAL"

        conf_time = self.confirmed_signal["time"] if self.confirmed_signal else None
        conf_dir = self.confirmed_signal["direction"] if self.confirmed_signal else None

        if conf_dir:
            result = "CORRECT" if (conf_dir == "BULL" and day_chg > 0) or (conf_dir == "BEAR" and day_chg < 0) else "WRONG"
        else:
            result = "NO_SIGNAL"

        self.conn.execute(
            "INSERT OR REPLACE INTO daily_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.today, self.nifty_open, nifty_close, round(day_chg, 1), actual,
             conf_time, conf_dir, self.bull_count, self.bear_count, self.vol_count, dominant, result)
        )
        self.conn.commit()

        emoji = "✅" if result == "CORRECT" else "❌" if result == "WRONG" else "⚪"
        log.info(f"{'='*60}")
        log.info(f"  DAILY: {self.today} | Nifty {self.nifty_open:.1f}→{nifty_close:.1f} ({day_chg:+.1f}) = {actual}")
        log.info(f"  Signals: 🟢{self.bull_count} 🔴{self.bear_count} ⚪{self.vol_count} | {dominant}")
        log.info(f"  Result: {conf_dir or 'NO_SIGNAL'} {emoji}")
        log.info(f"{'='*60}")

        # EOD Telegram
        try:
            conf_str = None
            if self.confirmed_signal:
                c = self.confirmed_signal.get("confidence")
                conf_str = f"{c[0]}/100 ({c[1]})" if c else None
            tg.send_eod_summary(self.today, self.nifty_open, nifty_close, conf_dir, conf_str, result, 0)
        except Exception as e:
            log.error(f"EOD Telegram error: {e}")


# ─── Run Modes ───────────────────────────────────────────────────────────────

def run_live():
    """Run live during market hours. Ctrl+C to stop."""
    engine = DivergenceEngine()

    market_open = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)

    if datetime.now() < market_open:
        wait = (market_open - datetime.now()).total_seconds()
        log.info(f"Market opens in {wait/60:.0f} min. Waiting...")
        time.sleep(max(0, wait))

    if datetime.now() > market_close:
        log.error("Market is closed. Run during 9:15 AM - 3:30 PM IST.")
        return

    log.info(f"Live monitoring started at {datetime.now().strftime('%H:%M:%S')}")

    try:
        while datetime.now() < market_close:
            engine.tick()
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        log.info("Stopped by user")
    except Exception as e:
        log.error(f"Engine crashed: {e}")
    finally:
        engine.save_daily_summary()


def run_backtest(date, ce_key, pe_key, ce_strike, pe_strike, nifty_open, nifty_close):
    """Backtest on historical 1-min candles."""
    from upstox_api import get_historical_candles

    ce_candles = get_historical_candles(ce_key, "1minute", date, date)
    pe_candles = get_historical_candles(pe_key, "1minute", date, date)

    if not ce_candles or not pe_candles:
        print(f"  No data for {date}")
        return

    n = min(len(ce_candles), len(pe_candles))
    day_chg = nifty_close - nifty_open
    actual = "BULLISH" if day_chg > 0 else "BEARISH"

    print(f"\n{'━'*80}")
    print(f"  {date} | Nifty: {nifty_open} → {nifty_close} | {actual} ({day_chg:+.1f})")
    print(f"  CE: {ce_strike}CE | PE: {pe_strike}PE")
    print(f"{'━'*80}\n")

    ce_prices = deque(maxlen=100)
    pe_prices = deque(maxlen=100)
    consecutive = 0
    current_dir = None
    confirmed = None
    bull = bear = vol = 0

    print(f"  {'Time':<7} {'CE':>8} {'CE%5m':>7} {'PE':>8} {'PE%5m':>7} {'Div':>7} {'Signal'}")
    print(f"  {'─'*70}")

    for i in range(n):
        t = ce_candles[i][0][11:16]
        ce_p = ce_candles[i][4]
        pe_p = pe_candles[i][4]

        ce_prices.append(ce_p)
        pe_prices.append(pe_p)

        ce_chg5 = pe_chg5 = 0.0
        if len(ce_prices) > LOOKBACK_CANDLES:
            ce_chg5 = safe_pct_change(ce_p, ce_prices[-LOOKBACK_CANDLES - 1])
            pe_chg5 = safe_pct_change(pe_p, pe_prices[-LOOKBACK_CANDLES - 1])

        div = ce_chg5 - pe_chg5
        sig = classify_signal(ce_chg5, pe_chg5) if i >= IGNORE_FIRST_MINUTES else "NONE"

        sig_str = ""
        if sig in ("BULL", "BEAR"):
            if sig == current_dir:
                consecutive += 1
            else:
                consecutive = 1
                current_dir = sig

            if sig == "BULL": bull += 1
            else: bear += 1

            strength = signal_strength(consecutive)
            icons = ("🟢" if sig == "BULL" else "🔴") * min(consecutive, 3)
            sig_str = f"{icons} {sig} ({strength})"

            if consecutive >= CONSECUTIVE_FOR_CONFIRM and not confirmed:
                conf = compute_confidence(sig, ce_chg5, pe_chg5, div, consecutive,
                                         list(ce_prices), list(pe_prices), len(ce_prices)-1)
                confirmed = {"time": t, "dir": sig, "ce": ce_p, "pe": pe_p,
                             "confidence": conf, "idx": i}
        elif sig == "VOL":
            vol += 1; consecutive = 0; current_dir = None; sig_str = "⚪ VOL"
        else:
            if not confirmed:
                consecutive = 0; current_dir = None

        if i < 75 or sig_str:
            print(f"  {t:<7} {ce_p:>8.1f} {ce_chg5:>+6.1f}% {pe_p:>8.1f} {pe_chg5:>+6.1f}% {div:>+6.1f} {sig_str}")

    # Results
    dominant = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    print(f"\n  {'━'*70}")
    print(f"  Signals: 🟢{bull} 🔴{bear} ⚪{vol} | Dominant: {dominant}")

    if confirmed:
        correct = (confirmed["dir"] == "BULL" and day_chg > 0) or (confirmed["dir"] == "BEAR" and day_chg < 0)
        print(f"  Confirmed: {confirmed['dir']} at {confirmed['time']} → {'✅ CORRECT' if correct else '❌ WRONG'}")

        nifty_est = nifty_open + (confirmed["ce"] - ce_candles[0][4]) * 0.5
        print_trade_recommendation(confirmed["dir"], nifty_est, ce_strike, pe_strike,
                                   confirmed["ce"], confirmed["pe"], "weekly",
                                   confidence=confirmed["confidence"])

        # P&L tracker
        sig_idx = confirmed["idx"]
        conf = confirmed["confidence"]
        lots = conf[2]

        if sig_idx > 0 and sig_idx < n - 30:
            entry = confirmed["ce"] if confirmed["dir"] == "BULL" else confirmed["pe"]
            candles = ce_candles if confirmed["dir"] == "BULL" else pe_candles
            opt_name = f"{ce_strike}CE" if confirmed["dir"] == "BULL" else f"{pe_strike}PE"

            print(f"  ┌────────────────────────────────────────────────────────┐")
            print(f"  │  P&L: {opt_name} @ ₹{entry:.1f} × {lots} lots ({lots*NIFTY_LOT_SIZE} qty) │")
            print(f"  ├────────────────────────────────────────────────────────┤")

            for offset in [5, 10, 15, 20, 30, 45, 60]:
                idx = sig_idx + offset
                if idx < n:
                    price = candles[idx][4]
                    pnl = (price - entry) * NIFTY_LOT_SIZE * lots
                    pct = safe_pct_change(price, entry)
                    tt = candles[idx][0][11:16]
                    print(f"  │  +{offset:2d}m ({tt}): ₹{price:>7.1f} | ₹{pnl:>+9,.0f} ({pct:>+5.1f}%) {'📈' if pnl>0 else '📉'} │")

            eod = candles[-1][4]
            eod_pnl = (eod - entry) * NIFTY_LOT_SIZE * lots
            eod_pct = safe_pct_change(eod, entry)
            print(f"  │  EOD:       ₹{eod:>7.1f} | ₹{eod_pnl:>+9,.0f} ({eod_pct:>+5.1f}%) {'📈' if eod_pnl>0 else '📉'} │")
            print(f"  └────────────────────────────────────────────────────────┘")
    else:
        print(f"  No confirmed signal")

    print(f"  Actual: {actual} ({day_chg:+.1f})")
