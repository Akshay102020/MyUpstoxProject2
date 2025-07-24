# upstox_screener_app.py
# Streamlit removed due to missing module; using CLI-based alternative
from upstox_api.api import Session, Upstox, LiveFeedType, Instrument
import pandas as pd
import webbrowser
import time
from callback_server import auth_code, start_server

# --- CONFIG ---
API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"
REDIRECT_URI = "http://localhost:8000"

# --- Start Flask callback server in background ---
start_server()

print("\n🔐 Starting Upstox Login Flow...")
session = Session(API_KEY)
login_url = session.get_login_url(REDIRECT_URI)
print(f"\n👉 Please open the following URL in your browser and authorize the app:\n{login_url}")
webbrowser.open(login_url)

print("\n⏳ Waiting for Upstox authorization...")
for _ in range(60):
    time.sleep(1)
    if 'code' in auth_code:
        break

if 'code' not in auth_code:
    print("❌ Authorization failed or timed out.")
    exit()

try:
    session.set_code(auth_code['code'])
    token = session.retrieve_access_token(API_SECRET)
    u = Upstox(API_KEY, token)
    profile = u.get_profile()
    print(f"\n✅ Login successful. Logged in as: {profile['name']}")
except Exception as e:
    print(f"Login failed: {e}")
    exit()

print("\n🔎 Fetching instrument data...")
all_instruments = pd.DataFrame(u.get_instruments())
fno_stocks = all_instruments[
    (all_instruments['segment'] == 'NSE-FUT') &
    (~all_instruments['symbol'].str.contains("NIFTY|BANKNIFTY"))
].drop_duplicates('symbol')

momentum_stocks = []
for _, row in fno_stocks.iterrows():
    try:
        instrument = Instrument(row['exchange'], row['token'], row['symbol'],
                                row['lot_size'], row['instrument_type'],
                                row['strike_price'], row['expiry'], row['name'],
                                row['tick_size'])
        quote = u.get_live_feed(instrument, LiveFeedType.LTP)
        ltp = quote['ltp']
        open_ = quote['open']
        vwap = quote['vwap']
        volume = quote['volume']

        if open_ > 0:
            pct_change = ((ltp - open_) / open_) * 100
            if abs(pct_change) >= 2 and volume >= 500000:
                direction = "Bullish" if ltp > vwap else "Bearish"
                momentum_stocks.append({
                    'symbol': row['symbol'],
                    'ltp': ltp,
                    'momentum': direction
                })
    except:
        continue

top5 = pd.DataFrame(momentum_stocks).head(5)

final_results = []
for _, stock in top5.iterrows():
    symbol = stock['symbol']
    ltp = stock['ltp']
    direction = stock['momentum']

    opt_data = all_instruments[
        (all_instruments['segment'] == 'NFO-OPT') &
        (all_instruments['symbol'] == symbol)
    ]

    if opt_data.empty:
        continue

    nearest_expiry = opt_data['expiry'].min()
    opt_data = opt_data[opt_data['expiry'] == nearest_expiry]

    if direction == "Bullish":
        otm_opts = opt_data[(opt_data['instrument_type'] == 'CE') & (opt_data['strike_price'] > ltp)]
    else:
        otm_opts = opt_data[(opt_data['instrument_type'] == 'PE') & (opt_data['strike_price'] < ltp)]

    otm_opts = otm_opts.sort_values(by='strike_price').head(5)

    for _, opt in otm_opts.iterrows():
        try:
            inst = Instrument(opt['exchange'], opt['token'], opt['symbol'],
                              opt['lot_size'], opt['instrument_type'],
                              opt['strike_price'], opt['expiry'], opt['name'],
                              opt['tick_size'])
            quote = u.get_live_feed(inst, LiveFeedType.LTP)
            ltp = quote['ltp']
            change = quote['change']
            oi = quote['oi']

            if ltp <= 700 and change >= 7:
                final_results.append({
                    'stock': symbol,
                    'momentum': direction,
                    'type': opt['instrument_type'],
                    'strike': opt['strike_price'],
                    'expiry': opt['expiry'],
                    'option_ltp': ltp,
                    '% gain': change,
                    'OI': oi
                })
        except:
            continue

if final_results:
    df = pd.DataFrame(final_results).sort_values(by='OI', ascending=False).head(5)
    print("\n📈 Top 5 OTM Options (LTP ≤ ₹700 & Gain ≥ 7%):")
    print(df.to_string(index=False))
else:
    print("\n⚠️ No matching OTM options found based on criteria.")
