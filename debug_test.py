"""
ASMM v3.2 Pro Debug Test Script
Run this to verify all components are working correctly.
"""

import sys

def run_tests():
    print("=" * 60)
    print("ASMM v3.2 Pro - Debug Test")
    print("=" * 60)
    
    # Test 1: Imports
    print("\n[1] Testing imports...")
    try:
        from config import config
        from indicators import calculate_all_indicators, calculate_ema, calculate_rsi
        from strategy import trading_strategy, TradeDirection
        from risk import risk_manager
        from exchange import exchange_client
        print("    All imports successful!")
    except ImportError as e:
        print(f"    FAILED: {e}")
        return False
    
    # Test 2: Config
    print("\n[2] Testing config...")
    print(f"    Strategy: {config.strategy_name} v{config.strategy_version}")
    print(f"    Assets: {config.trading_pairs}")
    print(f"    Risk: {config.base_risk_pct*100:.0f}% / {config.high_conviction_risk_pct*100:.0f}%")
    print(f"    Leverage: {config.base_leverage}x / {config.high_conviction_leverage}x")
    print(f"    Nansen Mandatory: {config.nansen_mandatory}")
    print(f"    Dry run: {config.dry_run}")
    print(f"    Testnet: {config.use_testnet}")
    print("    Config OK!")
    
    # Test 3: Indicators
    print("\n[3] Testing indicators with mock data...")
    try:
        import pandas as pd
        import numpy as np
        np.random.seed(42)
        
        mock_data = pd.DataFrame({
            'open': 95000 + np.random.randn(100) * 500,
            'high': 95500 + np.random.randn(100) * 500,
            'low': 94500 + np.random.randn(100) * 500,
            'close': 95000 + np.random.randn(100) * 500,
            'volume': np.random.randint(1000, 5000, 100)
        })
        
        ind = calculate_all_indicators(mock_data)
        print(f"    EMA20: ${ind['ema_20']:.2f}")
        print(f"    EMA50: ${ind['ema_50']:.2f}")
        print(f"    RSI: {ind['rsi']:.2f}")
        print(f"    MACD: {ind['macd']:.2f}")
        print(f"    ADX: {ind['adx']:.2f}")
        print(f"    ATR: ${ind['atr']:.2f}")
        print("    Indicators OK!")
    except Exception as e:
        print(f"    FAILED: {e}")
        return False
    
    # Test 4: Position Sizing
    print("\n[4] Testing position sizing...")
    try:
        entry = 95000
        stop = 94000  # $1000 stop distance
        
        pos, lev, notional, risk_amt, risk_pct = trading_strategy.calculate_position_size(
            100, entry, stop, 'STANDARD'
        )
        print(f"    STANDARD (4/5): {pos:.4f} BTC @ {lev}x = ${notional:.2f}")
        
        pos_h, lev_h, notional_h, risk_h, _ = trading_strategy.calculate_position_size(
            100, entry, stop, 'HIGH'
        )
        print(f"    HIGH (5/5): {pos_h:.4f} BTC @ {lev_h}x = ${notional_h:.2f}")
        print("    Position sizing OK!")
    except Exception as e:
        print(f"    FAILED: {e}")
        return False
    
    # Test 5: Exit Calculations
    print("\n[5] Testing exit calculations...")
    try:
        exits = trading_strategy.calculate_exits(95000, TradeDirection.LONG, 500)
        print(f"    LONG Entry: $95,000")
        print(f"    Stop Loss: ${exits['stop_loss']:,.2f} (-{(95000-exits['stop_loss'])/95000*100:.2f}%)")
        print(f"    Take Profit: ${exits['take_profit']:,.2f} (+{(exits['take_profit']-95000)/95000*100:.2f}%)")
        print(f"    Trailing Stop: ${exits['trailing_stop']:,.2f}")
        print("    Exit calculations OK!")
    except Exception as e:
        print(f"    FAILED: {e}")
        return False
    
    # Test 6: Risk Manager
    print("\n[6] Testing risk manager...")
    try:
        can_trade, reason = risk_manager.check_circuit_breakers(100)
        print(f"    Can trade: {can_trade} ({reason})")
        print(f"    Win rate: {risk_manager.calculate_win_rate():.1f}%")
        print(f"    Consecutive losses: {risk_manager.consecutive_losses}")
        print("    Risk manager OK!")
    except Exception as e:
        print(f"    FAILED: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("ASMM v3.2 Pro is ready for dry-run testing!")
    print("=" * 60)
    
    print("\nNext steps:")
    print("  1. Add Bybit testnet API keys to .env file")
    print("  2. Add Nansen API key to .env file")
    print("  3. Run: python main.py (with DRY_RUN=true)")
    print("  4. Monitor 4H candle closes for signals")
    
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
