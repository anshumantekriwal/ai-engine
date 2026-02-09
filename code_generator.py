"""
Code Generator - Core logic for generating trading agent code

Implements:
- Unified code generation (all three methods together)
- Syntax validation with esprima
- Lint checking with regex patterns
- Single AI validation pass that receives all check outputs and corrects errors + logic
"""

from typing import Dict, Any, Optional, List, Tuple
import json
import re
from ai_providers import AIProvider
from prompts import (
    SYSTEM_PROMPT,
    UNIFIED_GENERATION_PROMPT,
    VALIDATION_PROMPT
)

try:
    import esprima
    ESPRIMA_AVAILABLE = True
except ImportError:
    ESPRIMA_AVAILABLE = False
    print("⚠️  esprima not available, syntax checking disabled")


def _syntax_check(js_code: str) -> Optional[str]:
    """
    Parse with esprima to catch syntax errors.
    Returns error string if invalid, None if valid.
    """
    if not ESPRIMA_AVAILABLE:
        return None

    try:
        try:
            esprima.parseScript(js_code)
            return None
        except:
            wrapped_code = f"async function testFunction() {{\n{js_code}\n}}"
            esprima.parseScript(wrapped_code)
            return None
    except Exception as e:
        return str(e).split("\n")[0]


def _lint_check(js_code: str) -> List[str]:
    """
    Shallow lint via regex for common JavaScript issues.
    Returns a list of issue strings (empty if clean).
    """
    errors = []

    # 1) const reassignment
    for const_match in re.finditer(r'\bconst\s+([A-Za-z_$][0-9A-Za-z_$]*)', js_code):
        name = const_match.group(1)
        rest = js_code[const_match.end():]
        if re.search(rf'\b{name}\s*=', rest):
            errors.append(f"Cannot reassign const `{name}`")

    # 2) missing await for async calls
    async_patterns = [
        r'this\.orderExecutor\.\w+\(',
        r'this\.wsManager\.\w+\(',
        r'this\.supabase\.\w+\(',
        r'this\.updateState\(',
        r'this\.syncPositions\(',
        r'this\.logTrade\(',
        r'this\.checkSafetyLimits\(',
        r'this\.executeTrade\(',
        r'getPortfolio\(',
        r'getUserFills\(',
        r'getOpenOrders\(',
        r'getAllMids\(',
        r'getCandleSnapshot\(',
    ]

    for pattern in async_patterns:
        calls = list(re.finditer(pattern, js_code))
        awaited = list(re.finditer(rf'await\s+{pattern}', js_code))
        if len(calls) > len(awaited):
            func_name = re.search(r'(\w+)\(', pattern)
            if func_name:
                errors.append(f"Possible missing `await` for `{func_name.group(1)}()` call")

    # 3) try without catch
    if 'try' in js_code and 'catch' not in js_code:
        errors.append("Found `try` block without corresponding `catch`")

    # 4) No logging
    if 'console.log' not in js_code:
        errors.append("No console.log statements found - add logging for debugging")

    # 5) Missing result.success check after order placement
    order_methods = ['placeMarketOrder', 'placeLimitOrder', 'closePosition']
    for method in order_methods:
        if method in js_code:
            pattern = rf'{method}\([^)]+\)'
            matches = re.finditer(pattern, js_code)
            for match in matches:
                snippet = js_code[match.end():match.end() + 500]
                if 'result.success' not in snippet and '.success' not in snippet:
                    errors.append(f"Missing `result.success` check after `{method}()` call")
                    break

    # 6) Missing syncPositions after trades
    if 'placeMarketOrder' in js_code or 'closePosition' in js_code:
        if 'syncPositions' not in js_code:
            errors.append("Missing `syncPositions()` call after trade execution")

    # 7) Missing updateState
    if 'updateState' not in js_code:
        errors.append("No `updateState()` calls found - add state updates for user communication")

    # 8) Missing safety checks before orders
    if 'placeMarketOrder' in js_code or 'placeLimitOrder' in js_code:
        if 'checkSafetyLimits' not in js_code:
            errors.append("Missing `checkSafetyLimits()` check before placing orders")

    # 9) Sandboxing: cancelAllOrders should be cancelAgentOrders
    if 'cancelAllOrders' in js_code:
        errors.append("Using `cancelAllOrders()` — this cancels ALL orders on the account (including other agents). Use `cancelAgentOrders()` instead for sandboxed cancellation")

    # 10) Sandboxing: closePosition without explicit size
    bare_close = re.findall(r'closePosition\(\s*(?:this\.\w+|\w+|["\'][^"\']+["\'])\s*\)', js_code)
    if bare_close:
        for match in bare_close:
            if ',' not in match:
                errors.append(f"Bare `closePosition(coin)` without explicit size — this closes the ENTIRE account position. Pass your tracked entrySize: `closePosition(coin, mySize)`")
                break

    # 11) Sandboxing: entrySize tracking after placing orders
    if 'placeMarketOrder' in js_code:
        if 'entrySize' not in js_code and 'entry_size' not in js_code:
            errors.append("Not tracking `entrySize` after opening positions — agent won't know how much to close later. Store `this.tradeState[coin].entrySize = filled` after entry")

    return errors


def _run_all_checks(
    initialization_code: str,
    trigger_code: str,
    execution_code: str
) -> Dict[str, List[str]]:
    """
    Run syntax + lint checks on all three code sections.
    Returns a dict with all issues grouped by section.
    """
    results = {
        "syntax_errors": [],
        "lint_issues": [],
    }

    for label, code in [("Initialization", initialization_code),
                        ("Triggers", trigger_code),
                        ("Execution", execution_code)]:
        err = _syntax_check(code)
        if err:
            results["syntax_errors"].append(f"{label}: {err}")

        lint_issues = _lint_check(code)
        for issue in lint_issues:
            results["lint_issues"].append(f"{label}: {issue}")

    return results


class CodeGenerator:
    """Generates trading agent code using AI"""

    def __init__(
        self,
        ai_provider: AIProvider,
        validate: bool = True
    ):
        self.ai_provider = ai_provider
        self.validate = validate

    async def generate_complete_agent(
        self,
        strategy_description: str,
    ) -> Dict[str, str]:
        """
        Generate all three method bodies for a complete agent.

        Pipeline:
        1. Generate code via AI
        2. If validation enabled: run syntax + lint checks
        3. Send everything (code + all check outputs) to a single validation/correction pass
        4. Return the best code available
        """

        print("🤖 Generating agent code...")
        print(f"Strategy: {strategy_description[:100]}...")

        # Build user prompt
        user_prompt = UNIFIED_GENERATION_PROMPT.format(
            strategy_description=strategy_description,
        )

        # --- Step 1: Generate code ---
        print("\n📝 Generating code...")

        response = await self.ai_provider.generate_with_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt
        )

        initialization_code = response.get("initialization_code", "")
        trigger_code = response.get("trigger_code", "")
        execution_code = response.get("execution_code", "")

        if not initialization_code or not trigger_code or not execution_code:
            raise ValueError("Response missing one or more code sections")

        print("✅ Code generated successfully")

        if not self.validate:
            return {
                "initialization_code": initialization_code,
                "trigger_code": trigger_code,
                "execution_code": execution_code,
                "strategy_description": strategy_description,
            }

        # --- Step 2: Run all checks ---
        print("\n🔍 Running checks...")
        check_results = _run_all_checks(initialization_code, trigger_code, execution_code)

        syntax_count = len(check_results["syntax_errors"])
        lint_count = len(check_results["lint_issues"])
        print(f"📊 Found {syntax_count} syntax errors, {lint_count} lint issues")

        # --- Step 3: Single validation + correction pass ---
        # Always run the AI validation pass — it checks logic, API usage, and
        # strategy correctness beyond what the linters can catch.
        print("\n🤖 Running AI validation & correction pass...")

        corrected = await self._validate_and_correct(
            initialization_code, trigger_code, execution_code,
            check_results
        )

        if corrected:
            final_init = corrected.get("initialization_code") or initialization_code
            final_trigger = corrected.get("trigger_code") or trigger_code
            final_exec = corrected.get("execution_code") or execution_code
            print("✅ Validation pass complete — using corrected code")
            return {
                "initialization_code": final_init,
                "trigger_code": final_trigger,
                "execution_code": final_exec,
                "strategy_description": strategy_description,
            }

        # No corrections needed or guardrail returned nothing — use original
        print("✅ Validation pass complete — no corrections needed")
        return {
            "initialization_code": initialization_code,
            "trigger_code": trigger_code,
            "execution_code": execution_code,
            "strategy_description": strategy_description,
        }

    async def _validate_and_correct(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str,
        check_results: Dict[str, List[str]]
    ) -> Optional[Dict[str, str]]:
        """
        Single AI validation + correction pass.
        Receives the generated code AND all outputs from syntax/lint checks.
        The AI reviews for correctness, logic, API usage, and fixes any issues.
        """

        validation_user_prompt = VALIDATION_PROMPT.format(
            initialization_code=initialization_code,
            trigger_code=trigger_code,
            execution_code=execution_code
        )

        # Append all check outputs so the AI has full context
        syntax_errors = check_results["syntax_errors"]
        lint_issues = check_results["lint_issues"]

        validation_user_prompt += f"""

## Automated Check Results

SYNTAX ERRORS ({len(syntax_errors)}):
{chr(10).join(syntax_errors) if syntax_errors else 'None'}

LINT ISSUES ({len(lint_issues)}):
{chr(10).join(lint_issues) if lint_issues else 'None'}

Review the code for all the issues listed in "What to Check" above.
Use the automated check results as a starting point, but also check for logic errors,
API misuse, strategy implementation bugs, and anything else that could cause problems.
Fix everything and provide corrected_code. Set fields to null if no changes needed for that section.
"""

        try:
            response = await self.ai_provider.generate_with_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=validation_user_prompt
            )

            corrected = response.get("corrected_code", {})
            if not corrected or not isinstance(corrected, dict):
                return None

            # Filter out null entries
            result = {}
            for key in ["initialization_code", "trigger_code", "execution_code"]:
                if corrected.get(key):
                    result[key] = corrected[key]

            return result if result else None

        except Exception as e:
            print(f"⚠️  Validation pass failed: {str(e)}")
            return None
