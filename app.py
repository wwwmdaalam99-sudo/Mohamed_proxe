import os
import json
import time
from datetime import datetime
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot

# ===== BHAI CONFIG =====
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT"]
TRADE_PERCENT = 40
TAKE_PROFIT = 6.0
STOP_LOSS = 2.5
DAILY_TARGET = 2.50
DAILY_LOSS_LIMIT = -3.00
CHECK_TIME = 300
MIN_USDT = 10

client = Client(API_KEY, API_SECRET)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

def load_json(file, default):
    try:
        if os.path.exists(file):
            with open(file, "r") as f:
                return json.load(f)
    except: pass
    return default

def save_json(file, data):
    try:
        with open(file, "w") as f:
            json.dump(data, f)
    except: pass

entry_prices = load_json("entries.json", {})
pnl_data = load_json("pnl.json", {"date": str(datetime.now().date()), "pnl": 0.0})
daily_pnl = pnl_data["pnl"]
if pnl_data["date"] != str(datetime.now().date()):
    daily_pnl = 0.0
    save_json("pnl.json", {"date": str(datetime.now().date()), "pnl": 0.0})

trading_active = True

def send_telegram(msg):
    try:
        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
    except: pass

def get_balance(asset):
    try:
        bal = client.get_asset_balance(asset=asset)
        return float(bal['free'])
    except: return 0.0

def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except: return 0.0

def get_ema(prices, period):
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def get_qty_precision(symbol):
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = f['stepSize']
                if '.' in step:
                    return len(step.split('.')[1].rstrip('0'))
                return 0
    except: pass
    return 1 if "SOL" in symbol else 0

def check_and_trade():
    global daily_pnl, entry_prices
    while True:
        try:
            if not trading_active:
                time.sleep(10)
                continue
            if daily_pnl >= DAILY_TARGET:
                send_telegram(f"✅ *TARGET PURA BHAI!* Daily PNL: ${daily_pnl:.2f}\nBot Kal Tak Band Bhai!")
                time.sleep(86400)
                continue
            if daily_pnl <= DAILY_LOSS_LIMIT:
                send_telegram(f"🛑 *LOSS LIMIT BHAI!* Daily PNL: ${daily_pnl:.2f}\nBot Kal Tak Band Bhai! Paise Bach Gaye Bhai!")
                time.sleep(86400)
                continue

            usdt_balance = get_balance("USDT")
            for symbol in TRADE_SYMBOLS:
                try:
                    time.sleep(1.5)
                    base = symbol.replace("USDT", "")
                    coin_balance = get_balance(base)
                    current_price = get_price(symbol)
                    if current_price == 0: continue
                    coin_value = coin_balance * current_price
                    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=50)
                    closes = [float(k[4]) for k in klines]
                    if len(closes) < 21: continue
                    ema9 = get_ema(closes, 9)
                    ema21 = get_ema(closes, 21)

                    if symbol in entry_prices and coin_value > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = (current_price - entry) / entry * 100
                        profit_dollar = (current_price - entry) * coin_balance
                        if pnl_percent >= TAKE_PROFIT or pnl_percent <= -STOP_LOSS or ema9 < ema21:
                            precision = get_qty_precision(symbol)
                            qty_to_sell = round(coin_balance * 0.99, precision)
                            if qty_to_sell > 0:
                                client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                daily_pnl += profit_dollar
                                save_json("pnl.json", {"date": str(datetime.now().date()), "pnl": daily_pnl})
                                status = "🟢 PROFIT" if profit_dollar > 0 else "🔴 LOSS"
                                send_telegram(f"{status} SELL Bhai!\nCoin: {symbol}\nPNL: {pnl_percent:.2f}% (${profit_dollar:.2f})\nDaily: ${daily_pnl:.2f}")
                                del entry_prices[symbol]
                                save_json("entries.json", entry_prices)

                    elif coin_value < 1 and usdt_balance > MIN_USDT:
                        if ema9 > ema21:
                            buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                            if buy_usdt >= MIN_USDT:
                                precision = get_qty_precision(symbol)
                                qty = round(buy_usdt / current_price, precision)
                                if qty > 0:
                                    client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                    entry_prices[symbol] = current_price
                                    save_json("entries.json", entry_prices)
                                    send_telegram(f"🟡 BUY Bhai!\nCoin: {symbol}\nPrice: ${current_price}\nQty: {qty}")
                                    usdt_balance = get_balance("USDT")
                except Exception as e:
                    print(f"Error {symbol}: {e}")
                    continue
            time.sleep(CHECK_TIME)
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(60)

@bot.message_handler(commands=['start', 'status', 'balance'])
def handle_status(message):
    usdt = get_balance("USDT")
    sol = get_balance("SOL")
    doge = get_balance("DOGE")
    send_telegram(f"📊 *BOT STATUS BHAI*\nUSDT: ${usdt:.2f}\nSOL: {sol}\nDOGE: {doge}\nDaily PNL: ${daily_pnl:.2f}\nTarget: +${DAILY_TARGET} / Loss: ${DAILY_LOSS_LIMIT}")

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    global trading_active
    trading_active = False
    send_telegram("🛑 Trading Band Bhai!")

@bot.message_handler(commands=['start_trading'])
def handle_start(message):
    global trading_active
    trading_active = True
    send_telegram("▶️ Trading Shuru Bhai!")

threading.Thread(target=check_and_trade, daemon=True).start()
send_telegram(f"🚀 *BOT STARTED BHAI!*\nBalance: ${get_balance('USDT'):.2f}\nTarget: +${DAILY_TARGET} Loss: ${DAILY_LOSS_LIMIT}")
bot.infinity_polling() 
