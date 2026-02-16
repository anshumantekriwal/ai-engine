"""
Backtest strategy spec generator for candle-based backtesting runtime.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import json as _json
import logging

from ai_providers import AIProvider
from backtest_spec_prompts import BACKTEST_SPEC_GENERATION_PROMPT, BACKTEST_SPEC_SYSTEM_PROMPT
from backtest_spec_schema import assert_valid_backtest_spec, validate_backtest_spec

logger = logging.getLogger(__name__)

# Maximum correction passes when the LLM output fails schema validation
MAX_CORRECTION_ATTEMPTS = 2

TIMEFRAME_ALIASES = {
    "1m": "1m",
    "1min": "1m",
    "1minute": "1m",
    "3m": "3m",
    "3min": "3m",
    "5m": "5m",
    "5min": "5m",
    "15m": "15m",
    "15min": "15m",
    "30m": "30m",
    "30min": "30m",
    "60m": "1h",
    "1h": "1h",
    "1hr": "1h",
    "hourly": "1h",
    "2h": "2h",
    "4h": "4h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "daily": "1d",
    "3d": "3d",
    "1w": "1w",
    "weekly": "1w",
    "1mo": "1M",
    "1month": "1M",
    "1mth": "1M",
}

LOOKBACK_DAYS_BY_TIMEFRAME = {
    "1m": 60,
    "3m": 60,
    "5m": 90,
    "15m": 120,
    "30m": 180,
    "1h": 365,
    "2h": 365,
    "4h": 365,
    "8h": 365,
    "12h": 365,
    "1d": 730,
    "3d": 730,
    "1w": 1095,
    "1M": 1460,
}

ENTRY_ORDER_ALIASES = {
    "market": "market",
    "limit": "limit",
    "ioc": "Ioc",
    "gtc": "Gtc",
    "alo": "Alo",
}


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            if "." in stripped:
                num = float(stripped)
                if num.is_integer():
                    return int(num)
                return None
            return int(stripped)
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.endswith("%"):
            stripped = stripped[:-1]
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _sanitize_kebab(value: str, fallback: str = "generated-strategy") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or fallback


def _normalize_timeframe(value: Any) -> str:
    if isinstance(value, str):
        normalized = TIMEFRAME_ALIASES.get(value.strip().lower())
        if normalized:
            return normalized
    return "1h"


def _normalize_market(symbol: Any) -> Optional[str]:
    if not isinstance(symbol, str):
        return None
    cleaned = symbol.strip().upper()
    if not cleaned:
        return None
    cleaned = cleaned.replace("-PERP", "").replace("PERP", "").strip("-_ ")
    if not cleaned:
        return None
    return cleaned


def _normalize_market_list(value: Any) -> List[str]:
    symbols: List[str] = []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        parts = value
    else:
        parts = []

    seen = set()
    for part in parts:
        normalized = _normalize_market(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        symbols.append(normalized)
    return symbols


def _pct_ratio(value: Any) -> Any:
    numeric = _to_float(value)
    if numeric is None:
        return value
    if numeric > 1 and numeric <= 100:
        return numeric / 100.0
    return numeric


def _normalize_order_type(value: Any, fallback: str = "market") -> str:
    if isinstance(value, str):
        mapped = ENTRY_ORDER_ALIASES.get(value.strip().lower())
        if mapped:
            return mapped
    return fallback


def _infer_signal_kind(signal: Dict[str, Any]) -> str:
    if "kind" in signal and isinstance(signal["kind"], str):
        kind = signal["kind"].strip().lower()
        # Normalize aliases
        if kind in {"position_pnl", "pnl", "positionpnl"}:
            return "position_pnl"
        if kind in {"ranking", "rank"}:
            return "ranking"
        return kind
    if "pnl_pct_above" in signal or "pnl_pct_below" in signal:
        return "position_pnl"
    if "rank_by" in signal:
        return "ranking"
    if "indicator" in signal and "operator" in signal:
        return "threshold"
    if "fast" in signal and "slow" in signal:
        return "crossover"
    if "condition" in signal:
        return "price"
    if "every_n_bars" in signal or "intervalMs" in signal:
        return "scheduled"
    return "threshold"


def _normalize_indicator(value: Any) -> str:
    if not isinstance(value, str):
        return "RSI"
    raw = value.strip()
    upper = raw.upper()
    if upper in {"RSI", "EMA", "SMA", "MACD", "ATR", "ADX", "VWAP"}:
        return upper
    if upper in {"BOLLINGERBANDS", "BOLLINGER_BANDS", "BBANDS", "BOLLINGER"}:
        return "BollingerBands"
    if upper in {"STOCHASTIC", "STOCH", "STOCHASTICS"}:
        return "Stochastic"
    return raw


def _normalize_signal_action(value: Any, fallback: str = "buy") -> str:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"buy", "long"}:
            return "buy"
        if lower in {"sell", "short"}:
            return "sell"
    return fallback


def _normalize_gate(gate: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a signal gate object."""
    normalized: Dict[str, Any] = {}
    cooldown = _to_int(gate.get("cooldown_bars"))
    if cooldown and cooldown > 0:
        normalized["cooldown_bars"] = cooldown
    max_fires = _to_int(gate.get("max_total_fires"))
    if max_fires and max_fires > 0:
        normalized["max_total_fires"] = max_fires
    if "requires_no_position" in gate:
        normalized["requires_no_position"] = _to_bool(gate["requires_no_position"], False)
    if "requires_position" in gate:
        normalized["requires_position"] = _to_bool(gate["requires_position"], False)
    return normalized


def _normalize_signals(signals: Any, timeframe: str) -> List[Dict[str, Any]]:
    if not isinstance(signals, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for idx, raw in enumerate(signals):
        if not isinstance(raw, dict):
            continue
        signal = copy.deepcopy(raw)
        signal_id = signal.get("id")
        if not isinstance(signal_id, str) or not signal_id.strip():
            signal["id"] = f"signal_{idx + 1}"

        kind = _infer_signal_kind(signal)
        signal["kind"] = kind

        if kind == "threshold":
            signal["indicator"] = _normalize_indicator(signal.get("indicator", "RSI"))
            signal["check_field"] = str(signal.get("check_field", "value"))
            signal["operator"] = str(signal.get("operator", "lt")).lower()
            signal["action"] = _normalize_signal_action(signal.get("action"), fallback="buy")
            # Period-based indicators
            if signal["indicator"] in {"RSI", "EMA", "SMA", "BollingerBands", "ATR", "ADX", "VWAP", "Stochastic"}:
                period = _to_int(signal.get("period"))
                signal["period"] = period if period and period > 0 else 14
            if signal["indicator"] == "BollingerBands":
                std_dev = _to_float(signal.get("stdDev"))
                signal["stdDev"] = std_dev if std_dev and std_dev > 0 else 2
            if signal["indicator"] == "MACD":
                fp = _to_int(signal.get("fastPeriod"))
                sp = _to_int(signal.get("slowPeriod"))
                sigp = _to_int(signal.get("signalPeriod"))
                signal["fastPeriod"] = fp if fp and fp > 0 else 12
                signal["slowPeriod"] = sp if sp and sp > 0 else 26
                signal["signalPeriod"] = sigp if sigp and sigp > 0 else 9
            if signal["indicator"] == "Stochastic":
                sigp = _to_int(signal.get("signalPeriod"))
                if sigp and sigp > 0:
                    signal["signalPeriod"] = sigp
            value = _to_float(signal.get("value"))
            signal["value"] = value if value is not None else 0.0
            # Normalize optional gate (pass through if dict)
            if "gate" in signal and isinstance(signal["gate"], dict):
                signal["gate"] = _normalize_gate(signal["gate"])
            # Normalize optional timeframe for multi-TF
            if "timeframe" in signal:
                signal["timeframe"] = _normalize_timeframe(signal["timeframe"])

        elif kind == "crossover":
            fast = signal.get("fast") if isinstance(signal.get("fast"), dict) else {}
            slow = signal.get("slow") if isinstance(signal.get("slow"), dict) else {}
            signal["fast"] = {
                "indicator": "EMA" if str(fast.get("indicator", "EMA")).upper() != "SMA" else "SMA",
                "period": max(1, _to_int(fast.get("period")) or 9),
            }
            signal["slow"] = {
                "indicator": "EMA" if str(slow.get("indicator", "EMA")).upper() != "SMA" else "SMA",
                "period": max(1, _to_int(slow.get("period")) or 21),
            }
            direction = str(signal.get("direction", "both")).lower()
            signal["direction"] = direction if direction in {"bullish", "bearish", "both"} else "both"
            signal["action_on_bullish"] = _normalize_signal_action(signal.get("action_on_bullish"), "buy")
            signal["action_on_bearish"] = _normalize_signal_action(signal.get("action_on_bearish"), "sell")

        elif kind == "price":
            condition = signal.get("condition") if isinstance(signal.get("condition"), dict) else {}
            normalized_condition: Dict[str, float] = {}
            for key in ("above", "below", "crosses"):
                number = _to_float(condition.get(key))
                if number is not None and number > 0:
                    normalized_condition[key] = number
            signal["condition"] = normalized_condition
            signal["action"] = _normalize_signal_action(signal.get("action"), fallback="buy")

        elif kind == "scheduled":
            every_n_bars = _to_int(signal.get("every_n_bars"))
            if not every_n_bars or every_n_bars <= 0:
                interval_ms = _to_int(signal.get("intervalMs"))
                if interval_ms and interval_ms > 0:
                    tf_minutes = {
                        "1m": 1,
                        "3m": 3,
                        "5m": 5,
                        "15m": 15,
                        "30m": 30,
                        "1h": 60,
                        "2h": 120,
                        "4h": 240,
                        "8h": 480,
                        "12h": 720,
                        "1d": 1440,
                        "3d": 4320,
                        "1w": 10080,
                        "1M": 43200,
                    }.get(timeframe, 60)
                    bars = max(1, round(interval_ms / (tf_minutes * 60 * 1000)))
                    signal["every_n_bars"] = bars
                else:
                    signal["every_n_bars"] = 1
            else:
                signal["every_n_bars"] = every_n_bars
            signal["action"] = _normalize_signal_action(signal.get("action"), fallback="buy")
            if "gate" in signal and isinstance(signal["gate"], dict):
                signal["gate"] = _normalize_gate(signal["gate"])

        elif kind == "position_pnl":
            if "pnl_pct_above" in signal:
                v = _to_float(signal["pnl_pct_above"])
                if v is not None:
                    signal["pnl_pct_above"] = _pct_ratio(v) if abs(v) > 1 else v
            if "pnl_pct_below" in signal:
                v = _to_float(signal["pnl_pct_below"])
                if v is not None:
                    signal["pnl_pct_below"] = _pct_ratio(v) if abs(v) > 1 else v
            signal["action"] = _normalize_signal_action(signal.get("action"), fallback="buy")
            if "gate" in signal and isinstance(signal["gate"], dict):
                signal["gate"] = _normalize_gate(signal["gate"])

        elif kind == "ranking":
            rank_by = signal.get("rank_by")
            if not isinstance(rank_by, str) or not rank_by.strip():
                signal["rank_by"] = "change_24h"
            long_top_n = _to_int(signal.get("long_top_n"))
            signal["long_top_n"] = long_top_n if long_top_n is not None and long_top_n >= 0 else 1
            short_bottom_n = _to_int(signal.get("short_bottom_n"))
            signal["short_bottom_n"] = short_bottom_n if short_bottom_n is not None and short_bottom_n >= 0 else 0
            if "rebalance" in signal:
                signal["rebalance"] = _to_bool(signal["rebalance"], False)
            if "close_before_open" in signal:
                signal["close_before_open"] = _to_bool(signal["close_before_open"], False)
            if "gate" in signal and isinstance(signal["gate"], dict):
                signal["gate"] = _normalize_gate(signal["gate"])

        normalized.append(signal)

    return normalized


def _default_window(timeframe: str, now_ts: int) -> Tuple[int, int]:
    days = LOOKBACK_DAYS_BY_TIMEFRAME.get(timeframe, 180)
    end_ts = now_ts
    start_ts = end_ts - (days * 24 * 60 * 60 * 1000)
    return start_ts, end_ts


def normalize_backtest_spec(
    input_payload: Dict[str, Any],
    strategy_description: str,
    now_ts: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    now_ms = now_ts or _now_ms()
    assumptions: List[str] = []

    payload = input_payload.get("strategy_spec", input_payload)
    if not isinstance(payload, dict):
        raise ValueError("strategy_spec must be an object")

    spec = copy.deepcopy(payload)
    name = str(spec.get("name") or "Generated Backtest Strategy").strip()
    strategy_id = spec.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        strategy_id = _sanitize_kebab(name if name else strategy_description)
        assumptions.append("strategy_id was auto-generated from strategy name.")

    spec["version"] = "1.0"
    spec["strategy_id"] = _sanitize_kebab(str(strategy_id))
    spec["name"] = name

    markets = _normalize_market_list(spec.get("markets"))
    if not markets:
        inferred = _normalize_market(spec.get("coin")) or "BTC"
        markets = [inferred]
        assumptions.append("markets was missing; defaulted to BTC.")
    spec["markets"] = markets

    timeframe = _normalize_timeframe(spec.get("timeframe"))
    if spec.get("timeframe") != timeframe:
        assumptions.append(f"timeframe normalized to {timeframe}.")
    spec["timeframe"] = timeframe

    default_start, default_end = _default_window(timeframe, now_ms)
    start_ts = _to_int(spec.get("start_ts"))
    end_ts = _to_int(spec.get("end_ts"))
    if not start_ts or start_ts <= 0:
        start_ts = default_start
        assumptions.append("start_ts defaulted from lookback window.")
    if not end_ts or end_ts <= 0:
        end_ts = default_end
        assumptions.append("end_ts defaulted to current timestamp.")
    if end_ts <= start_ts:
        start_ts, end_ts = default_start, default_end
        assumptions.append("invalid time range replaced with default lookback window.")
    spec["start_ts"] = int(start_ts)
    spec["end_ts"] = int(end_ts)

    signals = _normalize_signals(spec.get("signals"), timeframe)
    if not signals:
        fallback_signal = {
            "id": "fallback_rsi",
            "kind": "threshold",
            "indicator": "RSI",
            "period": 14,
            "check_field": "value",
            "operator": "lt",
            "value": 30,
            "action": "buy",
        }
        signals = [fallback_signal]
        assumptions.append("signals were missing; inserted fallback RSI threshold signal.")
    spec["signals"] = signals

    sizing = spec.get("sizing") if isinstance(spec.get("sizing"), dict) else {}
    sizing_mode = sizing.get("mode")
    valid_sizing_modes = {"notional_usd", "margin_usd", "equity_pct", "base_units", "risk_based", "kelly", "signal_proportional"}
    if sizing_mode not in valid_sizing_modes:
        sizing_mode = "notional_usd"
        assumptions.append("sizing.mode defaulted to notional_usd.")
    sizing_value = _to_float(sizing.get("value"))
    if sizing_value is None or sizing_value <= 0:
        sizing_value = 100.0
        assumptions.append("sizing.value defaulted to 100.")
    if sizing_mode == "equity_pct" and sizing_value > 1:
        sizing_value = sizing_value / 100.0
        assumptions.append("sizing.value converted from percent to ratio for equity_pct.")

    normalized_sizing: Dict[str, Any] = {"mode": sizing_mode, "value": sizing_value}

    # risk_based extras
    if sizing_mode == "risk_based":
        rpt = _to_float(sizing.get("risk_per_trade_usd"))
        if rpt and rpt > 0:
            normalized_sizing["risk_per_trade_usd"] = rpt
        sl_atr = _to_float(sizing.get("sl_atr_multiple"))
        if sl_atr and sl_atr > 0:
            normalized_sizing["sl_atr_multiple"] = sl_atr

    # kelly extras
    if sizing_mode == "kelly":
        kf = _to_float(sizing.get("kelly_fraction"))
        if kf and 0 < kf <= 1:
            normalized_sizing["kelly_fraction"] = kf
        klt = _to_int(sizing.get("kelly_lookback_trades"))
        if klt and klt > 0:
            normalized_sizing["kelly_lookback_trades"] = klt
        kmt = _to_int(sizing.get("kelly_min_trades"))
        if kmt and kmt > 0:
            normalized_sizing["kelly_min_trades"] = kmt
        mbp = _to_float(sizing.get("max_balance_pct"))
        if mbp and 0 < mbp <= 1:
            normalized_sizing["max_balance_pct"] = mbp

    # signal_proportional extras
    if sizing_mode == "signal_proportional":
        bn = _to_float(sizing.get("base_notional_usd"))
        if bn and bn > 0:
            normalized_sizing["base_notional_usd"] = bn
        mn = _to_float(sizing.get("max_notional_usd"))
        if mn and mn > 0:
            normalized_sizing["max_notional_usd"] = mn
        sf = sizing.get("signal_field")
        if isinstance(sf, str) and sf.strip():
            normalized_sizing["signal_field"] = sf.strip()

    spec["sizing"] = normalized_sizing

    risk = spec.get("risk") if isinstance(spec.get("risk"), dict) else {}
    leverage = _to_float(risk.get("leverage"))
    if leverage is None or leverage <= 0:
        leverage = 3.0
        assumptions.append("risk.leverage defaulted to 3.")
    max_positions = _to_int(risk.get("max_positions"))
    if not max_positions or max_positions <= 0:
        max_positions = len(markets)
        assumptions.append("risk.max_positions defaulted to number of markets.")
    min_notional = _to_float(risk.get("min_notional_usd"))
    if min_notional is None or min_notional <= 0:
        min_notional = 10.0

    normalized_risk: Dict[str, Any] = {
        "leverage": leverage,
        "max_positions": max_positions,
        "min_notional_usd": min_notional,
        "allow_position_add": _to_bool(risk.get("allow_position_add"), True),
        "allow_flip": _to_bool(risk.get("allow_flip"), True),
    }

    for optional_key in ("daily_loss_limit_usd", "max_position_notional_usd", "max_total_notional_usd", "max_total_margin_usd"):
        opt = _to_float(risk.get(optional_key))
        if opt is not None and opt > 0:
            normalized_risk[optional_key] = opt

    # Maintenance margin rate
    mmr = _to_float(risk.get("maintenance_margin_rate"))
    if mmr is not None and 0 < mmr <= 1:
        normalized_risk["maintenance_margin_rate"] = mmr

    # Independent sub-positions (grid trading)
    if "independent_sub_positions" in risk:
        normalized_risk["independent_sub_positions"] = _to_bool(risk["independent_sub_positions"], False)

    spec["risk"] = normalized_risk

    exits = spec.get("exits") if isinstance(spec.get("exits"), dict) else {}
    normalized_exits: Dict[str, Any] = {}
    for key in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct"):
        if key in exits:
            value = _pct_ratio(exits.get(key))
            if isinstance(value, (int, float)) and value > 0:
                normalized_exits[key] = float(value)

    max_hold_bars = _to_int(exits.get("max_hold_bars"))
    if max_hold_bars and max_hold_bars > 0:
        normalized_exits["max_hold_bars"] = max_hold_bars

    if "move_stop_to_break_even_after_tp" in exits:
        normalized_exits["move_stop_to_break_even_after_tp"] = bool(exits.get("move_stop_to_break_even_after_tp"))

    partials = exits.get("partial_take_profit_levels")
    if isinstance(partials, list):
        normalized_partials = []
        for level in partials:
            if not isinstance(level, dict):
                continue
            profit_pct = _pct_ratio(level.get("profit_pct"))
            close_fraction = _pct_ratio(level.get("close_fraction"))
            if not isinstance(profit_pct, (int, float)) or not isinstance(close_fraction, (int, float)):
                continue
            if profit_pct <= 0 or close_fraction <= 0:
                continue
            normalized_partials.append(
                {
                    "profit_pct": float(profit_pct),
                    "close_fraction": float(close_fraction),
                }
            )
        if normalized_partials:
            normalized_exits["partial_take_profit_levels"] = normalized_partials

    if not any(key in normalized_exits for key in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "partial_take_profit_levels")):
        normalized_exits["stop_loss_pct"] = 0.08
        normalized_exits["take_profit_pct"] = 0.12
        assumptions.append("exits defaulted to stop_loss_pct=0.08 and take_profit_pct=0.12.")

    spec["exits"] = normalized_exits

    execution = spec.get("execution") if isinstance(spec.get("execution"), dict) else {}
    spec["execution"] = {
        "entry_order_type": _normalize_order_type(execution.get("entry_order_type"), "market"),
        "limit_offset_bps": max(0.0, _to_float(execution.get("limit_offset_bps")) or 0.0),
        "slippage_bps": max(0.0, _to_float(execution.get("slippage_bps")) or 5.0),
        "maker_fee_rate": max(0.0, _to_float(execution.get("maker_fee_rate")) or 0.00015),
        "taker_fee_rate": max(0.0, _to_float(execution.get("taker_fee_rate")) or 0.00045),
        "stop_order_type": "limit" if str(execution.get("stop_order_type", "market")).lower() == "limit" else "market",
        "take_profit_order_type": "limit"
        if str(execution.get("take_profit_order_type", "market")).lower() == "limit"
        else "market",
        "stop_limit_slippage_pct": float(_pct_ratio(execution.get("stop_limit_slippage_pct")) or 0.03),
        "take_profit_limit_slippage_pct": float(_pct_ratio(execution.get("take_profit_limit_slippage_pct")) or 0.01),
        "trigger_type": str(execution.get("trigger_type", "last")).lower()
        if str(execution.get("trigger_type", "last")).lower() in {"mark", "last", "oracle"}
        else "last",
        "reduce_only_on_exits": _to_bool(execution.get("reduce_only_on_exits"), True),
    }

    initial_capital = _to_float(spec.get("initial_capital_usd"))
    if initial_capital is None or initial_capital <= 0:
        initial_capital = 10000.0
        assumptions.append("initial_capital_usd defaulted to 10000.")
    spec["initial_capital_usd"] = initial_capital

    if "seed" in spec:
        seed = _to_int(spec.get("seed"))
        if seed is None:
            spec.pop("seed", None)
        else:
            spec["seed"] = seed

    # Pass through optional extended fields (validated by schema)
    if "conditions" in spec and isinstance(spec["conditions"], list):
        pass  # keep as-is; schema will validate
    elif "conditions" in spec:
        spec.pop("conditions", None)

    if "hooks" in spec and isinstance(spec["hooks"], list):
        pass  # keep as-is; schema will validate
    elif "hooks" in spec:
        spec.pop("hooks", None)

    if "auxiliary_timeframes" in spec and isinstance(spec["auxiliary_timeframes"], list):
        pass  # keep as-is; schema will validate
    elif "auxiliary_timeframes" in spec:
        spec.pop("auxiliary_timeframes", None)

    return spec, assumptions


class BacktestSpecGenerator:
    """Generates normalized + validated backtest strategy specs from natural language.

    Includes a validate-or-correct guardrail: if the LLM output fails schema
    validation after normalization, the errors are sent back to the LLM for a
    correction pass (up to MAX_CORRECTION_ATTEMPTS times).
    """

    def __init__(self, ai_provider: AIProvider, validate: bool = True):
        self.ai_provider = ai_provider
        self.validate = validate

    # ── internal: build correction prompt ──────────────────────────

    @staticmethod
    def _build_correction_prompt(
        original_spec: Dict[str, Any],
        errors: List[Dict[str, str]],
    ) -> str:
        error_lines = "\n".join(
            f"  - {e['path']}: {e['message']}" for e in errors
        )
        return (
            "The strategy_spec you generated failed schema validation.\n"
            "Fix ONLY the fields listed below and return the corrected full JSON "
            "envelope ({{ \"strategy_spec\": {{...}}, \"notes\": {{...}} }}).\n\n"
            f"Validation errors:\n{error_lines}\n\n"
            f"Original spec:\n{_json.dumps(original_spec, indent=2)}"
        )

    # ── internal: normalize + validate (returns errors or None) ────

    def _normalize_and_validate(
        self,
        response: Dict[str, Any],
        strategy_description: str,
        now_ts: int,
    ) -> Tuple[Dict[str, Any], List[str], Optional[List[Dict[str, str]]]]:
        """Return (normalized_spec, assumptions, errors_or_None)."""
        normalized_spec, assumptions = normalize_backtest_spec(
            response, strategy_description, now_ts=now_ts
        )
        if not self.validate:
            return normalized_spec, assumptions, None

        valid, errors = validate_backtest_spec(normalized_spec)
        if valid:
            return normalized_spec, assumptions, None
        return normalized_spec, assumptions, errors

    # ── public entry point ─────────────────────────────────────────

    async def generate_backtest_spec(self, strategy_description: str) -> Dict[str, Any]:
        now_ts = _now_ms()
        user_prompt = (
            BACKTEST_SPEC_GENERATION_PROMPT.replace("{strategy_description}", strategy_description.strip())
            .replace("{now_ts}", str(now_ts))
        )

        response = await self.ai_provider.generate_with_json(
            system_prompt=BACKTEST_SPEC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if not isinstance(response, dict):
            raise ValueError("LLM response must be a JSON object")

        # ── validate-or-correct loop ─────────────────────────────
        normalized_spec, normalization_assumptions, val_errors = (
            self._normalize_and_validate(response, strategy_description, now_ts)
        )

        correction_attempts = 0
        while val_errors and correction_attempts < MAX_CORRECTION_ATTEMPTS:
            correction_attempts += 1
            logger.warning(
                "Backtest spec validation failed (%d error(s)), requesting correction (attempt %d/%d)",
                len(val_errors), correction_attempts, MAX_CORRECTION_ATTEMPTS,
            )

            correction_prompt = self._build_correction_prompt(normalized_spec, val_errors)
            try:
                corrected_response = await self.ai_provider.generate_with_json(
                    system_prompt=BACKTEST_SPEC_SYSTEM_PROMPT,
                    user_prompt=correction_prompt,
                )
                if not isinstance(corrected_response, dict):
                    break

                response = corrected_response
                normalized_spec, extra_assumptions, val_errors = (
                    self._normalize_and_validate(corrected_response, strategy_description, now_ts)
                )
                normalization_assumptions.extend(extra_assumptions)
                if not val_errors:
                    normalization_assumptions.append(
                        f"Spec was auto-corrected after {correction_attempts} correction pass(es)."
                    )
            except Exception as exc:
                logger.error("Correction pass %d failed: %s", correction_attempts, exc)
                break

        # If validation is on and errors remain after all corrections, raise
        if self.validate and val_errors:
            normalized_spec = assert_valid_backtest_spec(normalized_spec)  # will raise

        # ── assemble notes ───────────────────────────────────────
        notes = response.get("notes", {})
        if not isinstance(notes, dict):
            notes = {}

        assumptions = notes.get("assumptions", [])
        if not isinstance(assumptions, list):
            assumptions = []

        notes["assumptions"] = assumptions + normalization_assumptions
        notes["complexity"] = str(notes.get("complexity", "medium"))
        notes["reasoning_summary"] = str(
            notes.get("reasoning_summary", "Generated from natural language strategy request.")
        )

        unsupported = notes.get("unsupported_features", [])
        notes["unsupported_features"] = unsupported if isinstance(unsupported, list) else []

        confidence = notes.get("mapping_confidence", 0.75)
        confidence_num = _to_float(confidence)
        notes["mapping_confidence"] = max(0.0, min(1.0, confidence_num if confidence_num is not None else 0.75))

        return {
            "strategy_spec": normalized_spec,
            "notes": notes,
        }
