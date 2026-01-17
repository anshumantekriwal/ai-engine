"""
FastAPI Server for AI Agent Code Generation

Endpoints:
- POST /code - Generate complete agent code and store in Supabase
- GET /status - Health check
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import os
from dotenv import load_dotenv
from supabase import create_client, Client

from ai_providers import get_provider
from code_generator import CodeGenerator

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # Startup
    print("=" * 60)
    print("🚀 AI Agent Code Generator")
    print("=" * 60)
    print(f"Provider: {AI_PROVIDER.upper()}")
    print(f"Model: {AI_MODEL}")
    print(f"Validation: {'Enabled' if VALIDATION_ENABLED else 'Disabled'}")
    print("=" * 60)
    yield
    # Shutdown (if needed)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AI Agent Code Generator",
    description="Generate trading agent code using AI",
    version="1.0.0",
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

# Supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# AI Configuration
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
AI_MODEL = os.getenv("AI_MODEL", None)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
VALIDATION_ENABLED = os.getenv("VALIDATION_ENABLED", "true").lower() == "true"

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

# Use model from env or default
AI_MODEL = AI_MODEL or DEFAULT_MODEL

# Initialize AI provider and code generator
ai_provider = get_provider(
    api_key=AI_API_KEY,
    model=AI_MODEL,
    provider=AI_PROVIDER
)
code_generator = CodeGenerator(
    ai_provider=ai_provider,
    max_retries=MAX_RETRIES,
    validate=VALIDATION_ENABLED
)


# ============================================================================
# MODELS
# ============================================================================

class CodeRequest(BaseModel):
    """Request for code generation"""
    user_id: str = Field(..., description="User ID")
    agent_name: str = Field(..., description="Agent name")
    strategy_description: str = Field(..., description="Trading strategy description")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "agent_name": "RSI Scalper",
                "strategy_description": "Buy BTC when RSI drops below 30, sell when RSI rises above 70. Use 14-period RSI on 1h candles. Trade 0.01 BTC per signal."
            }
        }


class GenerateRequest(BaseModel):
    """Request for code generation only (no storage)"""
    strategy_description: str = Field(..., description="Trading strategy description")
    
    class Config:
        json_schema_extra = {
            "example": {
                "strategy_description": "Buy BTC when RSI drops below 30, sell when RSI rises above 70. Use 14-period RSI on 1h candles. Trade 0.01 BTC per signal."
            }
        }


class CodeResponse(BaseModel):
    """Response from code generation"""
    success: bool
    agent_id: Optional[str] = None
    initialization_code: Optional[str] = None
    trigger_code: Optional[str] = None
    execution_code: Optional[str] = None
    error: Optional[str] = None


class GenerateResponse(BaseModel):
    """Response from code generation only"""
    success: bool
    initialization_code: Optional[str] = None
    trigger_code: Optional[str] = None
    execution_code: Optional[str] = None
    error: Optional[str] = None


class StatusResponse(BaseModel):
    """Status check response"""
    status: str
    provider: str
    model: str
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
        validation_enabled=VALIDATION_ENABLED
    )


@app.post("/generate", response_model=GenerateResponse)
async def generate_code_only(request: GenerateRequest):
    """
    Generate agent code without storing in database
    Just returns the generated code
    """
    try:
        print(f"\n{'='*60}")
        print(f"📥 Generating code")
        print(f"{'='*60}")
        
        # Generate code
        result = await code_generator.generate_complete_agent(
            strategy_description=request.strategy_description
        )
        
        print(f"✅ Code generated")
        print(f"{'='*60}\n")
        
        return GenerateResponse(
            success=True,
            initialization_code=result["initialization_code"],
            trigger_code=result["trigger_code"],
            execution_code=result["execution_code"]
        )
        
    except Exception as e:
        print(f"❌ Failed: {str(e)}")
        print(f"{'='*60}\n")
        return GenerateResponse(
            success=False,
            error=str(e)
        )


@app.post("/code", response_model=CodeResponse)
async def generate_and_store(request: CodeRequest):
    """
    Generate complete agent code and store in Supabase
    """
    try:
        print(f"\n{'='*60}")
        print(f"📥 Generating code for: {request.agent_name}")
        print(f"{'='*60}")
        
        # Generate code
        result = await code_generator.generate_complete_agent(
            strategy_description=request.strategy_description
        )
        
        # Store in Supabase
        db_result = supabase.table("agents").insert({
            "user_id": request.user_id,
            "agent_name": request.agent_name,
            "strategy_description": request.strategy_description,
            "initialization_code": result["initialization_code"],
            "trigger_code": result["trigger_code"],
            "execution_code": result["execution_code"],
            "status": "stopped",
            "agent_deployed": False
        }).execute()
        
        agent_id = db_result.data[0]["id"]
        
        print(f"✅ Agent created: {agent_id}")
        print(f"{'='*60}\n")
        
        return CodeResponse(
            success=True,
            agent_id=agent_id,
            initialization_code=result["initialization_code"],
            trigger_code=result["trigger_code"],
            execution_code=result["execution_code"]
        )
        
    except Exception as e:
        print(f"❌ Failed: {str(e)}")
        print(f"{'='*60}\n")
        return CodeResponse(
            success=False,
            error=str(e)
        )


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
