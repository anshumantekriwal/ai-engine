"""
Prompts for the backtest-engine v2 SpecAgent strategy spec transpiler.

The output format is the Hyperliquid SpecAgent format (triggers + workflows + expressions),
designed for the candle-based backtesting engine.
"""

BACKTEST_V2_SYSTEM_PROMPT = """
You are an expert quant strategy transpiler for Hyperliquid perpetual futures backtesting.
Your job is to convert natural-language strategy descriptions into valid SpecAgent Strategy Spec JSON
that can be executed by the candle-based backtesting engine.

Rules:
- Return valid JSON only. No markdown fences, no explanation, no commentary.
- Use only supported trigger/action/expression primitives listed below.
- Keep workflows deterministic and explicit.
- Prioritize safety checks before opening risk.
- Every spec must be self-contained — no external dependencies.
- The output is used for BACKTESTING, not live trading. Prefer scheduled triggers
  that check indicators via market methods when fine-grained control is needed.
"""

BACKTEST_V2_GENERATION_PROMPT = """
Convert this trading strategy into a valid SpecAgent Strategy Spec JSON for backtesting:

{strategy_description}

## Strategy Spec Schema

Required top-level fields:
- version: "1.0"
- strategy_id: short kebab-case id
- name: human-readable
- description: concise summary
- initial_state: mutable strategy state (e.g., in_position, counts)
- variables: configurable parameters (e.g., size, thresholds)
- risk: object with safety settings
- triggers: array of trigger definitions
- workflows: object keyed by workflow id

## Trigger Types

### price
{{ "id": "...", "type": "price", "coin": "BTC", "condition": {{ "above": 100000 }}, "onTrigger": "workflow_id" }}

### technical
Indicators: RSI, EMA, SMA, WMA, MACD, BollingerBands, EMA_CROSSOVER, SMA_CROSSOVER, ATR, Stochastic, StochasticRSI, WilliamsR, ADX, CCI, ROC, OBV, TRIX, MFI, VWAP, PSAR, KeltnerChannels

Condition types:
- "above": N — fires when indicator >= N
- "below": N — fires when indicator <= N
- "crosses": N — fires when indicator crosses N in either direction (requires 2 bars)
- "crosses_above": N — fires when indicator crosses above N (prev <= N and now > N)
- "crosses_below": N — fires when indicator crosses below N (prev >= N and now < N)
- "crossover": true — fires when fast line crosses above slow line (for dual-line indicators: EMA_CROSSOVER, SMA_CROSSOVER, MACD, Stochastic, StochasticRSI, ADX)
- "crossunder": true — fires when fast line crosses below slow line
- "checkField": "fieldName" — evaluate condition against a specific sub-field (e.g., "histogram" for MACD, "k" for Stochastic, "pdi" for ADX)

Dual-line indicators automatically resolve:
- EMA_CROSSOVER / SMA_CROSSOVER: fast vs slow
- MACD: macd vs signal
- Stochastic / StochasticRSI: k vs d
- ADX: pdi vs mdi

#### Trigger data injected into {{ "ref": "trigger.*" }}:
- All: type, indicator, value, coin
- EMA_CROSSOVER/SMA_CROSSOVER: fast, slow
- MACD: histogram, signal, macd
- BollingerBands/KeltnerChannels: upper, lower, middle
- Stochastic/StochasticRSI: k, d
- ADX: adx, pdi, mdi
- ATR: atr
- PSAR: psar
- Crossover/crossunder: fastValue, slowValue, prevFast, prevSlow

{{ "id": "...", "type": "technical", "coin": "BTC", "indicator": "RSI", "params": {{ "period": 14 }}, "condition": {{ "below": 30 }}, "onTrigger": "workflow_id" }}
{{ "id": "...", "type": "technical", "coin": "BTC", "indicator": "EMA_CROSSOVER", "params": {{ "fastPeriod": 9, "slowPeriod": 21 }}, "condition": {{ "crossover": true }}, "onTrigger": "buy_wf" }}
{{ "id": "...", "type": "technical", "coin": "ETH", "indicator": "MACD", "params": {{ "fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9 }}, "condition": {{ "crossover": true }}, "onTrigger": "macd_buy" }}
{{ "id": "...", "type": "technical", "coin": "BTC", "indicator": "Stochastic", "params": {{ "period": 14, "signalPeriod": 3 }}, "condition": {{ "crossover": true }}, "onTrigger": "stoch_buy" }}
{{ "id": "...", "type": "technical", "coin": "BTC", "indicator": "ADX", "params": {{ "period": 14 }}, "condition": {{ "above": 25 }}, "checkField": "adx", "onTrigger": "trend_wf" }}

### scheduled
{{ "id": "...", "type": "scheduled", "intervalMs": 3600000, "immediate": false, "onTrigger": "workflow_id" }}

### event (limited in backtest — only userFill is simulated)
{{ "id": "...", "type": "event", "eventType": "userFill", "onTrigger": "workflow_id" }}

Optional trigger fields: cooldownMs, maxExecutions, enabled

## Workflow Action Types

### set — Set a value in state/vars/local
{{ "action": "set", "path": "state.count", "value": {{ "op": "add", "args": [{{ "ref": "state.count" }}, 1] }} }}

### if — Conditional branching
{{ "action": "if", "condition": {{ "op": "lt", "args": [{{ "ref": "state.rsi" }}, 30] }}, "then": [...], "else": [...] }}

### for_each — Iterate over array
{{ "action": "for_each", "list": ["BTC", "ETH"], "item": "coin", "steps": [...] }}

### call — Call a binding method
Targets: market, user, order, agent, state
{{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, 0.1, false] }}
{{ "action": "call", "target": "market", "method": "getAllMids", "assign": "local.mids" }}

### log — Log a message
{{ "action": "log", "message": "Trade executed", "level": "info" }}

### return — Stop workflow execution
{{ "action": "return", "value": null }}

### assert — Fail if condition is false
{{ "action": "assert", "condition": {{ "op": "gt", "args": [{{ "ref": "state.balance" }}, 0] }}, "message": "Insufficient balance" }}

## Expression Format

- Literal: 42, "hello", true, null
- Reference: {{ "ref": "state.count" }}
- Operation: {{ "op": "add", "args": [1, 2] }}
- Nested: {{ "op": "gt", "args": [{{ "ref": "state.rsi" }}, 30] }}

Available operators: eq, neq, gt, gte, lt, lte, and, or, not, add, sub, mul, div, mod, abs, min, max, round, clamp, floor, ceil, pow, sqrt, log, coalesce, if_else, contains, starts_with, ends_with, in, length, sum, avg, mean, stddev, zscore, percent_change, sort_desc, sort_asc, slice, last, first, index, get, keys, values, map, filter_gt, filter_lt, range, concat, to_string, to_number, rolling_mean, rolling_std, linspace, dot, sort_by_key, elementwise_div, normalize, count_liquidations, orderbook_imbalance, trade_stats, kelly_fraction, now, crosses_above, crosses_below

## Available Order Methods

- placeMarketOrder(coin, isBuy, size, reduceOnly, slippage?)
- placeLimitOrder(coin, isBuy, size, price, reduceOnly?)
- placeStopLoss(coin, isBuy, size, triggerPrice, limitPrice?, reduceOnly?)
- placeTakeProfit(coin, isBuy, size, triggerPrice, limitPrice?, reduceOnly?)
- placeTrailingStop(coin, isBuy, size, trailPercent, reduceOnly?)
- closePosition(coin, size?) — size=0 to close entire position
- cancelOrder(coin, orderId)
- cancelAgentOrders(coin)
- setLeverage(coin, leverage)
- getPositions(coin?)
- getAccountValue()
- getAvailableBalance()
- getMaxTradeSizes(coin)

## Available Market Methods

- getAllMids() — returns {{ "BTC": 50000, "ETH": 3000, ... }}
- getCandleSnapshot(coin, interval, startTime, endTime)
- getTicker(coin) — returns {{ coin, open, high, low, close, volume, timestamp }}
- getL2Book(coin) — synthetic in backtest
- getFundingHistory(coin, startTime, endTime)
- getRecentTrades(coin) — synthetic in backtest
- getPredictedFundings() — returns {{ "BTC": 0.0001, "ETH": -0.0002, ... }}
- getIndicator(coin, indicator, params) — compute any indicator on-demand. Returns full indicator result with all sub-fields (value, upper, lower, fast, slow, k, d, etc.)
- getClosePrices(coin, lookback) — returns array of close prices
- getVolumes(coin, lookback) — returns array of volumes
- getOHLCV(coin) — returns {{ open, high, low, close, volume, body, isGreen, range, timestamp }}
- get24hChange(coin) — returns 24h percentage change
- getPriceRatio(coinA, coinB) — returns price ratio coinA/coinB
- getPriceRatioSeries(coinA, coinB, lookback) — returns array of price ratios
- getCoins() — returns all coins in universe
- getLatestFunding(coin) — returns latest funding rate for a coin

## Risk Object

{{ "maxPositionSize": null, "maxLeverage": null, "dailyLossLimit": null, "minNotional": 10, "maxConcurrentPositions": null, "requireSafetyCheck": true, "allowUnsafeOrderMethods": false }}

## Few-Shot Examples

### Example 1: RSI Bounce
Strategy: "Buy BTC when RSI drops below 30, sell when RSI rises above 70"
{{
  "version": "1.0",
  "strategy_id": "rsi-bounce",
  "name": "RSI Bounce",
  "description": "Buy when RSI < 30, sell when RSI > 70",
  "initial_state": {{ "in_position": false }},
  "variables": {{ "size": 0.01 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "rsi-buy", "type": "technical", "coin": "BTC", "indicator": "RSI", "params": {{ "period": 14 }}, "condition": {{ "below": 30 }}, "onTrigger": "buy" }},
    {{ "id": "rsi-sell", "type": "technical", "coin": "BTC", "indicator": "RSI", "params": {{ "period": 14 }}, "condition": {{ "above": 70 }}, "onTrigger": "sell" }}
  ],
  "workflows": {{
    "buy": {{
      "steps": [
        {{ "action": "if", "condition": {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.in_position", "value": true }}
        ]}}
      ]
    }},
    "sell": {{
      "steps": [
        {{ "action": "if", "condition": {{ "ref": "state.in_position" }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }}
        ]}}
      ]
    }}
  }}
}}

### Example 2: DCA
Strategy: "Buy 0.001 BTC every 4 hours"
{{
  "version": "1.0",
  "strategy_id": "dca-btc",
  "name": "BTC DCA",
  "description": "Dollar cost average into BTC every 4 hours",
  "initial_state": {{ "buy_count": 0 }},
  "variables": {{ "size": 0.001 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "buy-timer", "type": "scheduled", "intervalMs": 14400000, "onTrigger": "buy" }}
  ],
  "workflows": {{
    "buy": {{
      "steps": [
        {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
        {{ "action": "set", "path": "state.buy_count", "value": {{ "op": "add", "args": [{{ "ref": "state.buy_count" }}, 1] }} }},
        {{ "action": "log", "message": {{ "op": "add", "args": ["DCA buy #", {{ "ref": "state.buy_count" }}] }} }}
      ]
    }}
  }}
}}

### Example 3: EMA Crossover (9/21) with SL/TP
Strategy: "Go long when EMA(9) crosses above EMA(21) on ETH, go short when it crosses below. Use 2% stop loss and 4% take profit."
{{
  "version": "1.0",
  "strategy_id": "ema-cross-eth",
  "name": "ETH EMA 9/21 Crossover",
  "description": "Long on EMA 9/21 golden cross, short on death cross, with SL/TP",
  "initial_state": {{ "position_side": "none" }},
  "variables": {{ "size": 0.1, "sl_pct": 0.02, "tp_pct": 0.04 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "ema-golden-cross", "type": "technical", "coin": "ETH", "indicator": "EMA_CROSSOVER", "params": {{ "fastPeriod": 9, "slowPeriod": 21 }}, "condition": {{ "crossover": true }}, "onTrigger": "enter_long" }},
    {{ "id": "ema-death-cross", "type": "technical", "coin": "ETH", "indicator": "EMA_CROSSOVER", "params": {{ "fastPeriod": 9, "slowPeriod": 21 }}, "condition": {{ "crossunder": true }}, "onTrigger": "enter_short" }}
  ],
  "workflows": {{
    "enter_long": {{
      "steps": [
        {{ "action": "if", "condition": {{ "op": "eq", "args": [{{ "ref": "state.position_side" }}, "short"] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["ETH", 0] }},
          {{ "action": "call", "target": "order", "method": "cancelAllOrders", "args": ["ETH"], "allowUnsafe": true }},
          {{ "action": "log", "message": "Closed short before flipping long" }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "neq", "args": [{{ "ref": "state.position_side" }}, "long"] }}, "then": [
          {{ "action": "call", "target": "market", "method": "getAllMids", "assign": "local.mids" }},
          {{ "action": "set", "path": "local.price", "value": {{ "ref": "local.mids.ETH" }} }},
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["ETH", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.position_side", "value": "long" }},
          {{ "action": "call", "target": "order", "method": "placeStopLoss", "args": [
            "ETH", false, {{ "ref": "vars.size" }},
            {{ "op": "mul", "args": [{{ "ref": "local.price" }}, {{ "op": "sub", "args": [1, {{ "ref": "vars.sl_pct" }}] }}] }}
          ] }},
          {{ "action": "call", "target": "order", "method": "placeTakeProfit", "args": [
            "ETH", false, {{ "ref": "vars.size" }},
            {{ "op": "mul", "args": [{{ "ref": "local.price" }}, {{ "op": "add", "args": [1, {{ "ref": "vars.tp_pct" }}] }}] }}
          ] }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["EMA golden cross — entered long at ", {{ "ref": "local.price" }}] }} }}
        ] }}
      ]
    }},
    "enter_short": {{
      "steps": [
        {{ "action": "if", "condition": {{ "op": "eq", "args": [{{ "ref": "state.position_side" }}, "long"] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["ETH", 0] }},
          {{ "action": "call", "target": "order", "method": "cancelAllOrders", "args": ["ETH"], "allowUnsafe": true }},
          {{ "action": "log", "message": "Closed long before flipping short" }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "neq", "args": [{{ "ref": "state.position_side" }}, "short"] }}, "then": [
          {{ "action": "call", "target": "market", "method": "getAllMids", "assign": "local.mids" }},
          {{ "action": "set", "path": "local.price", "value": {{ "ref": "local.mids.ETH" }} }},
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["ETH", false, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.position_side", "value": "short" }},
          {{ "action": "call", "target": "order", "method": "placeStopLoss", "args": [
            "ETH", true, {{ "ref": "vars.size" }},
            {{ "op": "mul", "args": [{{ "ref": "local.price" }}, {{ "op": "add", "args": [1, {{ "ref": "vars.sl_pct" }}] }}] }}
          ] }},
          {{ "action": "call", "target": "order", "method": "placeTakeProfit", "args": [
            "ETH", true, {{ "ref": "vars.size" }},
            {{ "op": "mul", "args": [{{ "ref": "local.price" }}, {{ "op": "sub", "args": [1, {{ "ref": "vars.tp_pct" }}] }}] }}
          ] }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["EMA death cross — entered short at ", {{ "ref": "local.price" }}] }} }}
        ] }}
      ]
    }}
  }}
}}

### Example 4: Bollinger Band Breakout
Strategy: "Buy when price drops below lower Bollinger Band, sell above upper band"
{{
  "version": "1.0",
  "strategy_id": "bb-breakout",
  "name": "Bollinger Band Breakout",
  "description": "Buy at lower band, sell at upper band",
  "initial_state": {{ "in_position": false }},
  "variables": {{ "size": 0.05, "bb_period": 20, "bb_stddev": 2 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "bb-check", "type": "technical", "coin": "BTC", "indicator": "BollingerBands", "params": {{ "period": 20, "stdDev": 2 }}, "condition": {{ "below": 0 }}, "onTrigger": "check_bands" }}
  ],
  "workflows": {{
    "check_bands": {{
      "steps": [
        {{ "action": "call", "target": "market", "method": "getAllMids", "assign": "local.mids" }},
        {{ "action": "set", "path": "local.price", "value": {{ "ref": "local.mids.BTC" }} }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
          {{ "op": "lte", "args": [{{ "ref": "local.price" }}, {{ "ref": "trigger.lower" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.in_position", "value": true }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "ref": "state.in_position" }},
          {{ "op": "gte", "args": [{{ "ref": "local.price" }}, {{ "ref": "trigger.upper" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }}
        ] }}
      ]
    }}
  }}
}}

### Example 5: MACD Crossover
Strategy: "Buy BTC when MACD line crosses above signal line, sell when it crosses below"
{{
  "version": "1.0",
  "strategy_id": "macd-cross-btc",
  "name": "BTC MACD Crossover",
  "description": "Long on MACD crossover, exit on crossunder",
  "initial_state": {{ "in_position": false }},
  "variables": {{ "size": 0.01 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "macd-buy", "type": "technical", "coin": "BTC", "indicator": "MACD", "params": {{ "fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9 }}, "condition": {{ "crossover": true }}, "onTrigger": "buy" }},
    {{ "id": "macd-sell", "type": "technical", "coin": "BTC", "indicator": "MACD", "params": {{ "fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9 }}, "condition": {{ "crossunder": true }}, "onTrigger": "sell" }}
  ],
  "workflows": {{
    "buy": {{
      "steps": [
        {{ "action": "if", "condition": {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.in_position", "value": true }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["MACD bullish crossover. MACD=", {{ "ref": "trigger.macd" }}] }} }}
        ] }}
      ]
    }},
    "sell": {{
      "steps": [
        {{ "action": "if", "condition": {{ "ref": "state.in_position" }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }},
          {{ "action": "log", "message": "MACD bearish crossunder — closing position" }}
        ] }}
      ]
    }}
  }}
}}

### Example 6: Stochastic + ADX Trend Filter
Strategy: "Buy when Stochastic K crosses above D in oversold territory (K < 20) while ADX > 25 confirms trend strength"
{{
  "version": "1.0",
  "strategy_id": "stoch-adx-btc",
  "name": "BTC Stochastic Oversold + ADX Filter",
  "description": "Enter long on stochastic crossover in oversold zone with ADX trend confirmation",
  "initial_state": {{ "in_position": false, "adx_strong": false }},
  "variables": {{ "size": 0.01, "adx_threshold": 25, "stoch_oversold": 20, "stoch_overbought": 80 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "adx-strong", "type": "technical", "coin": "BTC", "indicator": "ADX", "params": {{ "period": 14 }}, "condition": {{ "above": 25 }}, "onTrigger": "update_adx" }},
    {{ "id": "adx-weak", "type": "technical", "coin": "BTC", "indicator": "ADX", "params": {{ "period": 14 }}, "condition": {{ "below": 25 }}, "onTrigger": "update_adx_weak" }},
    {{ "id": "stoch-buy", "type": "technical", "coin": "BTC", "indicator": "Stochastic", "params": {{ "period": 14, "signalPeriod": 3 }}, "condition": {{ "crossover": true }}, "onTrigger": "check_buy" }},
    {{ "id": "stoch-sell", "type": "technical", "coin": "BTC", "indicator": "Stochastic", "params": {{ "period": 14, "signalPeriod": 3 }}, "condition": {{ "crosses_above": 80 }}, "onTrigger": "exit_position", "checkField": "k" }}
  ],
  "workflows": {{
    "update_adx": {{
      "steps": [
        {{ "action": "set", "path": "state.adx_strong", "value": true }},
        {{ "action": "log", "message": {{ "op": "add", "args": ["ADX strong: ", {{ "ref": "trigger.adx" }}] }}, "level": "debug" }}
      ]
    }},
    "update_adx_weak": {{
      "steps": [
        {{ "action": "set", "path": "state.adx_strong", "value": false }}
      ]
    }},
    "check_buy": {{
      "steps": [
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
          {{ "ref": "state.adx_strong" }},
          {{ "op": "lt", "args": [{{ "ref": "trigger.k" }}, {{ "ref": "vars.stoch_oversold" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.in_position", "value": true }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["Stochastic oversold crossover with strong ADX. K=", {{ "ref": "trigger.k" }}] }} }}
        ] }}
      ]
    }},
    "exit_position": {{
      "steps": [
        {{ "action": "if", "condition": {{ "ref": "state.in_position" }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }},
          {{ "action": "log", "message": "Stochastic overbought — exiting position" }}
        ] }}
      ]
    }}
  }}
}}

### Example 7: Bollinger Band Mean Reversion (Scheduled + getIndicator)
Strategy: "Buy BTC when price drops below lower BB, sell when it returns to middle band"
{{
  "version": "1.0",
  "strategy_id": "bb-mean-reversion",
  "name": "BB Mean Reversion",
  "description": "Buy when price < lower BB via getIndicator, sell when price >= middle BB",
  "initial_state": {{ "in_position": false }},
  "variables": {{ "size": 0.01, "bb_period": 20, "bb_stddev": 2 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "bb-check", "type": "scheduled", "intervalMs": 60000, "immediate": true, "onTrigger": "check_bb" }}
  ],
  "workflows": {{
    "check_bb": {{
      "steps": [
        {{ "action": "call", "target": "market", "method": "getIndicator", "args": ["BTC", "BollingerBands", {{ "period": {{ "ref": "vars.bb_period" }}, "stdDev": {{ "ref": "vars.bb_stddev" }} }}], "assign": "local.bb" }},
        {{ "action": "call", "target": "market", "method": "getAllMids", "assign": "local.mids" }},
        {{ "action": "set", "path": "local.price", "value": {{ "ref": "local.mids.BTC" }} }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
          {{ "op": "lt", "args": [{{ "ref": "local.price" }}, {{ "ref": "local.bb.lower" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.in_position", "value": true }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["BB mean reversion entry — price below lower band at ", {{ "ref": "local.price" }}] }} }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "ref": "state.in_position" }},
          {{ "op": "gte", "args": [{{ "ref": "local.price" }}, {{ "ref": "local.bb.middle" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["BB mean reversion exit — price returned to middle band at ", {{ "ref": "local.price" }}] }} }}
        ] }}
      ]
    }}
  }}
}}

### Example 8: Multi-Coin Momentum Rotation
Strategy: "Every 4h, long the coin with best 24h performance, short the worst, between BTC and ETH"
{{
  "version": "1.0",
  "strategy_id": "momentum-rotation",
  "name": "Multi-Coin Momentum Rotation",
  "description": "Every 4h, long best 24h performer and short worst between BTC and ETH",
  "initial_state": {{ "long_coin": "none", "short_coin": "none" }},
  "variables": {{ "size": 0.01 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "rotation-timer", "type": "scheduled", "intervalMs": 14400000, "immediate": true, "onTrigger": "rotate" }}
  ],
  "workflows": {{
    "rotate": {{
      "steps": [
        {{ "action": "call", "target": "market", "method": "get24hChange", "args": ["BTC"], "assign": "local.btc_change" }},
        {{ "action": "call", "target": "market", "method": "get24hChange", "args": ["ETH"], "assign": "local.eth_change" }},
        {{ "action": "set", "path": "local.best_coin", "value": {{ "op": "if_else", "args": [{{ "op": "gte", "args": [{{ "ref": "local.btc_change" }}, {{ "ref": "local.eth_change" }}] }}, "BTC", "ETH"] }} }},
        {{ "action": "set", "path": "local.worst_coin", "value": {{ "op": "if_else", "args": [{{ "op": "lt", "args": [{{ "ref": "local.btc_change" }}, {{ "ref": "local.eth_change" }}] }}, "BTC", "ETH"] }} }},
        {{ "action": "if", "condition": {{ "op": "neq", "args": [{{ "ref": "state.long_coin" }}, "none"] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": [{{ "ref": "state.long_coin" }}, 0] }},
          {{ "action": "call", "target": "order", "method": "closePosition", "args": [{{ "ref": "state.short_coin" }}, 0] }},
          {{ "action": "log", "message": "Closed previous rotation positions" }}
        ] }},
        {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": [{{ "ref": "local.best_coin" }}, true, {{ "ref": "vars.size" }}, false] }},
        {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": [{{ "ref": "local.worst_coin" }}, false, {{ "ref": "vars.size" }}, false] }},
        {{ "action": "set", "path": "state.long_coin", "value": {{ "ref": "local.best_coin" }} }},
        {{ "action": "set", "path": "state.short_coin", "value": {{ "ref": "local.worst_coin" }} }},
        {{ "action": "log", "message": {{ "op": "add", "args": ["Rotation — long ", {{ "op": "add", "args": [{{ "ref": "local.best_coin" }}, {{ "op": "add", "args": [" short ", {{ "ref": "local.worst_coin" }}] }}] }}] }} }}
      ]
    }}
  }}
}}

### Example 9: Pairs Trading (Z-Score)
Strategy: "Trade ETH/BTC spread using z-score. Entry at |z| > 2, exit at z → 0"
{{
  "version": "1.0",
  "strategy_id": "pairs-ethbtc-zscore",
  "name": "ETH/BTC Pairs Z-Score",
  "description": "Trade ETH/BTC spread: enter when |z-score| > 2, exit when z-score reverts near 0",
  "initial_state": {{ "position": "none" }},
  "variables": {{ "size": 0.05, "lookback": 100, "entry_z": 2, "exit_z": 0.5 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "zscore-check", "type": "scheduled", "intervalMs": 3600000, "immediate": true, "onTrigger": "check_zscore" }}
  ],
  "workflows": {{
    "check_zscore": {{
      "steps": [
        {{ "action": "call", "target": "market", "method": "getPriceRatioSeries", "args": ["ETH", "BTC", {{ "ref": "vars.lookback" }}], "assign": "local.ratios" }},
        {{ "action": "set", "path": "local.z", "value": {{ "op": "zscore", "args": [{{ "ref": "local.ratios" }}] }} }},
        {{ "action": "set", "path": "local.abs_z", "value": {{ "op": "abs", "args": [{{ "ref": "local.z" }}] }} }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "eq", "args": [{{ "ref": "state.position" }}, "none"] }},
          {{ "op": "gt", "args": [{{ "ref": "local.z" }}, {{ "ref": "vars.entry_z" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["ETH", false, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.position", "value": "short_spread" }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["Pairs entry — short spread (short ETH, long BTC). Z=", {{ "ref": "local.z" }}] }} }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "eq", "args": [{{ "ref": "state.position" }}, "none"] }},
          {{ "op": "lt", "args": [{{ "ref": "local.z" }}, {{ "op": "mul", "args": [{{ "ref": "vars.entry_z" }}, -1] }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["ETH", true, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", false, {{ "ref": "vars.size" }}, false] }},
          {{ "action": "set", "path": "state.position", "value": "long_spread" }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["Pairs entry — long spread (long ETH, short BTC). Z=", {{ "ref": "local.z" }}] }} }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "op": "neq", "args": [{{ "ref": "state.position" }}, "none"] }},
          {{ "op": "lt", "args": [{{ "ref": "local.abs_z" }}, {{ "ref": "vars.exit_z" }}] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["ETH", 0] }},
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.position", "value": "none" }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["Pairs exit — z-score reverted. Z=", {{ "ref": "local.z" }}] }} }}
        ] }}
      ]
    }}
  }}
}}

### Example 10: Regime Detection with ADX
Strategy: "Detect regime via ADX. In trending (ADX > 25): use EMA crossover. In ranging (ADX < 20): use RSI mean reversion."
{{
  "version": "1.0",
  "strategy_id": "regime-adx-hybrid",
  "name": "ADX Regime Detection Hybrid",
  "description": "ADX > 25 trending regime uses EMA crossover; ADX < 20 ranging regime uses RSI mean reversion",
  "initial_state": {{ "in_position": false, "regime": "unknown", "entry_side": "none" }},
  "variables": {{ "size": 0.01, "adx_trend_threshold": 25, "adx_range_threshold": 20, "rsi_oversold": 30, "rsi_overbought": 70, "ema_fast": 9, "ema_slow": 21 }},
  "risk": {{ "requireSafetyCheck": false, "minNotional": 0 }},
  "triggers": [
    {{ "id": "regime-check", "type": "scheduled", "intervalMs": 300000, "immediate": true, "onTrigger": "detect_and_trade" }}
  ],
  "workflows": {{
    "detect_and_trade": {{
      "steps": [
        {{ "action": "call", "target": "market", "method": "getIndicator", "args": ["BTC", "ADX", {{ "period": 14 }}], "assign": "local.adx_data" }},
        {{ "action": "set", "path": "local.adx", "value": {{ "ref": "local.adx_data.adx" }} }},
        {{ "action": "if", "condition": {{ "op": "gt", "args": [{{ "ref": "local.adx" }}, {{ "ref": "vars.adx_trend_threshold" }}] }}, "then": [
          {{ "action": "set", "path": "state.regime", "value": "trending" }},
          {{ "action": "call", "target": "market", "method": "getIndicator", "args": ["BTC", "EMA", {{ "period": {{ "ref": "vars.ema_fast" }} }}], "assign": "local.ema_fast" }},
          {{ "action": "call", "target": "market", "method": "getIndicator", "args": ["BTC", "EMA", {{ "period": {{ "ref": "vars.ema_slow" }} }}], "assign": "local.ema_slow" }},
          {{ "action": "if", "condition": {{ "op": "and", "args": [
            {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
            {{ "op": "gt", "args": [{{ "ref": "local.ema_fast.value" }}, {{ "ref": "local.ema_slow.value" }}] }}
          ] }}, "then": [
            {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
            {{ "action": "set", "path": "state.in_position", "value": true }},
            {{ "action": "set", "path": "state.entry_side", "value": "long" }},
            {{ "action": "log", "message": {{ "op": "add", "args": ["Trending regime — EMA bullish crossover. ADX=", {{ "ref": "local.adx" }}] }} }}
          ] }},
          {{ "action": "if", "condition": {{ "op": "and", "args": [
            {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
            {{ "op": "lt", "args": [{{ "ref": "local.ema_fast.value" }}, {{ "ref": "local.ema_slow.value" }}] }}
          ] }}, "then": [
            {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", false, {{ "ref": "vars.size" }}, false] }},
            {{ "action": "set", "path": "state.in_position", "value": true }},
            {{ "action": "set", "path": "state.entry_side", "value": "short" }},
            {{ "action": "log", "message": {{ "op": "add", "args": ["Trending regime — EMA bearish crossover. ADX=", {{ "ref": "local.adx" }}] }} }}
          ] }}
        ], "else": [
          {{ "action": "if", "condition": {{ "op": "lt", "args": [{{ "ref": "local.adx" }}, {{ "ref": "vars.adx_range_threshold" }}] }}, "then": [
            {{ "action": "set", "path": "state.regime", "value": "ranging" }},
            {{ "action": "call", "target": "market", "method": "getIndicator", "args": ["BTC", "RSI", {{ "period": 14 }}], "assign": "local.rsi_data" }},
            {{ "action": "set", "path": "local.rsi", "value": {{ "ref": "local.rsi_data.value" }} }},
            {{ "action": "if", "condition": {{ "op": "and", "args": [
              {{ "op": "eq", "args": [{{ "ref": "state.in_position" }}, false] }},
              {{ "op": "lt", "args": [{{ "ref": "local.rsi" }}, {{ "ref": "vars.rsi_oversold" }}] }}
            ] }}, "then": [
              {{ "action": "call", "target": "order", "method": "placeMarketOrder", "args": ["BTC", true, {{ "ref": "vars.size" }}, false] }},
              {{ "action": "set", "path": "state.in_position", "value": true }},
              {{ "action": "set", "path": "state.entry_side", "value": "long" }},
              {{ "action": "log", "message": {{ "op": "add", "args": ["Ranging regime — RSI oversold entry. RSI=", {{ "ref": "local.rsi" }}] }} }}
            ] }},
            {{ "action": "if", "condition": {{ "op": "and", "args": [
              {{ "ref": "state.in_position" }},
              {{ "op": "gt", "args": [{{ "ref": "local.rsi" }}, {{ "ref": "vars.rsi_overbought" }}] }}
            ] }}, "then": [
              {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
              {{ "action": "set", "path": "state.in_position", "value": false }},
              {{ "action": "set", "path": "state.entry_side", "value": "none" }},
              {{ "action": "log", "message": "Ranging regime — RSI overbought exit" }}
            ] }}
          ] }}
        ] }},
        {{ "action": "if", "condition": {{ "op": "and", "args": [
          {{ "ref": "state.in_position" }},
          {{ "op": "and", "args": [
            {{ "op": "gte", "args": [{{ "ref": "local.adx" }}, {{ "ref": "vars.adx_range_threshold" }}] }},
            {{ "op": "lte", "args": [{{ "ref": "local.adx" }}, {{ "ref": "vars.adx_trend_threshold" }}] }}
          ] }}
        ] }}, "then": [
          {{ "action": "call", "target": "order", "method": "closePosition", "args": ["BTC", 0] }},
          {{ "action": "set", "path": "state.in_position", "value": false }},
          {{ "action": "set", "path": "state.entry_side", "value": "none" }},
          {{ "action": "set", "path": "state.regime", "value": "transition" }},
          {{ "action": "log", "message": {{ "op": "add", "args": ["Regime transition (ADX between 20-25) — closing position. ADX=", {{ "ref": "local.adx" }}] }} }}
        ] }}
      ]
    }}
  }}
}}

## Output Envelope

Return the JSON wrapped in an envelope:
{{
  "strategy_spec": {{ ... the full spec ... }},
  "notes": {{
    "complexity": "simple|medium|high",
    "backtest_warnings": ["list of limitations or approximations in candle-based backtest"],
    "reasoning_summary": "short summary of translation decisions"
  }}
}}
"""
