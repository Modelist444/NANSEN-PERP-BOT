from config import config
import os

print(f"API Key: {config.bybit_api_key}")
print(f"API Secret length: {len(config.bybit_api_secret) if config.bybit_api_secret else 0}")
print(f"API Secret starts with: {config.bybit_api_secret[:20] if config.bybit_api_secret else 'None'}")
print(f"API Secret ends with: {config.bybit_api_secret[-20:] if config.bybit_api_secret else 'None'}")
