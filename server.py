"""
FastAPI Server for AI Agent Code Generation

Endpoints:
- POST /generate - Generate trading agent code (agentic pipeline)
- POST /generate-backtest-spec - Generate backtest-tool-compatible strategy spec
- POST /backtest-spec/validate - Validate backtest strategy spec payload
- GET /status - Health check
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import os
from dotenv import load_dotenv

from ai_providers import get_provider
from agent_generator import AgentCodeGenerator
from backtest_spec_generator import BacktestSpecGenerator
from backtest_spec_schema import validate_backtest_spec

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    print("=" * 60)
    print("🚀 AI Agent Code Generator")
    print("=" * 60)
    print(f"Provider: {AI_PROVIDER.upper()}")
    print(f"Model: {AI_MODEL}")
    print(f"Agent Model: {AGENT_MODEL or AI_MODEL}")
    print(f"Max Turns: {AGENT_MAX_TURNS}")
    print(f"Validation: {'enabled' if VALIDATION_ENABLED else 'disabled'}")
    print("=" * 60)
    yield

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AI Agent Code Generator",
    description="Generate trading agent code using AI",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# CONFIGURATION
# ============================================================================

AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
AI_MODEL = os.getenv("AI_MODEL", None)
VALIDATION_ENABLED = os.getenv("VALIDATION_ENABLED", "true").lower() == "true"

AGENT_MODEL = os.getenv("AGENT_MODEL", None)
AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "15"))

# Get API key based on provider
if AI_PROVIDER == "anthropic":
    AI_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    if not AI_API_KEY:
        raise ValueError("Missing ANTHROPIC_API_KEY environment variable")
    DEFAULT_MODEL = "claude-sonnet-4-5"
elif AI_PROVIDER == "openai":
    AI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not AI_API_KEY:
        raise ValueError("Missing OPENAI_API_KEY environment variable")
    DEFAULT_MODEL = "gpt-5.2"
else:
    raise ValueError(f"Invalid AI_PROVIDER: {AI_PROVIDER}. Must be 'openai' or 'anthropic'")

AI_MODEL = AI_MODEL or DEFAULT_MODEL

# ============================================================================
# INITIALIZE GENERATORS
# ============================================================================

# Agent-based code generator (primary pipeline — reads actual source files)
if AI_PROVIDER != "anthropic":
    raise ValueError("Agent code generation requires Anthropic provider.")

agent_code_generator = AgentCodeGenerator(
    api_key=AI_API_KEY,
    model=AGENT_MODEL or AI_MODEL,
    max_turns=AGENT_MAX_TURNS,
    validate=VALIDATION_ENABLED,
)
print(f"✅ Agent code generator initialized (model: {AGENT_MODEL or AI_MODEL}, max_turns: {AGENT_MAX_TURNS})")

# Backtest spec generator (uses generic AI provider)
ai_provider = get_provider(
    api_key=AI_API_KEY,
    model=AI_MODEL,
    provider=AI_PROVIDER
)
backtest_spec_generator = BacktestSpecGenerator(
    ai_provider=ai_provider,
    validate=VALIDATION_ENABLED
)


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class GenerateRequest(BaseModel):
    """Request for code generation"""
    strategy_description: str = Field(..., description="Trading strategy description")

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_description": "Buy BTC when RSI drops below 30 and MACD histogram crosses above 0. Use ATR-based sizing with $5 risk per trade at 5x leverage."
            }
        }


class GenerateResponse(BaseModel):
    """Response from code generation"""
    success: bool
    initialization_code: Optional[str] = None
    trigger_code: Optional[str] = None
    execution_code: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class GenerateBacktestSpecRequest(BaseModel):
    """Request for backtest strategy_spec generation"""
    strategy_description: str = Field(..., description="Trading strategy description")

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_description": "Trade BTC using EMA 9/21 crossover on 5m candles with 5x leverage and 4% stop loss."
            }
        }


class GenerateBacktestSpecResponse(BaseModel):
    """Response from backtest strategy_spec generation"""
    success: bool
    strategy_spec: Optional[Dict[str, Any]] = None
    notes: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ValidateBacktestSpecRequest(BaseModel):
    strategy_spec: Dict[str, Any] = Field(..., description="backtest strategy_spec payload to validate")


class ValidateBacktestSpecResponse(BaseModel):
    valid: bool
    errors: List[Dict[str, str]]


class StatusResponse(BaseModel):
    """Status check response"""
    status: str
    provider: str
    model: str
    agent_model: str
    max_turns: int
    validation_enabled: bool


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/status", response_model=StatusResponse)
async def status():
    """Health check endpoint"""
    return StatusResponse(
        status="running",
        provider=AI_PROVIDER,
        model=AI_MODEL,
        agent_model=AGENT_MODEL or AI_MODEL,
        max_turns=AGENT_MAX_TURNS,
        validation_enabled=VALIDATION_ENABLED,
    )


@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    """
    Generate trading agent code from a strategy description.
    
    The model reads actual source files (BaseAgent.js, orderExecutor.js, etc.)
    via tool calls to understand exact function signatures before generating code.
    """
    try:
        print(f"\n{'='*60}")
        print(f"📥 Generating code")
        print(f"   Strategy: {request.strategy_description[:100]}...")
        print(f"{'='*60}")

        result = await agent_code_generator.generate_complete_agent(
            strategy_description=request.strategy_description
        )

        metadata = result.get("agent_metadata", {})
        print(f"✅ Code generated — {metadata.get('turns', '?')} turns, "
              f"{metadata.get('tool_calls', '?')} tool calls, "
              f"{metadata.get('total_tokens', '?'):,} tokens")
        print(f"{'='*60}\n")

        return GenerateResponse(
            success=True,
            initialization_code=result["initialization_code"],
            trigger_code=result["trigger_code"],
            execution_code=result["execution_code"],
            metadata=metadata,
        )

    except Exception as e:
        print(f"❌ Generation failed: {str(e)}")
        print(f"{'='*60}\n")
        return GenerateResponse(
            success=False,
            error=str(e)
        )


@app.post("/generate-backtest-spec", response_model=GenerateBacktestSpecResponse)
async def generate_backtest_strategy_spec(request: GenerateBacktestSpecRequest):
    """
    Generate backtest-tool-compatible strategy_spec payload from plain text strategy.
    """
    try:
        print(f"\n{'='*60}")
        print("📥 Generating backtest strategy_spec")
        print(f"{'='*60}")

        result = await backtest_spec_generator.generate_backtest_spec(
            strategy_description=request.strategy_description
        )

        print("✅ backtest strategy_spec generated")
        print(f"{'='*60}\n")

        return GenerateBacktestSpecResponse(
            success=True,
            strategy_spec=result["strategy_spec"],
            notes=result.get("notes", {}),
        )
    except Exception as e:
        print(f"❌ backtest strategy_spec generation failed: {str(e)}")
        print(f"{'='*60}\n")
        return GenerateBacktestSpecResponse(
            success=False,
            error=str(e)
        )


@app.post("/backtest-spec/validate", response_model=ValidateBacktestSpecResponse)
async def validate_backtest_strategy_spec(request: ValidateBacktestSpecRequest):
    """Validate a backtest strategy_spec payload against the backtest-tool contract."""
    valid, errors = validate_backtest_spec(request.strategy_spec)
    return ValidateBacktestSpecResponse(valid=valid, errors=errors)


# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )
