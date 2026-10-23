import os, time, requests, threading, json
from flask import Flask, request
from binance.client import Client
from binance.exceptions import BinanceAPIException

app = Flask(__name__)

# ===== SAME CONFIG BHAI =====
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT"]
COINS_DIP = {"SOLUSDT": -1.0,"DOGEUSDT": -1.5,"PEPEUSDT": -3.0,"SHIBUSDT": -3.0,"BONKUSDT": -5.0,"FLOKIUSDT": -5.0}
TRADE_PERCENT = 50
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 2.0
DAILY_PROFIT_TARGET = 2.50
DAILY_LOSS_LIMIT = 1
daily_pnl = 0

price_cache = {}
precision_cache = {}
ENTRY_FILE = "/tmp/entry_prices.json"
def save_entries(d):
    try:
        with open(ENTRY_FILE, "w") as f: json.dump(d, f)
    except: pass
def load_entries():
    try:
        if os.path.exists(ENTRY_FILE):
            with open(ENTRY_FILE, "r") as f: return json.load(f)
    except: pass
    return {}

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

@app.route('/')
def home(): return f"✅ Mohamed DIP Bot LIVE - LOW WEIGHT - {TAKE_PROFIT_PERCENT}% Profit"
@app.route('/health')
def health(): return "OK", 200

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        if not data or 'message' not in data: return "OK",200
        msg = data['message']
        chat_id = msg['chat']['id']
        text = msg.get('text','').lower()
        allowed = os.environ.get("TELEGRAM_CHAT_ID")
        if allowed and str(chat_id) != str(allowed): return "OK",200
        
        api_key = os.environ.get("BINANCE_API_KEY")
        api_secret = os.environ.get("BINANCE_API_SECRET")
        client = Client(api_key, api_secret)
        token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
        def reply(t):
            try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": t}, timeout=10)
            except: pass
        
        if '/status' in text or '/start' in text:
            entries = load_entries()
            all_p = get_all_prices_once(client)
            txt = f"📊 STATUS Bhai - 6 MIN BOT\nDaily: ${daily_pnl:.2f} / ${DAILY_PROFIT_TARGET}\n\n"
            for sym in TRADE_SYMBOLS:
                base = sym.replace("USDT","")
                bal = get_balance(client, base)
                pr = all_p.get(sym,0)
                if bal*pr > 1:
                    ent = entries.get(sym, pr)
                    pnl = ((pr-ent)/ent*100) if ent else 0
                    txt+=f"{sym}: {bal:.2f} PNL {pnl:.2f}% Entry {ent}\n"
            txt+=f"\nUSDT: ${get_balance(client,'USDT'):.2f} Bhai"
            reply(txt)
        elif '/balance' in text:
            all_p = get_all_prices_once(client)
            total=0
            usdt=get_balance(client,"USDT")
            total+=usdt
            txt=f"💰 BALANCE Bhai\nUSDT: ${usdt:.2f}\n"
            for sym in TRADE_SYMBOLS:
                base=sym.replace("USDT","")
                bal=get_balance(client, base)
                pr=all_p.get(sym,0)
                val=bal*pr
                if val>0.5:
                    total+=val
                    txt+=f"{base}: ${val:.2f}\n"
            txt+=f"\nTOTAL: ${total:.2f} Bhai"
            reply(txt)
    except Exception as e: print(f"Webhook Error {e}")
    return "OK",200

@app.route('/setwebhook')
def set_webhook():
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    if not token: return "No Token Bhai"
    # BHAI FIX BHAI - HTTPS FORCE BHAI
    url = "https://mohamed-proxe.onrender.com/telegram"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={url}", timeout=10)
        return f"Webhook Set Bhai to {url} - {r.text}"
    except Exception as e: return f"Error Bhai {e}"

def get_balance(client, asset="USDT"):
    try: return float(client.get_asset_balance(asset=asset)['free'])
    except: return 0.0

def get_all_prices_once(client):
    try:
        tickers = client.get_all_tickers()
        return {t['symbol']: float(t['price']) for t in tickers}
    except: return {}

def get_precision_cached(client, symbol):
    if symbol in precision_cache: return precision_cache[symbol]
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step = f['stepSize']
                prec = len(step.split('.')[1].rstrip('0')) if '.' in step else 0
                precision_cache[symbol] = prec
                return prec
    except: pass
    precision_cache[symbol] = 6
    return 6

def get_ema(closes, period):
    try:
        k = 2 / (period + 1)
        ema = closes[0]
        for price in closes[1:]: ema = price * k + ema * (1 - k)
        return ema
    except: return sum(closes[-period:]) / period

def trading_bot():
    global daily_pnl
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret: return
    client = Client(api_key, api_secret)
    
    usdt_bal = get_balance(client, "USDT")
    send_telegram(f"✅ DIP BOT LIVE Bhai! 🚀 LOW WEIGHT MODE Bhai!\n💰 USDT: ${usdt_bal:.2f}\nTarget: ${DAILY_PROFIT_TARGET}")

    entry_prices = load_entries()
    for symbol in TRADE_SYMBOLS:
        try:
            base = symbol.replace("USDT", "")
            bal = get_balance(client, base)
            if bal > 0:
                all_p = get_all_prices_once(client)
                cp = all_p.get(symbol, 0)
                if cp and bal * cp > 1 and symbol not in entry_prices:
                    entry_prices[symbol] = cp
                    print(f"BHAI HOLDING BHAI {symbol} Entry: {cp}")
        except: pass
        time.sleep(1)
    save_entries(entry_prices)

    while True:
        try:
            if daily_pnl >= DAILY_PROFIT_TARGET or daily_pnl <= -DAILY_LOSS_LIMIT:
                print("DAILY LIMIT REACHED BHAI - SLEEP 1 HOUR BHAI")
                time.sleep(3600); continue

            all_prices = get_all_prices_once(client)
            if not all_prices:
                time.sleep(60); continue

            for symbol in TRADE_SYMBOLS:
                try:
                    base_coin = symbol.replace("USDT", "")
                    current_price = all_prices.get(symbol, 0)
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

                    print(f"Check {symbol} P:{current_price} Dip:{dip_percent:.2f}% Need:{dip_needed}%")

                    if coin_balance * current_price > 1 and symbol not in entry_prices:
                        entry_prices[symbol] = current_price
                        save_entries(entry_prices)

                    if ema9 < ema21 and dip_percent <= dip_needed and usdt_balance > 10:
                        if coin_balance * current_price < 5:
                            buy_usdt = usdt_balance * (TRADE_PERCENT / 100)
                            if buy_usdt > 10:
                                prec = get_precision_cached(client, symbol)
                                qty = round(buy_usdt / current_price, prec)
                                if qty > 0:
                                    client.create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                                    entry_prices[symbol] = current_price
                                    save_entries(entry_prices)
                                    send_telegram(f"🟢 DIP BUY Bhai!\n{symbol} @ {current_price}\nDip: {dip_percent:.2f}%")

                    if symbol not in entry_prices and coin_balance * current_price > 1:
                        entry_prices[symbol] = current_price
                        save_entries(entry_prices)
                    
                    if symbol in entry_prices and coin_balance * current_price > 5:
                        entry = entry_prices[symbol]
                        pnl_percent = ((current_price - entry) / entry) * 100
                        if pnl_percent >= TAKE_PROFIT_PERCENT or pnl_percent <= -STOP_LOSS_PERCENT or ema9 > ema21:
                            prec = get_precision_cached(client, symbol)
                            qty_to_sell = round(coin_balance, prec)
                            if qty_to_sell > 0:
                                client.create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty_to_sell)
                                profit = (current_price - entry) * coin_balance
                                daily_pnl += profit
                                send_telegram(f"{'🟢 PROFIT' if pnl_percent>0 else '🔴 LOSS'} SELL Bhai!\n{symbol} {pnl_percent:.2f}% (${profit:.2f})\nDaily: ${daily_pnl:.2f}")
                                del entry_prices[symbol]
                                save_entries(entry_prices)

                    time.sleep(3)

                except Exception as e:
                    print(f"Error {symbol}: {e}")
                    if "-1003" in str(e) or "banned" in str(e).lower():
                        print("BHAI BAN HUA BHAI 1 HOUR SLEEP BHAI")
                        time.sleep(1200)
                        break
                    continue

            print(f"✅ Cycle Done - USDT: ${get_balance(client, 'USDT'):.2f} Bhai")
            time.sleep(360)

        except Exception as e:
            print(f"Loop Error: {e}")
            if "-1003" in str(e): time.sleep(1200)
            else: time.sleep(60)

threading.Thread(target=trading_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
