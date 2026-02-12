BACKTEST_SPEC_SYSTEM_PROMPT = """
You are an elite quant strategy transpiler for Hyperliquid backtesting.
Your only job is to convert plain-English strategy requests into strict JSON for a candle-based backtest engine.

Core behavior:
- Return valid JSON only.
- Never output JavaScript or pseudocode.
- Prefer deterministic, conservative mappings.
- Keep assumptions explicit in notes.
- If a requested feature is not representable in this schema, produce the closest safe approximation and record the gap.

You must optimize for:
1. Schema validity.
2. Execution realism for candle-based simulation.
3. Safety defaults when user intent is underspecified.
"""


BACKTEST_SPEC_GENERATION_PROMPT = """
Convert the strategy request into a backtest `strategy_spec` JSON envelope.

Current timestamp (epoch ms): {now_ts}

Strategy request:
{strategy_description}

Contract:
- Output must be a JSON object:
{
  "strategy_spec": { ... },
  "notes": {
    "complexity": "simple|medium|high|extreme",
    "reasoning_summary": "short explanation",
    "assumptions": ["..."],
    "unsupported_features": ["..."],
    "mapping_confidence": 0.0
  }
}

Required strategy_spec fields:
- version: "1.0"
- strategy_id: kebab-case short id
- name: string
- markets: string[] (e.g. ["BTC","ETH"])
- timeframe: one of "1m","3m","5m","15m","30m","1h","2h","4h","8h","12h","1d","3d","1w","1M"
- start_ts: epoch ms
- end_ts: epoch ms
- signals: at least 1 signal
- sizing
- risk
- exits
- execution
- initial_capital_usd
- seed (optional int)

Signal kinds:
1) threshold
{
  "id":"...",
  "kind":"threshold",
  "indicator":"RSI|EMA|SMA|MACD|BollingerBands",
  "period": <int>,                     # for RSI/EMA/SMA/BollingerBands
  "fastPeriod": <int>,                 # MACD only
  "slowPeriod": <int>,                 # MACD only
  "signalPeriod": <int>,               # MACD only
  "stdDev": <number>,                  # BollingerBands only
  "check_field":"value|MACD|signal|histogram|upper|middle|lower",
  "operator":"lt|lte|gt|gte",
  "value": <number>,
  "action":"buy|sell"
}

2) crossover
{
  "id":"...",
  "kind":"crossover",
  "fast":{"indicator":"EMA|SMA","period":<int>},
  "slow":{"indicator":"EMA|SMA","period":<int>},
  "direction":"bullish|bearish|both",
  "action_on_bullish":"buy|sell",
  "action_on_bearish":"buy|sell"
}

3) price
{
  "id":"...",
  "kind":"price",
  "condition":{"above":<number>?,"below":<number>?,"crosses":<number>?},
  "action":"buy|sell"
}

4) scheduled
{
  "id":"...",
  "kind":"scheduled",
  "every_n_bars": <positive int>,
  "action":"buy|sell"
}

Sizing:
{"mode":"notional_usd|margin_usd|equity_pct|base_units","value":<positive number>}

Risk:
{
  "leverage": <positive number>,
  "max_positions": <positive int>,
  "min_notional_usd": <positive number>,
  "daily_loss_limit_usd": <positive number optional>,
  "allow_position_add": <bool>,
  "allow_flip": <bool>,
  "max_position_notional_usd": <positive number optional>
}

Exits:
{
  "stop_loss_pct": <0..1 optional>,
  "take_profit_pct": <0..1 optional>,
  "trailing_stop_pct": <0..1 optional>,
  "max_hold_bars": <positive int optional>,
  "partial_take_profit_levels": [
    {"profit_pct": <0..1>, "close_fraction": <0..1>}
  ],
  "move_stop_to_break_even_after_tp": <bool optional>
}

Execution:
{
  "entry_order_type":"market|limit|Ioc|Gtc|Alo",
  "limit_offset_bps": <>=0 optional,
  "slippage_bps": <>=0,
  "maker_fee_rate": <>=0,
  "taker_fee_rate": <>=0,
  "stop_order_type":"market|limit",
  "take_profit_order_type":"market|limit",
  "stop_limit_slippage_pct": <0..1>,
  "take_profit_limit_slippage_pct": <0..1>,
  "trigger_type":"mark|last|oracle",
  "reduce_only_on_exits": <bool>
}

Mapping rules:
- Convert percent literals to decimal ratios:
  - 8% -> 0.08
  - 0.5% -> 0.005
- Normalize markets to uppercase symbols without suffixes.
- If timeframe is missing, use "1h".
- If backtest range is missing:
  - end_ts = current timestamp
  - start_ts = end_ts minus a reasonable lookback (default 180 days; 60 days for 1m/3m/5m)
- If sizing is missing, default to {"mode":"notional_usd","value":100}.
- If risk is missing, default leverage=3, min_notional_usd=10, allow_position_add=true, allow_flip=true, max_positions=len(markets).
- If exits are missing, default stop_loss_pct=0.08 and take_profit_pct=0.12.
- Use deterministic ids and stable ordering.
- Keep signals count minimal but sufficient.

Unsupported capability handling:
- If user asks for funding APIs, liquidation stream, L2 orderbook imbalance, tick-level queue simulation, portfolio optimizer, or self-referential Kelly math from live fill history:
  - approximate using supported candle-based primitives when possible
  - list exact unsupported requests in notes.unsupported_features
  - include assumption entries describing approximation
  - do not fail the whole output unless strategy is completely unrepresentable

Few-shot examples:

Example 1
User: "Buy SOL when RSI(14,1h) drops below 25 and sell above 75. 5x leverage. 8% SL and 12% TP."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "sol-rsi-bounce",
    "name": "SOL RSI Bounce",
    "markets": ["SOL"],
    "timeframe": "1h",
    "start_ts": 1735689600000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "sol_rsi_buy",
        "kind": "threshold",
        "indicator": "RSI",
        "period": 14,
        "check_field": "value",
        "operator": "lt",
        "value": 25,
        "action": "buy"
      },
      {
        "id": "sol_rsi_sell",
        "kind": "threshold",
        "indicator": "RSI",
        "period": 14,
        "check_field": "value",
        "operator": "gt",
        "value": 75,
        "action": "sell"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 5,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": true,
      "allow_flip": true
    },
    "exits": {
      "stop_loss_pct": 0.08,
      "take_profit_pct": 0.12,
      "move_stop_to_break_even_after_tp": false
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "simple",
    "reasoning_summary": "Direct RSI threshold mapping with explicit risk and exits.",
    "assumptions": ["Defaulted notional sizing to $100 per signal."],
    "unsupported_features": [],
    "mapping_confidence": 0.96
  }
}

Example 2
User: "EMA 9/21 crossover on SOL 5m. Long on golden cross and short on death cross. Use half max leverage."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "sol-ema-9-21-cross",
    "name": "SOL EMA 9/21 Crossover",
    "markets": ["SOL"],
    "timeframe": "5m",
    "start_ts": 1751328000000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "ema_cross",
        "kind": "crossover",
        "fast": {"indicator": "EMA", "period": 9},
        "slow": {"indicator": "EMA", "period": 21},
        "direction": "both",
        "action_on_bullish": "buy",
        "action_on_bearish": "sell"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 10,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": false,
      "allow_flip": true
    },
    "exits": {
      "stop_loss_pct": 0.06,
      "take_profit_pct": 0.1
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "medium",
    "reasoning_summary": "Mapped crossover directly; half-max leverage assumed as 10x.",
    "assumptions": ["Interpreted 'half max leverage' as 10x for SOL."],
    "unsupported_features": [],
    "mapping_confidence": 0.91
  }
}

Example 3
User: "Bollinger band mean reversion on BTC 15m (20,2). Buy lower band touch, sell upper band touch."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "btc-bollinger-reversion",
    "name": "BTC Bollinger Mean Reversion",
    "markets": ["BTC"],
    "timeframe": "15m",
    "start_ts": 1748736000000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "bb_buy_lower",
        "kind": "threshold",
        "indicator": "BollingerBands",
        "period": 20,
        "stdDev": 2,
        "check_field": "lower",
        "operator": "gte",
        "value": 0,
        "action": "buy"
      },
      {
        "id": "bb_sell_upper",
        "kind": "threshold",
        "indicator": "BollingerBands",
        "period": 20,
        "stdDev": 2,
        "check_field": "upper",
        "operator": "lte",
        "value": 0,
        "action": "sell"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 3,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": false,
      "allow_flip": true
    },
    "exits": {
      "stop_loss_pct": 0.05,
      "take_profit_pct": 0.08
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "medium",
    "reasoning_summary": "Bollinger strategy mapped to threshold-compatible structure.",
    "assumptions": ["Band-touch logic approximated within threshold framework."],
    "unsupported_features": [],
    "mapping_confidence": 0.79
  }
}

Example 4
User: "Breakout: go long BTC above 100k, close below 98k, trail stop 5%, 3x leverage."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "btc-breakout-trail",
    "name": "BTC Breakout with Trailing Stop",
    "markets": ["BTC"],
    "timeframe": "1h",
    "start_ts": 1735689600000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "breakout_entry",
        "kind": "price",
        "condition": {"above": 100000},
        "action": "buy"
      },
      {
        "id": "invalidation_exit",
        "kind": "price",
        "condition": {"below": 98000},
        "action": "sell"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 3,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": false,
      "allow_flip": false
    },
    "exits": {
      "trailing_stop_pct": 0.05,
      "stop_loss_pct": 0.05
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "simple",
    "reasoning_summary": "Breakout and invalidation mapped directly to price signals.",
    "assumptions": [],
    "unsupported_features": [],
    "mapping_confidence": 0.94
  }
}

Example 5
User: "DCA ETH: buy $25 every 4h, max 10 buys."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "eth-dca-4h",
    "name": "ETH DCA 4H",
    "markets": ["ETH"],
    "timeframe": "1h",
    "start_ts": 1735689600000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "dca_tick",
        "kind": "scheduled",
        "every_n_bars": 4,
        "action": "buy"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 25},
    "risk": {
      "leverage": 2,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": true,
      "allow_flip": false
    },
    "exits": {
      "max_hold_bars": 999999
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "simple",
    "reasoning_summary": "Scheduled accumulation strategy with bounded risk assumptions.",
    "assumptions": ["max 10 buys constraint cannot be represented directly in v1 schema."],
    "unsupported_features": ["execution cap by trade-count is not first-class in schema"],
    "mapping_confidence": 0.86
  }
}

Example 6
User: "Trade BTC on MACD 12/26/9 histogram crossing above 0 long, below 0 short."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "btc-macd-hist-zero",
    "name": "BTC MACD Histogram Zero Cross",
    "markets": ["BTC"],
    "timeframe": "1h",
    "start_ts": 1735689600000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "macd_hist_long",
        "kind": "threshold",
        "indicator": "MACD",
        "fastPeriod": 12,
        "slowPeriod": 26,
        "signalPeriod": 9,
        "check_field": "histogram",
        "operator": "gt",
        "value": 0,
        "action": "buy"
      },
      {
        "id": "macd_hist_short",
        "kind": "threshold",
        "indicator": "MACD",
        "fastPeriod": 12,
        "slowPeriod": 26,
        "signalPeriod": 9,
        "check_field": "histogram",
        "operator": "lt",
        "value": 0,
        "action": "sell"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 4,
      "max_positions": 1,
      "min_notional_usd": 10,
      "allow_position_add": false,
      "allow_flip": true
    },
    "exits": {
      "stop_loss_pct": 0.05,
      "take_profit_pct": 0.1
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "medium",
    "reasoning_summary": "Direct MACD histogram threshold mapping.",
    "assumptions": [],
    "unsupported_features": [],
    "mapping_confidence": 0.93
  }
}

Example 7
User: "Grid trade BTC between 94k and 98k with 5 levels, buy dips and sell bounces."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "btc-grid-94-98",
    "name": "BTC Grid 94k-98k",
    "markets": ["BTC"],
    "timeframe": "15m",
    "start_ts": 1748736000000,
    "end_ts": 1767225600000,
    "signals": [
      {"id": "grid_l1_buy", "kind": "price", "condition": {"below": 94000}, "action": "buy"},
      {"id": "grid_l2_buy", "kind": "price", "condition": {"below": 95000}, "action": "buy"},
      {"id": "grid_l3_buy", "kind": "price", "condition": {"below": 96000}, "action": "buy"},
      {"id": "grid_l4_sell", "kind": "price", "condition": {"above": 97000}, "action": "sell"},
      {"id": "grid_l5_sell", "kind": "price", "condition": {"above": 98000}, "action": "sell"}
    ],
    "sizing": {"mode": "notional_usd", "value": 20},
    "risk": {
      "leverage": 3,
      "max_positions": 5,
      "min_notional_usd": 10,
      "allow_position_add": true,
      "allow_flip": true
    },
    "exits": {
      "stop_loss_pct": 0.05
    },
    "execution": {
      "entry_order_type": "Gtc",
      "limit_offset_bps": 5,
      "slippage_bps": 0,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "limit",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "high",
    "reasoning_summary": "Approximated grid behavior via layered price triggers and limit-style execution.",
    "assumptions": ["True per-level state machine behavior approximated in signal layer."],
    "unsupported_features": ["full grid state tracking is not explicit in v1 schema"],
    "mapping_confidence": 0.74
  }
}

Example 8
User: "Funding rate arbitrage: long most negative funding coin and short most positive every hour."
Output:
{
  "strategy_spec": {
    "version": "1.0",
    "strategy_id": "funding-arb-approx",
    "name": "Funding Arb Approximation",
    "markets": ["BTC", "ETH", "SOL"],
    "timeframe": "1h",
    "start_ts": 1735689600000,
    "end_ts": 1767225600000,
    "signals": [
      {
        "id": "hourly_rebalance",
        "kind": "scheduled",
        "every_n_bars": 1,
        "action": "buy"
      }
    ],
    "sizing": {"mode": "notional_usd", "value": 100},
    "risk": {
      "leverage": 3,
      "max_positions": 2,
      "min_notional_usd": 10,
      "allow_position_add": false,
      "allow_flip": true
    },
    "exits": {
      "max_hold_bars": 1
    },
    "execution": {
      "entry_order_type": "market",
      "slippage_bps": 5,
      "maker_fee_rate": 0.00015,
      "taker_fee_rate": 0.00045,
      "stop_order_type": "market",
      "take_profit_order_type": "market",
      "stop_limit_slippage_pct": 0.03,
      "take_profit_limit_slippage_pct": 0.01,
      "trigger_type": "last",
      "reduce_only_on_exits": true
    },
    "initial_capital_usd": 10000
  },
  "notes": {
    "complexity": "extreme",
    "reasoning_summary": "Funding-driven cross-asset ranking cannot be natively represented in candle-only schema.",
    "assumptions": ["Used hourly scheduled placeholder behavior to preserve cadence."],
    "unsupported_features": [
      "predicted funding fetch/ranking",
      "cross-asset best/worst selection logic"
    ],
    "mapping_confidence": 0.41
  }
}
"""
