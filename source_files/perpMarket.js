import { hyperliquidInfoRequest as hyperliquidRequest } from './apiClient.js';

/**
 * Get all mid prices for all trading pairs
 * @param {string} [dex=""] - Optional: Perp dex name; empty for first perp dex (includes spot mids)
 * @returns {Promise<Object>} Object mapping coin symbols to mid prices (as strings)
 * 
 * @example
 * const mids = await getAllMids();
 * console.log(mids.BTC); // "90518.5"
 * console.log(mids.ETH); // "3117.45"
 * 
 * @example Output Format:
 * {
 *   "BTC": "90518.5",
 *   "ETH": "3117.45",
 *   "SOL": "139.835",
 *   "0G": "0.90136",
 *   "2Z": "0.11947",
 *   "@1": "15.0345",
 *   "@10": "0.00003116",
 *   "AAVE": "165.53",
 *   "ACE": "0.2801",
 *   // ... hundreds more coins
 * }
 * 
 * Note: All prices are returned as strings. Convert to number if needed:
 * const btcPrice = parseFloat(mids.BTC);
 */
async function getAllMids(dex = "") {
  const body = { type: "allMids", dex };
  return await hyperliquidRequest(body);
}

/**
 * Get OHLCV candle snapshot data for a trading pair
 * @param {string} coin - Trading pair symbol (e.g., "BTC", "ETH")
 * @param {string} interval - Candle interval: "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "3d", "1w", "1M"
 * @param {number} startTime - Start time in milliseconds (inclusive)
 * @param {number} endTime - End time in milliseconds (inclusive)
 * @returns {Promise<Array<Object>>} Array of candle objects sorted by timestamp ascending
 * 
 * @example
 * const now = Date.now();
 * const oneDayAgo = now - (24 * 60 * 60 * 1000);
 * const candles = await getCandleSnapshot("BTC", "1h", oneDayAgo, now);
 * console.log(`Got ${candles.length} candles`); // e.g., "Got 25 candles"
 * 
 * @example Output Format:
 * [
 *   {
 *     timestampOpen: 1767862800000,
 *     timestampClose: 1767866400000,
 *     open: 86500.5,
 *     high: 86750.2,
 *     low: 86400.1,
 *     close: 86600.8,
 *     volume: 1250.5,
 *     trades: 150,
 *     symbol: "BTC",
 *     interval: "1h"
 *   },
 *   // ... more candles sorted by timestampOpen ascending
 * ]
 */
async function getCandleSnapshot(coin, interval, startTime, endTime) {
  const body = {
    type: "candleSnapshot",
    req: { coin, interval, startTime, endTime }
  };
  const response = await hyperliquidRequest(body);
  const processed = response.map(c => ({
    timestampOpen: c.t,
    timestampClose: c.T,
    open: parseFloat(c.o),
    high: parseFloat(c.h),
    low: parseFloat(c.l),
    close: parseFloat(c.c),
    volume: parseFloat(c.v),
    trades: c.n,
    symbol: c.s,
    interval: c.i
  })).sort((a, b) => a.timestampOpen - b.timestampOpen);
  return processed;
}

/**
 * Get 24h ticker data for a trading pair
 * @param {string} coin - Trading pair symbol (e.g., "BTC", "ETH")
 * @returns {Promise<Object>} Dictionary with ticker information including 24h stats
 * 
 * @example
 * const ticker = await getTicker("BTC");
 * console.log(`24h Volume: ${ticker.volume}`);
 * console.log(`24h Change: ${ticker.change_percent}%`);
 * console.log(`Current Price: $${ticker.price}`);
 * 
 * @example Output Format:
 * {
 *   coin: "BTC",
 *   price: 90518.5,           // Current mid price
 *   open: 90677.0,            // Opening price 24h ago
 *   high: 91000.0,            // Highest price in last 24h
 *   low: 90000.0,             // Lowest price in last 24h
 *   volume: 1250.5,           // 24h trading volume
 *   change: -158.5,           // Price change (current - open)
 *   change_percent: -1.75     // Percentage change (rounded to 2 decimals)
 * }
 */
async function getTicker(coin) {
  try {
    // Get current mid price
    const mids = await getAllMids();
    const currentPrice = parseFloat(mids[coin] || "0");
    
    if (currentPrice === 0) {
      return {
        coin: coin,
        price: 0,
        open: 0,
        high: 0,
        low: 0,
        volume: 0,
        change: 0,
        change_percent: 0
      };
    }
    
    // Get 24h candle for volume and change
    const endTime = Date.now();
    const startTime = endTime - (24 * 60 * 60 * 1000); // 24 hours ago
    
    const candles = await getCandleSnapshot(coin, "1d", startTime, endTime);
    
    if (candles && candles.length > 0) {
      const candle = candles[candles.length - 1]; // Get the most recent candle
      const openPrice = candle.open || currentPrice;
      const high = candle.high || currentPrice;
      const low = candle.low || currentPrice;
      const volume = candle.volume || 0;
      
      const change = currentPrice - openPrice;
      const changePercent = openPrice > 0 ? (change / openPrice * 100) : 0;
      
      return {
        coin: coin,
        price: currentPrice,
        open: openPrice,
        high: high,
        low: low,
        volume: volume,
        change: change,
        change_percent: Math.round(changePercent * 100) / 100 // Round to 2 decimals
      };
    }
    
    // Fallback if no candles available
    return {
      coin: coin,
      price: currentPrice,
      open: 0,
      high: 0,
      low: 0,
      volume: 0,
      change: 0,
      change_percent: 0
    };
    
  } catch (error) {
    console.error(`Failed to get ticker for ${coin}:`, error);
    // Return minimal ticker on error
    const mids = await getAllMids();
    const currentPrice = parseFloat(mids[coin] || "0");
    return {
      coin: coin,
      price: currentPrice,
      open: 0,
      high: 0,
      low: 0,
      volume: 0,
      change: 0,
      change_percent: 0
    };
  }
}

/**
 * Get L2 order book snapshot (up to 20 levels per side)
 * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
 * @param {number|null} [nSigFigs=5] - Optional: Significant figures (2-5 or null for full precision)
 * @param {number} [mantissa] - Optional: 1, 2, or 5 (only used if nSigFigs=5)
 * @returns {Promise<Object>} Processed order book with bids/asks arrays
 * 
 * @example
 * const book = await getL2Book("BTC");
 * console.log("Best bid:", book.bids[0]); // { price: 90518, size: 34.6921, n: 61 }
 * console.log("Best ask:", book.asks[0]);
 * 
 * @example Output Format:
 * {
 *   coin: "BTC",
 *   time: 1767947582743,
 *   bids: [
 *     { price: 90518, size: 34.6921, n: 61 },  // n = number of orders at this level
 *     { price: 90517, size: 12.5, n: 3 },
 *     // ... up to 20 levels, sorted descending by price
 *   ],
 *   asks: [
 *     { price: 90519, size: 25.3, n: 45 },
 *     { price: 90520, size: 18.7, n: 12 },
 *     // ... up to 20 levels, sorted ascending by price
 *   ]
 * }
 */
async function getL2Book(coin, nSigFigs = 5, mantissa = undefined) {
  const body = { type: "l2Book", coin };
  if (nSigFigs !== undefined && nSigFigs !== null) body.nSigFigs = nSigFigs;
  if (mantissa !== undefined) body.mantissa = mantissa;

  const response = await hyperliquidRequest(body);
  const bids = response.levels[0].map(l => ({
    price: parseFloat(l.px),
    size: parseFloat(l.sz),
    n: l.n
  })).sort((a, b) => b.price - a.price);

  const asks = response.levels[1].map(l => ({
    price: parseFloat(l.px),
    size: parseFloat(l.sz),
    n: l.n
  })).sort((a, b) => a.price - b.price);

  return { coin: response.coin, time: response.time, bids, asks };
}

/**
 * Get funding history for a coin
 * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
 * @param {number} startTime - Start time in milliseconds (inclusive)
 * @param {number} [endTime=Date.now()] - End time in milliseconds (inclusive), defaults to current time
 * @returns {Promise<Array<Object>>} Array of funding entries sorted by timestamp ascending
 * 
 * @example
 * const oneDayAgo = Date.now() - (24 * 60 * 60 * 1000);
 * const funding = await getFundingHistory("BTC", oneDayAgo);
 * console.log(`Got ${funding.length} funding entries`);
 * 
 * @example Output Format:
 * [
 *   {
 *     timestamp: 1767862800077,
 *     fundingRate: 0.0000125,
 *     premium: -0.0002621123
 *   },
 *   {
 *     timestamp: 1767866400037,
 *     fundingRate: 0.0000125,
 *     premium: -0.0002856393
 *   },
 *   {
 *     timestamp: 1767870000015,
 *     fundingRate: 0.0000125,
 *     premium: -0.0002408339
 *   },
 *   // ... more entries sorted by timestamp ascending
 * ]
 */
async function getFundingHistory(coin, startTime, endTime = Date.now()) {
  const body = { type: "fundingHistory", coin, startTime, endTime };
  const response = await hyperliquidRequest(body);
  return response.map(f => ({
    timestamp: f.time,
    fundingRate: parseFloat(f.fundingRate),
    premium: parseFloat(f.premium)
  })).sort((a, b) => a.timestamp - b.timestamp);
}

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
async function getMetaAndAssetCtxs() {
  const body = { type: "metaAndAssetCtxs" };
  const response = await hyperliquidRequest(body);
  const assetCtxs = response[1].map(ctx => ({
    ...ctx,
    openInterest: parseFloat(ctx.openInterest || 0),
    markPx: parseFloat(ctx.markPx),
    funding: parseFloat(ctx.funding)
  }));
  return { meta: response[0], assetCtxs };
}

/**
 * Get recent trades for a coin (up to 500)
 * @param {string} coin - Coin symbol (e.g., "BTC", "ETH")
 * @returns {Promise<Array<Object>>} Array of recent trades sorted by timestamp descending (newest first)
 * 
 * @example
 * const trades = await getRecentTrades("BTC");
 * console.log(`Got ${trades.length} recent trades`);
 * console.log("Latest trade:", trades[0]);
 * 
 * @example Output Format:
 * [
 *   {
 *     timestamp: 1767947582743,
 *     price: 90563,
 *     size: 0.011,
 *     side: "Buy",  // or "Sell"
 *     hash: "0x46ee5154184941424868043301506602057e0039b34c6014eab6fca6d74d1b2c"
 *   },
 *   {
 *     timestamp: 1767947582743,
 *     price: 90563,
 *     size: 0.0122,
 *     side: "Buy",
 *     hash: "0xc8cd004c9872f4d7ca4604330150660205790032337613a96c95ab9f5776cec2"
 *   },
 *   {
 *     timestamp: 1767947582622,
 *     price: 90557,
 *     size: 0.011,
 *     side: "Buy",
 *     hash: "0x9489357b8ef338bb96020433015065020ae6006129f6578d3851e0ce4df712a6"
 *   },
 *   // ... up to 500 trades, sorted by timestamp descending
 * ]
 */
async function getRecentTrades(coin) {
  const body = { type: "recentTrades", coin };
  const response = await hyperliquidRequest(body);
  return response.map(t => ({
    timestamp: t.time,
    price: parseFloat(t.px),
    size: parseFloat(t.sz),
    side: t.side === "B" ? "Buy" : "Sell",
    hash: t.hash
  })).sort((a, b) => b.timestamp - a.timestamp);
}

/**
 * Get predicted fundings across venues
 * @returns {Promise<Array>} Array of tuples [coin, [funding arrays]] for all coins
 * 
 * @example
 * const predicted = await getPredictedFundings();
 * const btcFunding = predicted.find(([coin]) => coin === "BTC");
 * console.log("BTC predicted funding:", btcFunding);
 * 
 * @example Output Format:
 * [
 *   ["BTC", [[/* funding data *\/], [/* funding data *\/], [/* funding data *\/]]],
 *   ["ETH", [[/* funding data *\/], [/* funding data *\/], [/* funding data *\/]]],
 *   ["SOL", [[/* funding data *\/], [/* funding data *\/], [/* funding data *\/]]],
 *   // ... one entry per coin
 * ]
 */
async function getPredictedFundings() {
  const body = { type: "predictedFundings" };
  return await hyperliquidRequest(body);
}

/**
 * Get list of perps at open interest cap
 * @param {string} [dex=""] - Optional: Perp dex name; empty string for first perp dex
 * @returns {Promise<Array<string>>} Array of coin symbols that are at their open interest cap
 * 
 * @example
 * const atCap = await getPerpsAtOpenInterestCap();
 * console.log("Coins at OI cap:", atCap); // e.g., ["CANTO", "FTM", "JELLY", "LOOM", "RLB"]
 * 
 * @example Output Format:
 * ["CANTO", "FTM", "JELLY", "LOOM", "RLB"]
 * // Empty array [] if no coins are at cap
 */
async function getPerpsAtOpenInterestCap(dex = "") {
  const body = { type: "perpsAtOpenInterestCap", dex };
  return await hyperliquidRequest(body);
}

export {
  getAllMids,
  getCandleSnapshot,
  getTicker,
  getL2Book,
  getFundingHistory,
  getMetaAndAssetCtxs,
  getRecentTrades,
  getPredictedFundings,
  getPerpsAtOpenInterestCap,
};
