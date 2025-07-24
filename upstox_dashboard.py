# upstox_dashboard.py - Streamlit Dashboard for Visual Screener with Live Updates + Telegram Alerts
import streamlit as st
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
from upstox_api.api import Session, Upstox, OHLCInterval
import requests  # For Telegram alerts
import numpy as np

st.set_page_config(layout="wide")
st.title("📊 Upstox Intraday Screener Dashboard")

# Telegram Setup
TELEGRAM_TOKEN = st.secrets["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
DASHBOARD_URL = st.secrets.get("DASHBOARD_URL", "http://localhost:8501")  # Optional link to chart view


def send_telegram_alert(message: str):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, data=payload)
        except Exception as e:
            st.warning(f"Telegram alert failed: {e}")

# Auto-refresh every 30 seconds (manual override using streamlit option)
refresh_interval = st.sidebar.number_input("Auto-refresh (seconds)", min_value=10, max_value=300, value=60, step=10)
st_autorefresh = st.empty()
st_autorefresh.markdown(f"⏱️ Auto-refreshing every {refresh_interval} seconds...")

# Load reports with loop for auto-refresh
@st.cache_data(ttl=refresh_interval)
def load_data():
    screener = pd.read_excel("screener_report.xlsx")
    otm = pd.read_excel("otm_options_report.xlsx")
    return screener, otm

screener_df, otm_df = load_data()

# Auto Telegram Alerts for Top Screener and OTM
if not screener_df.empty:
    top_stock = screener_df.iloc[0]
    screener_msg = f"📈 *Top Momentum Stock Alert: {top_stock['symbol']}*\nLTP: ₹{top_stock['ltp']}\nVWAP: ₹{top_stock['vwap']}\nMomentum: {top_stock['momentum']}\n[📊 View Dashboard]({DASHBOARD_URL})"
    send_telegram_alert(screener_msg)

if not otm_df.empty:
    top_otm = otm_df.iloc[0]
    otm_msg = f"🟢 *Top OTM Option Alert: {top_otm['symbol']}*\nStrike: {top_otm['strike']} | LTP: ₹{top_otm['ltp']}\nChange: {top_otm['change']}% | OI Change: {top_otm['oi_change']}%\n[📊 View Dashboard]({DASHBOARD_URL})"
    send_telegram_alert(otm_msg)

# Setup Upstox session using secure environment vars
@st.cache_resource
def init_upstox():
    api_key = st.secrets["UPSTOX_API_KEY"]
    access_token = st.secrets["UPSTOX_ACCESS_TOKEN"]

    session = Session(api_key)
    session.set_access_token(access_token)
    upstox = Upstox(session)
    upstox.get_master_contract('NSE_EQ')
    upstox.get_master_contract('NSE_INDEX')
    upstox.get_master_contract('NSE_FO')
    return upstox

upstox_obj = init_upstox()

# Layout
col1, col2 = st.columns(2)

with col1:
    st.subheader("Top Intraday Momentum F&O Stocks")
    st.dataframe(screener_df.style.background_gradient(cmap="YlGn"), use_container_width=True)

with col2:
    st.subheader("Top 5 OTM Options")
    st.dataframe(otm_df.style.background_gradient(cmap="OrRd"), use_container_width=True)

# Filters
st.sidebar.header("Filters")
sectors = st.sidebar.multiselect("Sector (mocked)", options=screener_df['symbol'].unique())
momentum = st.sidebar.selectbox("Momentum Direction", options=["All", "Bullish", "Bearish"])

filtered_df = screener_df.copy()
if sectors:
    filtered_df = filtered_df[filtered_df['symbol'].isin(sectors)]
if momentum != "All":
    filtered_df = filtered_df[filtered_df['momentum'] == momentum]

st.sidebar.markdown("---")
st.sidebar.caption("Updated: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

# --- Charts ---
st.subheader("📈 VWAP & Price Chart Previews")
selected_symbol = st.selectbox("Select a stock for VWAP chart preview", filtered_df['symbol'].unique())

if selected_symbol:
    selected_row = filtered_df[filtered_df['symbol'] == selected_symbol].iloc[0]

    fig = go.Figure()
    fig.add_trace(go.Indicator(
        mode="number+delta",
        value=selected_row['ltp'],
        delta={"reference": selected_row['vwap'], "valueformat": ".2f"},
        title={"text": f"{selected_symbol} LTP vs VWAP"}
    ))
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=['LTP', 'VWAP'], y=[selected_row['ltp'], selected_row['vwap']],
                          marker_color=['green', 'blue']))
    fig2.update_layout(title=f"{selected_symbol} LTP vs VWAP", yaxis_title="Price")
    st.plotly_chart(fig2, use_container_width=True)

    # --- Mini Candlestick Chart (Live OHLC from Upstox) ---
    st.subheader("🕯️ Mini Candlestick Chart + Technical Indicators")

    # --- Indicator toggles ---
    show_vwap = st.checkbox("Show VWAP", value=True)
    show_macd = st.checkbox("Show MACD", value=True)
    show_rsi = st.checkbox("Show RSI", value=True)

    try:
        now = datetime.datetime.now()
        start_time = now - datetime.timedelta(hours=1)
        end_time = now

        instrument = upstox_obj.get_instrument_by_symbol('NSE_EQ', selected_symbol)
        candles = upstox_obj.get_ohlc(instrument, OHLCInterval.Minute_5, start_time, end_time)

        if candles:
            ohlc_data = pd.DataFrame(candles)
            ohlc_data.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
            ohlc_data['time'] = pd.to_datetime(ohlc_data['time'])

            # Calculate indicators
            ohlc_data['vwap'] = (ohlc_data['volume'] * (ohlc_data['high'] + ohlc_data['low'] + ohlc_data['close']) / 3).cumsum() / ohlc_data['volume'].cumsum()
            ohlc_data['rsi'] = ohlc_data['close'].diff().apply(lambda x: max(x, 0)).rolling(14).mean() / abs(ohlc_data['close'].diff()).rolling(14).mean() * 100
            exp1 = ohlc_data['close'].ewm(span=12, adjust=False).mean()
            exp2 = ohlc_data['close'].ewm(span=26, adjust=False).mean()
            ohlc_data['macd'] = exp1 - exp2

            candle = go.Figure()
            candle.add_trace(go.Candlestick(
                x=ohlc_data['time'], open=ohlc_data['open'], high=ohlc_data['high'],
                low=ohlc_data['low'], close=ohlc_data['close'],
                increasing_line_color='green', decreasing_line_color='red'
            ))
            if show_vwap:
                candle.add_trace(go.Scatter(x=ohlc_data['time'], y=ohlc_data['vwap'], mode='lines', name='VWAP'))
            if show_macd:
                candle.add_trace(go.Scatter(x=ohlc_data['time'], y=ohlc_data['macd'], mode='lines', name='MACD'))

            candle.update_layout(title=f"{selected_symbol} - Candlestick + Indicators", xaxis_rangeslider_visible=False)
            st.plotly_chart(candle, use_container_width=True)

            if show_rsi:
                st.line_chart(ohlc_data.set_index('time')['rsi'].dropna(), use_container_width=True)
        else:
            st.warning("No candlestick data available.")

    except Exception as e:
        st.error(f"Error fetching OHLC data: {e}")

    # Optional: Telegram alert trigger for top stock
    if st.button("Send Telegram Alert for this Stock"):
        msg = f"🚨 *Momentum Alert: {selected_symbol}*\nLTP: ₹{selected_row['ltp']}\nVWAP: ₹{selected_row['vwap']}\nMomentum: {selected_row['momentum']}\n[📊 View Dashboard]({DASHBOARD_URL})"
        send_telegram_alert(msg)
        st.success("Telegram alert sent.")

# Auto-refresh UI by rerunning
st.experimental_rerun()
