# Alpaca trading bots

Not part of the Ticket 01 (real estate signal ingestion) work in the rest of
this repo — this lives here because it's tied to the Alpaca connection test
on this branch (PR #5).

## momentum_bot.py (current, used by the hourly Routine)

Moving-average crossover across BTC/USD, ETH/USD, DOGE/USD, LTC/USD, SOL/USD,
and COIN:

- Short SMA (3 bars) vs. long SMA (10 bars) on 1-hour bars.
- A 0.15% dead-zone on the SMA gap: a gap smaller than that counts as
  "neutral" and leaves the current position (in or out) alone, instead of
  trading on noise. Ported from `daytrading_bot.py` after the 3-day
  day-trading experiment (2026-09-24 to 2026-09-27) proved it out live —
  see `notes.md` for the whipsaw root cause and the experiment's results.
- No position + uptrend (gap > threshold) → buy ~$1000 notional.
- Holding + downtrend (gap < -threshold) → sell the full position.
- Not enough bar history yet → skip that symbol this run.

Crypto pairs trade around the clock; COIN is the one equity leg and only
moves during exchange hours.

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

## daytrading_bot.py (inactive — bounded 3-day experiment, 2026-09-24 to 2026-09-27)

Same crossover shape as `momentum_bot.py`, but on 15-minute bars checked
hourly (the platform's minimum Routine interval), crypto-only (BTC, ETH,
DOGE, LTC, SOL, plus GRT/UNI added mid-experiment) to stay clear of the
Pattern Day Trader rule. Net result over the 3 days: -$124.85 realized
across 132 filled orders, +$53.85 unrealized on positions still open at the
end, for -$71.00 net — see `notes.md` for the full breakdown and the
(qualitative, not a live side-by-side) comparison against the hourly bot.
Kept for reference; the Routine now runs `momentum_bot.py` again.

## alpaca_bot.py (superseded)

The original fixed-threshold version (sell at +3% unrealized, rebuy at -2%
off the last sell). Kept for reference; the hourly Routine now runs
`momentum_bot.py` instead, since the fixed thresholds rarely triggered on
these three large/stable names.

## Reality check

Neither script guarantees profit. They are simple rule-based bots on a
paper account — they will win on some cycles and lose on others.
