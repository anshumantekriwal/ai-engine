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
    # ──────────── Existing tests ────────────

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

    # ──────────── New Indicators ────────────

    def test_atr_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "atr_sig",
                "kind": "threshold",
                "indicator": "ATR",
                "period": 14,
                "check_field": "value",
                "operator": "gt",
                "value": 100,
                "action": "buy",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_adx_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "adx_sig",
                "kind": "threshold",
                "indicator": "ADX",
                "period": 14,
                "check_field": "adx",
                "operator": "gt",
                "value": 25,
                "action": "buy",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_stochastic_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "stoch_sig",
                "kind": "threshold",
                "indicator": "Stochastic",
                "period": 14,
                "signalPeriod": 3,
                "check_field": "k",
                "operator": "lt",
                "value": 20,
                "action": "buy",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_vwap_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "vwap_sig",
                "kind": "threshold",
                "indicator": "VWAP",
                "period": 20,
                "check_field": "vwap",
                "operator": "lt",
                "value": 50000,
                "action": "buy",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    # ──────────── Position PnL Signal ────────────

    def test_position_pnl_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "pnl_buy",
                "kind": "position_pnl",
                "pnl_pct_below": -0.10,
                "action": "buy",
            },
            {
                "id": "pnl_sell",
                "kind": "position_pnl",
                "pnl_pct_above": 0.10,
                "action": "sell",
            },
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_position_pnl_missing_threshold_fails(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "pnl_bad",
                "kind": "position_pnl",
                "action": "buy",
            },
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any("pnl_pct_above" in e["message"] or "pnl_pct_below" in e["message"] for e in errors))

    # ──────────── Ranking Signal ────────────

    def test_ranking_signal_valid(self):
        spec = build_valid_backtest_spec()
        spec["markets"] = ["BTC", "ETH", "SOL"]
        spec["risk"]["max_positions"] = 3
        spec["signals"] = [
            {
                "id": "rank_rotation",
                "kind": "ranking",
                "rank_by": "change_24h",
                "long_top_n": 1,
                "short_bottom_n": 1,
                "rebalance": True,
                "close_before_open": True,
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_ranking_both_zero_fails(self):
        spec = build_valid_backtest_spec()
        spec["signals"] = [
            {
                "id": "rank_bad",
                "kind": "ranking",
                "rank_by": "change_24h",
                "long_top_n": 0,
                "short_bottom_n": 0,
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    # ──────────── Signal Gates ────────────

    def test_signal_gate_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"][0]["gate"] = {
            "cooldown_bars": 5,
            "max_total_fires": 10,
            "requires_no_position": True,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_signal_gate_mutually_exclusive_fails(self):
        spec = build_valid_backtest_spec()
        spec["signals"][0]["gate"] = {
            "requires_no_position": True,
            "requires_position": True,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any("requires_no_position" in e["message"] for e in errors))

    # ──────────── Conditions ────────────

    def test_conditions_valid(self):
        spec = build_valid_backtest_spec()
        spec["conditions"] = [
            {
                "id": "buy_cond",
                "operator": "and",
                "clauses": [
                    {"type": "indicator_compare", "indicator": "RSI:14", "field": "value", "operator": "lt", "value": 30},
                    {"type": "volume_compare", "volume_ratio_above": 1.5, "volume_lookback": 20},
                ],
                "action": "buy",
                "priority": 10,
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_condition_invalid_clause_type_fails(self):
        spec = build_valid_backtest_spec()
        spec["conditions"] = [
            {
                "id": "bad_cond",
                "operator": "and",
                "clauses": [
                    {"type": "invalid_type"},
                ],
                "action": "buy",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    def test_condition_position_state_clause(self):
        spec = build_valid_backtest_spec()
        spec["conditions"] = [
            {
                "id": "pos_cond",
                "operator": "and",
                "clauses": [
                    {"type": "position_state", "has_position": True, "position_pnl_pct_above": 0.05},
                ],
                "action": "sell",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_condition_duplicate_id_fails(self):
        spec = build_valid_backtest_spec()
        spec["conditions"] = [
            {"id": "dup", "operator": "and", "clauses": [{"type": "signal_active", "signal_id": "rsi_buy"}], "action": "buy"},
            {"id": "dup", "operator": "or", "clauses": [{"type": "signal_active", "signal_id": "rsi_sell"}], "action": "sell"},
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    # ──────────── Hooks ────────────

    def test_hooks_valid(self):
        spec = build_valid_backtest_spec()
        spec["hooks"] = [
            {
                "id": "grid_engine",
                "trigger": "per_bar",
                "code": "return { intents: [], stateDelta: {} };",
                "timeout_ms": 100,
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_hook_invalid_trigger_fails(self):
        spec = build_valid_backtest_spec()
        spec["hooks"] = [
            {
                "id": "bad_hook",
                "trigger": "on_invalid",
                "code": "return {};",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    def test_hook_empty_code_fails(self):
        spec = build_valid_backtest_spec()
        spec["hooks"] = [
            {
                "id": "empty_hook",
                "trigger": "per_bar",
                "code": "",
            }
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    def test_hook_duplicate_id_fails(self):
        spec = build_valid_backtest_spec()
        spec["hooks"] = [
            {"id": "h1", "trigger": "per_bar", "code": "return {};"},
            {"id": "h1", "trigger": "per_bar", "code": "return {};"},
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    # ──────────── Sizing Modes ────────────

    def test_risk_based_sizing_valid(self):
        spec = build_valid_backtest_spec()
        spec["sizing"] = {
            "mode": "risk_based",
            "value": 100,
            "risk_per_trade_usd": 50,
            "sl_atr_multiple": 2,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_risk_based_missing_required_fails(self):
        spec = build_valid_backtest_spec()
        spec["sizing"] = {
            "mode": "risk_based",
            "value": 100,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        paths = [e["path"] for e in errors]
        self.assertIn("sizing.risk_per_trade_usd", paths)
        self.assertIn("sizing.sl_atr_multiple", paths)

    def test_kelly_sizing_valid(self):
        spec = build_valid_backtest_spec()
        spec["sizing"] = {
            "mode": "kelly",
            "value": 100,
            "kelly_fraction": 0.5,
            "kelly_lookback_trades": 20,
            "kelly_min_trades": 15,
            "max_balance_pct": 0.25,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_kelly_missing_fraction_fails(self):
        spec = build_valid_backtest_spec()
        spec["sizing"] = {
            "mode": "kelly",
            "value": 100,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any("kelly_fraction" in e["path"] for e in errors))

    def test_signal_proportional_sizing_valid(self):
        spec = build_valid_backtest_spec()
        spec["sizing"] = {
            "mode": "signal_proportional",
            "value": 100,
            "base_notional_usd": 50,
            "max_notional_usd": 200,
        }
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    # ──────────── Portfolio Risk ────────────

    def test_portfolio_risk_fields_valid(self):
        spec = build_valid_backtest_spec()
        spec["risk"]["max_total_notional_usd"] = 5000
        spec["risk"]["max_total_margin_usd"] = 2000
        spec["risk"]["maintenance_margin_rate"] = 0.5
        spec["risk"]["independent_sub_positions"] = True
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_invalid_maintenance_margin_rate_fails(self):
        spec = build_valid_backtest_spec()
        spec["risk"]["maintenance_margin_rate"] = 1.5
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)
        self.assertTrue(any("maintenance_margin_rate" in e["path"] for e in errors))

    # ──────────── Auxiliary Timeframes ────────────

    def test_auxiliary_timeframes_valid(self):
        spec = build_valid_backtest_spec()
        spec["auxiliary_timeframes"] = [
            {"timeframe": "4h", "markets": ["BTC"]},
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_auxiliary_timeframes_invalid_tf_fails(self):
        spec = build_valid_backtest_spec()
        spec["auxiliary_timeframes"] = [
            {"timeframe": "invalid", "markets": ["BTC"]},
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    def test_auxiliary_timeframes_empty_markets_fails(self):
        spec = build_valid_backtest_spec()
        spec["auxiliary_timeframes"] = [
            {"timeframe": "4h", "markets": []},
        ]
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)

    # ──────────── Threshold with timeframe (multi-TF) ────────────

    def test_threshold_with_timeframe_valid(self):
        spec = build_valid_backtest_spec()
        spec["signals"][0]["timeframe"] = "4h"
        valid, errors = validate_backtest_spec(spec)
        self.assertTrue(valid, msg=errors)

    def test_threshold_with_invalid_timeframe_fails(self):
        spec = build_valid_backtest_spec()
        spec["signals"][0]["timeframe"] = "99m"
        valid, errors = validate_backtest_spec(spec)
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
