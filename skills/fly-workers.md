# Fly.io Workers — Always-On Persistent Agents

## Source
https://fly.io/docs/reference/configuration/

## Installation

```bash
# Install flyctl
brew install flyctl
# or
curl -L https://fly.io/install.sh | sh

flyctl auth login
```

---

## `fly.toml` structure for this project

The project runs two kinds of processes:
- **Ephemeral agents** (coder, tester, deployer): run in GitHub Actions, not Fly.io
- **Persistent agents** (log_watcher, anomaly_classifier, fix_agent, validator, skills_updater): always-on Fly.io workers

```toml
# fly.toml
app = "meta-builder-monitor"
primary_region = "ord"    # Chicago — change to region closest to your infra

[build]
  dockerfile = "docker/Dockerfile.agent"

[env]
  PORT = "8080"
  LOG_LEVEL = "info"

# Define multiple process groups — each runs on its own Machine
[processes]
  log_watcher        = "python -m agent.monitor.log_watcher"
  anomaly_classifier = "python -m agent.monitor.anomaly_classifier"
  fix_agent          = "python -m agent.monitor.fix_agent"
  validator          = "python -m agent.monitor.validator"
  skills_updater     = "python -m agent.monitor.skills_updater"
  health             = "python -m agent.monitor.health_server"   # HTTP health endpoint

# Auto-restart policy for worker processes
[[restart]]
  policy  = "always"    # restart regardless of exit code
  retries = 10
  processes = ["log_watcher", "anomaly_classifier", "fix_agent", "validator", "skills_updater"]

# Health check — Fly.io uses this to decide if the Machine is healthy
[[http_service]]
  internal_port = 8080
  processes     = ["health"]
  [[http_service.checks]]
    grace_period = "15s"
    interval     = "30s"
    method       = "GET"
    path         = "/health"
    timeout      = "5s"

# Persistent volume for skills/ directory (agents read/write across restarts)
[[mounts]]
  source      = "skills_volume"
  destination = "/app/skills"
  processes   = ["log_watcher", "anomaly_classifier", "fix_agent", "validator", "skills_updater"]
  initial_size = "5gb"
  snapshot_retention = 7   # keep 7 days of daily snapshots
```

---

## Process groups

Each entry in `[processes]` runs as a separate Fly Machine. Machines in the same process group share the same Docker image but run different commands.

```toml
[processes]
  worker = "python -m agent.monitor.log_watcher"
```

Assign volumes and services to specific groups using the `processes` field.

---

## Auto-restart policies

| Policy | Behavior |
|--------|----------|
| `always` | Restart on any exit (including clean exit 0) — use for daemons |
| `on-failure` | Restart only on non-zero exit — use for jobs that should stop when done |
| `never` | No automatic restart |

```toml
[[restart]]
  policy  = "always"
  retries = 10                         # max restart attempts before giving up
  processes = ["log_watcher"]
```

---

## Persistent volumes

Volumes survive Machine restarts and replacements.

```toml
[[mounts]]
  source      = "skills_volume"        # volume name (create with flyctl)
  destination = "/app/skills"          # mount path inside container
  processes   = ["fix_agent"]
  initial_size = "5gb"
```

Create the volume before first deploy:

```bash
flyctl volumes create skills_volume --size 5 --region ord --app meta-builder-monitor
```

**Gotcha:** volumes are single-region and single-machine by default. Two machines in the same process group cannot share a volume. For shared state across machines, use Redis.

---

## Health check endpoint (Python)

```python
# agent/monitor/health_server.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass   # suppress access log noise

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()
```

---

## Secrets injection

```bash
# Set secrets (stored encrypted, injected as env vars at runtime)
flyctl secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  REDIS_URL="redis://..." \
  LANGSMITH_API_KEY="ls-..." \
  --app meta-builder-monitor
```

In Python:
```python
import os
api_key = os.environ["ANTHROPIC_API_KEY"]
```

---

## Deploy commands

```bash
# First deploy
flyctl launch --name meta-builder-monitor --region ord --no-deploy
flyctl deploy --app meta-builder-monitor

# Re-deploy after code change
flyctl deploy --app meta-builder-monitor

# Scale a specific process group
flyctl scale count log_watcher=1 fix_agent=1 --app meta-builder-monitor

# View logs
flyctl logs --app meta-builder-monitor
flyctl logs --app meta-builder-monitor -i <machine-id>

# SSH into a running machine
flyctl ssh console --app meta-builder-monitor
```

---

## Dockerfile for agent workers

```dockerfile
# docker/Dockerfile.agent
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY agent/ ./agent/
COPY mcp/ ./mcp/
COPY skills/ ./skills/

# Skills dir will be overlaid by the persistent volume mount at runtime
# The COPY above is the initial seed — volume takes precedence

CMD ["python", "-m", "agent.monitor.log_watcher"]
# Overridden per-process by [processes] in fly.toml
```

---

## Multi-region

```toml
primary_region = "ord"
```

For read replicas of a database in multiple regions:

```bash
flyctl deploy -e PRIMARY_REGION=ord --app meta-builder-monitor
```

Workers in non-primary regions automatically get `FLY_REGION` env var set.

---

## Gotchas

- **Volumes are single-machine.** If you run 2 instances of `fix_agent`, they each need their own volume or share state via Redis.
- **`always` restart policy + bug = infinite restart loop.** Monitor with `flyctl logs`. Add backoff logic in your process (exponential sleep before retrying the main loop on error).
- **`grace_period` on health checks.** Set to at least 15s — Python startup + dependency loading takes several seconds. Too short = healthy process marked unhealthy and killed.
- **Secrets are not environment variables at build time.** They're only available at runtime. Don't reference them in `Dockerfile` `RUN` commands.
- **`initial_size` on volumes is a minimum.** It can grow beyond this. Snapshot retention defaults to 5 days — bump to 7+ for skills/ so knowledge is never lost.
- **Process group machines are isolated.** `log_watcher` and `fix_agent` run on separate machines. They coordinate via Redis pub/sub, not shared memory.


---
## Researcher update

# fly-workers

## Overview
Building an MCP server for Perplexity search and deploying to production on Fly.io requires containerizing a Python application with proper async HTTP handling and Fly.io-specific deployment configuration. This skill covers setting up a FastAPI-based MCP server, integrating the Perplexity API, and deploying via Docker on Fly.io's global infrastructure.

## Recommended library / tool
**FastAPI** — Modern Python web framework with async/await support, automatic OpenAPI docs, and excellent Pydantic validation for MCP protocol compliance.

## Key patterns

### 1. MCP Server Structure with FastAPI
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

app = FastAPI(title="Perplexity MCP Server")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize Perplexity client
    yield
    # Shutdown cleanup

app = FastAPI(lifespan=lifespan)

@app.post("/mcp/search")
async def search(query: str):
    # Call Perplexity API
    pass
```

### 2. Perplexity API Integration
```python
import httpx

async def perplexity_search(query: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
            json={
                "model": "pplx-7b-online",
                "messages": [{"role": "user", "content": query}]
            }
        )
    return response.json()
```

### 3. Fly.io Deployment with fly.toml
```toml
app = "perplexity-mcp-server"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[[services]]
  internal_port = 8000
  protocol = "tcp"
  
  [services.concurrency]
    hard_limit = 25
    soft_limit = 20

[env]
  PERPLEXITY_API_KEY = ""  # Set via `fly secrets set`
```

### 4. Dockerfile for Python on Fly.io
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5. Environment Variables & Secrets Management
```bash
# Deploy secrets without committing to repo
fly secrets set PERPLEXITY_API_KEY=sk-xxxxx

# Verify in app with environment loader
import os
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
if not PERPLEXITY_API_KEY:
    raise ValueError("PERPLEXITY_API_KEY not set")
```

## Gotchas

1. **Missing requirements.txt dependency** — FastAPI and uvicorn must be explicitly listed; Fly.io doesn't auto-detect Python dependencies. Always include `httpx` for async HTTP calls to avoid blocking I/O.

2. **Port binding mismatch** — The container must listen on `0.0.0.0:8000` (not `127.0.0.1`), and `fly.toml` `internal_port` must match the app's exposed port. Mismatch causes "Connection refused" on first deployment.

3. **API rate limits with Perplexity** — No backoff strategy in the integration code above. Add exponential retry logic with `httpx.AsyncClient` or use `tenacity` library to handle 429 responses before your MCP server fails under load.

recommended_tool: FastAPI

---
## Researcher update

# fly-workers

## Overview
Build and deploy an MCP (Model Context Protocol) server for Perplexity search on Fly.io using Python. This involves creating a FastAPI-based MCP server that integrates Perplexity's search API and deploying it as a containerized application on Fly.io's distributed infrastructure.

## Recommended library / tool
**FastAPI + pydantic** — Built-in validation, async support, and automatic OpenAPI docs; pairs seamlessly with MCP server patterns and Fly.io deployment.

## Key patterns

- **MCP Server Setup**: Use the MCP Python SDK to define resources and tools. Wrap with FastAPI for HTTP endpoints.
  ```python
  from mcp.server import Server
  from fastapi import FastAPI
  
  app = FastAPI()
  mcp_server = Server("perplexity-search")
  
  @mcp_server.resource("perplexity://search/{query}")
  async def search(query: str) -> str:
      # Call Perplexity API here
      pass
  ```

- **Perplexity API Integration**: Use `httpx` for async HTTP calls to Perplexity's endpoints. Store API key in Fly.io secrets.
  ```python
  import httpx
  import os
  
  PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
  
  async def perplexity_search(query: str):
      async with httpx.AsyncClient() as client:
          response = await client.post(
              "https://api.perplexity.ai/chat/completions",
              headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
              json={"model": "pplx-7b-online", "messages": [{"role": "user", "content": query}]}
          )
          return response.json()
  ```

- **Dockerfile for Fly.io**: Use Python 3.11+ slim image, include requirements.txt, and expose port 8000.
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```

- **fly.toml Configuration**: Set app name, allocate resources, and mount secrets for production.
  ```toml
  app = "perplexity-mcp-server"
  [env]
  PERPLEXITY_API_KEY = "xxx"
  [build]
  dockerfile = "Dockerfile"
  [deploy]
  release_command = "python migrate.py"
  ```

- **Deployment**: Initialize with `flyctl launch`, set secrets via `flyctl secrets set`, and deploy with `flyctl deploy`.
  ```bash
  flyctl secrets set PERPLEXITY_API_KEY=your_key_here
  flyctl deploy
  ```

## Gotchas

- **Cold Start Latency**: Fly.io boots containers on-demand; MCP servers with heavy imports (like langchain) may timeout on first request. Pre-warm with health checks or use `fly scale count`.
- **API Key Exposure**: Never commit `.env` files or embed keys in Dockerfile. Always use `flyctl secrets set` and reference via `os.getenv()`. Fly.io injects secrets as environment variables at runtime.
- **Async/Sync Mismatch**: MCP tools must be async-compatible. If using blocking Perplexity libraries, wrap with `asyncio.to_thread()` to avoid blocking the event loop on Fly.io's resource-constrained machines.

recommended_tool: FastAPI + pydantic

---
## Researcher update

# fly-workers

## Overview
Fly.io provides a serverless execution environment for Python applications, making it ideal for deploying MCP (Model Context Protocol) servers. To build and deploy an MCP server for Perplexity search on Fly.io, you'll containerize a Python application with FastAPI or similar framework, then use Fly's deployment tooling to manage the production service globally.

## Recommended library / tool
**FastAPI** — lightweight async framework with built-in OpenAPI support, ideal for MCP server endpoints and Perplexity API integration.

## Key patterns

- **MCP Server skeleton with FastAPI**
```python
from fastapi import FastAPI
from mcp.server import Server
from mcp.types import Tool

app = FastAPI()
mcp_server = Server("perplexity-mcp")

@mcp_server.tool()
async def search_perplexity(query: str) -> str:
    # Call Perplexity API and return results
    pass

@app.post("/mcp")
async def handle_mcp_request(request: dict):
    return await mcp_server.process(request)
```

- **Dockerfile for Fly.io deployment**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- **fly.toml configuration for production**
```toml
app = "perplexity-mcp"
primary_region = "sjc"  # San Jose for US latency

[[services]]
  internal_port = 8080
  protocol = "tcp"
  
  [services.http_checks]
    enabled = true
    uri = "/health"
```

- **Environment secrets for Perplexity API key**
```bash
flyctl secrets set PERPLEXITY_API_KEY=your_key_here
```
Access in code via `os.getenv("PERPLEXITY_API_KEY")`

- **Health check endpoint (required for Fly.io)**
```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

## Gotchas

- **Port binding**: Fly.io expects your app to listen on `0.0.0.0` and the port defined in `fly.toml` (default 8080). Binding to `localhost` will cause connection failures in production.

- **Request timeouts**: MCP server requests may exceed Fly.io's default timeout (30s). Explicitly set `services.timeout` in fly.toml or use async operations with streaming responses for long-running Perplexity searches.

- **Cold starts with heavy dependencies**: If using large ML/search libraries, Docker image size matters. Keep requirements.txt minimal—use `python:3.11-slim` not `python:3.11-full`, and consider multi-stage builds to exclude dev dependencies.

recommended_tool: FastAPI

---
## Researcher update

# fly-workers

## Overview
Fly.io is a platform for deploying Python applications globally with low latency. To build an MCP (Model Context Protocol) server for Perplexity search and deploy to production, you'll package a Python service in Docker, define your Fly app configuration, and deploy using the `flyctl` CLI. This skill covers containerizing an MCP server and managing its lifecycle on Fly.io.

## Recommended library / tool
**FastAPI** — Lightweight, async-friendly Python web framework ideal for building MCP servers with built-in request validation and OpenAPI documentation.

## Key patterns

- **Basic Fly.io Docker setup**: Create a `Dockerfile` with Python base image, install dependencies, and expose your MCP server port.
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
  ```

- **fly.toml configuration**: Define your app name, region, port bindings, and resource limits. Fly.io auto-scales based on metrics.
  ```toml
  app = "perplexity-mcp-server"
  primary_region = "iad"
  
  [build]
    dockerfile = "Dockerfile"
  
  [env]
    PERPLEXITY_API_KEY = ""
  
  [[services]]
    protocol = "tcp"
    internal_port = 8080
    processes = ["app"]
    
    [[services.ports]]
      port = 80
      handlers = ["http"]
  ```

- **Environment secrets management**: Use `flyctl secrets set` to store sensitive API keys (e.g., Perplexity API credentials) securely without embedding in Docker image.
  ```bash
  flyctl secrets set PERPLEXITY_API_KEY="your-key-here"
  ```

- **MCP server with Perplexity integration**: Use httpx or requests to call Perplexity's API; structure responses per MCP protocol (tools, resources, prompts).
  ```python
  from fastapi import FastAPI
  import httpx
  import os
  
  app = FastAPI()
  PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY")
  
  @app.post("/mcp/tools/search")
  async def search(query: str):
      async with httpx.AsyncClient() as client:
          response = await client.post(
              "https://api.perplexity.ai/chat/completions",
              json={"model": "pplx-70b-online", "messages": [{"role": "user", "content": query}]},
              headers={"Authorization": f"Bearer {PERPLEXITY_KEY}"}
          )
      return response.json()
  ```

- **Deployment workflow**: Build, push, and deploy with a single command. Fly.io handles image building and registry management.
  ```bash
  flyctl deploy
  ```

## Gotchas

- **Port binding mismatch**: Ensure `internal_port` in `fly.toml` matches the port your Python app listens on (typically 8080). Docker CMD must expose the same port with `--port` flag.

- **Large dependency bloat**: Python Docker images can grow quickly. Use `slim` base images, pin specific versions in `requirements.txt`, and leverage `.dockerignore` to exclude cache and test files; this reduces cold-start latency on Fly.io's global edge.

- **API key exposure in logs**: Never log the `PERPLEXITY_API_KEY` or include it in error messages. Use environment variables (via `flyctl secrets`) and validate responses server-side to avoid leaking credentials to client-side error handling.

recommended_tool: FastAPI

---
## Researcher update

# fly-workers

## Overview
Deploy a Model Context Protocol (MCP) server for Perplexity search to Fly.io using Python and Docker. This skill covers containerizing a Python MCP server, configuring Fly.io deployments, and managing production API integrations with Perplexity's search capabilities.

## Recommended library / tool
**FastAPI** — lightweight, async-first Python web framework ideal for building MCP servers with built-in validation and excellent Fly.io compatibility.

## Key patterns

### 1. MCP Server Structure with FastAPI
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

app = FastAPI()

@app.post("/mcp/search")
async def perplexity_search(query: str):
    """MCP endpoint for Perplexity search"""
    result = await call_perplexity_api(query)
    return {"query": query, "results": result}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
```

### 2. Dockerfile for Fly.io Python Apps
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 3. Fly.io Configuration (fly.toml)
```toml
app = "perplexity-mcp-server"
primary_region = "ord"

[build]
  dockerfile = "Dockerfile"

[[services]]
  protocol = "tcp"
  internal_port = 8080
  processes = ["app"]
  
  [services.http_checks]
    enabled = true
    grace_period = "5s"
    interval = 10000
    timeout = 2000
    path = "/health"
```

### 4. Environment Management for API Keys
```bash
# Deploy secrets to Fly.io
fly secrets set PERPLEXITY_API_KEY="your-key-here"

# Access in Python
import os
api_key = os.getenv("PERPLEXITY_API_KEY")
```

### 5. Health Check & Graceful Shutdown
```python
@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.on_event("shutdown")
async def shutdown():
    # Clean up connections, pending requests
    pass
```

## Gotchas

1. **Port binding must be 0.0.0.0** — Fly.io requires apps to listen on `0.0.0.0:8080` by default. Using `127.0.0.1` will cause connection timeouts.

2. **Secrets not available at build time** — Environment variables set via `fly secrets set` are only available at runtime, not during Docker build. Use build args for compile-time config.

3. **Cold starts with large dependencies** — Perplexity API client libraries and async HTTP clients (httpx, aiohttp) add startup overhead. Use lightweight imports and consider lazy-loading heavy modules to reduce boot time under 30 seconds (Fly timeout limit).

---

recommended_tool: FastAPI

---
## Researcher update

# fly-workers

## Overview
Building an MCP (Model Context Protocol) server for Perplexity search on Fly.io requires containerizing a Python application with proper API integration and deployment configuration. Fly.io provides excellent global distribution and minimal DevOps overhead for production Python services.

## Recommended library / tool
**FastAPI** — Modern, async-capable Python framework ideal for MCP servers with built-in OpenAPI docs and excellent Pydantic integration for type safety.

## Key patterns

### 1. MCP Server Structure with FastAPI
```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class SearchQuery(BaseModel):
    query: str
    max_results: int = 5

@app.post("/search")
async def perplexity_search(req: SearchQuery):
    # Integrate Perplexity API call here
    results = await query_perplexity(req.query)
    return {"results": results}
```

### 2. Fly.io Dockerfile Best Practice
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 3. fly.toml Configuration for Production
```toml
app = "perplexity-mcp"
primary_region = "iad"

[build]
  image = "perplexity-mcp:latest"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true

[[vm]]
  size = "shared-cpu-1x"
  memory_mb = 256
```

### 4. Perplexity API Integration Pattern
```python
import httpx
from typing import List

async def query_perplexity(query: str) -> List[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
            json={
                "model": "pplx-7b-online",
                "messages": [{"role": "user", "content": query}]
            }
        )
        return response.json()
```

### 5. Environment Variables in Fly.io
```bash
# Set secrets via CLI
flyctl secrets set PERPLEXITY_API_KEY=<your-key>
flyctl secrets set LOG_LEVEL=info

# Access in Python
import os
api_key = os.getenv("PERPLEXITY_API_KEY")
```

## Gotchas

1. **Cold starts matter** — Use `auto_start_machines = true` in fly.toml to prevent request timeouts; shared-cpu VMs auto-stop after inactivity. Consider dedicated resources for production MCP servers handling frequent requests.

2. **API Key exposure in logs** — Always use `flyctl secrets` for sensitive data, never hardcode or commit `.env` files. Perplexity API keys in stdout/stderr will leak to logs accessible via `flyctl logs`.

3. **Async/await mismatches** — FastAPI expects async handlers for MCP endpoints. Blocking Perplexity API calls (via `requests` instead of `httpx`) will freeze the event loop; use `httpx.AsyncClient` or wrap blocking calls in `asyncio.to_thread()`.

4. **Region latency** — Perplexity API calls from distant regions add 100-500ms latency. Pin your Fly region closest to Perplexity's endpoints or use a multi-region setup with `processes` for read replicas.

recommended_tool: FastAPI

---
## Researcher update

# fly-workers

## Overview
Building an MCP server for Perplexity search requires deploying a Python-based service that bridges MCP protocol with Perplexity's search API. Fly.io provides a globally-distributed platform ideal for low-latency MCP servers, while Cloudflare Workers offers lightweight serverless execution. For this use case, a Python application deployed on Fly.io is recommended over Workers due to MCP server complexity and stateful connection requirements.

## Recommended library / tool
**FastMCP** — Python framework for building Model Context Protocol servers with built-in HTTP/SSE transport and async request handling.

## Key patterns

- **Initialize MCP server with Perplexity client**
  ```python
  from mcp.server import Server
  from mcp.server.stdio import stdio_server
  import httpx
  
  server = Server("perplexity-mcp")
  perplexity_client = httpx.AsyncClient(
      base_url="https://api.perplexity.ai",
      headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"}
  )
  ```

- **Expose search as MCP tool**
  ```python
  @server.call_tool()
  async def search(query: str, search_recency: str = "month"):
      response = await perplexity_client.post(
          "/chat/completions",
          json={"model": "pplx-7b-online", "messages": [{"role": "user", "content": query}]}
      )
      return [{"type": "text", "text": response.json()["choices"][0]["message"]["content"]}]
  ```

- **Deploy to Fly.io with `fly.toml` configuration**
  ```toml
  [env]
  PERPLEXITY_API_KEY = ""
  
  [[services]]
  internal_port = 8000
  protocol = "tcp"
  ```

- **Use Fly.io secrets for API credentials**
  ```bash
  fly secrets set PERPLEXITY_API_KEY=sk-xxx
  fly deploy
  ```

- **Enable observability before production**
  Configure logging to Sentry or Datadog; use `fly logs` for real-time monitoring. Avoid global mutable state in async handlers—use dependency injection or context locals.

## Gotchas

- **MCP server expects stdio or HTTP transport** — Workers' request/response model doesn't natively support MCP's streaming protocol. Fly.io's persistent connections are required; Workers will timeout long-running streams.

- **Perplexity API has strict rate limits** — Implement exponential backoff and cache results. Use `httpx.AsyncClient` with connection pooling; don't create new clients per request on Fly.io or cost multiplies.

- **Cold starts and state isolation** — Fly.io machines remain warm, but avoid storing search results in Python globals. Use Fly.io Postgres or Redis for multi-instance coordination if scaling horizontally.

---

recommended_tool: FastMCP