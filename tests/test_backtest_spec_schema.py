import unittest

from backtest_spec_schema import assert_valid_backtest_spec, validate_backtest_spec


def build_valid_backtest_spec():
    return {
        "version": "1.0",
        "strategy_id": "btc-rsi-bounce",
        "name": "BTC RSI Bounce",
        "markets": ["BTC"],
        "timeframe": "1h",
        "start_ts": 1735689600000,
        "end_ts": 1767225600000,
        "signals": [
            {
                "id": "rsi_buy",
                "kind": "threshold",
                "indicator": "RSI",
                "period": 14,
                "check_field": "value",
                "operator": "lt",
                "value": 30,
                "action": "buy",
            },
            {
                "id": "rsi_sell",
                "kind": "threshold",
                "indicator": "RSI",
                "period": 14,
                "check_field": "value",
                "operator": "gt",
                "value": 70,
                "action": "sell",
            },
        ],
        "sizing": {"mode": "notional_usd", "value": 100},
        "risk": {
            "leverage": 5,
            "max_positions": 1,
            "min_notional_usd": 10,
            "allow_position_add": True,
            "allow_flip": True,
        },
        "exits": {
            "stop_loss_pct": 0.08,
            "take_profit_pct": 0.12,
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
            "reduce_only_on_exits": True,
        },
        "initial_capital_usd": 10000,
    }


class BacktestSpecSchemaTests(unittest.TestCase):
    def test_valid_spec_passes(self):
        spec = build_valid_backtest_spec()
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_missing_exit_rules_fails(self):
        spec = build_valid_backtest_spec()
        spec["exits"] = {}
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any(error["path"] == "exits" for error in errors))

    def test_duplicate_signal_ids_fail(self):
        spec = build_valid_backtest_spec()
        spec["signals"][1]["id"] = "rsi_buy"
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any(error["path"] == "signals[1].id" for error in errors))

    def test_assert_raises_for_invalid_spec(self):
        spec = build_valid_backtest_spec()
        spec["timeframe"] = "10m"
        with self.assertRaises(ValueError):
            assert_valid_backtest_spec(spec)


if __name__ == "__main__":
    unittest.main()
