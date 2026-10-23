import os, time, requests, threading
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot

app = Flask(__name__)

# ===== COIN WAISE HI BHAI 6 COIN BHAI =====
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT"]

COINS_DIP = {
    "SOLUSDT": -1.0,
    "DOGEUSDT": -1.5,
    "PEPEUSDT": -3.0,
    "SHIBUSDT": -3.0,
    "BONKUSDT": -5.0,
    "FLOKIUSDT": -5.0
}

TRADE_PERCENT = 90
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 2.0
daily_pnl = 0

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
bot = None
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    @bot.message_handler(commands=['start'])
    def start_cmd(m):
        bot.reply_to(m, f"✅ Mohamed DIP Bot LIVE Bhai 24H Bhai!\nCoins: {', '.join(TRADE_SYMBOLS)}\nUnlimited Trades Bhai!")
    @bot.message_handler(commands=['balance'])
    def balance_cmd(m):
        try:
            api_key = os.environ.get("BINANCE_API_KEY")
            api_secret = os.environ.get("BINANCE_API_SECRET")
            client = Client(api_key, api_secret)
            usdt = float(client.get_asset_balance(asset="USDT")['free'])
            bot.reply_to(m, f"💰 Balance Bhai: ${usdt:.2f}\nPNL: ${daily_pnl:.2f}")
        except Exception as e:
            bot.reply_to(m, f"Error: {e} Bhai 10 min baad try kar Bhai!")
    @bot.message_handler(commands=['status'])
    def status_cmd(m):
        bot.reply_to(m, f"📊 DIP Bot ON Bhai! Coins: {', '.join(TRADE_SYMBOLS)} PNL: ${daily_pnl:.2f} Bhai 24H Nonstop Bhai!")

    def run_telebot():
        while True:
            try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except: time.sleep(10)
    threading.Thread(target=run_telebot, daemon=True).start()

@app.route('/')
def home(): return f"✅ Mohamed DIP Bot LIVE 24H - {TAKE_PROFIT_PERCENT}% Profit Bhai"
@app.route('/health')
def health(): return "OK", 200

def get_balance(client, asset="USDT"):
    try: return float(client.get_asset_balance(asset=asset)['free'])
    except: return 0.0

def get_current_price(client, symbol):
    try: return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except: return 0.0

# BHAI PRECISION CACHE BHAI BAN FIX BHAI
PRECISION_CACHE = {}
def get_qty_precision(client, symbol):
    if symbol in PRECISION_CACHE: return PRECISION_CACHE[symbol]
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = f['stepSize']
                prec = len(step.split('.')[1].rstrip('0')) if '.' in step else 0
                PRECISION_CACHE[symbol] = prec
                return prec
    except: pass
    return 3

def trading_bot():
    global daily_pnl
    print("🚀 DIP Bot 24H Starting... Bhai!")
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    client = Client(api_key, api_secret)
    usdt_bal = get_balance(client, "USDT")
    send_telegram(f"✅ DIP BOT LIVE 24H Bhai! 🚀\n💰 USDT: ${usdt_bal:.2f}\nCoins 6 Bhai Unlimited Trades Bhai!")

    entry_prices = {}
    while True:
        try:
            # BHAI USDT EK BAAR LO BHAI 6 BAAR NAHI BHAI - BAN FIX BHAI
            usdt_balance = get_balance(client, "USDT")
            print(f"Bhai Cycle Start USDT ${usdt_balance:.2f} Bhai")

            for symbol in TRADE_SYMBOLS:
                try:
                    base_coin = symbol.replace("USDT", "")
                    current_price = get_current_price(client, symbol)
                    if current_price == 0: 
                        time.sleep(5)
                        continue

                    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=21)
                    closes = [float(k[4]) for k in klines]
                    ema9 = sum(closes[-9:]) / 9
                    ema21 = sum(closes[-21:]) / 21
                    price_1h_ago = closes[-4]
                    dip_percent = ((current_price - price_1h_ago) / price_1h_ago) * 100
                    dip_needed = COINS_DIP.get(symbol, -1.0)
                    coin_balance = get_balance(client, base_coin)

                    print(f"Bhai {symbol} Dip:{dip_percent:.2f}% Need:{dip_needed}%")

                    if ema9 < ema21 and dip_percent <= dip_needed and usdt_balance > 11:
                        if coin_balance * current_price < 5:
                            buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                            if buy_usdt < 10: buy_usdt = 10
                            if buy_usdt > usdt_balance: buy_usdt = usdt_balance - 0.5
                            if buy_usdt >= 10:
                                precision = get_qty_precision(client, symbol)
                                qty = round(buy_usdt / current_price, precision)
                                if qty > 0:
                                    try:
                                        client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                        entry_prices[symbol] = current_price
                                        usdt_balance -= buy_usdt
                                        send_telegram(f"🟢 DIP BUY Bhai! {symbol} Dip {dip_percent:.2f}% Price {current_price} Bhai!")
                                    except BinanceAPIException as e:
                                        print(f"Buy Error {symbol}: {e}")

                    if symbol in entry_prices and coin_balance * current_price > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = ((current_price - entry) / entry) * 100
                        if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 > ema21:
                            try:
                                precision = get_qty_precision(client, symbol)
                                qty_to_sell = round(coin_balance * 0.99, precision)
                                if qty_to_sell > 0:
                                    client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    profit_dollar = (current_price - entry) * coin_balance
                                    daily_pnl += profit_dollar
                                    send_telegram(f"{'🟢 PROFIT' if pnl_percent>0 else '🔴 LOSS'} {symbol} PNL {pnl_percent:.2f}% Daily ${daily_pnl:.2f} Bhai")
                                    del entry_prices[symbol]
                            except Exception as e2:
                                print(f"Sell Error {symbol}: {e2}")
                except Exception as e:
                    print(f"Error {symbol}: {e}")
                time.sleep(10) # BHAI 10 SEC RUK BHAI HAR COIN PE BHAI BAN NAHI LAGEGA BHAI

            print(f"✅ Cycle Complete Bhai - Next 10 min me Bhai")
            time.sleep(600) # BHAI TIME 600 KAR DIYA BHAI 180 SE BAN LAG RAHA THA BHAI

        except Exception as e:
            print(f"Loop Error: {e}")
            if "-1003" in str(e) or "banned" in str(e) or "1003" in str(e):
                print("BHAI BAN LAGA BHAI 10 MIN RUK BHAI!")
                send_telegram("⚠️ Ban Laga Bhai 10 Min Ruk Raha Hu Bhai!")
                time.sleep(600)
            else:
                time.sleep(30)

threading.Thread(target=trading_bot, daemon=True).start()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
