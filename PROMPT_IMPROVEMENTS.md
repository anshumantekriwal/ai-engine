# Prompt Improvement Backlog

Issues discovered through generation testing. Each entry includes the root cause,
observed symptom, and proposed fix. Will be addressed in batch alongside few-shot
example development.

---

## Issue 1: Model reimplements indicator math instead of using the trigger system

**Severity:** Critical  
**Observed in:**
- `strategy.json` (RSI mean reversion, Feb 2026) — manual RSI from candles in scheduled
  trigger, frozen at 55.21 while real trigger RSI was ~41
- `strategy2.json` (vague "make money" prompt, Feb 2026) — manual EMA9/EMA21 calculation
  from raw candles using a hand-rolled `calculateEMA` function, instead of using
  `registerTechnicalTrigger` with `crossover`/`crossunder` condition which handles
  two-series comparison natively
- `strategy6.json` (RSI+MACD composite, Feb 2026) — worst instance yet. Uses
  `registerCompositeTrigger` for entry (correct), but the monitor/exit path manually
  reimplements BOTH RSI and MACD from candles. RSI uses naive SMA (not Wilder's).
  MACD is completely wrong: omits the signal line entirely, sets `macdHist = macdLine`
  with comment "Simplified". Manual EMA helper only returns the final value, making
  signal line computation impossible. Exit decisions based on wrong histogram will
  fire at different times than the real composite trigger. Code copy-pasted twice
  (idle path and position-hold path). Also took notably long to generate — the
  complexity of reimplementing two indicators manually likely contributed to slow
  generation and bloated output.

**Symptom:** The generated code registers `registerTechnicalTrigger` for buy/sell
signals OR uses `registerScheduledTrigger` with manual indicator math. The manual
calculations:
- Use naive/incorrect algorithms (SMA instead of Wilder's for RSI, custom EMA seed)
- Produce stale or divergent values compared to the trigger system
- Contradicts real indicator values from the trigger system
- In the worst case (strategy6), the MACD histogram is entirely fabricated (MACD line
  without signal line subtraction), making exit decisions based on a meaningless number

**Root cause:** The prompt doesn't explicitly teach that:
1. The trigger system already computes fresh indicator values every ~60s
2. You should NOT re-implement indicator math from candles when triggers already do it
3. `TechnicalIndicatorService` is available if you truly need a manual computation

**Proposed fix:**
- Add a rule: "NEVER manually calculate an indicator (RSI, EMA, etc.) from raw candles
  when you already have a registerTechnicalTrigger for that indicator. The trigger system
  uses the `technicalindicators` library with proper algorithms. Manual candle math will
  produce different (usually wrong) values."
- Add a rule: "If you need an indicator value in a scheduled trigger (e.g. for reset
  detection), register an additional `registerTechnicalTrigger` with an appropriate
  condition, or use the last known value from the trigger system stored in `this.tradeState`."
- Add a reasoning example for the "RSI reset detection" pattern that shows how to store
  the trigger-provided RSI value and check reset thresholds without reimplementing RSI.

---

## Issue 2: Scheduled trigger produces stale/divergent data from technical triggers

**Severity:** Critical  
**Observed in:**
- `strategy.json` — RSI 55.21 (manual) vs 41.09 (trigger system) simultaneously
- `strategy2.json` — manual EMA values computed every 5 min from candles, no way to
  verify against a reference since `registerTechnicalTrigger` with `crossover` was not used
- `strategy6.json` — monitor path computes RSI and MACD from candles independently of
  the composite trigger. The MACD calculation is provably wrong (no signal line), so
  monitor reports and exit decisions are guaranteed to diverge from the trigger system.

**Symptom:** Two different RSI values logged simultaneously — 41.09 from the trigger
system and 55.21 from the scheduled monitor. User sees contradictory data in their
dashboard. In strategy6, the monitor shows a fabricated MACD histogram that has no
relationship to the real one used by the composite trigger.

**Root cause:** Direct consequence of Issue 1. The scheduled trigger computes its own
RSI independently, and the two computations use different algorithms and data windows.

**Proposed fix:**
- Address via Issue 1 fixes (don't reimpllement indicators).
- Additionally: add a pattern showing how to structure a monitor/heartbeat trigger
  that reports the last known indicator value without recalculating it. Example:
  ```
  // In tradeState, store the latest RSI from triggers:
  // (inside executeTrade when action is 'buy' or 'sell')
  this.tradeState.lastRsiValue = triggerData.value;
  
  // In the monitor action, just report the stored value:
  const lastRsi = this.tradeState.lastRsiValue;
  await this.updateState('monitor', { rsi: lastRsi, ... }, ...);
  ```

---

## Issue 3: Model doesn't know TechnicalIndicatorService exists for manual computation

**Severity:** Medium  
**Observed in:** Same strategy

**Symptom:** When the model needs an indicator value outside a trigger callback, it
writes raw candle-based math instead of using the existing service.

**Root cause:** `TechnicalIndicatorService` is not documented in `prompt_docs.py`.
The model only knows about `registerTechnicalTrigger` (which uses the service
internally) but not how to call the service directly.

**Proposed fix:**
- Decision needed: should we expose `TechnicalIndicatorService` to the model at all?
  - Pro: avoids bad manual math.
  - Con: adds API surface / potential misuse. The trigger system should cover 95% of cases.
- If yes: add a small section in `prompt_docs.py` for `this._technicalIndicatorService.compute()`.
- If no: strengthen the "never reimplement" rule and ensure the patterns cover all
  common cases where the model might feel it needs manual computation.

---

## Issue 4: Minor API usage — direct positionTracker method instead of BaseAgent wrapper

**Severity:** Low  
**Observed in:**
- `strategy.json` — `this.positionTracker.getClosedPositions(coin)`
- `strategy2.json` — `this.positionTracker.getOpenPosition(coin)`
- `strategy3.json` — mixed: uses `this.positionTracker.getOpenPosition(coin)` in
  external close detection and skip logic, but correctly uses `this.getTrackedOpenPositions()`
  and `this.getTrackedClosedPositions()` elsewhere in the same file. Inconsistent.
- `strategy4.json` — `this.positionTracker.getOpenPosition()` in external close detection
- `strategy5.json` — `this.positionTracker.getOpenPosition()` in init resume check and
  external close detection. Also `this.positionTracker.getClosedPositions()` (2 places)
- `strategy6.json` — `this.positionTracker.getOpenPosition()` in external close detection
- `strategy7.json` — `this.positionTracker.getOpenPosition(this.coin)` in external close
  detection

**Symptom:** Code uses `this.positionTracker.getClosedPositions(coin)` instead of the
documented `this.getTrackedClosedPositions(coin)`. Both work, but the documented API
is the intended public interface.

**Proposed fix:**
- Strengthen the prompt rule: "Use `this.getTrackedClosedPositions()`,
  `this.getTrackedOpenPositions()`, `this.getPnlSummary()`, `this.getPnlByCoin()`
  — NOT `this.positionTracker.*` directly."
- Add to validation prompt error list: "Direct `this.positionTracker.*` method calls
  instead of the documented `this.get*` wrapper methods."

---

## Issue 5: Model hallucinates APIs that don't exist (`this.logger`)

**Severity:** Critical (causes runtime crash)  
**Observed in:**
- `strategy2.json` — `this.logger.info(...)` and `this.logger.error(...)` throughout
  all three code sections. Crashes on init.
- `strategy6.json` — `this.log(...)` in init (`this.log('RSI-MACD Momentum Dip agent
  initialized for BTC')`) and in the catch block (`this.log(\`Error...\`, 'error')`).
  Different hallucinated method name but same root cause. Crashes on init.
- `strategy8.json` — `this.logger.info(...)` in init AND `this.logger.error(...)` in
  the execution catch block. Same pattern as strategy2. Crashes on init. This is now
  3/8 strategies (37.5%) — the single most common crash cause.

**Symptom:** The generated code calls `this.logger.*` or `this.log(...)`. `BaseAgent`
has neither property. This crashes immediately on init. When the hallucinated call is
inside a `catch` block, it masks the real error.

The crash is especially insidious because it happens inside a `catch` block — the first
`this.logger.info(...)` throws, the `catch` block runs `this.logger.error(...)` which
also throws, and the real error is masked.

**Root cause:** The model is inventing convenience APIs it expects to exist. This is a
classic LLM hallucination — `this.logger` looks like a standard pattern from other
frameworks (Winston, Pino, etc.) and the model assumes it's available.

**Proposed fix:**
- Add explicit rule: "There is NO `this.logger` or `this.log`. Use `console.log` for
  debug logging and `this.updateState()` for user-facing messages. Do NOT invent APIs."
- Add to validation prompt error list: "Usage of `this.logger`, `this.log`, or any
  undocumented `this.*` method — these do not exist."
- Add lint check in `code_generator.py`: flag `this.logger` and `this.log(` as errors.
  This is a P0 fix — it causes immediate crashes and is now observed in 3/8 strategies.

---

## Issue 6: Missing `await` on async methods

**Severity:** High (silent logic bug — safety gate permanently blocks or bypasses)  
**Observed in:**
- `strategy2.json` — `checkSafetyLimits` called without `await`. Safety bypassed.
- `strategy4.json` — same. Safety ALWAYS blocks (returns "undefined" as reason)
  because `!safetyCheck.allowed` where `safetyCheck` is a Promise evaluates to
  `!undefined` = `true`. Confirmed in live logs: "blocked by safety: undefined".
  This prevented the agent from EVER trading despite valid signals.
- `strategy5.json` — correctly `await`ed ✓
- `strategy6.json` — correctly `await`ed ✓

Score: 2/6 strategies have this bug. Both rendered the agent non-functional.

**Symptom:** `const safetyCheck = this.checkSafetyLimits(...)` returns a Promise, not
the result object. The subsequent `if (!safetyCheck.allowed)` check evaluates against
a Promise (which is truthy), so the safety gate always blocks with "reason: undefined".

**Root cause:** The lint checker in `code_generator.py` does check for missing `await`
on known async methods, but this particular call may have slipped through the regex
(e.g. if the assignment pattern doesn't match the expected format).

**Proposed fix:**
- Verify that `checkSafetyLimits` is in the lint checker's async patterns list.
- Consider a broader lint: any `this.orderExecutor.*`, `this.checkSafetyLimits`,
  `this.logTrade`, `this.reconcileTrackedPositions`, `this.updateState` call not
  preceded by `await` should be flagged, regardless of assignment pattern.

---

## Issue 7: Reset logic fires while position is still open

**Severity:** Medium (logic bug, not crash)  
**Observed in:** `strategy3.json` (multi-coin mean reversion, Feb 2026)

**Symptom:** The "CHECK FOR RESET" section resets `ideaActive = false` and
`lastSignal = null` when price deviation returns to the neutral zone — but does NOT
close the open position. The position stays open with SL/TP, but since `ideaActive`
is now false, a new signal in the same direction could open a duplicate position on
the same coin.

**Root cause:** The model conflates "trade idea reset" (ready for new signal) with
"position lifecycle" (still have an open position). In a mean reversion strategy,
the reset should only happen AFTER the position is closed (by SL/TP or manual exit),
not while it's still open.

**Proposed fix:**
- Add a reasoning example or rule: "A trade idea reset (clearing `ideaActive` and
  `lastSignal`) should only happen after the position is confirmed closed — either
  via external close detection or explicit close logic. Do NOT reset state while a
  position is still open, or you risk opening duplicate positions."
- The few-shot examples should demonstrate the correct lifecycle:
  signal → entry → hold (ideaActive=true) → exit (SL/TP or manual) → reset → ready

---

## Issue 8: Model guesses wrong return shapes for underdocumented API endpoints

**Severity:** Critical (silent total failure — strategy never trades)  
**Observed in:** `strategy5.json` (SOL funding carry, Feb 2026)

**Symptom:** The code parses `getPredictedFundings()` as:
```javascript
currentFundingRate = parseFloat(fundingArrays[0][0]);
```
But the actual return shape is:
```
["SOL", [
  ["BinPerp",  {"fundingRate": "-0.00011252", ...}],
  ["HlPerp",   {"fundingRate": "-0.0000031192", ...}],
  ["BybitPerp", {"fundingRate": "-0.0000162", ...}]
]]
```
So `fundingArrays[0][0]` is the string `"BinPerp"`, and `parseFloat("BinPerp")` = `NaN`.
The strategy silently fails — every funding check evaluates to `NaN`, so entry/exit
conditions are never met. No error is thrown, no user-visible indication of failure.

**Verified by test:** Direct API call confirmed the return shape. The correct parsing is:
```javascript
const hlEntry = fundingArrays.find(([venue]) => venue === 'HlPerp');
const fundingRate = hlEntry ? parseFloat(hlEntry[1].fundingRate) : null;
```

**Root cause:** `getPredictedFundings()` is a raw passthrough (`return await
hyperliquidRequest(body)`) with no transformation. The return shape is not documented
in `prompt_docs.py` — only the function signature is listed. The model guesses a
simpler nested array structure and gets it wrong.

**Proposed fix:**
- Document the exact return shape of `getPredictedFundings()` in `prompt_docs.py`:
  ```
  getPredictedFundings() → [["BTC", [["BinPerp", {fundingRate, nextFundingTime, fundingIntervalHours}],
                                      ["HlPerp", {...}], ["BybitPerp", {...}]]], ...]
    fundingRate is a decimal string (e.g. "0.0001" = 0.01%). parseFloat() before math.
    To get Hyperliquid's own rate: find the entry where venue === "HlPerp".
  ```
- Also document `getFundingHistory()` return shape if not already done.
- Consider: should `perpMarket.js` transform this into a cleaner shape (like `perpUser.js`
  does for fills)? That would prevent this entire class of error.
- Add a lint check: `parseFloat` called on a value that could be a venue string.

---

## Issue 9: Model uses wrong funding interval for Hyperliquid

**Severity:** High (strategy logic error — missed carry, late exits)  
**Observed in:** `strategy5.json` (SOL funding carry, Feb 2026)

**Symptom:** The code sets `checkInterval = 2 * 60 * 60 * 1000` (2 hours) with the
comment "funding updates every 8h, no need for real-time monitoring." But the actual
API data shows Hyperliquid's own funding (`HlPerp`) settles every **1 hour**
(`fundingIntervalHours: 1`). Only Binance/Bybit use 4-8 hour intervals.

With a 2-hour check interval on a 1-hour funding cycle:
- The strategy could miss an entire funding settlement without reacting
- Entry could happen right after settlement (missing the carry for that period)
- Exit could be delayed by up to 2 hours after funding drops below threshold
- The strategy earns funding only while holding through settlement — checking less
  frequently than the settlement interval defeats the purpose of a carry trade

**Root cause:** The model assumes standard CEX funding intervals (8h) rather than
Hyperliquid's actual 1-hour cycle. This information is not in the prompt docs.

**Proposed fix:**
- Add to `prompt_docs.py` or `prompts.py` strategy reasoning: "Hyperliquid funding
  settles every 1 hour (not 8h like Binance/Bybit). For funding carry strategies,
  check at least every 30 minutes to react before the next settlement."
- The `getPredictedFundings` documentation should mention the `fundingIntervalHours`
  field and that it varies by venue (HlPerp = 1h, BinPerp/BybitPerp = 4-8h).

---

## Issue 10: Complex strategies produce bloated, slow-to-generate code

**Severity:** Medium (UX and quality)  
**Observed in:** `strategy6.json` (RSI+MACD composite with ATR sizing, Feb 2026)

**Symptom:** The generation took notably longer than simpler strategies. The resulting
code is ~300+ lines with massive duplication — the RSI and MACD manual calculation
code is copy-pasted identically in two branches of the monitor path. The model also
struggled with MACD correctness (omitted signal line entirely).

**Root cause:** When the model needs indicator values outside trigger callbacks (for
exit logic / monitoring), it has no choice but to reimplement them from scratch. This
is time-consuming for the model (complex math), error-prone (gets MACD wrong), and
produces bloated output. The more indicators involved, the worse it gets.

This is fundamentally the same root cause as Issue 1, but viewed from a UX angle:
the model's only option for "I need RSI and MACD values in my monitor loop" is to
reimplement both, leading to slow generation and code that's 2-3x longer than needed.

**Proposed fix:**
- Addressing Issue 1 (no manual indicator reimplementation) would also fix this.
  If the model stores trigger-provided values in `tradeState` and uses those for
  exit decisions, the monitor path becomes trivial — no candle fetching, no math,
  just read stored values and compare.
- Alternatively, exposing `TechnicalIndicatorService` (Issue 3 decision) would give
  the model a clean one-liner for any indicator, avoiding both the bloat and errors.

---

## Issue 11: Drop detection compares oldest vs newest, not peak vs current

**Severity:** High (logic error — misses real drops, triggers on false ones)  
**Observed in:** `strategy7.json` (HFT scalp, WS-driven, Feb 2026)

**Symptom:** The strategy monitors BTC price via WebSocket and looks for a 0.1% drop
within a 10-second window. The drop detection logic is:

```js
const oldest = this.priceHistory[0];
const newest = this.priceHistory[this.priceHistory.length - 1];
const priceChange = ((newest.price - oldest.price) / oldest.price) * 100;
if (priceChange <= -this.dropThresholdPct) { ... }
```

This compares **oldest price to newest price** in the rolling window. The correct
approach for "price drops X% in Y seconds" is to compare the **highest price** in
the window to the **current (newest) price**:

```js
const prices = this.priceHistory.map(p => p.price);
const high = Math.max(...prices);
const dropFromHigh = ((newest.price - high) / high) * 100;
if (dropFromHigh <= -this.dropThresholdPct) { ... }
```

Why this matters:
- **Misses real drops**: If price goes 100.0 → 100.1 → 99.9 over 10s, oldest→newest
  is only -0.1% from 100.0. But if it goes 100.0 → 100.2 → 99.8, the real drop from
  peak is -0.4% (highly significant), while oldest→newest is only -0.2%.
- **False triggers on slow drifts**: A slow decline from 100.0 → 99.9 over 10s would
  trigger (-0.1%), but that's not a "drop" — it's a gradual drift. A real drop means
  price was higher and then fell rapidly.

**Root cause:** The prompt doesn't provide guidance on velocity/drop detection patterns.
The model implements the simplest comparison (start→end of window) rather than the
correct one (peak→current within window).

**Proposed fix:**
- Add a reasoning example or pattern for "price velocity / drop detection" showing:
  `const high = Math.max(...window); const drop = (current - high) / high * 100;`
- Clarify in the thinking framework that "drops X% in Y seconds" means price falls
  from a local high, not just a start-to-end comparison.

---

## Issue 12: Scheduled trigger interval doesn't match strategy's monitoring frequency

**Severity:** Medium (poor code architecture, misleading status reports)  
**Observed in:** `strategy7.json` (HFT scalp, WS-driven, Feb 2026)

**Symptom:** The user specified "Enter when price drops 0.1% in under 10 seconds" and
"Keep running continuously." The model correctly uses WebSocket for real-time price
monitoring (sub-second), but the scheduled trigger for status updates is set to 60s:

```js
this.statusIntervalMs = 60000;  // Report every 60s when idle
```

The logs confirm exactly 60-second gaps between status updates:
- 20:11:13 → 20:12:13 → 20:13:13 → 20:14:14 → 20:15:13

From the user's perspective, this is confusing — they asked for monitoring "every 10
seconds" but see updates once per minute. While the WebSocket IS monitoring in real-time,
the user has no visibility into what's happening between status updates. The 10-second
price range shown in the 60s status report (`historyPoints: 10`) only reflects a
snapshot of the last 10 seconds before the report, not continuous monitoring data.

**Root cause:** The model conflates two things:
1. **Detection frequency** (WebSocket — continuous, correct)
2. **Reporting frequency** (scheduled trigger — 60s, too slow for an HFT strategy)

For a strategy that detects events in <10 seconds, the user expects to see confirmations
of activity at a similar granularity — at minimum every 10-15 seconds, ideally every
few seconds. 60-second status gaps make it look broken.

**Proposed fix:**
- Add guidance in the thinking framework's logging section: "Match your reporting
  interval to your strategy's time horizon. HFT/scalp strategies (sub-minute detection)
  should report every 5-15 seconds. Swing strategies can report every 1-5 minutes."
- Or better: use the WS callback itself to throttle status reports every N seconds,
  avoiding the overhead of a separate scheduled trigger for reporting.

---

## Issue 13: Direct `positionTracker` usage (repeat of Issue 4)

**Observed in:** `strategy7.json` — `this.positionTracker.getOpenPosition(this.coin)`
in external close detection. Appended to Issue 4.

---

## Issue 14: Model invents extra parameters for `checkSafetyLimits`

**Severity:** High (silent logic bug — safety check runs with wrong size)  
**Observed in:** `strategy8.json` (momentum rotation, Feb 2026)

**Symptom:** The code calls:
```js
const safetyCheck = await this.checkSafetyLimits(longCoin, true, longSize);
const safetyCheck = await this.checkSafetyLimits(shortCoin, false, shortSize);
```

The actual signature is `checkSafetyLimits(coin, proposedSize)` — only 2 arguments.
The `true`/`false` (intended as "isBuy" direction) gets interpreted as `proposedSize`,
converting to `1`/`0`. The actual size (`longSize`/`shortSize`) is silently ignored
as an extra argument.

Consequences:
- `checkSafetyLimits(coin, true)` → `proposedSize = 1` (meaningless)
- `checkSafetyLimits(coin, false)` → `proposedSize = 0` (even more meaningless)
- The daily PnL tracking that uses `proposedSize` will be based on these wrong values
- Safety limits effectively don't work — they'll never trigger on the real trade size

**Root cause:** The model assumes `checkSafetyLimits` has a direction parameter (like
`placeMarketOrder(coin, isBuy, size, ...)`). The prompt docs show the correct 2-arg
signature, but the model pattern-matches against other APIs that have a buy/sell boolean.

**Proposed fix:**
- Add a lint check in `code_generator.py` that matches `checkSafetyLimits(` calls and
  validates argument count (should be exactly 2: coin, size).
- Add explicit note in `prompt_docs.py`: "checkSafetyLimits takes (coin, size) — there
  is NO direction parameter. It checks daily loss limits, not directional exposure."
- Consider adding to the validation prompt: "checkSafetyLimits(coin, proposedSize) — do
  NOT pass a boolean direction flag; this function only takes coin and numeric size."

---

## Issue 15: Multi-coin strategy doesn't consider same-coin conflicts in rotation

**Severity:** Low (edge case, unlikely to cause issues in practice)  
**Observed in:** `strategy8.json` (momentum rotation, Feb 2026)

**Symptom:** The strategy holds one LONG and one SHORT simultaneously across a pool of
4 coins. The rotation logic closes old positions and opens new ones. However, the code
doesn't guard against the case where the strongest and weakest coins are the same — for
example, if only 2 coins return valid ticker data and one is the same as the current
long/short, the close-then-open sequence could conflict.

More importantly, the close logic uses `trackedPositions` captured at the TOP of
`executeTrade`. After closing the LONG position, this stale snapshot is used to find the
SHORT position's data. If both positions were on related coins and the close affected
the tracker, the stale data could be subtly wrong.

In practice, with 4 coins and `sort()` + index 0 vs last, strongest != weakest unless
`momentumData.length === 1` (guarded by the `< 2` check). So this is mostly theoretical.

**Root cause:** No explicit guard against strongest === weakest, and stale position
snapshot after partial rotation.

**Proposed fix:**
- Add a reasoning example in the thinking framework: "For rotation strategies, always
  verify your new long != your new short before opening. Re-fetch tracked positions after
  closing old ones if the close could affect subsequent logic."

---

## Issue 16: Margin math is backwards in init logging

**Severity:** Low (cosmetic — doesn't affect trading logic)  
**Observed in:** `strategy8.json` (momentum rotation, Feb 2026)

**Symptom:** The init message says:
```
$10 per position at 5x leverage ($2.00 margin each, $4.00 total)
```

The code calculates `marginPerPosition = tradeAmountUsd / leverage = 10 / 5 = $2`.
But "$10 per position" already means $10 notional. With 5x leverage, $10 notional
requires $2 margin. This is correct — the math is fine.

However, the user said "$10 per position, 5x leverage" which could mean either:
- $10 notional, 5x leverage → $2 margin (code's interpretation)
- $10 margin, 5x leverage → $50 notional (the more common user intent)

The prompt's thinking framework has guidance on this ("margin" vs "notional"), but the
model chose the more conservative interpretation. Not necessarily wrong, but worth noting
that a user saying "$10 per position" at "5x leverage" likely means $10 margin = $50
notional exposure, which would be a more meaningful trade.

**Root cause:** Ambiguous user prompt. The model defaulted to notional interpretation.

**Proposed fix:** No prompt change needed — the thinking framework already covers this
distinction. This is more of an observation about ambiguity handling.

---

## Issue 17: No take-profit for a momentum rotation strategy

**Severity:** Medium (design flaw — asymmetric risk management)  
**Observed in:** `strategy8.json` (momentum rotation, Feb 2026)

**Symptom:** The strategy places stop-losses (10% ROI) but NO take-profits. The only
exit mechanism besides SL is the 5-minute rotation cycle — if rankings change, the
position is closed via market order. This means:

1. **Unbounded winner risk:** If a position moves heavily in favor between cycles, the
   unrealized gain is exposed to reversal for up to 5 minutes before the next check.
2. **Asymmetric risk:** Losses are capped at 10% ROI (SL), but gains have no protection
   until the next rebalance cycle. A flash crash that reverses could wipe gains.
3. **Missing the point of momentum rotation:** In a pairs strategy, you WANT to hold
   winners and cut losers. SL-only is appropriate IF the rebalance interval is short
   enough. At 5 minutes, it's borderline acceptable.

The user prompt didn't specify TP, so this is technically correct per the prompt. But a
well-designed rotation strategy should at minimum consider a trailing stop or TP.

**Root cause:** The model followed the prompt literally (no TP specified → no TP placed).
The thinking framework's exit section says "If user doesn't specify exit: default to
7-8% SL, 10% TP" — but the model only applied SL, not the default TP.

**Proposed fix:**
- The default exit guidance should be clearer: "If user specifies SL but not TP, still
  apply a default TP. If neither is specified, apply both defaults."

---

## Issue 18: No fee awareness in rotation strategy

**Severity:** Medium (real profitability concern)  
**Observed in:** `strategy8.json` (momentum rotation, Feb 2026)

**Symptom:** The strategy rotates positions every 5 minutes — closing and reopening
whenever rankings change. Each rotation involves up to 4 market orders (close long,
close short, open new long, open new short). At taker fee rates:

- $10 notional per position → ~$0.0025 per order → ~$0.01 per full rotation
- If rankings change every cycle (volatile markets), that's $0.01 every 5 minutes
  = $0.12/hour = $2.88/day in fees alone
- With $10 notional positions at 5x leverage ($2 margin), the daily fee burn of
  $2.88 exceeds the total margin deployed ($4)

The code does track `totalFees` per rotation in the reporting, which is good. But there
is no pre-trade fee viability check (unlike strategy7 which had excellent fee awareness).
The model doesn't warn the user that frequent rotation at $10 notional is likely
unprofitable after fees.

**Root cause:** The prompt encourages fee awareness for explicit scalping strategies but
doesn't emphasize it for rotation/rebalancing strategies where cumulative fees are the
main cost driver.

**Proposed fix:**
- Add a reasoning example: "For rebalancing/rotation strategies, calculate the DAILY
  fee burn assuming worst-case rotation frequency. If daily fees exceed a significant
  portion of expected daily returns, warn the user or increase the rebalance interval."

---

## Pending: Few-shot examples

All of the above will be easier to address with concrete few-shot examples showing
correct patterns. The few-shot system is being designed separately. When ready, the
examples should demonstrate:
1. Correct use of `registerTechnicalTrigger` for all signal detection (including
   `crossover`/`crossunder` for two-series comparisons like EMA 9/21)
2. Storing trigger-provided indicator values in `tradeState` for later use
3. Monitor/heartbeat patterns that report stored state, not recomputed indicators
4. Proper RSI reset detection using stored values
5. External close detection using `this.getTrackedOpenPositions()` wrappers (not direct)
6. Correct sizing, fee estimation, and SL/TP placement
7. Only using documented APIs — no `this.logger`, no invented methods
8. Correct `await` on all async calls, especially in non-obvious places like
   `checkSafetyLimits` and `logTrade`
9. Composite trigger strategy showing clean exit logic using stored values from
   triggerData instead of reimplementing indicator math
10. Proper MACD usage — showing that MACD histogram = MACD line - signal line, and
    the trigger system handles this correctly, so never recompute manually
11. Concise monitor patterns — status reports using stored state, not 50-line candle
    fetch + indicator recomputation blocks
12. Correct price drop/velocity detection using peak-to-current within a rolling
    window, not oldest-to-newest
13. Appropriate status reporting frequency matching the strategy's time horizon
    (HFT = every 5-15s, swing = every 1-5 min)
14. Correct `checkSafetyLimits(coin, size)` usage — no direction boolean
15. Multi-coin rotation showing fee-aware rebalancing with both SL and default TP
