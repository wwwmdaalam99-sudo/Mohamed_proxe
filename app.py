import os
import time
import threading
import requests
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException

app = Flask(__name__)

# ===== CONFIG - Aap yaha change kar sakte ho Bhai =====
TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"] # Jin coins pe trading karni hai
TRADE_PERCENT = 10  # Balance ka kitna % ek trade me use hoga (10% safe hai)
STOP_LOSS_PERCENT = 2  # 2% loss pe auto sell
TAKE_PROFIT_PERCENT = 3 # 3% profit pe auto sell

# ===== Telegram =====
def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# ===== Flask Health Check - Render ke liye zaroori hai =====
@app.route('/')
def home():
    return "✅ Mohamed REAL Trading Bot LIVE - 24/7 Running"
@app.route('/health')
def health(): return "OK", 200

# ===== REAL TRADING BOT =====
def get_balance(client, asset="USDT"):
    try:
        bal = client.get_asset_balance(asset=asset)
        return float(bal['free'])
    except: return 0.0

def get_current_price(client, symbol):
    return float(client.get_symbol_ticker(symbol=symbol)['price'])

def trading_bot():
    print("🚀 REAL Bot Starting...")
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ API Key Missing!")
        return

    client = Client(api_key, api_secret)
    
    usdt_bal = get_balance(client, "USDT")
    send_telegram(f"✅ BOT LIVE Bhai!\n💰 USDT Balance: ${usdt_bal:.2f}\n🤖 Auto Trading Started: {', '.join(TRADE_SYMBOLS)}")

    # Entry price yaad rakhne ke liye
    entry_prices = {}

    while True:
        try:
            for symbol in TRADE_SYMBOLS:
                base_coin = symbol.replace("USDT","")
                current_price = get_current_price(client, symbol)
                
                # Klines se EMA nikalte hain - simple strategy
                klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_5MINUTE, limit=50)
                closes = [float(k[4]) for k in klines]
                
                ema9 = sum(closes[-9:]) / 9
                ema21 = sum(closes[-21:]) / 21

                usdt_balance = get_balance(client, "USDT")
                coin_balance = get_balance(client, base_coin)

                # ===== BUY CONDITION - 9 EMA ne 21 EMA ko upar kaata =====
                if ema9 > ema21 and usdt_balance > 10:
                    # Agar pehle se coin nahi hai to BUY karo
                    if coin_balance * current_price < 5: # 5$ se kam hai to naya BUY
                        buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                        if buy_usdt > 10:
                            qty = round(buy_usdt / current_price, 6)
                            try:
                                order = client.create_order(symbol=symbol, side='BUY', type='MARKET', quoteOrderQty=buy_usdt)
                                entry_prices[symbol] = current_price
                                send_telegram(f"🟢 REAL BUY Bhai!\nCoin: {symbol}\nPrice: ${current_price}\nQty: ${buy_usdt:.2f} USDT se")
                                print(f"BUY {symbol} at {current_price}")
                            except BinanceAPIException as e:
                                print(f"Buy Error {symbol}: {e}")

                # ===== SELL CONDITION - Profit ya Loss pe =====
                if symbol in entry_prices and coin_balance * current_price > 5:
                    entry = entry_prices[symbol]
                    pnl_percent = ((current_price - entry) / entry) * 100

                    # Stop Loss ya Take Profit ya EMA Cross Down
                    if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 < ema21:
                        try:
                            # Sare coins becho
                            qty_to_sell = round(coin_balance, 6)
                            # Binance lot size ke liye info lena padta hai, simple ke liye free balance becho
                            order = client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                            send_telegram(f"{'🔴 LOSS SELL' if pnl_percent < 0 else '💰 PROFIT SELL'} Bhai!\nCoin: {symbol}\nEntry: ${entry:.2f} -> Exit: ${current_price:.2f}\nPNL: {pnl_percent:.2f}%\nBalance: ${get_balance(client,'USDT'):.2f}")
                            del entry_prices[symbol]
                            print(f"SELL {symbol} PNL {pnl_percent}%")
                        except BinanceAPIException as e:
                            # Lot size error aaye to thoda kam karke try karo
                            try:
                                qty_to_sell = round(coin_balance * 0.99, 6)
                                client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                            except Exception as e2:
                                print(f"Sell Error {symbol}: {e2}")

                time.sleep(2) # Har coin ke beech 2 sec gap

            print(f"✅ Cycle Complete - USDT: ${get_balance(client,'USDT'):.2f}")
            time.sleep(30) # 30 sec baad fir check karega

        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(10)

# Bot ko background me start
threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
