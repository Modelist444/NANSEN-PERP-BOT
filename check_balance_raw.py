import ccxt
from config import config
import json

exchange = ccxt.bybit({
    'apiKey': config.bybit_api_key,
    'secret': config.bybit_api_secret,
    'sandbox': True,
    'options': {
        'defaultType': 'swap',
    }
})

try:
    balance = exchange.fetch_balance()
    # print(json.dumps(balance['info'], indent=2))
    # Let's see all total values
    print("Total balance per coin:")
    for coin, value in balance['total'].items():
        if value > 0:
            print(f"{coin}: {value}")
except Exception as e:
    print(f"Error: {e}")
