import os
import time
import threading
import requests
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot
app = Flask(__name__)

# ===== CONFIG - 5% PROFIT / 3% LOSS Bhai =====
TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
TRADE_PERCENT = 10
STOP_LOSS_PERCENT = 3   # 3% Loss pe SELL Bhai
TAKE_PROFIT_PERCENT = 5 # 5% Profit pe SELL Bhai

# ===== Telegram Send =====
def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# ===== TELEGRAM /start /balance /status COMMAND =====
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = None
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)

    @bot.message_handler(commands=['start'])
    def start_cmd(m):
        bot.reply_to(m, "✅ Mohamed Bot LIVE Bhai! 🚀\n\nStrategy: 5% Profit / 3% Loss\n\nCommands:\n/start - Status\n/balance - USDT + AED Balance\n/status - Trading Info\n\n24/7 Auto Trading ON hai!")

    @bot.message_handler(commands=['balance'])
    def balance_cmd(m):
        try:
            api_key = os.environ.get("BINANCE_API_KEY")
            api_secret = os.environ.get("BINANCE_API_SECRET")
            client = Client(api_key, api_secret)
            usdt = float(client.get_asset_balance(asset="USDT")['free'])
            aed = usdt * 3.67
            bot.reply_to(m, f"💰 Balance Bhai:\nUSDT: ${usdt:.2f}\nAED: {aed:.2f} AED\nRate: 3.67")
        except Exception as e:
            bot.reply_to(m, f"Error: {e}")

    @bot.message_handler(commands=['status'])
    def status_cmd(m):
        bot.reply_to(m, f"📊 Auto Trading ON Bhai!\nCoins: {', '.join(TRADE_SYMBOLS)}\nProfit: {TAKE_PROFIT_PERCENT}% | Loss: {STOP_LOSS_PERCENT}%\nTrade Size: {TRADE_PERCENT}%\nCheck: Har 30 sec")

    def run_telebot():
        print("🤖 Telegram Bot Running...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                print(f"Telebot Error: {e}")
                time.sleep(10)

    threading.Thread(target=run_telebot, daemon=True).start()

# ===== Flask =====
@app.route('/')
def home():
    return "✅ Mohamed Bot LIVE - 5% Profit / 3% Loss - AED + /start Working!"

@app.route('/health')
def health(): return "OK", 200

# ===== TRADING BOT =====
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
    aed_bal = usdt_bal * 3.67
    send_telegram(f"✅ BOT LIVE Bhai!\n💰 USDT: ${usdt_bal:.2f}\n💵 AED: {aed_bal:.2f} AED\n🎯 Strategy: 5% Profit / 3% Loss\n🤖 Auto Trading Started!")

    entry_prices = {}

    while True:
        try:
            for symbol in TRADE_SYMBOLS:
                base_coin = symbol.replace("USDT", "")
                current_price = get_current_price(client, symbol)

                klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=30)
                closes = [float(k[4]) for k in klines]
                ema9 = sum(closes[-9:]) / 9
                ema21 = sum(closes[-21:]) / 21

                usdt_balance = get_balance(client, "USDT")
                coin_balance = get_balance(client, base_coin)

                # BUY - EMA Cross Up
                if ema9 > ema21 and usdt_balance > 10:
                    if coin_balance * current_price < 5:
                        buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                        if buy_usdt > 10:
                            qty = round(buy_usdt / current_price, 6)
                            try:
                                order = client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                entry_prices[symbol] = current_price
                                send_telegram(f"🟢 BUY Bhai!\nCoin: {symbol}\nPrice: {current_price}\nUSDT: ${buy_usdt:.2f}\nAED: {buy_usdt*3.67:.2f} AED")
                                print(f"BUY {symbol} at {current_price}")
                            except BinanceAPIException as e:
                                print(f"Buy Error {symbol}: {e}")

                # SELL - 5% Profit ya 3% Loss ya EMA Down
                if symbol in entry_prices and coin_balance * current_price > 5:
                    entry = entry_prices[symbol]
                    pnl_percent = ((current_price - entry) / entry) * 100

                    if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 < ema21:
                        try:
                            qty_to_sell = round(coin_balance, 6)
                            order = client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                            pnl_aed = (current_price - entry) * coin_balance * 3.67
                            send_telegram(f"{'🟢 5% PROFIT SELL' if pnl_percent > 0 else '🔴 3% LOSS SELL'} Bhai!\nCoin: {symbol}\nPNL: {pnl_percent:.2f}%\nAED PNL: {pnl_aed:.2f} AED")
                            del entry_prices[symbol]
                            print(f"SELL {symbol} PNL {pnl_percent}%")
                        except BinanceAPIException as e:
                            try:
                                qty_to_sell = round(coin_balance * 0.99, 6)
                                client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                            except Exception as e2:
                                print(f"Sell Error {symbol}: {e2}")

                time.sleep(2)

            print(f"✅ Cycle Complete - USDT: ${get_balance(client,'USDT'):.2f}")
            time.sleep(30)

        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(10)

threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
