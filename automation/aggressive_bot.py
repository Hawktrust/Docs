#!/usr/bin/env python3
"""
Aggressive bot for the Alpaca connection test (PR #5) — a bounded 3-day
high-variance experiment (2026-09-28 to 2026-10-01), after the user asked
for a $10,000-in-3-days target.

Being direct about what this is: there is no legitimate strategy that
reliably turns ~$99k into ~$109k in 3 days. This script does not target
that number — nothing can, and no amount of tuning below makes it a
likely outcome rather than a low-probability bet. What it actually does
differently from momentum_bot.py is trade far more aggressively: 35% of
current equity per position (vs. a flat $1000), faster/more sensitive
signals, and none of the risk controls (regime filter, trailing stop)
added to momentum_bot.py on 2026-09-28. That raises the odds of a big gain
and the odds of a big loss by roughly the same amount — it is realistically
more likely to lose money than momentum_bot.py, not less. Scheduled to
auto-revert to momentum_bot.py after 3 days regardless of outcome.

Crypto-only (dropped COIN) to stay clear of the Pattern Day Trader rule at
this trade frequency. Stateless like the other bots: everything is derived
fresh from Alpaca's own data each run, no local state file.
"""
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

TRADE_BASE = "https://paper-api.alpaca.markets/v2"
DATA_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3"

SYMBOLS = ["BTC/USD", "ETH/USD", "DOGE/USD", "LTC/USD", "SOL/USD", "GRT/USD", "UNI/USD"]

SHORT_WINDOW = 2
LONG_WINDOW = 6
TIMEFRAME = "15Min"
SIGNAL_THRESHOLD = 0.0005  # much tighter dead zone than momentum_bot.py — trades on smaller gaps
NOTIONAL_FRACTION = 0.35  # 35% of current account equity per new entry, recomputed live each run


def _request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", "alpaca-aggressive-bot/1.0")
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


def get_equity():
    status, body = _request(f"{TRADE_BASE}/account")
    if status != 200:
        raise RuntimeError(f"account: {status} {body}")
    return float(body["equity"])


def get_position(symbol):
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
        data["notional"] = str(round(notional, 2))
    status, body = _request(f"{TRADE_BASE}/orders", method="POST", data=data)
    if status not in (200, 201):
        # Aggressive sizing can outrun buying power once several symbols
        # trigger in the same run — treat that as a skip, not a crash.
        msg = str(body.get("message", body)) if isinstance(body, dict) else str(body)
        if "buying power" in msg.lower() or "insufficient" in msg.lower():
            return None
        raise RuntimeError(f"order {side} {symbol}: {status} {body}")
    return body


def sma(closes, n):
    return sum(closes[-n:]) / n


def momentum_signal(symbol):
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


def check_symbol(symbol, equity):
    result, n_bars = momentum_signal(symbol)
    pos = get_position(symbol)

    if result is None:
        return f"{symbol}: only {n_bars} {TIMEFRAME} bars available (need {LONG_WINDOW}) — skipping"
    signal, gap = result

    if has_open_order(symbol):
        return f"{symbol}: order already pending — not re-ordering this run"

    if pos is None:
        if signal == "up":
            notional = equity * NOTIONAL_FRACTION
            order = place_order(symbol, "buy", notional=notional)
            if order is None:
                return f"{symbol}: momentum up (gap {gap:+.3%}) but SKIPPED — insufficient buying power for ${notional:.2f}"
            return f"BOUGHT ~${notional:.2f} {symbol} (momentum up: gap {gap:+.3%} > {SIGNAL_THRESHOLD:.3%})"
        return f"{symbol}: no position, momentum {signal} (gap {gap:+.3%}) — staying out"

    plpc = float(pos.get("unrealized_plpc", 0))
    if signal == "down":
        qty = pos["qty"]
        place_order(symbol, "sell", qty=qty)
        return f"SOLD {qty} {symbol} (momentum down: gap {gap:+.3%}, unrealized was {plpc:+.2%})"
    return f"{symbol}: holding, momentum {signal} (gap {gap:+.3%}, unrealized {plpc:+.2%})"


def main():
    equity = get_equity()
    results = [f"equity: ${equity:,.2f}"]
    for sym in SYMBOLS:
        try:
            results.append(check_symbol(sym, equity))
        except Exception as e:
            results.append(f"{sym}: ERROR {e}")
    print("\n".join(results))


if __name__ == "__main__":
    main()
