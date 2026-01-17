# AI Agent Code Generator

Comprehensive AI-powered code generation system for Hyperliquid trading agents using state-of-the-art prompting techniques.

## Features

- ✅ **Unified Generation**: All three methods generated together for maximum cohesion
- ✅ **Multi-Provider Support**: Anthropic (Claude) and OpenAI (GPT)
- ✅ **Chain of Thought Reasoning**: Advanced prompting for better code quality
- ✅ **Enhanced Validation**: Comprehensive linting with syntax, logic, and safety checks
- ✅ **Guardrails**: Built-in safety validation and error prevention
- ✅ **Code Validation**: Automatic syntax and logic checking with auto-correction
- ✅ **Retry Mechanism**: Exponential backoff for reliability
- ✅ **Supabase Integration**: Direct storage of generated agents
- ✅ **RESTful API**: Easy integration with frontend
- ✅ **JSON Output**: Structured response format for parsing

## Architecture

```
ai-engine/
├── server.py              # FastAPI server with REST endpoints
├── code_generator.py      # Core unified generation logic
├── ai_providers.py        # AI provider abstractions (Claude/GPT)
├── prompts.py             # Comprehensive system and validation prompts
├── requirements.txt       # Python dependencies
└── env.example            # Environment variables template
```

## Key Design Principles

### Unified Generation
Unlike traditional multi-step generation, this system generates all three methods (`onInitialize`, `setupTriggers`, `executeTrade`) in a **single AI call**. This ensures:
- ✅ Variable consistency across methods
- ✅ Logical cohesion in strategy implementation
- ✅ Better context understanding by the AI
- ✅ Reduced API calls and latency

### Enhanced Validation
The system includes comprehensive code validation with:
- **Syntax Validation**: Ensures valid JavaScript
- **Variable Validation**: Checks for undefined references
- **API Usage Validation**: Verifies correct function calls
- **Logic Validation**: Detects contradictions and errors
- **Safety Validation**: Enforces risk management checks
- **Cohesion Validation**: Ensures methods work together
- **Auto-Correction**: Attempts to fix detected issues

### Linting & Guardrails
Built-in linting system categorizes issues as:
- **Errors**: Must fix (undefined variables, syntax errors)
- **Warnings**: Should fix (missing safety checks, poor practices)
- **Suggestions**: Nice to have (better comments, optimizations)

## Installation

1. **Install Dependencies**
```bash
cd ai-engine
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Set Up Environment**
```bash
cp env.example .env
# Edit .env and add your API keys
```

Required environment variables:
```bash
# AI Provider Configuration
AI_PROVIDER=anthropic  # Options: "anthropic" or "openai"
ANTHROPIC_API_KEY=sk-ant-...  # Required if using Anthropic
OPENAI_API_KEY=sk-...  # Required if using OpenAI

# Supabase credentials
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key

# Optional: Model Configuration
AI_MODEL=  # Leave blank for defaults (claude-sonnet-4-5 or gpt-5.2)

# Optional: Generation Settings
MAX_RETRIES=3
VALIDATION_ENABLED=true
```

## Usage

### Start the Server

**Development:**
```bash
python server.py
```

**Production:**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

### API Endpoints

#### 1. Generate Complete Agent
```bash
POST /generate
```

**Request:**
```json
{
  "user_id": "user_123",
  "agent_name": "RSI Scalper",
  "strategy_description": "Buy BTC when RSI < 30, sell when RSI > 70",
  "strategy_config": {
    "coin": "BTC",
    "rsiPeriod": 14,
    "oversoldLevel": 30,
    "overboughtLevel": 70,
    "positionSize": 0.01
  }
}
```

**Response:**
```json
{
  "success": true,
  "agent_id": "uuid-here",
  "initialization_code": "// Generated initialization code...",
  "trigger_code": "// Generated triggers code...",
  "execution_code": "// Generated execution code...",
  "message": "Agent 'RSI Scalper' created successfully with ID uuid-here"
}
```

#### 2. Regenerate Specific Method
```bash
PUT /agents/{agent_id}/regenerate?method_type=init
```

Query params: `method_type` = `init` | `triggers` | `execution`

**Request:**
```json
{
  "strategy_description": "Updated strategy description",
  "strategy_config": {
    "coin": "BTC",
    "rsiPeriod": 21
  }
}
```

**Response:**
```json
{
  "success": true,
  "agent_id": "uuid-here",
  "method_type": "init",
  "code": "// Regenerated code...",
  "message": "init code regenerated successfully"
}
```

#### 3. Health Check
```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "ai_provider": "anthropic",
  "model": "claude-sonnet-4",
  "validation_enabled": true
}
```

**Note**: The partial generation endpoints (`/generate/init`, `/generate/triggers`, `/generate/execution`) are deprecated in favor of unified generation.

## Prompting Techniques

### 1. Unified Prompt Architecture
- **Single Generation Call**: All three methods generated together
- **Cohesion by Design**: Variables initialized in one method are guaranteed to exist in others
- **Context Preservation**: AI maintains full strategy context across all methods
- **JSON Output**: Structured response for reliable parsing

### 2. System Prompt
- **Role-based prompting**: AI acts as an "elite JavaScript trading agent code generator"
- **Clear constraints**: Only uses documented APIs
- **Safety-first principles**: Emphasizes risk management
- **Step-by-step thinking**: Encourages CoT reasoning before code generation

### 3. User Prompt
- **Strategy description**: Natural language explanation
- **Configuration**: JSON parameters
- **API documentation**: Complete reference of available functions
- **Output specification**: Exact JSON structure required

### 4. Validation Prompt
- **8-point checklist**: Syntax, variables, APIs, logic, safety, cohesion, state, practices
- **Severity levels**: Errors, warnings, suggestions
- **Auto-correction**: Validator attempts to fix issues
- **Lint summary**: Categorized issue counts

## Code Generation Flow

```
1. User Request
   ↓
2. Unified Generation Call
   - Generate all three methods together
   - onInitialize() + setupTriggers() + executeTrade()
   ↓
3. Parse JSON Response
   - Extract initialization_code
   - Extract trigger_code
   - Extract execution_code
   ↓
4. Comprehensive Validation
   - Syntax checking
   - Variable validation
   - API usage verification
   - Logic validation
   - Safety checks
   - Cohesion analysis
   ↓
5. Auto-Correction (if needed)
   - Fix common errors
   - Retry if necessary
   ↓
6. Store in Supabase
   ↓
7. Return Agent ID + Code
```

## Example Strategies

### RSI Mean Reversion
```json
{
  "strategy_description": "Buy when RSI < 30 (oversold), sell when RSI > 70 (overbought). Use 14-period RSI on 1h candles. Close opposite positions before opening new ones.",
  "strategy_config": {
    "coin": "BTC",
    "rsiPeriod": 14,
    "oversoldLevel": 30,
    "overboughtLevel": 70,
    "positionSize": 0.01,
    "interval": "1h"
  }
}
```

### EMA Crossover
```json
{
  "strategy_description": "Buy when fast EMA (12) crosses above slow EMA (26), sell when it crosses below. Check every minute.",
  "strategy_config": {
    "coin": "ETH",
    "fastPeriod": 12,
    "slowPeriod": 26,
    "positionSize": 0.1,
    "interval": "1h",
    "checkInterval": 60000
  }
}
```

### Price Breakout
```json
{
  "strategy_description": "Buy BTC when price breaks above $100,000, sell when it drops below $95,000. Use 5x leverage.",
  "strategy_config": {
    "coin": "BTC",
    "breakoutPrice": 100000,
    "exitPrice": 95000,
    "positionSize": 0.05,
    "leverage": 5
  }
}
```

## Error Handling

The system includes comprehensive error handling:

- **Validation Errors**: Returns detailed error messages
- **API Failures**: Automatic retry with exponential backoff
- **Syntax Errors**: Attempts auto-correction
- **Database Errors**: Proper HTTP status codes

## Best Practices

1. **Clear Strategy Descriptions**: Be specific about entry/exit conditions
2. **Sensible Config Values**: Use realistic position sizes and parameters
3. **Test on Testnet First**: Always test generated agents on testnet
4. **Monitor Logs**: Check server logs for generation details
5. **Iterate**: Use regenerate endpoint to refine specific methods

## Testing

```bash
# Test the server
curl http://localhost:8000/health

# Test code generation
python test_generator.py
```

## Deployment

### Docker (Recommended)
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables for Production
- Set `ENVIRONMENT=production`
- Use service role key for Supabase
- Configure appropriate CORS origins
- Set up rate limiting

## Monitoring

- **Health Endpoint**: `/health` for uptime monitoring
- **Logs**: Server logs include generation progress
- **Supabase**: Track agent creation and usage

## Limitations

- Maximum 4000 tokens per generation (configurable)
- Code validation is heuristic-based
- Requires valid Supabase schema
- AI may occasionally generate invalid code (retry mechanism helps)

## Future Enhancements

- [ ] Code playground for testing generated code
- [ ] Strategy templates library
- [ ] Multi-coin support
- [ ] Backtesting integration
- [ ] Performance analytics
- [ ] Version control for agent code

## Support

For issues or questions:
1. Check server logs for detailed error messages
2. Verify environment variables are set correctly
3. Ensure Supabase schema matches expected structure
4. Test with simple strategies first

## License

MIT
