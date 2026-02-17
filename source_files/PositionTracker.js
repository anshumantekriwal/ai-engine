import fs from 'fs';
import fsp from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { MAX_HISTORY_ENTRIES, MAX_TRADE_ENTRIES } from './config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * PositionTracker - Local file-based position tracking with PnL calculation
 * 
 * Tracks position lifecycles and calculates accurate PnL including fees.
 * Works alongside Supabase logging for local backup and quick access.
 */
class PositionTracker {
  /**
   * @param {string} agentId
   * @param {Object} [options]
   * @param {Function} [options.onSlTpFill] - Callback when a SL/TP fill is detected.
   *   Receives { coin, side, size, price, fee, orderId, orderType, cloid, triggerType }.
   * @param {number} [options.defaultTakerFeeRate=0.00045] - Default taker fee rate
   *   used to estimate exit fees for externally closed positions and opposite-side
   *   auto-closes where the actual fee is unknown.
   */
  constructor(agentId, { onSlTpFill, defaultTakerFeeRate = 0.00045 } = {}) {
    this.agentId = agentId;
    this.positionsDir = path.join(__dirname, 'positions');
    
    // Default fee rate for estimated exits
    this.defaultTakerFeeRate = defaultTakerFeeRate;

    // SL/TP fill detection
    this.onSlTpFill = onSlTpFill || null;
    this.pendingSlTp = {};          // { [orderId]: { coin, cloid, orderType, size, triggerPrice, side } }
    this.pendingSlTpByCloid = {};   // { [cloid]: orderId } — reverse index
    
    // File paths
    this.positionsFile = path.join(this.positionsDir, `${agentId}_positions.json`);
    this.historyFile = path.join(this.positionsDir, `${agentId}_history.json`);
    this.tradesFile = path.join(this.positionsDir, `${agentId}_trades.json`);
    
    // Ensure directory exists
    if (!fs.existsSync(this.positionsDir)) {
      fs.mkdirSync(this.positionsDir, { recursive: true });
    }
    
    // Write serialization: chain promises per file to avoid overlapping async writes
    this._writeQueue = {
      positions: Promise.resolve(),
      history: Promise.resolve(),
      trades: Promise.resolve(),
    };

    // Initialize files if they don't exist
    this._initFiles();
    
    // Load into memory
    this.openPositions = this._loadPositions();
    this.closedPositions = this._loadHistory();
    this.trades = this._loadTrades();
  }
  
  _initFiles() {
    if (!fs.existsSync(this.positionsFile)) {
      fs.writeFileSync(this.positionsFile, JSON.stringify({}, null, 2));
    }
    if (!fs.existsSync(this.historyFile)) {
      fs.writeFileSync(this.historyFile, JSON.stringify([], null, 2));
    }
    if (!fs.existsSync(this.tradesFile)) {
      fs.writeFileSync(this.tradesFile, JSON.stringify([], null, 2));
    }
  }
  
  _loadPositions() {
    try {
      return JSON.parse(fs.readFileSync(this.positionsFile, 'utf8'));
    } catch (error) {
      console.error('Error loading positions:', error);
      return {};
    }
  }
  
  _loadHistory() {
    try {
      return JSON.parse(fs.readFileSync(this.historyFile, 'utf8'));
    } catch (error) {
      console.error('Error loading history:', error);
      return [];
    }
  }
  
  _loadTrades() {
    try {
      return JSON.parse(fs.readFileSync(this.tradesFile, 'utf8'));
    } catch (error) {
      console.error('Error loading trades:', error);
      return [];
    }
  }
  
  _savePositions() {
    const data = JSON.stringify(this.openPositions, null, 2);
    this._writeQueue.positions = this._writeQueue.positions
      .then(() => fsp.writeFile(this.positionsFile, data))
      .catch(error => console.error('Error saving positions:', error));
  }
  
  _saveHistory() {
    // Cap before persisting
    if (this.closedPositions.length > MAX_HISTORY_ENTRIES) {
      this.closedPositions = this.closedPositions.slice(-MAX_HISTORY_ENTRIES);
    }
    const data = JSON.stringify(this.closedPositions, null, 2);
    this._writeQueue.history = this._writeQueue.history
      .then(() => fsp.writeFile(this.historyFile, data))
      .catch(error => console.error('Error saving history:', error));
  }
  
  _saveTrades() {
    // Cap before persisting
    if (this.trades.length > MAX_TRADE_ENTRIES) {
      this.trades = this.trades.slice(-MAX_TRADE_ENTRIES);
    }
    const data = JSON.stringify(this.trades, null, 2);
    this._writeQueue.trades = this._writeQueue.trades
      .then(() => fsp.writeFile(this.tradesFile, data))
      .catch(error => console.error('Error saving trades:', error));
  }
  
  /**
   * Open a new position
   */
  openPosition(coin, side, size, price, orderType, orderId, fee, feeRate) {
    // B4: Input validation guards
    if (!size || size <= 0) {
      console.warn(`⚠️  PositionTracker.openPosition: invalid size ${size} for ${coin}, ignoring`);
      return null;
    }
    if (!price || price <= 0) {
      console.warn(`⚠️  PositionTracker.openPosition: invalid price ${price} for ${coin}, ignoring`);
      return null;
    }
    
    const timestamp = new Date().toISOString();
    const existing = this.openPositions[coin];
    
    // B5: If opposite-side position exists, auto-close it before opening new one
    if (existing && existing.entry.side !== side) {
      console.warn(`⚠️  PositionTracker: ${coin} has ${existing.entry.side.toUpperCase()} position but opening ${side.toUpperCase()}. Auto-closing old position at $${price.toFixed(2)}.`);
      
      // Close the existing position at the new trade's price as an estimated external close
      // Estimate exit fee using defaultTakerFeeRate to avoid PnL overstatement
      const estimatedExitFee = existing.entry.size * price * this.defaultTakerFeeRate;

      const closedPos = JSON.parse(JSON.stringify(existing));
      closedPos.status = 'closed_opposite_overwrite';
      closedPos.closedAt = timestamp;
      closedPos.updatedAt = timestamp;
      closedPos.exit = {
        side: existing.entry.side === 'buy' ? 'sell' : 'buy',
        size: existing.entry.size,
        price: price,  // Use the new trade's price as best estimate
        fee: estimatedExitFee,
        feeRate: this.defaultTakerFeeRate,
        orderType: 'estimated_close',
        orderId: 'opposite_overwrite',
        timestamp
      };
      closedPos.pnl = this._calculatePnl(closedPos);
      
      this.closedPositions.push(closedPos);
      delete this.openPositions[coin];
      
      this._savePositions();
      this._saveHistory();
      
      this._logTrade({
        positionId: closedPos.positionId,
        coin,
        type: 'exit_opposite_overwrite',
        side: closedPos.exit.side,
        size: closedPos.entry.size,
        price,
        fee: estimatedExitFee,
        feeRate: this.defaultTakerFeeRate,
        orderType: 'estimated_close',
        orderId: 'opposite_overwrite',
        timestamp,
        pnl: closedPos.pnl
      });
      
      console.log(`🏁 Auto-closed ${coin} ${existing.entry.side.toUpperCase()} | Estimated Net PnL: $${closedPos.pnl.net.toFixed(4)}`);
      // Fall through to create the new position below
    }
    
    // Re-check after potential opposite-side close
    const currentExisting = this.openPositions[coin];
    
    // If adding to an existing same-side position, calculate weighted average entry
    if (currentExisting && currentExisting.entry.side === side) {
      const oldSize = currentExisting.entry.size;
      const oldPrice = currentExisting.entry.price;
      const oldFee = currentExisting.entry.fee;
      const newSize = oldSize + size;
      const avgPrice = ((oldPrice * oldSize) + (price * size)) / newSize;
      const totalFee = oldFee + fee;
      
      currentExisting.entry.size = newSize;
      currentExisting.entry.price = avgPrice;
      currentExisting.entry.fee = totalFee;
      currentExisting.updatedAt = timestamp;
      
      this._savePositions();
      
      this._logTrade({
        positionId: currentExisting.positionId,
        coin,
        type: 'add',
        side,
        size,
        price,
        fee,
        feeRate,
        orderType,
        orderId,
        timestamp
      });
      
      console.log(`📍 Position added: ${coin} ${side.toUpperCase()} +${size} @ $${price.toFixed(2)} → total ${newSize} @ avg $${avgPrice.toFixed(2)} (Fee: +$${fee.toFixed(4)})`);
      
      return currentExisting.positionId;
    }
    
    // New position
    const positionId = `${this.agentId}_${coin}_${Date.now()}`;
    
    const position = {
      positionId,
      coin,
      status: 'open',
      
      // Entry details
      entry: {
        side,
        size,
        price,
        fee,
        feeRate,
        orderType,
        orderId,
        timestamp
      },
      
      // Exit details (null until closed)
      exit: null,
      
      // PnL (calculated on close)
      pnl: null,
      
      createdAt: timestamp,
      updatedAt: timestamp
    };
    
    // Store in memory and file
    this.openPositions[coin] = position;
    this._savePositions();
    
    // Log trade
    this._logTrade({
      positionId,
      coin,
      type: 'entry',
      side,
      size,
      price,
      fee,
      feeRate,
      orderType,
      orderId,
      timestamp
    });
    
    console.log(`📍 Position tracked: ${coin} ${side.toUpperCase()} ${size} @ $${price.toFixed(2)} (Fee: $${fee.toFixed(4)})`);
    
    return positionId;
  }
  
  /**
   * Close an existing position (full or partial)
   * 
   * If the close size is less than the entry size, performs a partial close:
   * - Computes PnL proportionally for the closed portion
   * - Reduces the remaining open position size and entry fee proportionally
   * - Archives the closed portion to history
   * 
   * If the close size >= entry size, performs a full close (original behavior).
   */
  closePosition(coin, side, size, price, orderType, orderId, fee, feeRate) {
    // B6: Input validation guards
    if (!size || size <= 0) {
      console.warn(`⚠️  PositionTracker.closePosition: invalid size ${size} for ${coin}, ignoring`);
      return null;
    }
    if (!price || price <= 0) {
      console.warn(`⚠️  PositionTracker.closePosition: invalid price ${price} for ${coin}, ignoring`);
      return null;
    }
    
    const position = this.openPositions[coin];
    
    if (!position) {
      console.warn(`⚠️  No open position found for ${coin} in local tracker`);
      return null;
    }
    
    const timestamp = new Date().toISOString();
    const entrySize = position.entry.size;
    const closeSize = Math.min(size, entrySize);
    
    if (closeSize < entrySize) {
      // ── PARTIAL CLOSE ──
      // Create a snapshot of the closed portion for history
      const closedPortion = JSON.parse(JSON.stringify(position));
      closedPortion.positionId = `${position.positionId}_partial_${Date.now()}`;
      closedPortion.entry.size = closeSize;
      // Proportional entry fee for the closed portion
      closedPortion.entry.fee = position.entry.fee * (closeSize / entrySize);
      closedPortion.exit = { side, size: closeSize, price, fee, feeRate, orderType, orderId, timestamp };
      closedPortion.pnl = this._calculatePnl(closedPortion);
      closedPortion.status = 'closed';
      closedPortion.closedAt = timestamp;
      closedPortion.updatedAt = timestamp;
      
      this.closedPositions.push(closedPortion);
      
      // Reduce remaining open position
      const remainingSize = entrySize - closeSize;
      position.entry.size = remainingSize;
      position.entry.fee = position.entry.fee * (remainingSize / entrySize);
      position.updatedAt = timestamp;
      
      this._savePositions();
      this._saveHistory();
      
      this._logTrade({
        positionId: closedPortion.positionId,
        coin,
        type: 'partial_exit',
        side,
        size: closeSize,
        price,
        fee,
        feeRate,
        orderType,
        orderId,
        timestamp,
        pnl: closedPortion.pnl,
        remainingSize
      });
      
      console.log(`🏁 Partial close: ${coin} ${closeSize}/${entrySize} | Net PnL: $${closedPortion.pnl.net.toFixed(4)} (${closedPortion.pnl.percent.toFixed(2)}%) | Remaining: ${remainingSize}`);
      
      return closedPortion;
    }
    
    // ── FULL CLOSE ──
    // Add exit details
    position.exit = {
      side,
      size: closeSize,
      price,
      fee,
      feeRate,
      orderType,
      orderId,
      timestamp
    };
    
    // Calculate PnL
    position.pnl = this._calculatePnl(position);
    position.status = 'closed';
    position.closedAt = timestamp;
    position.updatedAt = timestamp;
    
    // Move to history
    this.closedPositions.push(position);
    delete this.openPositions[coin];
    
    this._savePositions();
    this._saveHistory();
    
    // Log trade
    this._logTrade({
      positionId: position.positionId,
      coin,
      type: 'exit',
      side,
      size: closeSize,
      price,
      fee,
      feeRate,
      orderType,
      orderId,
      timestamp,
      pnl: position.pnl
    });
    
    console.log(`🏁 Position closed: ${coin} | Net PnL: $${position.pnl.net.toFixed(4)} (${position.pnl.percent.toFixed(2)}%)`);
    
    return position;
  }
  
  /**
   * Calculate PnL for a position
   */
  _calculatePnl(position) {
    const { entry, exit } = position;
    const entryPrice = Number.isFinite(entry.price) ? entry.price : 0;
    const entrySize = Number.isFinite(entry.size) ? entry.size : 0;
    const exitPrice = Number.isFinite(exit.price) ? exit.price : 0;
    const exitSize = Number.isFinite(exit.size) ? exit.size : 0;
    const entryFee = Number.isFinite(entry.fee) ? entry.fee : 0;
    const exitFee = Number.isFinite(exit.fee) ? exit.fee : 0;
    
    // Determine if long or short
    const isLong = entry.side === 'buy';
    
    // Calculate gross PnL
    let grossPnl;
    if (isLong) {
      grossPnl = (exitPrice - entryPrice) * exitSize;
    } else {
      grossPnl = (entryPrice - exitPrice) * exitSize;
    }
    
    // Calculate total fees
    const totalFees = entryFee + exitFee;
    
    // Calculate net PnL
    const netPnl = grossPnl - totalFees;
    
    // Calculate percentage return
    const positionValue = entryPrice * entrySize;
    const pnlPercent = (positionValue > 0 && Number.isFinite(positionValue))
      ? (netPnl / positionValue) * 100
      : 0;
    
    return {
      gross: grossPnl,
      net: netPnl,
      fees: {
        entry: entryFee,
        exit: exitFee,
        total: totalFees
      },
      percent: pnlPercent,
      entryValue: positionValue,
      exitValue: exitPrice * exitSize
    };
  }
  
  /**
   * Log a trade
   */
  _logTrade(trade) {
    this.trades.push(trade);
    this._saveTrades();
  }
  
  /**
   * Get open position for a coin
   */
  getOpenPosition(coin) {
    return this.openPositions[coin] || null;
  }
  
  /**
   * Get all open positions
   */
  getAllOpenPositions() {
    return Object.values(this.openPositions);
  }
  
  /**
   * Get closed positions (with optional filters)
   */
  getClosedPositions(coin = null, limit = null) {
    let positions = [...this.closedPositions];
    
    if (coin) {
      positions = positions.filter(p => p.coin === coin);
    }
    
    // Sort by closed date (newest first)
    positions.sort((a, b) => new Date(b.closedAt) - new Date(a.closedAt));
    
    if (limit) {
      positions = positions.slice(0, limit);
    }
    
    return positions;
  }
  
  /**
   * Get total PnL statistics
   */
  getTotalStats() {
    const closed = this.closedPositions;
    
    if (closed.length === 0) {
      return {
        totalTrades: 0,
        totalNetPnl: 0,
        totalGrossPnl: 0,
        totalFees: 0,
        avgPnlPercent: 0,
        winRate: 0,
        winningTrades: 0,
        losingTrades: 0
      };
    }
    
    const totalNetPnl = closed.reduce((sum, p) => sum + p.pnl.net, 0);
    const totalGrossPnl = closed.reduce((sum, p) => sum + p.pnl.gross, 0);
    const totalFees = closed.reduce((sum, p) => sum + p.pnl.fees.total, 0);
    const avgPnlPercent = closed.reduce((sum, p) => sum + p.pnl.percent, 0) / closed.length;
    
    const winningTrades = closed.filter(p => p.pnl.net > 0).length;
    const losingTrades = closed.filter(p => p.pnl.net < 0).length;
    const winRate = (winningTrades / closed.length) * 100;
    
    return {
      totalTrades: closed.length,
      totalNetPnl,
      totalGrossPnl,
      totalFees,
      avgPnlPercent,
      winRate,
      winningTrades,
      losingTrades
    };
  }
  
  /**
   * Get per-coin statistics
   */
  getStatsByCoin() {
    const stats = {};
    
    this.closedPositions.forEach(position => {
      const coin = position.coin;
      
      if (!stats[coin]) {
        stats[coin] = {
          coin,
          trades: 0,
          netPnl: 0,
          grossPnl: 0,
          fees: 0,
          wins: 0,
          losses: 0
        };
      }
      
      stats[coin].trades++;
      stats[coin].netPnl += position.pnl.net;
      stats[coin].grossPnl += position.pnl.gross;
      stats[coin].fees += position.pnl.fees.total;
      
      if (position.pnl.net > 0) {
        stats[coin].wins++;
      } else if (position.pnl.net < 0) {
        stats[coin].losses++;
      }
    });
    
    // Calculate win rate for each coin
    Object.values(stats).forEach(s => {
      s.winRate = s.trades > 0 ? (s.wins / s.trades) * 100 : 0;
    });
    
    return stats;
  }
  
  // ═══════════════════════════════════════════════════════════════════
  // SL/TP Fill Detection
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Register pending SL/TP orders so fills can be detected.
   * Called by BaseAgent.registerSlTpOrders() after the agent places SL/TP.
   *
   * @param {string} coin
   * @param {Array<{orderId: string|number, cloid: string, orderType: string, size: number, triggerPrice: number, side: boolean}>} orders
   */
  registerSlTpOrders(coin, orders) {
    for (const order of orders) {
      if (!order || !order.orderId) continue;
      const key = String(order.orderId);
      this.pendingSlTp[key] = {
        coin,
        cloid: order.cloid || null,
        orderType: order.orderType,  // 'stop_loss' | 'take_profit' | 'trailing_stop'
        size: order.size,
        triggerPrice: order.triggerPrice,
        side: order.side,            // isBuy for the SL/TP order (closing side)
        registeredAt: Date.now()
      };
      if (order.cloid) {
        this.pendingSlTpByCloid[order.cloid] = key;
      }
    }
    console.log(`📋 PositionTracker: registered ${orders.filter(o => o?.orderId).length} SL/TP order(s) for ${coin}`);
  }

  /**
   * Remove pending SL/TP orders for a coin.
   * Called when the agent manually closes a position and cancels its SL/TP orders.
   *
   * @param {string} coin
   */
  removeSlTpOrders(coin) {
    let removed = 0;
    for (const [oid, entry] of Object.entries(this.pendingSlTp)) {
      if (entry.coin === coin) {
        if (entry.cloid) delete this.pendingSlTpByCloid[entry.cloid];
        delete this.pendingSlTp[oid];
        removed++;
      }
    }
    if (removed > 0) {
      console.log(`📋 PositionTracker: cleared ${removed} pending SL/TP order(s) for ${coin}`);
    }
  }

  /**
   * Handle a real-time WebSocket fill event.
   * Returns true if the fill matched a pending SL/TP order for this agent.
   *
   * @param {{ coin: string, px: string, sz: string, side: string, oid: string|number, cloid?: string, fee?: string, hash?: string }} event
   * @returns {boolean}
   */
  handleFillEvent(event) {
    if (!event || !event.oid) return false;

    const oid = String(event.oid);
    let entry = this.pendingSlTp[oid];

    // Also try matching by cloid if present
    if (!entry && event.cloid) {
      const mappedOid = this.pendingSlTpByCloid[event.cloid];
      if (mappedOid) entry = this.pendingSlTp[mappedOid];
    }

    if (!entry) return false;  // Not one of our SL/TP orders

    const coin = entry.coin || event.coin;
    const fillPrice = parseFloat(event.px);
    const fillSize = parseFloat(event.sz);
    const fillSide = event.side === 'B' ? 'buy' : 'sell';
    const fee = event.fee ? parseFloat(event.fee) : 0;

    console.log(`🎯 PositionTracker: SL/TP fill detected — ${entry.orderType} for ${coin} | ${fillSize} @ $${fillPrice.toFixed(2)}`);

    // Close the position in local tracker with actual fill data
    const closedPosition = this.closePosition(
      coin,
      fillSide,
      fillSize,
      fillPrice,
      entry.orderType,   // 'stop_loss' / 'take_profit' / 'trailing_stop'
      oid,
      fee,
      fee > 0 && fillSize * fillPrice > 0
        ? fee / (fillSize * fillPrice)
        : this.defaultTakerFeeRate   // Estimate feeRate when WS doesn't provide it
    );

    // Clean up the pending order
    if (entry.cloid) delete this.pendingSlTpByCloid[entry.cloid];
    delete this.pendingSlTp[oid];

    // Also remove the counterpart order for the same coin (if SL filled, remove TP and vice versa)
    this.removeSlTpOrders(coin);

    // Fire callback so BaseAgent can log to Supabase and notify the user
    if (this.onSlTpFill) {
      try {
        this.onSlTpFill({
          coin,
          side: fillSide,
          size: fillSize,
          price: fillPrice,
          fee,
          orderId: oid,
          orderType: entry.orderType,
          cloid: entry.cloid,
          triggerType: entry.orderType,  // 'stop_loss' | 'take_profit' | 'trailing_stop'
          closedPosition
        });
      } catch (err) {
        console.error('⚠️  PositionTracker: onSlTpFill callback error:', err.message);
      }
    }

    return true;
  }

  /**
   * Check pending SL/TP orders against recent fills (REST polling fallback).
   * Called from reconcile() to catch fills that the WebSocket may have missed.
   *
   * @param {Array<{oid: string|number, coin: string, px: number, sz: number, side: string, fee: number}>} recentFills
   */
  _checkPendingSlTpAgainstFills(recentFills) {
    if (!recentFills || recentFills.length === 0) return;
    if (Object.keys(this.pendingSlTp).length === 0) return;

    for (const fill of recentFills) {
      const oid = String(fill.oid);
      if (this.pendingSlTp[oid]) {
        // Simulate a WS-style event for handleFillEvent
        const handled = this.handleFillEvent({
          coin: fill.coin,
          px: String(fill.px),
          sz: String(fill.sz),
          side: fill.side === 'Buy' ? 'B' : 'A',
          oid: fill.oid,
          fee: fill.fee ? String(fill.fee) : '0'
        });
        if (handled) {
          console.log(`📋 PositionTracker: fallback fill match for order ${oid} (${fill.coin})`);
        }
      }
    }
  }

  /**
   * Reconcile file-based open positions against actual exchange positions.
   * Removes stale entries, detects size drift, and logs untracked exchange positions.
   * 
   * @param {Array<{coin: string, size: number, entryPrice: number}>} exchangePositions - Actual positions from Hyperliquid
   * @param {Object} [currentMids=null] - Current mid prices keyed by coin (e.g., { "BTC": "90500" }).
   *   If provided, used as exit price estimate for external closes instead of fabricating from entry prices.
   * @param {Array} [recentFills=null] - Recent fills from getUserFills() for SL/TP fallback detection.
   */
  reconcile(exchangePositions, currentMids = null, recentFills = null) {
    // --- SL/TP fallback: check pending orders against recent fills first ---
    if (recentFills) {
      this._checkPendingSlTpAgainstFills(recentFills);
    }

    const exchangeMap = new Map(
      exchangePositions.filter(p => p.size !== 0).map(p => [p.coin, p])
    );
    const trackedCoins = Object.keys(this.openPositions);
    let removed = 0;
    let driftWarnings = 0;
    
    for (const coin of trackedCoins) {
      const exchangePos = exchangeMap.get(coin);
      const localPos = this.openPositions[coin];
      
      // Remove if coin has NO position on exchange at all
      // OR if the exchange position is in the opposite direction to what we track
      const shouldRemove = !exchangePos || (
        (localPos.entry.side === 'buy' && exchangePos.size < 0) ||
        (localPos.entry.side === 'sell' && exchangePos.size > 0)
      );
      
      if (shouldRemove) {
        const reason = !exchangePos 
          ? 'not found on exchange' 
          : 'exchange position flipped direction';
        console.warn(`⚠️  PositionTracker: removing stale position for ${coin} (${reason})`);
        
        // Use current mid price as exit estimate; fall back to 0 (unknown)
        let exitPrice = 0;
        if (currentMids && currentMids[coin]) {
          exitPrice = parseFloat(currentMids[coin]);
        }
        
        const position = localPos;
        position.status = 'closed_external';
        position.closedAt = new Date().toISOString();
        position.updatedAt = new Date().toISOString();
        // Estimate exit fee using defaultTakerFeeRate to avoid PnL overstatement
        const estimatedExitFee = exitPrice > 0
          ? position.entry.size * exitPrice * this.defaultTakerFeeRate
          : 0;

        position.exit = {
          side: 'unknown',
          size: position.entry.size,
          price: exitPrice,
          fee: estimatedExitFee,
          feeRate: this.defaultTakerFeeRate,
          orderType: 'external',
          orderId: 'reconcile',
          timestamp: new Date().toISOString()
        };
        
        // Calculate approximate PnL if we have exit price
        if (exitPrice > 0) {
          const isLong = position.entry.side === 'buy';
          const gross = isLong 
            ? (exitPrice - position.entry.price) * position.entry.size
            : (position.entry.price - exitPrice) * position.entry.size;
          const entryValue = position.entry.price * position.entry.size;
          const totalFees = position.entry.fee + estimatedExitFee;
          position.pnl = {
            gross,
            net: gross - totalFees,
            fees: { entry: position.entry.fee, exit: estimatedExitFee, total: totalFees },
            percent: entryValue > 0 ? ((gross - totalFees) / entryValue) * 100 : 0,
            entryValue,
            exitValue: exitPrice * position.entry.size,
            estimated: true  // Mark as estimated since we don't know the actual exit price
          };
        } else {
          const entryValue = position.entry.price * position.entry.size;
          position.pnl = {
            gross: 0,
            net: -position.entry.fee,
            fees: { entry: position.entry.fee, exit: 0, total: position.entry.fee },
            percent: 0,
            entryValue,
            exitValue: 0,
            estimated: true
          };
        }
        
        this.closedPositions.push(position);
        delete this.openPositions[coin];
        removed++;
      } else {
        // Position exists on both sides — check for size drift
        const localSize = localPos.entry.size;
        const exchangeSize = Math.abs(exchangePos.size);
        const drift = Math.abs(localSize - exchangeSize);
        const driftPercent = exchangeSize > 0 ? (drift / exchangeSize) * 100 : 0;
        
        if (driftPercent > 10) {
          driftWarnings++;
          console.warn(`⚠️  PositionTracker: size drift for ${coin} — local: ${localSize}, exchange: ${exchangeSize} (${driftPercent.toFixed(1)}% drift)`);
        }
      }
    }
    
    // Log untracked exchange positions (positions on exchange not in our tracker)
    const trackedSet = new Set(trackedCoins);
    for (const [coin, exchangePos] of exchangeMap) {
      if (!trackedSet.has(coin)) {
        console.log(`📋 PositionTracker: untracked exchange position — ${coin}: ${exchangePos.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(exchangePos.size)} (not managed by this agent)`);
      }
    }
    
    if (removed > 0) {
      this._savePositions();
      this._saveHistory();
      console.log(`📋 PositionTracker reconciliation: removed ${removed} stale position(s)${driftWarnings > 0 ? `, ${driftWarnings} size drift warning(s)` : ''}`);
    } else {
      console.log(`📋 PositionTracker reconciliation: all positions match exchange${driftWarnings > 0 ? ` (${driftWarnings} size drift warning(s))` : ''}`);
    }
  }

  /**
   * Print summary
   */
  printSummary() {
    const stats = this.getTotalStats();
    const coinStats = this.getStatsByCoin();
    
    console.log('\n' + '='.repeat(60));
    console.log('📊 POSITION TRACKER SUMMARY');
    console.log('='.repeat(60));
    
    console.log('\n🔢 Overall Statistics:');
    console.log(`   Total Trades: ${stats.totalTrades}`);
    console.log(`   Winning Trades: ${stats.winningTrades} (${stats.winRate.toFixed(1)}%)`);
    console.log(`   Losing Trades: ${stats.losingTrades}`);
    console.log(`   Total Net PnL: $${stats.totalNetPnl.toFixed(2)}`);
    console.log(`   Total Gross PnL: $${stats.totalGrossPnl.toFixed(2)}`);
    console.log(`   Total Fees Paid: $${stats.totalFees.toFixed(2)}`);
    console.log(`   Avg Return: ${stats.avgPnlPercent.toFixed(2)}%`);
    
    if (Object.keys(coinStats).length > 0) {
      console.log('\n💰 Per-Coin Breakdown:');
      Object.values(coinStats).forEach(s => {
        console.log(`   ${s.coin}:`);
        console.log(`      Trades: ${s.trades} (${s.wins}W/${s.losses}L, ${s.winRate.toFixed(1)}% WR)`);
        console.log(`      Net PnL: $${s.netPnl.toFixed(2)}`);
        console.log(`      Fees: $${s.fees.toFixed(2)}`);
      });
    }
    
    const openPositions = this.getAllOpenPositions();
    if (openPositions.length > 0) {
      console.log('\n📍 Open Positions:');
      openPositions.forEach(p => {
        console.log(`   ${p.coin}: ${p.entry.side.toUpperCase()} ${p.entry.size} @ $${p.entry.price.toFixed(2)}`);
      });
    }
    
    console.log('\n' + '='.repeat(60) + '\n');
  }
}

export default PositionTracker;
