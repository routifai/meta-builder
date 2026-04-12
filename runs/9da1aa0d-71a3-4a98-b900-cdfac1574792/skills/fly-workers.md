# fly-workers

## Overview
Building an MCP (Model Context Protocol) server for Perplexity search and deploying to Fly.io combines serverless search integration with scalable edge deployment. This skill covers creating a Python-based MCP server that wraps Perplexity's API and packaging it for Fly.io's containerized runtime environment.

## Recommended library / tool
**FastAPI** — lightweight async Python framework ideal for MCP servers with built-in OpenAPI support and excellent Fly.io deployment patterns.

## Key patterns

**1. MCP Server Structure with FastAPI**
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

app = FastAPI()

@app.post("/search")
async def perplexity_search(query: str):
    """MCP endpoint for Perplexity search"""
    result = await call_perplexity_api(query)
    return {"query": query, "result": result}
```

**2. Perplexity API Integration**
```python
import httpx
from os import getenv

PERPLEXITY_API_KEY = getenv("PERPLEXITY_API_KEY")

async def call_perplexity_api(query: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
            json={
                "model": "pplx-7b-online",
                "messages": [{"role": "user", "content": query}]
            }
        )
        return response.json()["choices"][0]["message"]["content"]
```

**3. Fly.io Dockerfile Setup**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**4. fly.toml Configuration**
```toml
app = "perplexity-mcp-server"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[[services]]
  protocol = "tcp"
  internal_port = 8080
  processes = ["app"]
  
  [[services.ports]]
    port = 80
    handlers = ["http"]
  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

[env]
  PERPLEXITY_API_KEY = ""  # Set via `fly secrets set`
```

**5. Environment Secrets on Fly.io**
```bash
fly secrets set PERPLEXITY_API_KEY="your-api-key-here"
fly deploy
```

## Gotchas

**1. Port Binding Mismatch** — Fly.io expects the app to listen on port 8080 by default. Ensure FastAPI binds to `0.0.0.0:8080`, not `localhost:8080`, or the health checks will fail.

**2. Missing PERPLEXITY_API_KEY at Runtime** — Secrets set via `fly secrets` aren't automatically available during build. They're injected at runtime—ensure your code reads from `os.getenv()` without raising exceptions if the key is missing during initialization.

**3. Async Context Cleanup** — MCP servers with persistent connections need proper lifespan management. Use FastAPI's `@asynccontextmanager` to handle httpx client lifecycle, preventing resource leaks on repeated deployments.

---

recommended_tool: FastAPI