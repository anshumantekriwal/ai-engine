"""
Test script for the AI Agent Code Generator

Tests the complete flow of generating agent code
"""

import asyncio
import os
from dotenv import load_dotenv
from ai_providers import get_provider
from code_generator import CodeGenerator

# Load environment
load_dotenv()

async def test_rsi_strategy():
    """Test generating code for an RSI strategy"""
    
    print("\n" + "=" * 70)
    print("TEST: RSI Mean Reversion Strategy")
    print("=" * 70)
    
    # Configuration
    strategy_description = """
    Buy BTC when RSI drops below 30 (oversold condition), indicating potential bounce.
    Sell BTC when RSI rises above 70 (overbought condition), indicating potential correction.
    Use 14-period RSI calculated on 1-hour candles.
    Close any opposite positions before opening new ones.
    Position size is 0.01 BTC.
    """
    
    strategy_config = {
        "coin": "BTC",
        "rsiPeriod": 14,
        "oversoldLevel": 30,
        "overboughtLevel": 70,
        "positionSize": 0.01,
        "interval": "1h"
    }
    
    # Initialize AI provider
    provider_type = os.getenv("DEFAULT_AI_PROVIDER", "anthropic")
    if provider_type == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print(f"❌ Missing API key for {provider_type}")
        return
    
    provider = get_provider(provider_type, api_key)
    generator = CodeGenerator(
        ai_provider=provider,
        temperature=0.2,
        max_tokens=4000,
        max_retries=3,
        validate=True
    )
    
    try:
        # Generate complete agent
        result = await generator.generate_complete_agent(
            strategy_description=strategy_description,
            strategy_config=strategy_config
        )
        
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        
        print("\n📋 INITIALIZATION CODE:")
        print("-" * 70)
        print(result["initialization_code"])
        
        print("\n🎯 TRIGGERS CODE:")
        print("-" * 70)
        print(result["trigger_code"])
        
        print("\n💼 EXECUTION CODE:")
        print("-" * 70)
        print(result["execution_code"])
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


async def test_ema_crossover():
    """Test generating code for an EMA crossover strategy"""
    
    print("\n" + "=" * 70)
    print("TEST: EMA Crossover Strategy")
    print("=" * 70)
    
    strategy_description = """
    Implement an EMA crossover strategy for ETH.
    Buy when the 12-period EMA crosses above the 26-period EMA (bullish signal).
    Sell when the 12-period EMA crosses below the 26-period EMA (bearish signal).
    Check for crossovers every minute using a scheduled trigger.
    Position size is 0.1 ETH.
    """
    
    strategy_config = {
        "coin": "ETH",
        "fastPeriod": 12,
        "slowPeriod": 26,
        "positionSize": 0.1,
        "interval": "1h",
        "checkInterval": 60000  # 1 minute
    }
    
    # Initialize
    provider_type = os.getenv("DEFAULT_AI_PROVIDER", "anthropic")
    if provider_type == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print(f"❌ Missing API key for {provider_type}")
        return
    
    provider = get_provider(provider_type, api_key)
    generator = CodeGenerator(
        ai_provider=provider,
        temperature=0.2,
        max_tokens=4000,
        max_retries=3,
        validate=True
    )
    
    try:
        result = await generator.generate_complete_agent(
            strategy_description=strategy_description,
            strategy_config=strategy_config
        )
        
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        
        print("\n📋 INITIALIZATION CODE:")
        print("-" * 70)
        print(result["initialization_code"])
        
        print("\n🎯 TRIGGERS CODE:")
        print("-" * 70)
        print(result["trigger_code"])
        
        print("\n💼 EXECUTION CODE:")
        print("-" * 70)
        print(result["execution_code"])
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


async def test_price_breakout():
    """Test generating code for a price breakout strategy"""
    
    print("\n" + "=" * 70)
    print("TEST: Price Breakout Strategy")
    print("=" * 70)
    
    strategy_description = """
    Trade BTC breakouts using price triggers.
    Buy when BTC price breaks above $100,000 (resistance breakout).
    Sell/close position when price drops below $95,000 (stop loss).
    Use 0.05 BTC position size.
    No leverage initially, but can be configured.
    """
    
    strategy_config = {
        "coin": "BTC",
        "breakoutPrice": 100000,
        "stopLossPrice": 95000,
        "positionSize": 0.05,
        "leverage": 1
    }
    
    # Initialize
    provider_type = os.getenv("DEFAULT_AI_PROVIDER", "anthropic")
    if provider_type == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print(f"❌ Missing API key for {provider_type}")
        return
    
    provider = get_provider(provider_type, api_key)
    generator = CodeGenerator(
        ai_provider=provider,
        temperature=0.2,
        max_tokens=4000,
        max_retries=3,
        validate=True
    )
    
    try:
        result = await generator.generate_complete_agent(
            strategy_description=strategy_description,
            strategy_config=strategy_config
        )
        
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        
        print("\n📋 INITIALIZATION CODE:")
        print("-" * 70)
        print(result["initialization_code"])
        
        print("\n🎯 TRIGGERS CODE:")
        print("-" * 70)
        print(result["trigger_code"])
        
        print("\n💼 EXECUTION CODE:")
        print("-" * 70)
        print(result["execution_code"])
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


async def main():
    """Run all tests"""
    
    print("\n🧪 Starting AI Agent Code Generator Tests")
    print("=" * 70)
    
    # Test 1: RSI Strategy
    await test_rsi_strategy()
    
    # Test 2: EMA Crossover
    # Uncomment to test:
    # await test_ema_crossover()
    
    # Test 3: Price Breakout
    # Uncomment to test:
    # await test_price_breakout()
    
    print("\n" + "=" * 70)
    print("🎉 All tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
