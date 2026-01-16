"""
Nansen API client for smart money signals and exchange flow data.
Provides accumulation/distribution signals for trading decisions.
"""

import requests
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from config import config
from logger import log_info, log_error, log_signal, log_debug


class SignalType(Enum):
    """Types of Nansen signals."""
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    NEUTRAL = "neutral"


@dataclass
class NansenSignal:
    """Represents a Nansen smart money signal."""
    token: str
    signal_type: SignalType
    strength: float  # 0.0 to 1.0
    smart_money_netflow: float
    exchange_netflow: float
    timestamp: datetime
    
    @property
    def is_bullish(self) -> bool:
        return self.signal_type == SignalType.ACCUMULATION
    
    @property
    def is_bearish(self) -> bool:
        return self.signal_type == SignalType.DISTRIBUTION


class NansenClient:
    """Client for Nansen API integration."""
    
    BASE_URL = "https://api.nansen.ai"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.nansen_api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = timedelta(minutes=5)
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make authenticated request to Nansen API."""
        try:
            url = f"{self.BASE_URL}{endpoint}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            log_error(f"Nansen API error: {e}", exc_info=False)
            return None
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._cache_ttl:
                return data
        return None
    
    def _set_cache(self, key: str, data: Any):
        """Store value in cache."""
        self._cache[key] = (data, datetime.now())
    
    def get_smart_money_netflow(self, token: str, timeframe: str = "24h") -> Optional[Dict]:
        """
        Get smart money netflow for a token.
        
        Args:
            token: Token symbol (e.g., 'BTC', 'ETH')
            timeframe: Time period ('1h', '24h', '7d')
        
        Returns:
            Dict with netflow data or None on error
        """
        cache_key = f"netflow_{token}_{timeframe}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Map common symbols to chain-specific addresses if needed
        token_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum", 
            "SOL": "solana",
            "AVAX": "avalanche",
            "LINK": "chainlink",
            "MATIC": "polygon"
        }
        
        token_id = token_map.get(token.upper().replace("USDT", ""), token.lower())
        
        data = self._request(
            "/v1/smart-money/netflow",
            params={"token": token_id, "timeframe": timeframe}
        )
        
        if data:
            self._set_cache(cache_key, data)
        
        return data
    
    def get_exchange_flow(self, token: str) -> Optional[Dict]:
        """
        Get exchange flow intelligence for a token.
        
        Args:
            token: Token symbol
        
        Returns:
            Dict with inflow/outflow data or None on error
        """
        cache_key = f"exchange_flow_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "AVAX": "avalanche", 
            "LINK": "chainlink",
            "MATIC": "polygon"
        }
        
        token_id = token_map.get(token.upper().replace("USDT", ""), token.lower())
        
        data = self._request(
            "/v1/tgm/flow-intelligence",
            params={"token": token_id}
        )
        
        if data:
            self._set_cache(cache_key, data)
        
        return data
    
    def get_signal(self, symbol: str) -> Optional[NansenSignal]:
        """
        Generate a trading signal based on smart money and exchange flows.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
        
        Returns:
            NansenSignal object or None if data unavailable
        """
        # Strip USDT suffix for Nansen queries
        token = symbol.replace("USDT", "").upper()
        
        # Fetch both data sources
        netflow_data = self.get_smart_money_netflow(token)
        exchange_data = self.get_exchange_flow(token)
        
        if not netflow_data or not exchange_data:
            log_debug(f"Unable to fetch Nansen data for {token}")
            return None
        
        try:
            # Parse netflow (positive = buying, negative = selling)
            smart_money_netflow = netflow_data.get("netflow", 0)
            
            # Parse exchange flow (negative = coins leaving exchanges = bullish)
            exchange_inflow = exchange_data.get("inflow", 0)
            exchange_outflow = exchange_data.get("outflow", 0)
            exchange_netflow = exchange_inflow - exchange_outflow
            
            # Determine signal type and strength
            signal_type = SignalType.NEUTRAL
            strength = 0.0
            
            # Accumulation: smart money buying + coins leaving exchanges
            if smart_money_netflow > 0 and exchange_netflow < 0:
                signal_type = SignalType.ACCUMULATION
                # Normalize strength (0-1 scale)
                netflow_strength = min(abs(smart_money_netflow) / 1000000, 1.0)
                exchange_strength = min(abs(exchange_netflow) / 1000000, 1.0)
                strength = (netflow_strength + exchange_strength) / 2
            
            # Distribution: smart money selling + coins entering exchanges
            elif smart_money_netflow < 0 and exchange_netflow > 0:
                signal_type = SignalType.DISTRIBUTION
                netflow_strength = min(abs(smart_money_netflow) / 1000000, 1.0)
                exchange_strength = min(abs(exchange_netflow) / 1000000, 1.0)
                strength = (netflow_strength + exchange_strength) / 2
            
            signal = NansenSignal(
                token=token,
                signal_type=signal_type,
                strength=strength,
                smart_money_netflow=smart_money_netflow,
                exchange_netflow=exchange_netflow,
                timestamp=datetime.now()
            )
            
            if signal_type != SignalType.NEUTRAL:
                log_signal(
                    symbol=symbol,
                    signal_type=signal_type.value,
                    strength=strength,
                    details=f"SM netflow: {smart_money_netflow:,.0f} | Exchange netflow: {exchange_netflow:,.0f}"
                )
            
            return signal
            
        except (KeyError, TypeError) as e:
            log_error(f"Error parsing Nansen data for {token}: {e}")
            return None
    
    def is_accumulation_signal(self, symbol: str, min_strength: float = 0.3) -> bool:
        """Check if there's a valid accumulation signal."""
        signal = self.get_signal(symbol)
        return (
            signal is not None and 
            signal.signal_type == SignalType.ACCUMULATION and
            signal.strength >= min_strength
        )
    
    def is_distribution_signal(self, symbol: str, min_strength: float = 0.3) -> bool:
        """Check if there's a valid distribution signal."""
        signal = self.get_signal(symbol)
        return (
            signal is not None and
            signal.signal_type == SignalType.DISTRIBUTION and
            signal.strength >= min_strength
        )


# Global client instance
nansen_client = NansenClient()
