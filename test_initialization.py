import os
from dotenv import load_dotenv
from config import config
from exchange import BybitFuturesClient
from nansen import NansenClient
from logger import log_info, log_error

def test_initialization():
    print("=" * 60)
    print("ASMM v3.3.1 Pro - Initialization Test")
    print("=" * 60)
    
    # Check .env loading
    load_dotenv()
    
    # 1. Check API Keys in Config
    print(f"\n[1] Checking API Keys...")
    bybit_key = os.getenv("BYBIT_API_KEY")
    nansen_key = os.getenv("NANSEN_API_KEY")
    
    if bybit_key:
        print(f"    BYBIT_API_KEY: Found ({bybit_key[:4]}...{bybit_key[-4:]})")
    else:
        print(f"    BYBIT_API_KEY: NOT FOUND")
        
    if nansen_key:
        print(f"    NANSEN_API_KEY: Found ({nansen_key[:4]}...{nansen_key[-4:]})")
    else:
        print(f"    NANSEN_API_KEY: NOT FOUND")

    # 2. Test Bybit Client Initialization
    print(f"\n[2] Initializing Bybit Client...")
    try:
        # We manually pass keys to see if it initializes without crashing
        client = BybitFuturesClient()
        print(f"    Bybit Client initialized.")
        print(f"    Mock Mode: {client.mock_mode}")
        
        if not client.mock_mode:
            print(f"    Attempting to fetch public ticker for BTCUSDT...")
            try:
                price = client.get_current_price("BTCUSDT")
                print(f"    Current BTC Price: ${price}")
                print(f"    Public connection: SUCCESS")
            except Exception as e:
                print(f"    Public connection FAILED: {e}")
        else:
            print(f"    Note: Client is in MOCK MODE (likely due to missing secret or config settings).")
            
    except Exception as e:
        print(f"    Bybit Client FAILED to initialize: {e}")

    # 3. Test Nansen Client Initialization
    print(f"\n[3] Initializing Nansen Client...")
    try:
        nansen = NansenClient()
        print(f"    Nansen Client initialized.")
    except Exception as e:
        print(f"    Nansen Client FAILED to initialize: {e}")

    print("\n" + "=" * 60)
    print("INITIALIZATION TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    test_initialization()
