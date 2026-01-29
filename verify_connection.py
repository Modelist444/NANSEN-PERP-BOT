import ccxt
from config import config

exchange = ccxt.bybit({
    'apiKey': config.bybit_api_key,
    'secret': config.bybit_api_secret,
    'sandbox': True
})

try:
    markets = exchange.load_markets()
    print(f"Connection OK. Loaded {len(markets)} markets.")
    # Try account info
    # print(exchange.privateGetV5AccountInfo())
except Exception as e:
    print(f"Error: {e}")
