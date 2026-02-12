"""
FastAPI Server for AI Agent Code Generation

Endpoints:
- POST /code - Generate complete agent code and store in Supabase
- GET /status - Health check
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import os
from dotenv import load_dotenv
from supabase import create_client, Client

from ai_providers import get_provider
from code_generator import CodeGenerator
from strategy_spec_generator import StrategySpecGenerator
from strategy_spec_schema import validate_strategy_spec

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
    print(f"Validation: {'enabled' if VALIDATION_ENABLED else 'disabled'}")
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
    validate=VALIDATION_ENABLED
)
strategy_spec_generator = StrategySpecGenerator(
    ai_provider=ai_provider,
    validate=VALIDATION_ENABLED,
    code_generator=code_generator
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


class GenerateSpecRequest(BaseModel):
    """Request for strategy_spec generation"""
    strategy_description: str = Field(..., description="Trading strategy description")
    include_code_fallback: bool = Field(
        False,
        description="Also generate JS fallback code bundle"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_description": "Buy BTC when RSI(14,1h) drops below 30 and sell above 70. Use 5x leverage.",
                "include_code_fallback": True
            }
        }


class CreateAgentRequest(BaseModel):
    """Request to create agent in Supabase from generated code"""
    user_id: str = Field(..., description="User ID")
    agent_name: str = Field(..., description="Agent name")
    strategy_description: str = Field(..., description="Trading strategy description")
    initialization_code: Optional[str] = Field("", description="Initialization code")
    trigger_code: Optional[str] = Field("", description="Trigger code")
    execution_code: Optional[str] = Field("", description="Execution code")
    strategy_spec: Optional[Dict[str, Any]] = Field(None, description="Declarative strategy spec payload")
    strategy_runtime: Optional[str] = Field(
        None,
        description="Runtime mode override: code, spec, hybrid"
    )
    config: Optional[Dict[str, Any]] = Field(None, description="Additional config payload")
    hyperliquid_address: str = Field(..., description="Hyperliquid wallet address")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "agent_name": "RSI Scalper",
                "strategy_description": "Buy BTC when RSI drops below 30",
                "initialization_code": "console.log('init')",
                "trigger_code": "this.registerScheduledTrigger(60000, async (data) => {})",
                "execution_code": "console.log('execute')",
                "hyperliquid_address": "0x..."
            }
        }


class RunAgentRequest(BaseModel):
    """Request to run an agent"""
    agent_id: str = Field(..., description="Agent UUID from Supabase")
    
    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000"
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


class GenerateSpecResponse(BaseModel):
    """Response from strategy_spec generation"""
    success: bool
    strategy_spec: Optional[Dict[str, Any]] = None
    notes: Optional[Dict[str, Any]] = None
    code_fallback: Optional[Dict[str, str]] = None
    error: Optional[str] = None


class CreateAgentResponse(BaseModel):
    """Response from agent creation"""
    success: bool
    agent_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class RunAgentResponse(BaseModel):
    """Response from running agent"""
    success: bool
    agent_id: Optional[str] = None
    message: Optional[str] = None
    pid: Optional[int] = None
    error: Optional[str] = None


class StatusResponse(BaseModel):
    """Status check response"""
    status: str
    provider: str
    model: str
    validation_enabled: bool


class ValidateSpecRequest(BaseModel):
    strategy_spec: Dict[str, Any] = Field(..., description="strategy_spec payload to validate")


class ValidateSpecResponse(BaseModel):
    valid: bool
    errors: List[Dict[str, str]]


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


@app.post("/spec/validate", response_model=ValidateSpecResponse)
async def validate_spec(request: ValidateSpecRequest):
    """Validate a strategy_spec payload against the tool contract."""
    valid, errors = validate_strategy_spec(request.strategy_spec)
    return ValidateSpecResponse(valid=valid, errors=errors)


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


@app.post("/generate-spec", response_model=GenerateSpecResponse)
async def generate_strategy_spec(request: GenerateSpecRequest):
    """
    Generate strategy_spec payload for declarative/hybrid runtime.
    Optionally include JS fallback code bundle.
    """
    try:
        print(f"\n{'='*60}")
        print("📥 Generating strategy_spec")
        print(f"{'='*60}")

        result = await strategy_spec_generator.generate_hybrid_bundle(
            strategy_description=request.strategy_description,
            include_code_fallback=request.include_code_fallback
        )

        print("✅ strategy_spec generated")
        print(f"{'='*60}\n")

        return GenerateSpecResponse(
            success=True,
            strategy_spec=result["strategy_spec"],
            notes=result.get("notes", {}),
            code_fallback=result.get("code_fallback")
        )
    except Exception as e:
        print(f"❌ strategy_spec generation failed: {str(e)}")
        print(f"{'='*60}\n")
        return GenerateSpecResponse(
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


@app.post("/create-agent", response_model=CreateAgentResponse)
async def create_agent(request: CreateAgentRequest):
    """
    Create agent in Supabase from already generated code
    """
    try:
        print(f"\n{'='*60}")
        print(f"📝 Creating agent: {request.agent_name}")
        print(f"{'='*60}")
        
        has_spec = request.strategy_spec is not None
        has_code = all([
            bool((request.initialization_code or "").strip()),
            bool((request.trigger_code or "").strip()),
            bool((request.execution_code or "").strip())
        ])

        if not has_spec and not has_code:
            return CreateAgentResponse(
                success=False,
                error="Provide either strategy_spec or all three code sections"
            )

        strategy_runtime = request.strategy_runtime
        if strategy_runtime is None:
            strategy_runtime = "hybrid" if (has_spec and has_code) else ("spec" if has_spec else "code")

        config_payload = dict(request.config or {})
        if has_spec:
            config_payload.setdefault("strategy_spec", request.strategy_spec)
            config_payload.setdefault("strategy_runtime", strategy_runtime)

        insert_payload = {
            "user_id": request.user_id,
            "agent_name": request.agent_name,
            "strategy_description": request.strategy_description,
            "initialization_code": request.initialization_code or "",
            "trigger_code": request.trigger_code or "",
            "execution_code": request.execution_code or "",
            "hyperliquid_address": request.hyperliquid_address,
            "status": "stopped",
            "agent_deployed": False,
            "instruction": "RUN",
            "config": config_payload if config_payload else None
        }

        if has_spec:
            insert_payload["strategy_runtime"] = strategy_runtime
            insert_payload["strategy_spec"] = request.strategy_spec
            insert_payload["strategy_spec_version"] = request.strategy_spec.get("version")

        # Store in Supabase. If newer columns do not exist yet, fallback to config-only storage.
        try:
            db_result = supabase.table("agents").insert(insert_payload).execute()
        except Exception as insert_error:
            error_str = str(insert_error)
            if has_spec and (
                "strategy_spec" in error_str
                or "strategy_runtime" in error_str
                or "strategy_spec_version" in error_str
            ):
                fallback_payload = dict(insert_payload)
                fallback_payload.pop("strategy_runtime", None)
                fallback_payload.pop("strategy_spec", None)
                fallback_payload.pop("strategy_spec_version", None)
                db_result = supabase.table("agents").insert(fallback_payload).execute()
            else:
                raise
        
        agent_id = db_result.data[0]["id"]
        
        print(f"✅ Agent created in Supabase: {agent_id}")
        print(f"{'='*60}\n")
        
        return CreateAgentResponse(
            success=True,
            agent_id=agent_id,
            message=f"Agent '{request.agent_name}' created successfully with ID: {agent_id}"
        )
        
    except Exception as e:
        print(f"❌ Failed: {str(e)}")
        print(f"{'='*60}\n")
        return CreateAgentResponse(
            success=False,
            error=str(e)
        )


@app.post("/run-agent", response_model=RunAgentResponse)
async def run_agent(request: RunAgentRequest):
    """
    Run an agent using agentRunner (spawns a subprocess)
    """
    try:
        import subprocess
        import os
        
        print(f"\n{'='*60}")
        print(f"🚀 Starting agent: {request.agent_id}")
        print(f"{'='*60}")
        
        # Check if agent exists
        agent_check = supabase.table("agents").select("id, agent_name, status").eq("id", request.agent_id).execute()
        
        if not agent_check.data or len(agent_check.data) == 0:
            return RunAgentResponse(
                success=False,
                error=f"Agent {request.agent_id} not found in database"
            )
        
        agent_data = agent_check.data[0]
        agent_name = agent_data.get("agent_name", "Unknown")
        
        # Path to hyperliquid directory and agentRunner.js
        hyperliquid_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hyperliquid")
        agent_runner_path = os.path.join(hyperliquid_dir, "agentRunner.js")
        
        if not os.path.exists(agent_runner_path):
            return RunAgentResponse(
                success=False,
                error=f"agentRunner.js not found at {agent_runner_path}"
            )
        
        # Start agent in background
        process = subprocess.Popen(
            ["node", agent_runner_path, request.agent_id],
            cwd=hyperliquid_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # Detach from parent process
        )
        
        print(f"✅ Agent started with PID: {process.pid}")
        print(f"   Agent: {agent_name}")
        print(f"   ID: {request.agent_id}")
        print(f"{'='*60}\n")
        
        return RunAgentResponse(
            success=True,
            agent_id=request.agent_id,
            message=f"Agent '{agent_name}' started successfully",
            pid=process.pid
        )
        
    except Exception as e:
        print(f"❌ Failed: {str(e)}")
        print(f"{'='*60}\n")
        return RunAgentResponse(
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
