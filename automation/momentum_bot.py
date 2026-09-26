#!/usr/bin/env python3
"""
Momentum swing bot for the Alpaca connection test (PR #5).

Replaces the fixed +3%/-2% swing bot (alpaca_bot.py) with a moving-average
crossover: short-term SMA above long-term SMA means "uptrend", below means
"downtrend". Enters a symbol on an uptrend with no position, exits a held
position on a downtrend. Adds BTC/USD and ETH/USD (24/7 markets) alongside
the existing equities, since positions only move during exchange hours.

Stateless like the original bot: momentum is recomputed from Alpaca's own
bar data every run, and open/closed state comes from Alpaca's own
positions endpoint. No local state file.

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
TIMEFRAME = "1Hour"
NOTIONAL = "1000"  # dollars per new entry


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


def get_bars(symbol, asset_class):
    start = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if asset_class == "crypto":
        encoded = urllib.parse.quote(symbol, safe="")
        url = f"{DATA_CRYPTO_BASE}/crypto/us/bars?symbols={encoded}&timeframe={TIMEFRAME}&limit=50&start={start}"
        status, body = _request(url)
        if status != 200:
            raise RuntimeError(f"bars/{symbol}: {status} {body}")
        return body.get("bars", {}).get(symbol, [])
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"{DATA_STOCKS_BASE}/stocks/{encoded}/bars?timeframe={TIMEFRAME}&limit=50&feed=iex&start={start}"
    status, body = _request(url)
    if status != 200:
        raise RuntimeError(f"bars/{symbol}: {status} {body}")
    return body.get("bars") or []


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
    bars = get_bars(symbol, asset_class)
    closes = [b["c"] for b in bars]
    if len(closes) < LONG_WINDOW:
        return None, len(closes)
    return ("up" if sma(closes, SHORT_WINDOW) > sma(closes, LONG_WINDOW) else "down"), len(closes)


def check_symbol(symbol, asset_class):
    signal, n_bars = momentum_signal(symbol, asset_class)
    pos = get_position(symbol)

    if signal is None:
        return f"{symbol}: only {n_bars} {TIMEFRAME} bars available (need {LONG_WINDOW}) — skipping"

    # An order can sit unfilled for hours (e.g. equities placed outside
    # market hours). Without this check, every hourly run would see no
    # settled position/exit yet and re-issue another order on top of it.
    if has_open_order(symbol):
        return f"{symbol}: order already pending — not re-ordering this run"

    if pos is None:
        if signal == "up":
            place_order(symbol, "buy", notional=NOTIONAL)
            return f"BOUGHT ~${NOTIONAL} {symbol} (momentum up: {SHORT_WINDOW}h SMA > {LONG_WINDOW}h SMA)"
        return f"{symbol}: no position, momentum down — staying out"

    plpc = float(pos.get("unrealized_plpc", 0))
    if signal == "down":
        qty = pos["qty"]
        place_order(symbol, "sell", qty=qty)
        return f"SOLD {qty} {symbol} (momentum flipped down, unrealized was {plpc:+.2%})"
    return f"{symbol}: holding, momentum still up (unrealized {plpc:+.2%})"


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
