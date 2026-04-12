# perplexity-api

## Overview
The Perplexity API provides conversational AI with real-time web search capabilities, accessible via an OpenAI-compatible interface. It offers multiple Sonar models optimized for different latency/quality tradeoffs and includes dedicated Search and Embeddings APIs. Ideal for building MCP servers that need current, cited information with production-grade rate limiting and failover patterns.

## Recommended library / tool
**OpenAI Python SDK** — Perplexity uses OpenAI-compatible endpoints, so the official OpenAI client works directly with `base_url="https://api.perplexity.ai"`.

## Key patterns

- **Basic chat completion with Sonar models:**
  ```python
  from openai import OpenAI
  
  client = OpenAI(
      api_key="YOUR_PERPLEXITY_API_KEY",
      base_url="https://api.perplexity.ai"
  )
  
  response = client.chat.completions.create(
      model="sonar-pro",
      messages=[
          {"role": "system", "content": "You are a helpful assistant."},
          {"role": "user", "content": "What is the capital of France?"}
      ]
  )
  print(response.choices[0].message.content)
  ```

- **Environment-based API key management with fallback:**
  ```python
  import os
  
  primary_key = os.getenv("PERPLEXITY_API_KEY")
  fallback_key = os.getenv("PERPLEXITY_API_KEY_FALLBACK")
  
  if not primary_key:
      raise ValueError("Error: PERPLEXITY_API_KEY environment variable is required")
  
  client = OpenAI(api_key=primary_key, base_url="https://api.perplexity.ai")
  ```

- **Retry logic with exponential backoff:**
  ```python
  import time
  
  def search_with_retry(client, query, max_retries=3):
      for attempt in range(max_retries):
          try:
              return client.chat.completions.create(
                  model="sonar",
                  messages=[{"role": "user", "content": query}]
              )
          except Exception as e:
              if attempt == max_retries - 1:
                  raise
              delay = 2 ** attempt
              time.sleep(delay)
  ```

- **Batch/async search with rate limiting:**
  ```python
  import asyncio
  
  async def batch_search(client, queries, batch_size=3, delay_ms=1000):
      results = []
      for i in range(0, len(queries), batch_size):
          batch = queries[i:i+batch_size]
          batch_results = await asyncio.gather(*[
              asyncio.to_thread(lambda q=q: client.chat.completions.create(
                  model="sonar", messages=[{"role": "user", "content": q}]
              ))
              for q in batch
          ])
          results.extend(batch_results)
          if i + batch_size < len(queries):
              await asyncio.sleep(delay_ms / 1000)
      return results
  ```

- **Search API for raw results with citations:**
  ```python
  # Use client.search.create() for dedicated search endpoint
  # Returns ranked results with real-time web data and source citations
  search_result = client.search.create(query="tech news", max_results=5)
  for result in search_result.results:
      print(f"{result.title}: {result.url}")
  ```

## Gotchas

- **Model availability:** `sonar-pro` and `sonar` are the primary models; older GPT models may not be available. Always verify your chosen model in current docs before deploying.

- **Rate limits and cost:** Sonar models have different pricing tiers. Implement query caching and batch processing to avoid excessive API calls. Use `max_results` parameter sparingly (e.g., prefer 5 over 50 unless necessary).

- **Fly.io secrets:** Store `PERPLEXITY_API_KEY` as a Fly secret using `fly secrets set PERPLEXITY_API_KEY=<key>`, not in `fly.toml`. MCP servers deployed to Fly must access secrets via environment variables; hardcoding keys will cause security issues and deployment failures.

---

recommended_tool: OpenAI Python SDK