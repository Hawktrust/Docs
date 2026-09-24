#!/usr/bin/env python3
"""
Day-trading bot for the Alpaca connection test (PR #5) — a bounded 3-day
experiment starting 2026-09-24, scheduled to auto-stop and revert to
momentum_bot.py's hourly checks afterward.

Same SMA-crossover logic as momentum_bot.py, but faster: 15-minute bars
instead of 1-hour, checked every 15 minutes instead of hourly, so the
short/long windows (3/10) cover ~45min/~2.5h instead of ~3h/~10h. Crypto
only — dropped COIN to avoid Pattern Day Trader rule exposure (4+ round
trips in 5 business days restricts equity accounts under $25k) and
market-hours complications; crypto has neither restriction and trades
24/7, which fits an actual "day trading" cadence far better than an
equity that's closed 17.5 hours a day.

Stateless: momentum and position state are derived fresh from Alpaca's
own bar/position/order data every run, same approach as momentum_bot.py.
"""
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

TRADE_BASE = "https://paper-api.alpaca.markets/v2"
DATA_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3"

SYMBOLS = ["BTC/USD", "ETH/USD", "DOGE/USD", "LTC/USD", "SOL/USD"]

SHORT_WINDOW = 3
LONG_WINDOW = 10
TIMEFRAME = "15Min"
NOTIONAL = "1000"  # dollars per new entry
SIGNAL_THRESHOLD = 0.0015  # 0.15% minimum SMA gap to count as a real signal


def _request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", "alpaca-daytrading-bot/1.0")
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
    # Positions endpoint uses the compact crypto symbol (BTCUSD), not the
    # slash form (BTC/USD) that orders/bars use — see momentum_bot.py.
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


def get_bars(symbol):
    start = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"{DATA_CRYPTO_BASE}/crypto/us/bars?symbols={encoded}&timeframe={TIMEFRAME}&limit=50&start={start}"
    status, body = _request(url)
    if status != 200:
        raise RuntimeError(f"bars/{symbol}: {status} {body}")
    return body.get("bars", {}).get(symbol, [])


def place_order(symbol, side, qty=None, notional=None):
    data = {"symbol": symbol, "side": side, "type": "market", "time_in_force": "gtc"}
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


def momentum_signal(symbol):
    # A plain crossover flips on any gap, including near-zero noise (measured
    # 2026-09-24: BTC +0.01%, ETH -0.04%, DOGE -0.04%, SOL +0.07% — all well
    # under 0.1%), which whipsawed the bot into a same-day sell-then-rebuy at
    # a worse price. Require the gap to clear SIGNAL_THRESHOLD before calling
    # it a real trend; a gap inside the dead zone is "neutral" and leaves
    # whatever position state already exists unchanged (no trade either way).
    bars = get_bars(symbol)
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
    return (signal, gap), len(closes)


def check_symbol(symbol):
    result, n_bars = momentum_signal(symbol)
    pos = get_position(symbol)

    if result is None:
        return f"{symbol}: only {n_bars} {TIMEFRAME} bars available (need {LONG_WINDOW}) — skipping"
    signal, gap = result

    if has_open_order(symbol):
        return f"{symbol}: order already pending — not re-ordering this run"

    if pos is None:
        if signal == "up":
            place_order(symbol, "buy", notional=NOTIONAL)
            return f"BOUGHT ~${NOTIONAL} {symbol} (momentum up: gap {gap:+.3%} > {SIGNAL_THRESHOLD:.3%})"
        return f"{symbol}: no position, momentum {signal} (gap {gap:+.3%}) — staying out"

    plpc = float(pos.get("unrealized_plpc", 0))
    if signal == "down":
        qty = pos["qty"]
        place_order(symbol, "sell", qty=qty)
        return f"SOLD {qty} {symbol} (momentum down: gap {gap:+.3%}, unrealized was {plpc:+.2%})"
    return f"{symbol}: holding, momentum {signal} (gap {gap:+.3%}, unrealized {plpc:+.2%})"


def main():
    results = []
    for sym in SYMBOLS:
        try:
            results.append(check_symbol(sym))
        except Exception as e:
            results.append(f"{sym}: ERROR {e}")
    print("\n".join(results))


if __name__ == "__main__":
    main()
