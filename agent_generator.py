"""
Agent-based Code Generator using native Anthropic tool_use.

Instead of stuffing all API documentation into the system prompt, this generator
gives the model tools to READ the actual source files. The model reads BaseAgent.js,
orderExecutor.js, ws.js, etc. to understand exact function signatures and patterns
before generating code.

This eliminates documentation drift — the source IS the documentation.

Architecture:
1. System prompt contains: role, thinking framework, rules, few-shot examples
2. Model receives user's strategy description
3. Model calls read_source_file() to inspect the actual JavaScript source
4. Model generates code with full knowledge of real function signatures
5. Post-generation: same syntax + lint checks as the original pipeline
"""

from typing import Dict, Any, Optional, List
import json
import os
import re
import asyncio
import logging

from anthropic import AsyncAnthropic

try:
    import esprima
    ESPRIMA_AVAILABLE = True
except ImportError:
    ESPRIMA_AVAILABLE = False

logger = logging.getLogger(__name__)


# ─── Post-Generation Checks ──────────────────────────────────────────

def _syntax_check(js_code: str) -> Optional[str]:
    """Run esprima syntax check on JS code. Returns error string or None."""
    if not ESPRIMA_AVAILABLE or not js_code.strip():
        return None
    wrapped = f"(async function() {{\n{js_code}\n}})()"
    try:
        esprima.parseScript(wrapped, tolerant=True)
        return None
    except Exception as e:
        return str(e)


def _lint_check(js_code: str) -> List[str]:
    """Regex-based lint checks for common issues. Returns list of error strings."""
    errors = []
    if not js_code.strip():
        return errors

    # Async methods that must be awaited
    async_patterns = [
        r'(?<!await\s)this\.orderExecutor\.\w+\s*\(',
        r'(?<!await\s)this\.logTrade\s*\(',
        r'(?<!await\s)this\.reconcileTrackedPositions\s*\(',
        r'(?<!await\s)this\.updateState\s*\(',
        r'(?<!await\s)this\.checkSafetyLimits\s*\(',
        r'(?<!await\s)getAllMids\s*\(',
        r'(?<!await\s)getCandleSnapshot\s*\(',
        r'(?<!await\s)getTicker\s*\(',
        r'(?<!await\s)getUserFills\s*\(',
        r'(?<!await\s)getUserFillsByTime\s*\(',
        r'(?<!await\s)getL2Book\s*\(',
        r'(?<!await\s)getFundingHistory\s*\(',
        r'(?<!await\s)getPredictedFundings\s*\(',
        r'(?<!await\s)getMetaAndAssetCtxs\s*\(',
        r'(?<!await\s)getPortfolio\s*\(',
        r'(?<!await\s)getUserFees\s*\(',
    ]
    for pattern in async_patterns:
        match = re.search(pattern, js_code)
        if match:
            snippet = match.group(0).strip()[:60]
            errors.append(f"Missing `await` on async call: `{snippet}`")

    # Sandboxing: dangerous account-wide operations
    if re.search(r'cancelAllOrders\s*\(', js_code):
        errors.append("Using `cancelAllOrders` — use `cancelAgentOrders` instead (sandboxing)")
    if re.search(r'closePosition\s*\(\s*\w+\s*\)', js_code):
        if not re.search(r'closePosition\s*\(\s*\w+\s*,\s*', js_code):
            errors.append("Calling `closePosition(coin)` without size — closes ENTIRE account position. Pass explicit size.")

    # Hallucinated APIs
    if re.search(r'this\.logger\b', js_code):
        errors.append("`this.logger` does NOT exist. Use `console.log` or `this.updateState()`")
    if re.search(r'this\.log\s*\(', js_code):
        errors.append("`this.log()` does NOT exist. Use `console.log` or `this.updateState()`")

    # Direct positionTracker access where wrappers exist
    if re.search(r'this\.positionTracker\.getClosedPositions\b', js_code):
        errors.append("Use `this.getTrackedClosedPositions()` wrapper instead of `this.positionTracker.getClosedPositions()`")
    if re.search(r'this\.positionTracker\.getAllOpenPositions\b', js_code):
        errors.append("Use `this.getTrackedOpenPositions()` wrapper instead of `this.positionTracker.getAllOpenPositions()`")

    # checkSafetyLimits with wrong argument count
    safety_calls = re.findall(r'checkSafetyLimits\s*\(([^)]+)\)', js_code)
    for call_args in safety_calls:
        arg_count = len([a.strip() for a in call_args.split(',') if a.strip()])
        if arg_count != 2:
            errors.append(
                f"`checkSafetyLimits` called with {arg_count} args — takes exactly 2: (coin, proposedSize)"
            )

    # Deprecated syncPositions
    if re.search(r'\bsyncPositions\s*\(', js_code):
        errors.append("`syncPositions()` is deprecated — use `reconcileTrackedPositions()`")

    return errors


def _run_all_checks(
    initialization_code: str,
    trigger_code: str,
    execution_code: str,
) -> Dict[str, List[str]]:
    """Run syntax and lint checks on all three code sections."""
    syntax_errors = []
    lint_issues = []

    for label, code in [
        ("initialization", initialization_code),
        ("triggers", trigger_code),
        ("execution", execution_code),
    ]:
        err = _syntax_check(code)
        if err:
            syntax_errors.append(f"[{label}] {err}")
        for issue in _lint_check(code):
            lint_issues.append(f"[{label}] {issue}")

    return {"syntax_errors": syntax_errors, "lint_issues": lint_issues}

# ─── File Access Control ──────────────────────────────────────────────

# Only these files can be read by the agent. Security boundary.
ALLOWED_SOURCE_FILES = {
    'BaseAgent.js',
    'orderExecutor.js',
    'ws.js',
    'perpMarket.js',
    'perpUser.js',
    'PositionTracker.js',
    'TechnicalIndicatorService.js',
    'config.js',
    'utils.js',
    'apiClient.js',
    'OrderOwnershipStore.js',
}

# Few-shot example files (read-only, shown to model on request)
ALLOWED_EXAMPLE_FILES = {
    'fewshot_example_a.json',
    'fewshot_example_b.json',
}

ALL_ALLOWED_FILES = ALLOWED_SOURCE_FILES | ALLOWED_EXAMPLE_FILES

# ─── Tool Definitions ────────────────────────────────────────────────

TOOLS = [
    {
        "name": "read_source_file",
        "description": (
            "Read a JavaScript source file from the Hyperliquid trading framework. "
            "Use this to understand exact function signatures, return types, available methods, "
            "and implementation details before generating code. "
            "Available files: BaseAgent.js, orderExecutor.js, ws.js, perpMarket.js, perpUser.js, "
            "PositionTracker.js, TechnicalIndicatorService.js, config.js, utils.js, apiClient.js, "
            "OrderOwnershipStore.js. "
            "Also available: fewshot_example_a.json, fewshot_example_b.json (working strategy examples)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "The filename to read. Must be one of the allowed source files. "
                        "Example: 'BaseAgent.js', 'orderExecutor.js'"
                    )
                }
            },
            "required": ["filename"]
        }
    },
    {
        "name": "list_source_files",
        "description": (
            "List all available source files in the Hyperliquid trading framework "
            "with their sizes. Use this to decide which files to read."
        ),
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

# ─── Retry Logic ──────────────────────────────────────────────────────

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def _is_retryable(exc: Exception) -> bool:
    if hasattr(exc, "status_code") and getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
        return True
    err_name = type(exc).__name__.lower()
    if any(kw in err_name for kw in ("timeout", "connection", "overloaded", "ratelimit")):
        return True
    return False


async def _retry_api_call(fn, max_retries=3, base_delay=2.0):
    import random
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** attempt), 30.0)
            delay *= 1.0 + random.uniform(-0.3, 0.3)
            logger.warning("API call failed (attempt %d/%d): %s — retrying in %.1fs",
                           attempt + 1, max_retries + 1, exc, delay)
            await asyncio.sleep(delay)


# ─── Agent Code Generator ────────────────────────────────────────────

class AgentCodeGenerator:
    """
    Generates trading agent code using an agentic loop.
    
    The model reads actual source files via tool calls, then generates code
    with full knowledge of the real API surface. No hand-written documentation needed.
    
    Flow:
    1. Model receives system prompt (rules, thinking framework, examples) + user strategy
    2. Model calls read_source_file() to inspect relevant JS files
    3. Model generates JSON with initialization_code, trigger_code, execution_code
    4. Post-generation lint checks catch remaining issues
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        source_dir: Optional[str] = None,
        max_turns: int = 15,
        validate: bool = True,
        thinking: bool = True,
    ):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_turns = max_turns
        self.validate = validate
        self.thinking = thinking

        # Resolve source_files directory
        if source_dir:
            self.source_dir = source_dir
        else:
            self.source_dir = os.path.join(os.path.dirname(__file__), "source_files")

        if not os.path.isdir(self.source_dir):
            raise FileNotFoundError(
                f"Source files directory not found: {self.source_dir}. "
                f"Copy the Hyperliquid JS files into ai-engine/source_files/"
            )

    # ─── Tool Handlers ────────────────────────────────────────────

    def _handle_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool call and return the result as a string."""

        if tool_name == "read_source_file":
            return self._read_source_file(tool_input.get("filename", ""))

        elif tool_name == "list_source_files":
            return self._list_source_files()

        else:
            return f"Error: Unknown tool '{tool_name}'"

    def _read_source_file(self, filename: str) -> str:
        """Read a source file, with security restrictions."""
        if not filename:
            return "Error: filename is required"

        if filename not in ALL_ALLOWED_FILES:
            available = ", ".join(sorted(ALL_ALLOWED_FILES))
            return f"Error: '{filename}' is not an allowed file. Available: {available}"

        filepath = os.path.join(self.source_dir, filename)
        if not os.path.exists(filepath):
            return f"Error: File '{filename}' not found in source_files directory."

        try:
            with open(filepath, 'r') as f:
                content = f.read()

            # For very large files, add a size note
            line_count = content.count('\n') + 1
            size_kb = len(content) / 1024

            header = f"// File: {filename} ({line_count} lines, {size_kb:.1f} KB)\n"
            return header + content

        except Exception as e:
            return f"Error reading '{filename}': {str(e)}"

    def _list_source_files(self) -> str:
        """List available source files with sizes and descriptions."""
        file_info = {
            'BaseAgent.js': 'Core class — your code runs here. Triggers, state management, position tracking wrappers.',
            'orderExecutor.js': 'Order placement, cancellation, leverage, fee estimation. All this.orderExecutor.* methods.',
            'ws.js': 'WebSocket manager — subscribeAllMids, subscribeTrades, subscribeL2Book, etc.',
            'perpMarket.js': 'Market data — getAllMids, getCandleSnapshot, getTicker, getFundingHistory, etc.',
            'perpUser.js': 'User data — getUserFills, getPortfolio, getUserFees, etc.',
            'PositionTracker.js': 'Local position/PnL tracking — used by getTrackedOpenPositions, getPnlSummary, etc.',
            'TechnicalIndicatorService.js': 'Technical indicators — RSI, EMA, SMA, MACD, BollingerBands, etc.',
            'config.js': 'Default config values — fee rates, intervals, limits.',
            'utils.js': 'Utility functions — toPrecision, sleep, retryWithBackoff.',
            'apiClient.js': 'HTTP client for Hyperliquid info API.',
            'OrderOwnershipStore.js': 'Tracks which orders belong to this agent (sandboxing).',
            'fewshot_example_a.json': 'Working example: RSI+BB mean reversion with limit orders.',
            'fewshot_example_b.json': 'Working example: WS dip buyer with trailing stop (multi-coin).',
        }

        lines = ["Available source files:\n"]
        for filename in sorted(ALL_ALLOWED_FILES):
            filepath = os.path.join(self.source_dir, filename)
            if os.path.exists(filepath):
                size = os.path.getsize(filepath)
                desc = file_info.get(filename, '')
                lines.append(f"  {filename} ({size / 1024:.1f} KB) — {desc}")
            else:
                lines.append(f"  {filename} — NOT FOUND")

        lines.append("\nRecommended reading order:")
        lines.append("  1. ALWAYS read BaseAgent.js first (understand how your code integrates)")
        lines.append("  2. ALWAYS read orderExecutor.js (understand order placement API)")
        lines.append("  3. Read ws.js if strategy needs real-time data")
        lines.append("  4. Read perpMarket.js / perpUser.js for data functions you need")
        lines.append("  5. Read TechnicalIndicatorService.js if using indicators outside triggers")
        lines.append("  6. Read fewshot examples to see the expected code quality and patterns")

        return "\n".join(lines)

    # ─── JSON Extraction ──────────────────────────────────────────

    def _extract_json_from_response(self, response) -> Optional[Dict[str, Any]]:
        """Extract JSON from the model's final text response."""
        for block in response.content:
            if hasattr(block, 'text') and block.text:
                text = block.text.strip()

                # Try direct parse first
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass

                # Extract from markdown code block
                if "```json" in text:
                    start = text.find("```json") + 7
                    end = text.find("```", start)
                    if end > start:
                        try:
                            return json.loads(text[start:end].strip())
                        except json.JSONDecodeError:
                            pass

                elif "```" in text:
                    start = text.find("```") + 3
                    end = text.find("```", start)
                    if end > start:
                        try:
                            return json.loads(text[start:end].strip())
                        except json.JSONDecodeError:
                            pass

                # Try to find JSON object in the text
                brace_start = text.find('{')
                if brace_start >= 0:
                    depth = 0
                    for i in range(brace_start, len(text)):
                        if text[i] == '{':
                            depth += 1
                        elif text[i] == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    return json.loads(text[brace_start:i + 1])
                                except json.JSONDecodeError:
                                    break

        return None

    # ─── Main Generation Loop ─────────────────────────────────────

    async def generate_complete_agent(
        self,
        strategy_description: str,
    ) -> Dict[str, str]:
        """
        Generate all three method bodies using the agentic loop.
        
        The model reads source files via tool calls, reasons about the strategy,
        and produces code that matches the actual API surface.
        """
        from agent_prompts import AGENT_SYSTEM_PROMPT, build_agent_user_prompt

        system_prompt = AGENT_SYSTEM_PROMPT
        user_prompt = build_agent_user_prompt(strategy_description)

        print("🤖 Agent-based code generation starting...")
        print(f"Strategy: {strategy_description[:100]}...")
        print(f"Model: {self.model}, Max turns: {self.max_turns}")

        messages = [{"role": "user", "content": user_prompt}]

        files_read = []
        total_tool_calls = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_thinking_tokens = 0
        total_cache_read_tokens = 0
        total_cache_creation_tokens = 0

        for turn in range(self.max_turns):
            print(f"\n📡 Turn {turn + 1}/{self.max_turns}...")

            async def _api_call():
                kwargs = dict(
                    model=self.model,
                    system=system_prompt,
                    messages=messages,
                    tools=TOOLS,
                    max_tokens=16384,
                )
                if self.thinking:
                    kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}
                else:
                    kwargs["temperature"] = 0.5
                return await self.client.messages.create(**kwargs)

            response = await _retry_api_call(_api_call)

            # Accumulate token usage from this turn
            if hasattr(response, 'usage') and response.usage:
                turn_input = getattr(response.usage, 'input_tokens', 0) or 0
                turn_output = getattr(response.usage, 'output_tokens', 0) or 0
                total_input_tokens += turn_input
                total_output_tokens += turn_output
                # Extended thinking tokens (if available)
                thinking_tokens = getattr(response.usage, 'thinking_tokens', None)
                if thinking_tokens:
                    total_thinking_tokens += thinking_tokens
                # Cache tokens (if prompt caching is active)
                cache_read = getattr(response.usage, 'cache_read_input_tokens', None)
                cache_creation = getattr(response.usage, 'cache_creation_input_tokens', None)
                if cache_read:
                    total_cache_read_tokens += cache_read
                if cache_creation:
                    total_cache_creation_tokens += cache_creation
                print(f"   Tokens this turn: {turn_input:,} in / {turn_output:,} out"
                      + (f" / {thinking_tokens:,} thinking" if thinking_tokens else ""))

            # Check if the model is done (no more tool calls)
            if response.stop_reason == "end_turn":
                total_tokens = total_input_tokens + total_output_tokens
                print(f"\n✅ Agent finished after {turn + 1} turns, {total_tool_calls} tool calls")
                print(f"📂 Files read: {', '.join(files_read) if files_read else 'none'}")
                print(f"📊 Total tokens: {total_tokens:,} ({total_input_tokens:,} in / {total_output_tokens:,} out)"
                      + (f" / {total_thinking_tokens:,} thinking" if total_thinking_tokens else ""))

                result = self._extract_json_from_response(response)
                if not result:
                    raise ValueError(
                        "Agent completed but did not produce valid JSON. "
                        "Last response did not contain parseable JSON output."
                    )

                initialization_code = result.get("initialization_code", "")
                trigger_code = result.get("trigger_code", "")
                execution_code = result.get("execution_code", "")

                if not initialization_code or not trigger_code or not execution_code:
                    raise ValueError("Response missing one or more code sections")

                # Post-generation lint checks
                if self.validate:
                    check_results = _run_all_checks(initialization_code, trigger_code, execution_code)
                    syntax_count = len(check_results["syntax_errors"])
                    lint_count = len(check_results["lint_issues"])
                    print(f"🔍 Post-generation checks: {syntax_count} syntax errors, {lint_count} lint issues")

                    if syntax_count > 0 or lint_count > 0:
                        print("⚠️  Issues found — running self-correction pass...")
                        corrected, correction_usage = await self._self_correct(
                            messages, response, check_results,
                            initialization_code, trigger_code, execution_code
                        )
                        if correction_usage:
                            total_input_tokens += correction_usage.get("input_tokens", 0)
                            total_output_tokens += correction_usage.get("output_tokens", 0)
                            total_thinking_tokens += correction_usage.get("thinking_tokens", 0)
                            corr_total = correction_usage.get("input_tokens", 0) + correction_usage.get("output_tokens", 0)
                            print(f"   Self-correction tokens: {corr_total:,}")
                        if corrected:
                            initialization_code = corrected.get("initialization_code") or initialization_code
                            trigger_code = corrected.get("trigger_code") or trigger_code
                            execution_code = corrected.get("execution_code") or execution_code
                            print("✅ Self-correction applied")

                grand_total = total_input_tokens + total_output_tokens
                print(f"📊 Final total tokens: {grand_total:,} ({total_input_tokens:,} in / {total_output_tokens:,} out)"
                      + (f" / {total_thinking_tokens:,} thinking" if total_thinking_tokens else ""))
                print("✅ Code generated successfully")
                return {
                    "initialization_code": initialization_code,
                    "trigger_code": trigger_code,
                    "execution_code": execution_code,
                    "strategy_description": strategy_description,
                    "agent_metadata": {
                        "turns": turn + 1,
                        "tool_calls": total_tool_calls,
                        "files_read": files_read,
                        "total_tokens": grand_total,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "thinking_tokens": total_thinking_tokens or None,
                        "cache_read_tokens": total_cache_read_tokens or None,
                        "cache_creation_tokens": total_cache_creation_tokens or None,
                    }
                }

            # Handle tool calls
            if response.stop_reason == "tool_use":
                # Build assistant message with all content blocks
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        total_tool_calls += 1
                        tool_name = block.name
                        tool_input = block.input

                        # Track which files were read
                        if tool_name == "read_source_file":
                            fname = tool_input.get("filename", "")
                            if fname and fname not in files_read:
                                files_read.append(fname)
                            print(f"  📄 Reading: {fname}")
                        elif tool_name == "list_source_files":
                            print(f"  📋 Listing available files")

                        result_text = self._handle_tool_call(tool_name, tool_input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                print(f"⚠️  Unexpected stop_reason: {response.stop_reason}")
                raise ValueError(f"Agent stopped unexpectedly: {response.stop_reason}")

        raise TimeoutError(
            f"Agent did not complete within {self.max_turns} turns. "
            f"Read {len(files_read)} files, made {total_tool_calls} tool calls."
        )

    # ─── Self-Correction Pass ─────────────────────────────────────

    async def _self_correct(
        self,
        conversation_messages: List[Dict],
        last_response,
        check_results: Dict[str, List[str]],
        initialization_code: str,
        trigger_code: str,
        execution_code: str,
    ) -> tuple[Optional[Dict[str, str]], Optional[Dict[str, int]]]:
        """
        Send lint/syntax issues back to the model for self-correction.
        Uses the existing conversation context so the model remembers what files it read.
        
        Returns:
            (corrected_code_dict or None, usage_dict or None)
        """
        syntax_errors = check_results.get("syntax_errors", [])
        lint_issues = check_results.get("lint_issues", [])

        correction_prompt = (
            "Your generated code has the following issues that need fixing:\n\n"
        )

        if syntax_errors:
            correction_prompt += "SYNTAX ERRORS (must fix):\n"
            for err in syntax_errors:
                correction_prompt += f"  - {err}\n"
            correction_prompt += "\n"

        if lint_issues:
            correction_prompt += "LINT ISSUES (should fix):\n"
            for issue in lint_issues:
                correction_prompt += f"  - {issue}\n"
            correction_prompt += "\n"

        correction_prompt += (
            "Please fix ALL issues and return the corrected JSON with "
            "initialization_code, trigger_code, and execution_code. "
            "Return ONLY the corrected JSON, no additional text."
        )

        # Continue the conversation with the correction request
        correction_messages = list(conversation_messages)
        correction_messages.append({"role": "assistant", "content": last_response.content})
        correction_messages.append({"role": "user", "content": correction_prompt})

        try:
            from agent_prompts import AGENT_SYSTEM_PROMPT

            async def _correction_call():
                return await self.client.messages.create(
                    model=self.model,
                    system=AGENT_SYSTEM_PROMPT,
                    messages=correction_messages,
                    max_tokens=16384,
                    temperature=0.3,
                )

            response = await _retry_api_call(_correction_call)

            # Extract usage from correction response
            usage_dict = None
            if hasattr(response, 'usage') and response.usage:
                usage_dict = {
                    "input_tokens": getattr(response.usage, 'input_tokens', 0) or 0,
                    "output_tokens": getattr(response.usage, 'output_tokens', 0) or 0,
                    "thinking_tokens": getattr(response.usage, 'thinking_tokens', 0) or 0,
                }

            result = self._extract_json_from_response(response)

            if result and all(k in result for k in ["initialization_code", "trigger_code", "execution_code"]):
                return result, usage_dict
            return None, usage_dict

        except Exception as e:
            print(f"⚠️  Self-correction failed: {str(e)}")
            return None, None
