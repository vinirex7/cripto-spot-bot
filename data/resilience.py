"""
Resilient wrappers for external API calls with retry logic and exponential backoff.
"""
import time
import random
from typing import Callable, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
import requests

logger = logging.getLogger(__name__)


class RateLimitedAPI:
    """
    Rate-limited API wrapper with exponential backoff and jitter.
    
    Prevents the bot from crashing due to rate limits.
    """
    
    def __init__(self, name: str, max_retries: int = 3, base_delay: float = 1.0):
        """
        Initialize rate-limited API wrapper.
        
        Args:
            name: API name for logging
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff (seconds)
        """
        self.name = name
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.last_call_time = 0.0
        self.min_interval = 0.1  # Minimum 100ms between calls
    
    def call(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        Execute API call with retry logic and backoff.
        
        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
        
        Returns:
            Function result or None on failure
        """
        # Enforce minimum interval
        now = time.time()
        elapsed = now - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        
        # Try with retries
        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                self.last_call_time = time.time()
                return result
            
            except requests.exceptions.HTTPError as e:
                # Check if rate limited (429) or server error (5xx)
                if e.response is not None:
                    status_code = e.response.status_code
                    
                    if status_code == 429:
                        # Rate limited - backoff with jitter
                        delay = self._calculate_backoff(attempt)
                        logger.warning(
                            f"{self.name} rate limited (429), "
                            f"retrying in {delay:.1f}s (attempt {attempt+1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    
                    elif 500 <= status_code < 600:
                        # Server error - retry
                        delay = self._calculate_backoff(attempt)
                        logger.warning(
                            f"{self.name} server error ({status_code}), "
                            f"retrying in {delay:.1f}s"
                        )
                        time.sleep(delay)
                        continue
                    
                    else:
                        # Other HTTP error - don't retry
                        logger.error(f"{self.name} HTTP error {status_code}: {e}")
                        return None
                else:
                    logger.error(f"{self.name} HTTP error: {e}")
                    return None
            
            except requests.exceptions.ConnectionError as e:
                delay = self._calculate_backoff(attempt)
                logger.warning(
                    f"{self.name} connection error, "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                continue
            
            except requests.exceptions.Timeout as e:
                delay = self._calculate_backoff(attempt)
                logger.warning(
                    f"{self.name} timeout, "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                continue
            
            except Exception as e:
                logger.error(f"{self.name} unexpected error: {e}")
                return None
        
        # All retries failed
        logger.error(f"{self.name} failed after {self.max_retries} attempts")
        return None
    
    def _calculate_backoff(self, attempt: int) -> float:
        """
        Calculate backoff delay with exponential backoff and jitter.
        
        Args:
            attempt: Attempt number (0-based)
        
        Returns:
            Delay in seconds
        """
        # Exponential backoff: base_delay * (2 ^ attempt)
        delay = self.base_delay * (2 ** attempt)
        
        # Add jitter (±25%)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        delay += jitter
        
        # Cap at 60 seconds
        delay = min(delay, 60.0)
        
        return delay


class ResilientBinanceClient:
    """
    Resilient wrapper for Binance API client.
    
    Adds retry logic and rate limiting to prevent bot crashes.
    """
    
    def __init__(self, base_client):
        """
        Initialize with base Binance client.
        
        Args:
            base_client: BinanceRESTClient instance
        """
        self.client = base_client
        self.rate_limiter = RateLimitedAPI("Binance", max_retries=3, base_delay=1.0)
    
    def get_klines(self, *args, **kwargs):
        """Get klines with retry logic."""
        return self.rate_limiter.call(self.client.get_klines, *args, **kwargs)
    
    def get_ticker_24h(self, *args, **kwargs):
        """Get 24h ticker with retry logic."""
        return self.rate_limiter.call(self.client.get_ticker_24h, *args, **kwargs)
    
    def get_order_book(self, *args, **kwargs):
        """Get order book with retry logic."""
        return self.rate_limiter.call(self.client.get_order_book, *args, **kwargs)
    
    def place_order(self, *args, **kwargs):
        """Place order with retry logic."""
        # Orders are critical - use stricter retry
        limiter = RateLimitedAPI("Binance.Order", max_retries=2, base_delay=0.5)
        return limiter.call(self.client.place_order, *args, **kwargs)


class ResilientCryptoPanicClient:
    """
    Resilient wrapper for CryptoPanic API client.
    
    If CryptoPanic fails, bot continues with quant-only mode.
    """
    
    def __init__(self, base_client):
        """
        Initialize with base CryptoPanic client.
        
        Args:
            base_client: CryptoPanicClient instance
        """
        self.client = base_client
        self.rate_limiter = RateLimitedAPI("CryptoPanic", max_retries=2, base_delay=2.0)
        self.fallback_mode = False
    
    def fetch_news(self, *args, **kwargs):
        """Fetch news with retry logic and fallback."""
        result = self.rate_limiter.call(self.client.fetch_news, *args, **kwargs)
        
        if result is None:
            if not self.fallback_mode:
                logger.warning("CryptoPanic unavailable - entering quant-only mode")
                self.fallback_mode = True
            return []
        else:
            if self.fallback_mode:
                logger.info("CryptoPanic reconnected - exiting quant-only mode")
                self.fallback_mode = False
            return result
    
    def is_healthy(self) -> bool:
        """Check if API is healthy."""
        return not self.fallback_mode


class ResilientOpenAIClient:
    """
    Resilient wrapper for OpenAI API client.
    
    If OpenAI fails, bot continues with fail-closed policy.
    """
    
    def __init__(self, base_client):
        """
        Initialize with base OpenAI client.
        
        Args:
            base_client: OpenAIClient instance
        """
        self.client = base_client
        self.rate_limiter = RateLimitedAPI("OpenAI", max_retries=2, base_delay=1.0)
    
    def call_api(self, *args, **kwargs):
        """Call OpenAI API with retry logic."""
        if not self.client.is_enabled():
            return None
        
        result = self.rate_limiter.call(self.client.call_api, *args, **kwargs)
        
        if result is None:
            logger.warning("OpenAI unavailable - using fail-closed policy")
        
        return result
