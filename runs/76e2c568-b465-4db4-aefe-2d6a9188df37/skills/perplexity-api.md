# perplexity-api

## Overview
The Perplexity API provides real-time search and conversational AI capabilities using the Sonar model family. It supports both synchronous and asynchronous search operations with built-in retry logic, rate limiting, and caching strategies for production deployments. Perfect for building MCP servers that need current, cited information integrated with search results.

## Recommended library / tool
**Perplexity Python SDK** — Official client library with OpenAI-compatible interface and native support for search operations, retry patterns, and environment-based key management.

## Key patterns

### 1. Environment-based key management with fallback
```python
import os
from perplexity import Perplexity

primary_key = os.getenv("PERPLEXITY_API_KEY")
fallback_key = os.getenv("PERPLEXITY_API_KEY_FALLBACK")

if not primary_key:
    raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")

client = Perplexity(api_key=primary_key)
# Switch on failure: client = Perplexity(api_key=fallback_key)
```

### 2. Resilient search with retry and exponential backoff
```python
import asyncio
from typing import Optional

async def resilient_search(client, query: str, max_retries: int = 3) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            result = await client.search.create(query=query, max_results=5)
            return result
        except RateLimitError:
            delay = 2 ** attempt
            await asyncio.sleep(delay)
    return None
```

### 3. Batch search with concurrency control
```python
async def batch_search(client, queries: list[str], batch_size: int = 3, delay_ms: float = 1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i : i + batch_size]
        tasks = [resilient_search(client, q) for q in batch]
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)
        if i + batch_size < len(queries):
            await asyncio.sleep(delay_ms / 1000)
    return results
```

### 4. Query result caching with TTL
```python
import time
from typing import Optional, Tuple, Any

class SearchCache:
    def __init__(self, ttl_seconds: int = 3600):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, query: str) -> Optional[Any]:
        if query in self.cache:
            result, timestamp = self.cache[query]
            if time.time() - timestamp < self.ttl:
                return result
        return None
    
    def set(self, query: str, result: Any):
        self.cache[query] = (result, time.time())
```

### 5. Logging and observability wrapper
```python
import time
import logging

class ObservedClient:
    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger(__name__)
    
    def search(self, query: str, **kwargs) -> dict:
        start = time.time()
        self._log_request("search", query=query)
        try:
            result = self.client.search.create(query=query, **kwargs)
            duration = time.time() - start
            self._log_response("search", duration, success=True)
            return result
        except Exception as e:
            duration = time.time() - start
            self._log_response("search", duration, success=False)
            raise
    
    def _log_request(self, method: str, **kwargs):
        self.logger.info(f"Request: {method} {kwargs}")
    
    def _log_response(self, method: str, duration: float, success: bool = True):
        self.logger.info(f"Response: {method} ({duration:.2f}s) - {'OK' if success else 'FAIL'}")
```

## Gotchas

1. **Missing or expired API keys**: Always validate `PERPLEXITY_API_KEY` at initialization. Use fallback keys for production, but ensure both are valid and have quota remaining. The SDK will not retry on authentication errors.

2. **Rate limiting without backoff**: Perplexity applies aggressive rate limits. Naive retry loops without exponential backoff will exhaust quota quickly. Implement `asyncio.sleep(2 ** attempt)` delays and respect `429` responses with `Retry-After` headers when present.

3. **Unbounded `max_results` parameter**: Setting `max_results=50` costs significantly more than `max_results=5`. Default to small result sets (5-10) and only increase when necessary. Cache identical queries to avoid duplicate API calls across requests.

recommended_tool: Perplexity Python SDK