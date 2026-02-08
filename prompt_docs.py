"""Documentation constants for prompt assembly."""

# ============================================================================
# SYSTEM PROMPT - Unified Agent Code Generator
# ============================================================================

ORDER_EXECUTOR_DOCS = """

OrderExecutor Class:

The OrderExecutor handles ALL trading operations on Hyperliquid. It is pre-initialized in BaseAgent as `this.orderExecutor`.

**CRITICAL ARCHITECTURE NOTE:**
- Uses Hyperliquid API Wallet system (0x-prefixed keys)
- Main user address: For ALL queries (balance, positions, orders)
- API wallet (from privateKey): ONLY for signing transactions
- Already initialized in BaseAgent - you just call the methods

Available Methods:

1. placeMarketOrder(coin, isBuy, size, reduceOnly=false, slippage=0.05)
   /**
    * Place a market order with immediate execution and slippage protection
    * 
    * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
    * @param {boolean} isBuy - true for buy, false for sell
    * @param {number} size - Order size in base currency
    * @param {boolean} reduceOnly - Only reduce existing position (default: false)
    * @param {number} slippage - Max slippage tolerance (default: 0.05 = 5%)
    * @returns {Promise<OrderResult>} { success, orderId, filledSize, averagePrice, status, error }
    * 
    * @example
    * const result = await this.orderExecutor.placeMarketOrder("BTC", true, 0.01);
    * if (result.success) {
    *   console.log(`Filled ${result.filledSize} BTC at $${result.averagePrice}`);
    * }
    */

2. placeLimitOrder(coin, isBuy, size, price, reduceOnly=false, postOnly=false, timeInForce="Gtc")
   /**
    * Place a limit order at a specific price
    * 
    * @param {string} coin - Coin symbol
    * @param {boolean} isBuy - true for buy, false for sell
    * @param {number} size - Order size
    * @param {number} price - Limit price
    * @param {boolean} reduceOnly - Only reduce position (default: false)
    * @param {boolean} postOnly - Post-only (maker-only) order (default: false)
    * @param {string} timeInForce - "Gtc" (Good-Til-Canceled), "Ioc" (Immediate-Or-Cancel), "Alo" (Add-Liquidity-Only)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * const result = await this.orderExecutor.placeLimitOrder("ETH", true, 0.1, 2000.0);
    */

3. placeStopLoss(coin, isBuy, size, triggerPrice, limitPrice=null, reduceOnly=true)
   /**
    * Place a stop-loss order (triggers when price reaches trigger level)
    * 
    * @param {string} coin - Coin symbol
    * @param {boolean} isBuy - true for buy stop, false for sell stop
    * @param {number} size - Order size
    * @param {number} triggerPrice - Price to trigger at
    * @param {number|null} limitPrice - Limit price after trigger (null = auto-calculate with 3% slippage)
    * @param {boolean} reduceOnly - Only reduce position (default: true)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * // Protect long position: sell if BTC drops to $40k
    * const result = await this.orderExecutor.placeStopLoss("BTC", false, 0.1, 40000);
    */

4. placeTakeProfit(coin, isBuy, size, triggerPrice, limitPrice=null, reduceOnly=true)
   /**
    * Place a take-profit order
    * 
    * @param {string} coin - Coin symbol
    * @param {boolean} isBuy - true for buy, false for sell
    * @param {number} size - Order size
    * @param {number} triggerPrice - Price to trigger at
    * @param {number|null} limitPrice - Limit price after trigger (null = auto-calculate with 1% slippage)
    * @param {boolean} reduceOnly - Only reduce position (default: true)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * // Take profit on long: sell if BTC rises to $50k
    * const result = await this.orderExecutor.placeTakeProfit("BTC", false, 0.1, 50000);
    */

5. placeTrailingStop(coin, isBuy, size, trailPercent, reduceOnly=true)
   /**
    * Place a trailing stop order (dynamically follows price)
    * 
    * @param {string} coin - Coin symbol
    * @param {boolean} isBuy - true for buy trailing stop, false for sell trailing stop
    * @param {number} size - Order size
    * @param {number} trailPercent - Trail percentage (e.g., 5 = 5% trailing distance)
    * @param {boolean} reduceOnly - Only reduce position (default: true)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * // Protect long position with 5% trailing stop (triggers if price drops 5% from peak)
    * await this.orderExecutor.placeTrailingStop("BTC", false, 0.1, 5);
    */

6. closePosition(coin, slippage=0.05)
   /**
    * Close entire position for a coin (market order)
    * 
    * @param {string} coin - Coin symbol
    * @param {number} slippage - Max slippage tolerance (default: 0.05 = 5%)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * const result = await this.orderExecutor.closePosition("BTC");
    * if (result.success) {
    *   console.log(`Position closed, realized PnL: $${result.realizedPnl}`);
    * }
    */

7. cancelOrder(coin, orderId)
   /**
    * Cancel a specific open order
    * 
    * @param {string} coin - Coin symbol
    * @param {number} orderId - Order ID to cancel (must be a number, use parseInt() if needed)
    * @returns {Promise<OrderResult>}
    * 
    * @example
    * const result = await this.orderExecutor.cancelOrder("BTC", 12345);
    * 
    * @example
    * // When orderId comes as a string, convert it first
    * const result = await this.orderExecutor.cancelOrder("BTC", parseInt(order.orderId));
    */

8. cancelAllOrders(coin)
   /**
    * Cancel all open orders for a specific coin
    * 
    * @param {string} coin - Coin symbol (e.g., "BTC", "ETH") - REQUIRED
    * @returns {Promise<OrderResult>}
    * 
    * NOTE: A coin must be specified. To cancel orders for ALL coins, loop through each coin:
    * 
    * @example
    * await this.orderExecutor.cancelAllOrders("BTC"); // Cancel all BTC orders
    * 
    * @example
    * // Cancel orders for multiple coins
    * const coins = ["BTC", "ETH", "SOL"];
    * for (const coin of coins) {
    *   await this.orderExecutor.cancelAllOrders(coin);
    * }
    */

9. setLeverage(coin, leverage, isCross=true)
   /**
    * Set leverage for a specific coin. Automatically capped at the coin's maximum allowed leverage
    * from exchange metadata — if you request 50x but the coin only allows 20x, it silently caps to 20x.
    * 
    * @param {string} coin - Coin symbol
    * @param {number} leverage - Desired leverage (will be capped at coin's max)
    * @param {boolean} isCross - true for cross margin, false for isolated margin (default: true)
    * @returns {Promise<boolean>} true if successful, false otherwise
    * 
    * @example
    * await this.orderExecutor.setLeverage("BTC", 5); // 5x cross margin
    * await this.orderExecutor.setLeverage("ETH", 10, true); // 10x cross margin
    * await this.orderExecutor.setLeverage("SOL", 3, false); // 3x isolated margin
    */

Position & Account Query Methods:

10. getPositions(coin=null)
    /**
     * Get all open positions (or specific coin's position)
     * 
     * @param {string|null} coin - Coin symbol (null = get all positions)
     * @returns {Promise<Position[]>} Array of Position objects
     * 
     * Position object structure:
     * {
     *   coin: string,
     *   size: number,              // Positive = long, Negative = short
     *   entryPrice: number,
     *   unrealizedPnl: number,
     *   realizedPnl: number,
     *   leverage: number,
     *   liquidationPrice: number,
     *   marginUsed: number
     * }
     * 
     * @example
     * const positions = await this.orderExecutor.getPositions();
     * for (const pos of positions) {
     *   console.log(`${pos.coin}: ${pos.size} @ $${pos.entryPrice}, PnL: $${pos.unrealizedPnl}`);
     * }
     * 
     * @example
     * const btcPositions = await this.orderExecutor.getPositions("BTC");
     * if (btcPositions.length > 0) {
     *   const pos = btcPositions[0];
     *   console.log(`BTC position: ${pos.size}, unrealized PnL: $${pos.unrealizedPnl}`);
     * }
     */

11. getAccountValue()
    /**
     * Get total account value in USD
     * 
     * @returns {Promise<number>} Account value in USD
     * 
     * @example
     * const value = await this.orderExecutor.getAccountValue();
     * console.log(`Account value: $${value.toFixed(2)}`);
     */

12. getAvailableBalance()
    /**
     * Get available balance (not used in positions)
     * 
     * @returns {Promise<number>} Available balance in USD
     * 
     * @example
     * const balance = await this.orderExecutor.getAvailableBalance();
     * console.log(`Available: $${balance.toFixed(2)}`);
     */

13. getOpenOrders(coin=null)
    /**
     * Get all open orders
     * 
     * @param {string|null} coin - Coin symbol (null = all coins)
     * @returns {Promise<OpenOrder[]>} Array of open orders
     * 
     * OpenOrder structure:
     * {
     *   orderId: string,
     *   coin: string,
     *   side: "buy" | "sell",
     *   size: number,
     *   price: number,
     *   orderType: string,
     *   reduceOnly: boolean,
     *   timestamp: number
     * }
     * 
     * @example
     * const orders = await this.orderExecutor.getOpenOrders("BTC");
     * console.log(`${orders.length} open BTC orders`);
     */

14. getMaxTradeSizes(coin)
    /**
     * Get maximum trade sizes based on available balance and current leverage (capped at coin's max).
     * 
     * @param {string} coin - Coin symbol
     * @returns {Promise<Object>} { maxLong: number, maxShort: number }
     * 
     * @example
     * const { maxLong, maxShort } = await this.orderExecutor.getMaxTradeSizes("BTC");
     * await this.orderExecutor.placeMarketOrder("BTC", true, maxLong); // all-in long
     */

15. getMaxLeverage(coin)
    /**
     * Get the maximum leverage allowed for a coin from exchange metadata.
     * 
     * @param {string} coin - Coin symbol
     * @returns {Promise<number>} Maximum leverage (e.g., 50 for BTC, 5 for small coins)
     * 
     * @example
     * const maxLev = await this.orderExecutor.getMaxLeverage("BTC");
     * console.log(`BTC max leverage: ${maxLev}x`);
     */

**IMPORTANT USAGE NOTES:**

1. Always check result.success before proceeding:
   ```javascript
   const result = await this.orderExecutor.placeMarketOrder("BTC", true, 0.01);
   if (result.success) {
     // Order succeeded
     console.log(`Filled at $${result.averagePrice}`);
   } else {
     // Order failed
     console.error(`Order failed: ${result.error}`);
   }
   ```

2. Position sizes are automatically rounded to valid decimal places for each coin

3. Prices are automatically rounded to 5 significant figures

4. Rate limiting is handled automatically with exponential backoff retries

5. For market orders, slippage parameter protects against bad fills:
   - Default 5% slippage
   - Calculates limit price = mid ± (mid * slippage)

6. reduceOnly=true means the order can ONLY close/reduce an existing position, not open new ones

7. Position sizes: Positive = long, Negative = short

8. Always sync positions after trades:
   ```javascript
   const result = await this.orderExecutor.placeMarketOrder("BTC", true, 0.01);
   if (result.success) {
     await this.syncPositions(); // Update database
   }
   ```

9. CRITICAL: Always set leverage BEFORE opening a position/order, not after. Hyperliquid defaults to 20x if you don't set it. Call setLeverage() in onInitialize(). The system automatically caps leverage at the coin's maximum allowed value.

"""

WEBSOCKET_MANAGER_DOCS = """

HyperliquidWSManager Class:

The WebSocket Manager handles real-time data streams from Hyperliquid. It is pre-initialized in BaseAgent as `this.wsManager`.

**KEY FEATURES:**
- Auto-reconnection on disconnection
- Auto-resubscription to all channels after reconnect
- Message queuing when connection is down
- Multiple concurrent subscriptions supported

Available Subscription Methods:

1. subscribeAllMids(callback)
   /**
    * Subscribe to all mid prices (real-time price updates for all coins)
    * 
    * @param {Function} callback - Called with price data on every update
    * @returns {void}
    * 
    * Callback receives (AllMids format):
    * {
    *   mids: {
    *     "BTC": "90518.5",
    *     "ETH": "3117.45",
    *     "SOL": "139.835",
    *     // ... all coins (100+)
    *   }
    * }
    * 
    * Note: Prices are nested inside a `mids` key. All prices are strings.
    * 
    * @example
    * this.wsManager.subscribeAllMids((data) => {
    *   const btcPrice = parseFloat(data.mids.BTC);
    *   const ethPrice = parseFloat(data.mids.ETH);
    *   console.log(`BTC: $${btcPrice}`);
    *   console.log(`ETH: $${ethPrice}`);
    * });
    */

2. subscribeL2Book(coin, callback)
   /**
    * Subscribe to Level 2 order book for a specific coin
    * 
    * @param {string} coin - Coin symbol (e.g., "BTC")
    * @param {Function} callback - Called with orderbook data on every update
    * @returns {void}
    * 
    * Callback receives:
    * {
    *   coin: "BTC",
    *   time: 1767947582743,
    *   levels: [
    *     [{ px: "90500", sz: "1.5", n: 3 }],  // Bids (buy orders)
    *     [{ px: "90550", sz: "2.1", n: 5 }]   // Asks (sell orders)
    *   ]
    * }
    * 
    * @example
    * this.wsManager.subscribeL2Book("BTC", (book) => {
    *   const bestBid = book.levels[0][0];
    *   const bestAsk = book.levels[1][0];
    *   console.log(`Spread: ${parseFloat(bestAsk.px) - parseFloat(bestBid.px)}`);
    * });
    */

3. subscribeTrades(coin, callback)
   /**
    * Subscribe to real-time trades for a specific coin
    * 
    * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
    * @param {Function} callback - Called with trade data on every new trade
    * @returns {void}
    * 
    * Callback receives array of WsTrade objects (all values are strings):
    * [
    *   {
    *     coin: "BTC",
    *     side: "B",           // "B" = Buy (taker bought), "A" = Sell (taker sold)
    *                          // NOTE: Raw WebSocket uses "B"/"A", NOT "Buy"/"Sell"
    *     px: "90518.5",       // Execution price (string)
    *     sz: "0.01",          // Trade size (string)
    *     time: 1767947582743, // Unix timestamp in milliseconds
    *     hash: "0x...",       // Transaction hash
    *     tid: 12345678        // Unique trade ID (number)
    *   },
    *   // ... more trades (usually 1-5 per update)
    * ]
    * 
    * @example
    * this.wsManager.subscribeTrades("BTC", (trades) => {
    *   for (const trade of trades) {
    *     const side = trade.side === 'B' ? 'BUY' : 'SELL';
    *     console.log(`${side} ${trade.sz} BTC @ $${trade.px}`);
    *   }
    * });
    */

4. subscribeUserEvents(callback)
   /**
    * Subscribe to user-specific events (fills, funding, liquidations, non-user cancels)
    * Requires address to be set in constructor
    * 
    * @param {Function} callback - Called with user event data
    * @returns {void}
    * 
    * IMPORTANT: The subscription type is "userEvents" but Hyperliquid sends responses 
    * on the "user" channel. This is handled internally - just use the callback.
    * 
    * Callback receives a WsUserEvent - a union type where exactly ONE key is present:
    *   { "fills": [WsFill, ...] }         // When fills occur
    *   OR { "funding": WsUserFunding }     // When funding is applied
    *   OR { "liquidation": WsLiquidation } // When liquidation occurs
    *   OR { "nonUserCancel": [WsNonUserCancel, ...] } // When orders are cancelled by system
    * 
    * WsFill structure:
    * {
    *   coin: "BTC",
    *   px: "90563",        // Fill price (string)
    *   sz: "0.011",        // Fill size (string)
    *   side: "B",          // "B" = Buy, "A" = Sell (raw, NOT converted)
    *   time: 1767947582743,
    *   startPosition: "0.0", // Position size before fill (string)
    *   dir: "Open Long",   // Frontend display direction
    *   closedPnl: "0.0",   // Realized PnL if closing position (string)
    *   hash: "0x...",       // L1 transaction hash
    *   oid: 12345,          // Order ID (number)
    *   crossed: true,       // Whether order was taker
    *   fee: "0.5",          // Fee paid (string, negative = rebate)
    *   tid: 123456,         // Unique trade ID (number)
    *   feeToken: "USDC"     // Token fee was paid in
    * }
    * 
    * WsUserFunding structure:
    * { time: number, coin: string, usdc: string, szi: string, fundingRate: string }
    * 
    * WsLiquidation structure:
    * { lid: number, liquidator: string, liquidated_user: string, 
    *   liquidated_ntl_pos: string, liquidated_account_value: string }
    * 
    * WsNonUserCancel structure:
    * { coin: string, oid: number }
    * 
    * @example
    * this.wsManager.subscribeUserEvents((event) => {
    *   if (event.fills) {
    *     for (const fill of event.fills) {
    *       const side = fill.side === 'B' ? 'BUY' : 'SELL';
    *       console.log(`✅ ${side}: ${fill.sz} ${fill.coin} @ $${fill.px}`);
    *       console.log(`   Fee: $${fill.fee}, PnL: $${fill.closedPnl}`);
    *     }
    *   }
    *   if (event.funding) {
    *     console.log(`💰 Funding: ${event.funding.coin} ${event.funding.usdc} USDC`);
    *   }
    *   if (event.liquidation) {
    *     console.log(`💥 Liquidation: ${event.liquidation.liquidated_ntl_pos}`);
    *   }
    *   if (event.nonUserCancel) {
    *     for (const cancel of event.nonUserCancel) {
    *       console.log(`🚫 Order ${cancel.oid} on ${cancel.coin} cancelled by system`);
    *     }
    *   }
    * });
    */

5. subscribeLiquidations(callback)
  /**
   * Subscribe to liquidation events
   * 
   * Real-time stream of all liquidations across all coins on Hyperliquid.
   * 
   * @param {Function} callback - Called whenever a liquidation occurs
   * @param {Array<Object>} callback.data - Array of liquidation events
   * 
   * @example
   * manager.subscribeLiquidations((liqEvents) => {
   *   liqEvents.forEach(liq => {
   *     console.log(`💥 ${liq.sz} ${liq.coin} liquidated @ ${liq.px} (${liq.side === 'B' ? 'LONG' : 'SHORT'})`);
   *   });
   * });
   * 
   * @example Output Format (single liquidation):
   * [
   *   {
   *     liq: "0x...",        // Liquidated user address
   *     coin: "BTC",
   *     side: "A",           // "A" = Long liquidation, "B" = Short liquidation
   *     px: "90500.0",       // Liquidation price
   *     sz: "0.5",           // Position size liquidated
   *     time: 1736504100000
   *   }
   * ]
   * 
   * Performance: Updates immediately when liquidations occur (sporadic).
   */

Unsubscribe Methods:

6. unsubscribeAllMids()
   /** Stop receiving all mid price updates */

7. unsubscribeL2Book(coin)
   /** Stop receiving order book updates for a coin */

8. unsubscribeTrades(coin)
   /** Stop receiving trade updates for a coin */

9. unsubscribeUserEvents()
   /** Stop receiving user event updates */

10. unsubscribeLiquidations()
    /** Stop receiving liquidation event updates */

11. close()
    /**
     * Close WebSocket connection (does not auto-reconnect)
     * Call this during agent shutdown
     */

**IMPORTANT USAGE NOTES:**

1. WebSocket is already connected when BaseAgent starts - just call subscribe methods

2. Callbacks fire on EVERY update - can be very frequent (multiple times per second)

3. All price/size data comes as STRINGS - always use parseFloat() before any math operations

4. User events require address - already configured in BaseAgent

5. Multiple subscriptions allowed - subscribe to as many channels as needed

6. Auto-reconnect handles disconnections - subscriptions persist

7. Use in setupTriggers() or onInitialize() to set up real-time data feeds

"""

PERP_MARKET_DOCS = """

perpMarket.js - Market Data Helper Functions:

These functions fetch public market data from Hyperliquid. Import and use directly.

Available Functions:

1. getAllMids(dex="")
   /**
    * Get current mid prices for all trading pairs
    * 
    * @param {string} dex - Optional perp dex name (default: "")
    * @returns {Promise<Object>} { "BTC": "90518.5", "ETH": "3117.45", ... }
    * 
    * @example
    * const mids = await getAllMids();
    * const btcPrice = parseFloat(mids.BTC);
    * console.log(`BTC: $${btcPrice.toFixed(2)}`);
    */

2. getCandleSnapshot(coin, interval, startTime, endTime)
   /**
    * Get historical OHLCV candles
    * 
    * @param {string} coin - Coin symbol (e.g., "BTC")
    * @param {string} interval - "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "3d", "1w", "1M"
    * @param {number} startTime - Start time in milliseconds
    * @param {number} endTime - End time in milliseconds
    * @returns {Promise<Array>} Array of candle objects sorted ascending
    * 
    * Candle object:
    * {
    *   timestampOpen: 1767862800000,
    *   timestampClose: 1767866400000,
    *   open: 86500.5,
    *   high: 86750.2,
    *   low: 86400.1,
    *   close: 86600.8,
    *   volume: 1250.5,
    *   trades: 150,
    *   symbol: "BTC",
    *   interval: "1h"
    * }
    * 
    * @example
    * // Get last 24 hours of 1h candles
    * const now = Date.now();
    * const yesterday = now - (24 * 60 * 60 * 1000);
    * const candles = await getCandleSnapshot("BTC", "1h", yesterday, now);
    * console.log(`Got ${candles.length} candles`);
    * const closes = candles.map(c => c.close);
    */

3. getTicker(coin)
   /**
    * Get 24h ticker statistics
    * 
    * @param {string} coin - Coin symbol
    * @returns {Promise<Object>} Ticker data
    * 
    * Returns:
    * {
    *   coin: "BTC",
    *   price: 90518.5,        // Current price
    *   open: 90677.0,         // 24h open
    *   high: 91000.0,         // 24h high
    *   low: 90000.0,          // 24h low
    *   volume: 15000.5,       // 24h volume
    *   change: -158.5,        // 24h change
    *   change_percent: -0.17  // 24h change %
    * }
    * 
    * @example
    * const ticker = await getTicker("BTC");
    * console.log(`24h Change: ${ticker.change_percent.toFixed(2)}%`);
    * console.log(`24h Volume: ${ticker.volume.toFixed(2)}`);
    */

4. getL2Book(coin, nSigFigs=5)
   /**
    * Get Level 2 order book snapshot
    * 
    * @param {string} coin - Coin symbol
    * @param {number} nSigFigs - Price precision (default: 5)
    * @returns {Promise<Object>} Order book data (processed format)
    * 
    * Returns:
    * {
    *   coin: "BTC",
    *   time: 1767947582743,
    *   bids: [                    // Bids sorted descending by price (best bid first)
    *     { price: 90518, size: 34.6921, n: 61 },  // n = number of orders at this level
    *     { price: 90517, size: 12.5, n: 3 },
    *     // ... up to 20 levels
    *   ],
    *   asks: [                    // Asks sorted ascending by price (best ask first)
    *     { price: 90519, size: 25.3, n: 45 },
    *     { price: 90520, size: 18.7, n: 12 },
    *     // ... up to 20 levels
    *   ]
    * }
    * 
    * @example
    * const book = await getL2Book("BTC");
    * const bestBid = book.bids[0].price;
    * const bestAsk = book.asks[0].price;
    * const spread = bestAsk - bestBid;
    * console.log(`Spread: $${spread.toFixed(2)}`);
    */

5. getFundingHistory(coin, startTime, endTime=Date.now())
   /**
    * Get historical funding rates (sorted by timestamp ascending)
    * 
    * @param {string} coin - Coin symbol
    * @param {number} startTime - Start time in milliseconds
    * @param {number} endTime - End time in milliseconds (default: Date.now())
    * @returns {Promise<Array>} Funding rate history
    * 
    * Each entry:
    * {
    *   timestamp: 1767947582743,  // Unix timestamp in ms (NOT "time")
    *   fundingRate: 0.0000125,    // Hourly funding rate (number, parsed)
    *   premium: -0.0002621123     // Premium (number, parsed)
    * }
    * 
    * NOTE: Field name is `timestamp` (not `time`), and there is no `coin` field in each entry.
    * 
    * @example
    * const now = Date.now();
    * const weekAgo = now - (7 * 24 * 60 * 60 * 1000);
    * const funding = await getFundingHistory("BTC", weekAgo, now);
    * const avgRate = funding.reduce((sum, f) => sum + f.fundingRate, 0) / funding.length;
    * console.log(`Avg funding rate: ${(avgRate * 100).toFixed(4)}%`);
    */

6. getMetaAndAssetCtxs()
    /**
    * Get meta and asset contexts (includes open interest, mark price, funding, etc.)
    * @returns {Promise<Object>} Object containing meta information and asset contexts for all coins
    * 
    * @example
    * const { meta, assetCtxs } = await getMetaAndAssetCtxs();
    * const btcCtx = assetCtxs.find(ctx => ctx.coin === "BTC");
    * console.log("BTC Open Interest:", btcCtx.openInterest); // 29098.73964
    * console.log("BTC Mark Price:", btcCtx.markPx); // 90518
    * 
    * @example Output Format:
    * {
    *   meta: {
    *     universe: [/* array of coin metadata objects *\/],
    *     marginTables: [/* array of margin table arrays *\/],
    *     collateralToken: 0
    *   },
    *   assetCtxs: [
    *     {
    *       funding: 0.0000125,
    *       openInterest: 29098.73964,
    *       prevDayPx: "90677.0",
    *       dayNtlVlm: "3200890932.4486026764",
    *       premium: "0.0",
    *       oraclePx: "90530.0",
    *       markPx: 90518,
    *       midPx: "90525.5",
    *       impactPxs: [/* array of impact prices *\/],
    *       dayBaseVlm: "35338.04737"
    *     },
    *     {
    *       funding: 0.0000125,
    *       openInterest: 979884.1077999996,
    *       prevDayPx: "3132.8",
    *       dayNtlVlm: "1471830580.780487299",
    *       premium: "0.00022561",
    *       oraclePx: "3102.7",
    *       markPx: 3103.4,
    *       midPx: "3103.45",
    *       impactPxs: [/* array *\/],
    *       dayBaseVlm: "474189.5115999999"
    *     },
    *     // ... one entry per coin in universe (100+ coins)
    *   ]
    * }
    */

7. getRecentTrades(coin)
   /**
    * Get recent trades for a coin (up to 500, sorted by timestamp descending)
    * 
    * @param {string} coin - Coin symbol
    * @returns {Promise<Array>} Recent trades (processed format with parsed numbers)
    * 
    * Each trade:
    * {
    *   timestamp: 1767947582743,  // Unix timestamp in ms
    *   price: 90518.5,            // Execution price (number, parsed)
    *   size: 0.01,                // Trade size (number, parsed)
    *   side: "Buy",               // "Buy" or "Sell" (converted from raw "B"/"A")
    *   hash: "0x..."              // Transaction hash
    * }
    * 
    * NOTE: Field names are `price`, `size`, `timestamp` (NOT `px`, `sz`, `time`).
    * Side is converted: "B" -> "Buy", "A" -> "Sell".
    * 
    * @example
    * const trades = await getRecentTrades("BTC");
    * const recentBuys = trades.filter(t => t.side === "Buy");
    * const buyVolume = recentBuys.reduce((sum, t) => sum + t.size, 0);
    * console.log(`Recent buy volume: ${buyVolume.toFixed(2)} BTC`);
    */

8. getPredictedFundings()
   /**
    * Get predicted funding rates across venues for all coins
    * 
    * @returns {Promise<Array>} Array of tuples [coin, [funding arrays]]
    * 
    * Returns the raw Hyperliquid API response - an array of tuples:
    * [
    *   ["BTC", [[funding_data], [funding_data], [funding_data]]],
    *   ["ETH", [[funding_data], [funding_data], [funding_data]]],
    *   ["SOL", [[funding_data], [funding_data], [funding_data]]],
    *   // ... one entry per coin
    * ]
    * 
    * @example
    * const predicted = await getPredictedFundings();
    * const btcFunding = predicted.find(([coin]) => coin === "BTC");
    * if (btcFunding) {
    *   console.log("BTC predicted funding:", btcFunding[1]);
    * }
    */

9. getPerpsAtOpenInterestCap()
   /**
    * Get list of perps at their open interest cap
    * 
    * @returns {Promise<Array>} Array of coin symbols at OI cap
    * 
    * @example
    * const capped = await getPerpsAtOpenInterestCap();
    * if (capped.includes("BTC")) {
    *   console.log("BTC is at open interest cap - cannot open new positions");
    * }
    */

**IMPORTANT USAGE NOTES:**

1. All prices returned as strings or numbers - check type and convert if needed
2. Timestamps are in milliseconds (JavaScript Date.now() format)
3. Candle intervals: "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"
4. These are async functions - always use await
5. No rate limiting built-in - space out requests if making many calls
6. Use getAllMids() for quick price checks (single call for all coins)
7. Use getCandleSnapshot() for technical indicator calculations

"""

PERP_USER_DOCS = """

perpUser.js - User Data Helper Functions:

These functions fetch user-specific data from Hyperliquid. Require user address.

Available Functions:

1. getOpenOrders(user, dex="")
   /**
    * Get current open orders for a user
    * 
    * @param {string} user - User address in 42-character hexadecimal format (0x...)
    * @param {string} dex - Optional perp dex name (default: "")
    * @returns {Promise<Array>} Array of open orders sorted by timestamp descending
    * 
    * Returns empty array [] if no open orders.
    * 
    * @example
    * const orders = await getOpenOrders(this.userAddress);
    * console.log(`You have ${orders.length} open orders`);
    * const btcOrders = orders.filter(o => o.coin === "BTC");
    * 
    * @example Output Format:
    * [
    *   {{
    *     oid: "12345",              // Order ID
    *     coin: "BTC",
    *     side: "Buy",               // or "Sell"
    *     limitPx: 90518.5,          // Limit price
    *     sz: 0.01,                  // Order size
    *     timestamp: 1767947582743
    *   }},
    *   // ... more orders sorted by timestamp descending
    * ]
    */

2. getFrontendOpenOrders(user, dex="")
   /**
    * Get open orders with frontend/trigger details
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @param {string} dex - Optional perp dex name (default: "")
    * @returns {Promise<Array>} Array of open orders with trigger information
    * 
    * @example
    * const orders = await getFrontendOpenOrders(this.userAddress);
    * const triggerOrders = orders.filter(o => o.isTrigger);
    * console.log(`${{triggerOrders.length}} stop-loss/take-profit orders active`);
    * 
    * @example Output Format:
    * [
    *   {{
    *     oid: "12345",
    *     coin: "BTC",
    *     side: "Buy",
    *     limitPx: 90518.5,
    *     sz: 0.01,
    *     isTrigger: false,        // true if this is a stop-loss/take-profit order
    *     triggerPx: null,         // Trigger price if isTrigger is true
    *     timestamp: 1767947582743
    *   }}
    * ]
    */

3. getUserFills(user, aggregateByTime=false)
   /**
    * Get recent fills (executed trades, up to 2000 most recent)
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @param {boolean} aggregateByTime - When true, partial fills are combined (default: false)
    * @returns {Promise<Array>} Array of fills sorted by timestamp descending (newest first)
    * 
    * @example
    * const fills = await getUserFills(this.userAddress);
    * console.log(`Got ${{fills.length}} recent fills`);
    * const totalFees = fills.reduce((sum, f) => sum + f.fee, 0);
    * console.log(`Total fees: $${{totalFees.toFixed(2)}}`);
    * 
    * @example Output Format:
    * [
    *   {{
    *     coin: "BTC",
    *     px: 90563,               // Execution price
    *     sz: 0.011,              // Size filled
    *     side: "Buy",            // or "Sell"
    *     time: 1767947582743,    // Timestamp
    *     fee: 0.5,               // Fee paid
    *     closedPnl: 0.0,         // Realized PnL if closing position
    *     oid: "12345",           // Order ID
    *     hash: "0x..."           // Transaction hash
    *   }},
    *   // ... up to 2000 fills, sorted by time descending
    * ]
    */

4. getUserFillsByTime(user, startTime, endTime=Date.now(), aggregateByTime=false)
   /**
    * Get fills in time range (up to 2000 per response, only 10000 most recent fills available)
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @param {number} startTime - Start time in milliseconds (inclusive)
    * @param {number} endTime - End time in milliseconds (inclusive), defaults to current time
    * @param {boolean} aggregateByTime - When true, partial fills are combined
    * @returns {Promise<Array>} Array of fills sorted by timestamp descending
    * 
    * Same output format as getUserFills().
    * 
    * @example
    * const oneDayAgo = Date.now() - (24 * 60 * 60 * 1000);
    * const fills = await getUserFillsByTime(this.userAddress, oneDayAgo);
    * const totalPnl = fills.reduce((sum, f) => sum + f.closedPnl, 0);
    * console.log(`24h PnL: $${{totalPnl.toFixed(2)}}`);
    */

5. getHistoricalOrders(user)
   /**
    * Get historical orders (up to 2000 most recent)
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @returns {Promise<Array>} Array of historical orders sorted by timestamp descending
    * 
    * Includes all order statuses: "open", "filled", "canceled", "rejected", etc.
    * 
    * @example
    * const orders = await getHistoricalOrders(this.userAddress);
    * console.log(`Got ${{orders.length}} historical orders`);
    * const filled = orders.filter(o => o.status === "filled");
    * 
    * @example Output Format:
    * [
    *   {{
    *     oid: "12345",
    *     coin: "BTC",
    *     side: "Buy",
    *     limitPx: 90518.5,
    *     sz: 0.01,
    *     status: "filled",       // "open", "filled", "canceled", "rejected", etc.
    *     timestamp: 1767947582743
    *   }}
    * ]
    */

6. getPortfolio(user)
   /**
    * Get portfolio PnL + account value history
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @returns {Promise<Array>} Array of tuples [period, {{ accountValueHistory, pnlHistory, vlm }}]
    * 
    * Returns historical PnL and account value data across different time periods.
    * 
    * @example
    * const portfolio = await getPortfolio(this.userAddress);
    * const allTime = portfolio.find(([period]) => period === "allTime");
    * console.log("All-time volume:", allTime[1].vlm);
    * 
    * @example Output Format:
    * [
    *   [
    *     "day",
    *     {{
    *       accountValueHistory: [[timestamp, "accountValue"], ...],
    *       pnlHistory: [[timestamp, "pnl"], ...],
    *       vlm: "0.0"  // Volume in USDC
    *     }}
    *   ],
   *   [
   *     "week",
   *     {{ accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }}
   *   ],
   *   [
   *     "month",
   *     {{ accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }}
   *   ],
   *   [
   *     "allTime",
   *     {{
   *       accountValueHistory: [Array],
   *       pnlHistory: [Array],
   *       vlm: "3008970620.4899997711"  // Total volume
   *     }}
   *   ],
   *   [
   *     "perpDay",
   *     {{ accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }}
   *   ],
   *   [
   *     "perpWeek",
   *     {{ accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }}
   *   ],
   *   [
   *     "perpMonth",
   *     {{ accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }}
   *   ],
   *   [
   *     "perpAllTime",
   *     {{
   *       accountValueHistory: [Array],
   *       pnlHistory: [Array],
   *       vlm: "3008749918.9499998093"  // Perp-only volume
   *     }}
   *   ]
   * ]
    */

7. getSubAccounts(user)
   /**
    * Get sub-accounts (margin + spot balances)
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @returns {Promise<Object|null>} Balances/margin info, or null if no sub-accounts
    * 
    * @example
    * const subAccounts = await getSubAccounts(this.userAddress);
    * if (subAccounts) {{
    *   console.log("Sub-accounts:", subAccounts);
    * }} else {{
    *   console.log("No sub-accounts");
    * }}
    */

8. getUserFees(user)
   /**
    * Get user fee rates, volume tiers, and fee schedule
    * 
    * @param {string} user - User address in 42-character hexadecimal format
    * @returns {Promise<Object>} Object containing fee rates, volume data, and fee schedule
    * 
    * @example
    * const fees = await getUserFees(this.userAddress);
    * console.log("Your maker rate:", fees.userAddRate);     // "0.00015"
    * console.log("Your taker rate:", fees.userCrossRate);   // "0.00045"
    * 
    * @example Output Format:
    * {{
    *   dailyUserVlm: [
    *     {{
    *       date: "2026-01-09",
    *       userCross: "0.0",      // Your taker volume
    *       userAdd: "0.0",        // Your maker volume
    *       exchange: "6465965874.76"  // Total exchange volume
    *     }}
    *   ],
    *   feeSchedule: {{
    *     cross: "0.00045",        // Base taker fee
    *     add: "0.00015",          // Base maker fee
    *     spotCross: "0.0007",     // Spot taker fee
    *     spotAdd: "0.0004",       // Spot maker fee
    *     tiers: {{ vip: [...], mm: [...] }},
    *     referralDiscount: "0.04",
    *     stakingDiscountTiers: [...]
    *   }},
    *   userCrossRate: "0.00045",      // Your effective taker rate
    *   userAddRate: "0.00015",        // Your effective maker rate
    *   userSpotCrossRate: "0.0007",  // Your spot taker rate
    *   userSpotAddRate: "0.0004",    // Your spot maker rate
    *   activeReferralDiscount: "0.0",
    *   activeStakingDiscount: {{ discount: "0.0" }}
    * }}
    */

**IMPORTANT USAGE NOTES:**

1. All functions require a valid user address (0x... format, 42 characters)
2. Use this.userAddress in BaseAgent (already configured)
3. Most numeric values returned as strings - convert with parseFloat() if needed
4. Timestamps in milliseconds
5. getUserFills() limited to 2000 most recent fills
6. getUserFillsByTime() limited to 2000 per response and only 10000 most recent fills available
7. getHistoricalOrders() limited to 2000 most recent orders
8. getPortfolio() returns PnL/account value HISTORY, not current positions (use orderExecutor.getPositions() for current positions)
9. Side conversion: "B" = Buy, "A" = Sell (automatically converted in helper functions)
10. These make HTTP requests - not real-time like WebSocket

"""

BASE_AGENT_DOCS = """

BaseAgent class:

constructor() method (config taken as input):

- `this.agentId` (string): UUID identifying this agent in Supabase
- `this.userId` (string): User ID who owns this agent  
- `this.privateKey` (string): Hyperliquid API wallet private key (0x-prefixed)
- `this.userAddress` (string): User's main Hyperliquid address (0x-prefixed)
- `this.isMainnet` (boolean): Network selection (always true)

- `this.orderExecutor` (OrderExecutor): 
  - Handles ALL trading operations (place orders, close positions, check balances)
  - Initialized with user's credentials and network
  
- `this.wsManager` (HyperliquidWSManager):
  - WebSocket connections for real-time data streams
  - Pre-connected to user's address
  
- `this.supabase` (SupabaseClient):
  - Database client for state persistence
  - Pre-configured with project URL and credentials
  - Rarely needed directly (use helper methods instead)


- `this.currentState` (string): Agent state ('initializing', 'running', 'stopped', 'error')
- `this.isRunning` (boolean): Whether agent is actively running
- `this.isPaused` (boolean): Whether agent is paused
- `this.lastHeartbeat` (number): Unix timestamp of last heartbeat

- `this.activeTriggers` (Map): Registered triggers map (triggerId -> config)
- `this.triggerCallbacks` (Map): Callbacks map (triggerId -> function)
  - Do not access this directly, use the helper methods instead

- `this.maxPositionSize` (number): Maximum position size
- `this.maxLeverage` (number): Maximum leverage (differs per coin, set via setLeverage)
- `this.dailyLossLimit` (number): Daily loss limit in USD (default: 100)
  - Automatically enforced by checkSafetyLimits() - don't modify directly

State-Management Methods:

async updateState(stateType, stateData, message)
/**
  * Update agent state in Supabase
  * 
  * @param {string} stateType - Type of state update (cycle, position, order, error, etc.)
  * @param {Object} stateData - Raw state data (JSONB)
  * @param {string} message - Human-readable message
  */

/**
  * Sync positions to Supabase
  * Fetches current positions from Hyperliquid and updates database
  * Also removes closed positions from the database
  */
async syncPositions()

  /**
   * Log trade to Supabase AND track position locally for PnL calculation.
   * 
   * is_entry/is_exit are AUTO-INFERRED if not provided: the system checks existing
   * positions to determine if this trade opens or closes a position. You can still
   * set them explicitly for clarity, but it is not required.
   * 
   * Fees are auto-calculated from the order type if not provided.
   * 
   * @param {Object} tradeData
   * @param {string} tradeData.coin - Coin symbol
   * @param {string} tradeData.side - 'buy' or 'sell'
   * @param {number} tradeData.size - Trade size
   * @param {number} [tradeData.price] - Execution price
   * @param {string} [tradeData.order_type] - 'market', 'limit', 'close_position', etc.
   * @param {string} [tradeData.order_id] - Order ID
   * @param {string} [tradeData.trigger_reason] - What triggered the trade
   * @param {boolean} [tradeData.is_entry] - Explicitly mark as entry (auto-inferred if omitted)
   * @param {boolean} [tradeData.is_exit] - Explicitly mark as exit (auto-inferred if omitted)
   * @returns {Promise<Object|null>} { positionId, pnl, fee, feeRate } or null on error
   * 
   * @example
   * await this.logTrade({
   *   coin, side: 'buy', size: result.filledSize,
   *   price: result.averagePrice, order_type: 'market',
   *   order_id: result.orderId, trigger_reason: 'RSI oversold',
   *   is_entry: true
   * });
   */
  async logTrade(tradeData)

  /**
   * Update agent metrics (raw metrics only)
   * Computes total PnL, trade count, win rate, and account value
   */
  async updateMetrics() {


Trigger Utility Methods:

  /**
   * Register a price-based trigger
   * 
   * @param {string} coin - Coin symbol
   * @param {Object} condition - { above: number } or { below: number } or { crosses: number }
   * @param {Function} callback - Async function to call when triggered
   * @returns {string} triggerId
   * 
   * @example
   * this.registerPriceTrigger('BTC', { below: 85000 }, async (triggerData) => {
   *   await this.executeTrade(triggerData);
   * });
   */
  registerPriceTrigger(coin, condition, callback)


    /**
   * Register a technical indicator trigger
   * 
   * @param {string} coin - Coin symbol
   * @param {string} indicator - Indicator name ('RSI', 'EMA', 'MACD', 'BollingerBands', 'SMA')
   * @param {Object} params - Indicator parameters (e.g., { period: 14, interval: '1h' })
   * @param {Object} condition - Trigger condition (e.g., { above: 70 }, { below: 30 })
   * @param {Function} callback - Async function to call when triggered
   * @returns {string} triggerId
   * 
   * @example
   * this.registerTechnicalTrigger(
   *   'BTC',
   *   'RSI',
   *   { period: 14, interval: '1h' },
   *   { below: 30 },
   *   async (triggerData) => {
   *     await this.executeTrade({ ...triggerData, action: 'buy' });
   *   }
   * );
   */
  registerTechnicalTrigger(coin, indicator, params, condition, callback) 

    /**
   * Register a scheduled trigger (runs at fixed intervals)
   * 
   * @param {number} intervalMs - Interval in milliseconds
   * @param {Function} callback - Async function to call
   * @returns {string} triggerId
   * 
   * @example
   * this.registerScheduledTrigger(5 * 60 * 1000, async (triggerData) => {
   *   await this.executeTrade(triggerData);
   * });
   */
  registerScheduledTrigger(intervalMs, callback) 

    /**
   * Register an event-based trigger (WebSocket events)
   * 
   * @param {string} eventType - Event type: 'liquidation', 'largeTrade', or 'userFill'
   * @param {Object} condition - Event condition
   *   - For 'liquidation': { minSize: number } - Minimum liquidation size
   *   - For 'largeTrade': { coin: string, minSize: number } - Coin and minimum trade size
   *   - For 'userFill': {} - No condition needed (all user fills trigger)
   * @param {Function} callback - Async function to call
   * @returns {string} triggerId
   * 
   * @example
   * // Liquidation events
   * this.registerEventTrigger('liquidation', { minSize: 1.0 }, async (triggerData) => {
   *   console.log('Large liquidation detected:', triggerData);
   * });
   * 
   * @example
   * // Large trade events
   * this.registerEventTrigger('largeTrade', { coin: 'BTC', minSize: 10.0 }, async (triggerData) => {
   *   console.log('Large BTC trade:', triggerData);
   * });
   * 
   * @example
   * // User fill events (all fills on your account)
   * this.registerEventTrigger('userFill', {}, async (triggerData) => {
   *   console.log('Your order filled:', triggerData);
   * });
   */
  registerEventTrigger(eventType, condition, callback)

    /**
   * Remove a trigger
   * 
   * @param {string} triggerId - Trigger ID to remove
   */
  removeTrigger(triggerId) 


Utility Methods:

  /**
   * Check if safety limits are satisfied
   * 
   * @param {string} coin - Coin to check
   * @param {number} proposedSize - Proposed position size
   * @returns {Promise<Object>} { allowed: boolean, reason: string }
   */
  async checkSafetyLimits(coin, proposedSize) {

Lifecycle Methods:
  /**
   * Start the agent
   * 
   * 1. Call onInitialize() (abstract method)
   * 2. Call setupTriggers() (abstract method)
   * 3. Start monitoring loop
   * 4. Update state to 'running'
   */
  async start() {

  /**
   * Monitoring loop
   * Evaluates all active triggers continuously
   */
  async monitor() {

  /**
   * Pause the agent (stops executing triggers but keeps monitoring)
   */
  async pause() {

  /**
   * Resume the agent
   */
  async resume() {

  /**
   * Stop and shutdown the agent
   * This is a PRESET method that all agents use (not abstract)
   * 
   * Steps:
   * 1. Stop monitoring loop
   * 2. Cancel all open orders
   * 3. Close all positions (optional, based on config)
   * 4. Close WebSocket connections
   * 5. Final state sync and evaluation
   * 6. Update state to 'stopped'
   */
  async shutdown() {

  
"""

