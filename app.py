import os
import time
import requests
import threading
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot
import pandas as pd

app = Flask(__name__)

# ===== CONFIG - DIP BUY BHAI =====
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT"]

COINS_DIP = {
    "SOLUSDT": -1.0,
    "DOGEUSDT": -1.5,
    "PEPEUSDT": -3.0,
    "SHIBUSDT": -3.0,
    "BONKUSDT": -5.0,
    "FLOKIUSDT": -5.0
}

TRADE_PERCENT = 50
BUY_USDT_FIXED = 6  # BHAI FIXED 6 USDT BHAI SAFE BHAI
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 2.0
DAILY_PROFIT_TARGET = 2.50
DAILY_LOSS_LIMIT = 1
FILE_ENTRY = "entry_prices.json"
FILE_PNL = "daily_pnl.json"

def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file, data):
    try:
        with open(file, "w") as f:
            json.dump(data, f)
    except: pass

daily_pnl = load_json(FILE_PNL, 0)

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
        bot.reply_to(m, f"✅ Mohamed DIP Bot LIVE Bhai!\n💰 Daily Target: ${DAILY_PROFIT_TARGET}\n📉 Loss Limit: ${DAILY_LOSS_LIMIT}\nCoins: {', '.join(TRADE_SYMBOLS)}\nProfit: {TAKE_PROFIT_PERCENT}% / Loss: {STOP_LOSS_PERCENT}%\nStrategy: NEECHE PE BUY / UPAR PE SELL Bhai!\n/status /balance Working Bhai!")

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
        entries = load_json(FILE_ENTRY, {})
        bot.reply_to(m, f"📊 DIP Bot ON Bhai!\nCoins: {', '.join(TRADE_SYMBOLS)}\nHolding: {list(entries.keys())}\nDaily PNL: ${daily_pnl:.2f} / Target: ${DAILY_PROFIT_TARGET}\nCheck: Har 600 sec Bhai")

    def run_telebot():
        print("🤖 Telegram Bot Running...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                print(f"Telebot Error: {e}")
                time.sleep(10)

    threading.Thread(target=run_telebot, daemon=True).start()

@app.route('/')
def home():
    entries = load_json(FILE_ENTRY, {})
    return f"✅ Mohamed DIP Bot LIVE - HOLDING: {entries} - PNL: ${daily_pnl:.2f}"

@app.route('/health')
def health(): return "OK", 200

def get_balance(client, asset="USDT"):
    try:
        bal = client.get_asset_balance(asset=asset)
        return float(bal['free'])
    except: return 0.0

def get_current_price(client, symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except: return 0.0

def get_qty_lot(client, symbol, usdt_amount, current_price):
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = float(f['stepSize'])
                min_qty = float(f['minQty'])
                qty = usdt_amount / current_price
                # BHAI STEP SE ROUND BHAI
                qty = qty - (qty % step)
                if qty < min_qty:
                    qty = min_qty
                # BHAI PRECISION NIKAL BHAI
                step_str = f['stepSize']
                if '.' in step_str:
                    prec = len(step_str.split('.')[1].rstrip('0'))
                    qty = round(qty, prec)
                return qty
    except: pass
    return round(usdt_amount / current_price, 6)

def get_sell_qty(client, symbol, free_qty):
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = float(f['stepSize'])
                qty = free_qty - (free_qty % step)
                step_str = f['stepSize']
                if '.' in step_str:
                    prec = len(step_str.split('.')[1].rstrip('0'))
                    qty = round(qty, prec)
                return qty
    except: pass
    return free_qty

def get_ema(closes, period):
    try:
        df = pd.DataFrame(closes, columns=['close'])
        return df['close'].ewm(span=period).mean().iloc[-1]
    except:
        return sum(closes[-period:]) / period

def trading_bot():
    global daily_pnl
    print("🚀 DIP Bot Starting... NEECHE BUY / UPAR SELL Bhai!")
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        print("❌ API Key Missing!")
        return

    client = Client(api_key, api_secret)
    usdt_bal = get_balance(client, "USDT")
    aed_bal = usdt_bal * 3.67
    send_telegram(f"✅ DIP BOT LIVE Bhai! 🚀\n💰 USDT: ${usdt_bal:.2f}\n💵 AED: {aed_bal:.2f} AED\nTarget: ${DAILY_PROFIT_TARGET} Bhai!")

    entry_prices = load_json(FILE_ENTRY, {})

    print("BHAI PURANA HOLDING CHECK KAR RAHA HU BHAI...")
    for symbol in TRADE_SYMBOLS:
        try:
            base_coin = symbol.replace("USDT", "")
            c_price = get_current_price(client, symbol)
            if c_price == 0: continue
            c_bal = get_balance(client, base_coin)
            if c_bal * c_price > 1:
                if symbol not in entry_prices:
                    try:
                        trades = client.get_my_trades(symbol=symbol, limit=10)
                        last_buys = [t for t in trades if t['isBuyer']]
                        if last_buys:
                            entry_prices[symbol] = float(last_buys[-1]['price'])
                        else:
                            entry_prices[symbol] = c_price
                    except:
                        entry_prices[symbol] = c_price
                    save_json(FILE_ENTRY, entry_prices)
                print(f"BHAI YAAD AAYA BHAI {symbol} Entry: {entry_prices[symbol]} Bhai!")
        except: pass

    while True:
        try:
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
                    time.sleep(2)
                    base_coin = symbol.replace("USDT", "")
                    current_price = get_current_price(client, symbol)
                    if current_price == 0: continue

                    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=50)
                    closes = [float(k[4]) for k in klines]
                    ema9 = get_ema(closes, 9)
                    ema21 = get_ema(closes, 21)

                    price_1h_ago = closes[-4]
                    dip_percent = ((current_price - price_1h_ago) / price_1h_ago) * 100
                    dip_needed = COINS_DIP.get(symbol, -1.0)

                    usdt_balance = get_balance(client, "USDT")
                    coin_balance = get_balance(client, base_coin)

                    print(f"Bhai Check {symbol} Price:{current_price} Dip:{dip_percent:.2f}% Need:{dip_needed}% EMA9:{ema9:.2f} EMA21:{ema21:.2f} USDT:{usdt_balance:.2f}")

                    # BHAI BUY BHAI
                    if ema9 < ema21 and dip_percent <= dip_needed and usdt_balance > 10:
                        if coin_balance * current_price < 5:
                            # BHAI FIXED USDT BHAI SAFE BHAI
                            buy_usdt = min(BUY_USDT_FIXED, usdt_balance * 0.4)
                            if buy_usdt >= 5:
                                qty = get_qty_lot(client, symbol, buy_usdt, current_price)
                                if qty > 0:
                                    try:
                                        order = client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                        entry_prices[symbol] = current_price
                                        save_json(FILE_ENTRY, entry_prices)
                                        send_telegram(f"🟢 DIP BUY Bhai! SASTA KHARIDA BHAI!\nCoin: {symbol}\nPrice: {current_price}\nDip: {dip_percent:.2f}% (Need {dip_needed}%)\nQty: {qty}\nEMA9 {ema9:.2f} < EMA21 {ema21:.2f} Bhai!")
                                        print(f"DIP BUY {symbol} at {current_price} Dip {dip_percent:.2f}%")
                                    except BinanceAPIException as e:
                                        print(f"Buy Error {symbol}: {e}")

                    # BHAI ENTRY YAAD BHAI
                    if symbol not in entry_prices and coin_balance * current_price > 1:
                        entry_prices[symbol] = current_price
                        save_json(FILE_ENTRY, entry_prices)

                    # BHAI SELL BHAI - 100% BECHEGA BHAI
                    if symbol in entry_prices and coin_balance * current_price > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = ((current_price - entry) / entry) * 100

                        if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 > ema21:
                            try:
                                qty_to_sell = get_sell_qty(client, symbol, coin_balance)
                                if qty_to_sell > 0:
                                    order = client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    profit_dollar = (current_price - entry) * qty_to_sell
                                    daily_pnl += profit_dollar
                                    save_json(FILE_PNL, daily_pnl)
                                    reason = "PROFIT" if pnl_percent > 0 else "LOSS"
                                    if ema9 > ema21:
                                        reason = "UPAR GAYA - MEHENGA BECHA BHAI"
                                    send_telegram(f"{'🟢 PROFIT SELL - UPAR BECHA BHAI!' if pnl_percent > 0 else '🔴 LOSS SELL'} Bhai!\nCoin: {symbol}\nReason: {reason}\nPNL: {pnl_percent:.2f}% (${profit_dollar:.2f})\nDaily: ${daily_pnl:.2f}")
                                    del entry_prices[symbol]
                                    save_json(FILE_ENTRY, entry_prices)
                                    print(f"SELL - {symbol} PNL {pnl_percent}% Reason: {reason}")
                            except BinanceAPIException as e:
                                print(f"Sell Error {symbol}: {e}")
                                try:
                                    # BHAI LAST TRY BHAI PURA BALANCE BHAI
                                    qty_to_sell = get_sell_qty(client, symbol, coin_balance)
                                    client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    del entry_prices[symbol]
                                    save_json(FILE_ENTRY, entry_prices)
                                except Exception as e2:
                                    print(f"Sell Error 2 {symbol}: {e2}")
                except Exception as e:
                    print(f"Error {symbol}: {e}")
                    continue

                time.sleep(20)

            print(f"✅ Cycle Complete - USDT: ${get_balance(client, 'USDT'):.2f} Bhai")
            time.sleep(600)

        except Exception as e:
            print(f"Loop Error: {e}")
            if "-1003" in str(e) or "banned" in str(e):
                print("BHAI BAN HAI BHAI 10 MIN RUK JA BHAI!")
                time.sleep(600)
            else:
                time.sleep(10)

threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
