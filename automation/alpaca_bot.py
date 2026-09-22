#!/usr/bin/env python3
"""
Paper-trading swing bot for the Alpaca connection test (PR #5).

Rule: sell a held position once it is up SELL_TRIGGER from cost basis;
after a symbol has no position but has a prior filled sell on record,
rebuy the same quantity once price has dropped REBUY_TRIGGER from that
sell's fill price. State is derived entirely from Alpaca's own position
and order-history endpoints, so the bot needs no local state file and is
safe to run from a fresh container on every scheduled firing.

Auth headers (APCA-API-KEY-ID / APCA-API-SECRET-KEY) are injected by the
cloud environment's network proxy for requests to *.alpaca.markets, so
this script never handles the credentials itself.
"""
import json
import urllib.request
import urllib.error

TRADE_BASE = "https://paper-api.alpaca.markets/v2"
DATA_BASE = "https://data.alpaca.markets/v2"
SYMBOLS = ["BYD", "BYDDY", "MSFT"]
SELL_TRIGGER = 0.03    # sell once up 3% unrealized
REBUY_TRIGGER = -0.02  # rebuy once down 2% from the sell price


def _request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_position(symbol):
    status, body = _request(f"{TRADE_BASE}/positions/{symbol}")
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"positions/{symbol}: {status} {body}")
    return body


def last_filled_order(symbol, side):
    status, body = _request(
        f"{TRADE_BASE}/orders?status=closed&symbols={symbol}&limit=50&direction=desc"
    )
    if status != 200:
        raise RuntimeError(f"orders/{symbol}: {status} {body}")
    for o in body:
        if o["side"] == side and o["status"] == "filled":
            return o
    return None


def latest_price(symbol):
    status, body = _request(f"{DATA_BASE}/stocks/{symbol}/trades/latest")
    if status != 200:
        raise RuntimeError(f"trades/latest/{symbol}: {status} {body}")
    return float(body["trade"]["p"])


def place_order(symbol, qty, side):
    status, body = _request(
        f"{TRADE_BASE}/orders",
        method="POST",
        data={
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        },
    )
    if status not in (200, 201):
        raise RuntimeError(f"order {side} {symbol}: {status} {body}")
    return body


def check_symbol(symbol):
    pos = get_position(symbol)
    if pos:
        plpc = float(pos["unrealized_plpc"])
        if plpc >= SELL_TRIGGER:
            qty = pos["qty"]
            place_order(symbol, qty, "sell")
            return f"SOLD {qty} {symbol} (unrealized was {plpc:+.2%}, trigger {SELL_TRIGGER:+.0%})"
        return f"{symbol}: holding, unrealized {plpc:+.2%} (sell trigger {SELL_TRIGGER:+.0%})"

    sell = last_filled_order(symbol, "sell")
    if not sell:
        return f"{symbol}: no position, no prior sell on record — nothing to do"

    sell_price = float(sell["filled_avg_price"])
    qty = sell["filled_qty"]
    cur = latest_price(symbol)
    change = (cur - sell_price) / sell_price
    if change <= REBUY_TRIGGER:
        place_order(symbol, qty, "buy")
        return f"REBOUGHT {qty} {symbol} (price {change:+.2%} vs last sell, trigger {REBUY_TRIGGER:+.0%})"
    return f"{symbol}: no position, price {change:+.2%} vs last sell (rebuy trigger {REBUY_TRIGGER:+.0%})"


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
