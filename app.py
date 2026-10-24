import os
import time
import json
import threading
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, request
from binance.client import Client
from binance.exceptions import BinanceAPIException
import telebot

app = Flask(__name__)

# ============== CONFIG ==============
TRADE_SYMBOLS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT"]

TRADE_PERCENT = 10.0
STOP_LOSS_PERCENT = 1.2
TAKE_PROFIT_PERCENT = 2.0
DAILY_PROFIT_TARGET = 2.50
DAILY_LOSS_LIMIT = 1.00

CHECK_INTERVAL = 300
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

DATA_FILE = os.getenv("TRADE_DATA_FILE", "/var/data/trade_data.json")
TIMEZONE = ZoneInfo("Asia/Dubai")

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None
state_lock = threading.RLock()
trading_lock = threading.Lock()
entry_prices = {}
daily_pnl = 0.0
daily_date = datetime.now(TIMEZONE).date().isoformat()
reported_untracked = set()

# ============== PERSISTENT STATE ==============
def load_state():
    global entry_prices, daily_pnl, daily_date
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        entry_prices = data.get("entry_prices", {})
        daily_pnl = float(data.get("daily_pnl", 0.0))
        daily_date = data.get(
            "daily_date",
            datetime.now(TIMEZONE).date().isoformat()
        )
        print("Saved trade state loaded.")
    except FileNotFoundError:
        print("No saved state. Existing Binance holdings need verification.")
    except Exception as e:
        print(f"STATE LOAD ERROR: {e}")
        raise RuntimeError(
            "Cannot safely load trade state. Trading must not start."
        )

def save_state():
    folder = os.path.dirname(DATA_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w") as f:
        json.dump({
            "entry_prices": entry_prices,
            "daily_pnl": daily_pnl,
            "daily_date": daily_date
        }, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, DATA_FILE)

load_state()

def reset_daily_pnl_if_needed():
    global daily_pnl, daily_date
    today = datetime.now(TIMEZONE).date().isoformat()
    with state_lock:
        if today != daily_date:
            daily_date = today
            daily_pnl = 0.0
            save_state()
            send_telegram("New Dubai trading day. Daily PnL reset.")

# ============== TELEGRAM ==============
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        ).raise_for_status()
    except Exception as e:
        print(f"Telegram send error: {e}")

def authorized(message):
    return CHAT_ID and str(message.chat.id) == str(CHAT_ID)

if bot:
    @bot.message_handler(commands=["start", "status", "balance"])
    def basic_commands(message):
        if not authorized(message):
            return
        command = message.text.split()[0].split("@")[0].lower()
        if command == "/start":
            bot.reply_to(
                message,
                "DIP Bot connected.\n"
                "Commands: /status /balance\n"
                f"Live trading: {LIVE_TRADING}"
            )
        elif command == "/status":
            with state_lock:
                positions = dict(entry_prices)
                pnl = daily_pnl
            lines = [
                "DIP BOT STATUS",
                f"Mode: {'LIVE' if LIVE_TRADING else 'PAUSED'}",
                f"Daily PnL estimate: ${pnl:.4f}",
                f"Target: ${DAILY_PROFIT_TARGET:.2f}",
                f"Loss limit: ${DAILY_LOSS_LIMIT:.2f}",
                f"Check interval: {CHECK_INTERVAL}s",
                "Tracked entries:"
            ]
            if positions:
                for symbol, record in positions.items():
                    lines.append(
                        f"{symbol}: entry "
                        f"{record.get('price', 'unknown')}, "
                        f"qty {record.get('qty', 'unknown')}"
                    )
            else:
                lines.append("No saved entries.")
            bot.reply_to(message, "\n".join(lines))
        elif command == "/balance":
            try:
                client = get_client()
                usdt = get_balance(client, "USDT")
                bot.reply_to(
                    message,
                    f"Free USDT: {usdt:.4f}\n"
                    f"Approx AED: {usdt * 3.67:.2f}\n"
                    f"Daily PnL estimate: ${daily_pnl:.4f}"
                )
            except Exception as e:
                bot.reply_to(message, f"Balance error: {e}")

# ============== FLASK / WEBHOOK ==============
@app.route("/")
def home():
    return "DIP Bot service running", 200

@app.route("/health")
def health():
    return "OK", 200

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    if not bot:
        return "Telegram not configured", 503
    try:
        update = telebot.types.Update.de_json(
            request.get_data(as_text=True)
        )
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return "Webhook error", 500

@app.route("/setwebhook")
def set_webhook_route():
    if not bot:
        return "Bot token missing", 503

    # BHAI - Unauthorized check hata diya
    url = os.getenv(
        "WEBHOOK_URL",
        "https://mohamed-proxe.onrender.com/telegram"
    )
    try:
        bot.set_webhook(url=url)
        return f"Webhook configured to {url}", 200
    except Exception as e:
        return f"Webhook setup failed: {e}", 500

# ============== BINANCE HELPERS ==============
def get_client():
    key = os.getenv("BINANCE_API_KEY")
    secret = os.getenv("BINANCE_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Binance API credentials missing")
    client = Client(key, secret)
    client.get_server_time()
    return client

def get_balance(client, asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance["free"]) if balance else 0.0

def get_price(client, symbol):
    result = client.get_symbol_ticker(symbol=symbol)
    return float(result["price"])

def get_symbol_rules(client, symbol):
    info = client.get_symbol_info(symbol)
    if not info:
        raise RuntimeError(f"Symbol not found: {symbol}")
    filters = {f["filterType"]: f for f in info["filters"]}
    lot = filters["LOT_SIZE"]
    min_notional = (
        filters.get("NOTIONAL", {}).get("minNotional")
        or filters.get("MIN_NOTIONAL", {}).get("minNotional")
        or "0"
    )
    return {
        "step": Decimal(lot["stepSize"]),
        "min_qty": Decimal(lot["minQty"]),
        "max_qty": Decimal(lot["maxQty"]),
        "min_notional": Decimal(str(min_notional))
    }

def floor_quantity(quantity, step):
    quantity = Decimal(str(quantity))
    step = Decimal(str(step))
    if step <= 0:
        return Decimal("0")
    return (
        (quantity / step).to_integral_value(rounding=ROUND_DOWN)
        * step
    )

def format_quantity(quantity):
    return format(quantity, "f")

def get_ema(values, period):
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = value * multiplier + ema * (1 - multiplier)
    return ema

def get_signals(client, symbol):
    candles = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_15MINUTE,
        limit=50
    )
    closes = [float(c[4]) for c in candles[:-1]]
    if len(closes) < 22:
        raise RuntimeError("Not enough completed candles")
    ema9 = get_ema(closes, 9)
    ema21 = get_ema(closes, 21)
    reference_price = closes[-4]
    price = get_price(client, symbol)
    dip = ((price - reference_price) / reference_price) * 100
    return price, ema9, ema21, dip

# ============== TRADING ==============
def trading_bot():
    global daily_pnl
    try:
        client = get_client()
        send_telegram(
            "DIP Bot started.\n"
            f"Trading mode: {'LIVE' if LIVE_TRADING else 'PAUSED'}\n"
            f"Symbols: {', '.join(TRADE_SYMBOLS)}"
        )
    except Exception as e:
        print(f"Binance startup error: {e}")
        send_telegram(f"Bot startup failed: {e}")
        return

    while True:
        try:
            reset_daily_pnl_if_needed()
            with state_lock:
                pnl = daily_pnl
            if pnl >= DAILY_PROFIT_TARGET or pnl <= -DAILY_LOSS_LIMIT:
                print("Daily limit reached. Trading paused until Dubai date changes.")
                time.sleep(60)
                continue
            for symbol in TRADE_SYMBOLS:
                try:
                    with trading_lock:
                        inspect_symbol(client, symbol)
                except BinanceAPIException as e:
                    print(f"Binance error {symbol}: {e}")
                    if e.code == -1003:
                        time.sleep(120)
                except Exception as e:
                    print(f"Symbol error {symbol}: {e}")
                time.sleep(2)
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(15)

def inspect_symbol(client, symbol):
    global daily_pnl
    base_asset = symbol.replace("USDT", "")
    price, ema9, ema21, dip = get_signals(client, symbol)
    balance = get_balance(client, base_asset)
    value = balance * price
    with state_lock:
        record = entry_prices.get(symbol)
    print(
        f"{symbol} price={price} dip={dip:.2f}% "
        f"EMA9={ema9:.8f} EMA21={ema21:.8f} "
        f"balance={balance:.8f}"
    )
    if record is None and value > 5:
        if symbol not in reported_untracked:
            send_telegram(
                f"⚠️ UNTRACKED HOLDING: {symbol}\n"
                f"Balance value: approximately ${value:.2f}\n"
                "No automatic SELL: purchase entry is unknown.\n"
                "Verify Binance trade history before recording its entry."
            )
            reported_untracked.add(symbol)
        return
    if record is not None:
        entry = float(record["price"])
        saved_qty = float(record["qty"])
        pnl_percent = ((price - entry) / entry) * 100
        sell_balance = min(balance, saved_qty)
        should_sell = (
            pnl_percent >= TAKE_PROFIT_PERCENT
            or pnl_percent <= -STOP_LOSS_PERCENT
            or ema9 > ema21
        )
        if should_sell and sell_balance > 0:
            if not LIVE_TRADING:
                print(f"PAUSED: SELL signal {symbol} ({pnl_percent:.2f}%)")
                return
            rules = get_symbol_rules(client, symbol)
            qty = floor_quantity(sell_balance * 0.99, rules["step"])
            if qty < rules["min_qty"] or qty * Decimal(str(price)) < rules["min_notional"]:
                print(f"Sell quantity below exchange minimum: {symbol}")
                return
            order = client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=format_quantity(qty)
            )
            executed_qty = float(order.get("executedQty", 0))
            quote_qty = float(order.get("cummulativeQuoteQty", 0))
            if executed_qty <= 0:
                send_telegram(f"SELL order returned zero fill: {symbol}")
                return
            average_sell = quote_qty / executed_qty
            gross_pnl = (average_sell - entry) * executed_qty
            with state_lock:
                daily_pnl += gross_pnl
                remaining_qty = max(saved_qty - executed_qty, 0)
                if remaining_qty * price > 5:
                    entry_prices[symbol]["qty"] = remaining_qty
                else:
                    entry_prices.pop(symbol, None)
                save_state()
            send_telegram(
                f"SELL FILLED: {symbol}\n"
                f"Average sell: {average_sell:.8f}\n"
                f"Executed qty: {executed_qty:.8f}\n"
                f"Price change: {pnl_percent:.2f}%\n"
                f"Estimated gross PnL: ${gross_pnl:.4f}\n"
                f"Daily estimated gross PnL: ${daily_pnl:.4f}\n"
                "Fees may not be included."
            )
        return
    if ema9 < ema21 and dip <= -1.0:
        usdt = get_balance(client, "USDT")
        buy_amount = usdt * (TRADE_PERCENT / 100)
        if buy_amount <= 10:
            return
        if not LIVE_TRADING:
            print(f"PAUSED: BUY signal {symbol}")
            return
        rules = get_symbol_rules(client, symbol)
        qty = floor_quantity(
            Decimal(str(buy_amount / price)),
            rules["step"]
        )
        if qty < rules["min_qty"]:
            print(f"Buy quantity too small: {symbol}")
            return
        if qty * Decimal(str(price)) < rules["min_notional"]:
            print(f"Buy value below exchange minimum: {symbol}")
            return
        order = client.create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=format_quantity(qty)
        )
        executed_qty = float(order.get("executedQty", 0))
        quote_qty = float(order.get("cummulativeQuoteQty", 0))
        if executed_qty <= 0 or quote_qty <= 0:
            send_telegram(f"BUY returned no confirmed fill: {symbol}")
            return
        actual_entry = quote_qty / executed_qty
        with state_lock:
            entry_prices[symbol] = {
                "price": actual_entry,
                "qty": executed_qty
            }
            save_state()
        send_telegram(
            f"BUY FILLED: {symbol}\n"
            f"Average entry: {actual_entry:.8f}\n"
            f"Executed qty: {executed_qty:.8f}\n"
            f"Dip: {dip:.2f}%\n"
            "Entry saved."
        )

# ============== STARTUP ==============
if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        print("WARNING: Trade state file does not exist.")
    thread = threading.Thread(target=trading_bot, daemon=True)
    thread.start()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
