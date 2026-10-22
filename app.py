import os
import time
import requests
import threading
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot

app = Flask(__name__)

# ===== CONFIG - $1 ROZ Bhai 5 TRADE Bhai - SAME HAI BHAI =====
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT"]
TRADE_PERCENT = 90
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 3.0
DAILY_PROFIT_TARGET = 2.50
DAILY_LOSS_LIMIT = 1
daily_pnl = 0

# ===== Telegram Send =====
def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

# ===== TELEGRAM /start /balance /status COMMAND =====
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
bot = None
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)

    @bot.message_handler(commands=['start'])
    def start_cmd(m):
        bot.reply_to(m, f"✅ Mohamed Bot LIVE Bhai!\n💰 Daily Target: ${DAILY_PROFIT_TARGET}\n📉 Loss Limit: ${DAILY_LOSS_LIMIT}\nCoins: {', '.join(TRADE_SYMBOLS)}\nProfit: {TAKE_PROFIT_PERCENT}% / Loss: {STOP_LOSS_PERCENT}%\nTrade: {TRADE_PERCENT}%\n/status /balance Working Bhai!")

    @bot.message_handler(commands=['balance'])
    def balance_cmd(m):
        try:
            api_key = os.environ.get("BINANCE_API_KEY")
            api_secret = os.environ.get("BINANCE_API_SECRET")
            client = Client(api_key, api_secret)
            usdt = float(client.get_asset_balance(asset="USDT")['free'])
            aed = usdt * 3.67
            bot.reply_to(m, f"💰 Balance Bhai:\nUSDT: ${usdt:.2f}\nAED: {aed:.2f} AED\nDaily PNL: ${daily_pnl:.2f}")
        except Exception as e:
            bot.reply_to(m, f"Error: {e}")

    @bot.message_handler(commands=['status'])
    def status_cmd(m):
        bot.reply_to(m, f"📊 Auto Trading ON Bhai!\nCoins: {', '.join(TRADE_SYMBOLS)}\nProfit: {TAKE_PROFIT_PERCENT}% | Loss: {STOP_LOSS_PERCENT}%\nTrade Size: {TRADE_PERCENT}%\nDaily PNL: ${daily_pnl:.2f} / Target: ${DAILY_PROFIT_TARGET}\nCheck: Har 120 sec Bhai")

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
    return f"✅ Mohamed Bot LIVE - {TAKE_PROFIT_PERCENT}% Profit / {STOP_LOSS_PERCENT}% Loss - AED + /start Working!"

@app.route('/health')
def health(): return "OK", 200

# ===== TRADING BOT =====
def get_balance(client, asset="USDT"):
    try:
        bal = client.get_asset_balance(asset=asset)
        return float(bal['free'])
    except: return 0.0

def get_current_price(client, symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except: return 0.0

def get_qty_precision(client, symbol):
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = f['stepSize']
                if '.' in step:
                    return len(step.split('.')[1].rstrip('0'))
                return 0
    except: pass
    return 0

def trading_bot():
    global daily_pnl
    print("🚀 REAL Bot Starting...")
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        print("❌ API Key Missing!")
        return

    client = Client(api_key, api_secret)
    usdt_bal = get_balance(client, "USDT")
    aed_bal = usdt_bal * 3.67
    send_telegram(f"✅ BOT LIVE Bhai! 🚀\n\nStrategy: {TAKE_PROFIT_PERCENT}% Profit / {STOP_LOSS_PERCENT}% Loss\n\n💰 USDT: ${usdt_bal:.2f}\n💵 AED: {aed_bal:.2f} AED\nTarget: ${DAILY_PROFIT_TARGET} Bhai!")

    entry_prices = {}

    while True:
        try:
            # BHAI DAILY TARGET CHECK
            if daily_pnl >= DAILY_PROFIT_TARGET:
                send_telegram(f"✅ TARGET PURA BHAI! Daily: ${daily_pnl:.2f} Bhai Kal Tak Band Bhai!")
                time.sleep(3600)
                continue
            if daily_pnl <= -DAILY_LOSS_LIMIT:
                send_telegram(f"🛑 LOSS LIMIT BHAI! Daily: ${daily_pnl:.2f} Bhai Kal Tak Band Bhai!")
                time.sleep(3600)
                continue

            for symbol in TRADE_SYMBOLS:
                try:
                    time.sleep(1.5)  # BHAI IP BAN FIX BHAI
                    base_coin = symbol.replace("USDT", "")
                    current_price = get_current_price(client, symbol)
                    if current_price == 0: continue

                    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=50)
                    closes = [float(k[4]) for k in klines]
                    ema9 = sum(closes[-9:]) / 9
                    ema21 = sum(closes[-21:]) / 21

                    usdt_balance = get_balance(client, "USDT")
                    coin_balance = get_balance(client, base_coin)

                    print(f"Bhai Check {symbol} Price:{current_price} EMA9:{ema9:.2f} EMA21:{ema21:.2f} USDT:{usdt_balance:.2f}")

                    # BUY - EMA Cross Up
                    if ema9 > ema21 and usdt_balance > 10:
                        if coin_balance * current_price < 5:
                            buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                            if buy_usdt > 10:
                                # BHAI YE FIX KIYA BHAI PRECISION KA BHAI
                                precision = get_qty_precision(client, symbol)
                                qty = round(buy_usdt / current_price, precision)
                                if qty > 0:
                                    try:
                                        order = client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                        entry_prices[symbol] = current_price
                                        send_telegram(f"🟢 BUY Bhai!\nCoin: {symbol}\nPrice: {current_price}\nQty: {qty}")
                                        print(f"BUY {symbol} at {current_price}")
                                    except BinanceAPIException as e:
                                        print(f"Buy Error {symbol}: {e}")

                    # SELL - 3% Profit ya 1.2% Loss ya EMA Down
                    if symbol in entry_prices and coin_balance * current_price > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = ((current_price - entry) / entry) * 100

                        if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 < ema21:
                            try:
                                # BHAI YE BHI FIX KIYA BHAI PRECISION KA
                                precision = get_qty_precision(client, symbol)
                                qty_to_sell = round(coin_balance * 0.99, precision)
                                if qty_to_sell > 0:
                                    order = client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    pnl_aed = (current_price - entry) * coin_balance * 3.67
                                    profit_dollar = (current_price - entry) * coin_balance
                                    daily_pnl += profit_dollar
                                    send_telegram(f"{'🟢 3% PROFIT SELL' if pnl_percent > 0 else '🔴 LOSS SELL'} Bhai!\nCoin: {symbol}\nPNL: {pnl_percent:.2f}% (${profit_dollar:.2f} / AED {pnl_aed:.2f})\nDaily: ${daily_pnl:.2f}")
                                    del entry_prices[symbol]
                                    print(f"SELL - {symbol} PNL {pnl_percent}%")
                            except BinanceAPIException as e:
                                try:
                                    # BHAI AGAR SELL FAIL HO TO DOBARA TRY BHAI
                                    qty_to_sell = round(coin_balance, precision)
                                    client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    del entry_prices[symbol]
                                except Exception as e2:
                                    print(f"Sell Error {symbol}: {e2}")
                                    pass
                except Exception as e:
                    print(f"Error {symbol}: {e}")
                    continue

                time.sleep(15)

            print(f"✅ Cycle Complete - USDT: ${get_balance(client, 'USDT'):.2f} Bhai")
            time.sleep(120)

        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(10)

threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
        
