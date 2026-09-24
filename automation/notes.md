# Trading bot notes

Running journal for the Alpaca connection test / trading bot experiments
(branch `claude/alpaca-connection-test-fpuiei`, PR #5). Newest entries at
the top.

---

## 2026-09-24 ~12:15 UTC — Expanded day-trading watchlist, found stronger candidates

Scanned 14 crypto pairs on 12h/15-min bars for volatility (range%) and
current momentum signal. Findings:

| Symbol | 12h range | 12h chg | Signal (0.15% threshold) |
|---|---|---|---|
| LTC/USD | 11.85% | +6.35% | DOWN |
| GRT/USD | 7.94% | -1.37% | **UP** |
| UNI/USD | 7.40% | -2.36% | **UP** |
| BCH/USD | 6.31% | -0.95% | neutral |
| SHIB/USD | 4.72% | +0.00% | UP |
| XRP/USD | 4.50% | -1.47% | UP |
| AVAX/USD | 4.29% | -1.20% | DOWN |
| AAVE/USD | 4.16% | +0.06% | neutral |
| DOGE/USD | 3.88% | -0.40% | neutral |
| LINK/USD | 3.24% | +0.08% | UP |
| SOL/USD | 3.17% | -1.61% | neutral |
| ETH/USD | 2.84% | -1.50% | neutral |
| BTC/USD | 2.09% | -1.00% | neutral |

At the time of scanning, BTC/ETH/DOGE/SOL (4 of the 5 original watchlist
symbols) were all sitting neutral — no real trend to trade — while GRT and
UNI had both meaningfully higher volatility *and* a genuine actionable
signal. Added both to `daytrading_bot.py`'s `SYMBOLS` list. Both bought
immediately on the existing UP signal:

- GRT/USD: 39,325.80 @ $0.025006
- UNI/USD: 108.65 @ $9.0257

**Takeaway for future scans:** volatility alone isn't enough — a volatile
symbol sitting neutral (like DOGE/SOL here) isn't a better trade than a
less-volatile one with a live signal. Look for the combination of range%
*and* a signal past the dead-zone threshold, not range% alone.

## 2026-09-24 ~12:00 UTC — Added 0.15% dead-zone filter to day-trading bot

Root-caused the -$330 realized loss (across both the hourly momentum bot
and the day-trading bot) to whipsaw: the plain SMA crossover flips on any
gap at all, including pure noise (measured gaps of 0.01–0.07% on
BTC/ETH/DOGE/SOL right before the fix — a full round trip of sell-then-
rebuy happened on gaps that small). Added `SIGNAL_THRESHOLD = 0.0015`
(0.15%) to `daytrading_bot.py`: a gap inside that band is "neutral" and
leaves the current position (in or out) alone rather than forcing a trade.

Verified live: same four symbols that had just whipsawed went straight to
"holding, momentum neutral" on the next run, with unrealized P&L flat and
small.

This is a noise-reduction fix, not a profitability fix — it should cut
losses from reacting to nothing, but doesn't give the underlying
indicator real predictive power it doesn't have. Real evidence of whether
it helped needs a few hourly cycles to accumulate; too little time has
passed as of this entry to say.

## 2026-09-24 ~11:00 UTC — Started 3-day day-trading experiment

User asked to try day trading for 3 days after asking for my opinion on
it (short version: most retail day traders lose money net of fees; this
is a bounded paper-money experiment, not something to take as strategy
advice). Built `daytrading_bot.py`: crypto-only (dropped COIN to avoid
Pattern Day Trader rule exposure on the equity leg), 15-minute bars
instead of 1-hour, same 3/10 SMA-crossover shape. Wanted to check every
15 minutes; the platform's Routine scheduler rejected anything under 1
hour, so it runs hourly with the faster 15-min-bar signal instead of true
15-minute cadence.

First run immediately sold all 5 existing crypto positions (15-min signal
agreed with the broader drawdown already in progress); next run bought
BTC/ETH/DOGE/SOL back within the hour, LTC stayed out. That fast round
trip was the first sign the plain crossover was too noise-sensitive — led
directly to the dead-zone fix above.

Scheduled an auto-revert to the original hourly `momentum_bot.py` for
2026-09-27, with a performance comparison at that point
(trigger `trig_01RSyB63t9jWKFfS3rboZAeR`).

## 2026-09-22/23 — v1 swing bot → v2 momentum bot, two live bugs

See `reports/alpaca-connection-test.md` for the full write-up: fixed
+3%/-2% thresholds barely triggered on BYD/BYDDY/MSFT (all ~3% range over
2 days), replaced with an SMA crossover retargeted to measured-volatile
symbols. Two bugs caught and fixed live: duplicate orders on unfilled
positions, and wrong crypto symbol format (`BTC/USD` vs `BTCUSD`) breaking
position lookups and causing repeat buys.
