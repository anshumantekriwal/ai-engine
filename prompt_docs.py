"""Documentation constants for prompt assembly — compressed for token efficiency."""

# ============================================================================
# OrderExecutor — accessed via this.orderExecutor
# ============================================================================

ORDER_EXECUTOR_DOCS = """
OrderExecutor Class (pre-initialized as `this.orderExecutor`):

Uses Hyperliquid API Wallet system. Main user address for queries, API wallet for signing.
Already initialized — just call the methods.

### CRITICAL: Multi-Agent Sandboxing

Multiple agents may share the SAME Hyperliquid account. The exchange sees ONE account with ONE position
per coin. Your agent MUST NOT interfere with other agents:

- **Positions are account-wide.** `getPositions("BTC")` returns the account's TOTAL BTC position, which
  may include size from OTHER agents. Never assume the entire position belongs to you.
- **Use `closePosition(coin, size)` with an explicit `size` for partial closes.** Never call
  `closePosition(coin)` (full close) unless your strategy truly owns the entire position. Track your
  own entry size and close exactly that amount.
- **Use `cancelAgentOrders(coin)` instead of `cancelAllOrders(coin)`.** `cancelAllOrders` cancels
  EVERY open order for that coin on the account (including other agents' SL/TP orders).
  `cancelAgentOrders` only cancels orders placed by THIS agent.
- **Track your own positions locally** using `this.tradeState` or similar. Don't rely solely on
  `getPositions()` to know your exposure — it's the whole account.

### Order Placement Methods

1. placeMarketOrder(coin, isBuy, size, reduceOnly=false, slippage=0.05)
   - coin: string, isBuy: boolean, size: number (base currency), reduceOnly: boolean, slippage: number (default 5%)
   - Returns OrderResult: { success, orderId, filledSize, averagePrice, status, error, fee, feeRate, feeType }
   - On success (filled): success=true, status="filled", filledSize and averagePrice populated.
   - On success (resting/open): success=true, status="open", filledSize/averagePrice may be null.
   - On failure: success=false, error contains reason. filledSize/averagePrice are null.
   - ALWAYS check result.success AND result.status before using fill data:
     ```
     const result = await this.orderExecutor.placeMarketOrder("BTC", true, 0.01);
     if (result.success) {
       const filled = result.filledSize || size;  // fallback if resting
       const price = result.averagePrice || currentPrice;  // fallback
     }
     ```

2. placeLimitOrder(coin, isBuy, size, price, reduceOnly=false, postOnly=false, timeInForce="Gtc")
   - timeInForce: "Gtc" (Good-Til-Canceled), "Ioc" (Immediate-Or-Cancel), "Alo" (Add-Liquidity-Only)
   - Returns: same OrderResult shape.

3. placeStopLoss(coin, isBuy, size, triggerPrice, limitPrice=null, reduceOnly=true)
   - isBuy is the DIRECTION OF THE CLOSE ORDER, not your position direction.
   - To protect a LONG position: isBuy=FALSE (you sell to close). triggerPrice = below entry.
   - To protect a SHORT position: isBuy=TRUE (you buy to close). triggerPrice = above entry.
   - limitPrice null = auto 3% slippage from triggerPrice.
   - Example (protect long): `await this.orderExecutor.placeStopLoss("BTC", false, 0.1, 40000);`
   - Example (protect short): `await this.orderExecutor.placeStopLoss("BTC", true, 0.1, 50000);`

4. placeTakeProfit(coin, isBuy, size, triggerPrice, limitPrice=null, reduceOnly=true)
   - Same isBuy logic as placeStopLoss: isBuy is the close direction.
   - To take profit on LONG: isBuy=FALSE (sell to close). triggerPrice = above entry.
   - To take profit on SHORT: isBuy=TRUE (buy to close). triggerPrice = below entry.
   - limitPrice null = auto 1% slippage from triggerPrice.
   - Example (TP long): `await this.orderExecutor.placeTakeProfit("BTC", false, 0.1, 50000);`
   - Example (TP short): `await this.orderExecutor.placeTakeProfit("BTC", true, 0.1, 40000);`

   Quick reference for SL/TP isBuy:
   | Position | SL isBuy | TP isBuy |
   |----------|----------|----------|
   | Long     | false    | false    |
   | Short    | true     | true     |

5. placeTrailingStop(coin, isBuy, size, trailPercent, reduceOnly=true)
   - Same isBuy logic: false for trailing stop on longs, true for shorts.
   - trailPercent: e.g., 5 = 5% trailing distance from peak/trough.

6. closePosition(coin, size=null, slippage=0.05)
   - Closes a position via market order. Automatically determines buy/sell direction.
   - size=null: closes ENTIRE position. size=number: partial close (clamped to position size).
   - Returns same OrderResult: { success, orderId, filledSize, averagePrice, status, error }
   - NOTE: Does NOT have a `realizedPnl` field. To get PnL, calculate from entry/exit prices.
   - Returns { success: false, error: "No open position for {coin}" } if no position exists.
   - **IMPORTANT (Sandboxing):** In multi-agent setups, ALWAYS pass your tracked size explicitly to
     avoid closing another agent's portion of the position:
     ```
     // GOOD: Close only what this agent opened
     const mySize = this.tradeState[coin].entrySize;
     await this.orderExecutor.closePosition(coin, mySize);

     // BAD: Closes the ENTIRE account position (may include other agents)
     await this.orderExecutor.closePosition(coin);
     ```
   - Examples:
     ```
     await this.orderExecutor.closePosition("BTC", 0.005);        // partial close 0.005 BTC
     await this.orderExecutor.closePosition("ETH", null, 0.02);   // full close, 2% slippage
     await this.orderExecutor.closePosition("BTC", myTrackedSize); // close exactly your size
     ```

7. cancelOrder(coin, orderId) — orderId must be number

8. cancelAgentOrders(coin=null) — **PREFERRED for multi-agent.** Only cancels orders placed by THIS agent.
   - Uses local ownership tracking. Safe on shared accounts.
   - coin=null cancels all owned orders across all coins.
   - Returns OrderResult with status "all_owned_orders_cancelled" or "no_owned_orders_to_cancel".

9. cancelAllOrders(coin) — **WARNING: Account-wide.** Cancels ALL open orders for the coin, including
   other agents' SL/TP orders. Use `cancelAgentOrders()` instead unless you intend to nuke everything.

### Leverage & Query Methods

10. setLeverage(coin, leverage, isCross=true)
   - Auto-capped at coin's max allowed leverage. Call in onInitialize() BEFORE orders.
   - Default 20x if not set. isCross=true for cross margin, false for isolated.

11. getPositions(coin=null)
    - Returns: Position[] — { coin, size, entryPrice, unrealizedPnl, realizedPnl, leverage, liquidationPrice, marginUsed }
    - size: positive = long, negative = short. Positions with size=0 are filtered out.
    - Returns EMPTY ARRAY [] if no position exists (not [{size:0}]).
    - coin=null returns all positions.
    - ALWAYS check array length before accessing:
      ```
      const positions = await this.orderExecutor.getPositions("BTC");
      if (positions.length > 0) {
        const pos = positions[0];
        // pos.size, pos.entryPrice, etc.
      }
      ```

12. getAccountValue() — Returns total account value in USD (number).

13. getAvailableBalance() — Returns available balance not in positions (number).

14. getOpenOrders(coin=null)
    - Returns: OpenOrder[] — { orderId, coin, side, size, price, orderType, reduceOnly, timestamp }

15. getMaxTradeSizes(coin) — Returns { maxLong, maxShort } based on balance and current leverage.

16. getMaxLeverage(coin) — Returns max leverage from exchange metadata (e.g., 50 for BTC).

### Critical Usage Rules

- ALWAYS check `result.success` before accessing fill data.
- Position sizes auto-rounded to valid decimals per coin. Prices rounded to 5 sig figs AND max (6-szDecimals) decimal places.
- Rate limiting handled automatically with exponential backoff.
- reduceOnly=true means order can ONLY close/reduce, not open.
- Positive size = long, negative = short.
- ALWAYS call syncPositions() after trades.
- ALWAYS set leverage BEFORE opening positions (defaults to 20x otherwise).
"""

# ============================================================================
# WebSocket Manager — accessed via this.wsManager
# ============================================================================

WEBSOCKET_MANAGER_DOCS = """
HyperliquidWSManager (pre-initialized as `this.wsManager`):

Auto-reconnection, auto-resubscription, message queuing when down. Already connected at agent start.

### Subscribe Methods

1. subscribeAllMids(callback)
   - Callback receives: { mids: { "BTC": "90518.5", "ETH": "3117.45", ... } }
   - Note: prices nested inside `mids` key, all as STRINGS. Use parseFloat().

2. subscribeL2Book(coin, callback)
   - Callback: { coin, time, levels: [[{px,sz,n},...], [{px,sz,n},...]] } — levels[0]=bids, levels[1]=asks
   - All values are strings.

3. subscribeTrades(coin, callback)
   - Callback: WsTrade[] — { coin, side: "B"|"A", px, sz, time, hash, tid }
   - side "B"=Buy(taker bought), "A"=Sell(taker sold). All values strings except tid.

4. subscribeUserEvents(callback)
   - Callback receives ONE of: { fills: [WsFill,...] } | { funding: WsUserFunding } | { liquidation: WsLiquidation } | { nonUserCancel: [WsNonUserCancel,...] }
   - WsFill: { coin, px, sz, side:"B"|"A", time, startPosition, dir, closedPnl, hash, oid, crossed, fee, tid, feeToken }
   - WsUserFunding: { time, coin, usdc, szi, fundingRate }
   - WsNonUserCancel: { coin, oid }
   - All numeric values are STRINGS — use parseFloat().

5. subscribeLiquidations(callback)
   - Callback: [{ liq, coin, side:"A"|"B", px, sz, time },...] — "A"=long liq, "B"=short liq

### Unsubscribe Methods
unsubscribeAllMids(), unsubscribeL2Book(coin), unsubscribeTrades(coin), unsubscribeUserEvents(), unsubscribeLiquidations(), close()

### Key Rules
- Callbacks fire on EVERY update (can be very frequent).
- ALL price/size data = STRINGS. Always parseFloat() before math.
- Use in setupTriggers() or onInitialize() for real-time data feeds.
"""

# ============================================================================
# perpMarket.js — module-scoped helpers (call directly, no import needed)
# ============================================================================

PERP_MARKET_DOCS = """
perpMarket.js — Market Data Helpers (call directly, e.g., `await getAllMids()`):

1. getAllMids(dex="")
   - Returns: { "BTC": "90518.5", "ETH": "3117.45", ... } — all prices as strings.

2. getCandleSnapshot(coin, interval, startTime, endTime)
   - interval: "1m","3m","5m","15m","30m","1h","2h","4h","8h","12h","1d","3d","1w","1M"
   - startTime/endTime: milliseconds
   - Returns: Candle[] sorted ascending — { timestampOpen, timestampClose, open, high, low, close, volume, trades, symbol, interval }
   - Example:
     ```
     const now = Date.now();
     const candles = await getCandleSnapshot("BTC", "1h", now - 24*60*60*1000, now);
     const closes = candles.map(c => c.close);
     ```

3. getTicker(coin)
   - Returns: { coin, price, open, high, low, volume, change, change_percent }

4. getL2Book(coin, nSigFigs=5)
   - Returns: { coin, time, bids: [{price,size,n},...], asks: [{price,size,n},...] }
   - Bids descending (best first), asks ascending (best first). Values are numbers.

5. getFundingHistory(coin, startTime, endTime=Date.now())
   - Returns: [{ timestamp (NOT "time"), fundingRate, premium },...] sorted ascending. Numbers, not strings.

6. getMetaAndAssetCtxs()
   - Returns: { meta: { universe, marginTables, collateralToken }, assetCtxs: [{ funding, openInterest, prevDayPx, dayNtlVlm, premium, oraclePx, markPx, midPx, impactPxs, dayBaseVlm },...] }
   - One assetCtx per coin in universe. Some values are strings, some numbers.

7. getRecentTrades(coin)
   - Returns: [{ timestamp, price, size, side:"Buy"|"Sell", hash },...] — up to 500, descending.
   - NOTE: fields are `price`, `size`, `timestamp` (NOT px/sz/time). Side is converted from "B"/"A".

8. getPredictedFundings()
   - Returns: [["BTC", [[funding_arrays]]], ["ETH", [...]], ...] — raw API response.

9. getPerpsAtOpenInterestCap()
   - Returns: string[] — coin symbols at their OI cap.

### Key Rules
- All async — always await.
- Timestamps in milliseconds.
- Use getAllMids() for quick prices, getCandleSnapshot() for indicator calculations.
"""

# ============================================================================
# perpUser.js — module-scoped helpers (call directly, no import needed)
# ============================================================================

PERP_USER_DOCS = """
perpUser.js — User Data Helpers (call directly, use `this.userAddress` for user param):

1. getOpenOrders(user, dex="")
   - Returns: [{ oid, coin, side:"Buy"|"Sell", limitPx, sz, timestamp },...] sorted by time desc.

2. getFrontendOpenOrders(user, dex="")
   - Same as above but includes: isTrigger (boolean), triggerPx (number|null).

3. getUserFills(user, aggregateByTime=false)
   - Returns: [{ coin, px, sz, side:"Buy"|"Sell", time, fee, closedPnl, oid, hash },...] — up to 2000, newest first.

4. getUserFillsByTime(user, startTime, endTime=Date.now(), aggregateByTime=false)
   - Same format as getUserFills(). Max 2000 per response, only 10000 most recent available.

5. getHistoricalOrders(user)
   - Returns: [{ oid, coin, side, limitPx, sz, status:"open"|"filled"|"canceled"|"rejected", timestamp },...] — up to 2000.

6. getPortfolio(user)
   - Returns: [["day", { accountValueHistory, pnlHistory, vlm }], ["week",...], ["month",...], ["allTime",...], ["perpDay",...], ...] 
   - NOTE: Returns HISTORY, not current positions. Use orderExecutor.getPositions() for current.

7. getSubAccounts(user) — Returns balances/margin info or null.

8. getUserFees(user)
   - Returns: { userCrossRate (taker), userAddRate (maker), feeSchedule, dailyUserVlm, ... }
   - Rates are strings like "0.00045".

### Key Rules
- All require user address (use `this.userAddress`).
- Most numeric values returned as strings — use parseFloat().
- Side conversion is automatic: "B"->"Buy", "A"->"Sell".
- These are HTTP requests, not real-time (use WebSocket for real-time).
"""

# ============================================================================
# BaseAgent — the class your code extends
# ============================================================================

BASE_AGENT_DOCS = """
BaseAgent Class (your code runs inside this):

### Pre-initialized Properties
- `this.agentId` (string): UUID for this agent in Supabase
- `this.userId` (string): Owner user ID
- `this.privateKey` (string): Hyperliquid API wallet key (0x-prefixed)
- `this.userAddress` (string): User's main Hyperliquid address (0x-prefixed)
- `this.isMainnet` (boolean): Network flag
- `this.orderExecutor` (OrderExecutor): Trading operations (sandbox-aware, tracks order ownership)
- `this.wsManager` (HyperliquidWSManager): WebSocket data streams
- `this.supabase` (SupabaseClient): Database (rarely needed directly)
- `this.currentState` (string): 'initializing'|'running'|'stopped'|'error'
- `this.isRunning` / `this.isPaused` (boolean)
- `this.maxPositionSize`, `this.maxLeverage`, `this.dailyLossLimit` (number, default 100 USD)

### State Management

updateState(stateType, stateData, message)
  - stateType: string (e.g., 'init', 'order_executed', 'error', 'skip_duplicate', 'external_close',
    'cycle_summary', 'no_action', 'trigger_check')
  - stateData: object (JSONB, stored in Supabase)
  - message: string — **THIS IS THE AGENT'S ONLY WAY TO COMMUNICATE WITH THE USER.** The user sees
    ONLY these messages in their dashboard. Every message must be a complete, natural-language sentence
    explaining WHAT happened, WHY, and WHAT COMES NEXT.
    Good: "BTC LONG: 0.001 BTC @ $95,230 (5x lev, RSI=28.5, SL=$93,417 TP=$97,148)"
    Good: "Checked all triggers — no conditions met. BTC RSI=45.2 (need <30), ETH RSI=52.1 (need <30). Will check again in 5 minutes."
    Good: "Skipped BTC buy — already have an active position from this RSI excursion (entered @ $94,100). Waiting for RSI to reset above 50."
    Bad: "order executed"
    Bad: "no action"
    Bad: "checking..."
  - **MANDATORY:** Call updateState at EVERY decision point, including when nothing happens. The user
    must never wonder "is my agent still working?" Silence = anxiety. Regular heartbeat updates
    build trust.

syncPositions()
  - Fetches ALL current positions from Hyperliquid and upserts to `agent_positions` table.
  - Also REMOVES positions from the database that no longer exist on the exchange.
  - Call after every trade (entry or exit) to keep database in sync.

logTrade(tradeData)
  - tradeData: { coin, side:'buy'|'sell', size, price?, order_type?, order_id?, trigger_reason?, is_entry?, is_exit? }
  - is_entry/is_exit auto-inference (if both are undefined):
    * order_type='close_position' OR opposite side to existing position -> is_exit=true
    * No existing position -> is_entry=true
    * Same side, existing position (adding) -> is_entry=true
  - You CAN set is_entry/is_exit explicitly for clarity, but it's not required.
  - Fees auto-calculated from order type.
  - Returns: { positionId, pnl, fee, feeRate } or null on error.

updateMetrics() — Called automatically. Computes total PnL, trade count, win rate, account value.

### Trigger Methods — triggerData Shapes

Each trigger type passes a specific triggerData object to the callback. You can add extra fields
when forwarding to executeTrade: `await this.executeTrade({ ...triggerData, action: 'buy', coin: 'BTC' })`.

registerPriceTrigger(coin, condition, callback)
  - condition: { above: number } or { below: number } or { crosses: number }
  - Evaluated ~every 1s. Returns triggerId.
  - triggerData passed to callback: { type: 'price', coin, price (number), condition, triggerId }

registerTechnicalTrigger(coin, indicator, params, condition, callback)
  - indicator: 'RSI'|'EMA'|'SMA'|'MACD'|'BollingerBands' (ONLY these five)
  - params per indicator:
    RSI: { period (default 14), interval }
    EMA: { period (default 20), interval }
    SMA: { period (default 20), interval }
    MACD: { fastPeriod (default 12), slowPeriod (default 26), signalPeriod (default 9), interval }
    BollingerBands: { period (default 20), stdDev (default 2), interval }
  - condition: ONLY { above: N } or { below: N }. For MACD/BB add checkField:
    MACD fields: 'MACD', 'signal', 'histogram' — e.g., { checkField: 'histogram', above: 0 }
    BB fields: 'upper', 'middle', 'lower' — e.g., { checkField: 'lower', below: 85000 }
  - DO NOT invent conditions. Only above/below/checkField recognized. Others silently ignored and the trigger NEVER fires.
  - CANNOT compare two indicators or detect crossovers. Use scheduledTrigger for that.
  - Rate-limited: evaluated once per 60s. Needs >= 20 candles of data.
  - Returns triggerId.
  - triggerData passed to callback: { type: 'technical', coin, indicator, value, condition, triggerId }
    * value for RSI/EMA/SMA: number
    * value for MACD: { MACD: number, signal: number, histogram: number }
    * value for BollingerBands: { upper: number, middle: number, lower: number }

registerScheduledTrigger(intervalMs, callback)
  - Fires at fixed intervals. Use for crossover/multi-indicator logic.
  - triggerData: { type: 'scheduled', timestamp (ms), triggerId }

registerEventTrigger(eventType, condition, callback)
  - eventType: 'liquidation'|'largeTrade'|'userFill'
  - condition: { minSize } for liquidation, { coin, minSize } for largeTrade, {} for userFill
  - triggerData: { type: eventType, data (raw event object), triggerId }

removeTrigger(triggerId)

### Safety & Lifecycle

checkSafetyLimits(coin, proposedSize)
  - Checks: (1) proposedSize <= maxPositionSize (default 10000), (2) today's PnL >= -dailyLossLimit (default $100)
  - Returns: { allowed: boolean, reason: string }
  - If allowed: reason = 'OK'. If blocked: reason explains why (e.g., "Daily loss limit reached: -$105.23 USD").

start() — Calls onInitialize(), setupTriggers(), starts monitor loop.
monitor() — Evaluates triggers continuously.
pause() / resume() — Pause/resume trigger evaluation.
shutdown() — Stops loop, cancels orders, optionally closes positions, syncs final state.
"""
