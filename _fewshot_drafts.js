// ============================================================================
// EXAMPLE 1: RSI Mean Reversion — $50 sizing, 10x leverage, ROI-based SL/TP
// Strategy: "Trade $50 worth of ETH when RSI(14, 1h) drops below 30 (buy) or
// rises above 70 (sell). Use 10x leverage. Close opposite before opening new."
// ============================================================================

// --- onInitialize ---
{
  console.log('Initializing RSI Mean Reversion Strategy...');

  this.coin = 'ETH';
  this.rsiPeriod = 14;
  this.interval = '1h';
  this.oversold = 30;
  this.overbought = 70;
  this.tradeAmountUsd = 50;  // $50 notional per trade
  this.leverage = 10;

  // ROI-based SL/TP: 8% SL, 12% TP on return on investment
  this.slRoiPercent = 8;
  this.tpRoiPercent = 12;

  // Trade-idea state
  this.tradeState = { lastSignal: null, ideaActive: false, entryPrice: null };

  await this.orderExecutor.setLeverage(this.coin, this.leverage);

  // Pre-calculate fee estimate for logging
  const mids = await getAllMids();
  const ethPrice = parseFloat(mids[this.coin]);
  const estSize = this.tradeAmountUsd / ethPrice;
  const { fee: estFee } = this.orderExecutor.calculateTradeFee(estSize, ethPrice, 'market');

  console.log(`  Coin: ${this.coin}`);
  console.log(`  RSI(${this.rsiPeriod}, ${this.interval}): Buy < ${this.oversold}, Sell > ${this.overbought}`);
  console.log(`  Size: $${this.tradeAmountUsd} notional (~${estSize.toFixed(4)} ETH @ $${ethPrice.toFixed(2)})`);
  console.log(`  Leverage: ${this.leverage}x | Margin: ~$${(this.tradeAmountUsd / this.leverage).toFixed(2)}`);
  console.log(`  SL: ${this.slRoiPercent}% ROI (${(this.slRoiPercent / this.leverage).toFixed(2)}% price move)`);
  console.log(`  TP: ${this.tpRoiPercent}% ROI (${(this.tpRoiPercent / this.leverage).toFixed(2)}% price move)`);
  console.log(`  Est. fee per trade: ~$${estFee.toFixed(4)}`);

  await this.updateState('init', {
    coin: this.coin, rsiPeriod: this.rsiPeriod, leverage: this.leverage,
    tradeAmountUsd: this.tradeAmountUsd, slRoi: this.slRoiPercent, tpRoi: this.tpRoiPercent
  }, `Strategy initialized: RSI Mean Reversion on ${this.coin}. Buy when RSI < ${this.oversold}, sell when RSI > ${this.overbought}. $${this.tradeAmountUsd} per trade at ${this.leverage}x leverage. SL at ${this.slRoiPercent}% ROI, TP at ${this.tpRoiPercent}% ROI. Estimated fee: ~$${estFee.toFixed(4)} per trade.`);
}

// --- setupTriggers ---
{
  this.registerTechnicalTrigger(
    this.coin, 'RSI',
    { period: this.rsiPeriod, interval: this.interval },
    { below: this.oversold },
    async (triggerData) => {
      await this.executeTrade({ ...triggerData, action: 'buy' });
    }
  );

  this.registerTechnicalTrigger(
    this.coin, 'RSI',
    { period: this.rsiPeriod, interval: this.interval },
    { above: this.overbought },
    async (triggerData) => {
      await this.executeTrade({ ...triggerData, action: 'sell' });
    }
  );

  console.log(`Triggers registered: RSI < ${this.oversold} → buy, RSI > ${this.overbought} → sell`);
}

// --- executeTrade ---
{
  const { action, coin, value } = triggerData;
  const isBuy = action === 'buy';

  try {
    console.log(`\n--- Trigger: ${action.toUpperCase()} | ${coin} | RSI: ${value?.toFixed(2)} ---`);

    // --- Detect external close (SL/TP hit on exchange) ---
    if (this.tradeState.ideaActive) {
      const checkPos = await this.orderExecutor.getPositions(coin);
      if (!checkPos.length || checkPos[0].size === 0) {
        this.tradeState.ideaActive = false;
        this.tradeState.lastSignal = null;
        this.tradeState.entryPrice = null;
        console.log(`${coin}: Position was closed externally (SL/TP likely hit). Trade idea reset.`);
        await this.updateState('external_close', { coin },
          `${coin}: I detected that the previous position was closed (likely by the SL/TP orders on the exchange). Resetting and ready for the next signal.`);
      }
    }

    // --- Trade-idea gating ---
    if (this.tradeState.ideaActive && this.tradeState.lastSignal === action) {
      console.log(`${coin}: Skipping — already acted on this RSI ${action} excursion`);
      await this.updateState('skip', { coin, action, rsi: value?.toFixed(2) },
        `${coin}: RSI is still ${action === 'buy' ? 'oversold' : 'overbought'} (${value?.toFixed(2)}), but I already have a position from this excursion. Waiting for RSI to reset before re-entering.`);
      return;
    }

    // --- Exit: close opposite (strategy explicitly requires this) ---
    const positions = await this.orderExecutor.getPositions(coin);
    const pos = positions.length > 0 ? positions[0] : null;

    if (pos && pos.size !== 0) {
      const posIsLong = pos.size > 0;
      const isOpposite = (isBuy && !posIsLong) || (!isBuy && posIsLong);

      if (isOpposite) {
        console.log(`${coin}: Closing ${posIsLong ? 'LONG' : 'SHORT'} before opening ${action.toUpperCase()}`);
        const closeResult = await this.orderExecutor.closePosition(coin);
        if (!closeResult.success) {
          await this.updateState('close_failed', { coin, error: closeResult.error },
            `${coin}: Tried to close the ${posIsLong ? 'long' : 'short'} position before flipping, but it failed: ${closeResult.error}`);
          return;
        }

        const closePnl = (closeResult.averagePrice - pos.entryPrice) * pos.size;
        await this.logTrade({
          coin, side: posIsLong ? 'sell' : 'buy', size: Math.abs(pos.size),
          price: closeResult.averagePrice, order_type: 'close_position', is_exit: true,
          trigger_reason: `Closing ${posIsLong ? 'long' : 'short'} — RSI flipped to ${action} (${value?.toFixed(2)})`
        });
        await this.syncPositions();

        await this.updateState('position_closed', {
          coin, side: posIsLong ? 'long' : 'short', entryPrice: pos.entryPrice,
          exitPrice: closeResult.averagePrice, estimatedPnl: closePnl.toFixed(2)
        }, `${coin}: Closed ${posIsLong ? 'long' : 'short'} position. Entry: $${pos.entryPrice.toFixed(2)}, Exit: $${closeResult.averagePrice.toFixed(2)}, Est. PnL: $${closePnl.toFixed(2)}. Reason: RSI reversed to ${value?.toFixed(2)}.`);
      } else {
        await this.updateState('holding', { coin, size: pos.size, entryPrice: pos.entryPrice, rsi: value?.toFixed(2) },
          `${coin}: Already ${posIsLong ? 'long' : 'short'} (${Math.abs(pos.size).toFixed(4)} @ $${pos.entryPrice.toFixed(2)}). RSI=${value?.toFixed(2)} confirms direction — holding.`);
        return;
      }
    }

    // --- Calculate position size ---
    const mids = await getAllMids();
    const currentPrice = parseFloat(mids[coin]);
    const size = this.tradeAmountUsd / currentPrice;  // $50 notional
    const notional = size * currentPrice;

    // Validate minimum
    if (notional < 10) {
      await this.updateState('skip_min_size', { coin, notional: notional.toFixed(2) },
        `${coin}: Calculated position is only $${notional.toFixed(2)} notional, below the $10 minimum. Skipping.`);
      return;
    }

    // --- Safety check ---
    const safety = await this.checkSafetyLimits(coin, size);
    if (!safety.allowed) {
      await this.updateState('blocked', { coin, reason: safety.reason },
        `${coin}: Trade blocked by safety limits — ${safety.reason}. Will try again on next signal.`);
      return;
    }

    // --- Place order ---
    const result = await this.orderExecutor.placeMarketOrder(coin, isBuy, size);
    if (!result.success) {
      await this.updateState('order_failed', { coin, error: result.error },
        `${coin}: ${action.toUpperCase()} order for ${size.toFixed(4)} ${coin} failed — ${result.error}`);
      return;
    }

    const filled = result.filledSize || size;
    const fillPrice = result.averagePrice || currentPrice;
    const fillNotional = filled * fillPrice;

    // --- Calculate and place SL/TP ---
    const slPriceMove = this.slRoiPercent / 100 / this.leverage;
    const tpPriceMove = this.tpRoiPercent / 100 / this.leverage;
    const slPrice = isBuy ? fillPrice * (1 - slPriceMove) : fillPrice * (1 + slPriceMove);
    const tpPrice = isBuy ? fillPrice * (1 + tpPriceMove) : fillPrice * (1 - tpPriceMove);

    // SL/TP: isBuy=false for closing longs, isBuy=true for closing shorts
    await this.orderExecutor.placeStopLoss(coin, !isBuy, filled, slPrice, null, true);
    await this.orderExecutor.placeTakeProfit(coin, !isBuy, filled, tpPrice, null, true);

    // --- Log everything ---
    const { fee } = this.orderExecutor.calculateTradeFee(filled, fillPrice, 'market');

    await this.logTrade({
      coin, side: isBuy ? 'buy' : 'sell', size: filled, price: fillPrice,
      order_type: 'market', order_id: result.orderId,
      trigger_reason: `RSI ${action} signal (RSI=${value?.toFixed(2)})`, is_entry: true
    });
    await this.syncPositions();

    this.tradeState.lastSignal = action;
    this.tradeState.ideaActive = true;
    this.tradeState.entryPrice = fillPrice;

    await this.updateState('trade_opened', {
      coin, side: action, size: filled, price: fillPrice, notional: fillNotional.toFixed(2),
      rsi: value?.toFixed(2), slPrice: slPrice.toFixed(2), tpPrice: tpPrice.toFixed(2), fee: fee.toFixed(4)
    }, `${coin}: Opened ${action.toUpperCase()} — ${filled.toFixed(4)} ${coin} @ $${fillPrice.toFixed(2)} ($${fillNotional.toFixed(2)} notional, ${this.leverage}x leverage). RSI was ${value?.toFixed(2)}. SL set at $${slPrice.toFixed(2)} (${this.slRoiPercent}% ROI), TP at $${tpPrice.toFixed(2)} (${this.tpRoiPercent}% ROI). Fee: $${fee.toFixed(4)}.`);

  } catch (error) {
    console.error(`${coin || 'unknown'}: Error — ${error.message}`);
    await this.updateState('error', { coin, error: error.message },
      `${coin || 'Unknown'}: Something went wrong during trade execution — ${error.message}. Will retry on next trigger.`);
  }
}


// ============================================================================
// EXAMPLE 2: Multi-coin EMA crossover — scheduled trigger, $10 including leverage
// Strategy: "Trade BTC and SOL using 9/21 EMA crossover on 5m candles. $10 per
// trade including leverage. Use half of max leverage. TP at 1.5x the risk."
// ============================================================================

// --- onInitialize ---
{
  console.log('Initializing Multi-Coin EMA Crossover Strategy...');

  this.coins = ['BTC', 'SOL'];
  this.fastEma = 9;
  this.slowEma = 21;
  this.interval = '5m';
  this.checkIntervalMs = 5 * 60 * 1000;  // Check every 5 min
  this.lookbackMs = 25 * 5 * 60 * 1000;  // 25 candles of 5m
  this.minCandles = 22;  // Need at least slowEma + 1 candles
  this.tradeNotional = 10;  // $10 notional per trade (user said "including leverage")

  // SL/TP: TP = 1.5x risk (user specified), default SL = 8% ROI
  this.slRoiPercent = 8;
  this.tpRoiPercent = 12;  // 1.5 * 8 = 12% ROI

  // Set leverage to half of max per coin
  this.leverageMap = {};
  for (const coin of this.coins) {
    const maxLev = await this.orderExecutor.getMaxLeverage(coin);
    const targetLev = Math.floor(maxLev / 2);
    await this.orderExecutor.setLeverage(coin, targetLev);
    this.leverageMap[coin] = targetLev;
    console.log(`  ${coin}: leverage set to ${targetLev}x (max: ${maxLev}x)`);
  }

  // Trade-idea state per coin
  this.tradeState = {};
  for (const coin of this.coins) {
    this.tradeState[coin] = { trend: null, ideaActive: false, entryPrice: null };
  }

  console.log(`\n  EMA(${this.fastEma}/${this.slowEma}) crossover on ${this.interval} candles`);
  console.log(`  Trade size: $${this.tradeNotional} notional per trade`);
  console.log(`  Coins: ${this.coins.join(', ')}`);

  await this.updateState('init', {
    coins: this.coins, fastEma: this.fastEma, slowEma: this.slowEma,
    interval: this.interval, tradeNotional: this.tradeNotional, leverageMap: this.leverageMap
  }, `Strategy initialized: EMA(${this.fastEma}/${this.slowEma}) crossover on ${this.coins.join(', ')} using ${this.interval} candles. $${this.tradeNotional} notional per trade. Leverage: ${this.coins.map(c => `${c}=${this.leverageMap[c]}x`).join(', ')}. SL: ${this.slRoiPercent}% ROI, TP: ${this.tpRoiPercent}% ROI.`);
}

// --- setupTriggers ---
{
  this.registerScheduledTrigger(this.checkIntervalMs, async (triggerData) => {
    await this.executeTrade({ ...triggerData, action: 'analyze' });
  });

  console.log(`Scheduled trigger: analyze every ${this.checkIntervalMs / 1000}s`);

  await this.updateState('triggers_ready', { interval: this.checkIntervalMs },
    `Triggers set up: analyzing all coins every ${this.checkIntervalMs / 60000} minutes for EMA crossover signals.`);
}

// --- executeTrade ---
{
  const { action } = triggerData;
  if (action !== 'analyze') return;

  try {
    console.log('\n=== EMA Crossover Analysis Cycle ===');

    // --- PHASE 1: Check exits across ALL coins first ---
    for (const coin of this.coins) {
      const positions = await this.orderExecutor.getPositions(coin);
      const pos = positions.length > 0 ? positions[0] : null;

      // Detect external close
      if (this.tradeState[coin].ideaActive && (!pos || pos.size === 0)) {
        this.tradeState[coin] = { trend: null, ideaActive: false, entryPrice: null };
        console.log(`${coin}: Position closed externally — resetting state`);
        await this.updateState('external_close', { coin },
          `${coin}: Position was closed externally (SL/TP hit). Ready for next crossover signal.`);
      }
    }

    // --- PHASE 2: Calculate indicators and find signals for ALL coins ---
    const signals = [];
    const now = Date.now();

    for (const coin of this.coins) {
      try {
        const candles = await getCandleSnapshot(coin, this.interval, now - this.lookbackMs, now);
        if (candles.length < this.minCandles) {
          console.log(`${coin}: Only ${candles.length} candles (need ${this.minCandles}). Skipping.`);
          continue;
        }
        const closes = candles.map(c => c.close);

        // Calculate EMAs manually
        const calcEma = (data, period) => {
          const k = 2 / (period + 1);
          let ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
          for (let i = period; i < data.length; i++) {
            ema = data[i] * k + ema * (1 - k);
          }
          return ema;
        };

        const ema9 = calcEma(closes, this.fastEma);
        const ema21 = calcEma(closes, this.slowEma);
        const currentPrice = closes[closes.length - 1];

        // Determine signal
        const newTrend = ema9 > ema21 ? 'bullish' : 'bearish';
        const prevTrend = this.tradeState[coin].trend;

        console.log(`${coin}: $${currentPrice.toFixed(2)} | EMA${this.fastEma}=${ema9.toFixed(2)} | EMA${this.slowEma}=${ema21.toFixed(2)} | Trend: ${newTrend}`);

        // Only act on crossover (trend change)
        if (prevTrend && newTrend !== prevTrend) {
          signals.push({ coin, newTrend, prevTrend, ema9, ema21, currentPrice });
        } else if (!prevTrend) {
          // First run — just record trend, don't trade
          this.tradeState[coin].trend = newTrend;
          await this.updateState('trend_detected', { coin, trend: newTrend, ema9: ema9.toFixed(2), ema21: ema21.toFixed(2) },
            `${coin}: First analysis — detected ${newTrend} trend (EMA${this.fastEma}=${ema9.toFixed(2)} vs EMA${this.slowEma}=${ema21.toFixed(2)}). Watching for crossover.`);
        } else {
          console.log(`${coin}: No crossover — trend still ${newTrend}`);
        }
      } catch (err) {
        console.error(`${coin}: Analysis failed — ${err.message}`);
      }
    }

    if (signals.length === 0) {
      console.log('No crossover signals detected this cycle.');
      return;
    }

    // --- PHASE 3: Execute signals ---
    for (const sig of signals) {
      const { coin, newTrend, prevTrend, ema9, ema21, currentPrice } = sig;
      const isBuy = newTrend === 'bullish';
      const lev = this.leverageMap[coin];

      console.log(`\n${coin}: CROSSOVER detected — ${prevTrend} → ${newTrend}`);

      // Close existing position if opposite direction
      const positions = await this.orderExecutor.getPositions(coin);
      const pos = positions.length > 0 ? positions[0] : null;

      if (pos && pos.size !== 0) {
        const posIsLong = pos.size > 0;
        if ((isBuy && !posIsLong) || (!isBuy && posIsLong)) {
          const closeResult = await this.orderExecutor.closePosition(coin);
          if (closeResult.success) {
            const closePnl = (closeResult.averagePrice - pos.entryPrice) * pos.size;
            await this.logTrade({
              coin, side: posIsLong ? 'sell' : 'buy', size: Math.abs(pos.size),
              price: closeResult.averagePrice, order_type: 'close_position', is_exit: true,
              trigger_reason: `EMA crossover: ${prevTrend} → ${newTrend}`
            });
            await this.syncPositions();
            await this.updateState('crossover_exit', {
              coin, prevSide: posIsLong ? 'long' : 'short', exitPrice: closeResult.averagePrice, pnl: closePnl.toFixed(2)
            }, `${coin}: Closed ${posIsLong ? 'long' : 'short'} on crossover. Exit: $${closeResult.averagePrice.toFixed(2)}, Est. PnL: $${closePnl.toFixed(2)}.`);
          }
        }
      }

      // Calculate size: $10 including leverage means notional = $10
      const size = this.tradeNotional / currentPrice;
      const notional = size * currentPrice;

      if (notional < 10) {
        await this.updateState('skip_min_size', { coin, notional: notional.toFixed(2) },
          `${coin}: Position too small ($${notional.toFixed(2)} notional). Minimum is $10. Skipping.`);
        continue;
      }

      const safety = await this.checkSafetyLimits(coin, size);
      if (!safety.allowed) {
        await this.updateState('blocked', { coin, reason: safety.reason },
          `${coin}: Safety check blocked this trade — ${safety.reason}.`);
        continue;
      }

      const result = await this.orderExecutor.placeMarketOrder(coin, isBuy, size);
      if (!result.success) {
        await this.updateState('order_failed', { coin, error: result.error },
          `${coin}: Failed to open ${isBuy ? 'long' : 'short'} — ${result.error}`);
        continue;
      }

      const filled = result.filledSize || size;
      const fillPrice = result.averagePrice || currentPrice;

      // Place ROI-based SL/TP
      const slMove = this.slRoiPercent / 100 / lev;
      const tpMove = this.tpRoiPercent / 100 / lev;
      const slPrice = isBuy ? fillPrice * (1 - slMove) : fillPrice * (1 + slMove);
      const tpPrice = isBuy ? fillPrice * (1 + tpMove) : fillPrice * (1 - tpMove);

      await this.orderExecutor.placeStopLoss(coin, !isBuy, filled, slPrice, null, true);
      await this.orderExecutor.placeTakeProfit(coin, !isBuy, filled, tpPrice, null, true);

      await this.logTrade({
        coin, side: isBuy ? 'buy' : 'sell', size: filled, price: fillPrice,
        order_type: 'market', order_id: result.orderId, is_entry: true,
        trigger_reason: `EMA${this.fastEma}/${this.slowEma} crossover: ${prevTrend} → ${newTrend}`
      });
      await this.syncPositions();

      this.tradeState[coin] = { trend: newTrend, ideaActive: true, entryPrice: fillPrice };

      const { fee } = this.orderExecutor.calculateTradeFee(filled, fillPrice, 'market');
      await this.updateState('trade_opened', {
        coin, side: isBuy ? 'long' : 'short', size: filled, price: fillPrice,
        ema9: ema9.toFixed(2), ema21: ema21.toFixed(2), slPrice: slPrice.toFixed(2), tpPrice: tpPrice.toFixed(2)
      }, `${coin}: Opened ${isBuy ? 'LONG' : 'SHORT'} on EMA crossover — ${filled.toFixed(6)} ${coin} @ $${fillPrice.toFixed(2)} ($${(filled * fillPrice).toFixed(2)} notional, ${lev}x lev). EMA${this.fastEma}=${ema9.toFixed(2)} crossed above EMA${this.slowEma}=${ema21.toFixed(2)}. SL: $${slPrice.toFixed(2)}, TP: $${tpPrice.toFixed(2)}. Fee: ~$${fee.toFixed(4)}.`);
    }

    // Update trend state for coins without signals
    for (const coin of this.coins) {
      if (!signals.find(s => s.coin === coin) && this.tradeState[coin].trend) {
        // trend unchanged, already logged
      }
    }

  } catch (error) {
    console.error(`Analysis error: ${error.message}`);
    await this.updateState('error', { error: error.message },
      `Error during analysis cycle: ${error.message}. Will retry next cycle.`);
  }
}


// ============================================================================
// EXAMPLE 3: Liquidation-driven scalping — event triggers, multi-position, trailing stops
// Strategy: "When a large BTC liquidation (>$500k) occurs, open a $20 position in the
// opposite direction with max leverage and a 3% trailing stop. Allow up to 3 concurrent
// positions."
// ============================================================================

// --- onInitialize ---
{
  console.log('Initializing Liquidation Scalping Strategy...');

  this.coin = 'BTC';
  this.minLiqNotional = 500000;  // $500k minimum liquidation size
  this.positionNotional = 20;  // $20 per trade
  this.maxConcurrentPositions = 3;
  this.trailPercent = 3;  // 3% trailing stop

  // Get and set max leverage
  const maxLev = await this.orderExecutor.getMaxLeverage(this.coin);
  this.leverage = maxLev;
  await this.orderExecutor.setLeverage(this.coin, this.leverage);

  // Track open positions from this strategy
  this.openTrades = [];  // [{ orderId, side, size, entryPrice, time }]

  const mids = await getAllMids();
  const btcPrice = parseFloat(mids[this.coin]);
  const estSize = this.positionNotional / btcPrice;
  const estMargin = this.positionNotional / this.leverage;
  const { fee: estFee } = this.orderExecutor.calculateTradeFee(estSize, btcPrice, 'market');

  console.log(`  Coin: ${this.coin}`);
  console.log(`  Min liquidation: $${(this.minLiqNotional / 1000).toFixed(0)}k notional`);
  console.log(`  Position: $${this.positionNotional} notional (margin: ~$${estMargin.toFixed(2)} at ${this.leverage}x)`);
  console.log(`  Max concurrent: ${this.maxConcurrentPositions}`);
  console.log(`  Trailing stop: ${this.trailPercent}%`);
  console.log(`  Est. fee: ~$${estFee.toFixed(4)} per trade`);

  await this.updateState('init', {
    coin: this.coin, leverage: this.leverage, positionNotional: this.positionNotional,
    minLiqNotional: this.minLiqNotional, maxConcurrent: this.maxConcurrentPositions, trailPercent: this.trailPercent
  }, `Strategy initialized: Liquidation Scalping on ${this.coin}. Watching for liquidations > $${(this.minLiqNotional / 1000).toFixed(0)}k. Will open $${this.positionNotional} positions in the opposite direction at ${this.leverage}x leverage with ${this.trailPercent}% trailing stop. Up to ${this.maxConcurrentPositions} concurrent positions allowed. Est. margin per trade: ~$${estMargin.toFixed(2)}, est. fee: ~$${estFee.toFixed(4)}.`);
}

// --- setupTriggers ---
{
  // Event trigger for large liquidations
  this.registerEventTrigger('liquidation', { minSize: 1.0 }, async (triggerData) => {
    await this.executeTrade({ ...triggerData, action: 'liq_event' });
  });

  // Scheduled cleanup: check for stale trades every 2 minutes
  this.registerScheduledTrigger(2 * 60 * 1000, async (triggerData) => {
    await this.executeTrade({ ...triggerData, action: 'cleanup' });
  });

  console.log(`Triggers: liquidation events (min 1.0 size), cleanup every 2min`);

  await this.updateState('triggers_ready', {},
    `Listening for ${this.coin} liquidation events and running position cleanup every 2 minutes.`);
}

// --- executeTrade ---
{
  const { action, data } = triggerData;

  try {
    // --- CLEANUP: Remove stale entries from tracking ---
    if (action === 'cleanup') {
      const positions = await this.orderExecutor.getPositions(this.coin);
      const currentSize = positions.length > 0 ? Math.abs(positions[0].size) : 0;

      // Remove tracked trades whose positions no longer exist
      const before = this.openTrades.length;
      if (currentSize === 0 && this.openTrades.length > 0) {
        this.openTrades = [];
        console.log(`Cleanup: All positions closed — cleared ${before} tracked trades`);
        await this.updateState('cleanup', { clearedTrades: before },
          `Cleanup: All ${this.coin} positions have been closed (trailing stops likely hit). Cleared tracking for ${before} trade(s). Ready for new liquidation events.`);
      }
      return;
    }

    // --- LIQUIDATION EVENT ---
    if (action !== 'liq_event' || !data) return;

    // Check if this is our coin and meets notional threshold
    const liqCoin = data.coin;
    if (liqCoin !== this.coin) return;

    const liqSize = parseFloat(data.sz || '0');
    const liqPrice = parseFloat(data.px || '0');
    const liqNotional = liqSize * liqPrice;

    if (liqNotional < this.minLiqNotional) return;  // Below threshold — ignore silently

    // Determine direction: side "B" = buy side (long) was liquidated, "A" = sell side (short) was liquidated
    const liqWasLong = data.side === 'B';
    const isBuy = liqWasLong;  // Buy when longs get liquidated (price dropped), short when shorts get liquidated
    const tradeDir = isBuy ? 'LONG' : 'SHORT';

    console.log(`\nLiquidation detected: ${liqWasLong ? 'LONG' : 'SHORT'} liq of ${liqSize.toFixed(4)} ${this.coin} ($${(liqNotional / 1000).toFixed(0)}k) @ $${liqPrice.toFixed(2)}`);

    // --- Check concurrent position limit ---
    if (this.openTrades.length >= this.maxConcurrentPositions) {
      console.log(`Max concurrent positions reached (${this.openTrades.length}/${this.maxConcurrentPositions}). Skipping.`);
      await this.updateState('skip_max_positions', {
        liqNotional: (liqNotional / 1000).toFixed(0) + 'k', currentPositions: this.openTrades.length
      }, `${this.coin}: Spotted a $${(liqNotional / 1000).toFixed(0)}k ${liqWasLong ? 'long' : 'short'} liquidation, but already at max positions (${this.openTrades.length}/${this.maxConcurrentPositions}). Waiting for an existing trade to close.`);
      return;
    }

    // --- Calculate size ---
    const mids = await getAllMids();
    const currentPrice = parseFloat(mids[this.coin]);
    const size = this.positionNotional / currentPrice;

    if (size * currentPrice < 10) {
      await this.updateState('skip_min_size', { notional: (size * currentPrice).toFixed(2) },
        `${this.coin}: Position size $${(size * currentPrice).toFixed(2)} below $10 minimum. Skipping.`);
      return;
    }

    const safety = await this.checkSafetyLimits(this.coin, size);
    if (!safety.allowed) {
      await this.updateState('blocked', { reason: safety.reason },
        `${this.coin}: Trade blocked — ${safety.reason}.`);
      return;
    }

    // --- Place order ---
    const result = await this.orderExecutor.placeMarketOrder(this.coin, isBuy, size);
    if (!result.success) {
      await this.updateState('order_failed', { error: result.error },
        `${this.coin}: Failed to open ${tradeDir} after liquidation event — ${result.error}`);
      return;
    }

    const filled = result.filledSize || size;
    const fillPrice = result.averagePrice || currentPrice;

    // Place trailing stop — isBuy=false for longs (sell to close), isBuy=true for shorts
    await this.orderExecutor.placeTrailingStop(this.coin, !isBuy, filled, this.trailPercent, true);

    // Track position
    this.openTrades.push({
      orderId: result.orderId, side: isBuy ? 'long' : 'short',
      size: filled, entryPrice: fillPrice, time: Date.now()
    });

    const { fee } = this.orderExecutor.calculateTradeFee(filled, fillPrice, 'market');

    await this.logTrade({
      coin: this.coin, side: isBuy ? 'buy' : 'sell', size: filled, price: fillPrice,
      order_type: 'market', order_id: result.orderId, is_entry: true,
      trigger_reason: `$${(liqNotional / 1000).toFixed(0)}k ${liqWasLong ? 'long' : 'short'} liquidation @ $${liqPrice.toFixed(2)}`
    });
    await this.syncPositions();

    await this.updateState('trade_opened', {
      side: tradeDir, size: filled, price: fillPrice, trailPercent: this.trailPercent,
      liqNotional: (liqNotional / 1000).toFixed(0) + 'k', openPositions: this.openTrades.length
    }, `${this.coin}: Opened ${tradeDir} — ${filled.toFixed(6)} BTC @ $${fillPrice.toFixed(2)} ($${(filled * fillPrice).toFixed(2)} notional, ${this.leverage}x lev). Triggered by $${(liqNotional / 1000).toFixed(0)}k ${liqWasLong ? 'long' : 'short'} liquidation. Trailing stop: ${this.trailPercent}%. Fee: $${fee.toFixed(4)}. Active positions: ${this.openTrades.length}/${this.maxConcurrentPositions}.`);

  } catch (error) {
    console.error(`${this.coin}: Error — ${error.message}`);
    await this.updateState('error', { error: error.message },
      `${this.coin}: Error processing event — ${error.message}. Will continue listening.`);
  }
}
