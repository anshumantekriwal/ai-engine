#!/usr/bin/env python3
"""
Generate a deterministic 20-strategy spec-generation matrix artifact.

This exercises the real StrategySpecGenerator path with a mock provider,
then writes per-strategy generation outputs and runtime plans for the
spec runtime matrix runner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from strategy_spec_generator import StrategySpecGenerator


def base_spec(strategy_id: str, name: str, *, mode: str = "hybrid", description: str = "") -> Dict[str, Any]:
    return {
        "version": "1.0",
        "strategy_id": strategy_id,
        "name": name,
        "description": description,
        "mode": mode,
        "variables": {},
        "initial_state": {},
        "risk": {
            "minNotional": 10,
            "requireSafetyCheck": True,
            "allowUnsafeOrderMethods": False,
        },
        "triggers": [],
        "workflows": {},
    }


def build_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # 1) RSI Oversold Bounce
    spec = base_spec("s01-rsi-bounce", "RSI Oversold Bounce")
    spec["initial_state"] = {"tradeState": {"SOL": {"ideaActive": False}}}
    spec["triggers"] = [
        {
            "id": "rsi_buy",
            "type": "technical",
            "coin": "SOL",
            "indicator": "RSI",
            "params": {"period": 14, "interval": "1h"},
            "condition": {"below": 25},
            "onTrigger": "entry",
        },
        {
            "id": "user_fill_close",
            "type": "event",
            "eventType": "userFill",
            "onTrigger": "external_close",
        },
    ]
    spec["workflows"] = {
        "entry": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "not",
                        "args": [{"ref": "state.tradeState.SOL.ideaActive"}],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "setLeverage",
                            "args": ["SOL", 5, True],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["SOL", True, 0.2],
                            "assign": "results.entry",
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeStopLoss",
                            "args": ["SOL", False, 0.2, 92.0],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeTakeProfit",
                            "args": ["SOL", False, 0.2, 112.0],
                        },
                        {
                            "action": "set",
                            "path": "state.tradeState.SOL.ideaActive",
                            "value": True,
                        },
                    ],
                },
                {"action": "return", "value": {"ref": "results.entry.success"}},
            ]
        },
        "external_close": {
            "steps": [
                {
                    "action": "set",
                    "path": "state.tradeState.SOL.ideaActive",
                    "value": False,
                }
            ]
        },
    }
    cases.append(
        {
            "order": 1,
            "id": "s01-rsi-bounce",
            "name": "RSI Oversold Bounce",
            "prompt": "Buy $100 of SOL when RSI(14, 1h) drops below 25, sell when it rises above 75. 5x leverage, 8% SL / 12% TP.",
            "complexity": "simple",
            "required_features": [
                "technical_rsi_threshold",
                "leverage_control",
                "sl_tp_orders",
                "excursion_reentry_gating",
                "external_fill_detection",
            ],
            "implemented_features": [
                "technical_rsi_threshold",
                "leverage_control",
                "sl_tp_orders",
                "excursion_reentry_gating",
                "external_fill_detection",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "simple",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "RSI trigger with guarded entry and SL/TP orders",
                },
            },
            "runtime_plan": {
                "trigger_sequence": ["rsi_buy", "user_fill_close"],
                "events": [
                    {"type": "technical", "coin": "SOL", "value": 20},
                    {"type": "event", "eventType": "userFill", "coin": "SOL"},
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_stop_loss_orders": 1,
                    "min_take_profit_orders": 1,
                    "state_equals": [
                        {"path": "tradeState.SOL.ideaActive", "equals": False}
                    ],
                },
            },
        }
    )

    # 2) Price Level Breakout
    spec = base_spec("s02-price-breakout", "Price Level Breakout")
    spec["initial_state"] = {"positionOpen": False}
    spec["triggers"] = [
        {
            "id": "breakout_up",
            "type": "price",
            "coin": "BTC",
            "condition": {"above": 100000},
            "onTrigger": "entry",
        },
        {
            "id": "invalidate_down",
            "type": "price",
            "coin": "BTC",
            "condition": {"below": 98000},
            "onTrigger": "exit",
        },
    ]
    spec["workflows"] = {
        "entry": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "not",
                        "args": [{"ref": "state.positionOpen"}],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "setLeverage",
                            "args": ["BTC", 3, True],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeTrailingStop",
                            "args": ["BTC", False, 0.2, 5, True],
                        },
                        {
                            "action": "set",
                            "path": "state.positionOpen",
                            "value": True,
                        },
                    ],
                }
            ]
        },
        "exit": {
            "steps": [
                {
                    "action": "if",
                    "condition": {"ref": "state.positionOpen"},
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["BTC"],
                        },
                        {
                            "action": "set",
                            "path": "state.positionOpen",
                            "value": False,
                        },
                    ],
                }
            ]
        },
    }
    cases.append(
        {
            "order": 2,
            "id": "s02-price-breakout",
            "name": "Price Level Breakout",
            "prompt": "Go long BTC if price breaks above $100,000 with 3x leverage. Trail stop at 5%. Close if price drops back below $98,000.",
            "complexity": "simple",
            "required_features": [
                "price_break_entry",
                "post_entry_invalidation",
                "trailing_stop",
                "entry_exit_sequencing",
            ],
            "implemented_features": [
                "price_break_entry",
                "post_entry_invalidation",
                "trailing_stop",
                "entry_exit_sequencing",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "simple",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Dual price triggers with stateful entry/exit sequencing",
                },
            },
            "runtime_plan": {
                "trigger_sequence": ["breakout_up", "invalidate_down"],
                "events": [
                    {"type": "price", "coin": "BTC", "price": 100100},
                    {"type": "price", "coin": "BTC", "price": 97900},
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_trailing_stop_orders": 1,
                    "min_close_positions": 1,
                    "state_equals": [{"path": "positionOpen", "equals": False}],
                },
            },
        }
    )

    # 3) DCA
    spec = base_spec("s03-dca", "DCA Every 4 Hours", mode="spec")
    spec["variables"] = {"maxBuys": 3}
    spec["initial_state"] = {"buyCount": 0}
    spec["triggers"] = [
        {
            "id": "dca_tick",
            "type": "scheduled",
            "intervalMs": 4 * 60 * 60 * 1000,
            "onTrigger": "cycle",
        }
    ]
    spec["workflows"] = {
        "cycle": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "lt",
                        "args": [{"ref": "state.buyCount"}, {"ref": "vars.maxBuys"}],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["ETH", True, 0.25],
                        },
                        {
                            "action": "set",
                            "path": "state.buyCount",
                            "value": {
                                "op": "add",
                                "args": [{"ref": "state.buyCount"}, 1],
                            },
                        },
                    ],
                },
                {"action": "return", "value": {"ref": "state.buyCount"}},
            ]
        }
    }
    cases.append(
        {
            "order": 3,
            "id": "s03-dca",
            "name": "Dollar-Cost Averaging",
            "prompt": "Buy $25 of ETH every 4 hours regardless of price. Max 10 buys. Use 2x leverage.",
            "complexity": "simple",
            "required_features": [
                "scheduled_interval",
                "max_buy_counter",
                "persistent_state",
            ],
            "implemented_features": [
                "scheduled_interval",
                "max_buy_counter",
                "persistent_state",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "simple",
                    "uses_hybrid_patterns": False,
                    "reasoning_summary": "Pure scheduled accumulation with capped count",
                },
            },
            "runtime_plan": {
                "trigger_id": "dca_tick",
                "events": [
                    {"type": "scheduled"},
                    {"type": "scheduled"},
                    {"type": "scheduled"},
                    {"type": "scheduled"},
                ],
                "assertions": {
                    "exact_market_orders": 3,
                    "state_equals": [{"path": "buyCount", "equals": 3}],
                },
            },
        }
    )

    # 4) Bollinger Mean Reversion
    spec = base_spec("s04-bollinger-reversion", "Bollinger Mean Reversion")
    spec["initial_state"] = {"lastBandTouch": "none"}
    spec["triggers"] = [
        {
            "id": "bb_tick",
            "type": "scheduled",
            "intervalMs": 60_000,
            "onTrigger": "bb_eval",
        },
    ]
    spec["workflows"] = {
        "bb_eval": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "lte", "args": [{"ref": "trigger.price"}, {"ref": "trigger.lowerBand"}]},
                            {"op": "neq", "args": [{"ref": "state.lastBandTouch"}, "lower"]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        },
                        {"action": "set", "path": "state.lastBandTouch", "value": "lower"},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gte", "args": [{"ref": "trigger.price"}, {"ref": "trigger.upperBand"}]},
                            {"op": "neq", "args": [{"ref": "state.lastBandTouch"}, "upper"]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", False, 0.2],
                        },
                        {"action": "set", "path": "state.lastBandTouch", "value": "upper"},
                    ],
                },
            ]
        },
    }
    cases.append(
        {
            "order": 4,
            "id": "s04-bollinger-reversion",
            "name": "Bollinger Band Mean Reversion",
            "prompt": "Trade BTC using Bollinger Bands (20, 2) on 15m candles. Buy when price touches the lower band, sell when it touches the upper band. $50 per trade, 10x leverage.",
            "complexity": "simple",
            "required_features": [
                "dynamic_band_price_comparison",
                "bb_indicator_fetch",
                "mean_reversion_exit",
                "anti_repeat_signals",
            ],
            "implemented_features": [
                "dynamic_band_price_comparison",
                "bb_indicator_fetch",
                "mean_reversion_exit",
                "anti_repeat_signals",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "medium",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Indicator triggers with directional responses",
                },
            },
            "runtime_plan": {
                "trigger_id": "bb_tick",
                "events": [
                    {"type": "scheduled", "price": 94, "lowerBand": 95, "upperBand": 105},
                    {"type": "scheduled", "price": 94.2, "lowerBand": 95, "upperBand": 105},
                    {"type": "scheduled", "price": 106, "lowerBand": 95, "upperBand": 105},
                ],
                "assertions": {
                    "min_market_orders": 2,
                    "state_equals": [{"path": "lastBandTouch", "equals": "upper"}],
                },
            },
        }
    )

    # 5) Funding Carry
    spec = base_spec("s05-funding-carry", "Funding Rate Carry")
    spec["variables"] = {"shortThreshold": 0.01, "longThreshold": -0.01}
    spec["initial_state"] = {"regime": "flat"}
    spec["triggers"] = [
        {
            "id": "funding_tick",
            "type": "scheduled",
            "intervalMs": 15 * 60 * 1000,
            "onTrigger": "funding_eval",
        }
    ]
    spec["workflows"] = {
        "funding_eval": {
            "steps": [
                {
                    "action": "call",
                    "target": "market",
                    "method": "getPredictedFundings",
                    "assign": "results.funding",
                },
                {"action": "set", "path": "local.rate", "value": {"ref": "results.funding.BTC"}},
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gte", "args": [{"ref": "local.rate"}, {"ref": "vars.shortThreshold"}]},
                            {"op": "neq", "args": [{"ref": "state.regime"}, "short"]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", False, 0.2],
                        },
                        {"action": "set", "path": "state.regime", "value": "short"},
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "and",
                                "args": [
                                    {"op": "lte", "args": [{"ref": "local.rate"}, {"ref": "vars.longThreshold"}]},
                                    {"op": "neq", "args": [{"ref": "state.regime"}, "long"]},
                                ],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", True, 0.2],
                                },
                                {"action": "set", "path": "state.regime", "value": "long"},
                            ],
                        }
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 5,
            "id": "s05-funding-carry",
            "name": "Funding Rate Carry",
            "prompt": "If BTC funding rate is above 0.01%, go short. If below -0.01%, go long. Hold until funding flips. Use 3x leverage with $200 margin.",
            "complexity": "simple",
            "required_features": [
                "funding_data_polling",
                "regime_flip_entry_exit",
                "reentry_gating",
            ],
            "implemented_features": [
                "funding_data_polling",
                "regime_flip_entry_exit",
                "reentry_gating",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "medium",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Funding polling with directional regime toggling",
                },
            },
            "runtime_plan": {
                "trigger_id": "funding_tick",
                "events": [{"type": "scheduled"}, {"type": "scheduled"}],
                "market_overrides": {"funding_sequence": [0.02, -0.02]},
                "assertions": {
                    "min_market_orders": 2,
                    "state_equals": [{"path": "regime", "equals": "long"}],
                },
            },
        }
    )

    # 6) EMA crossover
    spec = base_spec("s06-ema-crossover", "EMA 9/21 Crossover")
    spec["variables"] = {"minSignalGapMs": 60_000}
    spec["initial_state"] = {"prevFast": 0, "prevSlow": 0, "lastSignalTs": 0}
    spec["triggers"] = [
        {
            "id": "ema_tick",
            "type": "scheduled",
            "intervalMs": 60 * 1000,
            "onTrigger": "rebalance",
        }
    ]
    spec["workflows"] = {
        "rebalance": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "crosses_above",
                        "args": [
                            {"ref": "state.prevFast"},
                            {"ref": "trigger.emaFast"},
                            {"ref": "state.prevSlow"},
                            {"ref": "trigger.emaSlow"},
                        ],
                    },
                    "then": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "gte",
                                "args": [
                                    {"op": "sub", "args": [{"ref": "trigger.timestamp"}, {"ref": "state.lastSignalTs"}]},
                                    {"ref": "vars.minSignalGapMs"},
                                ],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["SOL", True, 0.2],
                                },
                                {"action": "set", "path": "state.lastSignalTs", "value": {"ref": "trigger.timestamp"}},
                            ],
                        }
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "crosses_below",
                                "args": [
                                    {"ref": "state.prevFast"},
                                    {"ref": "trigger.emaFast"},
                                    {"ref": "state.prevSlow"},
                                    {"ref": "trigger.emaSlow"},
                                ],
                            },
                            "then": [
                                {
                                    "action": "if",
                                    "condition": {
                                        "op": "gte",
                                        "args": [
                                            {"op": "sub", "args": [{"ref": "trigger.timestamp"}, {"ref": "state.lastSignalTs"}]},
                                            {"ref": "vars.minSignalGapMs"},
                                        ],
                                    },
                                    "then": [
                                        {
                                            "action": "call",
                                            "target": "order",
                                            "method": "placeMarketOrder",
                                            "args": ["SOL", False, 0.2],
                                        },
                                        {"action": "set", "path": "state.lastSignalTs", "value": {"ref": "trigger.timestamp"}},
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {"action": "set", "path": "state.prevFast", "value": {"ref": "trigger.emaFast"}},
                {"action": "set", "path": "state.prevSlow", "value": {"ref": "trigger.emaSlow"}},
            ]
        }
    }
    cases.append(
        {
            "order": 6,
            "id": "s06-ema-crossover",
            "name": "EMA 9/21 Crossover",
            "prompt": "Trade SOL using 9/21 EMA crossover on 5m candles. Go long on golden cross, short on death cross. $30 per trade, half of max leverage.",
            "complexity": "intermediate",
            "required_features": [
                "dual_indicator_crossover",
                "prev_state_tracking",
                "whipsaw_filter",
            ],
            "implemented_features": [
                "dual_indicator_crossover",
                "prev_state_tracking",
                "whipsaw_filter",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "medium",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Scheduled crossover with previous EMA state references",
                },
            },
            "runtime_plan": {
                "trigger_id": "ema_tick",
                "events": [
                    {"type": "scheduled", "emaFast": 9, "emaSlow": 10, "timestamp": 0},
                    {"type": "scheduled", "emaFast": 11, "emaSlow": 10, "timestamp": 30_000},
                    {"type": "scheduled", "emaFast": 8, "emaSlow": 10, "timestamp": 120_000},
                ],
                "assertions": {
                    "min_market_orders": 1,
                },
            },
        }
    )

    # 7) RSI + volume confirmation
    spec = base_spec("s07-rsi-volume", "RSI + Volume Confirmation")
    spec["initial_state"] = {"hasPosition": False}
    spec["triggers"] = [
        {
            "id": "signal_tick",
            "type": "scheduled",
            "intervalMs": 5 * 60 * 1000,
            "onTrigger": "evaluate",
        }
    ]
    spec["workflows"] = {
        "evaluate": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.avgVolume",
                    "value": {"op": "avg", "args": [{"ref": "trigger.volumeWindow"}]},
                },
                {
                    "action": "set",
                    "path": "local.volumeRatio",
                    "value": {
                        "op": "div",
                        "args": [{"ref": "trigger.currentVolume"}, {"ref": "local.avgVolume"}],
                    },
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "lt", "args": [{"ref": "trigger.rsi"}, 30]},
                            {"op": "gte", "args": [{"ref": "local.volumeRatio"}, 1.5]},
                            {"op": "not", "args": [{"ref": "state.hasPosition"}]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["ETH", True, 0.2],
                        },
                        {"action": "set", "path": "state.hasPosition", "value": True},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"ref": "state.hasPosition"},
                            {"op": "gt", "args": [{"ref": "trigger.rsi"}, 60]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["ETH"],
                        },
                        {"action": "set", "path": "state.hasPosition", "value": False},
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 7,
            "id": "s07-rsi-volume",
            "name": "RSI + Volume Confirmation",
            "prompt": "Buy ETH when RSI(14, 1h) is below 30 AND 1h volume is at least 1.5x the 24h average volume. Exit at RSI > 60 or 10% TP. $75 notional, 5x leverage.",
            "complexity": "intermediate",
            "required_features": [
                "rsi_condition",
                "volume_ratio_vs_avg",
                "conjunction_logic",
                "dual_exit_logic",
            ],
            "implemented_features": [
                "rsi_condition",
                "volume_ratio_vs_avg",
                "conjunction_logic",
                "dual_exit_logic",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "medium",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Conjunctive entry and stateful RSI-based exit",
                },
            },
            "runtime_plan": {
                "trigger_id": "signal_tick",
                "events": [
                    {"type": "scheduled", "rsi": 25, "currentVolume": 180, "volumeWindow": [100, 120, 110, 90]},
                    {"type": "scheduled", "rsi": 65, "currentVolume": 100, "volumeWindow": [100, 120, 110, 90]},
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_close_positions": 1,
                    "state_equals": [{"path": "hasPosition", "equals": False}],
                },
            },
        }
    )

    # 8) Grid trading
    spec = base_spec("s08-grid", "Range Grid Trading")
    spec["variables"] = {"lower": 94_000, "upper": 98_000, "levelCount": 5, "levelSize": 0.2}
    spec["initial_state"] = {"gridPlaced": [], "gridPartial": []}
    spec["triggers"] = [
        {
            "id": "grid_tick",
            "type": "scheduled",
            "intervalMs": 60 * 1000,
            "onTrigger": "grid_cycle",
        }
    ]
    spec["workflows"] = {
        "grid_cycle": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.levels",
                    "value": {
                        "op": "linspace",
                        "args": [{"ref": "vars.lower"}, {"ref": "vars.upper"}, {"ref": "vars.levelCount"}],
                    },
                },
                {
                    "action": "for_each",
                    "list": {"ref": "local.levels"},
                    "item": "level",
                    "steps": [
                        {
                            "action": "set",
                            "path": "local.isBuy",
                            "value": {"op": "lt", "args": [{"ref": "local.level"}, {"ref": "trigger.midPrice"}]},
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeLimitOrder",
                            "args": [
                                "BTC",
                                {"ref": "local.isBuy"},
                                {"ref": "vars.levelSize"},
                                {"op": "round", "args": [{"ref": "local.level"}, 2]},
                                False,
                            ],
                            "assign": "results.limitOrder",
                        },
                        {
                            "action": "call",
                            "target": "state",
                            "method": "push",
                            "args": [
                                "state.gridPlaced",
                                {
                                    "level": {"ref": "local.level"},
                                    "filled": {"ref": "results.limitOrder.filledSize"},
                                },
                            ],
                        },
                        {
                            "action": "if",
                            "condition": {
                                "op": "lt",
                                "args": [{"ref": "results.limitOrder.filledSize"}, {"ref": "vars.levelSize"}],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "state",
                                    "method": "push",
                                    "args": [
                                        "state.gridPartial",
                                        {
                                            "level": {"ref": "local.level"},
                                            "remaining": {
                                                "op": "sub",
                                                "args": [{"ref": "vars.levelSize"}, {"ref": "results.limitOrder.filledSize"}],
                                            },
                                        },
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 8,
            "id": "s08-grid",
            "name": "Range/Grid Trading",
            "prompt": "Grid trade BTC between $94,000 and $98,000 with 5 grid levels. Buy at each level going down, sell at each level going up. $20 per grid level, 3x leverage. Max 5 open positions.",
            "complexity": "intermediate",
            "required_features": [
                "grid_level_generation",
                "multi_limit_orders",
                "per_level_state_machine",
                "partial_fill_handling",
            ],
            "implemented_features": [
                "grid_level_generation",
                "multi_limit_orders",
                "per_level_state_machine",
                "partial_fill_handling",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Looped limit-order placement with simple fill bookkeeping",
                },
            },
            "runtime_plan": {
                "trigger_id": "grid_tick",
                "events": [
                    {"type": "scheduled", "midPrice": 96_000}
                ],
                "order_overrides": {"limit_fill_ratio": 0.5},
                "assertions": {
                    "min_limit_orders": 5,
                    "state_array_length": [
                        {"path": "gridPlaced", "length": 5},
                        {"path": "gridPartial", "length": 5},
                    ],
                },
            },
        }
    )

    # 9) VWAP reversion
    spec = base_spec("s09-vwap", "VWAP Reversion Scalping")
    spec["initial_state"] = {"side": "flat"}
    spec["triggers"] = [
        {
            "id": "vwap_tick",
            "type": "scheduled",
            "intervalMs": 60 * 1000,
            "onTrigger": "vwap_cycle",
        }
    ]
    spec["workflows"] = {
        "vwap_cycle": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.vwap",
                    "value": {
                        "op": "div",
                        "args": [
                            {"op": "dot", "args": [{"ref": "trigger.prices"}, {"ref": "trigger.volumes"}]},
                            {"op": "sum", "args": [{"ref": "trigger.volumes"}]},
                        ],
                    },
                },
                {
                    "action": "set",
                    "path": "local.deviation",
                    "value": {
                        "op": "percent_change",
                        "args": [{"ref": "trigger.price"}, {"ref": "local.vwap"}],
                    },
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "lt", "args": [{"ref": "local.deviation"}, -0.5]},
                            {"op": "neq", "args": [{"ref": "state.side"}, "long"]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["ETH", True, 0.2],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeStopLoss",
                            "args": [
                                "ETH",
                                False,
                                0.2,
                                {
                                    "op": "round",
                                    "args": [{"op": "mul", "args": [{"ref": "trigger.price"}, 0.9998]}, 4],
                                },
                            ],
                        },
                        {"action": "set", "path": "state.side", "value": "long"},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gt", "args": [{"ref": "local.deviation"}, 0.5]},
                            {"op": "neq", "args": [{"ref": "state.side"}, "short"]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["ETH", False, 0.2],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeStopLoss",
                            "args": [
                                "ETH",
                                True,
                                0.2,
                                {
                                    "op": "round",
                                    "args": [{"op": "mul", "args": [{"ref": "trigger.price"}, 1.0002]}, 4],
                                },
                            ],
                        },
                        {"action": "set", "path": "state.side", "value": "short"},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "lt", "args": [{"op": "abs", "args": [{"ref": "local.deviation"}]}, 0.05]},
                            {"op": "in", "args": [{"ref": "state.side"}, ["long", "short"]]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["ETH"],
                        },
                        {"action": "set", "path": "state.side", "value": "flat"},
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 9,
            "id": "s09-vwap",
            "name": "VWAP Reversion Scalping",
            "prompt": "Scalp ETH using VWAP on 5m candles. Buy when price drops 0.5% below VWAP, sell when it returns to VWAP. Short when price rises 0.5% above VWAP, cover at VWAP. Tight 0.3% SL. 15x leverage, $15 per trade.",
            "complexity": "intermediate",
            "required_features": [
                "vwap_calculation",
                "long_short_reversion",
                "tight_stop_precision",
                "four_leg_state_machine",
            ],
            "implemented_features": [
                "vwap_calculation",
                "long_short_reversion",
                "tight_stop_precision",
                "four_leg_state_machine",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Deviation-driven entries with flat reversion exits",
                },
            },
            "runtime_plan": {
                "trigger_id": "vwap_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "prices": [100, 101, 99, 100],
                        "volumes": [100, 120, 130, 90],
                        "price": 98.7,
                    },
                    {
                        "type": "scheduled",
                        "prices": [100, 101, 99, 100],
                        "volumes": [100, 120, 130, 90],
                        "price": 100.0,
                    },
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_close_positions": 1,
                    "min_stop_loss_orders": 1,
                    "state_equals": [{"path": "side", "equals": "flat"}],
                },
            },
        }
    )

    # 10) Multi-timeframe momentum
    spec = base_spec("s10-mtf-momentum", "Multi-Timeframe Momentum")
    spec["initial_state"] = {"hasPosition": False}
    spec["triggers"] = [
        {
            "id": "mtf_tick",
            "type": "scheduled",
            "intervalMs": 5 * 60 * 1000,
            "onTrigger": "mtf_eval",
        }
    ]
    spec["workflows"] = {
        "mtf_eval": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"ref": "trigger.htfTrendUp"},
                            {"op": "lt", "args": [{"ref": "trigger.rsi"}, 35]},
                            {"op": "not", "args": [{"ref": "state.hasPosition"}]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        },
                        {"action": "set", "path": "state.hasPosition", "value": True},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"ref": "state.hasPosition"},
                            {"op": "gt", "args": [{"ref": "trigger.rsi"}, 65]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["BTC"],
                        },
                        {"action": "set", "path": "state.hasPosition", "value": False},
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 10,
            "id": "s10-mtf-momentum",
            "name": "Multi-Timeframe Momentum",
            "prompt": "Only take long trades on BTC when the 4h EMA(50) is trending up. Entry: buy when 15m RSI drops below 35 (pullback into uptrend). Exit: 15m RSI above 65 or -5% ROI SL. $100 notional, 7x leverage.",
            "complexity": "intermediate",
            "required_features": [
                "multi_timeframe_filter",
                "hierarchical_entry_logic",
                "conditional_exit",
            ],
            "implemented_features": [
                "multi_timeframe_filter",
                "hierarchical_entry_logic",
                "conditional_exit",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Higher-timeframe gate with lower-timeframe pullback entries",
                },
            },
            "runtime_plan": {
                "trigger_id": "mtf_tick",
                "events": [
                    {"type": "scheduled", "htfTrendUp": True, "rsi": 30},
                    {"type": "scheduled", "htfTrendUp": True, "rsi": 68},
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_close_positions": 1,
                    "state_equals": [{"path": "hasPosition", "equals": False}],
                },
            },
        }
    )

    # 11) Momentum rotation
    spec = base_spec("s11-rotation", "Momentum Rotation")
    spec["initial_state"] = {"currentLongs": ["BTC"], "currentShorts": ["ETH"]}
    spec["triggers"] = [
        {
            "id": "rotation_tick",
            "type": "scheduled",
            "intervalMs": 8 * 60 * 60 * 1000,
            "onTrigger": "rotate",
        }
    ]
    spec["workflows"] = {
        "rotate": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.rankDesc",
                    "value": {"op": "sort_by_key", "args": [{"ref": "trigger.performance"}, "change", "desc"]},
                },
                {
                    "action": "set",
                    "path": "local.rankAsc",
                    "value": {"op": "sort_by_key", "args": [{"ref": "trigger.performance"}, "change", "asc"]},
                },
                {
                    "action": "set",
                    "path": "local.longAssets",
                    "value": {"op": "slice", "args": [{"ref": "local.rankDesc"}, 0, 2]},
                },
                {
                    "action": "set",
                    "path": "local.shortAssets",
                    "value": {"op": "slice", "args": [{"ref": "local.rankAsc"}, 0, 2]},
                },
                {
                    "action": "for_each",
                    "list": {"ref": "state.currentLongs"},
                    "item": "asset",
                    "steps": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": [{"op": "coalesce", "args": [{"ref": "local.asset.coin"}, {"ref": "local.asset"}]}],
                        }
                    ],
                },
                {
                    "action": "for_each",
                    "list": {"ref": "state.currentShorts"},
                    "item": "asset",
                    "steps": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": [{"op": "coalesce", "args": [{"ref": "local.asset.coin"}, {"ref": "local.asset"}]}],
                        }
                    ],
                },
                {
                    "action": "for_each",
                    "list": {"ref": "local.longAssets"},
                    "item": "asset",
                    "steps": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": [{"ref": "local.asset.coin"}, True, 0.2],
                        }
                    ],
                },
                {
                    "action": "for_each",
                    "list": {"ref": "local.shortAssets"},
                    "item": "asset",
                    "steps": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": [{"ref": "local.asset.coin"}, False, 0.2],
                        }
                    ],
                },
                {"action": "set", "path": "state.currentLongs", "value": {"ref": "local.longAssets"}},
                {"action": "set", "path": "state.currentShorts", "value": {"ref": "local.shortAssets"}},
            ]
        }
    }
    cases.append(
        {
            "order": 11,
            "id": "s11-rotation",
            "name": "Momentum Rotation (Top N)",
            "prompt": "Every 8 hours, rank BTC, ETH, SOL, DOGE, and AVAX by 24h price change. Go long the top 2 performers, short the bottom 2. Close positions from the previous rotation before opening new ones. $50 per position, 5x leverage.",
            "complexity": "advanced",
            "required_features": [
                "cross_asset_ranking",
                "rebalance_close_open_diff",
                "portfolio_state_tracking",
            ],
            "implemented_features": [
                "cross_asset_ranking",
                "rebalance_close_open_diff",
                "portfolio_state_tracking",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Rebalance loop assumes ranked lists are precomputed in trigger payload",
                },
            },
            "runtime_plan": {
                "trigger_id": "rotation_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "performance": [
                            {"coin": "BTC", "change": 0.5},
                            {"coin": "ETH", "change": 2.2},
                            {"coin": "SOL", "change": 1.8},
                            {"coin": "DOGE", "change": -1.6},
                            {"coin": "AVAX", "change": -1.1},
                        ],
                    }
                ],
                "assertions": {
                    "min_market_orders": 4,
                    "min_close_positions": 1,
                    "state_array_length": [
                        {"path": "currentLongs", "length": 2},
                        {"path": "currentShorts", "length": 2},
                    ],
                },
            },
        }
    )

    # 12) Liquidation cascade
    spec = base_spec("s12-liq-cascade", "Liquidation Cascade Fade")
    spec["initial_state"] = {"recentLiqs": [], "lastEntryTs": 0}
    spec["triggers"] = [
        {
            "id": "liq_event",
            "type": "event",
            "eventType": "liquidation",
            "onTrigger": "fade",
        }
    ]
    spec["workflows"] = {
        "fade": {
            "steps": [
                {
                    "action": "call",
                    "target": "state",
                    "method": "push",
                    "args": [
                        "state.recentLiqs",
                        {
                            "side": {"ref": "trigger.side"},
                            "notional": {"ref": "trigger.notional"},
                            "time": {"ref": "trigger.timestamp"},
                        },
                    ],
                },
                {
                    "action": "set",
                    "path": "local.sameSideCount",
                    "value": {
                        "op": "count_liquidations",
                        "args": [
                            {"ref": "state.recentLiqs"},
                            {"ref": "trigger.side"},
                            1000000,
                            120000,
                            {"ref": "trigger.timestamp"},
                        ],
                    },
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gte", "args": [{"ref": "local.sameSideCount"}, 3]},
                            {
                                "op": "gte",
                                "args": [
                                    {"op": "sub", "args": [{"ref": "trigger.timestamp"}, {"ref": "state.lastEntryTs"}]},
                                    60_000,
                                ],
                            },
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": [
                                "BTC",
                                {"op": "eq", "args": [{"ref": "trigger.side"}, "sell"]},
                                0.2,
                            ],
                        }
                        ,
                        {
                            "action": "set",
                            "path": "state.lastEntryTs",
                            "value": {"ref": "trigger.timestamp"},
                        }
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 12,
            "id": "s12-liq-cascade",
            "name": "Liquidation Cascade Scalping",
            "prompt": "When a BTC liquidation >$1M occurs, check if there have been 3+ liquidations in the same direction within the last 2 minutes. If so, open a $25 position in the opposite direction (fade the cascade). 3% trailing stop, max leverage. Max 2 concurrent positions.",
            "complexity": "advanced",
            "required_features": [
                "event_window_aggregation",
                "liquidation_pattern_count",
                "debounce_limit_positions",
            ],
            "implemented_features": [
                "event_window_aggregation",
                "liquidation_pattern_count",
                "debounce_limit_positions",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Event trigger consumes pre-aggregated liquidation metadata",
                },
            },
            "runtime_plan": {
                "trigger_id": "liq_event",
                "events": [
                    {
                        "type": "event",
                        "eventType": "liquidation",
                        "notional": 1200000,
                        "timestamp": 0,
                        "side": "sell",
                    },
                    {
                        "type": "event",
                        "eventType": "liquidation",
                        "notional": 1300000,
                        "timestamp": 40_000,
                        "side": "sell",
                    },
                    {
                        "type": "event",
                        "eventType": "liquidation",
                        "notional": 1250000,
                        "timestamp": 80_000,
                        "side": "sell",
                    }
                ],
                "assertions": {"min_market_orders": 1},
            },
        }
    )

    # 13) Funding differential arb
    spec = base_spec("s13-funding-arb", "Funding Differential Arbitrage")
    spec["initial_state"] = {"longCoin": "BTC", "shortCoin": "ETH"}
    spec["triggers"] = [
        {
            "id": "arb_tick",
            "type": "scheduled",
            "intervalMs": 60 * 60 * 1000,
            "onTrigger": "arb_cycle",
        }
    ]
    spec["workflows"] = {
        "arb_cycle": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.rankAsc",
                    "value": {"op": "sort_by_key", "args": [{"ref": "trigger.fundings"}, "rate", "asc"]},
                },
                {
                    "action": "set",
                    "path": "local.rankDesc",
                    "value": {"op": "sort_by_key", "args": [{"ref": "trigger.fundings"}, "rate", "desc"]},
                },
                {
                    "action": "set",
                    "path": "local.longCandidate",
                    "value": {"ref": "local.rankAsc.0.coin"},
                },
                {
                    "action": "set",
                    "path": "local.shortCandidate",
                    "value": {"ref": "local.rankDesc.0.coin"},
                },
                {
                    "action": "if",
                    "condition": {"ref": "state.longCoin"},
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": [{"ref": "state.longCoin"}],
                        }
                    ],
                },
                {
                    "action": "if",
                    "condition": {"ref": "state.shortCoin"},
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": [{"ref": "state.shortCoin"}],
                        }
                    ],
                },
                {
                    "action": "call",
                    "target": "order",
                    "method": "placeMarketOrder",
                    "args": [{"ref": "local.longCandidate"}, True, 0.2],
                },
                {
                    "action": "call",
                    "target": "order",
                    "method": "placeMarketOrder",
                    "args": [{"ref": "local.shortCandidate"}, False, 0.2],
                },
                {"action": "set", "path": "state.longCoin", "value": {"ref": "local.longCandidate"}},
                {"action": "set", "path": "state.shortCoin", "value": {"ref": "local.shortCandidate"}},
            ]
        }
    }
    cases.append(
        {
            "order": 13,
            "id": "s13-funding-arb",
            "name": "Funding Differential Arbitrage",
            "prompt": "Compare predicted funding rates across BTC, ETH, and SOL. Go long the coin with the most negative funding and short the coin with the most positive funding. Rebalance every hour. $100 notional per leg, 5x leverage.",
            "complexity": "advanced",
            "required_features": [
                "cross_coin_funding_ranking",
                "pair_open_long_short",
                "hourly_rebalance",
            ],
            "implemented_features": [
                "cross_coin_funding_ranking",
                "pair_open_long_short",
                "hourly_rebalance",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Arb legs execute from externally ranked long/short candidates",
                },
            },
            "runtime_plan": {
                "trigger_id": "arb_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "fundings": [
                            {"coin": "BTC", "rate": 0.01},
                            {"coin": "ETH", "rate": -0.03},
                            {"coin": "SOL", "rate": 0.02},
                        ],
                    }
                ],
                "assertions": {
                    "min_market_orders": 2,
                    "min_close_positions": 2,
                },
            },
        }
    )

    # 14) Pairs z-score
    spec = base_spec("s14-pairs-zscore", "Pairs Trading Z-Score")
    spec["initial_state"] = {"pairOpen": False}
    spec["triggers"] = [
        {
            "id": "pairs_tick",
            "type": "scheduled",
            "intervalMs": 15 * 60 * 1000,
            "onTrigger": "pairs_cycle",
        }
    ]
    spec["workflows"] = {
        "pairs_cycle": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.ratioSeries",
                    "value": {
                        "op": "elementwise_div",
                        "args": [{"ref": "trigger.ethPrices"}, {"ref": "trigger.btcPrices"}],
                    },
                },
                {
                    "action": "set",
                    "path": "local.zscore",
                    "value": {"op": "zscore", "args": [{"ref": "local.ratioSeries"}]},
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "lt",
                        "args": [{"ref": "local.zscore"}, -2],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["ETH", True, 0.2],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", False, 0.2],
                        },
                        {"action": "set", "path": "state.pairOpen", "value": True},
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "gt",
                                "args": [{"ref": "local.zscore"}, 2],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["ETH", False, 0.2],
                                },
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", True, 0.2],
                                },
                                {"action": "set", "path": "state.pairOpen", "value": True},
                            ],
                        }
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"ref": "state.pairOpen"},
                            {"op": "lt", "args": [{"op": "abs", "args": [{"ref": "local.zscore"}]}, 0.25]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["ETH"],
                        },
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["BTC"],
                        },
                        {"action": "set", "path": "state.pairOpen", "value": False},
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 14,
            "id": "s14-pairs-zscore",
            "name": "Pairs Trading (Spread Mean Reversion)",
            "prompt": "Trade the ETH/BTC spread. Calculate the ratio of ETH price to BTC price on a rolling 100-candle window (1h). When the z-score of the ratio drops below -2, go long ETH and short BTC. When z-score rises above +2, go short ETH and long BTC. Close when z-score returns to 0. $50 per leg, 3x leverage.",
            "complexity": "advanced",
            "required_features": [
                "rolling_ratio_series",
                "zscore_calc",
                "paired_position_lifecycle",
                "convergence_exit",
            ],
            "implemented_features": [
                "rolling_ratio_series",
                "zscore_calc",
                "paired_position_lifecycle",
                "convergence_exit",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Pair lifecycle is encoded, while spread stats are externally precomputed",
                },
            },
            "runtime_plan": {
                "trigger_id": "pairs_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "ethPrices": [2000, 2000, 2000, 2000, 2000, 500],
                        "btcPrices": [100000, 100000, 100000, 100000, 100000, 100000],
                    },
                    {
                        "type": "scheduled",
                        "ethPrices": [2000, 2000, 2000, 2000, 2000, 2000],
                        "btcPrices": [100000, 100000, 100000, 100000, 100000, 100000],
                    },
                ],
                "assertions": {
                    "min_market_orders": 2,
                    "min_close_positions": 2,
                    "state_equals": [{"path": "pairOpen", "equals": False}],
                },
            },
        }
    )

    # 15) ATR breakout
    spec = base_spec("s15-atr-breakout", "ATR Volatility Breakout")
    spec["variables"] = {"riskPerTrade": 10, "leverage": 10}
    spec["triggers"] = [
        {
            "id": "atr_tick",
            "type": "scheduled",
            "intervalMs": 5 * 60 * 1000,
            "onTrigger": "atr_entry",
        }
    ]
    spec["workflows"] = {
        "atr_entry": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.atr",
                    "value": {"op": "avg", "args": [{"ref": "trigger.trueRanges"}]},
                },
                {
                    "action": "set",
                    "path": "local.stopDistance",
                    "value": {"op": "mul", "args": [{"ref": "local.atr"}, 1.5]},
                },
                {
                    "action": "set",
                    "path": "local.dynamicSize",
                    "value": {
                        "op": "div",
                        "args": [
                            {"ref": "vars.riskPerTrade"},
                            {"op": "mul", "args": [{"ref": "local.stopDistance"}, {"ref": "vars.leverage"}]},
                        ],
                    },
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "neq",
                        "args": [{"ref": "trigger.breakout"}, "none"],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": [
                                "SOL",
                                {"op": "eq", "args": [{"ref": "trigger.breakout"}, "up"]},
                                {"ref": "local.dynamicSize"},
                            ],
                        },
                        {
                            "action": "if",
                            "condition": {"op": "eq", "args": [{"ref": "trigger.breakout"}, "up"]},
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeStopLoss",
                                    "args": [
                                        "SOL",
                                        False,
                                        {"ref": "local.dynamicSize"},
                                        {"op": "sub", "args": [{"ref": "trigger.price"}, {"ref": "local.stopDistance"}]},
                                    ],
                                }
                            ],
                            "else": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeStopLoss",
                                    "args": [
                                        "SOL",
                                        True,
                                        {"ref": "local.dynamicSize"},
                                        {"op": "add", "args": [{"ref": "trigger.price"}, {"ref": "local.stopDistance"}]},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 15,
            "id": "s15-atr-breakout",
            "name": "ATR-Based Volatility Breakout",
            "prompt": "Trade SOL: when the 1h candle body exceeds 2x the 14-period ATR, enter in the direction of the breakout candle. Position size dynamically: risk $10 per trade, SL at 1.5x ATR from entry. Adjust size so that if SL is hit, loss = $10. 10x leverage.",
            "complexity": "advanced",
            "required_features": [
                "atr_calculation",
                "dynamic_risk_sizing",
                "breakout_direction_entry",
                "atr_stop_distance",
            ],
            "implemented_features": [
                "atr_calculation",
                "dynamic_risk_sizing",
                "breakout_direction_entry",
                "atr_stop_distance",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "high",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Dynamic size and stop placement consume precomputed ATR-derived fields",
                },
            },
            "runtime_plan": {
                "trigger_id": "atr_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "breakout": "up",
                        "trueRanges": [2.0, 1.8, 2.2, 2.1, 2.3],
                        "price": 100.0,
                    }
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_stop_loss_orders": 1,
                },
            },
        }
    )

    # 16) Composite score
    spec = base_spec("s16-composite", "Composite Multi-Factor Scoring")
    spec["initial_state"] = {"side": "flat"}
    spec["triggers"] = [
        {
            "id": "score_tick",
            "type": "scheduled",
            "intervalMs": 30 * 60 * 1000,
            "onTrigger": "score_eval",
        }
    ]
    spec["workflows"] = {
        "score_eval": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.rsiScore",
                    "value": {"op": "mul", "args": [{"op": "normalize", "args": [{"ref": "trigger.rsi"}, 0, 100]}, 100]},
                },
                {
                    "action": "set",
                    "path": "local.macdScore",
                    "value": {"op": "mul", "args": [{"op": "normalize", "args": [{"ref": "trigger.macdHist"}, -5, 5]}, 100]},
                },
                {
                    "action": "set",
                    "path": "local.volumeScore",
                    "value": {"op": "mul", "args": [{"op": "normalize", "args": [{"ref": "trigger.volumeRatio"}, 0, 3]}, 100]},
                },
                {
                    "action": "set",
                    "path": "local.emaDistanceScore",
                    "value": {"op": "mul", "args": [{"op": "normalize", "args": [{"ref": "trigger.emaDistance"}, -5, 5]}, 100]},
                },
                {
                    "action": "set",
                    "path": "local.fundingScore",
                    "value": {"op": "mul", "args": [{"op": "normalize", "args": [{"ref": "trigger.fundingRate"}, -0.05, 0.05]}, 100]},
                },
                {
                    "action": "set",
                    "path": "local.compositeScore",
                    "value": {
                        "op": "add",
                        "args": [
                            {"ref": "local.rsiScore"},
                            {"ref": "local.macdScore"},
                            {"ref": "local.volumeScore"},
                            {"ref": "local.emaDistanceScore"},
                            {"ref": "local.fundingScore"},
                        ],
                    },
                },
                {
                    "action": "if",
                    "condition": {"op": "gt", "args": [{"ref": "local.compositeScore"}, 350]},
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        },
                        {"action": "set", "path": "state.side", "value": "long"},
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {"op": "lt", "args": [{"ref": "local.compositeScore"}, 150]},
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", False, 0.2],
                                },
                                {"action": "set", "path": "state.side", "value": "short"},
                            ],
                        }
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gte", "args": [{"ref": "local.compositeScore"}, 240]},
                            {"op": "lte", "args": [{"ref": "local.compositeScore"}, 260]},
                            {"op": "in", "args": [{"ref": "state.side"}, ["long", "short"]]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["BTC"],
                        },
                        {"action": "set", "path": "state.side", "value": "flat"},
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 16,
            "id": "s16-composite",
            "name": "Composite Multi-Factor Scoring",
            "prompt": "Score BTC every 30 minutes on 5 factors: RSI(14,1h), MACD histogram(12,26,9,1h), 1h volume vs 24h avg, distance from 4h EMA(50), and funding rate. Normalize each 0-100 and sum. Buy if composite > 350 (bullish confluence), short if < 150. Close at 250 (neutral). $80 notional, 8x leverage.",
            "complexity": "complex",
            "required_features": [
                "multifactor_normalization",
                "composite_score_thresholds",
                "neutral_exit_band",
            ],
            "implemented_features": [
                "multifactor_normalization",
                "composite_score_thresholds",
                "neutral_exit_band",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "extreme",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Composite thresholds are handled; factor normalization is externalized",
                },
            },
            "runtime_plan": {
                "trigger_id": "score_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "rsi": 80,
                        "macdHist": 4,
                        "volumeRatio": 2.5,
                        "emaDistance": 3,
                        "fundingRate": 0.04,
                    },
                    {
                        "type": "scheduled",
                        "rsi": 50,
                        "macdHist": 0,
                        "volumeRatio": 1.5,
                        "emaDistance": 0,
                        "fundingRate": 0.0,
                    },
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_close_positions": 1,
                    "state_equals": [{"path": "side", "equals": "flat"}],
                },
            },
        }
    )

    # 17) Regime switching
    spec = base_spec("s17-regime-switch", "Regime Detection Switching")
    spec["initial_state"] = {"activeRegime": "transition", "regimeCandidate": None, "candidateCount": 0}
    spec["triggers"] = [
        {
            "id": "regime_tick",
            "type": "scheduled",
            "intervalMs": 5 * 60 * 1000,
            "onTrigger": "regime_eval",
        }
    ]
    spec["workflows"] = {
        "regime_eval": {
            "steps": [
                {"action": "set", "path": "local.classified", "value": "transition"},
                {
                    "action": "if",
                    "condition": {"op": "gt", "args": [{"ref": "trigger.adx"}, 25]},
                    "then": [{"action": "set", "path": "local.classified", "value": "trending"}],
                    "else": [
                        {
                            "action": "if",
                            "condition": {"op": "lt", "args": [{"ref": "trigger.adx"}, 20]},
                            "then": [{"action": "set", "path": "local.classified", "value": "ranging"}],
                        }
                    ],
                },
                {
                    "action": "if",
                    "condition": {"op": "eq", "args": [{"ref": "local.classified"}, {"ref": "state.regimeCandidate"}]},
                    "then": [
                        {
                            "action": "set",
                            "path": "state.candidateCount",
                            "value": {"op": "add", "args": [{"ref": "state.candidateCount"}, 1]},
                        }
                    ],
                    "else": [
                        {"action": "set", "path": "state.regimeCandidate", "value": {"ref": "local.classified"}},
                        {"action": "set", "path": "state.candidateCount", "value": 1},
                    ],
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "neq", "args": [{"ref": "state.regimeCandidate"}, "transition"]},
                            {"op": "gte", "args": [{"ref": "state.candidateCount"}, 3]},
                        ],
                    },
                    "then": [
                        {"action": "set", "path": "state.activeRegime", "value": {"ref": "state.regimeCandidate"}}
                    ],
                },
                {
                    "action": "if",
                    "condition": {"op": "eq", "args": [{"ref": "state.activeRegime"}, "trending"]},
                    "then": [
                        {
                            "action": "if",
                            "condition": {"ref": "trigger.crossUp"},
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", True, 0.2],
                                }
                            ],
                            "else": [
                                {
                                    "action": "if",
                                    "condition": {"ref": "trigger.crossDown"},
                                    "then": [
                                        {
                                            "action": "call",
                                            "target": "order",
                                            "method": "placeMarketOrder",
                                            "args": ["BTC", False, 0.2],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {"op": "eq", "args": [{"ref": "state.activeRegime"}, "ranging"]},
                            "then": [
                                {
                                    "action": "if",
                                    "condition": {"op": "lt", "args": [{"ref": "trigger.rsi"}, 30]},
                                    "then": [
                                        {
                                            "action": "call",
                                            "target": "order",
                                            "method": "placeMarketOrder",
                                            "args": ["BTC", True, 0.2],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 17,
            "id": "s17-regime-switch",
            "name": "Regime Detection with Strategy Switching",
            "prompt": "Detect market regime on BTC: trending (ADX > 25) or ranging (ADX < 20). In trending regime, use EMA 9/21 crossover entries. In ranging regime, use RSI 30/70 mean reversion. Transition zone (ADX 20-25): no new trades, only manage existing. $60 per trade, 5x leverage.",
            "complexity": "complex",
            "required_features": [
                "adx_regime_classifier",
                "strategy_dispatch",
                "transition_hysteresis",
            ],
            "implemented_features": [
                "adx_regime_classifier",
                "strategy_dispatch",
                "transition_hysteresis",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "extreme",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Dispatch logic exists but ADX/hysteresis classifier is external",
                },
            },
            "runtime_plan": {
                "trigger_id": "regime_tick",
                "events": [
                    {"type": "scheduled", "adx": 27, "crossUp": False, "crossDown": False, "rsi": 50},
                    {"type": "scheduled", "adx": 28, "crossUp": False, "crossDown": False, "rsi": 50},
                    {"type": "scheduled", "adx": 29, "crossUp": True, "crossDown": False, "rsi": 50},
                    {"type": "scheduled", "adx": 18, "crossUp": False, "crossDown": False, "rsi": 40},
                    {"type": "scheduled", "adx": 17, "crossUp": False, "crossDown": False, "rsi": 35},
                    {"type": "scheduled", "adx": 16, "crossUp": False, "crossDown": False, "rsi": 25},
                ],
                "assertions": {"min_market_orders": 2},
            },
        }
    )

    # 18) Order book imbalance
    spec = base_spec("s18-book-imbalance", "Order Book Imbalance")
    spec["initial_state"] = {"positionOpen": False, "openedAt": 0}
    spec["triggers"] = [
        {
            "id": "book_tick",
            "type": "event",
            "eventType": "l2Book",
            "condition": {"coin": "BTC"},
            "onTrigger": "book_eval",
        },
        {
            "id": "time_tick",
            "type": "scheduled",
            "intervalMs": 30_000,
            "onTrigger": "time_stop",
        },
    ]
    spec["workflows"] = {
        "book_eval": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.bidAskRatio",
                    "value": {"op": "orderbook_imbalance", "args": [{"ref": "trigger.book"}, 0.005]},
                },
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"op": "gte", "args": [{"ref": "local.bidAskRatio"}, 3]},
                            {"op": "not", "args": [{"ref": "state.positionOpen"}]},
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        },
                        {"action": "set", "path": "state.positionOpen", "value": True},
                        {"action": "set", "path": "state.openedAt", "value": {"ref": "trigger.timestamp"}},
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "and",
                                "args": [
                                    {"op": "lte", "args": [{"ref": "local.bidAskRatio"}, 0.3333]},
                                    {"op": "not", "args": [{"ref": "state.positionOpen"}]},
                                ],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", False, 0.2],
                                },
                                {"action": "set", "path": "state.positionOpen", "value": True},
                                {"action": "set", "path": "state.openedAt", "value": {"ref": "trigger.timestamp"}},
                            ],
                        }
                    ],
                }
            ]
        },
        "time_stop": {
            "steps": [
                {
                    "action": "if",
                    "condition": {
                        "op": "and",
                        "args": [
                            {"ref": "state.positionOpen"},
                            {
                                "op": "gte",
                                "args": [
                                    {"op": "sub", "args": [{"ref": "trigger.timestamp"}, {"ref": "state.openedAt"}]},
                                    120_000,
                                ],
                            },
                        ],
                    },
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "closePosition",
                            "args": ["BTC"],
                        },
                        {"action": "set", "path": "state.positionOpen", "value": False},
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 18,
            "id": "s18-book-imbalance",
            "name": "Order Book Imbalance",
            "prompt": "Monitor BTC L2 order book in real-time. When bid-side volume within 0.5% of mid price exceeds ask-side volume by 3x, go long. When ask exceeds bid by 3x, go short. Hold for 2 minutes max, then close. $20 per trade, 20x leverage. Max 1 position at a time.",
            "complexity": "complex",
            "required_features": [
                "l2_book_subscription",
                "near_mid_volume_aggregation",
                "two_minute_time_stop",
            ],
            "implemented_features": [
                "l2_book_subscription",
                "near_mid_volume_aggregation",
                "two_minute_time_stop",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "extreme",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Entry threshold only; true L2 stream aggregation and timed exits are not modeled",
                },
            },
            "runtime_plan": {
                "trigger_sequence": ["book_tick", "time_tick", "time_tick"],
                "events": [
                    {
                        "type": "event",
                        "eventType": "l2Book",
                        "timestamp": 0,
                        "book": {
                            "levels": [
                                [{"px": "100", "sz": "9"}, {"px": "99.8", "sz": "4"}],
                                [{"px": "100.1", "sz": "2"}, {"px": "100.2", "sz": "2"}],
                            ]
                        },
                    },
                    {"type": "scheduled", "timestamp": 60_000},
                    {"type": "scheduled", "timestamp": 130_000},
                ],
                "assertions": {
                    "min_market_orders": 1,
                    "min_close_positions": 1,
                    "state_equals": [{"path": "positionOpen", "equals": False}],
                },
            },
        }
    )

    # 19) Kelly sizing
    spec = base_spec("s19-kelly", "Kelly Criterion Dynamic Sizing")
    spec["variables"] = {"leverage": 5, "halfKelly": 0.5, "maxFraction": 0.25}
    spec["triggers"] = [
        {
            "id": "kelly_tick",
            "type": "scheduled",
            "intervalMs": 5 * 60 * 1000,
            "onTrigger": "kelly_eval",
        }
    ]
    spec["workflows"] = {
        "kelly_eval": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.stats",
                    "value": {"op": "trade_stats", "args": [{"ref": "trigger.tradePnls"}]},
                },
                {
                    "action": "set",
                    "path": "local.positionFraction",
                    "value": {
                        "op": "kelly_fraction",
                        "args": [
                            {"ref": "local.stats.winRate"},
                            {"ref": "local.stats.avgWin"},
                            {"ref": "local.stats.avgLoss"},
                            {"ref": "vars.halfKelly"},
                            {"ref": "vars.maxFraction"},
                        ],
                    },
                },
                {
                    "action": "set",
                    "path": "local.size",
                    "value": {
                        "op": "div",
                        "args": [
                            {
                                "op": "mul",
                                "args": [
                                    {"ref": "trigger.balance"},
                                    {"ref": "local.positionFraction"},
                                    {"ref": "vars.leverage"},
                                ],
                            },
                            {"ref": "trigger.price"},
                        ],
                    },
                },
                {
                    "action": "if",
                    "condition": {"op": "eq", "args": [{"ref": "trigger.cross"}, "up"]},
                    "then": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, {"ref": "local.size"}],
                        }
                    ],
                    "else": [
                        {
                            "action": "if",
                            "condition": {"op": "eq", "args": [{"ref": "trigger.cross"}, "down"]},
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["BTC", False, {"ref": "local.size"}],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    cases.append(
        {
            "order": 19,
            "id": "s19-kelly",
            "name": "Kelly Criterion Dynamic Sizing",
            "prompt": "Trade BTC using EMA 20/50 crossover. After each trade closes, recalculate win rate and avg win/loss ratio from the last 20 trades. Use Kelly Criterion to set position size as a fraction of available balance. Half-Kelly for safety. Cap at 25% of balance per trade. 5x leverage.",
            "complexity": "complex",
            "required_features": [
                "trade_history_analysis",
                "kelly_formula",
                "dynamic_position_cap",
            ],
            "implemented_features": [
                "trade_history_analysis",
                "kelly_formula",
                "dynamic_position_cap",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "extreme",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Execution accepts dynamic size but Kelly analytics are external",
                },
            },
            "runtime_plan": {
                "trigger_id": "kelly_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "cross": "up",
                        "tradePnls": [20, -10, 15, -5, 25, -10],
                        "balance": 1_000,
                        "price": 100,
                    },
                    {
                        "type": "scheduled",
                        "cross": "down",
                        "tradePnls": [20, -10, 15, -5, 25, -10],
                        "balance": 1_000,
                        "price": 100,
                    },
                ],
                "assertions": {"min_market_orders": 2},
            },
        }
    )

    # 20) Ensemble portfolio
    spec = base_spec("s20-ensemble", "Multi-Coin Trend + Mean Reversion Ensemble")
    spec["variables"] = {"maxBudget": 200, "baseNotional": 20, "maxNotional": 60}
    spec["initial_state"] = {"executed": []}
    spec["triggers"] = [
        {
            "id": "ensemble_tick",
            "type": "scheduled",
            "intervalMs": 15 * 60 * 1000,
            "onTrigger": "ensemble_cycle",
        }
    ]
    spec["workflows"] = {
        "ensemble_cycle": {
            "steps": [
                {
                    "action": "set",
                    "path": "local.remainingNotional",
                    "value": {"ref": "vars.maxBudget"},
                },
                {
                    "action": "for_each",
                    "list": {"ref": "trigger.coins"},
                    "item": "coinData",
                    "steps": [
                        {
                            "action": "set",
                            "path": "local.score",
                            "value": {
                                "op": "add",
                                "args": [
                                    {"op": "mul", "args": [{"ref": "local.coinData.trendScore"}, 0.6]},
                                    {"op": "mul", "args": [{"ref": "local.coinData.meanRevScore"}, 0.4]},
                                ],
                            },
                        },
                        {
                            "action": "if",
                            "condition": {
                                "op": "and",
                                "args": [
                                    {"op": "gte", "args": [{"op": "abs", "args": [{"ref": "local.score"}]}, 0.6]},
                                    {"op": "gt", "args": [{"ref": "local.remainingNotional"}, 0]},
                                ],
                            },
                            "then": [
                                {
                                    "action": "set",
                                    "path": "local.notional",
                                    "value": {
                                        "op": "min",
                                        "args": [
                                            {"ref": "vars.maxNotional"},
                                            {
                                                "op": "add",
                                                "args": [
                                                    {"ref": "vars.baseNotional"},
                                                    {
                                                        "op": "mul",
                                                        "args": [
                                                            {
                                                                "op": "div",
                                                                "args": [
                                                                    {"op": "sub", "args": [{"op": "abs", "args": [{"ref": "local.score"}]}, 0.6]},
                                                                    0.4,
                                                                ],
                                                            },
                                                            40,
                                                        ],
                                                    },
                                                ],
                                            },
                                        ],
                                    },
                                },
                                {
                                    "action": "set",
                                    "path": "local.notional",
                                    "value": {"op": "min", "args": [{"ref": "local.notional"}, {"ref": "local.remainingNotional"}]},
                                },
                                {
                                    "action": "set",
                                    "path": "local.size",
                                    "value": {"op": "div", "args": [{"ref": "local.notional"}, {"ref": "local.coinData.price"}]},
                                },
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": [
                                        {"ref": "local.coinData.coin"},
                                        {"op": "gt", "args": [{"ref": "local.score"}, 0]},
                                        {"ref": "local.size"},
                                    ],
                                },
                                {
                                    "action": "if",
                                    "condition": {"op": "gt", "args": [{"ref": "local.score"}, 0]},
                                    "then": [
                                        {
                                            "action": "call",
                                            "target": "order",
                                            "method": "placeStopLoss",
                                            "args": [
                                                {"ref": "local.coinData.coin"},
                                                False,
                                                {"ref": "local.size"},
                                                {
                                                    "op": "sub",
                                                    "args": [
                                                        {"ref": "local.coinData.price"},
                                                        {"op": "mul", "args": [{"ref": "local.coinData.atr"}, 2]},
                                                    ],
                                                },
                                            ],
                                        }
                                    ],
                                    "else": [
                                        {
                                            "action": "call",
                                            "target": "order",
                                            "method": "placeStopLoss",
                                            "args": [
                                                {"ref": "local.coinData.coin"},
                                                True,
                                                {"ref": "local.size"},
                                                {
                                                    "op": "add",
                                                    "args": [
                                                        {"ref": "local.coinData.price"},
                                                        {"op": "mul", "args": [{"ref": "local.coinData.atr"}, 2]},
                                                    ],
                                                },
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "action": "call",
                                    "target": "state",
                                    "method": "push",
                                    "args": ["state.executed", {"ref": "local.coinData.coin"}],
                                },
                                {
                                    "action": "set",
                                    "path": "local.remainingNotional",
                                    "value": {"op": "sub", "args": [{"ref": "local.remainingNotional"}, {"ref": "local.notional"}]},
                                },
                            ],
                        }
                    ],
                },
            ]
        }
    }
    cases.append(
        {
            "order": 20,
            "id": "s20-ensemble",
            "name": "Multi-Coin Trend + Mean Reversion Ensemble",
            "prompt": "Manage a portfolio of BTC, ETH, SOL, and DOGE. For each coin every 15 min: compute a trend score (EMA 9 vs 21 spread, normalized) and a mean reversion score (RSI 14 distance from 50, normalized). Weight: 60% trend, 40% mean reversion. Enter long if ensemble > 0.6, short if < -0.6. Size proportional to signal strength: stronger signal = bigger position ($20 base, up to $60). Risk budget: max $200 total notional across all coins. Dynamic SL: 2x ATR per coin. 5x leverage.",
            "complexity": "complex",
            "required_features": [
                "per_coin_ensemble_scoring",
                "signal_strength_sizing",
                "portfolio_notional_budget",
                "dynamic_atr_stops",
            ],
            "implemented_features": [
                "per_coin_ensemble_scoring",
                "signal_strength_sizing",
                "portfolio_notional_budget",
                "dynamic_atr_stops",
            ],
            "payload": {
                "strategy_spec": spec,
                "notes": {
                    "complexity": "extreme",
                    "uses_hybrid_patterns": True,
                    "reasoning_summary": "Portfolio budget enforcement with externalized scoring and ATR stop computation",
                },
            },
            "runtime_plan": {
                "trigger_id": "ensemble_tick",
                "events": [
                    {
                        "type": "scheduled",
                        "coins": [
                            {"coin": "BTC", "trendScore": 0.9, "meanRevScore": 0.4, "atr": 2.0, "price": 100},
                            {"coin": "ETH", "trendScore": -0.8, "meanRevScore": -0.5, "atr": 1.8, "price": 100},
                            {"coin": "DOGE", "trendScore": 0.2, "meanRevScore": 0.1, "atr": 0.5, "price": 100},
                        ],
                    }
                ],
                "assertions": {
                    "min_market_orders": 2,
                    "min_stop_loss_orders": 2,
                    "state_array_length": [{"path": "executed", "length": 2}],
                },
            },
        }
    )

    return cases


class MatrixMockProvider:
    def __init__(self, prompt_to_payload: Dict[str, Dict[str, Any]]):
        self.prompt_to_payload = prompt_to_payload
        self.calls = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def generate_with_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        self.calls += 1
        for prompt, payload in self.prompt_to_payload.items():
            if prompt in user_prompt:
                return payload
        raise ValueError("No mocked payload for strategy prompt")


def compute_coverage(required_features: List[str], implemented_features: List[str]) -> Dict[str, Any]:
    required = list(dict.fromkeys(required_features))
    implemented = set(implemented_features)
    missing = [feature for feature in required if feature not in implemented]
    covered = len(required) - len(missing)
    ratio = 1.0 if len(required) == 0 else covered / len(required)
    return {
        "required_count": len(required),
        "covered_count": covered,
        "missing_count": len(missing),
        "ratio": ratio,
        "missing_features": missing,
    }


async def run(output_path: Path) -> None:
    cases = build_cases()

    prompt_to_payload = {case["prompt"]: case["payload"] for case in cases}
    provider = MatrixMockProvider(prompt_to_payload)
    generator = StrategySpecGenerator(provider, validate=True)

    results: List[Dict[str, Any]] = []
    generation_pass = 0

    for case in cases:
        coverage = compute_coverage(case["required_features"], case["implemented_features"])
        row: Dict[str, Any] = {
            "order": case["order"],
            "id": case["id"],
            "name": case["name"],
            "prompt": case["prompt"],
            "complexity": case["complexity"],
            "required_features": case["required_features"],
            "implemented_features": case["implemented_features"],
            "coverage": coverage,
            "runtime_plan": case["runtime_plan"],
            "generation": {
                "status": "pending",
                "error": None,
            },
            "notes": None,
            "strategy_spec": None,
        }

        try:
            generated = await generator.generate_strategy_spec(case["prompt"])
            row["generation"]["status"] = "pass"
            row["notes"] = generated.get("notes", {})
            row["strategy_spec"] = generated["strategy_spec"]
            generation_pass += 1
        except Exception as exc:
            row["generation"]["status"] = "fail"
            row["generation"]["error"] = str(exc)

        results.append(row)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matrix": "spec_generation_pipeline",
        "total_cases": len(results),
        "generation_pass": generation_pass,
        "generation_fail": len(results) - generation_pass,
        "cases": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate strategy spec pipeline matrix artifact")
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output).resolve()
    asyncio.run(run(output_path))
    print(f"[matrix] Wrote generation artifact to {output_path}")


if __name__ == "__main__":
    main()
