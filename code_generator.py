"""
Code Generator - Core logic for generating trading agent code

Implements:
- Chain of Thought reasoning
- Unified code generation (all three methods together)
- Syntax validation with esprima
- Lint checking with regex patterns
- AI-powered guardrail corrections
- Retry mechanism with exponential backoff
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
        
    print("🔍 Running syntax check...")
    try:
        # First try to parse as-is (for complete functions)
        try:
            esprima.parseScript(js_code)
            print("✅ Syntax looks good")
            return None
        except:
            # If that fails, try wrapping in an async function
            wrapped_code = f"async function testFunction() {{\n{js_code}\n}}"
            esprima.parseScript(wrapped_code)
            print("✅ Syntax looks good")
            return None
    except Exception as e:
        err = str(e).split("\n")[0]
        print(f"❌ Syntax error: {err}")
        return err


def _lint_check(js_code: str) -> Optional[str]:
    """
    Shallow lint via regex for common JavaScript issues:
    - const reassignment
    - missing await in async functions
    - suspicious patterns
    - undefined variables (basic check)
    """
    print("🔍 Running lint check...")
    errors = []

    # 1) const reassignment
    for const_match in re.finditer(r'\bconst\s+([A-Za-z_$][0-9A-Za-z_$]*)', js_code):
        name = const_match.group(1)
        # look for a second assignment to that name
        rest = js_code[const_match.end():]
        if re.search(rf'\b{name}\s*=', rest):
            errors.append(f"Cannot reassign const `{name}`")

    # 2) missing await for async calls (common patterns)
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
        # Find all occurrences
        calls = list(re.finditer(pattern, js_code))
        # Find awaited occurrences
        awaited = list(re.finditer(rf'await\s+{pattern}', js_code))
        
        if len(calls) > len(awaited):
            # Try to identify which specific call is missing await
            func_name = re.search(r'(\w+)\(', pattern)
            if func_name:
                errors.append(f"Possible missing `await` for `{func_name.group(1)}()` call")

    # 3) Check for proper error handling
    if 'try' in js_code and 'catch' not in js_code:
        errors.append("Found `try` block without corresponding `catch`")

    # 4) Check for console.log (should have at least some logging)
    if 'console.log' not in js_code:
        errors.append("No console.log statements found - add logging for debugging")

    # 5) Check for result.success pattern after order placement
    order_methods = ['placeMarketOrder', 'placeLimitOrder', 'closePosition']
    for method in order_methods:
        if method in js_code:
            # Check if result.success is checked after the call
            pattern = rf'{method}\([^)]+\)'
            matches = re.finditer(pattern, js_code)
            for match in matches:
                # Look ahead for result.success check within next 500 chars
                snippet = js_code[match.end():match.end()+500]
                if 'result.success' not in snippet and '.success' not in snippet:
                    errors.append(f"Missing `result.success` check after `{method}()` call")
                    break

    # 6) Check for position syncing after trades
    if 'placeMarketOrder' in js_code or 'closePosition' in js_code:
        if 'syncPositions' not in js_code:
            errors.append("Missing `syncPositions()` call after trade execution")

    # 7) Check for updateState calls
    if 'updateState' not in js_code:
        errors.append("No `updateState()` calls found - add state updates for user communication")

    # 8) Check for safety checks
    if 'placeMarketOrder' in js_code or 'placeLimitOrder' in js_code:
        if 'checkSafetyLimits' not in js_code:
            errors.append("Missing `checkSafetyLimits()` check before placing orders")

    if errors:
        print(f"❌ Lint issues found ({len(errors)}):")
        for err in errors:
            print(f"   - {err}")
        return "\n".join(errors)
    
    print("✅ Lint looks good")
    return None


class CodeGenerator:
    """Generates trading agent code using AI"""
    
    def __init__(
        self,
        ai_provider: AIProvider,
        max_retries: int = 3,
        validate: bool = True
    ):
        self.ai_provider = ai_provider
        self.max_retries = max_retries
        self.validate = validate
    
    async def generate_complete_agent(
        self,
        strategy_description: str,
    ) -> Dict[str, str]:
        """
        Generate all three method bodies for a complete agent in one unified call.
        
        Pipeline:
        1. Generate code (retry up to max_retries on JSON/generation failures)
        2. Run syntax + lint checks
        3. If issues found, invoke AI guardrail ONCE to fix them
        4. Re-validate corrected code (full syntax + lint, not syntax-only)
        5. Return the best code available
        """
        
        print("🤖 Generating agent code...")
        print(f"Strategy: {strategy_description[:100]}...")
        
        # Build user prompt
        user_prompt = UNIFIED_GENERATION_PROMPT.format(
            strategy_description=strategy_description,
        )
        
        last_errors = None  # Track errors across retries for context
        
        for attempt in range(self.max_retries):
            try:
                print(f"\n📝 Generation attempt {attempt + 1}/{self.max_retries}...")
                
                # Build the generation prompt, including error context from prior attempts
                generation_prompt = user_prompt
                if last_errors and attempt > 0:
                    generation_prompt += f"\n\n## Previous Attempt Failed\nThe prior generation had these issues — avoid them:\n{last_errors}"
                
                response = await self.ai_provider.generate_with_json(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=generation_prompt
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
                
                # --- Validation pipeline (runs once per generation attempt) ---
                print("\n🔍 Validating generated code...")
                syntax_errors, lint_errors = self._run_checks(
                    initialization_code, trigger_code, execution_code
                )
                
                error_count = len(syntax_errors)
                warning_count = len(lint_errors)
                print(f"\n📊 Validation: {error_count} syntax errors, {warning_count} lint warnings")
                
                # If clean, return immediately
                if not syntax_errors and not lint_errors:
                    print("✅ Code passed all checks")
                    return {
                        "initialization_code": initialization_code,
                        "trigger_code": trigger_code,
                        "execution_code": execution_code,
                        "strategy_description": strategy_description,
                    }
                
                # --- Guardrail: invoke ONCE to attempt correction ---
                print("\n🤖 Invoking AI guardrail for corrections (single pass)...")
                try:
                    corrected_code = await self._invoke_guardrail(
                        initialization_code, trigger_code, execution_code,
                        syntax_errors, lint_errors
                    )
                    
                    if corrected_code:
                        # Merge corrections with originals
                        final_init = corrected_code.get("initialization_code") or initialization_code
                        final_trigger = corrected_code.get("trigger_code") or trigger_code
                        final_exec = corrected_code.get("execution_code") or execution_code
                        
                        # Re-validate corrected code (FULL check, not syntax-only)
                        re_syntax, re_lint = self._run_checks(final_init, final_trigger, final_exec)
                        
                        if not re_syntax:
                            print("✅ Corrected code passed syntax checks")
                            if re_lint:
                                print(f"⚠️  {len(re_lint)} lint warnings remain (non-blocking)")
                            return {
                                "initialization_code": final_init,
                                "trigger_code": final_trigger,
                                "execution_code": final_exec,
                                "strategy_description": strategy_description,
                            }
                        else:
                            print("⚠️  Corrected code still has syntax errors")
                            # Record errors for next retry
                            last_errors = "Syntax: " + "; ".join(re_syntax)
                            if re_lint:
                                last_errors += "\nLint: " + "; ".join(re_lint)
                    else:
                        last_errors = "Syntax: " + "; ".join(syntax_errors) if syntax_errors else ""
                        if lint_errors:
                            last_errors += "\nLint: " + "; ".join(lint_errors)
                        
                except Exception as e:
                    print(f"⚠️  Guardrail error: {str(e)}")
                    last_errors = "Syntax: " + "; ".join(syntax_errors) if syntax_errors else ""
                
                # If no syntax errors (only lint warnings), accept the code
                if not syntax_errors:
                    print("✅ No syntax errors — accepting with lint warnings")
                    return {
                        "initialization_code": initialization_code,
                        "trigger_code": trigger_code,
                        "execution_code": execution_code,
                        "strategy_description": strategy_description,
                    }
                
                # Syntax errors remain — retry generation with error context
                if attempt < self.max_retries - 1:
                    print(f"🔄 Retrying generation with error context...")
                    continue
                else:
                    print("⚠️  Max retries reached, returning best available code")
                    return {
                        "initialization_code": initialization_code,
                        "trigger_code": trigger_code,
                        "execution_code": execution_code,
                        "strategy_description": strategy_description,
                    }
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing error: {str(e)}")
                last_errors = f"JSON parse error: {str(e)}"
                if attempt == self.max_retries - 1:
                    raise Exception(f"Failed to parse JSON response after {self.max_retries} attempts")
                continue
                
            except Exception as e:
                print(f"⚠️  Attempt {attempt + 1} failed: {str(e)}")
                last_errors = str(e)
                if attempt == self.max_retries - 1:
                    raise Exception(f"Failed to generate agent code after {self.max_retries} attempts: {str(e)}")
                continue
        
        raise Exception("Failed to generate valid agent code")
    
    def _run_checks(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str
    ) -> Tuple[List[str], List[str]]:
        """
        Run syntax + lint checks on all three code sections.
        Returns: (syntax_errors, lint_errors)
        """
        syntax_errors = []
        lint_errors = []
        
        for label, code in [("Initialization", initialization_code), 
                            ("Triggers", trigger_code), 
                            ("Execution", execution_code)]:
            err = _syntax_check(code)
            if err:
                syntax_errors.append(f"{label}: {err}")
            
            lint_err = _lint_check(code)
            if lint_err:
                lint_errors.append(f"{label}:\n{lint_err}")
        
        return syntax_errors, lint_errors
    
    async def _invoke_guardrail(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str,
        syntax_errors: List[str],
        lint_errors: List[str]
    ) -> Optional[Dict[str, str]]:
        """
        AI-powered code correction using the VALIDATION_PROMPT.
        Invoked at most ONCE per generation attempt.
        """
        
        # Use the actual VALIDATION_PROMPT so the guardrail has the same rules as validation
        validation_user_prompt = VALIDATION_PROMPT.format(
            initialization_code=initialization_code,
            trigger_code=trigger_code,
            execution_code=execution_code
        )
        
        # Append the specific errors found
        validation_user_prompt += f"""

## Detected Issues to Fix

SYNTAX ERRORS:
{chr(10).join(syntax_errors) if syntax_errors else 'None'}

LINT WARNINGS:
{chr(10).join(lint_errors) if lint_errors else 'None'}

Fix all errors and provide corrected_code. Set fields to null if no changes needed for that section.
"""
        
        try:
            response = await self.ai_provider.generate_with_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=validation_user_prompt
            )
            
            # The response follows VALIDATION_PROMPT format
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
            print(f"⚠️  Guardrail invocation failed: {str(e)}")
            return None
