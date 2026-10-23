import os
import time
import logging
import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# ============================================================
# Binance DIP Bot — live trading. Use at your own risk.
# Required environment variables:
# BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN,
# TELEGRAM_CHAT_ID
# ============================================================

app = Flask(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(threadName)s: %(message)s",
)
log = logging.getLogger("dip-bot")

TRADE_SYMBOLS = [
    "SOLUSDT", "DOGEUSDT", "PEPEUSDT",
    "SHIBUSDT", "BONKUSDT", "FLOKIUSDT",
]
COINS_DIP = {
    "SOLUSDT": -1.0,
    "DOGEUSDT": -1.5,
    "PEPEUSDT": -3.0,
    "SHIBUSDT": -3.0,
    "BONKUSDT": -5.0,
    "FLOKIUSDT": -5.0,
}

TRADE_PERCENT = Decimal("10")       # safer default: 10% of free USDT
MIN_BUY_USDT = Decimal("10")
MIN_HOLDING_USDT = Decimal("5")
STOP_LOSS_PERCENT = Decimal("1.2")
TAKE_PROFIT_PERCENT = Decimal("2.0")
DAILY_PROFIT_TARGET = Decimal("2.50")
DAILY_LOSS_LIMIT = Decimal("1.00")

SCAN_INTERVAL_SECONDS = 30
ERROR_RETRY_SECONDS = 10
TELEGRAM_POLL_TIMEOUT = 25
STATE_FILE = os.getenv("BOT_STATE_FILE", "dip_bot_state.json")
DUBAI_TZ = ZoneInfo("Asia/Dubai")

state_lock = threading.RLock()
trading_thread = None
telegram_thread = None
stop_event = threading.Event()

# Runtime state; persisted daily realized PnL and known entry estimates.
daily_pnl = Decimal("0")
daily_date = datetime.now(DUBAI_TZ).date().isoformat()
entry_prices = {}
bot_started = False


def now_dubai():
    return datetime.now(DUBAI_TZ)


def load_state():
    """Load persisted PnL and entry estimates. Invalid state is ignored safely."""
    global daily_pnl, daily_date, entry_prices
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        saved_date = saved.get("daily_date")
        today = now_dubai().date().isoformat()
        if saved_date == today:
            daily_pnl = Decimal(str(saved.get("daily_pnl", "0")))
        else:
            daily_pnl = Decimal("0")
        daily_date = today
        entry_prices = {
            str(k): Decimal(str(v))
            for k, v in saved.get("entry_prices", {}).items()
            if k in TRADE_SYMBOLS and Decimal(str(v)) > 0
        }
    except FileNotFoundError:
        daily_pnl = Decimal("0")
        daily_date = now_dubai().date().isoformat()
        entry_prices = {}
    except Exception:
        log.exception("Could not read state file; starting with safe defaults")
        daily_pnl = Decimal("0")
        daily_date = now_dubai().date().isoformat()
        entry_prices = {}


def save_state():
    with state_lock:
        payload = {
            "daily_date": daily_date,
            "daily_pnl": str(daily_pnl),
            "entry_prices": {k: str(v) for k, v in entry_prices.items()},
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, STATE_FILE)


def roll_daily_pnl_if_needed():
    global daily_pnl, daily_date
    today = now_dubai().date().isoformat()
    with state_lock:
        if today != daily_date:
            daily_date = today
            daily_pnl = Decimal("0")
            save_state()
            log.info("Daily PnL reset for UAE date %s", today)


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram not configured: missing token or chat ID")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            log.error("Telegram API returned not-ok: %s", result)
            return False
        return True
    except Exception:
        log.exception("Telegram send failed")
        return False


def get_client():
    key = os.getenv("BINANCE_API_KEY")
    secret = os.getenv("BINANCE_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET")
    # Keep this key limited to Spot trading only; do not enable withdrawals.
    return Client(key, secret, requests_params={"timeout": 15})


def get_balance(client, asset):
    try:
        data = client.get_asset_balance(asset=asset)
        return Decimal(str(data["free"])) if data else Decimal("0")
    except Exception:
        log.exception("Could not read balance for %s", asset)
        raise


def get_price(client, symbol):
    return Decimal(str(client.get_symbol_ticker(symbol=symbol)["price"]))


def get_symbol_rules(client, symbol):
    info = client.get_symbol_info(symbol)
    if not info:
        raise RuntimeError(f"No exchange info for {symbol}")
    filters = {f["filterType"]: f for f in info["filters"]}
    lot = filters["LOT_SIZE"]
    step = Decimal(lot["stepSize"])
    min_qty = Decimal(lot["minQty"])
    min_notional = Decimal("0")
    if "MIN_NOTIONAL" in filters:
        min_notional = Decimal(filters["MIN_NOTIONAL"].get("minNotional", "0"))
    elif "NOTIONAL" in filters:
        min_notional = Decimal(filters["NOTIONAL"].get("minNotional", "0"))
    return step, min_qty, min_notional


def floor_to_step(quantity, step):
    if step <= 0:
        return Decimal("0")
    return (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step


def format_quantity(quantity, step):
    # Format with exactly the decimal precision needed by the step size.
    decimals = max(0, -step.normalize().as_tuple().exponent)
    return f"{quantity:.{decimals}f}"


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough candles for EMA")
    k = Decimal("2") / Decimal(period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * k + result * (Decimal("1") - k)
    return result


def get_signal_data(client, symbol):
    klines = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_15MINUTE,
        limit=50,
    )
    if len(klines) < 25:
        raise RuntimeError(f"Not enough candles for {symbol}")
    # Use only completed candles for indicators, excluding the currently forming candle.
    closes = [Decimal(str(k[4])) for k in klines[:-1]]
    price = get_price(client, symbol)
    ema9 = ema(closes[-30:], 9)
    ema21 = ema(closes[-30:], 21)
    price_1h_ago = closes[-4]
    dip_percent = (price - price_1h_ago) / price_1h_ago * Decimal("100")
    return price, ema9, ema21, dip_percent


def is_daily_limit_reached():
    with state_lock:
        return (
            daily_pnl >= DAILY_PROFIT_TARGET
            or daily_pnl <= -DAILY_LOSS_LIMIT
        )


def current_status(client=None):
    roll_daily_pnl_if_needed()
    with state_lock:
        pnl = daily_pnl
        entries = dict(entry_prices)
        date_text = daily_date
    usdt = "unavailable"
    if client is not None:
        try:
            usdt = str(get_balance(client, "USDT"))
        except Exception:
            pass
    return (
        f"DIP Bot status\n"
        f"UAE date: {date_text}\n"
        f"Mode: automatic live Spot orders\n"
        f"Daily realized PnL tracker: ${pnl:.4f}\n"
        f"Profit pause target: ${DAILY_PROFIT_TARGET}\n"
        f"Loss pause limit: -${DAILY_LOSS_LIMIT}\n"
        f"Free USDT: {usdt}\n"
        f"Tracked entries: {len(entries)}\n"
        f"Trading thread alive: {bool(trading_thread and trading_thread.is_alive())}"
    )


def market_buy(client, symbol, price, usdt_amount):
    step, min_qty, min_notional = get_symbol_rules(client, symbol)
    qty = floor_to_step(usdt_amount / price, step)
    if qty < min_qty or qty <= 0:
        raise ValueError(f"{symbol}: quantity below exchange minimum")
    notional = qty * price
    if notional < max(min_notional, MIN_BUY_USDT):
        raise ValueError(f"{symbol}: order value {notional} below minimum")
    order = client.create_order(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        quantity=format_quantity(qty, step),
        newOrderRespType="FULL",
    )
    fills = order.get("fills", [])
    executed_qty = Decimal(str(order.get("executedQty", "0")))
    quote_qty = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    if executed_qty <= 0:
        raise RuntimeError(f"{symbol}: buy returned zero executed quantity")
    avg_price = quote_qty / executed_qty if quote_qty > 0 else price
    return order, executed_qty, avg_price


def market_sell(client, symbol, current_price, coin_balance):
    step, min_qty, min_notional = get_symbol_rules(client, symbol)
    qty = floor_to_step(coin_balance, step)
    if qty < min_qty or qty <= 0:
        raise ValueError(f"{symbol}: sell quantity below exchange minimum")
    if qty * current_price < min_notional:
        raise ValueError(f"{symbol}: sell value below exchange minimum")
    order = client.create_order(
        symbol=symbol,
        side="SELL",
        type="MARKET",
        quantity=format_quantity(qty, step),
        newOrderRespType="FULL",
    )
    executed_qty = Decimal(str(order.get("executedQty", "0")))
    quote_qty = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    if executed_qty <= 0:
        raise RuntimeError(f"{symbol}: sell returned zero executed quantity")
    avg_price = quote_qty / executed_qty if quote_qty > 0 else current_price
    return order, executed_qty, avg_price


def trading_bot():
    global daily_pnl
    try:
        client = get_client()
        # Fail early if credentials/API are not usable.
        client.get_account()
        send_telegram(
            "DIP Bot started.\n"
            f"Free USDT: ${get_balance(client, 'USDT'):.4f}\n"
            f"Daily target: ${DAILY_PROFIT_TARGET}; daily loss pause: -${DAILY_LOSS_LIMIT}\n"
            "Live Spot orders are enabled."
        )
    except Exception as e:
        log.exception("Bot startup failed")
        send_telegram(f"DIP Bot startup failed: {type(e).__name__}: {e}")
        return

    # Recover existing holdings cautiously. Last buy is only an estimate,
    # not a true average cost; the message makes this limitation explicit.
    for symbol in TRADE_SYMBOLS:
        try:
            base = symbol.removesuffix("USDT")
            price = get_price(client, symbol)
            balance = get_balance(client, base)
            if balance * price > MIN_HOLDING_USDT and symbol not in entry_prices:
                trades = client.get_my_trades(symbol=symbol, limit=50)
                buys = [t for t in trades if t.get("isBuyer")]
                if buys:
                    entry_prices[symbol] = Decimal(str(buys[-1]["price"]))
                    log.warning(
                        "%s recovered entry from last buy (estimate, not average cost)",
                        symbol,
                    )
                else:
                    # Do not invent a cost basis for an unknown holding.
                    log.warning("%s holding exists but no buy cost basis found", symbol)
        except Exception:
            log.exception("Holding recovery failed for %s", symbol)
    save_state()

    while not stop_event.is_set():
        try:
            roll_daily_pnl_if_needed()
            if is_daily_limit_reached():
                send_telegram(
                    f"Trading paused for today.\nDaily realized PnL tracker: ${daily_pnl:.4f}\n"
                    "Restart will not bypass today's saved limit."
                )
                # Check periodically, but don't flood Telegram.
                stop_event.wait(60)
                continue

            for symbol in TRADE_SYMBOLS:
                if stop_event.is_set():
                    break
                try:
                    price, ema9, ema21, dip_percent = get_signal_data(client, symbol)
                    base = symbol.removesuffix("USDT")
                    usdt_balance = get_balance(client, "USDT")
                    coin_balance = get_balance(client, base)
                    holding_value = coin_balance * price
                    dip_needed = Decimal(str(COINS_DIP.get(symbol, -1.0)))

                    log.info(
                        "%s price=%s dip=%.3f%% need=%s%% EMA9=%s EMA21=%s "
                        "USDT=%s holding=%s",
                        symbol, price, dip_percent, dip_needed, ema9, ema21,
                        usdt_balance, holding_value,
                    )

                    # One position per symbol. Buy only when dip and EMA conditions match.
                    if (
                        ema9 < ema21
                        and dip_percent <= dip_needed
                        and usdt_balance > MIN_BUY_USDT
                        and holding_value < MIN_HOLDING_USDT
                    ):
                        # Recheck daily limit before placing an order.
                        if is_daily_limit_reached():
                            break
                        buy_amount = usdt_balance * TRADE_PERCENT / Decimal("100")
                        if buy_amount >= MIN_BUY_USDT:
                            order, qty, avg_price = market_buy(
                                client, symbol, price, buy_amount
                            )
                            with state_lock:
                                entry_prices[symbol] = avg_price
                                save_state()
                            send_telegram(
                                f"🟢 LIVE DIP BUY\nCoin: {symbol}\n"
                                f"Avg fill: {avg_price}\nQty: {qty}\n"
                                f"Dip: {dip_percent:.3f}%\n"
                                f"Order ID: {order.get('orderId')}"
                            )

                    # Refresh balances after a possible buy before sell checks.
                    coin_balance = get_balance(client, base)
                    holding_value = coin_balance * price
                    with state_lock:
                        entry = entry_prices.get(symbol)

                    if entry and holding_value > MIN_HOLDING_USDT:
                        pnl_percent = (price - entry) / entry * Decimal("100")
                        should_sell = (
                            pnl_percent >= TAKE_PROFIT_PERCENT
                            or pnl_percent <= -STOP_LOSS_PERCENT
                            or ema9 > ema21
                        )
                        if should_sell:
                            order, sold_qty, avg_sell = market_sell(
                                client, symbol, price, coin_balance
                            )
                            # Approximate realized PnL on the sold quantity.
                            # Fees and partial fills may make exchange PnL differ.
                            realized = (avg_sell - entry) * sold_qty
                            with state_lock:
                                daily_pnl += realized
                                remaining = get_balance(client, base)
                                if remaining * price <= MIN_HOLDING_USDT:
                                    entry_prices.pop(symbol, None)
                                save_state()
                            label = "PROFIT" if realized >= 0 else "LOSS"
                            send_telegram(
                                f"{'🟢' if realized >= 0 else '🔴'} LIVE {label} SELL\n"
                                f"Coin: {symbol}\nAvg sell: {avg_sell}\nQty: {sold_qty}\n"
                                f"Approx PnL (fees excluded): ${realized:.4f}\n"
                                f"Daily realized PnL tracker: ${daily_pnl:.4f}\n"
                                f"Order ID: {order.get('orderId')}"
                            )

                except BinanceAPIException as e:
                    log.error("Binance API error for %s: code=%s msg=%s",
                              symbol, e.code, e.message)
                    send_telegram(f"Binance API error for {symbol}: {e.code} {e.message}")
                except (BinanceRequestException, requests.RequestException) as e:
                    log.warning("Network/API request issue for %s: %s", symbol, e)
                except Exception:
                    log.exception("Symbol scan failed: %s", symbol)

                stop_event.wait(SCAN_INTERVAL_SECONDS)

        except Exception:
            log.exception("Trading loop error")
            stop_event.wait(ERROR_RETRY_SECONDS)


def telegram_commands():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    allowed_chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not allowed_chat:
        log.warning("Telegram polling disabled: missing token or chat ID")
        return

    offset = None
    session = requests.Session()
    while not stop_event.is_set():
        try:
            response = session.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": TELEGRAM_POLL_TIMEOUT, "offset": offset},
                timeout=TELEGRAM_POLL_TIMEOUT + 10,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram getUpdates failed: {payload}")

            for update in payload.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                command = (msg.get("text") or "").strip().split()[0].lower() if msg.get("text") else ""

                # Only accept commands from the configured chat ID.
                if chat_id != str(allowed_chat):
                    continue

                if command in ("/start", "/help"):
                    send_telegram(
                        "DIP Bot commands:\n"
                        "/status - bot and PnL status\n"
                        "/help - show this help\n\n"
                        "This bot places live Spot orders automatically."
                    )
                elif command == "/status":
                    try:
                        client = get_client()
                        send_telegram(current_status(client))
                    except Exception:
                        log.exception("Could not build status with Binance balance")
                        send_telegram(current_status(None))
                elif command == "/pause":
                    stop_event.set()
                    send_telegram("Pause requested: bot threads are stopping. Restart the service to resume.")
                else:
                    send_telegram("Unknown command. Use /status or /help.")
        except Exception:
            log.exception("Telegram polling error")
            stop_event.wait(5)


@app.route("/")
def home():
    return "Mohamed DIP Bot service is running. Check /health for process health.", 200


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "trading_thread_alive": bool(trading_thread and trading_thread.is_alive()),
        "telegram_thread_alive": bool(telegram_thread and telegram_thread.is_alive()),
        "daily_date_uae": daily_date,
    }), 200


def start_background_threads():
    global trading_thread, telegram_thread, bot_started
    if bot_started:
        return
    bot
