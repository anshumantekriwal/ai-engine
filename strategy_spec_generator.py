"""
Strategy spec generator for declarative/hybrid execution.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai_providers import AIProvider
from spec_prompts import SPEC_GENERATION_PROMPT, SPEC_SYSTEM_PROMPT
from strategy_spec_schema import assert_valid_strategy_spec


class StrategySpecGenerator:
    """Generates validated strategy_spec payloads using the configured AI provider."""

    def __init__(
        self,
        ai_provider: AIProvider,
        validate: bool = True,
        code_generator: Optional[Any] = None,
    ):
        self.ai_provider = ai_provider
        self.validate = validate
        self.code_generator = code_generator

    async def generate_strategy_spec(self, strategy_description: str) -> Dict[str, Any]:
        user_prompt = SPEC_GENERATION_PROMPT.replace(
            "{strategy_description}",
            strategy_description.strip()
        )

        response = await self.ai_provider.generate_with_json(
            system_prompt=SPEC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        strategy_spec = response.get("strategy_spec", response)

        if self.validate:
            strategy_spec = assert_valid_strategy_spec(strategy_spec)

        return {
            "strategy_spec": strategy_spec,
            "notes": response.get("notes", {}),
        }

    async def generate_hybrid_bundle(
        self,
        strategy_description: str,
        include_code_fallback: bool = False,
    ) -> Dict[str, Any]:
        spec_result = await self.generate_strategy_spec(strategy_description)

        bundle: Dict[str, Any] = {
            "strategy_spec": spec_result["strategy_spec"],
            "notes": spec_result.get("notes", {}),
            "code_fallback": None,
        }

        if include_code_fallback and self.code_generator is not None:
            code_result = await self.code_generator.generate_complete_agent(
                strategy_description=strategy_description
            )
            bundle["code_fallback"] = {
                "initialization_code": code_result["initialization_code"],
                "trigger_code": code_result["trigger_code"],
                "execution_code": code_result["execution_code"],
            }

        return bundle
