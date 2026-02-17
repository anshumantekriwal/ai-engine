import { hyperliquidInfoRequest as hyperliquidRequest } from './apiClient.js';

/**
 * Get current open orders for a user
 * @param {string} user - User address in 42-character hexadecimal format (e.g., "0x0000000000000000000000000000000000000000")
 * @param {string} [dex=""] - Optional: Perp dex name; empty string for first perp dex (includes spot orders)
 * @returns {Promise<Array<Object>>} Array of open orders sorted by timestamp descending
 * 
 * @example
 * const orders = await getOpenOrders("0xf3F496C9486BE5924a93D67e98298733Bb47057c");
 * console.log(`You have ${orders.length} open orders`);
 * 
 * @example Output Format:
 * [
 *   {
 *     oid: "12345",              // Order ID
 *     coin: "BTC",
 *     side: "Buy",               // or "Sell"
 *     limitPx: 90518.5,          // Limit price
 *     sz: 0.01,                  // Order size
 *     timestamp: 1767947582743
 *   },
 *   // ... more orders sorted by timestamp descending
 * ]
 * // Empty array [] if no open orders
 */
async function getOpenOrders(user, dex = "") {
    const body = { type: "openOrders", user, dex };
    const response = await hyperliquidRequest(body);
    return (response || []).map(order => ({
      oid: order.oid,
      coin: order.coin,
      side: order.side === "B" ? "Buy" : "Sell",
      limitPx: parseFloat(order.limitPx),
      sz: parseFloat(order.sz),
      timestamp: order.timestamp,
      // Add trigger fields if needed
    })).sort((a, b) => b.timestamp - a.timestamp);
  }
  
  /**
   * Get open orders with frontend/trigger details
   * @param {string} user - User address in 42-character hexadecimal format
   * @param {string} [dex=""] - Optional: Perp dex name; empty string for first perp dex
   * @returns {Promise<Array<Object>>} Array of open orders with trigger information
   * 
   * @example
   * const orders = await getFrontendOpenOrders("0x...");
   * const triggerOrders = orders.filter(o => o.isTrigger);
   * 
   * @example Output Format:
   * [
   *   {
   *     oid: "12345",
   *     coin: "BTC",
   *     side: "Buy",
   *     limitPx: 90518.5,
   *     sz: 0.01,
   *     isTrigger: false,        // true if this is a stop-loss/take-profit order
   *     triggerPx: null,         // Trigger price if isTrigger is true
   *     timestamp: 1767947582743
   *   },
   *   // ... more orders
   * ]
   */
  async function getFrontendOpenOrders(user, dex = "") {
    const body = { type: "frontendOpenOrders", user, dex };
    const response = await hyperliquidRequest(body);
    return (response || []).map(order => ({
      oid: order.oid,
      coin: order.coin,
      side: order.side === "B" ? "Buy" : "Sell",
      limitPx: parseFloat(order.limitPx),
      sz: parseFloat(order.sz),
      isTrigger: order.isTrigger || false,
      triggerPx: order.triggerPx ? parseFloat(order.triggerPx) : null,
      timestamp: order.timestamp
    })).sort((a, b) => b.timestamp - a.timestamp);
  }
  
  /**
   * Get recent fills (executed trades, up to 2000 most recent)
   * @param {string} user - User address in 42-character hexadecimal format
   * @param {boolean} [aggregateByTime=false] - When true, partial fills are combined when a crossing order gets filled by multiple different resting orders
   * @returns {Promise<Array<Object>>} Array of fills sorted by timestamp descending (newest first)
   * 
   * @example
   * const fills = await getUserFills("0x...");
   * console.log(`Got ${fills.length} recent fills`); // Up to 2000
   * 
   * @example Output Format:
   * [
   *   {
   *     coin: "BTC",
   *     px: 90563,               // Execution price
   *     sz: 0.011,              // Size filled
   *     side: "Buy",            // or "Sell"
   *     time: 1767947582743,    // Timestamp
   *     fee: 0.5,               // Fee paid
   *     closedPnl: 0.0,         // Realized PnL if closing position
   *     oid: "12345",           // Order ID
   *     hash: "0x..."           // Transaction hash
   *   },
   *   // ... up to 2000 fills, sorted by time descending
   * ]
   */
  async function getUserFills(user, aggregateByTime = false) {
    const body = { type: "userFills", user, aggregateByTime };
    const response = await hyperliquidRequest(body);
    return (response || []).map(fill => ({
      coin: fill.coin,
      px: parseFloat(fill.px),
      sz: parseFloat(fill.sz),
      side: fill.side === "B" ? "Buy" : "Sell",
      time: fill.time,
      fee: parseFloat(fill.fee || 0),
      closedPnl: parseFloat(fill.closedPnl || 0),
      oid: fill.oid,
      hash: fill.hash
    })).sort((a, b) => b.time - a.time);
  }
  
  /**
   * Get fills in time range (up to 2000 per response, only 10000 most recent fills available)
   * @param {string} user - User address in 42-character hexadecimal format
   * @param {number} startTime - Start time in milliseconds (inclusive)
   * @param {number} [endTime=Date.now()] - End time in milliseconds (inclusive), defaults to current time
   * @param {boolean} [aggregateByTime=false] - When true, partial fills are combined
   * @returns {Promise<Array<Object>>} Array of fills sorted by timestamp descending
   * 
   * @example
   * const oneDayAgo = Date.now() - (24 * 60 * 60 * 1000);
   * const fills = await getUserFillsByTime("0x...", oneDayAgo);
   * console.log(`Got ${fills.length} fills in last 24h`);
   * 
   * @example Output Format:
   * [
   *   {
   *     coin: "BTC",
   *     px: 90563,
   *     sz: 0.011,
   *     side: "Buy",
   *     time: 1767947582743,
   *     fee: 0.5,
   *     closedPnl: 0.0,
   *     oid: "12345"
   *   },
   *   // ... up to 2000 fills per response
   * ]
   */
  async function getUserFillsByTime(user, startTime, endTime = Date.now(), aggregateByTime = false) {
    const body = { type: "userFillsByTime", user, startTime, endTime, aggregateByTime };
    const response = await hyperliquidRequest(body);
    return (response || []).map(fill => ({ /* same as getUserFills */ 
      coin: fill.coin,
      px: parseFloat(fill.px),
      sz: parseFloat(fill.sz),
      side: fill.side === "B" ? "Buy" : "Sell",
      time: fill.time,
      fee: parseFloat(fill.fee || 0),
      closedPnl: parseFloat(fill.closedPnl || 0),
      oid: fill.oid
    })).sort((a, b) => b.time - a.time);
  }
  
  /**
   * Get historical orders (up to 2000 most recent)
   * @param {string} user - User address in 42-character hexadecimal format
   * @returns {Promise<Array<Object>>} Array of historical orders sorted by timestamp descending
   * 
   * @example
   * const orders = await getHistoricalOrders("0x...");
   * console.log(`Got ${orders.length} historical orders`);
   * 
   * @example Output Format:
   * [
   *   {
   *     oid: "12345",
   *     coin: "BTC",
   *     side: "Buy",
   *     limitPx: 90518.5,
   *     sz: 0.01,
   *     status: "filled",       // "open", "filled", "canceled", "rejected", etc.
   *     timestamp: 1767947582743
   *   },
   *   // ... up to 2000 orders, sorted by timestamp descending
   * ]
   */
  async function getHistoricalOrders(user) {
    const body = { type: "historicalOrders", user };
    const response = await hyperliquidRequest(body);
    return (response || []).map(order => ({
      oid: order.oid,
      coin: order.coin,
      side: order.side === "B" ? "Buy" : "Sell",
      limitPx: parseFloat(order.limitPx),
      sz: parseFloat(order.sz),
      status: order.status,
      timestamp: order.timestamp
    })).sort((a, b) => b.timestamp - a.timestamp);
  }
  
  /**
   * Get portfolio PnL + account value history
   * @param {string} user - User address in 42-character hexadecimal format
   * @returns {Promise<Array>} Array of tuples [period, { accountValueHistory, pnlHistory, vlm }]
   * 
   * @example
   * const portfolio = await getPortfolio("0x...");
   * const allTime = portfolio.find(([period]) => period === "allTime");
   * console.log("All-time volume:", allTime[1].vlm);
   * 
   * @example Output Format:
   * [
   *   [
   *     "day",
   *     {
   *       accountValueHistory: [[timestamp, "accountValue"], ...],
   *       pnlHistory: [[timestamp, "pnl"], ...],
   *       vlm: "0.0"  // Volume in USDC
   *     }
   *   ],
   *   [
   *     "week",
   *     { accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }
   *   ],
   *   [
   *     "month",
   *     { accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }
   *   ],
   *   [
   *     "allTime",
   *     {
   *       accountValueHistory: [Array],
   *       pnlHistory: [Array],
   *       vlm: "3008970620.4899997711"  // Total volume
   *     }
   *   ],
   *   [
   *     "perpDay",
   *     { accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }
   *   ],
   *   [
   *     "perpWeek",
   *     { accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }
   *   ],
   *   [
   *     "perpMonth",
   *     { accountValueHistory: [Array], pnlHistory: [Array], vlm: "0.0" }
   *   ],
   *   [
   *     "perpAllTime",
   *     {
   *       accountValueHistory: [Array],
   *       pnlHistory: [Array],
   *       vlm: "3008749918.9499998093"  // Perp-only volume
   *     }
   *   ]
   * ]
   */
  async function getPortfolio(user) {
    const body = { type: "portfolio", user };
    return await hyperliquidRequest(body);  // Returns structured PnL data
  }
  
  /**
   * Get sub-accounts (margin + spot balances)
   * @param {string} user - User address in 42-character hexadecimal format
   * @returns {Promise<Object|null>} Balances/margin info, or null if no sub-accounts
   * 
   * @example
   * const subAccounts = await getSubAccounts("0x...");
   * if (subAccounts) {
   *   console.log("Sub-accounts:", subAccounts);
   * } else {
   *   console.log("No sub-accounts");
   * }
   * 
   * @example Output Format:
   * null  // If no sub-accounts
   * // OR object with balances/margin information if sub-accounts exist
   */
  async function getSubAccounts(user) {
    const body = { type: "subAccounts", user };
    return await hyperliquidRequest(body);
  }
  
  /**
   * Get user fee rates, volume tiers, and fee schedule
   * @param {string} user - User address in 42-character hexadecimal format
   * @returns {Promise<Object>} Object containing fee rates, volume data, and fee schedule
   * 
   * @example
   * const fees = await getUserFees("0x...");
   * console.log("Your maker rate:", fees.userAddRate); // "0.00015"
   * console.log("Your taker rate:", fees.userCrossRate); // "0.00045"
   * 
   * @example Output Format:
   * {
   *   dailyUserVlm: [
   *     {
   *       date: "2026-01-09",
   *       userCross: "0.0",      // Your taker volume
   *       userAdd: "0.0",        // Your maker volume
   *       exchange: "6465965874.7600002289"  // Total exchange volume
   *     },
   *     // ... daily volume entries
   *   ],
   *   feeSchedule: {
   *     cross: "0.00045",        // Base taker fee
   *     add: "0.00015",          // Base maker fee
   *     spotCross: "0.0007",     // Spot taker fee
   *     spotAdd: "0.0004",       // Spot maker fee
   *     tiers: {
   *       vip: [/* VIP tier objects *\/],
   *       mm: [/* Market maker tier objects *\/]
   *     },
   *     referralDiscount: "0.04",
   *     stakingDiscountTiers: [/* staking discount tiers *\/]
   *   },
   *   userCrossRate: "0.00045",      // Your effective taker rate
   *   userAddRate: "0.00015",        // Your effective maker rate
   *   userSpotCrossRate: "0.0007",  // Your spot taker rate
   *   userSpotAddRate: "0.0004",    // Your spot maker rate
   *   activeReferralDiscount: "0.0",
   *   trial: null,
   *   feeTrialEscrow: "0.0",
   *   nextTrialAvailableTimestamp: null,
   *   stakingLink: null,
   *   activeStakingDiscount: {
   *     bpsOfMaxSupply: "0.0",
   *     discount: "0.0"
   *   }
   * }
   */
  async function getUserFees(user) {
    const body = { type: "userFees", user };
    return await hyperliquidRequest(body);
  }
  
// Export all user data functions
export {
  getOpenOrders,
  getFrontendOpenOrders,
  getUserFills,
  getUserFillsByTime,
  getHistoricalOrders,
  getPortfolio,
  getSubAccounts,
  getUserFees,
};