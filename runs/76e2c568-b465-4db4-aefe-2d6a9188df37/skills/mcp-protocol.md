# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open standard for integrating LLM applications with external data sources and tools, similar to LSP for language servers. Building an MCP server for Perplexity search involves implementing tools/resources that expose search capabilities over stdio or HTTP transport, then deploying to Fly.io as a containerized service.

## Recommended library / tool
**FastMCP** — Python decorator-based MCP server framework that simplifies tool and resource definition with minimal boilerplate, supports both stdio and streamable-http transports.

## Key patterns

**1. Server initialization with FastMCP**
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def search_perplexity(query: str) -> str:
    """Search using Perplexity API"""
    # Call Perplexity API here
    return results
```

**2. HTTP transport for Fly.io deployment**
```python
# Instead of stdio (default), use streamable-http
mcp.run(
    transport="streamable-http",
    host="0.0.0.0",
    port=8000
)
```

**3. Dockerfile for Fly.io**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "server.py"]
```

**4. Fly.io configuration (fly.toml)**
```toml
app = "perplexity-mcp-server"
primary_region = "sjc"

[build]
  image = "perplexity-mcp:latest"

[[services]]
  protocol = "tcp"
  internal_port = 8000
  processes = ["app"]
  [services.ports]
    port = 8000
```

**5. Context and resource safety pattern**
```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def search(query: str, context: Context) -> str:
    # Validate user consent via context
    # Avoid transmitting sensitive user data
    results = await perplexity_api.search(query)
    return results
```

## Gotchas

**1. Missing environment variables at deployment** — Perplexity API key must be set in Fly.io secrets; use `flyctl secrets set PERPLEXITY_API_KEY=<key>` before deploy, not hardcoded in code.

**2. Default stdio transport won't work over HTTP** — FastMCP defaults to stdio mode; explicitly set `transport="streamable-http"` and bind to `0.0.0.0` or Fly.io will reject the service.

**3. Port binding mismatch** — Ensure `internal_port` in fly.toml matches the port your FastMCP server listens on (default 8000); mismatches cause health check failures.

recommended_tool: FastMCP