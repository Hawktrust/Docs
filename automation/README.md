# Alpaca swing bot

Not part of the Ticket 01 (real estate signal ingestion) work in the rest of
this repo — this lives here because it's tied to the Alpaca connection test
on this branch (PR #5).

`alpaca_bot.py` checks BYD, BYDDY, and MSFT paper positions:

- If a position is up **+3%** unrealized, it sells the whole position at
  market.
- If a symbol has no position but a prior filled sell is on record, it
  rebuys the same quantity once price has dropped **-2%** from that sell's
  fill price.

No local state file: both rules are derived from Alpaca's own position and
order-history endpoints each run, so it's safe to run from a fresh
container every time a scheduled check fires.

Run manually:

```
python3 automation/alpaca_bot.py
```

This is a real (if simple) trading strategy on a *paper* account — it will
lose on some trades and win on others. There is no guarantee of profit on
every run.
