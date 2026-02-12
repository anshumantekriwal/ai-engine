import unittest

from backtest_spec_generator import BacktestSpecGenerator
from backtest_spec_schema import validate_backtest_spec


class MockProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def generate_with_json(self, *, system_prompt=None, user_prompt=None):
        self.calls += 1
        return self.response


def build_minimal_response():
    return {
        "strategy_spec": {
            "strategy_id": "ema-breakout",
            "name": "EMA Breakout",
            "markets": ["eth-perp"],
            "timeframe": "60m",
            "signals": [
                {
                    "id": "cross",
                    "kind": "crossover",
                    "fast": {"indicator": "EMA", "period": 9},
                    "slow": {"indicator": "EMA", "period": 21},
                    "direction": "both",
                    "action_on_bullish": "buy",
                    "action_on_bearish": "sell",
                }
            ],
            "sizing": {"mode": "notional_usd", "value": 250},
            "risk": {"leverage": 7, "max_positions": 1},
            "exits": {"stop_loss_pct": 8, "take_profit_pct": 12},
            "execution": {
                "entry_order_type": "ioc",
                "slippage_bps": 3,
            },
        },
        "notes": {
            "complexity": "medium",
            "reasoning_summary": "EMA crossover mapping.",
            "assumptions": ["Using default lookback."],
            "unsupported_features": [],
            "mapping_confidence": 0.88,
        },
    }


class BacktestSpecGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_generator_normalizes_and_validates_output(self):
        provider = MockProvider(build_minimal_response())
        generator = BacktestSpecGenerator(provider, validate=True)

        result = await generator.generate_backtest_spec("EMA 9/21 crossover on ETH 1h.")

        self.assertEqual(provider.calls, 1)
        self.assertIn("strategy_spec", result)
        self.assertIn("notes", result)

        spec = result["strategy_spec"]
        self.assertEqual(spec["version"], "1.0")
        self.assertEqual(spec["markets"], ["ETH"])
        self.assertEqual(spec["timeframe"], "1h")
        self.assertAlmostEqual(spec["exits"]["stop_loss_pct"], 0.08)
        self.assertAlmostEqual(spec["exits"]["take_profit_pct"], 0.12)
        self.assertEqual(spec["execution"]["entry_order_type"], "Ioc")
        self.assertGreater(spec["end_ts"], spec["start_ts"])

        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    async def test_generator_enriches_notes_with_normalization_assumptions(self):
        provider = MockProvider(build_minimal_response())
        generator = BacktestSpecGenerator(provider, validate=True)

        result = await generator.generate_backtest_spec("EMA 9/21 crossover on ETH 1h.")

        assumptions = result["notes"]["assumptions"]
        self.assertTrue(isinstance(assumptions, list))
        self.assertTrue(any("defaulted" in item.lower() or "normalized" in item.lower() for item in assumptions))


if __name__ == "__main__":
    unittest.main()
