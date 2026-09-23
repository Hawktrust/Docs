# Alpaca connection test — status report

**Date:** 2026-09-22
**Goal:** connect to the user's Alpaca paper-trading account and place a
test order for 1 share of BYD, to confirm the fill shows up in the account.
**Status: complete.** See [Resolution](#resolution) below for the final
outcome — both orders filled.

## Result: initially blocked, no order placed

Credentials (key ID + secret) for `https://paper-api.alpaca.markets/v2` were
provided in chat. They were never actually exercised — every outbound
request to `paper-api.alpaca.markets` was rejected before reaching Alpaca:

```
$ curl https://paper-api.alpaca.markets/v2/account ...
curl: (56) <connection reset — proxy CONNECT rejected>
```

`curl -sS "$HTTPS_PROXY/__agentproxy/status"` confirms the cause:

```
"recentRelayFailures": [
  { "kind": "connect_rejected",
    "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
    "host": "paper-api.alpaca.markets:443" }
]
```

This is this session's egress proxy enforcing the cloud environment's
**network access policy**, which only allows a fixed set of package-registry
/ VCS domains by default ("Trusted" level). `paper-api.alpaca.markets` (and
`data.alpaca.markets`, needed for quotes) are not on that list. Per the
proxy's own operating rules, a 403 policy denial is to be reported, not
routed around.

## What needs to happen to unblock this

The environment's network access needs to be switched from **Trusted** to
**Custom** (at claude.ai/code → environment settings → Network access) with:

```
paper-api.alpaca.markets
data.alpaca.markets
```

added to **Allowed domains**. This has to be done by the account owner in
the environment configuration UI — it isn't something a session can change
about itself, and the change only takes effect for sessions started after
the update (a running session keeps its original policy).

## Other open question: ticker ambiguity

`BYD` on US exchanges (what Alpaca trades) resolves to **Boyd Gaming
Corporation**, not the Chinese EV maker BYD Company Ltd, which trades OTC as
`BYDDY` / `BYDDF`. Needs confirmation from the user before an order is
placed, once connectivity is unblocked.

## Security note

The Alpaca key ID and secret were pasted into the chat in plaintext. They
are **not** stored in this repo or this report. Since a paper-trading
secret was shared in plaintext, it's good practice to rotate it in the
Alpaca dashboard regardless of whether this test proceeds.

## Resolution

The environment owner updated the "Docs" cloud environment: **Network
access** switched from Trusted to **Custom**, with `paper-api.alpaca.markets`
and `data.alpaca.markets` added to Allowed domains. Unlike the general
guidance that network-policy changes only apply to new sessions, this took
effect immediately for the already-running session — a retried `GET
/v2/account` went from a proxy 403 to a `401 unauthorized` from Alpaca
itself, confirming the host was now reachable.

The 401 was because the original key/secret (pasted in chat) had since been
rotated and were no longer valid. Rather than pasting new credentials into
chat, the environment's **API credentials** feature was used instead: a
credential entry with custom headers `APCA-API-KEY-ID` and
`APCA-API-SECRET-KEY` (no prefix) scoped to `paper-api.alpaca.markets` and
`data.alpaca.markets`. The proxy injects these into matching requests
without the session ever seeing the raw values.

Both ambiguous-ticker interpretations of "BYD" were placed, per user
instruction:

| Symbol | Company | Qty | Fill price | Status |
|---|---|---|---|---|
| `BYD` | Boyd Gaming Corporation (NYSE) | 1 | $72.38 | Filled |
| `BYDDY` | BYD Company Ltd, unsponsored ADR (OTC) | 1 | $10.33 | Filled |

(`BYDDF`, the other BYD Company Ltd OTC listing, was checked and found
`tradable: false` / `status: inactive` on Alpaca — not used.)

## Follow-on: automated trading bot

After the connection test, the user asked for an ongoing automated
strategy ("keep on setting trades... making profit everytime"). Two
important caveats given up front and still true: no rule-based bot
guarantees profit, and this is paper money — losses here have no real
financial consequence, which is the point of testing it this way.

### v1 — fixed-threshold swing bot (`automation/alpaca_bot.py`)

Sell a position at **+3%** unrealized, rebuy at **-2%** off the last sell
price, checked hourly via a Routine (trigger `trig_01CoW1HYzK2mUehKfw7dkZas`).
Traded BYD/BYDDY/MSFT. Over many consecutive hourly checks these three
barely moved (~3% range across 2 days), so the bot sat idle almost the
entire time — correct behavior, just not useful.

### v2 — momentum bot (`automation/momentum_bot.py`, current)

Replaced the fixed thresholds with a 3-hour/10-hour SMA crossover, and
retargeted to the most volatile symbols actually measured on Alpaca paper
(2-day hourly-bar range%): **BTC/USD** (4.3%), **ETH/USD** (4.2%),
**DOGE/USD** (14.2%), **LTC/USD** (7.8%), **SOL/USD** (4.2%), and **COIN**
(5.3%, best-moving equity — beat TSLA/NVDA/MSFT/BYD). Crypto trades 24/7,
which also fixed the idle-overnight problem from v1. Same Routine, updated
to call the new script; no local state, everything derived fresh from
Alpaca's own position/order/bar data each run.

### Bugs found and fixed live

1. **Duplicate orders on unfilled positions.** The bot only checked
   *filled* positions before deciding to enter, so a symbol whose order
   was still pending (e.g. an equity order placed while markets were
   closed) looked identical to "never traded" on the next hourly run — it
   bought COIN a second time before the first $1000 order had even
   filled. Caught immediately; the duplicate was cancelled manually. Fix:
   check `GET /v2/orders?status=open` for the symbol first and skip if one
   exists.
2. **Wrong crypto symbol format for position lookups.** Alpaca's
   `/v2/positions/{symbol}` endpoint uses the compact crypto symbol
   (`BTCUSD`), while orders/assets/bars use the slash form (`BTC/USD`).
   Querying positions with the slash form 404s even when a position
   exists — indistinguishable from "no position" — so the bot re-bought
   BTC/USD and LTC/USD on top of already-filled positions two hourly
   cycles in a row before this was caught, roughly doubling both to
   ~$2000 each instead of the intended $1000. Fix: strip the slash for
   the positions-endpoint path only.

Both are committed with the fix; no further recurrences observed after.

### Status as of last report

All six target symbols reached a position at some point; COIN's position
was later closed when its momentum flipped down (SOLD, partial-then-full
fill, normal fractional-share behavior). Unrealized P&L across the
remaining crypto positions has been negative since entry (BTC/ETH/DOGE/
LTC/SOL all down several percent), with the SMA crossover not yet
flipping to a sell signal — expected behavior for a lagging-indicator
strategy riding out a drawdown, not a malfunction. Portfolio equity has
dipped modestly from the $100,000 starting baseline as a result. The
account also holds a few pre-existing positions (GS, ISRG, MRVL) that
predate this session and are not managed by the bot.

The Routine remains active and continues checking hourly.
