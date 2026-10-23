import os
import time
import requests
import threading
from flask import Flask
from binance.client import Client
from binance.exceptions import BinanceAPIException

app = Flask(__name__)

# ===== CONFIG - DIP BUY BHAI =====
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT"]
COINS_DIP = {"SOLUSDT": -1.0,"DOGEUSDT": -1.5,"PEPEUSDT": -3.0,"SHIBUSDT": -3.0,"BONKUSDT": -5.0,"FLOKIUSDT": -5.0}
TRADE_PERCENT = 50
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 2.0
DAILY_PROFIT_TARGET = 2.50
DAILY_LOSS_LIMIT = 1
daily_pnl = 0

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

@app.route('/')
def home(): return f"✅ Mohamed DIP Bot LIVE - NO CONFLICT MODE - {TAKE_PROFIT_PERCENT}% Profit"
@app.route('/health')
def health(): return "OK", 200

def get_balance(client, asset="USDT"):
    try: return float(client.get_asset_balance(asset=asset)['free'])
    except: return 0.0
def get_current_price(client, symbol):
    try: return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except: return 0.0
def get_qty_precision(client, symbol):
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = f['stepSize']
                if '.' in step: return len(step.split('.')[1].rstrip('0'))
                return 0
    except: pass
    return 0
def get_ema_real(closes, period):
    try:
        k = 2 / (period + 1)
        ema = closes[0]
        for price in closes[1:]: ema = price * k + ema * (1 - k)
        return ema
    except: return sum(closes[-period:]) / period

def trading_bot():
    global daily_pnl
    print("🚀 DIP Bot Starting... NO TELEBOT POLLING - NO 409 Bhai!")
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret: return
    client = Client(api_key, api_secret)
    usdt_bal = get_balance(client, "USDT")
    send_telegram(f"✅ DIP BOT LIVE Bhai! 🚀 NO CONFLICT MODE Bhai!\n💰 USDT: ${usdt_bal:.2f}\nTarget: ${DAILY_PROFIT_TARGET} Bhai!")
    entry_prices = {}
    print("BHAI PURANA HOLDING CHECK KAR RAHA HU BHAI...")
    for symbol in TRADE_SYMBOLS:
        try:
            base_coin = symbol.replace("USDT", "")
            c_price = get_current_price(client, symbol)
            if c_price == 0: continue
            c_bal = get_balance(client, base_coin)
            if c_bal * c_price > 1:
                try:
                    trades = client.get_my_trades(symbol=symbol, limit=10)
                    last_buys = [t for t in trades if t['isBuyer']]
                    if last_buys: entry_prices[symbol] = float(last_buys[-1]['price'])
                    else: entry_prices[symbol] = c_price
                except: entry_prices[symbol] = c_price
                print(f"BHAI YAAD AAYA BHAI {symbol} Entry: {entry_prices[symbol]} Bhai!")
        except: pass
    while True:
        try:
            if daily_pnl >= DAILY_PROFIT_TARGET or daily_pnl <= -DAILY_LOSS_LIMIT:
                time.sleep(3600); continue
            for symbol in TRADE_SYMBOLS:
                try:
                    time.sleep(2)
                    base_coin = symbol.replace("USDT", "")
                    current_price = get_current_price(client, symbol)
                    if current_price == 0: continue
                    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=50)
                    closes = [float(k[4]) for k in klines]
                    ema9 = get_ema_real(closes, 9)
                    ema21 = get_ema_real(closes, 21)
                    price_1h_ago = closes[-4]
                    dip_percent = ((current_price - price_1h_ago) / price_1h_ago) * 100
                    dip_needed = COINS_DIP.get(symbol, -1.0)
                    usdt_balance = get_balance(client, "USDT")
                    coin_balance = get_balance(client, base_coin)
                    print(f"Check {symbol} Price:{current_price} Dip:{dip_percent:.2f}% Need:{dip_needed}% EMA9:{ema9:.2f} EMA21:{ema21:.2f}")
                    if ema9 < ema21 and dip_percent <= dip_needed and usdt_balance > 10:
                        if coin_balance * current_price < 5:
                            buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                            if buy_usdt > 10:
                                precision = get_qty_precision(client, symbol)
                                qty = round(buy_usdt / current_price, precision)
                                if qty > 0:
                                    try:
                                        client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                        entry_prices[symbol] = current_price
                                        send_telegram(f"🟢 DIP BUY Bhai!\nCoin: {symbol}\nPrice: {current_price}\nDip: {dip_percent:.2f}%")
                                    except BinanceAPIException as e: print(f"Buy Error {symbol}: {e}")
                    if symbol not in entry_prices and coin_balance * current_price > 1: entry_prices[symbol] = current_price
                    if symbol in entry_prices and coin_balance * current_price > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = ((current_price - entry) / entry) * 100
                        if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 > ema21:
                            try:
                                precision = get_qty_precision(client, symbol)
                                qty_to_sell = round(coin_balance, precision)
                                if qty_to_sell > 0:
                                    client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    profit_dollar = (current_price - entry) * coin_balance
                                    daily_pnl += profit_dollar
                                    send_telegram(f"{'🟢 PROFIT SELL' if pnl_percent > 0 else '🔴 LOSS SELL'} Bhai!\nCoin: {symbol}\nPNL: {pnl_percent:.2f}% (${profit_dollar:.2f})\nDaily: ${daily_pnl:.2f}")
                                    del entry_prices[symbol]
                            except BinanceAPIException as e:
                                try:
                                    qty_to_sell = round(coin_balance, precision)
                                    client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                    del entry_prices[symbol]
                                except: pass
                except Exception as e: print(f"Error {symbol}: {e}"); continue
                time.sleep(20)
            print(f"✅ Cycle Complete - USDT: ${get_balance(client, 'USDT'):.2f} Bhai")
            time.sleep(600)
        except Exception as e:
            print(f"Loop Error: {e}")
            if "-1003" in str(e) or "banned" in str(e): time.sleep(600)
            else: time.sleep(10)

threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
