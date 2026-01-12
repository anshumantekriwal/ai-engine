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
        This ensures cohesion across all methods.
        """
        
        print("🤖 Generating agent code...")
        print(f"Strategy: {strategy_description[:100]}...")
        
        # Build user prompt with all context
        user_prompt = UNIFIED_GENERATION_PROMPT.format(
            strategy_description=strategy_description,
        )
        
        # Generate code with retries
        for attempt in range(self.max_retries):
            try:
                print(f"\n📝 Generation attempt {attempt + 1}/{self.max_retries}...")
                
                # Generate all three methods in one call
                response = await self.ai_provider.generate_with_json(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt
                )
                
                # Extract the three code sections
                initialization_code = response.get("initialization_code", "")
                trigger_code = response.get("trigger_code", "")
                execution_code = response.get("execution_code", "")
                
                if not initialization_code or not trigger_code or not execution_code:
                    raise ValueError("Response missing one or more code sections")
                
                print("✅ Code generated successfully")
                
                # Validate if enabled
                if self.validate:
                    print("\n🔍 Validating generated code...")
                    is_valid, corrected_code, lint_summary = await self._validate_code(
                        initialization_code,
                        trigger_code,
                        execution_code
                    )
                    
                    if is_valid:
                        print("✅ Code validation passed")
                        if corrected_code:
                            # Use corrected code if provided
                            initialization_code = corrected_code.get("initialization_code") or initialization_code
                            trigger_code = corrected_code.get("trigger_code") or trigger_code
                            execution_code = corrected_code.get("execution_code") or execution_code
                        
                        return {
                            "initialization_code": initialization_code,
                            "trigger_code": trigger_code,
                            "execution_code": execution_code,
                            "strategy_description": strategy_description,
                        }
                    elif attempt < self.max_retries - 1:
                        print(f"⚠️  Validation failed: {lint_summary}")
                        print(f"🔄 Retrying with corrections...")
                        
                        # If validator provided corrections, use them
                        if corrected_code and any(corrected_code.values()):
                            print("✅ Using auto-corrected code")
                            return {
                                "initialization_code": corrected_code.get("initialization_code") or initialization_code,
                                "trigger_code": corrected_code.get("trigger_code") or trigger_code,
                                "execution_code": corrected_code.get("execution_code") or execution_code,
                                "strategy_description": strategy_description,
                            }
                        # Otherwise retry generation
                        continue
                    else:
                        print("⚠️  Max retries reached, returning unvalidated code")
                        return {
                            "initialization_code": initialization_code,
                            "trigger_code": trigger_code,
                            "execution_code": execution_code,
                            "strategy_description": strategy_description,
                        }
                
                # If validation disabled, return immediately
                return {
                    "initialization_code": initialization_code,
                    "trigger_code": trigger_code,
                    "execution_code": execution_code,
                    "strategy_description": strategy_description,
                }
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing error: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise Exception(f"Failed to parse JSON response after {self.max_retries} attempts")
                continue
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise Exception(f"Failed to generate agent code after {self.max_retries} attempts: {str(e)}")
                print(f"⚠️  Attempt {attempt + 1} failed: {str(e)}")
                continue
        
        raise Exception("Failed to generate valid agent code")
    
    async def _validate_code(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str
    ) -> Tuple[bool, Optional[Dict[str, str]], Dict[str, int]]:
        """
        Validate generated code with comprehensive linting and guardrails.
        Returns: (is_valid, corrected_code, lint_summary)
        """
        
        print("\n🔍 Validating generated code...")
        
        # Combine all code for comprehensive validation
        full_code = f"""
// Initialization
{initialization_code}

// Triggers
{trigger_code}

// Execution
{execution_code}
"""
        
        # Step 1: Syntax check
        syntax_errors = []
        syntax_err_init = _syntax_check(initialization_code)
        if syntax_err_init:
            syntax_errors.append(f"Initialization: {syntax_err_init}")
        
        syntax_err_trigger = _syntax_check(trigger_code)
        if syntax_err_trigger:
            syntax_errors.append(f"Triggers: {syntax_err_trigger}")
        
        syntax_err_exec = _syntax_check(execution_code)
        if syntax_err_exec:
            syntax_errors.append(f"Execution: {syntax_err_exec}")
        
        # Step 2: Lint check
        lint_errors = []
        lint_err_init = _lint_check(initialization_code)
        if lint_err_init:
            lint_errors.append(f"Initialization:\n{lint_err_init}")
        
        lint_err_trigger = _lint_check(trigger_code)
        if lint_err_trigger:
            lint_errors.append(f"Triggers:\n{lint_err_trigger}")
        
        lint_err_exec = _lint_check(execution_code)
        if lint_err_exec:
            lint_errors.append(f"Execution:\n{lint_err_exec}")
        
        # Count errors
        error_count = len(syntax_errors)
        warning_count = len(lint_errors)
        
        lint_summary = {
            "error_count": error_count,
            "warning_count": warning_count,
            "suggestion_count": 0
        }
        
        print(f"\n📊 Validation Summary:")
        print(f"  Syntax Errors: {error_count}")
        print(f"  Lint Warnings: {warning_count}")
        
        # If we have errors, invoke AI guardrail
        if syntax_errors or lint_errors:
            print("\n🤖 Invoking AI guardrail for corrections...")
            
            try:
                corrected_code = await self._invoke_guardrail(
                    initialization_code,
                    trigger_code,
                    execution_code,
                    syntax_errors,
                    lint_errors
                )
                
                if corrected_code:
                    print("✅ AI guardrail provided corrections")
                    # Re-validate corrected code
                    revalidated = await self._quick_validate(
                        corrected_code.get("initialization_code", initialization_code),
                        corrected_code.get("trigger_code", trigger_code),
                        corrected_code.get("execution_code", execution_code)
                    )
                    
                    if revalidated:
                        print("✅ Corrected code passed validation")
                        return True, corrected_code, lint_summary
                    else:
                        print("⚠️  Corrected code still has issues, but accepting it")
                        return True, corrected_code, lint_summary
                        
            except Exception as e:
                print(f"⚠️  Guardrail error: {str(e)}")
        
        # If only warnings (no syntax errors), consider it valid
        is_valid = error_count == 0
        
        if is_valid:
            print("✅ Code validation passed")
        else:
            print(f"❌ Code validation failed with {error_count} errors")
        
        return is_valid, None, lint_summary
    
    async def _invoke_guardrail(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str,
        syntax_errors: List[str],
        lint_errors: List[str]
    ) -> Optional[Dict[str, str]]:
        """
        AI-powered code correction and refinement.
        Similar to the guardrail in coder.py but for trading agents.
        """
        
        system_prompt = """
You are a JavaScript code specialist for trading agent corrections.

Your job is to fix syntax and logic errors in trading agent code while maintaining the original intent.

The code has three parts:
1. initialization_code - Sets up strategy parameters
2. trigger_code - Registers trading triggers
3. execution_code - Executes trades when triggered

CRITICAL RULES:
- Fix ALL syntax errors
- Address lint warnings (missing await, error handling, safety checks)
- Do NOT change the strategy logic unnecessarily
- Ensure all async functions use await
- Always check result.success after order placement
- Always call syncPositions() after trades
- Always call updateState() for user communication
- Always call checkSafetyLimits() before placing orders
- Use proper try-catch error handling
- Maintain cohesion between the three code sections
- Variables set in initialization MUST be used in triggers and execution

Ignore undefined-reference errors for these (they're pre-defined):
- this.orderExecutor, this.wsManager, this.supabase
- this.coin, this.userAddress, this.agentId, this.userId
- this.maxPositionSize, this.dailyLossLimit
- Helper functions from perpMarket.js and perpUser.js

Output ONLY valid JSON with this structure:
{{
  "initialization_code": "<corrected code or null>",
  "trigger_code": "<corrected code or null>",
  "execution_code": "<corrected code or null>"
}}

Only include fields that need correction. If a section is fine, set it to null.
"""
        
        user_prompt = f"""Fix the following trading agent code:

INITIALIZATION CODE:
```javascript
{initialization_code}
```

TRIGGER CODE:
```javascript
{trigger_code}
```

EXECUTION CODE:
```javascript
{execution_code}
```

SYNTAX ERRORS:
{chr(10).join(syntax_errors) if syntax_errors else 'None'}

LINT WARNINGS:
{chr(10).join(lint_errors) if lint_errors else 'None'}

Provide corrected code for sections that need fixes. Return null for sections that are fine.
"""
        
        try:
            response = await self.ai_provider.generate_with_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            
            # Extract corrections
            corrected = {}
            if response.get("initialization_code"):
                corrected["initialization_code"] = response["initialization_code"]
            if response.get("trigger_code"):
                corrected["trigger_code"] = response["trigger_code"]
            if response.get("execution_code"):
                corrected["execution_code"] = response["execution_code"]
            
            return corrected if corrected else None
            
        except Exception as e:
            print(f"⚠️  Guardrail invocation failed: {str(e)}")
            return None
    
    async def _quick_validate(
        self,
        initialization_code: str,
        trigger_code: str,
        execution_code: str
    ) -> bool:
        """Quick syntax validation without full lint check."""
        
        syntax_ok = (
            _syntax_check(initialization_code) is None and
            _syntax_check(trigger_code) is None and
            _syntax_check(execution_code) is None
        )
        
        return syntax_ok
    
    async def regenerate_method(
        self,
        method_type: str,  # 'init', 'triggers', or 'execution'
        strategy_description: str,
        strategy_config: Dict[str, Any],
        current_code: Dict[str, str]
    ) -> str:
        """
        Regenerate a specific method while keeping others intact.
        Uses the unified prompt but focuses on one method.
        """
        
        print(f"🔄 Regenerating {method_type} method...")
        
        # Build focused prompt
        user_prompt = f"""Regenerate ONLY the {method_type} method for this agent.

Strategy: {strategy_description}
Config: {json.dumps(strategy_config, indent=2)}

Current initialization code:
```javascript
{current_code.get('initialization_code', '')}
```

Current trigger code:
```javascript
{current_code.get('trigger_code', '')}
```

Current execution code:
```javascript
{current_code.get('execution_code', '')}
```

Generate a replacement for the {method_type} method that maintains cohesion with the other methods.
Respond with JSON: {{"code": "// new code here"}}
"""
        
        try:
            response = await self.ai_provider.generate_with_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt
            )
            
            new_code = response.get("code", "")
            if not new_code:
                raise ValueError("No code in response")
            
            print(f"✅ {method_type} method regenerated")
            return new_code
            
        except Exception as e:
            raise Exception(f"Failed to regenerate {method_type}: {str(e)}")
