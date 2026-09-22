# Alpaca connection test — status report

**Date:** 2026-09-22
**Goal:** connect to the user's Alpaca paper-trading account and place a
test order for 1 share of BYD, to confirm the fill shows up in the account.

## Result: blocked, no order placed

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

## Next step

Once the environment's allowed domains include the two hosts above, re-run
the connection test:

```
GET /v2/account
GET /v2/assets/{symbol}
POST /v2/orders   { symbol, qty: 1, side: "buy", type: "market", time_in_force: "day" }
```
