"""
AI Provider Interface

Uses OpenAI GPT-4o with extended thinking for code generation.
All providers include exponential backoff with jitter for transient failures.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio
import logging
import os
import random

from openai import OpenAI
from anthropic import Anthropic

logger = logging.getLogger(__name__)

# ─── Retry Configuration ───────────────────────────────────────────

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0       # seconds
DEFAULT_MAX_DELAY = 30.0       # seconds
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_JITTER = 0.5           # ±50% jitter

# Exceptions worth retrying (transient / rate-limit)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception is a transient failure worth retrying."""
    # Anthropic errors
    if hasattr(exc, "status_code") and getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
        return True
    # OpenAI errors
    if hasattr(exc, "status_code") and getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
        return True
    # Generic HTTP status via response attribute
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        if exc.response.status_code in _RETRYABLE_STATUS_CODES:
            return True
    # Connection-level errors
    err_name = type(exc).__name__.lower()
    if any(kw in err_name for kw in ("timeout", "connection", "overloaded", "ratelimit")):
        return True
    return False


async def _retry_with_backoff(
    fn,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
):
    """
    Execute `fn` (an async callable returning a value) with exponential backoff.
    Retries only on transient / rate-limit errors.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            delay *= 1.0 + random.uniform(-jitter, jitter)
            delay = max(0.1, delay)
            logger.warning(
                "API call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, max_retries + 1, exc, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]   # unreachable, but keeps type-checker happy


class AIProvider(ABC):
    """Abstract base class for AI providers"""
    
    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:
        """Generate text completion"""
        pass
    
    @abstractmethod
    async def generate_with_json(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate JSON response. system_prompt is optional (e.g. for validation pass)."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI GPT-4o AI provider with extended thinking"""
    
    def __init__(self, api_key: str, model: str = "gpt-5.2"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:
        """Generate text completion using GPT-4o with reasoning"""
        
        # Combine system and user prompts for o1 model
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"

        async def _call():
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": combined_prompt}
                ],
                reasoning_effort="low"   
            )
            return response.choices[0].message.content

        return await _retry_with_backoff(_call)
    
    async def generate_with_json(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate JSON response using GPT-4o with reasoning"""
        import json
        
        if system_prompt:
            combined_prompt = f"{system_prompt}\n\nRespond with valid JSON only.\n\n{user_prompt}"
        else:
            combined_prompt = f"Respond with valid JSON only.\n\n{user_prompt}"

        async def _call():
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": combined_prompt}
                ],
                reasoning_effort="high"
            )
            return response.choices[0].message.content

        response_text = await _retry_with_backoff(_call)
        
        # Extract JSON if wrapped in markdown
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        return json.loads(response_text)


class AnthropicProvider(AIProvider):
    """Anthropic Claude AI provider"""
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5"):
        self.client = Anthropic(api_key=api_key)
        self.model = model
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:
        """Generate text completion using Claude"""

        async def _call():
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                temperature=0.7,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response.content[0].text

        return await _retry_with_backoff(_call)
    
    async def generate_with_json(
        self,
        user_prompt: str,
        *,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate JSON response using Claude. Caches system prompt when provided."""
        import json
        
        if system_prompt:
            enhanced_system = f"{system_prompt}\n\nRespond with valid JSON only."
            system_blocks = [
                {"type": "text", "text": enhanced_system, "cache_control": {"type": "ephemeral"}}
            ]
            create_kwargs = {"system": system_blocks}
        else:
            user_prompt = f"Respond with valid JSON only.\n\n{user_prompt}"
            create_kwargs = {}

        async def _call():
            if self.model == "claude-sonnet-4-5":
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=0.7,
                    messages=[{"role": "user", "content": user_prompt}],
                    **create_kwargs
                )
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    thinking={"type": "adaptive"},
                    messages=[{"role": "user", "content": user_prompt}],
                    **create_kwargs
                )
            return response.content[0].text

        response_text = await _retry_with_backoff(_call)
        
        # Extract JSON if wrapped in markdown
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        return json.loads(response_text)


def get_provider(api_key: str, model: Optional[str] = None, provider: str = "anthropic") -> AIProvider:
    """Factory function to get AI provider
    
    Args:
        api_key: API key for the provider
        model: Model name (optional, uses default for provider)
        provider: Provider name ('openai' or 'anthropic')
    """
    
    if provider.lower() == "anthropic":
        return AnthropicProvider(
            api_key=api_key,
            model=model or "claude-sonnet-4-5"
        )
    else:
        return OpenAIProvider(
            api_key=api_key,
            model=model or "o1"
        )
