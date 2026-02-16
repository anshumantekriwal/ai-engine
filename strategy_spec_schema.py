"""
Validation utilities for the declarative/hybrid strategy_spec contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

SUPPORTED_VERSION = "1.0"
SUPPORTED_MODES = {"spec", "hybrid"}
TRIGGER_TYPES = {"price", "technical", "scheduled", "event"}
EVENT_TYPES = {"liquidation", "largeTrade", "userFill", "l2Book"}
TECHNICAL_INDICATORS = {
    "RSI", "EMA", "SMA", "WMA", "MACD", "BollingerBands",
    "EMA_CROSSOVER", "SMA_CROSSOVER",
    "ATR", "Stochastic", "StochasticRSI", "WilliamsR",
    "ADX", "CCI", "ROC", "OBV", "TRIX", "MFI", "VWAP",
    "PSAR", "KeltnerChannels",
}
ACTION_TYPES = {
    "set",
    "if",
    "for_each",
    "call",
    "log",
    "update_state",
    "sync_positions",
    "pause_ms",
    "return",
    "assert",
}
CALL_TARGETS = {"market", "user", "order", "agent", "state"}


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _add_error(errors: List[Dict[str, str]], path: str, message: str) -> None:
    errors.append({"path": path, "message": message})


def _validate_expression(value: Any, path: str, errors: List[Dict[str, str]], depth: int = 0) -> None:
    if depth > 24:
        _add_error(errors, path, "expression nesting exceeds maximum depth 24")
        return

    if value is None or isinstance(value, (str, int, float, bool)):
        return

    if isinstance(value, list):
        for idx, item in enumerate(value):
            _validate_expression(item, f"{path}[{idx}]", errors, depth + 1)
        return

    if not _is_dict(value):
        _add_error(errors, path, "must be a primitive, list, or object expression")
        return

    # Allow object literals recursively, while preserving ref/op shortcuts.
    if "ref" in value:
        if len(value) != 1 or not isinstance(value.get("ref"), str) or not value.get("ref").strip():
            _add_error(errors, path, "ref expression must be {ref: <non-empty-string>}")
        return

    if "op" in value:
        if not isinstance(value.get("op"), str) or not value.get("op").strip():
            _add_error(errors, f"{path}.op", "must be a non-empty string")
        args = value.get("args", [])
        if not isinstance(args, list):
            _add_error(errors, f"{path}.args", "must be a list")
        else:
            for idx, arg in enumerate(args):
                _validate_expression(arg, f"{path}.args[{idx}]", errors, depth + 1)
        return

    for key, child in value.items():
        if key in {"__proto__", "constructor", "prototype"}:
            _add_error(errors, f"{path}.{key}", "reserved key is not allowed")
            continue
        _validate_expression(child, f"{path}.{key}", errors, depth + 1)


def _validate_trigger(trigger: Dict[str, Any], idx: int, errors: List[Dict[str, str]]) -> None:
    path = f"triggers[{idx}]"

    trigger_type = trigger.get("type")
    if trigger_type not in TRIGGER_TYPES:
        _add_error(errors, f"{path}.type", f"must be one of: {sorted(TRIGGER_TYPES)}")
        return

    if not isinstance(trigger.get("id"), str) or not trigger["id"].strip():
        _add_error(errors, f"{path}.id", "must be a non-empty string")

    if not isinstance(trigger.get("onTrigger"), str) or not trigger["onTrigger"].strip():
        _add_error(errors, f"{path}.onTrigger", "must be a non-empty workflow id")

    if "cooldownMs" in trigger and (not isinstance(trigger["cooldownMs"], (int, float)) or trigger["cooldownMs"] < 0):
        _add_error(errors, f"{path}.cooldownMs", "must be >= 0")

    if "maxExecutions" in trigger and (not isinstance(trigger["maxExecutions"], int) or trigger["maxExecutions"] <= 0):
        _add_error(errors, f"{path}.maxExecutions", "must be an integer > 0")

    if trigger_type == "price":
        if not isinstance(trigger.get("coin"), str) or not trigger["coin"].strip():
            _add_error(errors, f"{path}.coin", "is required for price trigger")
        if not _is_dict(trigger.get("condition")):
            _add_error(errors, f"{path}.condition", "must be an object")
        else:
            condition = trigger["condition"]
            valid_price_keys = ("above", "below", "crosses", "crosses_above", "crosses_below")
            if not any(k in condition for k in valid_price_keys):
                _add_error(errors, f"{path}.condition", f"must include one of: {', '.join(valid_price_keys)}")

    if trigger_type == "technical":
        if not isinstance(trigger.get("coin"), str) or not trigger["coin"].strip():
            _add_error(errors, f"{path}.coin", "is required for technical trigger")
        if trigger.get("indicator") not in TECHNICAL_INDICATORS:
            _add_error(errors, f"{path}.indicator", f"must be one of: {sorted(TECHNICAL_INDICATORS)}")
        if not _is_dict(trigger.get("params")):
            _add_error(errors, f"{path}.params", "must be an object")

    if trigger_type == "scheduled":
        if not isinstance(trigger.get("intervalMs"), (int, float)) or trigger["intervalMs"] <= 0:
            _add_error(errors, f"{path}.intervalMs", "must be > 0")

    if trigger_type == "event":
        if trigger.get("eventType") not in EVENT_TYPES:
            _add_error(errors, f"{path}.eventType", f"must be one of: {sorted(EVENT_TYPES)}")


def _validate_steps(steps: Any, path: str, errors: List[Dict[str, str]], depth: int = 0) -> None:
    if depth > 32:
        _add_error(errors, path, "step nesting exceeds maximum depth 32")
        return

    if not isinstance(steps, list) or len(steps) == 0:
        _add_error(errors, path, "must be a non-empty list")
        return

    for idx, step in enumerate(steps):
        step_path = f"{path}[{idx}]"
        if not _is_dict(step):
            _add_error(errors, step_path, "must be an object")
            continue

        action = step.get("action")
        if action not in ACTION_TYPES:
            _add_error(errors, f"{step_path}.action", f"must be one of: {sorted(ACTION_TYPES)}")
            continue

        if action == "set":
            if not isinstance(step.get("path"), str) or not step["path"].strip():
                _add_error(errors, f"{step_path}.path", "must be a non-empty string")
            if "value" not in step:
                _add_error(errors, f"{step_path}.value", "is required")
            else:
                _validate_expression(step["value"], f"{step_path}.value", errors)

        if action == "if":
            _validate_expression(step.get("condition"), f"{step_path}.condition", errors)
            _validate_steps(step.get("then"), f"{step_path}.then", errors, depth + 1)
            if "else" in step:
                _validate_steps(step.get("else"), f"{step_path}.else", errors, depth + 1)

        if action == "for_each":
            _validate_expression(step.get("list"), f"{step_path}.list", errors)
            if not isinstance(step.get("item"), str) or not step["item"].strip():
                _add_error(errors, f"{step_path}.item", "must be a non-empty string")
            _validate_steps(step.get("steps"), f"{step_path}.steps", errors, depth + 1)

        if action == "call":
            if step.get("target") not in CALL_TARGETS:
                _add_error(errors, f"{step_path}.target", f"must be one of: {sorted(CALL_TARGETS)}")
            if not isinstance(step.get("method"), str) or not step["method"].strip():
                _add_error(errors, f"{step_path}.method", "must be a non-empty string")
            args = step.get("args", [])
            if not isinstance(args, list):
                _add_error(errors, f"{step_path}.args", "must be a list")
            else:
                for arg_idx, arg in enumerate(args):
                    _validate_expression(arg, f"{step_path}.args[{arg_idx}]", errors)

        if action in {"log", "update_state", "pause_ms", "return", "assert"}:
            if "message" in step:
                _validate_expression(step["message"], f"{step_path}.message", errors)
            if "data" in step:
                _validate_expression(step["data"], f"{step_path}.data", errors)
            if "ms" in step:
                _validate_expression(step["ms"], f"{step_path}.ms", errors)
            if "value" in step:
                _validate_expression(step["value"], f"{step_path}.value", errors)
            if "condition" in step:
                _validate_expression(step["condition"], f"{step_path}.condition", errors)


def validate_strategy_spec(spec: Any) -> Tuple[bool, List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []

    if not _is_dict(spec):
        return False, [{"path": "root", "message": "strategy_spec must be an object"}]

    if spec.get("version") != SUPPORTED_VERSION:
        _add_error(errors, "version", f"must equal supported version {SUPPORTED_VERSION}")

    if not isinstance(spec.get("strategy_id"), str) or not spec["strategy_id"].strip():
        _add_error(errors, "strategy_id", "must be a non-empty string")

    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        _add_error(errors, "name", "must be a non-empty string")

    if "mode" in spec and spec.get("mode") not in SUPPORTED_MODES:
        _add_error(errors, "mode", f"must be one of: {sorted(SUPPORTED_MODES)}")

    triggers = spec.get("triggers")
    if not isinstance(triggers, list) or len(triggers) == 0:
        _add_error(errors, "triggers", "must be a non-empty list")
    else:
        seen_ids = set()
        for idx, trigger in enumerate(triggers):
            if not _is_dict(trigger):
                _add_error(errors, f"triggers[{idx}]", "must be an object")
                continue
            _validate_trigger(trigger, idx, errors)
            trigger_id = trigger.get("id")
            if isinstance(trigger_id, str):
                if trigger_id in seen_ids:
                    _add_error(errors, f"triggers[{idx}].id", f"duplicate trigger id {trigger_id}")
                seen_ids.add(trigger_id)

    workflows = spec.get("workflows")
    if not _is_dict(workflows) or len(workflows) == 0:
        _add_error(errors, "workflows", "must be a non-empty object")
    else:
        for workflow_id, workflow in workflows.items():
            if not _is_dict(workflow):
                _add_error(errors, f"workflows.{workflow_id}", "must be an object")
                continue
            _validate_steps(workflow.get("steps"), f"workflows.{workflow_id}.steps", errors)

        workflow_ids = set(workflows.keys())
        for idx, trigger in enumerate(triggers or []):
            if _is_dict(trigger):
                workflow = trigger.get("onTrigger")
                if isinstance(workflow, str) and workflow not in workflow_ids:
                    _add_error(
                        errors,
                        f"triggers[{idx}].onTrigger",
                        f"references unknown workflow {workflow}",
                    )

    return len(errors) == 0, errors


def assert_valid_strategy_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    valid, errors = validate_strategy_spec(spec)
    if not valid:
        detail = "; ".join([f"{item['path']}: {item['message']}" for item in errors])
        raise ValueError(f"Invalid strategy_spec: {detail}")
    return spec
