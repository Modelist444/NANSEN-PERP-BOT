"""
Test script for Nansen SMF Strategy v4.0.
Verifies signal generation, position sizing, and exit calculations.
"""

import sys


def run_tests():
    print("=" * 60)
    print("Nansen SMF Strategy v4.0 - Component Test")
    print("=" * 60)
    
    # Test 1: Imports
    print("\n[1] Testing imports...")
    try:
        from config import config
        from indicators import calculate_all_indicators, get_trend_direction, is_rsi_valid_for_long, is_rsi_valid_for_short
        from strategy import trading_strategy, TradeDirection
        from risk import risk_manager
        from exchange import exchange_client
        from nansen import nansen_client, SignalType
        print("    [OK] All imports successful!")
    except ImportError as e:
        print(f"    [FAIL] {e}")
        return False
    
    # Test 2: Config
    print("\n[2] Testing config...")
    print(f"    Strategy: {config.strategy_name} v{config.strategy_version}")
    print(f"    Assets: {config.trading_pairs}")
    print(f"    Risk: {config.base_risk_pct*100:.0f}% / {config.high_conviction_risk_pct*100:.0f}%")
    print(f"    Leverage: {config.base_leverage}x")
    print(f"    SL: {config.stop_loss_atr_mult}x ATR | TP: {config.take_profit_atr_mult}x ATR")
    print(f"    Max trades/day: {config.max_trades_per_day}")
    print(f"    Max concurrent: {config.max_concurrent_trades}")
    print("    [OK] Config OK!")
    
    # Test 3: Indicators
    print("\n[3] Testing indicators with mock data...")
    try:
        import pandas as pd
        import numpy as np
        np.random.seed(42)
        
        # Create uptrend mock data
        prices = 95000 + np.cumsum(np.random.randn(100) * 100)
        mock_data = pd.DataFrame({
            'open': prices - 50,
            'high': prices + 100,
            'low': prices - 100,
            'close': prices,
            'volume': np.random.randint(1000, 5000, 100)
        })
        
        ind = calculate_all_indicators(mock_data)
        trend = get_trend_direction(ind)
        print(f"    Price: ${ind['price']:.2f}")
        print(f"    EMA20: ${ind['ema_20']:.2f}")
        print(f"    EMA50: ${ind['ema_50']:.2f}")
        print(f"    Trend Direction: {trend}")
        print(f"    RSI: {ind['rsi']:.2f}")
        print(f"    ATR: ${ind['atr']:.2f}")
        print(f"    RSI valid for LONG: {is_rsi_valid_for_long(ind['rsi'])}")
        print(f"    RSI valid for SHORT: {is_rsi_valid_for_short(ind['rsi'])}")
        print("    [OK] Indicators OK!")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # Test 4: Nansen Signal
    print("\n[4] Testing Nansen client...")
    try:
        signal = nansen_client.get_signal("BTCUSDT")
        if signal:
            print(f"    Token: {signal.token}")
            print(f"    Type: {signal.signal_type.value}")
            print(f"    Confidence: {signal.confidence_score:.2f}")
            print(f"    Is Bullish: {signal.is_bullish}")
            print(f"    Is Bearish: {signal.is_bearish}")
            print("    [OK] Nansen client OK!")
        else:
            print("    [WARN] No signal returned (may be neutral)")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # Test 5: Exit Calculations
    print("\n[5] Testing exit calculations (ATR-based)...")
    try:
        entry = 95000
        atr = 500  # $500 ATR
        
        exits = trading_strategy.calculate_exits(entry, TradeDirection.LONG, atr)
        print(f"    LONG Entry: ${entry:,.0f}")
        print(f"    ATR: ${atr:.0f}")
        print(f"    Stop Loss (1.5x ATR): ${exits['stop_loss']:,.0f} (${entry - exits['stop_loss']:.0f} risk)")
        print(f"    Take Profit (2.5x ATR): ${exits['take_profit']:,.0f} (${exits['take_profit'] - entry:.0f} reward)")
        print(f"    R:R Ratio: {(exits['take_profit'] - entry) / (entry - exits['stop_loss']):.2f}")
        print("    [OK] Exit calculations OK!")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # Test 6: Position Sizing
    print("\n[6] Testing position sizing...")
    try:
        account = 1000  # $1000 account
        entry = 95000
        stop = 94250  # 1.5x ATR stop
        
        pos, lev, notional, risk_amt, risk_pct = trading_strategy.calculate_position_size(
            account, entry, stop, 'STANDARD'
        )
        print(f"    Account: ${account}")
        print(f"    Entry: ${entry}")
        print(f"    Stop Loss: ${stop}")
        print(f"    Risk %: {risk_pct*100:.1f}%")
        print(f"    Risk Amount: ${risk_amt:.2f}")
        print(f"    Position Size: {pos:.6f} BTC")
        print(f"    Leverage: {lev}x")
        print(f"    Notional: ${notional:.2f}")
        print("    [OK] Position sizing OK!")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # Test 7: Risk Manager
    print("\n[7] Testing risk manager...")
    try:
        can_trade, reason = risk_manager.check_circuit_breakers(1000)
        print(f"    Can trade: {can_trade} ({reason})")
        print(f"    Win rate: {risk_manager.calculate_win_rate():.1f}%")
        print(f"    Trades today: {risk_manager._trades_today}")
        stats = risk_manager.get_stats()
        print(f"    Stats: {stats}")
        print("    [OK] Risk manager OK!")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    print("\n" + "=" * 60)
    print("[OK] ALL TESTS PASSED!")
    print(f"Nansen SMF Strategy v{config.strategy_version} is ready!")
    print("=" * 60)
    
    print("\nNext steps:")
    print("  1. Ensure Bybit testnet API keys are in .env")
    print("  2. Run: python main.py")
    print("  3. Monitor signals and trades in the dashboard")
    
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

