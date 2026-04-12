# fly-workers

## Overview
Building an MCP server for Perplexity search and deploying to Fly.io involves creating a Model Context Protocol (MCP) server that integrates with Perplexity's API, then containerizing and deploying it on Fly.io's global infrastructure. This skill combines Python serverless patterns with Fly.io's deployment model for low-latency, distributed search capabilities.

## Recommended library / tool
**pywrangler** — Cloudflare's CLI for Python Workers development; alternatively use **FastAPI with Fly.io Docker deployment** for more direct control over the MCP server lifecycle.

## Key patterns

- **MCP Server Entry Point**: Create a FastAPI app that implements the MCP protocol with a `/mcp/search` endpoint for Perplexity queries.
  ```python
  from fastapi import FastAPI
  from httpx import AsyncClient
  
  app = FastAPI()
  
  @app.post("/mcp/search")
  async def search(query: str):
      async with AsyncClient() as client:
          response = await client.post(
              "https://api.perplexity.ai/chat/completions",
              json={"model": "pplx-7b-online", "messages": [{"role": "user", "content": query}]},
              headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"}
          )
      return response.json()
  ```

- **Fly.io Dockerfile**: Use a minimal Python base image with proper dependency pinning to keep cold-start times low.
  ```dockerfile
  FROM python:3.12-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
  ```

- **fly.toml Configuration**: Set appropriate resource limits and health checks for MCP server reliability.
  ```toml
  app = "mcp-perplexity"
  [env]
    PERPLEXITY_API_KEY = "your-key-here"
  
  [http_service]
    internal_port = 8080
    force_https = true
    auto_stop_machines = true
  
  [[services]]
    ports = [{port = 80, handlers = ["http"]}]
    [services.concurrency]
      type = "requests"
      hard_limit = 100
  ```

- **Bindings & Environment**: Use Fly.io's secrets management instead of hardcoding credentials; leverage async patterns for concurrent Perplexity requests to avoid bottlenecks.
  ```bash
  flyctl secrets set PERPLEXITY_API_KEY=sk-xxxx
  ```

- **Health Checks**: Implement a `/health` endpoint that validates both the MCP server and Perplexity connectivity.
  ```python
  @app.get("/health")
  async def health_check():
      # Quick validation that Perplexity endpoint is reachable
      return {"status": "healthy", "service": "mcp-perplexity"}
  ```

## Gotchas

- **Rate Limiting & API Costs**: Perplexity's API has rate limits per key; implement caching or queue-based batching to avoid excessive calls. Fly.io's auto-scaling can trigger high bills if not paired with circuit breakers.

- **Cold Starts with Large Dependencies**: MCP servers often require heavy libraries (httpx, pydantic); use lightweight base images and consider pre-compiling dependencies to reduce startup latency across regions.

- **Async/Await Context**: Cloudflare Workers use different async patterns than standard Python; if migrating to Workers later, avoid blocking I/O and use Worker bindings instead of direct HTTP calls. For Fly.io deployment, stick with FastAPI/Uvicorn async patterns.

---

recommended_tool: FastAPI + Fly.io Docker deployment (with pywrangler as secondary option for Cloudflare Workers portability)