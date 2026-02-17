# AI Agent Code Generator

Generates production-ready JavaScript trading agent code for Hyperliquid perpetual futures using an agentic AI pipeline. The model reads actual source files via tool calls to understand exact function signatures before generating code — eliminating documentation drift entirely.

## How It Works

Unlike traditional prompt-based code generation where API docs are embedded in the system prompt, this system gives the AI model **tools to read the actual source code** of the trading framework. The model:

1. Receives the user's strategy description
2. Calls `read_source_file()` to inspect `BaseAgent.js`, `orderExecutor.js`, `ws.js`, etc.
3. Reads few-shot examples to understand expected code quality
4. Reasons through a 5-step thinking framework (classify, data architecture, lifecycle, sizing, logging)
5. Generates code with full knowledge of real function signatures and return types
6. Post-generation lint/syntax checks catch remaining issues, with self-correction if needed

This means when someone adds a method to `orderExecutor.js` or changes a return shape in `perpMarket.js`, the AI automatically picks it up next generation. Zero documentation maintenance.

## Architecture

```
ai-engine/
├── server.py                 # FastAPI server (4 endpoints)
├── agent_generator.py        # Agentic code generation + lint/syntax checks
├── agent_prompts.py          # System prompt, thinking framework, rules
├── ai_providers.py           # AI provider abstraction (Anthropic/OpenAI)
├── backtest_spec_generator.py    # Backtest spec generation
├── backtest_spec_prompts.py      # Backtest spec prompts
├── backtest_spec_schema.py       # Backtest spec validation
├── source_files/             # Hyperliquid JS source files (read by the model)
│   ├── BaseAgent.js
│   ├── orderExecutor.js
│   ├── ws.js
│   ├── perpMarket.js
│   ├── perpUser.js
│   ├── PositionTracker.js
│   ├── TechnicalIndicatorService.js
│   ├── config.js
│   ├── utils.js
│   ├── apiClient.js
│   ├── OrderOwnershipStore.js
│   ├── fewshot_example_a.json
│   └── fewshot_example_b.json
├── requirements.txt
├── PROMPT_IMPROVEMENTS.md    # Backlog of issues from stress testing
└── .env
```

## Setup

```bash
cd ai-engine
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
AI_PROVIDER=anthropic

# Optional
AI_MODEL=claude-sonnet-4-5          # Default model for backtest spec generation
AGENT_MODEL=                        # Override model for code generation (defaults to AI_MODEL)
AGENT_MAX_TURNS=15                  # Max agentic loop iterations
VALIDATION_ENABLED=true             # Enable post-generation lint/syntax checks
```

## API Endpoints

### `POST /generate` — Generate Trading Agent Code

The primary endpoint. Takes a plain-text strategy description, returns three JavaScript method bodies.

**Request:**
```json
{
  "strategy_description": "Buy BTC when RSI drops below 30 and MACD histogram crosses above 0. Use ATR-based sizing with $5 risk per trade at 5x leverage."
}
```

**Response:**
```json
{
  "success": true,
  "initialization_code": "// onInitialize() body...",
  "trigger_code": "// setupTriggers() body...",
  "execution_code": "// executeTrade(triggerData) body...",
  "metadata": {
    "turns": 4,
    "tool_calls": 6,
    "files_read": ["BaseAgent.js", "orderExecutor.js", "perpMarket.js", "fewshot_example_a.json"],
    "total_tokens": 45230,
    "input_tokens": 38100,
    "output_tokens": 7130,
    "thinking_tokens": 4200
  }
}
```

### `POST /generate-backtest-spec` — Generate Backtest Strategy Spec

Generates a backtest-tool-compatible `strategy_spec` payload from plain text.

**Request:**
```json
{
  "strategy_description": "Trade BTC using EMA 9/21 crossover on 5m candles with 5x leverage and 4% stop loss."
}
```

### `POST /backtest-spec/validate` — Validate Backtest Spec

Validates a `strategy_spec` payload against the backtest-tool contract.

**Request:**
```json
{
  "strategy_spec": { ... }
}
```

### `GET /status` — Health Check

```json
{
  "status": "running",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5",
  "agent_model": "claude-sonnet-4-5",
  "max_turns": 15,
  "validation_enabled": true
}
```

## Running

**Development:**
```bash
python server.py
```

**Production:**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

## Keeping Source Files in Sync

The `source_files/` directory contains copies of the Hyperliquid JavaScript source files that the AI model reads during code generation. When the Hyperliquid codebase changes, copy the updated files:

```bash
cp ../hyperliquid/BaseAgent.js source_files/
cp ../hyperliquid/orderExecutor.js source_files/
# etc.
```

Only whitelisted files can be read by the model (defined in `agent_generator.py`). The model cannot read `.env`, credentials, or any file outside the whitelist.

## Post-Generation Checks

After the model generates code, automated checks run:

- **Syntax validation** via esprima (JavaScript parser)
- **Lint checks** via regex patterns:
  - Missing `await` on async calls
  - Sandboxing violations (`cancelAllOrders`, `closePosition` without size)
  - Hallucinated APIs (`this.logger`, `this.log`)
  - Wrong argument counts (`checkSafetyLimits` with 3 args instead of 2)
  - Deprecated methods (`syncPositions`)
  - Direct `positionTracker` access where wrappers exist

If issues are found, a self-correction pass sends them back to the model within the same conversation context for fixing.
