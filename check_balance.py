import ccxt
from config import config

exchange = ccxt.bybit({
    'apiKey': config.bybit_api_key,
    'secret': config.bybit_api_secret,
    'sandbox': True,
    'options': {
        'defaultType': 'swap',
        'recvWindow': 60000,
    }
})

try:
    balance = exchange.fetch_balance()
    print("Balance keys:", balance.keys())
    print("USDT balance:", balance.get('USDT'))
    print("Total keys:", balance.get('total', {}).keys() if balance.get('total') else "No total")
except Exception as e:
    print(f"Error: {e}")
