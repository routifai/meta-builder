# perplexity-api

## Overview
Perplexity API provides conversational AI with real-time web search capabilities, enabling applications to deliver current, cited information. The API uses OpenAI-compatible endpoints and offers multiple Sonar models optimized for different use cases. Build MCP servers by wrapping search/chat operations with retry logic, rate limiting, and fallback mechanisms for production reliability.

## Recommended library / tool
**OpenAI Python SDK** — drop-in compatible with Perplexity's base URL, simplifies chat completions and streaming patterns.

## Key patterns

**1. Client initialization with environment variables:**
```python
from openai import OpenAI
import os

api_key = os.getenv("PERPLEXITY_API_KEY")
client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
```

**2. Chat completions with Sonar models:**
```python
response = client.chat.completions.create(
    model="sonar-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

**3. Resilient search with retry logic:**
```python
import time
from typing import Optional

def resilient_search(client, query: str, max_retries: int = 3) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            return client.search.create(query=query, max_results=5)
        except Exception as e:
            if "rate_limit" in str(e).lower():
                delay = 2 ** attempt
                time.sleep(delay)
            else:
                raise
    return None
```

**4. Fallback API key pattern:**
```python
class ResilientPerplexityClient:
    def __init__(self, primary_key: str, fallback_key: Optional[str] = None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = OpenAI(api_key=self.primary_key, base_url="https://api.perplexity.ai")
    
    def search(self, query: str, **kwargs):
        try:
            return self.current_client.search.create(query=query, **kwargs)
        except Exception:
            self.current_client = OpenAI(api_key=self.fallback_key, base_url="https://api.perplexity.ai")
            return self.current_client.search.create(query=query, **kwargs)
```

**5. Batch search with rate-limiting:**
```python
import asyncio

async def batch_search(client, queries: list, batch_size: int = 3, delay_ms: int = 1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i+batch_size]
        tasks = [client.search.create(query=q, max_results=5) for q in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend(batch_results)
        await asyncio.sleep(delay_ms / 1000)
    return results
```

## Gotchas

1. **Rate limiting without backoff:** The Sonar API enforces strict rate limits. Always implement exponential backoff (2^attempt) and check for `rate_limit` errors before retrying. Naive loops will fail fast in production.

2. **Forgetting base_url:** Using the standard OpenAI SDK without overriding `base_url="https://api.perplexity.ai"` will route requests to OpenAI instead. This is a silent failure if your API key happens to work with both services.

3. **API key exposure in logs:** Never log the raw response object or include `PERPLEXITY_API_KEY` in error messages. Use structured logging with scrubbed payloads, and always load keys from environment variables, not hardcoded strings.

recommended_tool: openai

---
## Researcher update

# perplexity-api

## Overview
The Perplexity API provides conversational AI with real-time search capabilities, combining chat completions with web search for current, cited information. It uses OpenAI-compatible SDKs and offers multiple Sonar models optimized for different use cases. Essential for building MCP servers that need live web search integrated with LLM responses.

## Recommended library / tool
**Perplexity Python SDK** — Official SDK with native retry logic, batch processing, and search-specific methods; easier than raw HTTP calls.

## Key patterns

**1. Basic search with Sonar model**
```python
from perplexity import Perplexity
import os

client = Perplexity(api_key=os.getenv("PERPLEXITY_API_KEY"))
response = client.chat.completions.create(
    model="sonar-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

**2. Fallback API key handling (production resilience)**
```python
class PerplexityClient:
    def __init__(self, primary_key=None, fallback_key=None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = Perplexity(api_key=self.primary_key)
    
    def search(self, query: str, **kwargs):
        try:
            return self.current_client.search.create(query=query, **kwargs)
        except Exception:
            self.current_client = Perplexity(api_key=self.fallback_key)
            return self.current_client.search.create(query=query, **kwargs)
```

**3. Async batch search with retry logic**
```python
async def batch_search(queries, batch_size=3, delay_ms=1000):
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i + batch_size]
        tasks = [
            resilient_search(client, query, max_retries=3)
            for query in batch
        ]
        await asyncio.sleep(delay_ms / 1000)
        yield await asyncio.gather(*tasks)

async def resilient_search(client, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await client.search.create(query=query, max_results=5)
        except RateLimitError:
            await asyncio.sleep(2 ** attempt)
```

**4. Search result caching for cost control**
```python
class SearchCache:
    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, query: str):
        if query in self.cache:
            result, timestamp = self.cache[query]
            if time.time() - timestamp < self.ttl:
                return result
        return None
    
    def set(self, query: str, result):
        self.cache[query] = (result, time.time())
```

**5. MCP server integration pattern**
```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("perplexity-search")
client = Perplexity(api_key=os.getenv("PERPLEXITY_API_KEY"))

@server.call_tool()
async def search_tool(query: str, model: str = "sonar-pro"):
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": query}]
    )
    return TextContent(text=response.choices[0].message.content)
```

## Gotchas

**1. API key environment variable required**  
Must set `PERPLEXITY_API_KEY` explicitly. Code will fail silently if missing—use defensive checks:
```python
api_key = os.getenv("PERPLEXITY_API_KEY")
if not api_key:
    raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")
```

**2. Rate limiting without backoff**  
Default requests hit rate limits quickly in production. Always implement exponential backoff and batch with delays between calls (1s+ between batches recommended).

**3. Sonar model selection matters for cost**  
`sonar` vs `sonar-pro` have different pricing and latency. Select the right model upfront based on latency/cost requirements; switching models mid-stream wastes budget.

recommended_tool: Perplexity Python SDK

---
## Researcher update

# perplexity-api

## Overview
The Perplexity API provides conversational AI with real-time search capabilities through the OpenAI-compatible client interface. It combines language models (Sonar Pro, Sonar) with web search for current, cited information. Use this to build MCP servers that deliver up-to-date search results and reasoning in production environments.

## Recommended library / tool
OpenAI Python SDK (v1.0+) — Perplexity uses OpenAI-compatible endpoints, so the standard OpenAI client works with a custom base URL.

## Key patterns

**Authentication & Client Setup**
```python
from openai import OpenAI
import os

api_key = os.getenv("PERPLEXITY_API_KEY")
if not api_key:
    raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.perplexity.ai"
)
```

**Basic Search Query**
```python
response = client.chat.completions.create(
    model="sonar-pro",  # or "sonar" for lower cost
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

**Resilient Search with Retry Logic**
```python
import asyncio
import logging

logger = logging.getLogger(__name__)

async def resilient_search(client, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}],
                max_tokens=1000
            )
            logger.info(f"Search successful for: {query}")
            return result
        except Exception as e:
            if "rate_limit" in str(e).lower():
                delay = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {delay}s")
                await asyncio.sleep(delay)
            else:
                logger.error(f"API error for '{query}': {e}")
                raise
    raise RuntimeError(f"Max retries exceeded for: {query}")
```

**Fallback API Key Strategy**
```python
class ResilientPerplexityClient:
    def __init__(self, primary_key, fallback_key=None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = OpenAI(
            api_key=self.primary_key,
            base_url="https://api.perplexity.ai"
        )
    
    def search(self, query: str, **kwargs):
        try:
            return self.current_client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}],
                **kwargs
            )
        except Exception:
            if self.fallback_key:
                logger.warning("Switching to fallback API key")
                self.current_client = OpenAI(
                    api_key=self.fallback_key,
                    base_url="https://api.perplexity.ai"
                )
                return self.current_client.chat.completions.create(
                    model="sonar-pro",
                    messages=[{"role": "user", "content": query}],
                    **kwargs
                )
            raise
```

**Batch Processing with Rate Limiting**
```python
async def batch_search(client, queries, batch_size=5, delay_ms=1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i+batch_size]
        tasks = [
            resilient_search(client, q) 
            for q in batch
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend(batch_results)
        if i + batch_size < len(queries):
            await asyncio.sleep(delay_ms / 1000.0)
    return results
```

## Gotchas

**Rate Limiting & Quota Management**
The Perplexity API enforces rate limits per plan tier. Implement exponential backoff (2^attempt seconds) and batch processing with delays between batches. Monitor costs closely—sonar-pro is more capable but higher cost than sonar; choose the right model for your use case.

**Async Patterns Required for Production**
Synchronous blocking calls will starve an MCP server's event loop. Always use `async` variants with proper concurrency control (semaphores, batch limits) to prevent overwhelming the API and your deployment.

**Missing or Stale Environment Variables**
Forgetting to set `PERPLEXITY_API_KEY` in your container/deployment environment causes cryptic authentication errors at runtime. Always validate on startup and use fallback keys for high-availability production setups. Never hardcode keys in code.

recommended_tool: openai

---
## Researcher update

# perplexity-api

## Overview
Perplexity API provides conversational AI with real-time web search capabilities, using the OpenAI-compatible client interface. It offers multiple Sonar models optimized for different latency/accuracy tradeoffs and includes Search API for raw ranked web results. Essential for building MCP servers that need current, cited information with production-grade reliability patterns.

## Recommended library / tool
**OpenAI Python SDK** — Perplexity uses OpenAI-compatible API endpoints, so the standard `openai` library works directly with `base_url="https://api.perplexity.ai"`.

## Key patterns

### 1. Client initialization with environment variables
```python
from openai import OpenAI
import os

api_key = os.getenv("PERPLEXITY_API_KEY")
if not api_key:
    raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")

client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
```

### 2. Basic chat completion (sonar models)
```python
response = client.chat.completions.create(
    model="sonar-pro",  # or "sonar" for faster, cheaper inference
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

### 3. Fallback key strategy for high availability
```python
class PerplexityClientWithFallback:
    def __init__(self, primary_key: str = None, fallback_key: str = None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = OpenAI(api_key=self.primary_key, base_url="https://api.perplexity.ai")
    
    def search(self, query: str, **kwargs):
        try:
            return self.current_client.chat.completions.create(
                model="sonar-pro", 
                messages=[{"role": "user", "content": query}],
                **kwargs
            )
        except Exception as e:
            self.current_client = OpenAI(api_key=self.fallback_key, base_url="https://api.perplexity.ai")
            return self.current_client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}],
                **kwargs
            )
```

### 4. Async batch search with resilience
```python
import asyncio
import logging

async def resilient_search(client, query: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            result = await client.chat.completions.create(
                model="sonar",
                messages=[{"role": "user", "content": query}],
                max_tokens=500
            )
            logging.info(f"Search successful: {query}")
            return result
        except Exception as e:
            if "rate_limit" in str(e).lower():
                delay = 2 ** attempt
                logging.warning(f"Rate limited, retrying in {delay}s")
                await asyncio.sleep(delay)
            else:
                logging.error(f"API error: {e}")
                raise
    raise RuntimeError(f"Max retries exceeded for: {query}")

async def batch_search(queries: list, batch_size: int = 3):
    tasks = [resilient_search(client, q) for q in queries]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

### 5. Request/response logging for debugging
```python
import time
from typing import Any

class LoggingWrapper:
    def __init__(self, client):
        self.client = client
    
    def _log_request(self, method: str, **kwargs):
        logging.info(f"[{method}] Request: {kwargs}")
    
    def _log_response(self, method: str, duration: float, success: bool = True):
        status = "✓" if success else "✗"
        logging.info(f"[{method}] Response ({status}) took {duration:.2f}s")
    
    def search(self, query: str, **kwargs):
        start = time.time()
        self._log_request("search", query=query)
        try:
            result = self.client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}],
                **kwargs
            )
            self._log_response("search", time.time() - start, success=True)
            return result
        except Exception as e:
            self._log_response("search", time.time() - start, success=False)
            raise
```

## Gotchas

1. **Environment variable not set**: Always check that `PERPLEXITY_API_KEY` is exported in production. The SDK won't automatically look it up; you must explicitly pass it or retrieve it with `os.getenv()`. Missing keys will only fail at request time, not initialization.

2. **Rate limiting without backoff**: Perplexity enforces rate limits per API key. Naive retry loops will exhaust retries immediately. Use exponential backoff (`2^attempt`) and check error messages for `rate_limit` indicators before retrying.

3. **Model selection trade-offs**: `sonar` is faster and cheaper but less accurate; `sonar-pro` is slower but higher quality. For MCP server deployment, pick based on expected query latency budget (SLAs) and cost constraints. Default to `sonar` unless you need cite-quality responses.

4. **Async context managers**: When using async clients in MCP servers, ensure proper cleanup of client connections. Always use context managers or explicit `close()` calls to avoid resource le

---
## Researcher update

# perplexity-api

## Overview
The Perplexity API provides conversational AI with real-time search capabilities, using OpenAI-compatible endpoints. Build MCP servers that integrate Perplexity's Sonar models for current, cited search results. Deploy production systems with proper auth, rate limiting, and fallback strategies.

## Recommended library / tool
OpenAI Python SDK (with Perplexity base_url) — native support for Perplexity's chat completions interface with minimal setup.

## Key patterns

**1. Basic client initialization with environment variables**
```python
from openai import OpenAI
import os

api_key = os.getenv("PERPLEXITY_API_KEY")
client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
```

**2. Chat completions with Sonar models**
```python
response = client.chat.completions.create(
    model="sonar-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

**3. Fallback API key pattern for high availability**
```python
class PerplexityClientManager:
    def __init__(self, primary_key=None, fallback_key=None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = OpenAI(api_key=self.primary_key, 
                                      base_url="https://api.perplexity.ai")
    
    def search(self, query: str, **kwargs):
        try:
            return self.current_client.chat.completions.create(
                model="sonar-pro", 
                messages=[{"role": "user", "content": query}],
                **kwargs
            )
        except Exception as e:
            self.current_client = OpenAI(api_key=self.fallback_key,
                                         base_url="https://api.perplexity.ai")
            return self.current_client.chat.completions.create(...)
```

**4. Batch search with rate limiting and retry logic**
```python
import asyncio
import time

async def resilient_search(client, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}]
            )
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                await asyncio.sleep(delay)
            else:
                raise

async def batch_search(client, queries, batch_size=3, delay_ms=1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i+batch_size]
        tasks = [resilient_search(client, q) for q in batch]
        results.extend(await asyncio.gather(*tasks, return_exceptions=True))
        if i + batch_size < len(queries):
            await asyncio.sleep(delay_ms / 1000)
    return results
```

**5. Query result caching for cost optimization**
```python
import time
from typing import Optional, Dict, Any

class SearchCache:
    def __init__(self, ttl_seconds=3600):
        self.cache: Dict[str, tuple] = {}
        self.ttl = ttl_seconds
    
    def get(self, query: str) -> Optional[Any]:
        if query in self.cache:
            result, timestamp = self.cache[query]
            if time.time() - timestamp < self.ttl:
                return result
            del self.cache[query]
        return None
    
    def set(self, query: str, result: Any):
        self.cache[query] = (result, time.time())
```

## Gotchas

**1. API key must be passed to base_url endpoint**
Don't forget to set `base_url="https://api.perplexity.ai"` when initializing the OpenAI client, otherwise requests will hit OpenAI's servers instead of Perplexity's.

**2. Rate limits aren't automatically handled**
Implement explicit retry logic with exponential backoff; the SDK won't retry on 429 responses. Always batch queries with delays between batches in production.

**3. Model selection impacts cost and latency**
`sonar-pro` offers higher accuracy and citations; `sonar` is faster and cheaper. Clarify your use case before committing to production — test both models for your MCP server workload.

recommended_tool: OpenAI Python SDK

---
## Researcher update

# perplexity-api

## Overview
Perplexity API provides conversational AI with real-time web search capabilities, combining LLM responses with current, cited information. The API uses OpenAI-compatible SDK patterns and offers multiple Sonar models optimized for different latency/cost tradeoffs. Build MCP servers by wrapping the search/chat APIs with retry logic, rate limiting, and fallback key management for production resilience.

## Recommended library / tool
OpenAI Python SDK (with Perplexity base_url) — direct compatibility with OpenAI client interface, minimal migration friction.

## Key patterns

**1. Initialize client with environment variables and base_url override:**
```python
from openai import OpenAI
import os

client = OpenAI(
    api_key=os.getenv("PERPLEXITY_API_KEY"),
    base_url="https://api.perplexity.ai"
)
```

**2. Chat completions with sonar-pro model:**
```python
response = client.chat.completions.create(
    model="sonar-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)
print(response.choices[0].message.content)
```

**3. Implement retry wrapper with exponential backoff:**
```python
import time
from functools import wraps

def retry_on_rate_limit(max_retries=3):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "rate" in str(e).lower() and attempt < max_retries - 1:
                        delay = 2 ** attempt
                        time.sleep(delay)
                    else:
                        raise
        return wrapper
    return decorator
```

**4. Fallback API key pattern for high availability:**
```python
class PerplexityClientManager:
    def __init__(self):
        self.primary_key = os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        self.current_client = OpenAI(api_key=self.primary_key, base_url="https://api.perplexity.ai")
    
    def search(self, query):
        try:
            return self.current_client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}]
            )
        except Exception as e:
            self.current_client = OpenAI(api_key=self.fallback_key, base_url="https://api.perplexity.ai")
            return self.current_client.chat.completions.create(
                model="sonar-pro",
                messages=[{"role": "user", "content": query}]
            )
```

**5. Async batch processing with rate limiting:**
```python
import asyncio

async def batch_search(queries, batch_size=3, delay_ms=1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i+batch_size]
        tasks = [client.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": q}]
        ) for q in batch]
        results.extend(await asyncio.gather(*tasks))
        await asyncio.sleep(delay_ms / 1000)
    return results
```

## Gotchas

**1. API key exposure:** Never hardcode `PERPLEXITY_API_KEY`; always load from environment variables. Rotate fallback keys regularly for prod deployments.

**2. Model name precision:** Use exact model names like `"sonar-pro"` or `"sonar"` — typos silently fail or route to unexpected models. Check current available models in docs before deployment.

**3. Rate limiting and quota:** Default rate limits apply per API key; batch requests without delay cause 429 errors. Implement exponential backoff and respect `retry-after` headers. Set `max_results` parameter appropriately to avoid oversized responses in MCP tool context.

**4. Search API vs. Chat API confusion:** Search API returns structured ranked results with sources; Chat API returns conversational responses with inline citations. Choose based on whether you need raw results or conversational output for your MCP tool.

---

recommended_tool: OpenAI Python SDK

---
## Researcher update

# perplexity-api

## Overview
Perplexity API provides real-time search and conversational AI capabilities via the Sonar models. Build MCP servers that integrate search functionality by leveraging the official SDK, handling authentication securely, and implementing retry/rate-limit patterns for production reliability.

## Recommended library / tool
**Perplexity Python SDK** — Official SDK with built-in support for search and embeddings APIs, proper error handling, and async patterns.

## Key patterns

### 1. Environment-based API Key Management with Fallback
```python
import os
from perplexity import Perplexity

class PerplexityClient:
    def __init__(self, primary_key=None, fallback_key=None):
        self.primary_key = primary_key or os.getenv("PERPLEXITY_API_KEY")
        self.fallback_key = fallback_key or os.getenv("PERPLEXITY_API_KEY_FALLBACK")
        if not self.primary_key:
            raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")
        self.current_client = Perplexity(api_key=self.primary_key)
```

### 2. Retry Logic with Exponential Backoff
```python
import asyncio
from typing import Callable, Any, TypeVar

T = TypeVar('T')

async def resilient_search(client, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await client.search.create(query=query, max_results=5)
        except Exception as e:
            if "rate" in str(e).lower() and attempt < max_retries - 1:
                delay = 2 ** attempt
                await asyncio.sleep(delay)
            else:
                raise
```

### 3. Batch Search with Rate Limiting
```python
async def batch_search(client, queries, batch_size=3, delay_ms=1000):
    results = []
    for i in range(0, len(queries), batch_size):
        batch = queries[i : i + batch_size]
        tasks = [client.search.create(query=q, max_results=5) for q in batch]
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)
        await asyncio.sleep(delay_ms / 1000)
    return results
```

### 4. Logging Wrapper for Observability
```python
import time
from typing import Optional, Dict, Any

class LoggedPerplexityClient:
    def __init__(self, client):
        self.client = client
    
    def search(self, query: str, **kwargs):
        start = time.time()
        self._log_request("search", query=query, **kwargs)
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
        print(f"[REQUEST] {method}: {kwargs}")
    
    def _log_response(self, method: str, duration: float, success: bool):
        status = "OK" if success else "FAILED"
        print(f"[RESPONSE] {method}: {status} ({duration:.2f}s)")
```

### 5. MCP Server Integration Pattern
```python
from mcp.server import Server

app = Server("perplexity-search")
client = PerplexityClient()

@app.call_tool()
async def search(query: str, max_results: int = 5):
    """Execute a Perplexity search query."""
    try:
        result = await client.search.create(
            query=query,
            max_results=max_results
        )
        return {
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in result.results
            ]
        }
    except Exception as e:
        return {"error": str(e)}
```

## Gotchas

1. **Missing Environment Variables in Production** — Always validate `PERPLEXITY_API_KEY` is set before creating the client. Failing to do so causes runtime crashes during MCP server startup. Use `os.getenv()` with fallbacks and explicit error messages.

2. **Rate Limiting Without Backoff** — The API enforces rate limits; consecutive requests without delays will fail. Implement exponential backoff (2^attempt seconds) and batch requests with `delay_ms` between batches to avoid HTTP 429 errors.

3. **Unhandled Search Result Parsing** — Response objects have nested `results` lists with `title`, `url`, and `snippet` attributes. Iterating directly on the response object without accessing `.results` will fail. Always validate response structure before serializing to JSON for MCP return values.

recommended_tool: perplexity-python-sdk