"""
AI Provider Interface

Uses OpenAI GPT-4o with extended thinking for code generation
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import os
from openai import OpenAI
from anthropic import Anthropic


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
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """Generate JSON response"""
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
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": combined_prompt}
            ],
            reasoning_effort="low"   
        )
        
        return response.choices[0].message.content
    
    async def generate_with_json(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """Generate JSON response using GPT-4o with reasoning"""
        import json
        
        # Combine system and user prompts for o1 model
        combined_prompt = f"{system_prompt}\n\nRespond with valid JSON only.\n\n{user_prompt}"
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": combined_prompt}
            ],
            reasoning_effort="high"
        )
        
        response_text = response.choices[0].message.content
        
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
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_prompt,
            temperature=0.7,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        return response.content[0].text
    
    async def generate_with_json(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """Generate JSON response using Claude"""
        import json
        
        enhanced_system = f"{system_prompt}\n\nRespond with valid JSON only."
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=enhanced_system,
            temperature=0.7,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        response_text = response.content[0].text
        
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
