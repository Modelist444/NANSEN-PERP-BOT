"""
Nansen API client for smart money signals and exchange flow data.
Provides accumulation/distribution signals for Nansen SMF Strategy v4.0.
Key Output: SignalType (ACCUMULATION/DISTRIBUTION/NEUTRAL) + confidence_score (0.0-1.0)
"""

import requests
import random
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import time
import os
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
    """Represents a Nansen smart money signal for v4.0 strategy."""
    token: str
    signal_type: SignalType
    strength: float  # 0.0 to 1.0
    smart_money_netflow: float
    exchange_netflow: float
    timestamp: datetime
    
    @property
    def confidence_score(self) -> float:
        """Alias for strength - used as confidence score in v4.0."""
        return self.strength
    
    @property
    def is_bullish(self) -> bool:
        return self.signal_type == SignalType.ACCUMULATION
    
    @property
    def is_bearish(self) -> bool:
        return self.signal_type == SignalType.DISTRIBUTION
    
    @property
    def is_neutral(self) -> bool:
        return self.signal_type == SignalType.NEUTRAL
    
    def to_dict(self) -> Dict:
        """Convert signal to dictionary for logging."""
        return {
            'token': self.token,
            'signal_type': self.signal_type.value,
            'confidence_score': self.confidence_score,
            'smart_money_netflow': self.smart_money_netflow,
            'exchange_netflow': self.exchange_netflow,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class Tier1Signal:
    """Tier 1: Core entry conditions (5/5 required)."""
    sm_netflow_positive: bool      # SM net-buying 24h (LONG) / selling (SHORT)
    exchange_netflow_bullish: bool # Outflow (LONG) / Inflow (SHORT)
    vwap_confirmed: bool           # Above/reclaiming (LONG) / Below/failing (SHORT)
    atr_rising: bool               # Volatility momentum
    not_crowded: bool              # Funding <0.08% (LONG) / >0.05% (SHORT)
    
    def is_valid(self) -> bool:
        """Check if all 5 Tier 1 conditions are met."""
        return all([
            self.sm_netflow_positive,
            self.exchange_netflow_bullish,
            self.vwap_confirmed,
            self.atr_rising,
            self.not_crowded
        ])


@dataclass
class Tier2Signal:
    """Tier 2: Enhancement signals for position sizing."""
    sm_perp_ratio_ok: bool         # LONG >50% / SHORT >55%
    sm_position_health: float      # >40%
    multi_tf_aligned: bool         # Netflow aligned across TFs
    institutional_aligned: bool
    concentration_ok: bool         # <80%
    funding_optimal: bool          # <0.05% LONG / >0.05% SHORT
    whale_flow_supporting: bool    # Accumulation/Distribution
    
    def get_conviction(self) -> str:
        """Calculate conviction level based on Tier 2 score."""
        score = sum([
            self.sm_perp_ratio_ok,
            self.sm_position_health > 0.4,
            self.multi_tf_aligned,
            self.institutional_aligned,
            self.concentration_ok,
            self.funding_optimal,
            self.whale_flow_supporting
        ])
        
        if score >= 6:
            return "HIGH"      # 6-7 signals
        elif score >= 4:
            return "STANDARD"  # 4-5 signals
        elif score >= 2:
            return "LOW"       # 2-3 signals
        else:
            return "NO_TRADE"  # 0-1 signals


@dataclass
class Tier3Signal:
    """Tier 3: Advanced edge signals."""
    whale_flow: str                # "accumulation" / "distribution" / "neutral"
    cross_asset_regime: str        # "LOW_CORR" / "MEDIUM_CORR" / "HIGH_CORR"
    sentiment_divergence: str      # "bullish" / "bearish" / "neutral"
    institutional_pnl: float       # Institutional PnL metric
    
    def get_edge(self) -> str:
        """Calculate edge level based on Tier 3 signals."""
        score = 0
        
        # Whale flow alignment
        if self.whale_flow in ["accumulation", "distribution"]:
            score += 1
        
        # Avoid high correlation regimes
        if self.cross_asset_regime != "HIGH_CORR":
            score += 1
        
        # Sentiment divergence (contrarian)
        if self.sentiment_divergence != "neutral":
            score += 1
        
        # Institutional PnL positive
        if self.institutional_pnl > 0:
            score += 1
        
        if score >= 3:
            return "MAX"       # 3-4 edge signals
        elif score >= 2:
            return "STANDARD"  # 2 edge signals
        else:
            return "MINIMAL"   # 0-1 edge signals


class NansenClient:
    """Client for Nansen API integration."""
    
    BASE_URL = "https://api.nansen.ai/api/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.nansen_api_key
        # v3.3.1: Auto-Mock if key is missing
        self.mock_mode = not self.api_key or config.dry_run
        
        self.session = requests.Session()
        if not self.mock_mode:
            self.session.headers.update({
                "apikey": self.api_key,
                "Content-Type": "application/json"
            })
        
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = timedelta(minutes=5)
    
    def _request(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make authenticated request to Nansen API."""
        try:
            url = f"{self.BASE_URL}{endpoint}"
            if method.upper() == "POST":
                log_debug(f"DEBUG: Nansen POST {endpoint} Payload: {data}")
                response = self.session.post(url, json=data, timeout=30)
            else:
                log_debug(f"DEBUG: Nansen GET {endpoint} Params: {params}")
                response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                log_error(f"❌ Nansen API Error [{response.status_code}] for {endpoint}: {response.text}")
                return None
                
            return response.json()
        except requests.exceptions.RequestException as e:
            log_error(f"❌ Nansen request failed: {e}")
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
        
        token_info = self._get_token_info(token)
        chain = token_info.get("chain", "ethereum")
        
        # v4.3.3: Simplified payload - just chain and time_range
        data = self._request(
            "/smart-money/netflow",
            method="POST",
            data={
                "chain": chain,
                "time_range": timeframe
            }
        )
        
        # Debug: Log raw response to understand structure
        if data:
            log_debug(f"Nansen Netflow Response for {token}: {data}")
            self._set_cache(cache_key, data)
        else:
            log_info(f"Nansen Netflow returned None for {token} (chain={chain})")
        
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
        
        token_info = self._get_token_info(token)
        chain = token_info.get("chain")
        address = token_info.get("address")
        
        # TGM Flow Intelligence requires a supported chain and token address
        if not chain or not address:
            log_info(f"ℹ️ {token}: Skipping exchange flow (No chain/address mapped)")
            return None

        data = self._request(
            "/tgm/flow-intelligence",
            method="POST",
            data={
                "chain": chain,
                "token_address": address
            }
        )
        
        if data:
            self._set_cache(cache_key, data)
        
        return data
    async def get_signal_async(self, token: str) -> Optional[NansenSignal]:
        """Fetch signal asynchronously (Simulated in Mock Mode)."""
        if self.mock_mode:
            # Generate random but stable signals
            token_val = abs(hash(token)) % 100
            if token_val < 30:
                sig_type = SignalType.ACCUMULATION
                sm_flow = 1000000.0
                ex_flow = -500000.0
            elif token_val < 60:
                sig_type = SignalType.DISTRIBUTION
                sm_flow = -1000000.0
                ex_flow = 500000.0
            else:
                sig_type = SignalType.NEUTRAL
                sm_flow = 0.0
                ex_flow = 0.0
                
            return NansenSignal(
                token=token,
                signal_type=sig_type,
                strength=random.uniform(0.1, 0.9),
                smart_money_netflow=sm_flow,
                exchange_netflow=ex_flow,
                timestamp=datetime.now()
            )

        # Original implementation...
        return self.get_signal(token)
    
    def get_signal(self, symbol: str) -> Optional[NansenSignal]:
        """Generate a trading signal (with Mock support)."""
        # Strip USDT suffix for Nansen queries
        token = symbol.replace("USDT", "").upper()

        if self.mock_mode:
            # v3.3.1: Alternating signals for Balanced Simulation
            # Alternate between Long and Short every minute based on time
            seconds = int(time.time())
            is_uptrend = (seconds // 60) % 2 == 0 
            
            if token == "BTC":
                if is_uptrend:
                    sig_type = SignalType.ACCUMULATION
                    sm_flow = 2500000.0
                    ex_flow = -1200000.0
                else:
                    sig_type = SignalType.DISTRIBUTION
                    sm_flow = -2500000.0
                    ex_flow = 1200000.0
                strength = 0.95
            else:
                # Random logic for other tokens
                token_val = (abs(hash(token)) + datetime.now().hour) % 100
                if token_val < 35:
                    sig_type = SignalType.ACCUMULATION
                    sm_flow = random.uniform(500000, 2000000)
                    ex_flow = -random.uniform(200000, 1000000)
                elif token_val < 70:
                    sig_type = SignalType.DISTRIBUTION
                    sm_flow = -random.uniform(500000, 2000000)
                    ex_flow = random.uniform(200000, 1000000)
                else:
                    sig_type = SignalType.NEUTRAL
                    sm_flow = random.uniform(-100000, 100000)
                    ex_flow = random.uniform(-100000, 100000)
                strength = random.uniform(0.6, 0.95)
                
            return NansenSignal(
                token=token,
                signal_type=sig_type,
                strength=strength,
                smart_money_netflow=sm_flow,
                exchange_netflow=ex_flow,
                timestamp=datetime.now()
            )
        
        # Fetch both data sources
        netflow_data = self.get_smart_money_netflow(token)
        exchange_data = self.get_exchange_flow(token)
        
        if not netflow_data:
            log_info(f"⚠️ Nansen Data Missing for {token} (Netflow: False, Exchange: {bool(exchange_data)})")
            
            # Fallback for TESTING only
            if os.getenv("NANSEN_DEBUG_FALLBACK", "false").lower() == "true":
                log_info(f"🧪 [DEBUG] Injecting Fallback Signal for {token}")
                return NansenSignal(
                    token=token,
                    signal_type=SignalType.ACCUMULATION,
                    strength=0.8,
                    smart_money_netflow=1000000.0,
                    exchange_netflow=-500000.0,
                    timestamp=datetime.now()
                )
            return None
        
        try:
            # Parse netflow (positive = buying, negative = selling)
            smart_money_netflow = netflow_data.get("netflow", 0)
            
            # Parse exchange flow (negative = coins leaving exchanges = bullish)
            # v4.3.1: Handle missing exchange flow gracefully (API 404s)
            exchange_netflow = 0
            if exchange_data:
                exchange_inflow = exchange_data.get("inflow", 0)
                exchange_outflow = exchange_data.get("outflow", 0)
                exchange_netflow = exchange_inflow - exchange_outflow
            else:
                log_info(f"ℹ️ {token}: Using Netflow only (Exchange Flow unavailable)")
            
            # Determine signal type and strength
            
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
    
    # ========== TIER 2 SIGNAL METHODS ==========
    
    def get_sm_perp_ratio(self, token: str) -> Optional[float]:
        """Get smart money perpetual long/short ratio."""
        cache_key = f"sm_perp_ratio_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/smart-money/perp-ratio",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "long_ratio" in data:
            ratio = float(data["long_ratio"])
            self._set_cache(cache_key, ratio)
            return ratio
        return None
    
    def get_sm_position_health(self, token: str) -> Optional[float]:
        """Get smart money position health score (0-100)."""
        cache_key = f"sm_position_health_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/smart-money/position-health",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "health_score" in data:
            health = float(data["health_score"])
            self._set_cache(cache_key, health)
            return health
        return None
    
    def get_multi_tf_netflow(self, token: str) -> Optional[Dict]:
        """Get netflow across multiple timeframes."""
        cache_key = f"multi_tf_netflow_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/smart-money/multi-timeframe-netflow",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data:
            self._set_cache(cache_key, data)
        return data
    
    def get_institutional_flow(self, token: str) -> Optional[Dict]:
        """Get institutional flow data."""
        cache_key = f"institutional_flow_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/institutional/flow",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data:
            self._set_cache(cache_key, data)
        return data
    
    def get_concentration(self, token: str) -> Optional[float]:
        """Get token concentration metric (0-100)."""
        cache_key = f"concentration_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/token/concentration",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "concentration" in data:
            conc = float(data["concentration"])
            self._set_cache(cache_key, conc)
            return conc
        return None
    
    def get_whale_flow(self, token: str) -> str:
        """Get whale flow direction: accumulation/distribution/neutral."""
        cache_key = f"whale_flow_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/whale/flow",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "direction" in data:
            direction = data["direction"].lower()
            self._set_cache(cache_key, direction)
            return direction
        return "neutral"
    
    def get_cross_asset_regime(self) -> str:
        """Get cross-asset correlation regime: LOW_CORR/MEDIUM_CORR/HIGH_CORR."""
        cache_key = "cross_asset_regime"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        data = self._request("/market/correlation-regime")
        
        if data and "regime" in data:
            regime = data["regime"].upper()
            self._set_cache(cache_key, regime)
            return regime
        return "MEDIUM_CORR"  # Default
    
    def get_sentiment_divergence(self, token: str) -> str:
        """Get sentiment divergence: bullish/bearish/neutral."""
        cache_key = f"sentiment_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/sentiment/divergence",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "sentiment" in data:
            sentiment = data["sentiment"].lower()
            self._set_cache(cache_key, sentiment)
            return sentiment
        return "neutral"
    
    def get_institutional_pnl(self, token: str) -> float:
        """Get institutional PnL metric."""
        cache_key = f"institutional_pnl_{token}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        token_info = self._get_token_info(token)
        data = self._request(
            "/institutional/pnl",
            method="POST",
            data={
                "chains": [token_info.get("chain", "ethereum")],
                "filters": {
                    "token_address": token_info.get("address")
                }
            }
        )
        
        if data and "pnl" in data:
            pnl = float(data["pnl"])
            self._set_cache(cache_key, pnl)
            return pnl
        return 0.0
    
    def _get_token_info(self, token: str) -> Dict[str, str]:
        """Map common symbols to chain, ID, and address information."""
        # v1: Token addresses are required for TGM endpoints
        token_map = {
            "BTC": {
                "chain": "ethereum", # Use WBTC for flow proxy since BTC chain not supported in TGM
                "id": "bitcoin",
                "address": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599" # WBTC
            },
            "ETH": {
                "chain": "ethereum",
                "id": "ethereum",
                "address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2" # WETH (Nansen doesn't like 0x0...0)
            },
            "SOL": {
                "chain": "solana",
                "id": "solana",
                "address": "So11111111111111111111111111111111111111112" # Wrapped SOL
            }
        }
        
        symbol = token.upper().replace("USDT", "")
        return token_map.get(symbol, {})

    def _get_token_id(self, token: str) -> str:
        """Map common symbols to token IDs."""
        return self._get_token_info(token).get("id")


# Global client instance
nansen_client = NansenClient()
