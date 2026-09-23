# Alpaca trading bots

Not part of the Ticket 01 (real estate signal ingestion) work in the rest of
this repo — this lives here because it's tied to the Alpaca connection test
on this branch (PR #5).

## momentum_bot.py (current, used by the hourly Routine)

Moving-average crossover across BYD, BYDDY, MSFT, BTC/USD, and ETH/USD:

- Short SMA (3 bars) vs. long SMA (10 bars) on 1-hour bars.
- No position + uptrend (short > long) → buy ~$1000 notional.
- Holding + downtrend (short < long) → sell the full position.
- Not enough bar history yet → skip that symbol this run.

Crypto pairs were added because equities only move during exchange hours;
BTC/USD and ETH/USD trade around the clock, so the bot has something to do
outside 9:30–16:00 ET too.

**Known limitation:** BYDDY (OTC) has no bar data on the free IEX feed this
paper account uses, so it always skips — that's a data-availability gap,
not a bug. Its position (if any) sits untouched by this bot.

No local state file — momentum and position state are both derived fresh
from Alpaca's position/bar endpoints every run, so it's safe to run from a
fresh container each time a scheduled check fires.

Run manually:

```
python3 automation/momentum_bot.py
```

## alpaca_bot.py (superseded)

The original fixed-threshold version (sell at +3% unrealized, rebuy at -2%
off the last sell). Kept for reference; the hourly Routine now runs
`momentum_bot.py` instead, since the fixed thresholds rarely triggered on
these three large/stable names.

## Reality check

Neither script guarantees profit. They are simple rule-based bots on a
paper account — they will win on some cycles and lose on others.
