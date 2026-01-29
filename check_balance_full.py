import ccxt
from config import config
import json

exchange = ccxt.bybit({
    'apiKey': config.bybit_api_key,
    'secret': config.bybit_api_secret,
    'sandbox': True
})

try:
    balance = exchange.fetch_balance()
    print(json.dumps(balance['info'], indent=2))
except Exception as e:
    print(f"Error: {e}")
