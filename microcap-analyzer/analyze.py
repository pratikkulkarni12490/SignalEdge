"""Computes technical_signals from stored price_history and prints a ranked report."""

from db import connect
from indicators import compute_for_series


def compute_all():
    conn = connect()
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks").fetchall()]

    computed = 0
    for symbol in symbols:
        rows = conn.execute(
            "SELECT date, close FROM price_history WHERE symbol = ? ORDER BY date ASC", (symbol,)
        ).fetchall()
        if not rows:
            continue
        dates = [r[0] for r in rows]
        closes = [r[1] for r in rows]

        signal = compute_for_series(dates, closes)
        if signal is None:
            continue

        conn.execute(
            """INSERT INTO technical_signals
               (symbol, as_of_date, close, sma50, sma200, rsi14, week52_high, week52_low,
                range_position_pct, trend, rsi_state)
               VALUES (:symbol, :as_of_date, :close, :sma50, :sma200, :rsi14, :week52_high,
                       :week52_low, :range_position_pct, :trend, :rsi_state)
               ON CONFLICT(symbol, as_of_date) DO UPDATE SET
                 close=excluded.close, sma50=excluded.sma50, sma200=excluded.sma200,
                 rsi14=excluded.rsi14, week52_high=excluded.week52_high,
                 week52_low=excluded.week52_low, range_position_pct=excluded.range_position_pct,
                 trend=excluded.trend, rsi_state=excluded.rsi_state""",
            {**signal, "symbol": symbol},
        )
        computed += 1

    conn.commit()
    conn.close()
    print(f"Computed technical signals for {computed}/{len(symbols)} stocks.")


def report():
    """Print the latest signal per stock, ranked by 52-week range position (lowest first —
    i.e. names sitting nearest their 52-week low surface at the top, since that's usually the
    more interesting end of a technical screen). Adjust the ORDER BY to suit whatever you're
    hunting for.
    """
    conn = connect()
    rows = conn.execute(
        """
        SELECT s.symbol, s.name, t.close, t.sma50, t.sma200, t.rsi14, t.rsi_state,
               t.range_position_pct, t.trend, t.as_of_date
        FROM technical_signals t
        JOIN stocks s ON s.symbol = t.symbol
        WHERE t.as_of_date = (SELECT MAX(as_of_date) FROM technical_signals t2 WHERE t2.symbol = t.symbol)
        ORDER BY t.range_position_pct ASC NULLS LAST
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("No technical signals yet — run `python run.py ingest` then `python run.py analyze` first.")
        return

    header = f"{'Symbol':<12} {'Close':>9} {'50DMA':>9} {'200DMA':>9} {'RSI14':>7} {'RSI':>10} {'52wPos%':>8} {'Trend':<20} {'AsOf'}"
    print(header)
    print("-" * len(header))
    for symbol, name, close, sma50, sma200, rsi14, rsi_state, range_pos, trend, as_of in rows:
        print(
            f"{symbol:<12} {close or 0:>9.2f} {sma50 or 0:>9.2f} {sma200 or 0:>9.2f} "
            f"{rsi14 or 0:>7.1f} {rsi_state or '-':>10} {range_pos if range_pos is not None else 0:>8.1f} "
            f"{trend or '-':<20} {as_of}"
        )


if __name__ == "__main__":
    compute_all()
    report()
