#!/usr/bin/env python3
"""
Momentum swing bot for the Alpaca connection test (PR #5).

Replaces the fixed +3%/-2% swing bot (alpaca_bot.py) with a moving-average
crossover: short-term SMA above long-term SMA means "uptrend", below means
"downtrend". Enters a symbol on an uptrend with no position, exits a held
position on a downtrend. Adds BTC/USD and ETH/USD (24/7 markets) alongside
the existing equities, since positions only move during exchange hours.

Two additions on top of the base crossover (2026-09-28, after the user
asked how to improve returns):

- Regime filter: a new entry only fires if price is also above the longer
  TREND_WINDOW-bar SMA. The 3h/10h crossover reacts fast but has no sense
  of the broader trend; this blocks entries taken against it. Only
  restricts new entries — exits on a down signal are never blocked, since
  missing an exit is worse than missing an entry.
- Trailing stop: once a held position's price has been at least
  MIN_PEAK_GAIN above its entry, sell early if price gives back more than
  TRAILING_STOP_PCT off that peak — instead of waiting for the lagging
  crossover to flip, which has repeatedly given back multi-percent
  unrealized gains before triggering (see notes.md).

Stateless like the original bot: momentum is recomputed from Alpaca's own
bar data every run, and open/closed state comes from Alpaca's own
positions endpoint. No local state file — the trailing stop's "peak since
entry" is derived each run from the entry order's fill time plus bar data
since then, not from a stored value.

Auth headers are injected by the cloud environment's network proxy for
requests to *.alpaca.markets, so this script never handles credentials.
"""
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

TRADE_BASE = "https://paper-api.alpaca.markets/v2"
DATA_STOCKS_BASE = "https://data.alpaca.markets/v2"
DATA_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3"

# symbol -> asset class. Chosen for 2-day hourly-bar volatility (measured
# 2026-09-23): BYD/BYDDY/MSFT dropped (~3% range, barely move); these six
# were the top movers available on Alpaca paper (DOGE 14.2%, LTC 7.8%,
# COIN 5.3%, BTC 4.3%, SOL 4.2%, ETH 4.2%). Re-measure periodically —
# volatility ranking shifts over time.
SYMBOLS = {
    "BTC/USD": "crypto",
    "ETH/USD": "crypto",
    "DOGE/USD": "crypto",
    "LTC/USD": "crypto",
    "SOL/USD": "crypto",
    "COIN": "equity",
}

SHORT_WINDOW = 3
LONG_WINDOW = 10
TREND_WINDOW = 50  # ~2 days of 1h bars; longer-term regime filter for entries only
TIMEFRAME = "1Hour"
NOTIONAL = "1000"  # dollars per new entry
SIGNAL_THRESHOLD = 0.0015  # 0.15% minimum SMA gap to count as a real signal (see daytrading_bot.py)
MIN_PEAK_GAIN = 0.005  # 0.5% — a position must have been up at least this much to arm the trailing stop
TRAILING_STOP_PCT = 0.01  # sell if price gives back 1% off its peak since entry, once armed


def _request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", "alpaca-momentum-bot/1.0")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def get_position(symbol):
    # The positions endpoint uses the compact crypto symbol (BTCUSD), not
    # the slash form (BTC/USD) that orders/assets/bars use. Using the
    # slash form here 404s even when a position exists, which looks
    # identical to "never bought" and causes repeat buys every run.
    path_symbol = symbol.replace("/", "")
    status, body = _request(f"{TRADE_BASE}/positions/{path_symbol}")
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"positions/{symbol}: {status} {body}")
    return body


def has_open_order(symbol):
    encoded = urllib.parse.quote(symbol, safe="")
    status, body = _request(f"{TRADE_BASE}/orders?status=open&symbols={encoded}&limit=10")
    if status != 200:
        raise RuntimeError(f"open orders/{symbol}: {status} {body}")
    return len(body) > 0


def get_bars(symbol, asset_class, start=None, limit=100):
    # Equities only accumulate bars during ~6.5 trading hours/day, so they
    # need a much longer calendar lookback than crypto (24/7) to reach the
    # same bar count — TREND_WINDOW=50 needs well over a week of trading
    # days, which needs well over two calendar weeks including weekends.
    if start is None:
        lookback_days = 8 if asset_class == "crypto" else 25
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if asset_class == "crypto":
        encoded = urllib.parse.quote(symbol, safe="")
        url = f"{DATA_CRYPTO_BASE}/crypto/us/bars?symbols={encoded}&timeframe={TIMEFRAME}&limit={limit}&start={start}"
        status, body = _request(url)
        if status != 200:
            raise RuntimeError(f"bars/{symbol}: {status} {body}")
        return body.get("bars", {}).get(symbol, [])
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"{DATA_STOCKS_BASE}/stocks/{encoded}/bars?timeframe={TIMEFRAME}&limit={limit}&feed=iex&start={start}"
    status, body = _request(url)
    if status != 200:
        raise RuntimeError(f"bars/{symbol}: {status} {body}")
    return body.get("bars") or []


def get_regime(symbol, asset_class, closes):
    # True = price above the long-term trend SMA (uptrend regime), False =
    # below, None = not enough bar history to judge. Only used to gate new
    # entries — never blocks an exit.
    if len(closes) < TREND_WINDOW:
        return None
    return closes[-1] > sma(closes, TREND_WINDOW)


def get_last_entry_time(symbol):
    # Most recent filled buy for this symbol. Since the bot always fully
    # enters/exits (no partial scaling), this is the entry time of whatever
    # position is currently held.
    encoded = urllib.parse.quote(symbol, safe="")
    status, body = _request(f"{TRADE_BASE}/orders?status=closed&symbols={encoded}&side=buy&limit=5&direction=desc")
    if status != 200:
        raise RuntimeError(f"buy orders/{symbol}: {status} {body}")
    for order in body:
        if order.get("status") == "filled":
            return order.get("filled_at")
    return None


def get_peak_since(symbol, asset_class, start_iso):
    bars = get_bars(symbol, asset_class, start=start_iso, limit=200)
    if not bars:
        return None
    return max(b["h"] for b in bars)


def check_trailing_stop(symbol, asset_class, pos):
    entry_time = get_last_entry_time(symbol)
    if entry_time is None:
        return None
    peak = get_peak_since(symbol, asset_class, entry_time)
    entry_price = float(pos["avg_entry_price"])
    if peak is None:
        peak = entry_price
    peak = max(peak, entry_price)
    peak_gain = (peak - entry_price) / entry_price
    if peak_gain < MIN_PEAK_GAIN:
        return None  # never got far enough ahead to arm the trailing stop

    current_price = float(pos["current_price"])
    drawdown = (peak - current_price) / peak
    if drawdown < TRAILING_STOP_PCT:
        return None

    qty = pos["qty"]
    place_order(symbol, "sell", qty=qty)
    plpc = float(pos.get("unrealized_plpc", 0))
    return (f"SOLD {qty} {symbol} (trailing stop: peaked +{peak_gain:.2%} since entry, "
            f"pulled back {drawdown:.2%} from ${peak:.4f}, unrealized {plpc:+.2%})")


def place_order(symbol, side, qty=None, notional=None):
    data = {"symbol": symbol, "side": side, "type": "market",
             "time_in_force": "gtc" if SYMBOLS[symbol] == "crypto" else "day"}
    if qty is not None:
        data["qty"] = str(qty)
    else:
        data["notional"] = notional
    status, body = _request(f"{TRADE_BASE}/orders", method="POST", data=data)
    if status not in (200, 201):
        raise RuntimeError(f"order {side} {symbol}: {status} {body}")
    return body


def sma(closes, n):
    return sum(closes[-n:]) / n


def momentum_signal(symbol, asset_class):
    # A plain crossover flips on any gap, including near-zero noise, which
    # whipsawed the day-trading variant of this bot into same-hour
    # sell-then-rebuy at a worse price (see automation/notes.md). Require
    # the gap to clear SIGNAL_THRESHOLD before calling it a real trend; a
    # gap inside the dead zone is "neutral" and leaves the current
    # position (in or out) unchanged.
    bars = get_bars(symbol, asset_class)
    closes = [b["c"] for b in bars]
    if len(closes) < LONG_WINDOW:
        return None, len(closes)
    short, long_ = sma(closes, SHORT_WINDOW), sma(closes, LONG_WINDOW)
    gap = (short - long_) / long_
    if gap > SIGNAL_THRESHOLD:
        signal = "up"
    elif gap < -SIGNAL_THRESHOLD:
        signal = "down"
    else:
        signal = "neutral"
    return (signal, gap, closes), len(closes)


def check_symbol(symbol, asset_class):
    result, n_bars = momentum_signal(symbol, asset_class)
    pos = get_position(symbol)

    if result is None:
        return f"{symbol}: only {n_bars} {TIMEFRAME} bars available (need {LONG_WINDOW}) — skipping"
    signal, gap, closes = result

    # An order can sit unfilled for hours (e.g. equities placed outside
    # market hours). Without this check, every hourly run would see no
    # settled position/exit yet and re-issue another order on top of it.
    if has_open_order(symbol):
        return f"{symbol}: order already pending — not re-ordering this run"

    # Trailing stop takes priority over the crossover exit for a held
    # position — it can fire even on a "neutral" or "up" reading, since the
    # whole point is to lock in a gain before the lagging crossover gives
    # it back.
    if pos is not None:
        trail_result = check_trailing_stop(symbol, asset_class, pos)
        if trail_result is not None:
            return trail_result

    if pos is None:
        if signal == "up":
            regime = get_regime(symbol, asset_class, closes)
            if regime is not True:
                why = "below" if regime is False else "not enough history for"
                return f"{symbol}: momentum up (gap {gap:+.3%}) but {why} the {TREND_WINDOW}h trend — regime filter blocking entry"
            place_order(symbol, "buy", notional=NOTIONAL)
            return f"BOUGHT ~${NOTIONAL} {symbol} (momentum up: gap {gap:+.3%} > {SIGNAL_THRESHOLD:.3%}, above {TREND_WINDOW}h trend)"
        return f"{symbol}: no position, momentum {signal} (gap {gap:+.3%}) — staying out"

    plpc = float(pos.get("unrealized_plpc", 0))
    if signal == "down":
        qty = pos["qty"]
        place_order(symbol, "sell", qty=qty)
        return f"SOLD {qty} {symbol} (momentum down: gap {gap:+.3%}, unrealized was {plpc:+.2%})"
    return f"{symbol}: holding, momentum {signal} (gap {gap:+.3%}, unrealized {plpc:+.2%})"


def main():
    results = []
    for sym, cls in SYMBOLS.items():
        try:
            results.append(check_symbol(sym, cls))
        except Exception as e:
            results.append(f"{sym}: ERROR {e}")
    print("\n".join(results))


if __name__ == "__main__":
    main()
