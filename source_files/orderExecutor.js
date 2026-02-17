/**
 * Order Executor for Hyperliquid DEX
 * 
 * Clean implementation using the official Hyperliquid SDK.
 * Separates user's main account address (for queries) from API wallet (for signing).
 * 
 * @module orderExecutor
 */

import { ethers } from 'ethers';
import { Hyperliquid } from 'hyperliquid';
import { randomBytes } from 'crypto';
import { getAllMids, getMetaAndAssetCtxs } from './perpMarket.js';
import { getOpenOrders, getUserFees } from './perpUser.js';
import OrderOwnershipStore from './OrderOwnershipStore.js';
import { hyperliquidInfoRequest } from './apiClient.js';
import { sleep, retryWithBackoff } from './utils.js';
import { DEFAULT_LEVERAGE_SYNC_TTL_MS, META_CACHE_TTL_MS, CLEARINGHOUSE_CACHE_TTL_MS } from './config.js';

// ============================================================================
// ENUMS
// ============================================================================

const OrderSide = {
  BUY: "buy",
  SELL: "sell"
};

const OrderType = {
  MARKET: "market",
  LIMIT: "limit",
  STOP_LOSS: "stop_loss",
  TAKE_PROFIT: "take_profit",
  TRAILING_STOP: "trailing_stop"
};

const TriggerType = {
  MARK: "mark",
  LAST: "last",
  ORACLE: "oracle"
};

// ============================================================================
// RESULT CLASSES
// ============================================================================

class OrderResult {
  constructor({
    success,
    orderId = null,
    cloid = null,
    filledSize = null,
    averagePrice = null,
    status = null,
    error = null,
    rawResponse = null,
    fee = null,
    feeRate = null,
    feeType = null
  }) {
    this.success = success;
    this.orderId = orderId;
    this.cloid = cloid;
    this.filledSize = filledSize;
    this.averagePrice = averagePrice;
    this.status = status;
    this.error = error;
    this.rawResponse = rawResponse;
    this.fee = fee;
    this.feeRate = feeRate;
    this.feeType = feeType;
  }
}

class Position {
  constructor({
    coin,
    size,
    entryPrice,
    unrealizedPnl,
    realizedPnl,
    leverage,
    liquidationPrice = null,
    marginUsed
  }) {
    this.coin = coin;
    this.size = size;
    this.entryPrice = entryPrice;
    this.unrealizedPnl = unrealizedPnl;
    this.realizedPnl = realizedPnl;
    this.leverage = leverage;
    this.liquidationPrice = liquidationPrice;
    this.marginUsed = marginUsed;
  }
}

class OpenOrder {
  constructor({
    orderId,
    coin,
    side,
    size,
    price,
    orderType,
    reduceOnly,
    timestamp
  }) {
    this.orderId = orderId;
    this.coin = coin;
    this.side = side;
    this.size = size;
    this.price = price;
    this.orderType = orderType;
    this.reduceOnly = reduceOnly;
    this.timestamp = timestamp;
  }
}

// ============================================================================
// ORDER EXECUTOR CLASS
// ============================================================================

/**
 * Executes trading orders on Hyperliquid using API wallets
 * 
 * ARCHITECTURE:
 * - userAddress: Main Hyperliquid account (used for ALL queries: balance, positions, orders)
 * - privateKey: API wallet private key (used ONLY for signing transactions via SDK)
 * - apiWalletAddress: Derived from privateKey (for reference only, not directly used)
 * 
 * @example
 * const executor = new OrderExecutor(
 *   "0x1234...",  // API wallet private key (from Hyperliquid API console)
 *   "0x5678...",  // Your main Hyperliquid address
 *   true          // Mainnet
 * );
 * 
 * // Place orders
 * const result = await executor.placeMarketOrder("BTC", true, 0.01);
 */
class OrderExecutor {
  /**
   * Initialize order executor
   * 
   * @param {string} privateKey - API wallet private key (0x-prefixed, for signing only)
   * @param {string} userAddress - Main Hyperliquid address (0x-prefixed, for queries)
   * @param {boolean} isMainnet - Network selection (default: true)
   * @param {Object} [options] - Optional runtime options
   * @param {string} [options.agentId] - Agent ID for local order ownership sandboxing
   * @param {number} [options.leverageSyncTtlMs] - TTL to skip redundant leverage resets (default from config.js)
   */
  constructor(privateKey, userAddress, isMainnet = true, options = {}) {
    // Validate inputs
    if (!privateKey || !privateKey.startsWith('0x')) {
      throw new Error("Private key must start with 0x");
    }
    if (!userAddress || !userAddress.startsWith('0x')) {
      throw new Error("User address must start with 0x");
    }

    // Store addresses with clear separation
    this.userAddress = userAddress;  // For queries (balance, positions, orders)
    // NOTE: Do NOT derive API wallet address - SDK handles this internally
    this.isMainnet = isMainnet;

    // Initialize Hyperliquid SDK
    // The SDK will use privateKey for signing and walletAddress for all operations
    // Only pass privateKey and userAddress - SDK should NOT derive/check API wallet address
    this.sdk = new Hyperliquid({
      privateKey: privateKey,
      walletAddress: userAddress,  // SDK uses this as the trading account
      testnet: !isMainnet,
      enableWs: false
    });

    // Metadata cache
    this._metaCache = null;
    this._metaCacheTime = 0;
    this._metaCacheTTL = META_CACHE_TTL_MS;

    // Per-coin leverage set by the user via setLeverage()
    // Maps coin symbol -> leverage number (e.g., { "BTC": 10, "ETH": 5 })
    this._leverageMap = {};
    // Maps coin symbol -> margin mode (true = cross, false = isolated)
    this._leverageModeMap = {};
    // Coin -> timestamp of last successful leverage sync
    this._lastLeverageSyncAt = {};
    this._leverageSyncTtlMs = Number.isFinite(options.leverageSyncTtlMs)
      ? Math.max(0, options.leverageSyncTtlMs)
      : DEFAULT_LEVERAGE_SYNC_TTL_MS;

    // Local ownership sandbox store (no schema change required)
    this.agentId = options.agentId || null;
    this.orderOwnershipStore = this.agentId ? new OrderOwnershipStore(this.agentId) : null;

    // Clearinghouse state cache (short TTL to reduce duplicate API calls within a tight window)
    this._clearinghouseCache = null;
    this._clearinghouseCacheTime = 0;
    this._clearinghouseCacheTTL = CLEARINGHOUSE_CACHE_TTL_MS;

    // Fee rates (defaults, will fetch actual rates)
    this.takerFeeRate = 0.00045;  // 0.045%
    this.makerFeeRate = 0.00015;  // 0.015%
    this.userFeeRates = null;

    console.log(`OrderExecutor initialized:`);
    console.log(`  User Address: ${userAddress.substring(0, 10)}... (trading account)`);
    console.log(`  Network: ${isMainnet ? 'mainnet' : 'testnet'}`);
    if (this.agentId) {
      console.log(`  Sandbox Scope: agent=${this.agentId}`);
    }
  }

  // ==========================================================================
  // PRIVATE HELPER METHODS
  // ==========================================================================

  /**
   * Get cached metadata or fetch fresh
   * @private
   */
  async _getMeta() {
    const now = Date.now();
    if (this._metaCache && (now - this._metaCacheTime) < this._metaCacheTTL) {
      return this._metaCache;
    }
    
    this._metaCache = await retryWithBackoff(
      () => getMetaAndAssetCtxs(),
      5,
      2000
    );
    this._metaCacheTime = now;
    return this._metaCache;
  }

  /**
   * Get coin information from metadata
   * @private
   */
  async _getCoinInfo(coin) {
    const { meta } = await this._getMeta();
    const assetInfo = meta.universe.find(asset => asset.name === coin);
    if (!assetInfo) {
      throw new Error(`Unknown coin: ${coin}`);
    }
    return assetInfo;
  }

  /**
   * Fetch and cache user's actual fee rates
   */
  async fetchUserFeeRates() {
    try {
      const fees = await getUserFees(this.userAddress);
      this.takerFeeRate = parseFloat(fees.userCrossRate ?? 0.00045);
      this.makerFeeRate = parseFloat(fees.userAddRate ?? 0.00015);
      this.userFeeRates = fees;
      
      console.log(`📊 Fee rates: Taker ${(this.takerFeeRate * 100).toFixed(4)}%, Maker ${(this.makerFeeRate * 100).toFixed(4)}%`);
    } catch (error) {
      console.warn('⚠️  Failed to fetch fee rates, using defaults:', error.message);
    }
  }

  /**
   * Calculate fee for a trade
   * @param {number} size - Trade size
   * @param {number} price - Trade price
   * @param {string} orderType - Order type ('market', 'limit', 'Ioc', 'Gtc', 'Alo')
   * @returns {Object} Fee information { fee, feeRate, feeType }
   */
  calculateTradeFee(size, price, orderType = 'market') {
    const value = size * price;
    
    // ONLY Alo (Add Liquidity Only) orders are guaranteed maker on fill.
    // Everything else can execute as taker, so classify as taker to avoid optimistic fee underestimation.
    const normalizedType = String(orderType || '').trim().toLowerCase();
    const isMakerGuaranteed = normalizedType === 'alo';
    const feeRate = isMakerGuaranteed ? this.makerFeeRate : this.takerFeeRate;
    
    const fee = value * feeRate;
    
    return {
      fee,
      feeRate,
      feeType: isMakerGuaranteed ? 'maker' : 'taker'
    };
  }

  /**
   * Estimate the round-trip (open + close) fees for a trade.
   * Useful for pre-trade PnL projections.
   *
   * @param {number} size - Trade size in base currency
   * @param {number} entryPrice - Expected entry price
   * @param {number|null} [exitPrice=null] - Expected exit price (defaults to entryPrice)
   * @param {string} [entryOrderType='market'] - Order type for entry
   * @param {string} [exitOrderType='market'] - Order type for exit
   * @returns {{entryFee: number, exitFee: number, totalFee: number, entryFeeRate: number, exitFeeRate: number}}
   */
  estimateRoundTripFee(size, entryPrice, exitPrice = null, entryOrderType = 'market', exitOrderType = 'market') {
    const ep = exitPrice ?? entryPrice;
    const entry = this.calculateTradeFee(size, entryPrice, entryOrderType);
    const exit = this.calculateTradeFee(size, ep, exitOrderType);
    return {
      entryFee: entry.fee,
      exitFee: exit.fee,
      totalFee: entry.fee + exit.fee,
      entryFeeRate: entry.feeRate,
      exitFeeRate: exit.feeRate,
    };
  }

  /**
   * Estimate the fee to close a position for a specific coin.
   * Sandboxing-safe: accepts optional `agentSize` so the caller can pass
   * only the agent's portion of a shared position rather than the full
   * exchange position size.
   *
   * @param {string} coin - Coin symbol
   * @param {number|null} [agentSize=null] - The agent's position size. When null,
   *   falls back to fetching the full exchange position size (whole account).
   * @param {number|null} [exitPrice=null] - Expected exit price. When null,
   *   uses the current mid price.
   * @returns {Promise<{fee: number, feeRate: number, notional: number}>}
   */
  async estimateCloseFee(coin, agentSize = null, exitPrice = null) {
    let size = agentSize;

    if (size == null) {
      const positions = await this.getPositions(coin);
      size = positions.length > 0 ? Math.abs(positions[0].size) : 0;
    }

    let price = exitPrice;
    if (price == null) {
      const allMids = await getAllMids();
      price = parseFloat(allMids[coin] || '0');
    }

    if (size === 0 || price === 0) {
      return { fee: 0, feeRate: this.takerFeeRate, notional: 0 };
    }

    const notional = size * price;
    const feeRate = this.takerFeeRate;
    return { fee: notional * feeRate, feeRate, notional };
  }

  /**
   * Round size to valid decimal places for the coin
   * @private
   */
  async _roundSize(size, coin) {
    if (!Number.isFinite(size)) return NaN;
    const coinInfo = await this._getCoinInfo(coin);
    const szDecimals = coinInfo.szDecimals ?? 4;  // ?? preserves 0 (whole-unit coins)
    return parseFloat(size.toFixed(szDecimals));
  }

  /**
   * Validate rounded order size before placing any order.
   * @private
   * @param {number} size
   * @param {string} coin
   * @param {string} context
   * @returns {OrderResult|null}
   */
  _validatePositiveSize(size, coin, context = 'order') {
    if (!Number.isFinite(size) || size <= 0) {
      return new OrderResult({
        success: false,
        error: `Invalid ${context} size for ${coin}: ${size}`
      });
    }
    return null;
  }

  /**
   * Re-apply leverage for a coin before placing each order.
   * This keeps exchange-side leverage aligned with local sizing assumptions.
   * @private
   * @param {string} coin - Coin symbol
   * @returns {Promise<number>} Effective leverage used for this order
   */
  async _ensureLeverageBeforeOrder(coin) {
    const now = Date.now();
    const lastSync = this._lastLeverageSyncAt[coin] || 0;

    // TTL guard: skip redundant leverage updates on hot paths
    if (
      this._leverageMap[coin] &&
      this._leverageSyncTtlMs > 0 &&
      (now - lastSync) < this._leverageSyncTtlMs
    ) {
      return this._leverageMap[coin];
    }

    const leverage = await this._getLeverageForCoin(coin);
    const isCross = this._leverageModeMap[coin] !== undefined ? this._leverageModeMap[coin] : true;
    const ok = await this.setLeverage(coin, leverage, isCross);
    if (!ok) {
      throw new Error(`Failed to ensure leverage for ${coin}`);
    }
    return this._leverageMap[coin] || leverage;
  }

  /**
   * Build a valid Hyperliquid client order ID (cloid) for ownership isolation.
   * Hyperliquid requires cloid to be a 128-bit hex string: "0x" + 32 hex chars.
   * We encode agent identity in the first 8 bytes and use random bytes for the rest.
   * The ownership store can still match by cloid string equality.
   * @private
   */
  _generateCloid(coin) {
    if (!this.agentId) return null;
    // First 8 bytes: deterministic from agentId (for debugging/identification)
    const agentHex = Buffer.from(String(this.agentId).replace(/-/g, ''))
      .subarray(0, 8)
      .toString('hex')
      .padEnd(16, '0');
    // Last 8 bytes: random for uniqueness
    const randHex = randomBytes(8).toString('hex');
    return `0x${agentHex}${randHex}`;
  }

  /**
   * Persist ownership metadata for placed orders.
   * @private
   */
  _recordOwnedOrder(result, metadata) {
    if (!this.orderOwnershipStore || !metadata?.cloid || !result?.success) return;
    this.orderOwnershipStore.registerOrder({
      ...metadata,
      orderId: result?.orderId ?? null,
      status: result?.status || 'submitted',
      updatedAt: new Date().toISOString()
    });
  }

  /**
   * Round price to valid Hyperliquid tick size.
   * Rules: max 5 significant figures AND max (6 - szDecimals) decimal places for perps.
   * Integer prices are always valid regardless of sig-fig count.
   * @private
   * @param {number} price - Price to round
   * @param {string} coin - Coin symbol (needed to look up szDecimals)
   * @returns {Promise<number>} Rounded price
   */
  async _roundPrice(price, coin) {
    if (!Number.isFinite(price)) {
      throw new Error(`Invalid price for ${coin}: ${price}`);
    }
    if (price === 0) return 0.0;
    if (Number.isInteger(price)) return price;
    
    // Step 1: Round to 5 significant figures
    const sigFigs = 5;
    const magnitude = Math.floor(Math.log10(Math.abs(price)));
    const scale = Math.pow(10, sigFigs - 1 - magnitude);
    let rounded = Math.round(price * scale) / scale;
    
    // Step 2: Clamp to max decimal places (Hyperliquid perp rule: 6 - szDecimals)
    const coinInfo = await this._getCoinInfo(coin);
    const szDecimals = coinInfo.szDecimals ?? 4;
    const maxDecimals = Math.max(0, 6 - szDecimals);
    const decimalScale = Math.pow(10, maxDecimals);
    rounded = Math.round(rounded * decimalScale) / decimalScale;
    
    return rounded;
  }

  /**
   * Parse SDK order result into OrderResult
   * @private
   */
  _parseOrderResult(orderResult, orderType = 'market', cloid = null) {
    if (orderResult.status === "ok") {
      const response = orderResult.response || {};
      const data = response.data || {};
      const statuses = data.statuses || [{}];
      const status = statuses[0] || {};
      
      if (status.resting) {
        return new OrderResult({
          success: true,
          orderId: status.resting.oid,
          cloid,
          status: "open",
          rawResponse: orderResult
        });
      } else if (status.filled) {
        const filledSize = parseFloat(status.filled.totalSz || "0");
        const averagePrice = parseFloat(status.filled.avgPx || "0");
        
        // Prefer actual on-chain fee from API response when available
        const rawFee = status.filled.fee != null ? parseFloat(status.filled.fee) : NaN;
        const feeInfo = this.calculateTradeFee(filledSize, averagePrice, orderType);

        const actualFee = Number.isFinite(rawFee) ? rawFee : feeInfo.fee;
        const actualFeeRate = Number.isFinite(rawFee) && filledSize * averagePrice > 0
          ? rawFee / (filledSize * averagePrice)
          : feeInfo.feeRate;
        
        return new OrderResult({
          success: true,
          orderId: status.filled.oid,
          cloid,
          filledSize,
          averagePrice,
          status: "filled",
          rawResponse: orderResult,
          fee: actualFee,
          feeRate: actualFeeRate,
          feeType: feeInfo.feeType
        });
      } else if (status.error) {
        return new OrderResult({
          success: false,
          cloid,
          error: status.error,
          rawResponse: orderResult
        });
      }
    }
    
    return new OrderResult({
      success: false,
      cloid,
      error: orderResult.error || JSON.stringify(orderResult) || "Unknown error",
      rawResponse: orderResult
    });
  }

  // ==========================================================================
  // ORDER PLACEMENT METHODS
  // ==========================================================================

  /**
   * Place a market order (immediate execution with slippage protection)
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {boolean} isBuy - true for buy, false for sell
   * @param {number} size - Order size in base currency
   * @param {boolean} reduceOnly - Only reduce existing position (default: false)
   * @param {number} slippage - Max slippage tolerance (default: 0.05 = 5%)
   * @returns {Promise<OrderResult>}
   * 
   * @example
   * const result = await executor.placeMarketOrder("BTC", true, 0.01);
   * if (result.success) console.log(`Filled at ${result.averagePrice}`);
   */
  async placeMarketOrder(coin, isBuy, size, reduceOnly = false, slippage = 0.05) {
    try {
      // Fetch coinInfo once — used by _roundSize, margin check, and price rounding
      const coinInfo = await this._getCoinInfo(coin);
      const szDecimals = coinInfo.szDecimals ?? 4;

      size = parseFloat((Number.isFinite(size) ? size : NaN).toFixed(szDecimals));
      const sizeError = this._validatePositiveSize(size, coin, reduceOnly ? 'reduce-only order' : 'market order');
      if (sizeError) return sizeError;

      // Parallelize: fetch leverage, mids, and (if needed) balance concurrently
      const leveragePromise = this._ensureLeverageBeforeOrder(coin);
      const midsPromise = retryWithBackoff(() => getAllMids(), 3, 2000);
      const balancePromise = reduceOnly
        ? Promise.resolve(null)
        : this.getAvailableBalance();

      const [leverageForOrder, allMids, rawBalanceOrNull] = await Promise.all([
        leveragePromise, midsPromise, balancePromise
      ]);

      const cloid = this._generateCloid(coin);
      const midPrice = parseFloat(allMids[coin] || "0");
      
      if (midPrice === 0) {
        return new OrderResult({
          success: false,
          error: `Could not get price for ${coin}`
        });
      }
      
      // For reduceOnly orders (closing positions), skip balance/maxSize checks entirely.
      // Hyperliquid doesn't require margin for reduce-only orders.
      if (!reduceOnly) {
        const numericBalance = Number(rawBalanceOrNull);
        const availableBalance = Number.isFinite(numericBalance) ? Math.max(0, numericBalance) : 0;
        
        // Inline max-size calculation (reuses coinInfo from above, avoids extra _getCoinInfo)
        const maxLev = parseInt(coinInfo.maxLeverage || "20");
        const effectiveLev = Math.min(leverageForOrder, maxLev);
        if (!Number.isFinite(effectiveLev) || effectiveLev <= 0) {
          return new OrderResult({
            success: false,
            error: `Invalid leverage for ${coin}: ${effectiveLev}`
          });
        }

        // Fee-aware max size (same formula as getMaxTradeSizes)
        const denom = (1 / effectiveLev) + this.takerFeeRate;
        const maxNotional = denom > 0 ? availableBalance / denom : 0;
        const rawMaxSize = maxNotional / midPrice;
        const maxSize = parseFloat(Math.max(0, rawMaxSize).toFixed(szDecimals));
        
        // Cap size to max
        if (size > maxSize) {
          if (maxSize <= 0) {
            return new OrderResult({
              success: false,
              error: `Insufficient available balance for ${coin}. Available: $${availableBalance.toFixed(2)}`
            });
          }
          console.warn(`⚠️  Requested size ${size} exceeds max ${maxSize} for ${coin}, adjusting to max`);
          size = maxSize;
        }

        const adjustedSizeError = this._validatePositiveSize(size, coin, 'market order');
        if (adjustedSizeError) return adjustedSizeError;
        
        // Margin check (fee-aware: include estimated taker fee)
        const positionValue = size * midPrice;
        const estimatedFee = positionValue * this.takerFeeRate;
        const requiredMargin = (positionValue / effectiveLev) + estimatedFee;
        
        if (requiredMargin > availableBalance) {
          const accountValue = await this.getAccountValue();
          console.error(`❌ Insufficient balance for ${coin} ${isBuy ? 'BUY' : 'SELL'} ${size}`);
          console.error(`   Required margin: $${(positionValue / effectiveLev).toFixed(2)} + fee ~$${estimatedFee.toFixed(2)} = $${requiredMargin.toFixed(2)} (${effectiveLev}x leverage)`);
          console.error(`   Available balance: $${availableBalance.toFixed(2)}`);
          console.error(`   Account value: $${accountValue.toFixed(2)}`);
          
          return new OrderResult({
            success: false,
            error: `Insufficient balance. Required: $${requiredMargin.toFixed(2)} (incl. ~$${estimatedFee.toFixed(2)} fee), Available: $${availableBalance.toFixed(2)}`
          });
        }
        
        console.log(`📝 Placing ${isBuy ? 'BUY' : 'SELL'} market order: ${size} ${coin} @ ~$${midPrice.toFixed(2)}`);
        console.log(`   Position value: $${positionValue.toFixed(2)}`);
        console.log(`   Required margin: $${(positionValue / effectiveLev).toFixed(2)} + fee ~$${estimatedFee.toFixed(2)} (${effectiveLev}x leverage)`);
        console.log(`   Available balance: $${availableBalance.toFixed(2)}`);
      } else {
        console.log(`📝 Placing ${isBuy ? 'BUY' : 'SELL'} reduce-only order: ${size} ${coin} @ ~$${midPrice.toFixed(2)}`);
      }
      
      // Calculate limit price with slippage protection
      const limitPrice = isBuy 
        ? midPrice * (1 + slippage)
        : midPrice * (1 - slippage);
      
      const roundedLimitPrice = await this._roundPrice(limitPrice, coin);
      
      // Use SDK to place order
      const orderResult = await this.sdk.exchange.placeOrder({
        coin: coin + '-PERP',
        is_buy: isBuy,
        sz: size,
        limit_px: roundedLimitPrice,
        order_type: { limit: { tif: "Ioc" } },  // Immediate-or-cancel for market behavior
        reduce_only: reduceOnly,
        ...(cloid ? { cloid } : {})
      });
      
      // Invalidate clearinghouse cache after order placement
      this.invalidateClearinghouseCache();

      const result = this._parseOrderResult(orderResult, 'Ioc', cloid);
      this._recordOwnedOrder(result, {
        cloid,
        coin,
        orderType: 'Ioc',
        isBuy,
        reduceOnly,
        size,
        price: roundedLimitPrice
      });
      
      // Log fee if successful
      if (result.success && result.fee) {
        console.log(`💰 Fee: $${result.fee.toFixed(4)} (${(result.feeRate * 100).toFixed(4)}% ${result.feeType})`);
      }
      
      return result;
      
    } catch (error) {
      console.error("Market order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Place a limit order at a specific price
   * 
   * @param {string} coin - Coin symbol
   * @param {boolean} isBuy - true for buy, false for sell
   * @param {number} size - Order size
   * @param {number} price - Limit price
   * @param {boolean} reduceOnly - Only reduce position (default: false)
   * @param {boolean} postOnly - Post-only (maker-only) order (default: false)
   * @param {string} timeInForce - "Gtc", "Ioc", or "Alo" (default: "Gtc")
   * @returns {Promise<OrderResult>}
   * 
   * @example
   * const result = await executor.placeLimitOrder("ETH", true, 0.1, 2000.0);
   */
  async placeLimitOrder(
    coin,
    isBuy,
    size,
    price,
    reduceOnly = false,
    postOnly = false,
    timeInForce = "Gtc"
  ) {
    try {
      size = await this._roundSize(size, coin);
      const sizeError = this._validatePositiveSize(size, coin, 'limit order');
      if (sizeError) return sizeError;

      price = await this._roundPrice(price, coin);
      await this._ensureLeverageBeforeOrder(coin);
      const cloid = this._generateCloid(coin);
      
      if (postOnly) {
        timeInForce = "Alo";
      }
      
      const orderResult = await this.sdk.exchange.placeOrder({
        coin: coin + '-PERP',
        is_buy: isBuy,
        sz: size,
        limit_px: price,
        order_type: { limit: { tif: timeInForce } },
        reduce_only: reduceOnly,
        ...(cloid ? { cloid } : {})
      });
      
      this.invalidateClearinghouseCache();

      const result = this._parseOrderResult(orderResult, timeInForce, cloid);
      this._recordOwnedOrder(result, {
        cloid,
        coin,
        orderType: timeInForce,
        isBuy,
        reduceOnly,
        size,
        price
      });
      
      // Log fee if successful
      if (result.success && result.fee) {
        console.log(`💰 Fee: $${result.fee.toFixed(4)} (${(result.feeRate * 100).toFixed(4)}% ${result.feeType})`);
      }
      
      return result;
      
    } catch (error) {
      console.error("Limit order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Place a stop-loss order (triggers when price reaches trigger level)
   * 
   * @param {string} coin - Coin symbol
   * @param {boolean} isBuy - true for buy stop, false for sell stop
   * @param {number} size - Order size
   * @param {number} triggerPrice - Price to trigger at
   * @param {number|null} limitPrice - Limit price after trigger (null = auto-calculate)
   * @param {boolean} reduceOnly - Only reduce position (default: true)
   * @returns {Promise<OrderResult>}
   * 
   * @example
   * const result = await executor.placeStopLoss("BTC", false, 0.1, 40000);
   */
  async placeStopLoss(
    coin,
    isBuy,
    size,
    triggerPrice,
    limitPrice = null,
    reduceOnly = true
  ) {
    try {
      size = await this._roundSize(size, coin);
      const sizeError = this._validatePositiveSize(size, coin, 'stop-loss order');
      if (sizeError) return sizeError;

      triggerPrice = await this._roundPrice(triggerPrice, coin);
      await this._ensureLeverageBeforeOrder(coin);
      const cloid = this._generateCloid(coin);
      
      if (limitPrice === null) {
        const slippage = 0.03;  // 3% slippage for stop-loss
        limitPrice = isBuy
          ? triggerPrice * (1 + slippage)
          : triggerPrice * (1 - slippage);
      }
      
      limitPrice = await this._roundPrice(limitPrice, coin);
      
      const orderResult = await this.sdk.exchange.placeOrder({
        coin: coin + '-PERP',
        is_buy: isBuy,
        sz: size,
        limit_px: limitPrice,
        order_type: {
          trigger: {
            isMarket: false,
            triggerPx: triggerPrice,
            tpsl: "sl"
          }
        },
        reduce_only: reduceOnly,
        ...(cloid ? { cloid } : {})
      });
      
      const result = this._parseOrderResult(orderResult, 'stop_loss', cloid);
      this._recordOwnedOrder(result, {
        cloid,
        coin,
        orderType: 'stop_loss',
        isBuy,
        reduceOnly,
        size,
        price: limitPrice,
        triggerPrice
      });
      return result;
      
    } catch (error) {
      console.error("Stop-loss order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Place a take-profit order
   * 
   * @param {string} coin - Coin symbol
   * @param {boolean} isBuy - true for buy, false for sell
   * @param {number} size - Order size
   * @param {number} triggerPrice - Price to trigger at
   * @param {number|null} limitPrice - Limit price after trigger (null = auto-calculate)
   * @param {boolean} reduceOnly - Only reduce position (default: true)
   * @returns {Promise<OrderResult>}
   * 
   * @example
   * const result = await executor.placeTakeProfit("BTC", false, 0.1, 50000);
   */
  async placeTakeProfit(
    coin,
    isBuy,
    size,
    triggerPrice,
    limitPrice = null,
    reduceOnly = true
  ) {
    try {
      size = await this._roundSize(size, coin);
      const sizeError = this._validatePositiveSize(size, coin, 'take-profit order');
      if (sizeError) return sizeError;

      triggerPrice = await this._roundPrice(triggerPrice, coin);
      await this._ensureLeverageBeforeOrder(coin);
      const cloid = this._generateCloid(coin);
      
      if (limitPrice === null) {
        const slippage = 0.01;  // 1% slippage for take-profit
        limitPrice = isBuy
          ? triggerPrice * (1 + slippage)
          : triggerPrice * (1 - slippage);
      }
      
      limitPrice = await this._roundPrice(limitPrice, coin);
      
      const orderResult = await this.sdk.exchange.placeOrder({
        coin: coin + '-PERP',
        is_buy: isBuy,
        sz: size,
        limit_px: limitPrice,
        order_type: {
          trigger: {
            isMarket: false,
            triggerPx: triggerPrice,
            tpsl: "tp"
          }
        },
        reduce_only: reduceOnly,
        ...(cloid ? { cloid } : {})
      });
      
      const result = this._parseOrderResult(orderResult, 'take_profit', cloid);
      this._recordOwnedOrder(result, {
        cloid,
        coin,
        orderType: 'take_profit',
        isBuy,
        reduceOnly,
        size,
        price: limitPrice,
        triggerPrice
      });
      return result;
      
    } catch (error) {
      console.error("Take-profit order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Place a trailing stop order (dynamically calculates stop price from current price)
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {boolean} isBuy - true for buy trailing stop, false for sell trailing stop
   * @param {number} size - Order size in base currency
   * @param {number} trailPercent - Trail percentage (e.g., 5 = 5% trailing distance)
   * @param {boolean} reduceOnly - Only reduce existing position (default: true)
   * @returns {Promise<OrderResult>} Order result object
   * 
   * @example
   * // Protect a long position with 5% trailing stop
   * await executor.placeMarketOrder("BTC", true, 0.1); // Open long
   * await executor.placeTrailingStop("BTC", false, 0.1, 5); // 5% below current price
   * 
   * @example
   * // Protect a short position with 3% trailing stop
   * await executor.placeMarketOrder("ETH", false, 1.0); // Open short
   * await executor.placeTrailingStop("ETH", true, 1.0, 3); // 3% above current price
   * 
   * @example
   * // Dynamic stop for existing position
   * const positions = await executor.getPositions("BTC");
   * if (positions.length > 0) {
   *   const pos = positions[0];
   *   const isLong = pos.size > 0;
   *   await executor.placeTrailingStop(
   *     "BTC",
   *     !isLong,              // Opposite direction to close
   *     Math.abs(pos.size),
   *     5                     // 5% trail
   *   );
   * }
   * 
   * @example Output Format:
   * {
   *   success: true,
   *   orderId: "12345",
   *   status: "open",           // Trailing stop is an open order
   *   error: null,
   *   rawResponse: { ... }
   * }
   * 
   * How it works:
   * 1. Gets current mid price
   * 2. Calculates trigger price based on trail percentage:
   *    - For sell stop: triggerPrice = currentPrice * (1 - trailPercent/100)
   *    - For buy stop: triggerPrice = currentPrice * (1 + trailPercent/100)
   * 3. Places a stop-loss order at the calculated trigger price
   * 
   * Example: BTC at $90,000, 5% trailing stop (sell)
   * → Trigger price: $85,500 (90,000 * 0.95)
   * → If price rises to $95,000, trail moves to $90,250
   * → Protects profits while allowing upside
   * 
   * Note: This creates a static stop-loss order. For true trailing stops that
   * automatically adjust, you'd need to cancel and replace periodically.
   */
  async placeTrailingStop(coin, isBuy, size, trailPercent, reduceOnly = true) {
    try {
      size = await this._roundSize(size, coin);
      const sizeError = this._validatePositiveSize(size, coin, 'trailing-stop order');
      if (sizeError) return sizeError;
      
      const allMids = await retryWithBackoff(() => getAllMids(), 3, 2000);
      const currentPrice = parseFloat(allMids[coin] || "0");
      
      if (currentPrice === 0) {
        return new OrderResult({
          success: false,
          error: `Could not get price for ${coin}`
        });
      }
      
      const trailFactor = trailPercent / 100.0;
      const triggerPrice = isBuy
        ? currentPrice * (1 + trailFactor)
        : currentPrice * (1 - trailFactor);
      
      return await this.placeStopLoss(coin, isBuy, size, triggerPrice, null, reduceOnly);
      
    } catch (error) {
      console.error("Trailing stop order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  // ==========================================================================
  // ORDER MANAGEMENT METHODS
  // ==========================================================================

  /**
   * Cancel a specific order
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {number} orderId - Order ID to cancel
   * @returns {Promise<OrderResult>} Cancellation result
   * 
   * @example
   * // Cancel a specific order
   * const result = await executor.cancelOrder("BTC", 12345);
   * if (result.success) {
   *   console.log(`Order ${result.orderId} cancelled successfully`);
   * }
   * 
   * @example
   * // Cancel the first open order for BTC
   * const orders = await executor.getOpenOrders("BTC");
   * if (orders.length > 0) {
   *   const orderId = Number(orders[0].orderId);
   *   await executor.cancelOrder("BTC", orderId);
   * }
   * 
   * @example Output Format:
   * {
   *   success: true,
   *   orderId: "12345",
   *   status: "cancelled",
   *   error: null,
   *   rawResponse: { status: "ok", ... }
   * }
   * 
   * // On failure:
   * {
   *   success: false,
   *   orderId: null,
   *   status: null,
   *   error: "Order not found",
   *   rawResponse: { status: "err", ... }
   * }
   */
  async cancelOrder(coin, orderId) {
    try {
      const cancelResult = await this.sdk.exchange.cancelOrder({
        coin: coin + '-PERP',
        o: orderId
      });
      
      if (cancelResult.status === "ok") {
        if (this.orderOwnershipStore) {
          this.orderOwnershipStore.markByOrderId(orderId, 'cancelled');
        }
        return new OrderResult({
          success: true,
          orderId: orderId.toString(),
          status: "cancelled",
          rawResponse: cancelResult
        });
      }
      
      return new OrderResult({
        success: false,
        error: cancelResult.error || "Cancel failed",
        rawResponse: cancelResult
      });
      
    } catch (error) {
      console.error("Cancel order failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Cancel order by client order ID (cloid).
   * Useful for ownership-scoped cancels on shared accounts.
   *
   * @param {string} coin - Coin symbol
   * @param {string} cloid - Client order ID
   * @returns {Promise<OrderResult>}
   */
  async cancelOrderByCloid(coin, cloid) {
    try {
      const cancelResult = await this.sdk.exchange.cancelOrderByCloid(coin + '-PERP', cloid);
      if (cancelResult.status === "ok") {
        if (this.orderOwnershipStore) {
          this.orderOwnershipStore.markByCloid(cloid, 'cancelled');
        }
        return new OrderResult({
          success: true,
          cloid,
          status: "cancelled",
          rawResponse: cancelResult
        });
      }

      return new OrderResult({
        success: false,
        cloid,
        error: cancelResult.error || "Cancel by cloid failed",
        rawResponse: cancelResult
      });
    } catch (error) {
      console.error("Cancel by cloid failed:", error);
      return new OrderResult({ success: false, cloid, error: error.message });
    }
  }

  /**
   * Cancel ONLY this agent's owned open orders, tracked via local store.
   * This is the safest cancellation method for shared accounts.
   *
   * @param {string|null} coin - Optional coin filter
   * @returns {Promise<OrderResult>}
   */
  async cancelAgentOrders(coin = null) {
    if (!this.orderOwnershipStore) {
      return new OrderResult({
        success: false,
        error: "Ownership store not configured (agentId missing)"
      });
    }

    try {
      const ownedOrders = this.orderOwnershipStore.getOpenOrders(coin);
      if (ownedOrders.length === 0) {
        return new OrderResult({
          success: true,
          status: "no_owned_orders_to_cancel"
        });
      }

      // Build cancel tasks (agent-scoped only)
      const cancelTask = (order) => {
        if (order.orderId != null) {
          const numericId = Number(order.orderId);
          if (Number.isSafeInteger(numericId)) {
            return this.cancelOrder(order.coin, numericId);
          } else if (order.cloid) {
            return this.cancelOrderByCloid(order.coin, order.cloid);
          }
          return Promise.resolve(new OrderResult({ success: false, error: `Unsafe order ID: ${order.orderId}` }));
        } else if (order.cloid) {
          return this.cancelOrderByCloid(order.coin, order.cloid);
        }
        return Promise.resolve(new OrderResult({ success: false, error: "Missing both orderId and cloid" }));
      };

      // Batch cancel in parallel (groups of 5 to avoid rate limits)
      const BATCH_SIZE = 5;
      const results = [];
      for (let i = 0; i < ownedOrders.length; i += BATCH_SIZE) {
        const batch = ownedOrders.slice(i, i + BATCH_SIZE);
        const batchResults = await Promise.all(batch.map(cancelTask));
        results.push(...batchResults);

        // Mark terminal failures in ownership store
        for (let j = 0; j < batchResults.length; j++) {
          const result = batchResults[j];
          const order = batch[j];
          if (!result.success && this.orderOwnershipStore) {
            const errMsg = String(result.error || '').toLowerCase();
            const terminalNotOpen =
              errMsg.includes('filled') ||
              errMsg.includes('already canceled') ||
              errMsg.includes('already cancelled') ||
              errMsg.includes('not found') ||
              errMsg.includes('never placed') ||
              errMsg.includes('does not exist');
            if (terminalNotOpen && order.cloid) {
              this.orderOwnershipStore.markByCloid(order.cloid, 'closed_external');
            }
          }
        }

        if (i + BATCH_SIZE < ownedOrders.length) await sleep(100);
      }

      // Prune stale entries from the ownership store after cancel sweep
      this.orderOwnershipStore.prune();
      this.invalidateClearinghouseCache();

      const allSuccess = results.every(r => r.success);
      return new OrderResult({
        success: allSuccess,
        status: allSuccess ? "all_owned_orders_cancelled" : "partial_owned_cancellation",
        rawResponse: results
      });
    } catch (error) {
      console.error("Cancel owned orders failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Cancel all open orders for a coin
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @returns {Promise<OrderResult>} Bulk cancellation result
   * 
   * @example
   * // Cancel all BTC orders
   * const result = await executor.cancelAllOrders("BTC");
   * if (result.success) {
   *   console.log("All BTC orders cancelled");
   * }
   * 
   * @example
   * // Cancel all orders for multiple coins
   * const coins = ["BTC", "ETH", "SOL"];
   * for (const coin of coins) {
   *   const result = await executor.cancelAllOrders(coin);
   *   console.log(`${coin}: ${result.status}`);
   * }
   * 
   * @example
   * // Check individual cancellation results
   * const result = await executor.cancelAllOrders("BTC");
   * if (result.rawResponse && Array.isArray(result.rawResponse)) {
   *   result.rawResponse.forEach((res, i) => {
   *     console.log(`Order ${i + 1}: ${res.success ? 'Cancelled' : 'Failed'}`);
   *   });
   * }
   * 
   * @example Output Format:
   * // When orders exist and all cancelled:
   * {
   *   success: true,
   *   status: "all_cancelled",
   *   rawResponse: [
   *     { success: true, orderId: "12345", ... },
   *     { success: true, orderId: "12346", ... }
   *   ]
   * }
   * 
   * // When no orders exist:
   * {
   *   success: true,
   *   status: "no_orders_to_cancel"
   * }
   * 
   * // When some fail:
   * {
   *   success: false,
   *   status: "partial_cancellation",
   *   rawResponse: [
   *     { success: true, orderId: "12345", ... },
   *     { success: false, error: "...", ... }
   *   ]
   * }
   * 
   * Note: Cancellations are sent sequentially with 100ms delay between each
   * to avoid rate limits.
   */
  async cancelAllOrders(coin) {
    console.warn(`⚠️  cancelAllOrders(${coin}) is account-wide for this coin and may affect other agents`);
    try {
      const openOrders = await this.getOpenOrders(coin);
      
      if (openOrders.length === 0) {
        return new OrderResult({
          success: true,
          status: "no_orders_to_cancel"
        });
      }
      
      const results = [];
      for (const order of openOrders) {
        const numericId = Number(order.orderId);
        if (!Number.isSafeInteger(numericId) || isNaN(numericId)) {
          console.error(`⚠️  Order ID ${order.orderId} is not a safe integer, skipping cancel`);
          results.push(new OrderResult({ success: false, error: `Unsafe order ID: ${order.orderId}` }));
          continue;
        }
        const result = await this.cancelOrder(coin, numericId);
        results.push(result);
        await sleep(100);
      }
      
      const allSuccess = results.every(r => r.success);
      return new OrderResult({
        success: allSuccess,
        status: allSuccess ? "all_cancelled" : "partial_cancellation",
        rawResponse: results
      });
      
    } catch (error) {
      console.error("Cancel all orders failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Get locally tracked open orders owned by this agent.
   *
   * @param {string|null} coin - Optional coin filter
   * @returns {Array<Object>}
   */
  getOwnedOpenOrders(coin = null) {
    if (!this.orderOwnershipStore) return [];
    return this.orderOwnershipStore.getOpenOrders(coin);
  }

  // ==========================================================================
  // QUERY METHODS (All use userAddress)
  // ==========================================================================

  /**
   * Get all open orders for the account
   * 
   * @param {string|null} coin - Filter by coin symbol (null = all coins)
   * @returns {Promise<OpenOrder[]>} Array of open order objects
   * 
   * @example
   * // Get all open orders
   * const allOrders = await executor.getOpenOrders();
   * console.log(`Total open orders: ${allOrders.length}`);
   * 
   * @example
   * // Get open orders for a specific coin
   * const btcOrders = await executor.getOpenOrders("BTC");
   * btcOrders.forEach(order => {
   *   console.log(`Order ${order.orderId}: ${order.side} ${order.size} @ ${order.price}`);
   * });
   * 
   * @example Output Format:
   * [
   *   {
   *     orderId: "12345",
   *     coin: "BTC",
   *     side: "buy",              // "buy" or "sell"
   *     size: "0.01",
   *     price: "90500.0",
   *     orderType: "limit",
   *     reduceOnly: false,
   *     timestamp: 1736504100000
   *   },
   *   {
   *     orderId: "12346",
   *     coin: "ETH",
   *     side: "sell",
   *     size: "0.5",
   *     price: "3100.0",
   *     orderType: "limit",
   *     reduceOnly: false,
   *     timestamp: 1736504200000
   *   }
   * ]
   */
  async getOpenOrders(coin = null) {
    try {
      const orders = await retryWithBackoff(
        () => getOpenOrders(this.userAddress),
        3,
        2000
      );
      
      const filtered = coin 
        ? orders.filter(o => o.coin === coin)
        : orders;
      
      return filtered.map(order => new OpenOrder({
        orderId: order.oid,
        coin: order.coin,
        side: order.side.toLowerCase(),
        size: order.sz,
        price: order.limitPx,
        orderType: "limit",
        reduceOnly: false,
        timestamp: order.timestamp
      }));
      
    } catch (error) {
      console.error("Get open orders failed:", error);
      return [];
    }
  }

  /**
   * Get current positions for the account
   * 
   * @param {string|null} coin - Filter by coin symbol (null = all positions)
   * @returns {Promise<Position[]>} Array of position objects
   * 
   * @example
   * // Get all positions
   * const positions = await executor.getPositions();
   * positions.forEach(pos => {
   *   console.log(`${pos.coin}: ${pos.size} @ ${pos.entryPrice}`);
   *   console.log(`  PnL: $${pos.unrealizedPnl}`);
   * });
   * 
   * @example
   * // Get position for a specific coin
   * const btcPositions = await executor.getPositions("BTC");
   * if (btcPositions.length > 0) {
   *   const pos = btcPositions[0];
   *   console.log(`BTC Position: ${pos.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(pos.size)}`);
   * }
   * 
   * @example Output Format:
   * [
   *   {
   *     coin: "BTC",
   *     size: 0.05,                    // Positive = long, negative = short
   *     entryPrice: 90500.0,
   *     unrealizedPnl: 125.5,          // Current unrealized profit/loss
   *     realizedPnl: 0.0,              // Realized PnL from funding
   *     leverage: 10,                  // Current leverage
   *     liquidationPrice: 81450.0,     // Price at which position gets liquidated
   *     marginUsed: 452.5              // Margin allocated to this position
   *   },
   *   {
   *     coin: "ETH",
   *     size: -0.5,                    // Negative size = short position
   *     entryPrice: 3100.0,
   *     unrealizedPnl: -15.25,
   *     realizedPnl: 0.0,
   *     leverage: 5,
   *     liquidationPrice: 3720.0,
   *     marginUsed: 310.0
   *   }
   * ]
   */
  /**
   * Fetch the full clearinghouse state for this user (single API call).
   * All account queries (positions, balance, account value) should use this
   * to avoid redundant API calls when multiple pieces of data are needed.
   *
   * @returns {Promise<Object>} Raw clearinghouseState response
   */
  async getClearinghouseState() {
    const now = Date.now();
    if (
      this._clearinghouseCache &&
      (now - this._clearinghouseCacheTime) < this._clearinghouseCacheTTL
    ) {
      return this._clearinghouseCache;
    }

    const state = await hyperliquidInfoRequest({
      type: "clearinghouseState",
      user: this.userAddress
    });
    this._clearinghouseCache = state;
    this._clearinghouseCacheTime = Date.now();
    return state;
  }

  /**
   * Invalidate the clearinghouse cache.
   * Call after order placement / cancellation so the next read is fresh.
   */
  invalidateClearinghouseCache() {
    this._clearinghouseCache = null;
    this._clearinghouseCacheTime = 0;
  }

  async getPositions(coin = null) {
    try {
      const userState = await this.getClearinghouseState();
      return this._parsePositions(userState, coin);
    } catch (error) {
      console.error("Get positions failed:", error);
      return [];
    }
  }

  /**
   * Parse positions from a clearinghouseState response.
   * @private
   */
  _parsePositions(userState, coin = null) {
    const assetPositions = userState.assetPositions || [];
    const positions = [];
    for (const posData of assetPositions) {
      const position = posData.position;
      const posCoin = position.coin;
      if (coin && posCoin !== coin) continue;
      const size = parseFloat(position.szi || "0");
      if (size === 0) continue;
      positions.push(new Position({
        coin: posCoin,
        size,
        entryPrice: parseFloat(position.entryPx || "0"),
        unrealizedPnl: parseFloat(position.unrealizedPnl || "0"),
        realizedPnl: parseFloat(position.cumFunding?.sinceOpen || "0"),
        leverage: parseInt(position.leverage?.value || "1"),
        liquidationPrice: position.liquidationPx ? parseFloat(position.liquidationPx) : null,
        marginUsed: parseFloat(position.marginUsed || "0")
      }));
    }
    return positions;
  }

  /**
   * Get total account value including unrealized PnL
   * @returns {Promise<number>} Total account value in USD
   */
  async getAccountValue() {
    try {
      const userState = await this.getClearinghouseState();
      return this._parseAccountValue(userState);
    } catch (error) {
      console.error("Get account value failed:", error);
      return 0.0;
    }
  }

  /** @private */
  _parseAccountValue(userState) {
    const marginSummary = userState.marginSummary || {};
    return parseFloat(marginSummary.accountValue || "0");
  }

  /**
   * Get available balance for trading
   * @returns {Promise<number>} Available balance in USD
   */
  async getAvailableBalance() {
    try {
      const userState = await this.getClearinghouseState();
      return this._parseAvailableBalance(userState);
    } catch (error) {
      console.error("Get available balance failed:", error);
      return 0.0;
    }
  }

  /** @private */
  _parseAvailableBalance(userState) {
    const crossMargin = userState.crossMarginSummary;
    if (crossMargin && crossMargin.withdrawable != null) {
      return parseFloat(crossMargin.withdrawable);
    }
    const marginSummary = userState.marginSummary || {};
    const accountValue = parseFloat(marginSummary.accountValue || "0");
    const totalMarginUsed = parseFloat(marginSummary.totalMarginUsed || "0");
    return accountValue - totalMarginUsed;
  }

  /**
   * Get positions, account value, and available balance in a single API call.
   * Use this in places that need multiple pieces of account data to avoid
   * making 3 separate clearinghouseState requests.
   *
   * @param {string|null} [coin=null] - Optional coin filter for positions
   * @returns {Promise<{positions: Position[], accountValue: number, availableBalance: number}>}
   */
  async getAccountSnapshot(coin = null) {
    try {
      const userState = await this.getClearinghouseState();
      return {
        positions: this._parsePositions(userState, coin),
        accountValue: this._parseAccountValue(userState),
        availableBalance: this._parseAvailableBalance(userState)
      };
    } catch (error) {
      console.error("Get account snapshot failed:", error);
      return { positions: [], accountValue: 0, availableBalance: 0 };
    }
  }

  // ==========================================================================
  // POSITION MANAGEMENT METHODS
  // ==========================================================================

  /**
   * Set leverage for a trading pair
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {number} leverage - Leverage multiplier (1-50, depending on coin)
   * @param {boolean} isCross - true for cross margin, false for isolated margin (default: true)
   * @returns {Promise<boolean>} true if successful, false otherwise
   * 
   * @example
   * // Set 10x leverage for BTC with cross margin
   * const success = await executor.setLeverage("BTC", 10, true);
   * if (success) {
   *   console.log("Leverage set to 10x (cross margin)");
   * }
   * 
   * @example
   * // Set 5x leverage for ETH with isolated margin
   * const success = await executor.setLeverage("ETH", 5, false);
   * if (success) {
   *   console.log("Leverage set to 5x (isolated margin)");
   * }
   * 
   * @example
   * // Set leverage before opening a position
   * await executor.setLeverage("BTC", 20, true);
   * await executor.placeMarketOrder("BTC", true, 0.1);
   * 
   * @example Output Format:
   * true   // Success
   * false  // Failed (invalid leverage, API error, etc.)
   * 
   * Note: Leverage limits vary by coin. BTC typically allows up to 50x,
   * while smaller coins may have lower maximum leverage.
   * 
   * Cross Margin: Shared margin across all positions (higher capital efficiency)
   * Isolated Margin: Margin is isolated per position (limits risk to that position)
   */
  async setLeverage(coin, leverage, isCross = true) {
    try {
      // Validate against coin's max allowed leverage
      const maxLev = await this.getMaxLeverage(coin);
      const effectiveLeverage = Math.min(leverage, maxLev);
      if (effectiveLeverage !== leverage) {
        console.warn(`⚠️  Requested ${leverage}x exceeds max ${maxLev}x for ${coin}, capping to ${effectiveLeverage}x`);
      }

      const leverageMode = isCross ? "cross" : "isolated";
      await this.sdk.exchange.updateLeverage(
        coin + '-PERP',
        leverageMode,
        effectiveLeverage
      );
      
      // Store the effective (capped) leverage locally.
      // The SDK call either succeeds (no throw) or throws on actual failure.
      this._leverageMap[coin] = effectiveLeverage;
      this._leverageModeMap[coin] = isCross;
      this._lastLeverageSyncAt[coin] = Date.now();
      
      console.log(`✅ Leverage set: ${coin} → ${effectiveLeverage}x (${leverageMode})`);
      // If updateLeverage throws, we land in catch. No throw means success.
      return true;
      
    } catch (error) {
      console.error(`Set leverage failed for ${coin}:`, error);
      return false;
    }
  }

  /**
   * Get the max leverage allowed for a coin from exchange metadata.
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @returns {Promise<number>} Maximum leverage allowed for the coin
   */
  async getMaxLeverage(coin) {
    try {
      const coinInfo = await this._getCoinInfo(coin);
      return parseInt(coinInfo.maxLeverage || "20");
    } catch (e) {
      console.warn(`⚠️  Could not fetch maxLeverage for ${coin}, defaulting to 20x`);
      return 20;
    }
  }

  /**
   * Get the leverage currently set for a coin.
   * Returns the value stored by setLeverage(), or fetches from open position,
   * or falls back to the coin's max leverage from exchange metadata.
   * 
   * @param {string} coin - Coin symbol
   * @returns {Promise<number>} Current leverage for the coin
   */
  async _getLeverageForCoin(coin) {
    // 1. Check locally stored value (set via setLeverage)
    if (this._leverageMap[coin]) {
      return this._leverageMap[coin];
    }

    // 2. Try to read from an existing open position
    try {
      const positions = await this.getPositions(coin);
      if (positions.length > 0 && positions[0].leverage > 0) {
        this._leverageMap[coin] = positions[0].leverage;
        return positions[0].leverage;
      }
    } catch (e) {
      // Ignore - fall through to default
    }

    // 3. Fall back to the coin's max leverage from metadata (not hardcoded 20x)
    try {
      const maxLev = await this.getMaxLeverage(coin);
      return maxLev;
    } catch (e) {
      return 20; // Absolute last resort
    }
  }

  /**
   * Close a position (full or partial) for a coin using a market order
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {number|null} size - Size to close in base currency (null = close entire position)
   *   If provided, clamped to Math.abs(position.size) to prevent over-closing.
   * @param {number} slippage - Maximum slippage tolerance (default: 0.05 = 5%)
   * @returns {Promise<OrderResult>} Order result object
   * 
   * @example
   * // Full close — close entire BTC position
   * const result = await executor.closePosition("BTC");
   * if (result.success) {
   *   console.log(`Position closed at ${result.averagePrice}`);
   * }
   * 
   * @example
   * // Partial close — close 0.005 BTC of a larger position
   * const result = await executor.closePosition("BTC", 0.005);
   * if (result.success) {
   *   console.log(`Partially closed 0.005 BTC at ${result.averagePrice}`);
   * }
   * 
   * @example
   * // Close with tighter slippage control
   * const result = await executor.closePosition("ETH", null, 0.02); // full close, 2% max slippage
   * 
   * @example
   * // Close all positions
   * const positions = await executor.getPositions();
   * for (const pos of positions) {
   *   const result = await executor.closePosition(pos.coin);
   *   console.log(`${pos.coin}: ${result.success ? 'Closed' : 'Failed'}`);
   * }
   * 
   * @example Output Format:
   * {
   *   success: true,
   *   orderId: "12345",
   *   filledSize: 0.05,              // Size that was closed
   *   averagePrice: 90628.0,         // Average fill price
   *   status: "filled",
   *   error: null,
   *   rawResponse: { ... }
   * }
   * 
   * Note: This automatically determines the direction:
   * - Long position (size > 0) → Places sell order
   * - Short position (size < 0) → Places buy order
   */
  /**
   * Close a position (full or partial) for a coin using a market order.
   *
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @param {number|null} [size=null] - Size to close (null = close entire position).
   *   If provided, clamped to Math.abs(position.size) to prevent over-closing.
   * @param {number} [slippage=0.05] - Maximum slippage tolerance (default 5%)
   * @param {Object|null} [positionOverride=null] - Pre-fetched position object
   *   ({ size, ... }) to avoid a redundant `getPositions` API call.
   *   Useful when the caller already has position data (e.g. in shutdown loops).
   * @returns {Promise<OrderResult>}
   */
  async closePosition(coin, size = null, slippage = 0.05, positionOverride = null) {
    try {
      let position = positionOverride;

      if (!position) {
        const positions = await this.getPositions(coin);
        if (positions.length === 0) {
          return new OrderResult({
            success: false,
            error: `No open position for ${coin}`
          });
        }
        position = positions[0];
      }

      const isBuy = position.size < 0;  // Close short = buy, close long = sell
      const totalSize = Math.abs(position.size);
      
      // If size provided, clamp to total position size to prevent over-closing
      const closeSize = (size != null && size > 0)
        ? Math.min(size, totalSize)
        : totalSize;
      const sizeError = this._validatePositiveSize(closeSize, coin, 'close');
      if (sizeError) return sizeError;
      
      return await this.placeMarketOrder(coin, isBuy, closeSize, true, slippage);
      
    } catch (error) {
      console.error("Close position failed:", error);
      return new OrderResult({ success: false, error: error.message });
    }
  }

  /**
   * Get maximum trade sizes for a coin based on available balance
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
   * @returns {Promise<{maxLong: number, maxShort: number}>} Max sizes for long and short
   * 
   * @example
   * const { maxLong, maxShort } = await executor.getMaxTradeSizes("BTC");
   * console.log(`Max BTC long: ${maxLong} BTC`);
   * console.log(`Max BTC short: ${maxShort} BTC`);
   * 
   * @example
   * // Use max size to go all-in
   * const { maxLong } = await executor.getMaxTradeSizes("BTC");
   * await executor.placeMarketOrder("BTC", true, maxLong);
   * 
   * @example
   * // Calculate position size as percentage of max
   * const { maxLong } = await executor.getMaxTradeSizes("ETH");
   * const sizeToTrade = maxLong * 0.5; // Use 50% of max
   * await executor.placeMarketOrder("ETH", true, sizeToTrade);
   * 
   * @example Output Format:
   * {
   *   maxLong: 0.15,      // Maximum long position size in base currency
   *   maxShort: 0.15      // Maximum short position size in base currency
   * }
   * 
   * Calculation:
   * 1. Gets available balance
   * 2. Multiplies by maximum leverage for the coin
   * 3. Divides by current price
   * 4. Rounds to valid size decimals
   * 
   * Example: $1000 balance, 10x leverage, BTC at $90,000
   * → Max notional: $10,000
   * → Max size: 10,000 / 90,000 = 0.11111 BTC
   * → Rounded: 0.1111 BTC (to 4 decimals)
   */
  async getMaxTradeSizes(coin) {
    try {
      const coinInfo = await this._getCoinInfo(coin);
      const rawBalance = await this.getAvailableBalance();
      const numericBalance = Number(rawBalance);
      const availableBalance = Number.isFinite(numericBalance) ? Math.max(0, numericBalance) : 0;
      const allMids = await getAllMids();
      const price = parseFloat(allMids[coin] || "0");
      
      if (price === 0) {
        return { maxLong: 0, maxShort: 0 };
      }
      
      // Use the user's set leverage, capped at the coin's max allowed leverage
      const userLeverage = await this._getLeverageForCoin(coin);
      const maxLev = parseInt(coinInfo.maxLeverage || "20");
      const leverage = Math.max(0, Math.min(userLeverage, maxLev));
      if (availableBalance <= 0 || leverage <= 0) {
        return { maxLong: 0, maxShort: 0 };
      }

      // Fee-aware max size: reserve balance for the estimated taker fee.
      // maxNotional = availableBalance * leverage
      // fee = maxNotional * takerFeeRate
      // We need: (maxNotional / leverage) + (maxNotional * takerFeeRate) <= availableBalance
      // Solving: maxNotional * (1/leverage + takerFeeRate) <= availableBalance
      // => maxNotional <= availableBalance / (1/leverage + takerFeeRate)
      const denominator = (1 / leverage) + this.takerFeeRate;
      const maxNotional = denominator > 0 ? availableBalance / denominator : 0;
      const maxSize = Math.max(0, maxNotional / price);
      
      const szDecimals = coinInfo.szDecimals ?? 4;
      const roundedSize = parseFloat(maxSize.toFixed(szDecimals));
      const safeSize = Number.isFinite(roundedSize) ? Math.max(0, roundedSize) : 0;
      
      return {
        maxLong: safeSize,
        maxShort: safeSize
      };
      
    } catch (error) {
      console.error("Get max trade sizes failed:", error);
      return { maxLong: 0, maxShort: 0 };
    }
  }
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
  OrderExecutor,
  OrderResult,
  Position,
  OpenOrder,
  OrderSide,
  OrderType,
  TriggerType
};
