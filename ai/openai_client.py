"""
Rate-limited OpenAI client with caching.
"""
import os
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import logging
import hashlib

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI package not available")

logger = logging.getLogger(__name__)


class OpenAIClient:
    """
    Rate-limited OpenAI client with caching.
    
    Strictly for news analysis and explanations - NEVER for trade decisions.
    """
    
    def __init__(self, config: Dict):
        self.enabled = config.get('enabled', True)
        self.model = config.get('model', 'gpt-4o-mini')
        self.fallback_model = config.get('fallback_model', 'gpt-4o-mini')
        self.temperature = config.get('temperature', 0.0)
        self.max_output_tokens = config.get('max_output_tokens', 220)
        self.max_calls_per_hour = config.get('max_calls_per_hour', 30)
        self.cache_ttl_seconds = config.get('cache_ttl_seconds', 1800)
        self.json_strict = config.get('json_strict', True)
        self.fail_policy = config.get('fail_policy', 'fail_closed')
        
        # API key
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        
        # Initialize client
        self.client = None
        if OPENAI_AVAILABLE and self.api_key and self.enabled:
            try:
                self.client = OpenAI(api_key=self.api_key)
                logger.info("OpenAI client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.enabled = False
        else:
            self.enabled = False
            if not OPENAI_AVAILABLE:
                logger.warning("OpenAI package not installed")
            elif not self.api_key:
                logger.warning("OPENAI_API_KEY not set")
        
        # Rate limiting
        self.call_timestamps = []
        
        # Simple in-memory cache
        self.cache = {}
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = time.time()
        hour_ago = now - 3600
        
        # Remove old timestamps
        self.call_timestamps = [ts for ts in self.call_timestamps if ts > hour_ago]
        
        # Check limit
        if len(self.call_timestamps) >= self.max_calls_per_hour:
            logger.warning(f"Rate limit reached: {len(self.call_timestamps)} calls in last hour")
            return False
        
        return True
    
    def _record_call(self):
        """Record a new API call timestamp."""
        self.call_timestamps.append(time.time())
    
    def _get_cache_key(self, prompt: str, **kwargs) -> str:
        """Generate cache key from prompt and parameters."""
        cache_input = json.dumps({
            'prompt': prompt,
            'model': self.model,
            'temperature': self.temperature,
            **kwargs
        }, sort_keys=True)
        return hashlib.md5(cache_input.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """Get result from cache if not expired."""
        if cache_key not in self.cache:
            return None
        
        cached_item = self.cache[cache_key]
        timestamp = cached_item['timestamp']
        
        # Check if expired
        if time.time() - timestamp > self.cache_ttl_seconds:
            del self.cache[cache_key]
            return None
        
        logger.info(f"Cache hit for key {cache_key[:8]}...")
        return cached_item['result']
    
    def _save_to_cache(self, cache_key: str, result: Dict):
        """Save result to cache."""
        self.cache[cache_key] = {
            'timestamp': time.time(),
            'result': result
        }
    
    def call_api(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[Dict] = None,
        use_cache: bool = True
    ) -> Optional[Dict]:
        """
        Call OpenAI API with rate limiting and caching.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)
            response_format: Response format specification
            use_cache: Whether to use cache
        
        Returns:
            API response or None if disabled/failed
        """
        if not self.enabled or not self.client:
            logger.debug("OpenAI client not enabled")
            return None
        
        # Check cache
        if use_cache:
            cache_key = self._get_cache_key(
                prompt,
                system_prompt=system_prompt,
                response_format=response_format
            )
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                return cached_result
        
        # Check rate limit
        if not self._check_rate_limit():
            logger.warning("Rate limit exceeded, skipping OpenAI call")
            return None
        
        # Prepare messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Call API
        try:
            self._record_call()
            
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_output_tokens
            }
            
            if response_format and self.json_strict:
                kwargs["response_format"] = response_format
            
            response = self.client.chat.completions.create(**kwargs)
            
            # Parse response
            content = response.choices[0].message.content
            
            # Try to parse as JSON if expected
            if response_format:
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    logger.error("Failed to parse JSON response")
                    result = {"error": "Invalid JSON", "raw": content}
            else:
                result = {"content": content}
            
            # Cache result
            if use_cache:
                self._save_to_cache(cache_key, result)
            
            return result
        
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            
            # Try fallback model
            if self.fallback_model and self.fallback_model != self.model:
                try:
                    logger.info(f"Trying fallback model: {self.fallback_model}")
                    kwargs["model"] = self.fallback_model
                    response = self.client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content
                    
                    if response_format:
                        try:
                            result = json.loads(content)
                        except json.JSONDecodeError:
                            result = {"error": "Invalid JSON", "raw": content}
                    else:
                        result = {"content": content}
                    
                    return result
                
                except Exception as e2:
                    logger.error(f"Fallback model also failed: {e2}")
            
            return None
    
    def is_enabled(self) -> bool:
        """Check if OpenAI is enabled and available."""
        return self.enabled and self.client is not None
    
    def get_usage_stats(self) -> Dict[str, any]:
        """Get usage statistics."""
        now = time.time()
        hour_ago = now - 3600
        recent_calls = [ts for ts in self.call_timestamps if ts > hour_ago]
        
        return {
            'enabled': self.enabled,
            'calls_last_hour': len(recent_calls),
            'max_calls_per_hour': self.max_calls_per_hour,
            'cache_size': len(self.cache),
            'model': self.model
        }
