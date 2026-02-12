"""
Validation utilities for the backtest-tool strategy_spec contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

SUPPORTED_VERSION = "1.0"
TIMEFRAMES = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}
SIGNAL_KINDS = {"threshold", "crossover", "price", "scheduled"}
INDICATORS = {"RSI", "EMA", "SMA", "MACD", "BollingerBands"}
CHECK_FIELDS = {"value", "MACD", "signal", "histogram", "upper", "middle", "lower"}
THRESHOLD_OPERATORS = {"lt", "lte", "gt", "gte"}
ACTIONS = {"buy", "sell"}
SIZING_MODES = {"notional_usd", "margin_usd", "equity_pct", "base_units"}
ENTRY_ORDER_TYPES = {"market", "limit", "Ioc", "Gtc", "Alo"}
EXIT_ORDER_TYPES = {"market", "limit"}
TRIGGER_TYPES = {"mark", "last", "oracle"}


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _add_error(errors: List[Dict[str, str]], path: str, message: str) -> None:
    errors.append({"path": path, "message": message})


def _require_positive_number(
    spec: Dict[str, Any],
    key: str,
    errors: List[Dict[str, str]],
    path_prefix: str = "",
) -> None:
    path = f"{path_prefix}{key}"
    value = spec.get(key)
    if not _is_number(value) or float(value) <= 0:
        _add_error(errors, path, "must be a positive number")


def _require_nonnegative_number(
    spec: Dict[str, Any],
    key: str,
    errors: List[Dict[str, str]],
    path_prefix: str = "",
) -> None:
    path = f"{path_prefix}{key}"
    value = spec.get(key)
    if not _is_number(value) or float(value) < 0:
        _add_error(errors, path, "must be a non-negative number")


def _validate_threshold_signal(signal: Dict[str, Any], idx: int, errors: List[Dict[str, str]]) -> None:
    path = f"signals[{idx}]"

    indicator = signal.get("indicator")
    if indicator not in INDICATORS:
        _add_error(errors, f"{path}.indicator", f"must be one of: {sorted(INDICATORS)}")

    check_field = signal.get("check_field", "value")
    if check_field not in CHECK_FIELDS:
        _add_error(errors, f"{path}.check_field", f"must be one of: {sorted(CHECK_FIELDS)}")

    if signal.get("operator") not in THRESHOLD_OPERATORS:
        _add_error(errors, f"{path}.operator", f"must be one of: {sorted(THRESHOLD_OPERATORS)}")

    if not _is_number(signal.get("value")):
        _add_error(errors, f"{path}.value", "must be a number")

    if signal.get("action") not in ACTIONS:
        _add_error(errors, f"{path}.action", f"must be one of: {sorted(ACTIONS)}")

    if indicator == "MACD":
        for key in ("fastPeriod", "slowPeriod", "signalPeriod"):
            value = signal.get(key)
            if not isinstance(value, int) or value <= 0:
                _add_error(errors, f"{path}.{key}", "must be a positive integer for MACD signals")
        return

    if indicator == "BollingerBands":
        period = signal.get("period")
        if not isinstance(period, int) or period <= 0:
            _add_error(errors, f"{path}.period", "must be a positive integer for BollingerBands signals")
        std_dev = signal.get("stdDev")
        if not _is_number(std_dev) or float(std_dev) <= 0:
            _add_error(errors, f"{path}.stdDev", "must be a positive number for BollingerBands signals")
        return

    period = signal.get("period")
    if not isinstance(period, int) or period <= 0:
        _add_error(errors, f"{path}.period", "must be a positive integer")


def _validate_crossover_signal(signal: Dict[str, Any], idx: int, errors: List[Dict[str, str]]) -> None:
    path = f"signals[{idx}]"

    for leg in ("fast", "slow"):
        leg_obj = signal.get(leg)
        if not _is_dict(leg_obj):
            _add_error(errors, f"{path}.{leg}", "must be an object")
            continue
        if leg_obj.get("indicator") not in {"EMA", "SMA"}:
            _add_error(errors, f"{path}.{leg}.indicator", "must be one of: ['EMA', 'SMA']")
        period = leg_obj.get("period")
        if not isinstance(period, int) or period <= 0:
            _add_error(errors, f"{path}.{leg}.period", "must be a positive integer")

    if signal.get("direction") not in {"bullish", "bearish", "both"}:
        _add_error(errors, f"{path}.direction", "must be one of: ['bullish', 'bearish', 'both']")

    if signal.get("action_on_bullish") not in ACTIONS:
        _add_error(errors, f"{path}.action_on_bullish", f"must be one of: {sorted(ACTIONS)}")
    if signal.get("action_on_bearish") not in ACTIONS:
        _add_error(errors, f"{path}.action_on_bearish", f"must be one of: {sorted(ACTIONS)}")


def _validate_price_signal(signal: Dict[str, Any], idx: int, errors: List[Dict[str, str]]) -> None:
    path = f"signals[{idx}]"
    condition = signal.get("condition")
    if not _is_dict(condition):
        _add_error(errors, f"{path}.condition", "must be an object")
    else:
        if all(key not in condition for key in ("above", "below", "crosses")):
            _add_error(errors, f"{path}.condition", "must include at least one of above/below/crosses")
        for key in ("above", "below", "crosses"):
            if key in condition and (not _is_number(condition[key]) or float(condition[key]) <= 0):
                _add_error(errors, f"{path}.condition.{key}", "must be a positive number")

    if signal.get("action") not in ACTIONS:
        _add_error(errors, f"{path}.action", f"must be one of: {sorted(ACTIONS)}")


def _validate_scheduled_signal(signal: Dict[str, Any], idx: int, errors: List[Dict[str, str]]) -> None:
    path = f"signals[{idx}]"
    every_n_bars = signal.get("every_n_bars")
    if not isinstance(every_n_bars, int) or every_n_bars <= 0:
        _add_error(errors, f"{path}.every_n_bars", "must be a positive integer")
    if signal.get("action") not in ACTIONS:
        _add_error(errors, f"{path}.action", f"must be one of: {sorted(ACTIONS)}")


def _validate_signals(signals: Any, errors: List[Dict[str, str]]) -> None:
    if not isinstance(signals, list) or len(signals) == 0:
        _add_error(errors, "signals", "must be a non-empty list")
        return

    seen_ids = set()
    for idx, signal in enumerate(signals):
        path = f"signals[{idx}]"
        if not _is_dict(signal):
            _add_error(errors, path, "must be an object")
            continue

        signal_id = signal.get("id")
        if not isinstance(signal_id, str) or not signal_id.strip():
            _add_error(errors, f"{path}.id", "must be a non-empty string")
        elif signal_id in seen_ids:
            _add_error(errors, f"{path}.id", f"duplicate signal id: {signal_id}")
        else:
            seen_ids.add(signal_id)

        kind = signal.get("kind")
        if kind not in SIGNAL_KINDS:
            _add_error(errors, f"{path}.kind", f"must be one of: {sorted(SIGNAL_KINDS)}")
            continue

        if kind == "threshold":
            _validate_threshold_signal(signal, idx, errors)
        elif kind == "crossover":
            _validate_crossover_signal(signal, idx, errors)
        elif kind == "price":
            _validate_price_signal(signal, idx, errors)
        elif kind == "scheduled":
            _validate_scheduled_signal(signal, idx, errors)


def _validate_exits(exits: Any, errors: List[Dict[str, str]]) -> None:
    if not _is_dict(exits):
        _add_error(errors, "exits", "must be an object")
        return

    for key in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct"):
        if key in exits:
            value = exits.get(key)
            if not _is_number(value) or float(value) <= 0 or float(value) > 1:
                _add_error(errors, f"exits.{key}", "must be a number in (0, 1]")

    if "max_hold_bars" in exits:
        value = exits.get("max_hold_bars")
        if not isinstance(value, int) or value <= 0:
            _add_error(errors, "exits.max_hold_bars", "must be a positive integer")

    if "move_stop_to_break_even_after_tp" in exits and not isinstance(
        exits.get("move_stop_to_break_even_after_tp"), bool
    ):
        _add_error(errors, "exits.move_stop_to_break_even_after_tp", "must be a boolean")

    partials = exits.get("partial_take_profit_levels")
    if partials is not None:
        if not isinstance(partials, list):
            _add_error(errors, "exits.partial_take_profit_levels", "must be a list")
        else:
            close_sum = 0.0
            for idx, level in enumerate(partials):
                path = f"exits.partial_take_profit_levels[{idx}]"
                if not _is_dict(level):
                    _add_error(errors, path, "must be an object")
                    continue
                profit_pct = level.get("profit_pct")
                close_fraction = level.get("close_fraction")
                if not _is_number(profit_pct) or float(profit_pct) <= 0 or float(profit_pct) > 1:
                    _add_error(errors, f"{path}.profit_pct", "must be a number in (0, 1]")
                if not _is_number(close_fraction) or float(close_fraction) <= 0 or float(close_fraction) > 1:
                    _add_error(errors, f"{path}.close_fraction", "must be a number in (0, 1]")
                if _is_number(close_fraction):
                    close_sum += float(close_fraction)
            if close_sum > 1.000001:
                _add_error(errors, "exits.partial_take_profit_levels", "sum(close_fraction) cannot exceed 1.0")

    has_primary_exit = any(key in exits for key in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct"))
    has_partials = isinstance(partials, list) and len(partials) > 0
    if not has_primary_exit and not has_partials:
        _add_error(
            errors,
            "exits",
            "at least one exit rule is required (stop_loss_pct, take_profit_pct, trailing_stop_pct, or partial_take_profit_levels)",
        )


def _validate_execution(execution: Any, errors: List[Dict[str, str]]) -> None:
    if not _is_dict(execution):
        _add_error(errors, "execution", "must be an object")
        return

    if execution.get("entry_order_type") not in ENTRY_ORDER_TYPES:
        _add_error(errors, "execution.entry_order_type", f"must be one of: {sorted(ENTRY_ORDER_TYPES)}")

    for key in ("slippage_bps", "maker_fee_rate", "taker_fee_rate"):
        _require_nonnegative_number(execution, key, errors, "execution.")

    if "limit_offset_bps" in execution:
        _require_nonnegative_number(execution, "limit_offset_bps", errors, "execution.")

    if execution.get("stop_order_type") not in EXIT_ORDER_TYPES:
        _add_error(errors, "execution.stop_order_type", f"must be one of: {sorted(EXIT_ORDER_TYPES)}")

    if execution.get("take_profit_order_type") not in EXIT_ORDER_TYPES:
        _add_error(errors, "execution.take_profit_order_type", f"must be one of: {sorted(EXIT_ORDER_TYPES)}")

    for key in ("stop_limit_slippage_pct", "take_profit_limit_slippage_pct"):
        value = execution.get(key)
        if not _is_number(value) or float(value) < 0 or float(value) > 1:
            _add_error(errors, f"execution.{key}", "must be a number in [0, 1]")

    if execution.get("trigger_type") not in TRIGGER_TYPES:
        _add_error(errors, "execution.trigger_type", f"must be one of: {sorted(TRIGGER_TYPES)}")

    if not isinstance(execution.get("reduce_only_on_exits"), bool):
        _add_error(errors, "execution.reduce_only_on_exits", "must be a boolean")


def validate_backtest_spec(spec: Any) -> Tuple[bool, List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []

    if not _is_dict(spec):
        return False, [{"path": "root", "message": "strategy_spec must be an object"}]

    version = spec.get("version")
    if not isinstance(version, str) or not version.strip():
        _add_error(errors, "version", "must be a non-empty string")
    elif version != SUPPORTED_VERSION:
        _add_error(errors, "version", f"must equal {SUPPORTED_VERSION}")

    for field in ("strategy_id", "name"):
        value = spec.get(field)
        if not isinstance(value, str) or not value.strip():
            _add_error(errors, field, "must be a non-empty string")

    markets = spec.get("markets")
    if not isinstance(markets, list) or len(markets) == 0:
        _add_error(errors, "markets", "must be a non-empty list")
    else:
        for idx, market in enumerate(markets):
            if not isinstance(market, str) or not market.strip():
                _add_error(errors, f"markets[{idx}]", "must be a non-empty string")

    timeframe = spec.get("timeframe")
    if timeframe not in TIMEFRAMES:
        _add_error(errors, "timeframe", f"must be one of: {sorted(TIMEFRAMES)}")

    start_ts = spec.get("start_ts")
    end_ts = spec.get("end_ts")
    if not isinstance(start_ts, int) or start_ts <= 0:
        _add_error(errors, "start_ts", "must be a positive integer epoch ms")
    if not isinstance(end_ts, int) or end_ts <= 0:
        _add_error(errors, "end_ts", "must be a positive integer epoch ms")
    if isinstance(start_ts, int) and isinstance(end_ts, int) and end_ts <= start_ts:
        _add_error(errors, "end_ts", "must be greater than start_ts")

    _validate_signals(spec.get("signals"), errors)

    sizing = spec.get("sizing")
    if not _is_dict(sizing):
        _add_error(errors, "sizing", "must be an object")
    else:
        if sizing.get("mode") not in SIZING_MODES:
            _add_error(errors, "sizing.mode", f"must be one of: {sorted(SIZING_MODES)}")
        _require_positive_number(sizing, "value", errors, "sizing.")
        if sizing.get("mode") == "equity_pct" and _is_number(sizing.get("value")) and float(sizing["value"]) > 1:
            _add_error(errors, "sizing.value", "must be <= 1.0 when mode is equity_pct")

    risk = spec.get("risk")
    if not _is_dict(risk):
        _add_error(errors, "risk", "must be an object")
    else:
        _require_positive_number(risk, "leverage", errors, "risk.")
        max_positions = risk.get("max_positions")
        if not isinstance(max_positions, int) or max_positions <= 0:
            _add_error(errors, "risk.max_positions", "must be a positive integer")
        _require_positive_number(risk, "min_notional_usd", errors, "risk.")
        if "daily_loss_limit_usd" in risk:
            _require_positive_number(risk, "daily_loss_limit_usd", errors, "risk.")
        if "max_position_notional_usd" in risk:
            _require_positive_number(risk, "max_position_notional_usd", errors, "risk.")
        if "allow_position_add" in risk and not isinstance(risk.get("allow_position_add"), bool):
            _add_error(errors, "risk.allow_position_add", "must be a boolean")
        if "allow_flip" in risk and not isinstance(risk.get("allow_flip"), bool):
            _add_error(errors, "risk.allow_flip", "must be a boolean")

    _validate_exits(spec.get("exits"), errors)
    _validate_execution(spec.get("execution"), errors)

    if "initial_capital_usd" in spec:
        if not _is_number(spec.get("initial_capital_usd")) or float(spec["initial_capital_usd"]) <= 0:
            _add_error(errors, "initial_capital_usd", "must be a positive number")

    if "seed" in spec:
        if not isinstance(spec.get("seed"), int):
            _add_error(errors, "seed", "must be an integer")

    return len(errors) == 0, errors


def assert_valid_backtest_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    valid, errors = validate_backtest_spec(spec)
    if not valid:
        detail = "; ".join([f"{item['path']}: {item['message']}" for item in errors])
        raise ValueError(f"Invalid backtest strategy_spec: {detail}")
    return spec
