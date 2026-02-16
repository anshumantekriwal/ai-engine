"""
Backtest V2 strategy spec generator for the SpecAgent backtesting engine.

Generates strategy specs in the Hyperliquid SpecAgent format
(triggers + workflows + expressions) for candle-based backtesting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ai_providers import AIProvider
from backtest_v2_spec_prompts import BACKTEST_V2_GENERATION_PROMPT, BACKTEST_V2_SYSTEM_PROMPT
from strategy_spec_schema import validate_strategy_spec, assert_valid_strategy_spec


class BacktestV2SpecGenerator:
    """Generates validated SpecAgent strategy specs for backtesting."""

    def __init__(
        self,
        ai_provider: AIProvider,
        validate: bool = True,
    ):
        self.ai_provider = ai_provider
        self.validate = validate

    async def generate_backtest_v2_spec(
        self,
        strategy_description: str,
    ) -> Dict[str, Any]:
        """
        Generate a SpecAgent strategy spec from a natural language description.

        1. Build prompt with the strategy description
        2. Call AI provider for JSON generation
        3. Extract strategy_spec from envelope
        4. Validate against the strategy_spec schema
        5. If validation fails, retry once with error feedback
        6. Return validated spec + notes
        """
        user_prompt = BACKTEST_V2_GENERATION_PROMPT.replace(
            "{strategy_description}",
            strategy_description.strip(),
        )

        response = await self.ai_provider.generate_with_json(
            system_prompt=BACKTEST_V2_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        # Extract spec from envelope or treat the whole response as the spec
        strategy_spec = response.get("strategy_spec", response)
        notes = response.get("notes", {})

        if self.validate:
            valid, errors = validate_strategy_spec(strategy_spec)
            if not valid:
                # Attempt one correction pass
                strategy_spec, correction_notes = await self._retry_with_errors(
                    strategy_description,
                    strategy_spec,
                    errors,
                )
                if correction_notes:
                    notes["correction_applied"] = True
                    notes["original_errors"] = [
                        f"{e['path']}: {e['message']}" for e in errors
                    ]

            # Final validation (raises on failure)
            strategy_spec = assert_valid_strategy_spec(strategy_spec)

        return {
            "strategy_spec": strategy_spec,
            "notes": notes,
        }

    async def _retry_with_errors(
        self,
        strategy_description: str,
        failed_spec: Dict[str, Any],
        errors: List[Dict[str, str]],
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Send the validation errors back to the LLM for one correction pass.
        Returns (corrected_spec, was_corrected).
        """
        error_summary = "\n".join(
            f"- {e['path']}: {e['message']}" for e in errors
        )

        correction_prompt = (
            f"The previous SpecAgent strategy spec had validation errors:\n"
            f"{error_summary}\n\n"
            f"Original failed spec:\n{_safe_json_dumps(failed_spec)}\n\n"
            f"Original strategy description: {strategy_description}\n\n"
            f"Please fix ALL the errors and return ONLY the corrected JSON envelope:\n"
            f'{{"strategy_spec": {{ ... }}, "notes": {{ ... }}}}'
        )

        try:
            corrected_response = await self.ai_provider.generate_with_json(
                system_prompt=BACKTEST_V2_SYSTEM_PROMPT,
                user_prompt=correction_prompt,
            )
            corrected_spec = corrected_response.get("strategy_spec", corrected_response)
            return corrected_spec, True
        except Exception:
            # If correction fails, return the original (will fail final validation)
            return failed_spec, False


def _safe_json_dumps(obj: Any) -> str:
    """JSON serialize with fallback."""
    import json
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        return str(obj)
