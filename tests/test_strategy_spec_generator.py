import unittest

from strategy_spec_generator import StrategySpecGenerator


def build_valid_spec_response():
    return {
        "strategy_spec": {
            "version": "1.0",
            "strategy_id": "gen-rsi-001",
            "name": "Generated RSI",
            "mode": "spec",
            "triggers": [
                {
                    "id": "price_break",
                    "type": "price",
                    "coin": "BTC",
                    "condition": {"above": 100000},
                    "onTrigger": "entry",
                }
            ],
            "workflows": {
                "entry": {
                    "steps": [
                        {
                            "action": "log",
                            "message": "entry trigger",
                        },
                        {
                            "action": "return",
                            "value": "ok",
                        },
                    ]
                }
            },
        },
        "notes": {
            "complexity": "medium",
            "uses_hybrid_patterns": False,
            "reasoning_summary": "basic breakout",
        },
    }


class MockProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def generate_with_json(self, system_prompt, user_prompt):
        self.calls += 1
        return self.response


class MockCodeGenerator:
    def __init__(self):
        self.calls = 0

    async def generate_complete_agent(self, strategy_description):
        self.calls += 1
        return {
            "initialization_code": "console.log('init')",
            "trigger_code": "console.log('triggers')",
            "execution_code": "console.log('execute')",
        }


class StrategySpecGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_strategy_spec_returns_valid_payload(self):
        provider = MockProvider(build_valid_spec_response())
        generator = StrategySpecGenerator(provider, validate=True)

        result = await generator.generate_strategy_spec("buy breakout")

        self.assertIn("strategy_spec", result)
        self.assertEqual(result["strategy_spec"]["strategy_id"], "gen-rsi-001")
        self.assertEqual(provider.calls, 1)

    async def test_generate_hybrid_bundle_can_include_code_fallback(self):
        provider = MockProvider(build_valid_spec_response())
        code_generator = MockCodeGenerator()
        generator = StrategySpecGenerator(provider, validate=True, code_generator=code_generator)

        result = await generator.generate_hybrid_bundle(
            "buy breakout",
            include_code_fallback=True,
        )

        self.assertIsNotNone(result["code_fallback"])
        self.assertEqual(result["code_fallback"]["execution_code"], "console.log('execute')")
        self.assertEqual(code_generator.calls, 1)


if __name__ == "__main__":
    unittest.main()
