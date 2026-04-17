"""Premium Divergence — CLI Runner"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run.py live              — Run live during market hours")
        print("  python run.py backtest           — Backtest Apr 13-16")
        print("  python run.py dashboard          — Launch Streamlit dashboard")
        return

    cmd = sys.argv[1]

    if cmd == "live":
        from engine import run_live
        run_live()

    elif cmd == "backtest":
        from engine import run_backtest
        import time

        tests = [
            ("2026-04-13", "NSE_FO|63398", "NSE_FO|63403", 23550, 23650, 23589.6, 23842.65),
            ("2026-04-15", "NSE_FO|63422", "NSE_FO|63427", 24100, 24200, 24163.8, 24231.3),
            ("2026-04-16", "NSE_FO|63430", "NSE_FO|63437", 24300, 24400, 24385.2, 24196.75),
        ]

        for date, ce_key, pe_key, ce_s, pe_s, n_open, n_close in tests:
            run_backtest(date, ce_key, pe_key, ce_s, pe_s, n_open, n_close)
            time.sleep(0.5)

    elif cmd == "dashboard":
        os.system(f"streamlit run {os.path.join(os.path.dirname(__file__), 'app.py')}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
