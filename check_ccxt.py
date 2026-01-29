import ccxt
from config import config

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
    print("Balance fetch successful!")
    print(balance['total'])
except Exception as e:
    print(f"Error: {e}")
