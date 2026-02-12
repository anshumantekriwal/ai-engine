import unittest

from strategy_spec_schema import validate_strategy_spec, assert_valid_strategy_spec


def build_valid_spec():
    return {
        "version": "1.0",
        "strategy_id": "unit-rsi-001",
        "name": "Unit RSI",
        "mode": "hybrid",
        "risk": {
            "requireSafetyCheck": True,
            "allowUnsafeOrderMethods": False,
        },
        "triggers": [
            {
                "id": "rsi_trigger",
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
                        "args": ["BTC", True, 0.02],
                    },
                    {
                        "action": "return",
                        "value": {"ref": "trigger.coin"},
                    },
                ]
            }
        },
    }


class StrategySpecSchemaTests(unittest.TestCase):
    def test_valid_spec_passes(self):
        spec = build_valid_spec()
        valid, errors = validate_strategy_spec(spec)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_missing_workflow_reference_fails(self):
        spec = build_valid_spec()
        spec["triggers"][0]["onTrigger"] = "missing"

        valid, errors = validate_strategy_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any(e["path"] == "triggers[0].onTrigger" for e in errors))

    def test_assert_valid_strategy_spec_raises(self):
        spec = build_valid_spec()
        spec["version"] = "2.0"

        with self.assertRaises(ValueError):
            assert_valid_strategy_spec(spec)


if __name__ == "__main__":
    unittest.main()
