# Trading bot notes

## 2026-09-28 ~13:58 UTC — Trailing stop fired for the first time

LTC (bought ~09:58 UTC at $70.08 on a regime-confirmed entry) ran up to
+3.38% unrealized, then the trailing stop caught a 2.89% pullback from that
peak and sold at $70.25 (+0.40% unrealized) — well before the lagging
crossover would have flipped down on its own. Confirmed via order history:
sell filled 13.928408315 @ $70.25.

This is the comparison case the fix was meant for: contrast with the old
behavior (SOL running +2.74% → -2.44% across consecutive hourly checks on
2026-09-27/28 before the plain crossover caught the reversal). One data
point, but it's the first live confirmation the trailing stop is doing its
job rather than just adding complexity.

Also the regime filter has been blocking BTC/ETH/DOGE entries on every run
since it went live, all had positive crossover gaps up to +2.1% but sat
below the 50h trend — worth revisiting whether the filter is too strict if
this persists for days without any of them clearing it, since that would
mean missing real trend continuations rather than just filtering noise.

## 2026-09-28 ~08:15 UTC — Added regime filter + trailing stop to momentum_bot.py

User asked how to make more money; after laying out several options (regime
filter, trailing stop, volatility-weighted sizing, compounding,
multi-timeframe confirmation), picked the two addressing the clearest
failure modes actually observed in this account's history:

1. **Regime filter** — a new entry now requires price to be above the
   50-hour SMA (`TREND_WINDOW`), not just a positive 3h/10h crossover gap.
   Only gates entries; exits on a down signal are never blocked (missing an
   exit is worse than missing an entry). `get_bars()` now takes a longer
   lookback (8 days crypto / 25 days equity, to get 50+ bars even on
   COIN's sparse trading-hours-only bar count) and returns closes alongside
   the signal so the regime check can reuse them without a second fetch.
2. **Trailing stop** — once a held position has been up at least 0.5%
   (`MIN_PEAK_GAIN`) since entry, sell early if price pulls back 1%
   (`TRAILING_STOP_PCT`) from that peak, instead of waiting for the
   crossover to flip down. Directly targets the repeated pattern this
   week of a position running to +2-2.7% unrealized then round-tripping
   to a loss before the lagging signal caught up (SOL went +2.74% →
   -2.44% over consecutive hourly checks on 2026-09-27/28, for example).
   Peak-since-entry is derived statelessly each run: look up the most
   recent filled buy order for the symbol (its fill time = entry time,
   since the bot always fully enters/exits, never scales), then fetch bar
   highs from that timestamp forward and take the max.

Verified live immediately after deploying: LTC sold normally via the
ordinary crossover-down path (never armed the trailing stop, since it
never reached +0.5% before turning down) — confirms the new
`check_trailing_stop()` call doesn't error or interfere when it has
nothing to do. Both additions are unverified on an actual trailing-stop
trigger or a regime-blocked entry as of this entry; will note here when
either first fires.

Not implemented from the same discussion (out of scope for this pass):
volatility-weighted position sizing, compounding position size with
account equity, and multi-timeframe (15m+1h) confirmation.

## 2026-09-27 ~11:00-13:54 UTC — 3-day day-trading experiment ended; reverted to hourly momentum bot

Trigger `trig_01RSyB63t9jWKFfS3rboZAeR` fired at the scheduled end time. Pulled
all filled orders for the 7 day-trading symbols from experiment start
(2026-09-24 11:00 UTC) through end (2026-09-27 11:58 UTC) — 132 filled orders
total (68 buys, 64 closing sells) — and ran FIFO matching per symbol:

| Symbol | Realized P&L | Sells | Buys |
|---|---|---|---|
| LTC/USD | -$78.66 | 12 | 12 |
| GRT/USD | -$35.07 | 14 | 14 |
| UNI/USD | -$22.73 | 13 | 13 |
| DOGE/USD | -$16.85 | 9 | 10 |
| ETH/USD | +$1.47 | 5 | 6 |
| BTC/USD | +$1.39 | 3 | 4 |
| SOL/USD | +$25.59 | 8 | 9 |
| **Total realized** | **-$124.85** | 64 | 68 |

Win rate on closing trades: 19 wins / 45 losses (29.7%) — consistent with a
dead-zone-filtered crossover: most closes are small losses cut early, a
minority are the larger wins that make up for them. Positions still open at
experiment end (BTC, DOGE, ETH, SOL) carried +$53.85 unrealized, for a net
result of **-$71.00** over the 3 days on ~$1000/symbol sizing.

**Caveat on the "compared to the original hourly bot" ask:** `momentum_bot.py`
was not run in parallel during these 3 days (the day-trading bot fully
replaced it), so there's no live side-by-side. The closest comparison is
qualitative: before the dead-zone fix (2026-09-24, pre-noon), the combined
v1+v2 bots had run up roughly -$330 realized from whipsaw alone. The
day-trading bot's 3-day result (-$71 net) trades far more frequently (132
fills vs. momentum_bot.py's much lower hourly-bar turnover) but lands closer
to break-even than the pre-fix trajectory — mildly encouraging for the
dead-zone fix, but a small sample and not proof either strategy has a real
edge on a plain SMA crossover.

Reverted the Routine (`trig_01CoW1HYzK2mUehKfw7dkZas`) back to its original
name "Alpaca swing bot check" and to running `momentum_bot.py` hourly, per
the scheduled instruction. Before reactivating it, ported the 0.15%
dead-zone fix into `momentum_bot.py` itself (previously only
`daytrading_bot.py` had it) — running the known-whipsaw-prone version back
would have reintroduced the exact problem the fix addressed. Did not port
the GRT/UNI symbol expansion; `momentum_bot.py` keeps its original
BTC/ETH/DOGE/LTC/SOL/COIN set. First run under the reverted Routine (run
manually to verify the fix) immediately sold ETH/DOGE/SOL on momentum turning
down and bought LTC on momentum turning up — normal crossover behavior, not
an error.

## 2026-09-24 ~13:58 UTC — First all-green cycle since the fix; LTC rebought

Every held position now unrealized-positive (BTC +0.77%, ETH +0.51%, DOGE
+1.19%, SOL +0.78%, GRT +2.01%, UNI +1.51%). Rebought LTC on a strong
+3.588% gap — well clear of the dead zone, a real trend signal not noise.
Broader crypto market appears to have turned up this hour. Too early to
credit the dead-zone fix specifically (could just be market direction),
but no whipsaw and a clean single trade this cycle is the behavior we
wanted.

## 2026-09-24 ~12:58 UTC — First scheduled cycle since dead-zone fix: clean

First hourly Routine run after the 0.15% dead-zone fix and GRT/UNI
addition landed. Zero trades — all 7 positions (BTC/ETH/DOGE/SOL/GRT/UNI
holding, LTC still correctly out) stayed put. GRT is down -1.37%
unrealized but its gap (+0.374%) is well past the dead zone, so it held
through the dip on a real signal rather than reacting to noise — exactly
the intended behavior. One data point, not proof, but consistent with
the fix working.

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

## 2026-09-26 ~13:00 UTC — Credential-injection outage: authenticated endpoints hanging

The scheduled bot check timed out on all 7 symbols (`ERROR The read operation timed out`).
Investigated: public/unauthenticated Alpaca endpoints (`/v2/clock`, data feed
`/trades/latest`) respond normally (0.2-0.4s), but every authenticated
endpoint (`/v2/account`, `/v2/positions`, `/v2/orders`) hangs and times out
consistently across multiple retries (15-30s timeouts). This isolates the
problem to the environment's credential-injection layer for the Alpaca API
credential, not Alpaca's API itself (which is clearly up and fast for
public routes) and not a bug in daytrading_bot.py.

Practical effect: can't verify current positions or place/confirm trades
until this clears. No fabricated status reported during the outage —
reported as "unknown, blocked" instead.
