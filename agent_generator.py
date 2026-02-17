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


def _extract_declarations(code: str) -> set:
    """Extract all variable names declared via const/let/var/for/function params in JS code."""
    declared = set()
    # const x = ..., let y = ..., var z = ...
    declared.update(re.findall(r'(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[=;,]', code))
    # Destructured: const { a, b } = ... or const { a: b } = ...
    for match in re.finditer(r'(?:const|let|var)\s*\{([^}]+)\}', code):
        inner = match.group(1)
        for part in inner.split(','):
            part = part.strip()
            if ':' in part:
                declared.add(part.split(':')[-1].strip().split('=')[0].strip())
            elif part:
                declared.add(part.split('=')[0].strip())
    # Array destructuring: const [a, b] = ...
    for match in re.finditer(r'(?:const|let|var)\s*\[([^\]]+)\]', code):
        for part in match.group(1).split(','):
            part = part.strip().split('=')[0].strip()
            if part and not part.startswith('...'):
                declared.add(part.lstrip('.'))
            elif part.startswith('...'):
                declared.add(part[3:].strip())
    # for (const x of ...) / for (const x in ...)
    declared.update(re.findall(r'for\s*\(\s*(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s+(?:of|in)', code))
    # Arrow/function params: (x, y) => ... or function(x, y) { or async (x) => ...
    # Match arrow functions specifically: `(params) => {` or `async (params) => {`
    for match in re.finditer(r'\(([^()]*)\)\s*=>\s*\{', code):
        for param in match.group(1).split(','):
            param = param.strip().split('=')[0].strip()
            if param and not param.startswith('...') and re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', param):
                declared.add(param)
            elif param and param.startswith('...'):
                rest = param[3:].strip()
                if re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', rest):
                    declared.add(rest)
    # Also match `function name(params) {` and `function(params) {`
    for match in re.finditer(r'function\s*[a-zA-Z_$]*\s*\(([^)]*)\)\s*\{', code):
        for param in match.group(1).split(','):
            param = param.strip().split('=')[0].strip()
            if param and not param.startswith('...') and re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', param):
                declared.add(param)
            elif param and param.startswith('...'):
                rest = param[3:].strip()
                if re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', rest):
                    declared.add(rest)
    # Catch `async (params) => {` where async is on the same line (inner callback)
    for match in re.finditer(r'async\s+\(([^()]*)\)\s*=>\s*\{', code):
        for param in match.group(1).split(','):
            param = param.strip().split('=')[0].strip()
            if param and not param.startswith('...') and re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', param):
                declared.add(param)
    # function name(x) { ... }
    declared.update(re.findall(r'function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(', code))
    return declared


def _strip_comments_and_strings(code: str) -> str:
    """Remove comments and string literals from JS code to avoid false positives."""
    stripped = re.sub(r'//[^\n]*', '', code)
    stripped = re.sub(r'/\*[\s\S]*?\*/', '', stripped)
    # Template literals (simplified — doesn't handle nested backticks)
    stripped = re.sub(r'`[^`]*`', '""', stripped)
    stripped = re.sub(r"'[^']*'", '""', stripped)
    stripped = re.sub(r'"[^"]*"', '""', stripped)
    return stripped


def _variable_ref_check(
    initialization_code: str,
    trigger_code: str,
    execution_code: str,
) -> List[str]:
    """
    Check for variables used but never declared within each method body.
    
    Catches bugs like `rebalancesPerRebalance` used but only `rebalancesPerDay` declared.
    Operates per-section but also considers init code declarations available to all sections.
    """
    errors = []

    # JS built-in globals, Web APIs, and framework globals that are always available
    known_globals = {
        # JS primitives/keywords that regex picks up
        'undefined', 'null', 'true', 'false', 'NaN', 'Infinity',
        # Built-in constructors and namespaces
        'console', 'Math', 'Date', 'JSON', 'Object', 'Array', 'Map', 'Set',
        'WeakMap', 'WeakSet', 'String', 'Number', 'Boolean', 'Symbol', 'BigInt',
        'Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError',
        'Promise', 'RegExp', 'Proxy', 'Reflect', 'ArrayBuffer', 'DataView',
        'Float32Array', 'Float64Array', 'Int8Array', 'Int16Array', 'Int32Array',
        'Uint8Array', 'Uint16Array', 'Uint32Array',
        # Global functions
        'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
        'decodeURIComponent', 'encodeURI', 'decodeURI', 'eval', 'atob', 'btoa',
        'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
        'fetch', 'queueMicrotask', 'structuredClone',
        # Node.js globals
        'process', 'Buffer', 'global', 'globalThis', '__dirname', '__filename',
        'require', 'module', 'exports',
        # Framework globals (re-exported by BaseAgent.js module wrapper)
        'getAllMids', 'getCandleSnapshot', 'getTicker', 'getL2Book',
        'getFundingHistory', 'getMetaAndAssetCtxs', 'getRecentTrades',
        'getPredictedFundings', 'getPerpsAtOpenInterestCap',
        'getOpenOrders', 'getFrontendOpenOrders', 'getUserFills',
        'getUserFillsByTime', 'getHistoricalOrders', 'getPortfolio',
        'getSubAccounts', 'getUserFees',
    }

    js_keywords = {
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue',
        'return', 'throw', 'try', 'catch', 'finally', 'new', 'delete', 'typeof',
        'instanceof', 'in', 'of', 'function', 'class', 'const', 'let', 'var',
        'async', 'await', 'yield', 'import', 'export', 'default', 'from', 'this',
        'void', 'with', 'debugger', 'super', 'extends', 'implements', 'static',
        'get', 'set',
    }

    # Common short identifiers that cause false positives (loop vars, params, etc.)
    common_short = {
        'err', 'res', 'req', 'msg', 'val', 'obj', 'arr', 'str', 'num', 'buf',
        'idx', 'len', 'max', 'min', 'sum', 'avg', 'cnt', 'tmp', 'ret', 'ref',
        'arg', 'args', 'opts', 'cfg', 'ctx', 'env', 'url', 'uri', 'src', 'dst',
        'col', 'row', 'pos', 'dir', 'out',
    }

    # Implicit params available in execution code (from executeTrade wrapper)
    execution_implicit = {'triggerData'}

    # Gather init declarations — init code's const/let are NOT directly accessible
    # in trigger/execution (they run in separate function scopes), but this.* properties
    # set in init ARE available. We only use init declarations for the init section itself.

    sections = [
        ("initialization", initialization_code),
        ("triggers", trigger_code),
        ("execution", execution_code),
    ]

    for label, code in sections:
        if not code.strip():
            continue

        stripped = _strip_comments_and_strings(code)
        local_declarations = _extract_declarations(stripped)

        # Add section-specific implicit params
        if label == "execution":
            local_declarations |= execution_implicit

        # Remove object literal keys — `{ key: value }` patterns
        # Replace object literal contents with empty to avoid flagging property names
        obj_key_stripped = re.sub(r'([a-zA-Z_$][a-zA-Z0-9_$]*)\s*:', 'OBJKEY:', stripped)

        # Find all free-standing identifier usages (not after . which means property access)
        all_identifiers = set(re.findall(r'(?<![.\w$])([a-zA-Z_$][a-zA-Z0-9_$]*)', obj_key_stripped))

        # Candidates: identifiers used but not declared locally or known globally
        undeclared = all_identifiers - local_declarations - known_globals - js_keywords - common_short
        # Also exclude 'OBJKEY' from the substitution
        undeclared.discard('OBJKEY')

        # Filter: only flag multi-word camelCase names (compound identifiers)
        # These are almost always user-defined variables, not missed builtins.
        # A "compound" name has at least one uppercase letter after the first char,
        # indicating camelCase like `rebalancesPerRebalance`, `dailyFeeBurn`, etc.
        compound_undeclared = {
            v for v in undeclared
            if len(v) > 4 and re.search(r'[a-z][A-Z]', v) and v[0].islower()
        }

        for var_name in sorted(compound_undeclared):
            # Try to find a similarly-named declared variable for a helpful suggestion
            suggestion = _find_similar_declaration(var_name, local_declarations)
            if suggestion:
                errors.append(
                    f"[{label}] Undeclared variable `{var_name}` — did you mean `{suggestion}`?"
                )
            else:
                errors.append(
                    f"[{label}] Undeclared variable `{var_name}` — not declared in this scope"
                )

    return errors


def _find_similar_declaration(name: str, declared: set) -> Optional[str]:
    """Find the most similar declared variable name (for typo suggestions)."""
    best = None
    best_score = 0
    for d in declared:
        # Skip very short declarations (loop vars, catch params)
        if len(d) < 4:
            continue
        # Check common prefix length
        prefix_len = 0
        for a, b in zip(name, d):
            if a == b:
                prefix_len += 1
            else:
                break
        # Require at least 5 shared prefix chars for a suggestion
        if prefix_len >= 5 and prefix_len > best_score:
            best = d
            best_score = prefix_len
        # Check if one contains the other (but only for substantial names)
        if len(d) >= 4 and (name in d or d in name):
            return d
    return best


def _run_all_checks(
    initialization_code: str,
    trigger_code: str,
    execution_code: str,
) -> Dict[str, List[str]]:
    """Run syntax, lint, and variable reference checks on all three code sections."""
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

    # Cross-check variable references (catches typos like rebalancesPerRebalance vs rebalancesPerDay)
    for issue in _variable_ref_check(initialization_code, trigger_code, execution_code):
        lint_issues.append(issue)

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

        # Prompt caching: wrap system prompt so it's cached across turns.
        # This avoids re-processing the ~5K token system prompt on every turn.
        # Anthropic's ephemeral cache stays alive as long as requests keep coming
        # (refreshed on each call), so it stays hot for the entire generation loop.
        cached_system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        for turn in range(self.max_turns):
            print(f"\n📡 Turn {turn + 1}/{self.max_turns}...")

            async def _api_call():
                kwargs = dict(
                    model=self.model,
                    system=cached_system,
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

            cached_correction_system = [
                {
                    "type": "text",
                    "text": AGENT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

            async def _correction_call():
                return await self.client.messages.create(
                    model=self.model,
                    system=cached_correction_system,
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
