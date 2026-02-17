/**
 * BaseAgent.js
 * 
 * Base class that all trading agents inherit from.
 * Provides boilerplate for initialization, state management, monitoring, and shutdown.
 * 
 * ARCHITECTURE:
 * - Uses OrderExecutor for trading, HyperliquidWSManager for real-time data
 * - Imports utility functions from perpMarket.js and perpUser.js
 * - Integrates with Supabase for state management
 * - Provides trigger registration and evaluation utilities
 * 
 * ABSTRACT METHODS (Agent must implement):
 * - onInitialize(): Setup strategy-specific initialization
 * - setupTriggers(): Register all price/technical/scheduled/event triggers
 * - executeTrade(triggerData): Compute order parameters and place orders
 * 
 * @module BaseAgent
 */

import { OrderExecutor } from './orderExecutor.js';
import { HyperliquidWSManager } from './ws.js';
import { createClient } from '@supabase/supabase-js';
import PositionTracker from './PositionTracker.js';

// Import ALL market data functions
import {
  getAllMids,
  getCandleSnapshot,
  getTicker,
  getL2Book,
  getFundingHistory,
  getMetaAndAssetCtxs,
  getRecentTrades,
  getPredictedFundings,
  getPerpsAtOpenInterestCap
} from './perpMarket.js';

// Import ALL user data functions
import {
  getOpenOrders,
  getFrontendOpenOrders,
  getUserFills,
  getUserFillsByTime,
  getHistoricalOrders,
  getPortfolio,
  getSubAccounts,
  getUserFees
} from './perpUser.js';

import { toPrecision, compareFloats, safeDivide, toFiniteNumber } from './utils.js';
import TechnicalIndicatorService from './TechnicalIndicatorService.js';
import {
  DEFAULT_MAX_LEVERAGE,
  DEFAULT_DAILY_LOSS_LIMIT,
  DEFAULT_LEVERAGE_SYNC_TTL_MS,
  TECHNICAL_EVAL_INTERVAL_MS,
  HEARTBEAT_PERSIST_INTERVAL_MS,
  POSITION_SYNC_INTERVAL_MS,
  METRICS_INTERVAL_MS,
  FEE_REFRESH_INTERVAL_MS,
  TECHNICAL_TRIGGER_RATE_LIMIT_MS,
  CANDLE_LOOKBACK_MULTIPLIER,
  MIN_CANDLES_REQUIRED,
  INTERVAL_MS_MAP,
} from './config.js';

/**
 * BaseAgent class
 * 
 * All trading agents must extend this class and implement the three abstract methods:
 * - onInitialize()
 * - setupTriggers()
 * - executeTrade(triggerData)
 */
class BaseAgent {
  /**
   * Initialize base agent
   * 
   * @param {Object} config - Configuration
   * @param {string} config.agentId - UUID from Supabase
   * @param {string} config.userId - User ID
   * @param {string} config.privateKey - API wallet private key (0x-prefixed)
   * @param {string} config.userAddress - Main Hyperliquid address (0x-prefixed)
   * @param {string} config.supabaseUrl - Supabase project URL
   * @param {string} config.supabaseKey - Supabase anon key
   * @param {boolean} [config.isMainnet=true] - Network selection
   * @param {number} [config.maxLeverage] - Max leverage limit (default from config.js)
   * @param {number} [config.dailyLossLimit] - Daily loss limit in USD (default from config.js)
   * @param {number} [config.leverageSyncTtlMs] - TTL for leverage re-sync before orders (default from config.js)
   */
  constructor(config) {
    // Validation
    if (!config.agentId) throw new Error('agentId is required');
    if (!config.userId) throw new Error('userId is required');
    if (!config.privateKey) throw new Error('privateKey is required');
    if (!config.userAddress) throw new Error('userAddress is required');
    if (!config.supabaseUrl) throw new Error('supabaseUrl is required');
    if (!config.supabaseKey) throw new Error('supabaseKey is required');
    
    // Agent identification
    this.agentId = config.agentId;
    this.userId = config.userId;
    
    // Hyperliquid credentials
    this.privateKey = config.privateKey;
    this.userAddress = config.userAddress;
    this.isMainnet = config.isMainnet !== undefined ? config.isMainnet : true;
    
    // Core components
    const leverageSyncTtlMs = Number(config.leverageSyncTtlMs);
    this.orderExecutor = new OrderExecutor(
      this.privateKey,
      this.userAddress,
      this.isMainnet,
      {
        agentId: this.agentId,
        leverageSyncTtlMs: Number.isFinite(leverageSyncTtlMs) ? leverageSyncTtlMs : DEFAULT_LEVERAGE_SYNC_TTL_MS
      }
    );
    
    this.wsManager = new HyperliquidWSManager({
      address: this.userAddress,
      debug: false
    });
    
    // Supabase client
    this.supabase = createClient(config.supabaseUrl, config.supabaseKey);
    
    // Position tracker (local file-based tracking with PnL calculation)
    // The onSlTpFill callback fires when a SL/TP order fill is detected (WS or fallback)
    // Pass the executor's taker fee rate so PositionTracker can estimate exit fees
    // for externally closed positions and opposite-side auto-closes.
    this.positionTracker = new PositionTracker(this.agentId, {
      onSlTpFill: (fillData) => this._handleSlTpFill(fillData),
      onLiquidation: (fillData) => this._handleLiquidation(fillData),
      defaultTakerFeeRate: this.orderExecutor.takerFeeRate
    });
    
    // Fetch user's actual fee rates and sync to PositionTracker
    this.orderExecutor.fetchUserFeeRates().then(() => {
      this.positionTracker.defaultTakerFeeRate = this.orderExecutor.takerFeeRate;
    }).catch(err => {
      console.warn('Could not fetch fee rates:', err.message);
    });
    
    // Strategy configuration
    this.strategyConfig = {};
    
    // State tracking
    this.currentState = 'initializing';
    this.isRunning = false;
    this.isPaused = false;
    this._shutdownInProgress = false;
    this._shutdownPromise = null;
    this.lastHeartbeat = Date.now();
    
    // Trigger tracking (for monitor() loop)
    this.activeTriggers = new Map(); // triggerId -> trigger config
    this.triggerCallbacks = new Map(); // triggerId -> callback function
    
    // Safety limits (config overrides > config.js defaults)
    this.maxLeverage = Number.isFinite(Number(config.maxLeverage))
      ? Number(config.maxLeverage) : DEFAULT_MAX_LEVERAGE;
    this.dailyLossLimit = Number.isFinite(Number(config.dailyLossLimit))
      ? Number(config.dailyLossLimit) : DEFAULT_DAILY_LOSS_LIMIT;
    
    // Technical indicator computation service (lazy-loads the library)
    this._technicalIndicatorService = new TechnicalIndicatorService();
    
    // Fan-out buffer for userEvent callbacks — initialized here so
    // registerEventTrigger can safely push callbacks before start() runs.
    this._userEventCallbacks = [];
    
    // In-memory daily PnL accumulator (avoids querying Supabase on every trade)
    this._dailyPnl = 0;
    this._dailyPnlDate = new Date().toISOString().slice(0, 10); // 'YYYY-MM-DD'
    
    // Running metrics accumulator (avoids SELECT * FROM agent_trades every 5 min)
    this._metricsAccum = { totalPnl: 0, wins: 0, losses: 0, totalTrades: 0 };
    this._metricsSeeded = false;
    
    console.log(`✅ BaseAgent initialized for agent ${this.agentId}`);
    console.log(`   User: ${this.userId}`);
    console.log(`   Network: ${this.isMainnet ? 'mainnet' : 'testnet'}`);
  }
  
  // ==========================================================================
  // STATE MANAGEMENT METHODS
  // ==========================================================================
  
  /**
   * Update agent state in Supabase
   * 
   * @param {string} stateType - Type of state update (cycle, position, order, error, etc.)
   * @param {Object} stateData - Raw state data (JSONB)
   * @param {string} message - Human-readable message
   */
  async updateState(stateType, stateData, message) {
    try {
      const { error } = await this.supabase.from('agent_states').insert({
        agent_id: this.agentId,
        state_type: stateType,
        state_data: stateData,
        message: message
      });
      
      if (error) {
        console.error('Failed to update state:', error);
      }
    } catch (error) {
      console.error('Failed to update state:', error);
    }
  }
  
  /**
   * Reconcile local PositionTracker against exchange reality AND sync to
   * Supabase in a single pass.  Uses one getPositions() + one _getCurrentMids()
   * call instead of the previous two separate methods that each fetched positions.
   *
   * Also batches Supabase upserts into a single request.
   * @private
   */
  async _reconcileAndSync() {
    try {
      const exchangePositions = await this.orderExecutor.getPositions();
      const mids = await this._getCurrentMids();

      // --- Reconcile ---
      let recentFills = null;
      if (Object.keys(this.positionTracker.pendingSlTp).length > 0) {
        try {
          recentFills = await getUserFills(this.userAddress);
        } catch (err) {
          console.warn('⚠️  Could not fetch user fills for SL/TP fallback:', err.message);
        }
      }
      this.positionTracker.reconcile(exchangePositions, mids, recentFills);

      // --- Sync to Supabase ---
      const trackedCoins = Object.keys(this.positionTracker.openPositions);
      const exchangeMap = new Map(exchangePositions.map(p => [p.coin, p]));
      const activeCoinSet = new Set();
      const upsertRecords = [];
      const nowIso = new Date().toISOString();

      for (const coin of trackedCoins) {
        const localPos = this.positionTracker.openPositions[coin];
        const exchangePos = exchangeMap.get(coin);

        if (exchangePos && exchangePos.size !== 0) {
          activeCoinSet.add(coin);
          const agentSize = localPos.entry.size;
          const totalSize = Math.abs(exchangePos.size);
          const shareRatio = totalSize > 0 ? Math.min(agentSize / totalSize, 1) : 0;

          upsertRecords.push({
            agent_id: this.agentId,
            coin,
            size: localPos.entry.side === 'buy' ? agentSize : -agentSize,
            entry_price: localPos.entry.price,
            unrealized_pnl: exchangePos.unrealizedPnl * shareRatio,
            leverage: exchangePos.leverage,
            liquidation_price: exchangePos.liquidationPrice,
            updated_at: nowIso,
          });
        }
      }

      // Batch upsert (single round-trip)
      if (upsertRecords.length > 0) {
        const { error } = await this.supabase.from('agent_positions')
          .upsert(upsertRecords, { onConflict: 'agent_id,coin' });
        if (error) console.error('Failed to batch-sync positions:', error);
      }

      // Remove closed positions from database
      const { data: dbPositions, error: fetchError } = await this.supabase
        .from('agent_positions')
        .select('coin')
        .eq('agent_id', this.agentId);

      if (!fetchError && dbPositions) {
        for (const dbPos of dbPositions) {
          if (!activeCoinSet.has(dbPos.coin) && !this.positionTracker.openPositions[dbPos.coin]) {
            const { error: deleteError } = await this.supabase
              .from('agent_positions')
              .delete()
              .eq('agent_id', this.agentId)
              .eq('coin', dbPos.coin);

            if (!deleteError) {
              console.log(`✅ Removed closed ${dbPos.coin} position from database`);
              await this.updateState('position_removed', { coin: dbPos.coin }, `${dbPos.coin} position closed and removed`);
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to reconcile/sync positions:', error);
    }
  }

  /**
   * Reconcile local PositionTracker state against exchange reality.
   * Lightweight wrapper kept for callers outside the monitor loop (e.g. start()).
   */
  async reconcileTrackedPositions() {
    try {
      const exchangePositions = await this.orderExecutor.getPositions();
      const mids = await this._getCurrentMids();

      let recentFills = null;
      if (Object.keys(this.positionTracker.pendingSlTp).length > 0) {
        try {
          recentFills = await getUserFills(this.userAddress);
        } catch (err) {
          console.warn('⚠️  Could not fetch user fills for SL/TP fallback:', err.message);
        }
      }

      this.positionTracker.reconcile(exchangePositions, mids, recentFills);
    } catch (error) {
      console.warn('⚠️  Position reconciliation failed:', error.message);
    }
  }
  
  // ==========================================================================
  // SHARED HELPERS (used by logTrade, _handleSlTpFill, updateMetrics, shutdown)
  // ==========================================================================

  /**
   * Build a position history record suitable for inserting into
   * the agent_position_history Supabase table.
   * @private
   */
  _buildPositionHistoryRecord(closedPosition) {
    return {
      agent_id: this.agentId,
      coin: closedPosition.coin,
      side: closedPosition.entry.side,
      entry_size: closedPosition.entry.size,
      entry_price: closedPosition.entry.price,
      exit_size: closedPosition.exit.size,
      exit_price: closedPosition.exit.price,
      entry_fee: closedPosition.entry.fee,
      exit_fee: closedPosition.exit.fee,
      realized_pnl: closedPosition.pnl.net,
      pnl_percent: closedPosition.pnl.percent,
      opened_at: closedPosition.entry.timestamp,
      closed_at: closedPosition.exit.timestamp,
      duration_seconds: Math.floor(
        (new Date(closedPosition.exit.timestamp) - new Date(closedPosition.entry.timestamp)) / 1000
      )
    };
  }

  /**
   * Compute agent-scoped unrealized PnL by comparing local tracker
   * sizes against exchange positions (share-ratio weighted).
   * @private
   * @param {Array} exchangePositions - From orderExecutor.getPositions()
   * @returns {number}
   */
  _computeAgentUnrealizedPnl(exchangePositions) {
    const exchangeMap = new Map(exchangePositions.map(p => [p.coin, p]));
    let unrealized = 0;
    for (const coin of Object.keys(this.positionTracker.openPositions)) {
      const localPos = this.positionTracker.openPositions[coin];
      const exchangePos = exchangeMap.get(coin);
      if (exchangePos && exchangePos.size !== 0) {
        const agentSize = localPos.entry.size;
        const totalSize = Math.abs(exchangePos.size);
        const shareRatio = totalSize > 0 ? Math.min(agentSize / totalSize, 1) : 0;
        unrealized += (exchangePos.unrealizedPnl || 0) * shareRatio;
      }
    }
    return unrealized;
  }

  /**
   * Compute win/loss metrics from an array of trades that have PnL.
   * @private
   * @param {Array} tradesWithPnl - Array of { pnl: number }
   * @returns {{ totalRealizedPnl: number, winningTrades: number, losingTrades: number, winRate: number, totalTrades: number }}
   */
  _computeTradeMetrics(tradesWithPnl) {
    const totalRealizedPnl = tradesWithPnl.reduce((sum, t) => sum + toFiniteNumber(t.pnl, 0), 0);
    const winningTrades = tradesWithPnl.filter(t => toFiniteNumber(t.pnl, 0) > 0).length;
    const losingTrades = tradesWithPnl.filter(t => toFiniteNumber(t.pnl, 0) < 0).length;
    const totalTrades = tradesWithPnl.length;
    const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
    return { totalRealizedPnl, winningTrades, losingTrades, winRate, totalTrades };
  }

  // ==========================================================================
  // SL/TP FILL DETECTION
  // ==========================================================================

  /**
   * Register pending SL/TP orders so their fills can be automatically detected.
   * Call this after placing stop-loss and take-profit orders.
   *
   * @param {string} coin - Coin symbol (e.g. "BTC")
   * @param {Object} orders - { sl: OrderResult, tp: OrderResult, trailing: OrderResult }
   *   Each field is optional. Only orders with success=true and an orderId are registered.
   */
  registerSlTpOrders(coin, { sl, tp, trailing } = {}) {
    const entries = [];
    if (sl && sl.success && sl.orderId) {
      entries.push({ orderId: sl.orderId, cloid: sl.cloid, orderType: 'stop_loss', size: sl.filledSize || 0, triggerPrice: 0, side: null });
    }
    if (tp && tp.success && tp.orderId) {
      entries.push({ orderId: tp.orderId, cloid: tp.cloid, orderType: 'take_profit', size: tp.filledSize || 0, triggerPrice: 0, side: null });
    }
    if (trailing && trailing.success && trailing.orderId) {
      entries.push({ orderId: trailing.orderId, cloid: trailing.cloid, orderType: 'trailing_stop', size: trailing.filledSize || 0, triggerPrice: 0, side: null });
    }
    if (entries.length > 0) {
      this.positionTracker.registerSlTpOrders(coin, entries);
    }
  }

  /**
   * Clear pending SL/TP orders for a coin.
   * Call this before manually closing a position and cancelling SL/TP orders.
   *
   * @param {string} coin - Coin symbol
   */
  clearSlTpOrders(coin) {
    this.positionTracker.removeSlTpOrders(coin);
  }

  /**
   * Internal callback fired by PositionTracker when a SL/TP fill is detected.
   * Logs the trade to Supabase and notifies the user via updateState.
   *
   * @param {Object} fillData - Fill details from PositionTracker
   */
  async _handleSlTpFill(fillData) {
    try {
      const { coin, side, size, price, fee, orderId, orderType, cloid, triggerType, closedPosition } = fillData;

      const triggerLabel = orderType === 'stop_loss' ? 'Stop-loss'
        : orderType === 'take_profit' ? 'Take-profit'
        : orderType === 'trailing_stop' ? 'Trailing stop'
        : 'SL/TP';

      console.log(`🎯 BaseAgent: ${triggerLabel} filled for ${coin} — ${size} @ $${price.toFixed(2)}`);

      // Log trade to Supabase + PositionTracker (closePosition already called by PositionTracker)
      // We still call logTrade so the Supabase agent_trades and agent_position_history tables are updated.
      // Pass the closedPosition directly so logTrade doesn't try to double-close.
      const tradeRecord = {
        agent_id: this.agentId,
        timestamp: new Date().toISOString(),
        coin,
        side,
        size,
        price,
        order_type: orderType,
        order_id: orderId,
        trigger_reason: `${triggerLabel} filled @ $${price.toFixed(2)}`,
        pnl: closedPosition?.pnl?.net ?? null,
        is_entry: false,
        is_exit: true,
        fee: fee ?? null,
        fee_rate: null
      };

      const { error } = await this.supabase.from('agent_trades').insert(tradeRecord);
      if (error) console.error('Failed to log SL/TP trade to Supabase:', error);

      // Write position history if we have PnL
      if (closedPosition && closedPosition.pnl) {
        const historyRecord = this._buildPositionHistoryRecord(closedPosition);
        const { error: histError } = await this.supabase.from('agent_position_history').insert(historyRecord);
        if (histError) console.error('Failed to log SL/TP position history:', histError);
      }

      // Mark order as filled in ownership store
      if (this.orderExecutor.orderOwnershipStore) {
        if (orderId) this.orderExecutor.orderOwnershipStore.markByOrderId(orderId, 'filled');
        if (cloid) this.orderExecutor.orderOwnershipStore.markByCloid(cloid, 'filled');
      }

      // Notify user
      const pnlStr = closedPosition?.pnl
        ? ` PnL: $${closedPosition.pnl.net.toFixed(2)} (${closedPosition.pnl.percent.toFixed(2)}%)`
        : '';
      await this.updateState('sl_tp_filled', {
        coin, side, size, price, orderType, pnl: closedPosition?.pnl?.net ?? null
      }, `${coin}: ${triggerLabel} filled — ${size} @ $${price.toFixed(2)}.${pnlStr}`);

      // Sync positions after the fill
      await this._reconcileAndSync();
    } catch (err) {
      console.error('⚠️  _handleSlTpFill error:', err.message);
    }
  }

  /**
   * Handle a liquidation event for this agent's position.
   * Called by PositionTracker.onLiquidation when a fill with liquidation data is detected.
   * Logs to Supabase and notifies the user with a clear liquidation message.
   * 
   * @param {Object} fillData - Liquidation fill details from PositionTracker
   */
  async _handleLiquidation(fillData) {
    try {
      const { coin, side, size, price, fee, orderId, markPrice, closedPnl, closedPosition } = fillData;

      console.log(`💀 BaseAgent: LIQUIDATION for ${coin} — ${size} @ $${price.toFixed(2)} (mark: $${markPrice.toFixed(2)})`);

      // Log trade to Supabase
      const tradeRecord = {
        agent_id: this.agentId,
        timestamp: new Date().toISOString(),
        coin,
        side,
        size,
        price,
        order_type: 'liquidation',
        order_id: orderId,
        trigger_reason: `LIQUIDATED @ $${price.toFixed(2)} (mark: $${markPrice.toFixed(2)})`,
        pnl: closedPosition?.pnl?.net ?? closedPnl ?? null,
        is_entry: false,
        is_exit: true,
        fee: fee ?? null,
        fee_rate: null
      };

      const { error } = await this.supabase.from('agent_trades').insert(tradeRecord);
      if (error) console.error('Failed to log liquidation trade to Supabase:', error);

      // Write position history if we have PnL
      if (closedPosition && closedPosition.pnl) {
        const historyRecord = this._buildPositionHistoryRecord(closedPosition);
        const { error: histError } = await this.supabase.from('agent_position_history').insert(historyRecord);
        if (histError) console.error('Failed to log liquidation position history:', histError);
      }

      // Mark order as filled in ownership store
      if (this.orderExecutor.orderOwnershipStore && orderId) {
        this.orderExecutor.orderOwnershipStore.markByOrderId(orderId, 'filled');
      }

      // Update daily PnL accumulator
      const pnl = closedPosition?.pnl?.net ?? closedPnl ?? 0;
      this._dailyPnl += pnl;

      // Notify user with a prominent liquidation message
      const pnlStr = closedPosition?.pnl
        ? `PnL: $${closedPosition.pnl.net.toFixed(4)} (${closedPosition.pnl.percent.toFixed(2)}% ROI)`
        : closedPnl != null
          ? `PnL: $${closedPnl.toFixed(4)}`
          : 'PnL: unknown';

      const entryPrice = closedPosition?.entry?.price;
      const entryStr = entryPrice ? `Entry was $${entryPrice.toFixed(2)}. ` : '';

      await this.updateState('liquidation', {
        coin,
        side,
        size,
        price,
        markPrice,
        pnl: closedPosition?.pnl?.net ?? closedPnl ?? null,
        pnlPercent: closedPosition?.pnl?.percent ?? null,
        entryPrice: entryPrice ?? null,
        fee
      },
        `💀 ${coin}: POSITION LIQUIDATED. ${size} closed @ $${price.toFixed(2)} ` +
        `(mark price: $${markPrice.toFixed(2)}). ${entryStr}${pnlStr}. ` +
        `Fee: $${(fee || 0).toFixed(4)}. Position fully closed by exchange.`
      );

      // Sync positions after the liquidation
      await this._reconcileAndSync();
    } catch (err) {
      console.error('⚠️  _handleLiquidation error:', err.message);
    }
  }

  /**
   * Log trade to Supabase AND track position locally
   * 
   * @param {Object} tradeData - Trade information
   * @param {string} tradeData.coin - Coin symbol
   * @param {string} tradeData.side - 'buy' or 'sell'
   * @param {number} tradeData.size - Trade size
   * @param {number} [tradeData.price] - Execution price
   * @param {string} [tradeData.order_type] - Order type
   * @param {number} [tradeData.pnl] - Realized PnL
   * @param {string} [tradeData.order_id] - Order ID
   * @param {string} [tradeData.trigger_reason] - What triggered the trade
   * @param {number} [tradeData.fee] - Trade fee
   * @param {number} [tradeData.fee_rate] - Fee rate used
   * @param {boolean} [tradeData.is_entry] - Is this opening a position?
   * @param {boolean} [tradeData.is_exit] - Is this closing a position?
   */
  async logTrade(tradeData) {
    try {
      // Calculate fee if not provided (use ?? to preserve valid 0 fees)
      let fee = tradeData.fee;
      let feeRate = tradeData.fee_rate;
      
      if (fee == null && tradeData.price && tradeData.size) {
        const orderType = tradeData.order_type || 'market';
        const feeInfo = this.orderExecutor.calculateTradeFee(
          tradeData.size,
          tradeData.price,
          orderType
        );
        fee = feeInfo.fee;
        feeRate = feeInfo.feeRate;
      }
      
      // Auto-infer is_entry / is_exit if not explicitly provided
      if (tradeData.is_entry === undefined && tradeData.is_exit === undefined) {
        const existingPosition = this.positionTracker.openPositions[tradeData.coin];
        const isClosingSide = existingPosition && (
          (existingPosition.entry.side === 'buy' && tradeData.side === 'sell') ||
          (existingPosition.entry.side === 'sell' && tradeData.side === 'buy')
        );
        
        if (tradeData.order_type === 'close_position' || isClosingSide) {
          tradeData.is_exit = true;
          tradeData.is_entry = false;
        } else if (!existingPosition) {
          tradeData.is_entry = true;
          tradeData.is_exit = false;
        } else {
          // Same-side trade on existing position = adding to position
          tradeData.is_entry = true;
          tradeData.is_exit = false;
        }
      }
      
      // Track position in local files
      let positionId = tradeData.position_id;
      let pnlData = null;
      let closedPosition = null;
      
      if (tradeData.is_entry) {
        // Opening or adding to a position
        positionId = this.positionTracker.openPosition(
          tradeData.coin,
          tradeData.side,
          tradeData.size,
          tradeData.price,
          tradeData.order_type || 'market',
          tradeData.order_id || 'unknown',
          fee ?? 0,
          feeRate ?? 0
        );
      } else if (tradeData.is_exit) {
        // Closing a position (full or partial) - calculate PnL
        closedPosition = this.positionTracker.closePosition(
          tradeData.coin,
          tradeData.side,
          tradeData.size,
          tradeData.price,
          tradeData.order_type || 'market',
          tradeData.order_id || 'unknown',
          fee ?? 0,
          feeRate ?? 0
        );
        
        if (closedPosition) {
          positionId = closedPosition.positionId;
          pnlData = closedPosition.pnl;
        }
      }
      
      // Log to Supabase
      const tradeRecord = {
        agent_id: this.agentId,
        timestamp: new Date().toISOString(),
        coin: tradeData.coin,
        side: tradeData.side,
        size: tradeData.size,
        price: tradeData.price,
        order_type: tradeData.order_type,
        order_id: tradeData.order_id,
        trigger_reason: tradeData.trigger_reason,
        pnl: pnlData ? pnlData.net : (tradeData.pnl ?? null),
        is_entry: tradeData.is_entry || false,
        is_exit: tradeData.is_exit || false,
        fee: fee ?? null,
        fee_rate: feeRate ?? null
      };
      
      const { error } = await this.supabase.from('agent_trades').insert(tradeRecord);
      
      if (error) {
        console.error('Failed to log trade to Supabase:', error);
      }
      
      // Write to agent_position_history on exit
      if (tradeData.is_exit && closedPosition && closedPosition.pnl) {
        const historyRecord = this._buildPositionHistoryRecord(closedPosition);
        const { error: histError } = await this.supabase.from('agent_position_history').insert(historyRecord);
        if (histError) {
          console.error('Failed to log position history:', histError);
        }
      }
      
      // Update in-memory accumulators so checkSafetyLimits / updateMetrics
      // don't need to re-query Supabase on every call.
      const tradePnl = pnlData ? pnlData.net : toFiniteNumber(tradeData.pnl, 0);
      if (tradePnl !== 0) {
        // Daily PnL
        const todayStr = new Date().toISOString().slice(0, 10);
        if (todayStr !== this._dailyPnlDate) {
          this._dailyPnlDate = todayStr;
          this._dailyPnl = 0;
        }
        this._dailyPnl += tradePnl;

        // Running metrics
        this._metricsAccum.totalPnl += tradePnl;
        this._metricsAccum.totalTrades++;
        if (tradePnl > 0) this._metricsAccum.wins++;
        else this._metricsAccum.losses++;
      } else {
        // Entry trades still count
        this._metricsAccum.totalTrades++;
      }

      // Return position info for caller to use
      return {
        positionId,
        pnl: pnlData,
        fee,
        feeRate
      };
      
    } catch (error) {
      console.error('Failed to log trade:', error);
      return null;
    }
  }
  
  /**
   * Update agent metrics (raw metrics only)
   * Computes total PnL, trade count, win rate, and account value
   */
  async updateMetrics() {
    try {
      // Seed the accumulator from Supabase on the very first call
      if (!this._metricsSeeded) {
        try {
          const { data: trades } = await this.supabase
            .from('agent_trades')
            .select('pnl')
            .eq('agent_id', this.agentId);
          const withPnl = trades?.filter(t => t.pnl !== null && t.pnl !== undefined) || [];
          const { totalRealizedPnl, winningTrades, losingTrades, totalTrades } =
            this._computeTradeMetrics(withPnl);
          this._metricsAccum = {
            totalPnl: totalRealizedPnl,
            wins: winningTrades,
            losses: losingTrades,
            totalTrades,
          };
        } catch { /* proceed with current accumulator values */ }
        this._metricsSeeded = true;
      }

      // Single API call for account value + balance + positions
      const { positions: exchangePositions, accountValue, availableBalance } =
        await this.orderExecutor.getAccountSnapshot();

      const agentUnrealizedPnl = this._computeAgentUnrealizedPnl(exchangePositions);

      const { totalPnl: totalRealizedPnl, wins: winningTrades, losses: losingTrades, totalTrades } = this._metricsAccum;
      const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

      const metricsRecord = {
        agent_id: this.agentId,
        timestamp: new Date().toISOString(),
        total_pnl: totalRealizedPnl + agentUnrealizedPnl,
        total_trades: totalTrades,
        account_value: accountValue,
        realized_pnl: totalRealizedPnl,
        unrealized_pnl: agentUnrealizedPnl,
        win_rate: winRate,
        available_balance: availableBalance
      };
      
      const { error } = await this.supabase.from('agent_metrics').insert(metricsRecord);
      
      if (error) {
        console.error('Failed to update metrics:', error);
      } else {
        console.log(`📊 Metrics updated: PnL=$${(totalRealizedPnl + agentUnrealizedPnl).toFixed(2)}, Realized=$${totalRealizedPnl.toFixed(2)}, Trades=${totalTrades} (${winningTrades}W/${losingTrades}L), Win Rate=${winRate.toFixed(1)}%`);
      }
    } catch (error) {
      console.error('Failed to update metrics:', error);
    }
  }
  
  // ==========================================================================
  // TRIGGER UTILITY METHODS
  // ==========================================================================
  
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
  registerPriceTrigger(coin, condition, callback) {
    const triggerId = `price_${coin}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.activeTriggers.set(triggerId, {
      type: 'price',
      coin,
      condition,
      lastPrice: null
    });
    this.triggerCallbacks.set(triggerId, callback);
    console.log(`📍 Registered price trigger: ${coin} ${JSON.stringify(condition)}`);
    return triggerId;
  }
  
  /**
   * Register a technical indicator trigger
   * 
   * @param {string} coin - Coin symbol
   * @param {string} indicator - Indicator name ('RSI', 'EMA', 'SMA', 'MACD', 'BollingerBands',
   *                              'ATR', 'ADX', 'Stochastic', 'WilliamsR', 'CCI', 'ROC', 'OBV')
   * @param {Object} params - Indicator parameters (e.g., { period: 14, interval: '1h' })
   * @param {Object} condition - Trigger condition. Supported shapes:
   *   { above: N }                - value > N  (edge-detected)
   *   { below: N }                - value < N  (edge-detected)
   *   { between: [lo, hi] }       - lo <= value <= hi  (edge-detected)
   *   { outside: [lo, hi] }       - value < lo || value > hi  (edge-detected)
   *   { crosses_above: N }        - prev <= N && curr > N
   *   { crosses_below: N }        - prev >= N && curr < N
   *   { crossover: { fast: { indicator, ...params }, slow: { indicator, ...params } } }
   *       - fast series crosses above slow series
   *   { crossunder: { fast: { indicator, ...params }, slow: { indicator, ...params } } }
   *       - fast series crosses below slow series
   *
   *   Optional field on any condition: checkField (string) to pluck a sub-field
   *   from complex indicator objects (e.g., 'histogram' for MACD, 'k' for Stochastic).
   *
   * @param {Function} callback - Async function to call when triggered
   * @returns {string} triggerId
   * 
   * @example
   * // Simple threshold (edge-detected: fires once when RSI drops below 30)
   * this.registerTechnicalTrigger('BTC', 'RSI', { period: 14, interval: '1h' },
   *   { below: 30 }, async (td) => { await this.executeTrade({ ...td, action: 'buy' }); });
   * 
   * @example
   * // EMA crossover (fires once when EMA-9 crosses above EMA-21)
   * this.registerTechnicalTrigger('BTC', 'EMA', { period: 9, interval: '1h' },
   *   { crossover: { fast: { indicator: 'EMA', period: 9 }, slow: { indicator: 'EMA', period: 21 } } },
   *   async (td) => { await this.executeTrade({ ...td, action: 'buy' }); });
   *
   * @example
   * // MACD histogram crosses above zero
   * this.registerTechnicalTrigger('BTC', 'MACD', { interval: '1h' },
   *   { crosses_above: 0, checkField: 'histogram' },
   *   async (td) => { await this.executeTrade({ ...td, action: 'buy' }); });
   */
  registerTechnicalTrigger(coin, indicator, params, condition, callback) {
    const triggerId = `technical_${coin}_${indicator}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.activeTriggers.set(triggerId, {
      type: 'technical',
      coin,
      indicator,
      params,
      condition,
      lastValue: null,
      lastConditionMet: false,
      lastCheckTime: 0
    });
    this.triggerCallbacks.set(triggerId, callback);
    console.log(`📊 Registered technical trigger: ${coin} ${indicator} ${JSON.stringify(condition)}`);
    return triggerId;
  }
  
  /**
   * Register a composite trigger that combines multiple technical conditions
   * with a logical operator.  Fires (edge-detected) when the composite
   * result transitions from false to true.
   *
   * @param {string} coin - Coin symbol
   * @param {'AND'|'OR'} operator - Logical operator across sub-conditions
   * @param {Array<Object>} subConditions - Each element:
   *   { indicator: string, params: Object, condition: Object }
   *   `condition` accepts the same shapes as registerTechnicalTrigger.
   * @param {Function} callback - Async function to call when triggered
   * @returns {string} triggerId
   *
   * @example
   * this.registerCompositeTrigger('BTC', 'AND', [
   *   { indicator: 'RSI', params: { period: 14, interval: '1h' }, condition: { below: 30 } },
   *   { indicator: 'MACD', params: { interval: '1h' }, condition: { crosses_above: 0, checkField: 'histogram' } }
   * ], async (td) => { await this.executeTrade({ ...td, action: 'buy' }); });
   */
  registerCompositeTrigger(coin, operator, subConditions, callback) {
    if (!['AND', 'OR'].includes(operator)) {
      throw new Error(`Invalid composite operator: ${operator} (must be AND or OR)`);
    }
    if (!Array.isArray(subConditions) || subConditions.length < 2) {
      throw new Error('Composite triggers require at least 2 sub-conditions');
    }

    const triggerId = `composite_${coin}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.activeTriggers.set(triggerId, {
      type: 'composite',
      coin,
      operator,
      subConditions: subConditions.map(sc => ({
        ...sc,
        lastConditionMet: false,
        lastValue: null,
      })),
      lastConditionMet: false,
      lastCheckTime: 0,
      params: { interval: subConditions[0].params?.interval || '1h' },
    });
    this.triggerCallbacks.set(triggerId, callback);
    console.log(`📊 Registered composite trigger: ${coin} ${operator} (${subConditions.length} conditions)`);
    return triggerId;
  }
  
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
  registerScheduledTrigger(intervalMs, callback) {
    const triggerId = `scheduled_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const intervalId = setInterval(async () => {
      if (this.isRunning && !this.isPaused) {
        try {
          await callback({ 
            type: 'scheduled', 
            timestamp: Date.now(),
            triggerId 
          });
        } catch (error) {
          console.error(`Scheduled trigger ${triggerId} error:`, error);
        }
      }
    }, intervalMs);
    
    this.activeTriggers.set(triggerId, {
      type: 'scheduled',
      intervalMs,
      intervalId
    });
    this.triggerCallbacks.set(triggerId, callback);
    console.log(`⏰ Registered scheduled trigger: every ${intervalMs}ms`);
    return triggerId;
  }
  
  /**
   * Register an event-based trigger (WebSocket events)
   * 
   * @param {string} eventType
   * @param {Object} condition - Event condition (e.g., { minSize: 10 } for large trades)
   * @param {Function} callback - Async function to call
   * @returns {string} triggerId
   * 
   * @example
   * this.registerEventTrigger('liquidation', { minSize: 1.0 }, async (triggerData) => {
   *   console.log('Large liquidation detected:', triggerData);
   * });
   */
  registerEventTrigger(eventType, condition, callback) {
    const triggerId = `event_${eventType}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.activeTriggers.set(triggerId, {
      type: 'event',
      eventType,
      condition
    });
    this.triggerCallbacks.set(triggerId, callback);
    
    // Subscribe to appropriate WebSocket channel
    if (eventType === 'liquidation') {
      this.wsManager.subscribeLiquidations(async (events) => {
        for (const event of events) {
          if (this._checkEventCondition(event, condition)) {
            await callback({ type: 'liquidation', data: event, triggerId });
          }
        }
      });
    } else if (eventType === 'largeTrade') {
      // Subscribe to trades with size filter
      if (condition.coin) {
        this.wsManager.subscribeTrades(condition.coin, async (trades) => {
          for (const trade of trades) {
            if (this._checkEventCondition(trade, condition)) {
              await callback({ type: 'largeTrade', data: trade, triggerId });
            }
          }
        });
      }
    } else if (eventType === 'userFill') {
      // Fan-out pattern: infrastructure subscribes in start(), we add a callback
      // to the array which is always initialized in the constructor.
      // WS user events arrive as { fills: [...] }, { funding: {...} }, etc.
      this._userEventCallbacks.push(async (event) => {
        if (event && Array.isArray(event.fills)) {
          for (const fill of event.fills) {
            await callback({ type: 'userFill', data: fill, triggerId });
          }
        }
      });
    } else if (eventType === 'l2Book') {
      if (condition.coin) {
        this.wsManager.subscribeL2Book(condition.coin, async (book) => {
          await callback({ type: 'l2Book', data: book, triggerId });
        });
      }
    }
    
    console.log(`🔔 Registered event trigger: ${eventType} ${JSON.stringify(condition)}`);
    return triggerId;
  }
  
  /**
   * Remove a trigger
   * 
   * @param {string} triggerId - Trigger ID to remove
   */
  removeTrigger(triggerId) {
    const trigger = this.activeTriggers.get(triggerId);
    if (trigger) {
      if (trigger.type === 'scheduled' && trigger.intervalId) {
        clearInterval(trigger.intervalId);
      }
      this.activeTriggers.delete(triggerId);
      this.triggerCallbacks.delete(triggerId);
      console.log(`🗑️  Removed trigger: ${triggerId}`);
    }
  }
  
  // ==========================================================================
  // UTILITY METHODS
  // ==========================================================================
  
  /**
   * Check if safety limits are satisfied
   * 
   * @param {string} coin - Coin to check
   * @param {number} proposedSize - Proposed position size
   * @returns {Promise<Object>} { allowed: boolean, reason: string }
   */
  async checkSafetyLimits(coin, proposedSize) {
    // Midnight rollover: if the date changed, reset accumulator and re-seed from DB
    const todayStr = new Date().toISOString().slice(0, 10);
    if (todayStr !== this._dailyPnlDate) {
      this._dailyPnlDate = todayStr;
      this._dailyPnl = 0;
      // One-time reconciliation query on date change
      try {
        const dayStart = new Date();
        dayStart.setHours(0, 0, 0, 0);
        const { data: trades } = await this.supabase
          .from('agent_trades')
          .select('pnl')
          .eq('agent_id', this.agentId)
          .gte('timestamp', dayStart.toISOString());
        this._dailyPnl = trades?.reduce((s, t) => s + toFiniteNumber(t.pnl, 0), 0) || 0;
      } catch { /* proceed with 0 if query fails */ }
    }

    if (this._dailyPnl < -this.dailyLossLimit) {
      return {
        allowed: false,
        reason: `Daily loss limit reached: ${this._dailyPnl.toFixed(2)} USD`
      };
    }

    return { allowed: true, reason: 'OK' };
  }
  
  // ==========================================================================
  // LIFECYCLE METHODS
  // ==========================================================================
  
  /**
   * Start the agent
   * 
   * 1. Call onInitialize() (abstract method)
   * 2. Call setupTriggers() (abstract method)
   * 3. Start monitoring loop
   * 4. Update state to 'running'
   */
  async start() {
    if (this.isRunning) {
      console.warn('⚠️  Agent already running');
      return;
    }
    
    try {
      console.log(`\n🚀 Starting agent ${this.agentId}...`);
      await this.updateState('lifecycle', {}, 'Agent starting');
      
      // Ensure fee rates are loaded before any trades
      console.log('💰 Fetching user fee rates...');
      await this.orderExecutor.fetchUserFeeRates();
      
      // Reconcile PositionTracker with actual exchange positions
      console.log('📋 Reconciling position tracker...');
      await this.reconcileTrackedPositions();
      
      // Call abstract initialization method
      console.log('📋 Running onInitialize()...');
      await this.onInitialize();
      
      // Call abstract trigger setup method
      console.log('🎯 Running setupTriggers()...');
      await this.setupTriggers();
      
      // Initialize WebSocket price cache for low-latency price triggers
      this._cachedMids = null;
      this._midsLastUpdate = 0;
      this._wsConnected = false;
      
      console.log('📡 Subscribing to WebSocket price feed...');
      try {
        this.wsManager.subscribeAllMids((data) => {
          this._cachedMids = data.mids;
          this._midsLastUpdate = Date.now();
          this._wsConnected = true;
        });
      } catch (e) {
        console.warn('⚠️  WebSocket price subscription failed, using REST fallback:', e.message);
      }
      
      // Subscribe to user fill events for real-time SL/TP + liquidation detection.
      // Uses a fan-out pattern so agent-level userFill triggers can coexist
      // with this infrastructure-level handler.
      console.log('📡 Subscribing to user fill events for SL/TP + liquidation detection...');
      try {
        this.wsManager.subscribeUserEvents((event) => {
          // Infrastructure: route fill events to PositionTracker for SL/TP and liquidation detection.
          // WS user events arrive as { fills: [...] }, { funding: {...} }, etc.
          if (event && Array.isArray(event.fills)) {
            for (const fill of event.fills) {
              // Check if this fill is a liquidation of this agent's position
              if (fill.liquidation && fill.liquidation.liquidatedUser === this.userAddress) {
                // This is OUR position being liquidated
                this.positionTracker.handleLiquidationFill(fill);
              } else {
                // Normal fill — check if it's an SL/TP fill
                this.positionTracker.handleFillEvent(fill);
              }
            }
          }
          // Fan out to any agent-level userFill triggers
          for (const cb of this._userEventCallbacks) {
            try { cb(event); } catch (_) { /* swallow per-trigger errors */ }
          }
        });
      } catch (e) {
        console.warn('⚠️  User events subscription failed, SL/TP + liquidation detection will use REST fallback:', e.message);
      }
      
      // Start monitoring
      this.isRunning = true;
      this.currentState = 'running';
      await this.updateState('lifecycle', {}, 'Agent running');
      
      console.log('✅ Agent started successfully');
      console.log(`   Active triggers: ${this.activeTriggers.size}`);
      
      // Start monitoring loop (don't await - runs continuously)
      this.monitor().catch(error => {
        console.error('Monitor loop crashed:', error);
        this.currentState = 'error';
      });
      
    } catch (error) {
      console.error('❌ Failed to start agent:', error);
      this.currentState = 'error';
      await this.updateState('error', { error: error.message }, 'Start failed');
      throw error;
    }
  }
  
  /**
   * Monitoring loop
   * Evaluates all active triggers continuously
   */
  async monitor() {
    console.log('👀 Monitor loop started');
    console.log(`   Active triggers: ${this.activeTriggers.size}`);
    console.log(`   - Price: ${Array.from(this.activeTriggers.values()).filter(t => t.type === 'price').length}`);
    console.log(`   - Technical: ${Array.from(this.activeTriggers.values()).filter(t => t.type === 'technical').length}`);
    console.log(`   - Composite: ${Array.from(this.activeTriggers.values()).filter(t => t.type === 'composite').length}`);
    console.log(`   - Scheduled: ${Array.from(this.activeTriggers.values()).filter(t => t.type === 'scheduled').length}`);
    console.log(`   - Event: ${Array.from(this.activeTriggers.values()).filter(t => t.type === 'event').length}`);
    
    const monitorStart = Date.now();
    let nextTechnicalEvalAt = monitorStart + TECHNICAL_EVAL_INTERVAL_MS;
    let nextHeartbeatPersistAt = monitorStart + HEARTBEAT_PERSIST_INTERVAL_MS;
    let nextPositionSyncAt = monitorStart + POSITION_SYNC_INTERVAL_MS;
    let nextMetricsAt = monitorStart + METRICS_INTERVAL_MS;
    let nextFeeRefreshAt = monitorStart + FEE_REFRESH_INTERVAL_MS;
    
    while (this.isRunning) {
      let triggerFiredThisLoop = false;
      
      if (!this.isPaused) {
        try {
          const loopNow = Date.now();
          this.lastHeartbeat = loopNow;
          
          // Evaluate price triggers
          const priceFired = await this._evaluatePriceTriggers();
          if (priceFired) triggerFiredThisLoop = true;
          
          // Evaluate technical + composite triggers every 10s.
          if (loopNow >= nextTechnicalEvalAt) {
            await this._evaluateTechnicalTriggers();
            await this._evaluateCompositeTriggers();
            nextTechnicalEvalAt = loopNow + TECHNICAL_EVAL_INTERVAL_MS;
          }
          
          // Persist heartbeat to Supabase every 60 seconds.
          if (loopNow >= nextHeartbeatPersistAt) {
            this.supabase.from('agents')
              .update({ last_heartbeat: new Date(loopNow).toISOString() })
              .eq('id', this.agentId)
              .then(() => {})
              .catch(() => {}); // Fire-and-forget; don't block loop
            nextHeartbeatPersistAt = loopNow + HEARTBEAT_PERSIST_INTERVAL_MS;
          }
          
          // Reconcile + sync positions every 60 seconds (single API call).
          if (loopNow >= nextPositionSyncAt) {
            await this._reconcileAndSync();
            nextPositionSyncAt = loopNow + POSITION_SYNC_INTERVAL_MS;
          }
          
          // Update metrics every 5 minutes.
          if (loopNow >= nextMetricsAt) {
            await this.updateMetrics();
            nextMetricsAt = loopNow + METRICS_INTERVAL_MS;
          }
          
          // Refresh fee rates every hour.
          if (loopNow >= nextFeeRefreshAt) {
            this.orderExecutor.fetchUserFeeRates().catch(err => {
              console.warn('⚠️  Fee rate refresh failed:', err.message);
            });
            // Prune stale entries from order ownership store
            if (this.orderExecutor.orderOwnershipStore) {
              this.orderExecutor.orderOwnershipStore.prune();
            }
            nextFeeRefreshAt = loopNow + FEE_REFRESH_INTERVAL_MS;
          }
          
        } catch (error) {
          console.error('❌ Monitor loop error:', error);
          await this.updateState('error', { error: error.message }, 'Monitor error');
        }
      }
      
      // Adaptive sleep: shorter after trigger fires for faster reaction
      const sleepMs = triggerFiredThisLoop ? 200 : 1000;
      await new Promise(resolve => setTimeout(resolve, sleepMs));
    }
    
    console.log('👋 Monitor loop stopped');
  }
  
  /**
   * Pause the agent (stops executing triggers but keeps monitoring)
   */
  async pause() {
    if (!this.isRunning) {
      console.warn('⚠️  Agent not running');
      return;
    }
    
    this.isPaused = true;
    this.currentState = 'paused';
    await this.updateState('lifecycle', {}, 'Agent paused');
    console.log(`⏸️  Agent ${this.agentId} paused`);
  }
  
  /**
   * Resume the agent
   */
  async resume() {
    if (!this.isPaused) {
      console.warn('⚠️  Agent not paused');
      return;
    }
    
    this.isPaused = false;
    this.currentState = 'running';
    await this.updateState('lifecycle', {}, 'Agent resumed');
    console.log(`▶️  Agent ${this.agentId} resumed`);
  }
  
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
    // Guard: if shutdown is already in progress, wait for it to finish rather than
    // returning early. This prevents the race condition where a second SHUTDOWN call
    // (from polling fallback) triggers process.exit(0) while the first is mid-flight.
    if (this._shutdownInProgress) {
      console.warn('⚠️  Shutdown already in progress — waiting for it to complete');
      return this._shutdownPromise;
    }

    if (!this.isRunning) {
      console.warn('⚠️  Agent not running');
      return;
    }
    
    this._shutdownInProgress = true;
    this._shutdownPromise = this._executeShutdown();
    return this._shutdownPromise;
  }

  async _executeShutdown() {
    try {
      console.log(`\n🛑 Shutting down agent ${this.agentId}...`);
      await this.updateState('lifecycle', {}, 'Agent shutting down');
      
      // Stop monitoring loop
      this.isRunning = false;
      
      // Give monitor loop time to exit gracefully
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Cancel all scheduled triggers
      for (const [triggerId, trigger] of this.activeTriggers.entries()) {
        if (trigger.type === 'scheduled' && trigger.intervalId) {
          clearInterval(trigger.intervalId);
        }
      }
      
      // Cancel open orders ONLY for coins this agent is tracking
      const agentCoins = Object.keys(this.positionTracker.openPositions);
      if (agentCoins.length > 0) {
        console.log(`📝 Cancelling orders for agent's coins: ${agentCoins.join(', ')}...`);
        for (const coin of agentCoins) {
          try {
            const cancelResult = await this.orderExecutor.cancelAgentOrders(coin);
            if (cancelResult.success) {
              console.log(`   ✅ ${coin} owned orders cancelled (${cancelResult.status || 'ok'})`);
            } else {
              console.warn(`   ⚠️  Partial/failed cancel for ${coin}: ${cancelResult.error || cancelResult.status}`);
            }
          } catch (e) {
            console.warn(`   ⚠️  Failed to cancel ${coin} orders: ${e.message}`);
          }
        }
      }
      
      // Close ONLY this agent's tracked positions (not all account positions)
      {
        console.log('💰 Closing agent positions...');
        const trackedCoins = Object.keys(this.positionTracker.openPositions);
        
        for (const coin of trackedCoins) {
          try {
            const localPos = this.positionTracker.openPositions[coin];
            if (!localPos) continue;
            
            const agentSize = localPos.entry.size;
            const isLong = localPos.entry.side === 'buy';
            
            console.log(`   Closing ${coin}: ${isLong ? '+' : '-'}${agentSize} (agent's tracked size)`);
            
            // Close only the agent's portion using partial close
            const closeResult = await this.orderExecutor.closePosition(coin, agentSize);
            
            if (closeResult.success) {
              console.log(`   ✅ ${coin} position closed`);
              await this.logTrade({
                coin,
                side: isLong ? 'sell' : 'buy',
                size: closeResult.filledSize || agentSize,
                price: closeResult.averagePrice,
                order_type: 'close_position',
                order_id: closeResult.orderId,
                trigger_reason: 'Agent shutdown - closing tracked positions',
                is_exit: true,
                fee: closeResult.fee,
                fee_rate: closeResult.feeRate
              });
            } else {
              console.warn(`   ⚠️  Failed to close ${coin}: ${closeResult.error}`);
            }
          } catch (e) {
            console.error(`   ❌ Error closing ${coin} during shutdown: ${e.message}`);
          }
        }
      }
      
      // Reconcile position tracker BEFORE closing WS (needs API access)
      console.log('📊 Reconciling positions after closes...');
      await this.reconcileTrackedPositions();

      // Close WebSocket connections
      console.log('🔌 Closing WebSocket connections...');
      this.wsManager.close();
      
      // Print PnL summary from local tracker
      console.log('\n📊 Final PnL Summary:');
      this.positionTracker.printSummary();
      
      // Final comprehensive state sync and evaluation
      console.log('📊 Recording final evaluation...');
      
      // Single API call for all account data
      const { positions, accountValue, availableBalance } =
        await this.orderExecutor.getAccountSnapshot();
      
      // Get all trades for final summary
      const { data: trades } = await this.supabase
        .from('agent_trades')
        .select('pnl')
        .eq('agent_id', this.agentId);
      
      const tradesWithPnl = trades?.filter(t => t.pnl !== null && t.pnl !== undefined) || [];
      const { totalRealizedPnl, winningTrades, losingTrades, winRate, totalTrades } =
        this._computeTradeMetrics(tradesWithPnl);
      const totalUnrealizedPnl = this._computeAgentUnrealizedPnl(positions);
      
      // Cross-reference with PositionTracker for validation
      const trackerStats = this.positionTracker.getTotalStats();
      if (trackerStats.totalTrades > 0 && Math.abs(trackerStats.totalNetPnl - totalRealizedPnl) > 0.01) {
        console.warn(`⚠️  PnL mismatch: Supabase=$${totalRealizedPnl.toFixed(2)}, PositionTracker=$${trackerStats.totalNetPnl.toFixed(2)}`);
      }
      
      // Record final evaluation
      const finalEvaluation = {
        timestamp: new Date().toISOString(),
        account_value: accountValue,
        available_balance: availableBalance,
        total_pnl: totalRealizedPnl + totalUnrealizedPnl,
        realized_pnl: totalRealizedPnl,
        unrealized_pnl: totalUnrealizedPnl,
        total_trades: totalTrades,
        winning_trades: winningTrades,
        losing_trades: losingTrades,
        win_rate: winRate,
        open_positions: positions.length,
        positions_detail: positions.map(p => ({
          coin: p.coin,
          size: p.size,
          entry_price: p.entryPrice,
          unrealized_pnl: p.unrealizedPnl
        })),
        // Include PositionTracker stats for cross-reference
        tracker_stats: trackerStats
      };
      
      // Store final evaluation in agent_metrics
      const finalMetrics = {
        agent_id: this.agentId,
        timestamp: finalEvaluation.timestamp,
        total_pnl: finalEvaluation.total_pnl,
        total_trades: finalEvaluation.total_trades,
        account_value: finalEvaluation.account_value,
        realized_pnl: totalRealizedPnl,
        unrealized_pnl: totalUnrealizedPnl,
        win_rate: winRate,
        available_balance: availableBalance
      };
      
      const { error: metricsError } = await this.supabase.from('agent_metrics').insert(finalMetrics);
      if (metricsError) {
        console.error('Failed to store final metrics:', metricsError);
      }
      
      // Store detailed evaluation in agent_states
      await this.updateState('final_evaluation', finalEvaluation, 'Agent shutdown - final evaluation');
      
      // Update agent status in agents table
      await this.supabase
        .from('agents')
        .update({ 
          status: 'stopped',
          agent_deployed: false,
          updated_at: new Date().toISOString()
        })
        .eq('id', this.agentId);
      
      this.currentState = 'stopped';
      
      // Log final summary to console
      console.log('\n╔═══════════════════════════════════════════════════════╗');
      console.log('║              FINAL AGENT EVALUATION                   ║');
      console.log('╚═══════════════════════════════════════════════════════╝');
      console.log(`📊 Trading Summary:`);
      console.log(`   Total Trades: ${totalTrades}`);
      console.log(`   Winning Trades: ${winningTrades}`);
      console.log(`   Losing Trades: ${losingTrades}`);
      console.log(`   Win Rate: ${winRate.toFixed(1)}%`);
      console.log(`\n💰 Financial Summary:`);
      console.log(`   Realized PnL: $${totalRealizedPnl.toFixed(2)}`);
      console.log(`   Unrealized PnL: $${totalUnrealizedPnl.toFixed(2)}`);
      console.log(`   Total PnL: $${(totalRealizedPnl + totalUnrealizedPnl).toFixed(2)}`);
      console.log(`   Account Value: $${accountValue.toFixed(2)}`);
      console.log(`   Available Balance: $${availableBalance.toFixed(2)}`);
      console.log(`\n📍 Open Positions: ${positions.length}`);
      if (positions.length > 0) {
        positions.forEach(p => {
          console.log(`   ${p.coin}: ${p.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(p.size)} @ $${p.entryPrice} (PnL: $${p.unrealizedPnl.toFixed(2)})`);
        });
      }
      console.log(`\n✅ Agent ${this.agentId} shut down successfully`);
      
    } catch (error) {
      console.error('❌ Shutdown error:', error);
      try {
        await this.updateState('error', { error: error.message }, `Shutdown failed: ${error.message}`);
        // Still try to update DB status even on error
        await this.supabase
          .from('agents')
          .update({ 
            status: 'stopped',
            agent_deployed: false,
            updated_at: new Date().toISOString()
          })
          .eq('id', this.agentId);
      } catch (dbError) {
        console.error('❌ Failed to update DB during shutdown error:', dbError.message);
      }
      throw error;
    } finally {
      this._shutdownInProgress = false;
    }
  }
  
  // ==========================================================================
  // PRIVATE HELPER METHODS
  // ==========================================================================
  
  /**
   * Get current mid prices with WebSocket cache and REST fallback.
   * Uses cached WS data if fresh (< 5 seconds), otherwise falls back to REST.
   * @private
   * @returns {Promise<Object>} Mid prices keyed by coin symbol
   */
  async _getCurrentMids() {
    // Use WebSocket cache if fresh (< 5 seconds old)
    if (this._cachedMids && (Date.now() - this._midsLastUpdate) < 5000) {
      return this._cachedMids;
    }
    // Fallback to REST
    if (this._wsConnected) {
      this._wsConnected = false;
      console.warn('⚠️  WS price cache stale (>5s), falling back to REST');
    }
    return await getAllMids();
  }

  /**
   * Evaluate all price triggers
   * @private
   */
  async _evaluatePriceTriggers() {
    try {
      const mids = await this._getCurrentMids();
      let triggersChecked = 0;
      let triggersFired = 0;
      
      for (const [triggerId, trigger] of this.activeTriggers.entries()) {
        if (trigger.type !== 'price') continue;
        
        triggersChecked++;
        const currentPrice = parseFloat(mids[trigger.coin] || "0");
        if (currentPrice === 0) continue;
        
        const { condition, lastPrice } = trigger;
        let shouldTrigger = false;
        const hasAbove = condition.above !== undefined && condition.above !== null;
        const hasBelow = condition.below !== undefined && condition.below !== null;
        const hasCrosses = condition.crosses !== undefined && condition.crosses !== null;
        const hasLastPrice = lastPrice !== null && lastPrice !== undefined;
        
        if (hasAbove && currentPrice > condition.above && (!hasLastPrice || lastPrice <= condition.above)) {
          shouldTrigger = true;
        } else if (hasBelow && currentPrice < condition.below && (!hasLastPrice || lastPrice >= condition.below)) {
          shouldTrigger = true;
        } else if (hasCrosses && hasLastPrice) {
          if ((lastPrice < condition.crosses && currentPrice >= condition.crosses) ||
              (lastPrice > condition.crosses && currentPrice <= condition.crosses)) {
            shouldTrigger = true;
          }
        }
        
        if (shouldTrigger) {
          triggersFired++;
          console.log(`🎯 Price trigger: ${trigger.coin} @ $${currentPrice.toFixed(2)} met condition ${JSON.stringify(condition)}`);
          
          await this.updateState('trigger_fired', {
            type: 'price',
            coin: trigger.coin,
            price: currentPrice,
            condition: condition
          }, `Price trigger fired: ${trigger.coin} @ $${currentPrice.toFixed(2)}`);
          
          const callback = this.triggerCallbacks.get(triggerId);
          if (callback) {
            await callback({
              type: 'price',
              coin: trigger.coin,
              price: currentPrice,
              condition: condition,
              triggerId
            });
          }
        }
        
        // Update last price
        trigger.lastPrice = currentPrice;
      }
      
      // Log summary if triggers were checked but none fired
      if (triggersChecked > 0 && triggersFired === 0) {
        const coins = Array.from(this.activeTriggers.values())
          .filter(t => t.type === 'price')
          .map(t => t.coin);
        console.log(`✓ Checked ${triggersChecked} price trigger(s) [${coins.join(', ')}] - no conditions met`);
      }
      
      return triggersFired > 0;
    } catch (error) {
      console.error('Error evaluating price triggers:', error);
      return false;
    }
  }
  
  /**
   * Evaluate all technical indicator triggers
   * @private
   */
  /**
   * Evaluate all technical indicator triggers.
   *
   * Features:
   *   - Edge detection: callbacks fire only on the false -> true transition.
   *   - "Condition not met" status is reported via updateState (not console).
   *   - Dynamic candle lookback based on indicator period + interval.
   *   - Full OHLCV data passed to TechnicalIndicatorService.
   *   - Rich condition types: above, below, between, outside,
   *     crosses_above, crosses_below, crossover, crossunder.
   *
   * @private
   */
  async _evaluateTechnicalTriggers() {
    const technicalTriggers = Array.from(this.activeTriggers.entries())
      .filter(([, t]) => t.type === 'technical');

    if (technicalTriggers.length === 0) return;

    const now = Date.now();
    const triggersToEval = technicalTriggers.filter(
      ([, t]) => (now - t.lastCheckTime) >= TECHNICAL_TRIGGER_RATE_LIMIT_MS
    );
    if (triggersToEval.length === 0) return;

    // ------------------------------------------------------------------
    // 1. Deduplicate candle requests by coin+interval
    // ------------------------------------------------------------------
    const candleKeyTriggers = new Map(); // key -> [trigger entries]
    for (const entry of triggersToEval) {
      const trigger = entry[1];
      const key = `${trigger.coin}:${trigger.params.interval || '1h'}`;
      if (!candleKeyTriggers.has(key)) candleKeyTriggers.set(key, []);
      candleKeyTriggers.get(key).push(entry);
    }

    // ------------------------------------------------------------------
    // 2. Dynamic lookback: compute per key based on max period needed
    // ------------------------------------------------------------------
    const endTime = Date.now();
    const candleCache = new Map();
    const candleEntries = Array.from(candleKeyTriggers.entries());

    const candlePromises = candleEntries.map(([key, entries]) => {
      const [coin, interval] = key.split(':');
      const intervalMs = INTERVAL_MS_MAP[interval] || INTERVAL_MS_MAP['1h'];

      // Find the largest period any trigger in this group needs
      let maxPeriod = MIN_CANDLES_REQUIRED;
      for (const [, t] of entries) {
        const p = t.params.period || t.params.slowPeriod || 26;
        if (p > maxPeriod) maxPeriod = p;
        // crossover/crossunder may reference sub-indicators with their own periods
        const cond = t.condition;
        const crossDef = cond.crossover || cond.crossunder;
        if (crossDef) {
          const fp = crossDef.fast?.period || crossDef.fast?.slowPeriod || 0;
          const sp = crossDef.slow?.period || crossDef.slow?.slowPeriod || 0;
          if (fp > maxPeriod) maxPeriod = fp;
          if (sp > maxPeriod) maxPeriod = sp;
        }
      }

      const startTime = endTime - (maxPeriod * CANDLE_LOOKBACK_MULTIPLIER * intervalMs);

      return getCandleSnapshot(coin, interval, startTime, endTime)
        .then(data => candleCache.set(key, data))
        .catch(err => {
          console.error(`❌ Candle fetch error for ${key}:`, err.message);
          candleCache.set(key, null);
        });
    });

    await Promise.all(candlePromises);

    // ------------------------------------------------------------------
    // 3. Evaluate each trigger
    // ------------------------------------------------------------------
    let triggersEvaluated = 0;
    let triggersFired = 0;

    for (const [triggerId, trigger] of triggersToEval) {
      trigger.lastCheckTime = now;
      triggersEvaluated++;

      try {
        const key = `${trigger.coin}:${trigger.params.interval || '1h'}`;
        const candles = candleCache.get(key);

        if (!candles || candles.length < MIN_CANDLES_REQUIRED) {
          await this.updateState('trigger_check', {
            triggerId,
            coin: trigger.coin,
            indicator: trigger.indicator,
            status: 'insufficient_data',
            candleCount: candles?.length || 0,
          }, `${trigger.coin} ${trigger.indicator}: Insufficient data (${candles?.length || 0} candles)`);
          continue;
        }

        // Build full OHLCV object
        const candleData = {
          closes: candles.map(c => c.close),
          highs: candles.map(c => c.high),
          lows: candles.map(c => c.low),
          opens: candles.map(c => c.open),
          volumes: candles.map(c => c.volume),
        };

        const { condition } = trigger;
        let conditionMet = false;
        let indicatorValue = null;
        let displayValue = null; // human-readable value for state messages

        // ---------------------------------------------------------------
        // Crossover / Crossunder (two-series comparison)
        // ---------------------------------------------------------------
        const crossDef = condition.crossover || condition.crossunder;
        if (crossDef) {
          const fastInd = crossDef.fast?.indicator || trigger.indicator;
          const slowInd = crossDef.slow?.indicator || trigger.indicator;
          const fastParams = { ...trigger.params, ...crossDef.fast };
          const slowParams = { ...trigger.params, ...crossDef.slow };
          delete fastParams.indicator;
          delete slowParams.indicator;

          const { a: fastSeries, b: slowSeries } = await this._technicalIndicatorService.computePair(
            fastInd, fastParams, slowInd, slowParams, candleData, 2
          );

          if (fastSeries.length >= 2 && slowSeries.length >= 2) {
            const extractVal = (v) => {
              if (condition.checkField && typeof v === 'object') return v[condition.checkField];
              return v;
            };

            const prevFast = extractVal(fastSeries[0]);
            const currFast = extractVal(fastSeries[1]);
            const prevSlow = extractVal(slowSeries[0]);
            const currSlow = extractVal(slowSeries[1]);

            if (condition.crossover) {
              conditionMet = prevFast <= prevSlow && currFast > currSlow;
            } else {
              conditionMet = prevFast >= prevSlow && currFast < currSlow;
            }

            indicatorValue = { fast: currFast, slow: currSlow };
            displayValue = `fast=${typeof currFast === 'number' ? currFast.toFixed(2) : JSON.stringify(currFast)}, slow=${typeof currSlow === 'number' ? currSlow.toFixed(2) : JSON.stringify(currSlow)}`;
          }

        // ---------------------------------------------------------------
        // Crosses above / below a threshold (needs last 2 values)
        // ---------------------------------------------------------------
        } else if (condition.crosses_above !== undefined || condition.crosses_below !== undefined) {
          const series = await this._technicalIndicatorService.computeSeries(
            trigger.indicator, candleData, trigger.params, 2
          );

          if (series.length >= 2) {
            const extractVal = (v) => {
              if (condition.checkField && typeof v === 'object') return v[condition.checkField];
              return v;
            };

            const prev = extractVal(series[0]);
            const curr = extractVal(series[1]);
            indicatorValue = series[1];

            if (condition.crosses_above !== undefined) {
              const threshold = toPrecision(condition.crosses_above, 6);
              conditionMet = prev <= threshold && curr > threshold;
            } else {
              const threshold = toPrecision(condition.crosses_below, 6);
              conditionMet = prev >= threshold && curr < threshold;
            }

            displayValue = typeof curr === 'number' ? curr.toFixed(2) : JSON.stringify(curr);
          }

        // ---------------------------------------------------------------
        // Simple threshold / range conditions
        // ---------------------------------------------------------------
        } else {
          indicatorValue = await this._technicalIndicatorService.compute(
            trigger.indicator, candleData, trigger.params
          );

          if (indicatorValue === null || indicatorValue === undefined) continue;

          let checkValue = indicatorValue;
          if (condition.checkField && typeof indicatorValue === 'object') {
            checkValue = indicatorValue[condition.checkField];
          }

          displayValue = typeof checkValue === 'number' ? checkValue.toFixed(2) : JSON.stringify(checkValue);

          if (condition.above !== undefined) {
            const threshold = toPrecision(condition.above, 6);
            conditionMet = checkValue > threshold && !compareFloats(checkValue, threshold);
          } else if (condition.below !== undefined) {
            const threshold = toPrecision(condition.below, 6);
            conditionMet = checkValue < threshold && !compareFloats(checkValue, threshold);
          } else if (condition.between !== undefined) {
            const [lo, hi] = condition.between;
            conditionMet = checkValue >= toPrecision(lo, 6) && checkValue <= toPrecision(hi, 6);
          } else if (condition.outside !== undefined) {
            const [lo, hi] = condition.outside;
            conditionMet = checkValue < toPrecision(lo, 6) || checkValue > toPrecision(hi, 6);
          }
        }

        // ---------------------------------------------------------------
        // Edge detection + state reporting
        // ---------------------------------------------------------------
        const wasMet = trigger.lastConditionMet;

        if (conditionMet && !wasMet) {
          // --- FIRE: false -> true transition ---
          triggersFired++;
          console.log(`🎯 Technical trigger: ${trigger.coin} ${trigger.indicator}=${displayValue} met condition ${JSON.stringify(condition)}`);

          await this.updateState('trigger_fired', {
            type: 'technical',
            triggerId,
            coin: trigger.coin,
            indicator: trigger.indicator,
            value: indicatorValue,
            condition,
          }, `Technical trigger fired: ${trigger.coin} ${trigger.indicator}=${displayValue}`);

          const callback = this.triggerCallbacks.get(triggerId);
          if (callback) {
            await callback({
              type: 'technical',
              coin: trigger.coin,
              indicator: trigger.indicator,
              value: indicatorValue,
              condition,
              triggerId,
            });
          }

        } else if (conditionMet && wasMet) {
          // --- Still active, no re-fire ---
          await this.updateState('trigger_check', {
            triggerId,
            coin: trigger.coin,
            indicator: trigger.indicator,
            value: indicatorValue,
            status: 'still_active',
          }, `${trigger.coin} ${trigger.indicator}=${displayValue} — condition still active (already fired)`);

        } else {
          // --- Condition not met ---
          await this.updateState('trigger_check', {
            triggerId,
            coin: trigger.coin,
            indicator: trigger.indicator,
            value: indicatorValue,
            status: 'not_met',
            condition,
          }, `${trigger.coin} ${trigger.indicator}=${displayValue} — condition not met`);
        }

        trigger.lastConditionMet = conditionMet;
        trigger.lastValue = indicatorValue;
      } catch (error) {
        console.error(`❌ Technical trigger ${triggerId} error:`, error.message);
      }
    }

    if (triggersEvaluated > 0) {
      console.log(`📊 Technical check complete: ${triggersEvaluated} evaluated, ${triggersFired} fired (${candleEntries.length} unique candle fetches)`);
    }
  }
  
  /**
   * Evaluate a single technical sub-condition against candle data.
   * Returns { met: boolean, value: any, display: string }.
   * @private
   */
  async _evaluateSubCondition(sc, candleData) {
    const { condition } = sc;

    // --- crossover / crossunder ---
    const crossDef = condition.crossover || condition.crossunder;
    if (crossDef) {
      const fastInd = crossDef.fast?.indicator || sc.indicator;
      const slowInd = crossDef.slow?.indicator || sc.indicator;
      const fastParams = { ...sc.params, ...crossDef.fast }; delete fastParams.indicator;
      const slowParams = { ...sc.params, ...crossDef.slow }; delete slowParams.indicator;

      const { a: fs, b: ss } = await this._technicalIndicatorService.computePair(
        fastInd, fastParams, slowInd, slowParams, candleData, 2
      );

      if (fs.length >= 2 && ss.length >= 2) {
        const ext = (v) => (condition.checkField && typeof v === 'object') ? v[condition.checkField] : v;
        const [pf, cf] = [ext(fs[0]), ext(fs[1])];
        const [ps, cs] = [ext(ss[0]), ext(ss[1])];
        const met = condition.crossover ? (pf <= ps && cf > cs) : (pf >= ps && cf < cs);
        return { met, value: { fast: cf, slow: cs }, display: `fast=${typeof cf === 'number' ? cf.toFixed(2) : cf},slow=${typeof cs === 'number' ? cs.toFixed(2) : cs}` };
      }
      return { met: false, value: null, display: 'N/A' };
    }

    // --- crosses_above / crosses_below ---
    if (condition.crosses_above !== undefined || condition.crosses_below !== undefined) {
      const series = await this._technicalIndicatorService.computeSeries(sc.indicator, candleData, sc.params, 2);
      if (series.length >= 2) {
        const ext = (v) => (condition.checkField && typeof v === 'object') ? v[condition.checkField] : v;
        const prev = ext(series[0]), curr = ext(series[1]);
        let met = false;
        if (condition.crosses_above !== undefined) {
          met = prev <= toPrecision(condition.crosses_above, 6) && curr > toPrecision(condition.crosses_above, 6);
        } else {
          met = prev >= toPrecision(condition.crosses_below, 6) && curr < toPrecision(condition.crosses_below, 6);
        }
        return { met, value: series[1], display: typeof curr === 'number' ? curr.toFixed(2) : JSON.stringify(curr) };
      }
      return { met: false, value: null, display: 'N/A' };
    }

    // --- simple threshold / range ---
    const val = await this._technicalIndicatorService.compute(sc.indicator, candleData, sc.params);
    if (val === null || val === undefined) return { met: false, value: null, display: 'N/A' };
    let chk = (condition.checkField && typeof val === 'object') ? val[condition.checkField] : val;
    const disp = typeof chk === 'number' ? chk.toFixed(2) : JSON.stringify(chk);
    let met = false;

    if (condition.above !== undefined) {
      met = chk > toPrecision(condition.above, 6) && !compareFloats(chk, condition.above);
    } else if (condition.below !== undefined) {
      met = chk < toPrecision(condition.below, 6) && !compareFloats(chk, condition.below);
    } else if (condition.between !== undefined) {
      met = chk >= toPrecision(condition.between[0], 6) && chk <= toPrecision(condition.between[1], 6);
    } else if (condition.outside !== undefined) {
      met = chk < toPrecision(condition.outside[0], 6) || chk > toPrecision(condition.outside[1], 6);
    }

    return { met, value: val, display: disp };
  }

  /**
   * Evaluate all composite triggers.
   * @private
   */
  async _evaluateCompositeTriggers() {
    const compositeTriggers = Array.from(this.activeTriggers.entries())
      .filter(([, t]) => t.type === 'composite');
    if (compositeTriggers.length === 0) return;

    const now = Date.now();
    const due = compositeTriggers.filter(
      ([, t]) => (now - t.lastCheckTime) >= TECHNICAL_TRIGGER_RATE_LIMIT_MS
    );
    if (due.length === 0) return;

    // Build shared candle cache (same dedup logic as technical triggers)
    const endTime = Date.now();
    const candleCache = new Map();
    const keysNeeded = new Set();

    for (const [, trigger] of due) {
      for (const sc of trigger.subConditions) {
        const interval = sc.params?.interval || trigger.params.interval || '1h';
        keysNeeded.add(`${trigger.coin}:${interval}`);
      }
    }

    await Promise.all(Array.from(keysNeeded).map(async (key) => {
      const [coin, interval] = key.split(':');
      const intervalMs = INTERVAL_MS_MAP[interval] || INTERVAL_MS_MAP['1h'];
      const startTime = endTime - (200 * CANDLE_LOOKBACK_MULTIPLIER * intervalMs);
      try {
        const candles = await getCandleSnapshot(coin, interval, startTime, endTime);
        candleCache.set(key, candles);
      } catch (err) {
        console.error(`❌ Candle fetch for composite ${key}:`, err.message);
        candleCache.set(key, null);
      }
    }));

    for (const [triggerId, trigger] of due) {
      trigger.lastCheckTime = now;

      try {
        const subResults = [];
        for (const sc of trigger.subConditions) {
          const interval = sc.params?.interval || trigger.params.interval || '1h';
          const key = `${trigger.coin}:${interval}`;
          const candles = candleCache.get(key);
          if (!candles || candles.length < MIN_CANDLES_REQUIRED) {
            subResults.push({ met: false, value: null, display: 'insufficient data' });
            continue;
          }
          const candleData = {
            closes: candles.map(c => c.close),
            highs: candles.map(c => c.high),
            lows: candles.map(c => c.low),
            opens: candles.map(c => c.open),
            volumes: candles.map(c => c.volume),
          };
          const result = await this._evaluateSubCondition(sc, candleData);
          sc.lastConditionMet = result.met;
          sc.lastValue = result.value;
          subResults.push(result);
        }

        const compositeMet = trigger.operator === 'AND'
          ? subResults.every(r => r.met)
          : subResults.some(r => r.met);

        const wasMet = trigger.lastConditionMet;
        const summary = trigger.subConditions.map((sc, i) =>
          `${sc.indicator}=${subResults[i].display}(${subResults[i].met ? 'met' : 'not met'})`
        ).join(', ');

        if (compositeMet && !wasMet) {
          console.log(`🎯 Composite trigger: ${trigger.coin} ${trigger.operator} — ${summary}`);
          await this.updateState('trigger_fired', {
            type: 'composite',
            triggerId,
            coin: trigger.coin,
            operator: trigger.operator,
            subResults: subResults.map((r, i) => ({
              indicator: trigger.subConditions[i].indicator,
              value: r.value, met: r.met,
            })),
          }, `Composite trigger fired: ${trigger.coin} ${trigger.operator} — ${summary}`);

          const callback = this.triggerCallbacks.get(triggerId);
          if (callback) {
            await callback({
              type: 'composite',
              coin: trigger.coin,
              operator: trigger.operator,
              subResults: subResults.map((r, i) => ({
                indicator: trigger.subConditions[i].indicator,
                value: r.value, met: r.met,
              })),
              triggerId,
            });
          }
        } else if (compositeMet && wasMet) {
          await this.updateState('trigger_check', {
            triggerId, coin: trigger.coin, status: 'still_active',
            operator: trigger.operator, summary,
          }, `${trigger.coin} composite (${trigger.operator}) — still active`);
        } else {
          await this.updateState('trigger_check', {
            triggerId, coin: trigger.coin, status: 'not_met',
            operator: trigger.operator, summary,
          }, `${trigger.coin} composite (${trigger.operator}) — ${summary}`);
        }

        trigger.lastConditionMet = compositeMet;
      } catch (error) {
        console.error(`❌ Composite trigger ${triggerId} error:`, error.message);
      }
    }
  }

  /**
   * Check if event meets condition
   * @private
   */
  _checkEventCondition(event, condition) {
    if (condition.minSize !== undefined && condition.minSize !== null) {
      const minSize = toFiniteNumber(condition.minSize, 0);
      const eventSize = toFiniteNumber(event.sz ?? event.size, NaN);
      if (!Number.isFinite(eventSize) || eventSize < minSize) {
        return false;
      }
    }
    if (condition.coin && event.coin !== condition.coin) {
      return false;
    }
    return true;
  }
  
  // ==========================================================================
  // ABSTRACT METHODS (Must be implemented by subclasses)
  // ==========================================================================
  
  /**
   * Initialize the agent's strategy
   * 
   * AI-GENERATED CODE GOES HERE
   * 
   * This method should:
   * - Extract parameters from this.strategyConfig
   * - Initialize strategy-specific variables as this.varName
   * - Validate configuration
   * - Log initialization details
   * - Call this.updateState('init', { params }, 'Strategy initialized')
   * 
   * Available:
   * - this.strategyConfig (object with user-defined parameters)
   * - this.updateState(type, data, message)
   * - console.log() for logging
   * 
   * @returns {Promise<void>}
   */
  async onInitialize() {
    // ============================================================
    // AI GENERATED CODE START
    // ============================================================
    
    console.log('⚠️  No strategy initialization code provided');
    console.log('   Add your initialization logic here');
    
    // Example:
    // this.coin = this.strategyConfig.coin || 'BTC';
    // this.orderSize = this.strategyConfig.orderSize || 0.01;
    // await this.updateState('init', { coin: this.coin }, 'Initialized');
    
    // ============================================================
    // AI GENERATED CODE END
    // ============================================================
  }
  
  /**
   * Set up all triggers for this agent
   * 
   * AI-GENERATED CODE GOES HERE
   * 
   * This method should:
   * - Register price triggers using this.registerPriceTrigger(coin, condition, callback)
   * - Register technical triggers using this.registerTechnicalTrigger(coin, indicator, params, condition, callback)
   * - Register scheduled triggers using this.registerScheduledTrigger(intervalMs, callback)
   * - Register event triggers using this.registerEventTrigger(eventType, condition, callback)
   * 
   * Available methods:
   * - this.registerPriceTrigger(coin, { above|below|crosses: price }, async (data) => {...})
   * - this.registerTechnicalTrigger(coin, 'RSI|EMA|SMA|MACD|BollingerBands', { period, interval }, { above|below: value }, async (data) => {...})
   * - this.registerScheduledTrigger(milliseconds, async (data) => {...})
   * - this.registerEventTrigger('liquidation|largeTrade|userFill', { minSize, coin }, async (data) => {...})
   * 
   * Inside callbacks, call:
   * - await this.executeTrade(data) or your custom logic
   * 
   * @returns {Promise<void>}
   */
  async setupTriggers() {
    // ============================================================
    // AI GENERATED CODE START
    // ============================================================
    
    console.log('⚠️  No triggers registered');
    console.log('   Add your trigger registration code here');
    
    // Example:
    // this.registerPriceTrigger('BTC', { below: 85000 }, async (data) => {
    //   await this.executeTrade({ ...data, action: 'buy' });
    // });
    //
    // this.registerTechnicalTrigger('BTC', 'RSI', 
    //   { period: 14, interval: '1h' }, 
    //   { below: 30 }, 
    //   async (data) => {
    //     await this.executeTrade({ ...data, action: 'buy' });
    //   }
    // );
    
    // ============================================================
    // AI GENERATED CODE END
    // ============================================================
  }
  
  // ==========================================================================
  // POSITION TRACKING HELPERS
  // ==========================================================================
  
  /**
   * Get PnL summary statistics
   * @returns {Object} Summary statistics
   */
  getPnlSummary() {
    return this.positionTracker.getTotalStats();
  }
  
  /**
   * Get per-coin PnL breakdown
   * @returns {Object} Coin-specific statistics
   */
  getPnlByCoin() {
    return this.positionTracker.getStatsByCoin();
  }
  
  /**
   * Print PnL summary to console
   */
  printPnlSummary() {
    this.positionTracker.printSummary();
  }
  
  /**
   * Get all open positions from tracker
   * @returns {Array} Open positions
   */
  getTrackedOpenPositions() {
    return this.positionTracker.getAllOpenPositions();
  }
  
  /**
   * Get closed positions history
   * @param {string} coin - Optional coin filter
   * @param {number} limit - Optional limit
   * @returns {Array} Closed positions
   */
  getTrackedClosedPositions(coin = null, limit = null) {
    return this.positionTracker.getClosedPositions(coin, limit);
  }
  
  /**
   * Execute a trade based on trigger data
   * 
   * AI-GENERATED CODE GOES HERE
   * 
   * This method should:
   * - Extract data from triggerData parameter
   * - Compute order parameters (size, price, side)
   * - Check safety limits using: await this.checkSafetyLimits(coin, size)
   * - Place orders using: await this.orderExecutor.placeMarketOrder(coin, isBuy, size)
   * - Log trades using: await this.logTrade({ coin, side, size, price, order_type, trigger_reason })
   * - Update state using: await this.updateState(type, data, message)
   * 
   * Available in triggerData:
   * - triggerData.type ('price', 'technical', 'scheduled', 'event')
   * - triggerData.coin (string, coin symbol)
   * - triggerData.price (number, for price triggers)
   * - triggerData.value (number or object, for technical triggers)
   * - triggerData.action (custom field you can add)
   * 
   * Available methods:
   * - await this.orderExecutor.getPositions() - get all positions
   * - await this.orderExecutor.getAccountValue() - get account value
   * - await this.orderExecutor.placeMarketOrder(coin, isBuy, size, reduceOnly, slippage)
   * - await this.orderExecutor.placeLimitOrder(coin, isBuy, size, price, ...)
   * - await this.orderExecutor.closePosition(coin, size?, slippage?) - size=null for full close
   * - await this.checkSafetyLimits(coin, size) - returns { allowed: bool, reason: string }
   * - await this.logTrade({ coin, side, size, price, order_type, pnl, order_id, trigger_reason })
   * - await this.updateState(type, data, message)
   * 
   * Available imports (already imported):
   * - getAllMids, getCandleSnapshot, getTicker, getL2Book, etc. (from perpMarket.js)
   * - getOpenOrders, getUserFills, etc. (from perpUser.js)
   * 
   * @param {Object} triggerData - Data from the trigger that fired
   * @returns {Promise<void>}
   */
  async executeTrade(triggerData) {
    // ============================================================
    // AI GENERATED CODE START
    // ============================================================
    
    console.log('⚠️  No trade execution logic provided');
    console.log('   Trigger fired:', triggerData);
    console.log('   Add your trade execution logic here');
    
    // Example:
    // const { coin, price, action } = triggerData;
    // const isBuy = action === 'buy';
    // const size = 0.01;
    //
    // const safety = await this.checkSafetyLimits(coin, size);
    // if (!safety.allowed) {
    //   console.warn('Trade blocked:', safety.reason);
    //   return;
    // }
    //
    // const result = await this.orderExecutor.placeMarketOrder(coin, isBuy, size);
    // if (result.success) {
    //   await this.logTrade({
    //     coin, side: isBuy ? 'buy' : 'sell', size: result.filledSize,
    //     price: result.averagePrice, order_type: 'market',
    //     trigger_reason: `${triggerData.type} trigger`
    //   });
    // }
    
    // ============================================================
    // AI GENERATED CODE END
    // ============================================================
  }
}

export default BaseAgent;

// Export utility functions for agents to use
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
  getOpenOrders,
  getFrontendOpenOrders,
  getUserFills,
  getUserFillsByTime,
  getHistoricalOrders,
  getPortfolio,
  getSubAccounts,
  getUserFees
};
