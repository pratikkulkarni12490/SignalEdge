"""Premium Divergence — Streamlit Dashboard"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from config import DB_PATH
from engine import run_backtest

st.set_page_config(page_title="Premium Divergence", layout="wide", page_icon="📊")

st.markdown("""
<style>
.stApp {background: #0a0e14}
.block-container {padding-top: 1rem}
h1, h2, h3 {color: #e0e6ed}
.metric-card {background: #131a24; border: 1px solid #1e2d3d; border-radius: 10px; padding: 16px; text-align: center}
.metric-card .value {font-size: 28px; font-weight: 800}
.metric-card .label {font-size: 11px; color: #5a6e82; text-transform: uppercase}
.bull {color: #00d4aa}.bear {color: #ff4757}.neutral {color: #ffb020}
</style>
""", unsafe_allow_html=True)

st.title("📊 Premium Divergence Strategy")
st.caption("Track ITM option premium divergence to detect early directional moves")

tab1, tab2, tab3 = st.tabs(["🔴 Live Monitor", "📈 Backtest", "📋 History"])

# ── TAB 1: Live Monitor ──
with tab1:
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        today = datetime.now().strftime("%Y-%m-%d")

        ticks = pd.read_sql(f"SELECT * FROM ticks WHERE date = '{today}' ORDER BY timestamp", conn)
        signals = pd.read_sql(f"SELECT * FROM signals WHERE date = '{today}' ORDER BY timestamp", conn)

        if len(ticks) > 0:
            latest = ticks.iloc[-1]

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Nifty", f"{latest['nifty']:.1f}")
            col2.metric(f"CE {int(latest['ce_strike'])}", f"₹{latest['ce_premium']:.1f}", f"{latest['ce_chg5']:+.1f}%")
            col3.metric(f"PE {int(latest['pe_strike'])}", f"₹{latest['pe_premium']:.1f}", f"{latest['pe_chg5']:+.1f}%")
            col4.metric("Divergence", f"{latest['divergence']:+.1f}")

            bull_cnt = len(ticks[ticks['signal'] == 'BULL'])
            bear_cnt = len(ticks[ticks['signal'] == 'BEAR'])
            col5.metric("Signals", f"🟢{bull_cnt} 🔴{bear_cnt}")

            # Confirmed signal
            if len(signals) > 0:
                sig = signals.iloc[0]
                if sig['direction'] == 'BULL':
                    st.success(f"🟢 BULLISH SIGNAL confirmed at {sig['timestamp']} | Nifty: {sig['nifty_at_signal']:.1f}")
                else:
                    st.error(f"🔴 BEARISH SIGNAL confirmed at {sig['timestamp']} | Nifty: {sig['nifty_at_signal']:.1f}")

            # Charts
            st.subheader("Premium Trends")
            chart_data = ticks[['timestamp', 'ce_premium', 'pe_premium']].set_index('timestamp')
            st.line_chart(chart_data, height=300)

            st.subheader("Divergence (CE%5m - PE%5m)")
            div_data = ticks[['timestamp', 'divergence']].set_index('timestamp')
            st.area_chart(div_data, height=200)

            st.subheader("Signal Feed")
            for _, row in ticks.iterrows():
                if row['signal'] in ('BULL', 'BEAR'):
                    icon = "🟢" if row['signal'] == 'BULL' else "🔴"
                    cons = int(row['consecutive'])
                    st.text(f"  {row['timestamp']} | {icon * min(cons,5)} {row['signal']} (x{cons}) | CE: {row['ce_chg5']:+.1f}% PE: {row['pe_chg5']:+.1f}% | Div: {row['divergence']:+.1f}")
        else:
            st.info("No ticks yet today. Start the engine: `python run.py live`")

        conn.close()
    else:
        st.info("No data yet. Run the engine first.")

# ── TAB 2: Backtest ──
with tab2:
    st.subheader("Run Backtest")

    col1, col2 = st.columns(2)
    with col1:
        bt_date = st.date_input("Date", value=datetime(2026, 4, 16))
        ce_key = st.text_input("CE Instrument Key", "NSE_FO|63430")
        pe_key = st.text_input("PE Instrument Key", "NSE_FO|63437")
    with col2:
        ce_strike = st.number_input("CE Strike", value=24300)
        pe_strike = st.number_input("PE Strike", value=24400)
        nifty_open = st.number_input("Nifty Open", value=24385.2)
        nifty_close = st.number_input("Nifty Close", value=24196.75)

    if st.button("Run Backtest", type="primary"):
        with st.spinner("Running backtest..."):
            # Capture print output
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                run_backtest(
                    str(bt_date), ce_key, pe_key,
                    ce_strike, pe_strike, nifty_open, nifty_close
                )
            st.code(f.getvalue(), language="text")

# ── TAB 3: History ──
with tab3:
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)

        st.subheader("Daily Results")
        summary = pd.read_sql("SELECT * FROM daily_summary ORDER BY date DESC", conn)
        if len(summary) > 0:
            st.dataframe(summary, use_container_width=True)

            correct = len(summary[summary['result'] == 'CORRECT'])
            total = len(summary[summary['result'].isin(['CORRECT', 'WRONG'])])
            if total > 0:
                st.metric("Win Rate", f"{correct}/{total} ({correct/total*100:.0f}%)")

        st.subheader("All Signals")
        all_signals = pd.read_sql("SELECT * FROM signals ORDER BY date DESC, timestamp", conn)
        if len(all_signals) > 0:
            st.dataframe(all_signals, use_container_width=True)

        conn.close()
    else:
        st.info("No historical data yet.")
