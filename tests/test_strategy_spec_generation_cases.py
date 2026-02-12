import unittest

from strategy_spec_generator import StrategySpecGenerator


STRATEGY_CASES = {
    "RSI oversold bounce": {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "rsi-oversold-bounce",
            "name": "RSI Oversold Bounce",
            "mode": "hybrid",
            "risk": {"requireSafetyCheck": True, "allowUnsafeOrderMethods": False},
            "triggers": [
                {
                    "id": "rsi_buy",
                    "type": "technical",
                    "coin": "BTC",
                    "indicator": "RSI",
                    "params": {"period": 14, "interval": "1h"},
                    "condition": {"below": 30},
                    "onTrigger": "entry",
                }
            ],
            "workflows": {
                "entry": {
                    "steps": [
                        {
                            "action": "call",
                            "target": "order",
                            "method": "placeMarketOrder",
                            "args": ["BTC", True, 0.2],
                        }
                    ]
                }
            },
        },
        "notes": {
            "complexity": "simple",
            "uses_hybrid_patterns": False,
            "reasoning_summary": "single trigger to order",
        },
    },
    "DCA every 4 hours": {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "dca-4h",
            "name": "DCA Every 4 Hours",
            "mode": "spec",
            "variables": {"maxBuys": 10},
            "risk": {"requireSafetyCheck": True, "allowUnsafeOrderMethods": False},
            "triggers": [
                {
                    "id": "dca_tick",
                    "type": "scheduled",
                    "intervalMs": 14400000,
                    "onTrigger": "cycle",
                }
            ],
            "workflows": {
                "cycle": {
                    "steps": [
                        {"action": "set", "path": "state.buyCount", "value": {"op": "coalesce", "args": [{"ref": "state.buyCount"}, 0]}},
                        {"action": "return", "value": {"ref": "state.buyCount"}},
                    ]
                }
            },
        },
        "notes": {
            "complexity": "simple",
            "uses_hybrid_patterns": False,
            "reasoning_summary": "scheduled accumulation",
        },
    },
    "EMA crossover momentum": {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "ema-crossover",
            "name": "EMA Crossover Momentum",
            "mode": "hybrid",
            "risk": {"requireSafetyCheck": True, "allowUnsafeOrderMethods": False},
            "triggers": [
                {
                    "id": "ema_cycle",
                    "type": "scheduled",
                    "intervalMs": 60000,
                    "onTrigger": "analyze",
                }
            ],
            "workflows": {
                "analyze": {
                    "steps": [
                        {
                            "action": "if",
                            "condition": {
                                "op": "crosses_above",
                                "args": [{"ref": "state.prevSpread"}, {"ref": "trigger.spread"}, 0],
                            },
                            "then": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": ["SOL", True, 0.2],
                                }
                            ],
                        }
                    ]
                }
            },
        },
        "notes": {
            "complexity": "medium",
            "uses_hybrid_patterns": True,
            "reasoning_summary": "scheduled crossover with state",
        },
    },
    "Funding carry strategy": {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "funding-carry",
            "name": "Funding Carry",
            "mode": "hybrid",
            "variables": {"shortThreshold": 0.01},
            "risk": {"requireSafetyCheck": True, "allowUnsafeOrderMethods": False},
            "triggers": [
                {
                    "id": "funding_tick",
                    "type": "scheduled",
                    "intervalMs": 900000,
                    "onTrigger": "funding_eval",
                }
            ],
            "workflows": {
                "funding_eval": {
                    "steps": [
                        {
                            "action": "call",
                            "target": "market",
                            "method": "getPredictedFundings",
                            "assign": "results.funding",
                        },
                        {"action": "return", "value": {"ref": "results.funding"}},
                    ]
                }
            },
        },
        "notes": {
            "complexity": "medium",
            "uses_hybrid_patterns": True,
            "reasoning_summary": "market data polling",
        },
    },
    "Portfolio rotation top performers": {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "portfolio-rotation",
            "name": "Portfolio Rotation",
            "mode": "hybrid",
            "risk": {"requireSafetyCheck": True, "allowUnsafeOrderMethods": False},
            "triggers": [
                {
                    "id": "rotation_tick",
                    "type": "scheduled",
                    "intervalMs": 28800000,
                    "onTrigger": "rotate",
                }
            ],
            "workflows": {
                "rotate": {
                    "steps": [
                        {
                            "action": "for_each",
                            "list": {"ref": "trigger.targets"},
                            "item": "coin",
                            "steps": [
                                {
                                    "action": "call",
                                    "target": "order",
                                    "method": "placeMarketOrder",
                                    "args": [{"ref": "local.coin"}, True, 0.11],
                                }
                            ],
                        }
                    ]
                }
            },
        },
        "notes": {
            "complexity": "high",
            "uses_hybrid_patterns": True,
            "reasoning_summary": "loop-based multi-asset workflow",
        },
    },
}


class MockProvider:
    def __init__(self, cases):
        self.cases = cases
        self.calls = 0

    async def generate(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def generate_with_json(self, system_prompt, user_prompt):
        self.calls += 1
        for prompt, payload in self.cases.items():
            if prompt in user_prompt:
                return payload
        raise ValueError("No mocked payload for prompt")


class StrategySpecGenerationCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_strategy_prompts_generate_valid_specs(self):
        provider = MockProvider(STRATEGY_CASES)
        generator = StrategySpecGenerator(provider, validate=True)

        for prompt, payload in STRATEGY_CASES.items():
            result = await generator.generate_strategy_spec(prompt)
            self.assertEqual(result["strategy_spec"]["strategy_id"], payload["strategy_spec"]["strategy_id"])
            self.assertIn("notes", result)

        self.assertEqual(provider.calls, len(STRATEGY_CASES))


if __name__ == "__main__":
    unittest.main()
