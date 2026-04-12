# MCP Protocol — Building Python Servers

## Sources
- https://modelcontextprotocol.io/docs/concepts/architecture
- https://github.com/modelcontextprotocol/python-sdk

## Installation

```bash
pip install "mcp[cli]"
# or with uv (recommended)
uv add "mcp[cli]"
```

---

## Architecture

```
MCP Host (AI app, e.g. Claude Code)
  └── MCP Client 1  ──────────── MCP Server A (local, stdio)
  └── MCP Client 2  ──────────── MCP Server B (local, stdio)
  └── MCP Client 3  ──────────── MCP Server C (remote, HTTP)
```

- **Host**: the AI application that manages connections
- **Client**: one per server, maintains the connection
- **Server**: program that exposes tools/resources/prompts

Local servers use **stdio** (single client, same machine).  
Remote servers use **Streamable HTTP** (many clients, network).

---

## Protocol basics

JSON-RPC 2.0 over the chosen transport.

### Lifecycle

```json
// 1. Client → Server: initialize
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"elicitation":{}},
  "clientInfo":{"name":"my-agent","version":"1.0.0"}
}}

// 2. Server → Client: capabilities
{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"tools":{"listChanged":true}},
  "serverInfo":{"name":"my-server","version":"1.0.0"}
}}

// 3. Client → Server: ready notification (no response expected)
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

### Tool discovery

```json
// Request
{"jsonrpc":"2.0","id":2,"method":"tools/list"}

// Response
{"jsonrpc":"2.0","id":2,"result":{"tools":[
  {
    "name": "search_web",
    "title": "Web Search",
    "description": "Search the web for information",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type":"string","description":"Search query"},
        "max_results": {"type":"integer","default":5}
      },
      "required": ["query"]
    }
  }
]}}
```

### Tool execution

```json
// Request
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
  "name":"search_web",
  "arguments":{"query":"MCP protocol","max_results":3}
}}

// Response
{"jsonrpc":"2.0","id":3,"result":{"content":[
  {"type":"text","text":"Results: ..."}
]}}
```

### Dynamic update notification (if `listChanged: true`)

```json
{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}
// Client responds by calling tools/list again
```

---

## Building a server with FastMCP (recommended)

FastMCP handles protocol boilerplate via decorators.

### Minimal server with tools

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web and return results as text."""
    # implementation
    return f"Results for: {query}"

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the filesystem."""
    with open(path) as f:
        return f.read()

if __name__ == "__main__":
    mcp.run(transport="stdio")    # for local/desktop use
    # mcp.run(transport="streamable-http")   # for remote/browser use
```

### Tool with progress reporting (Context injection)

```python
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession

mcp = FastMCP("my-server")

@mcp.tool()
async def long_task(name: str, ctx: Context[ServerSession, None]) -> str:
    """Run a long task with progress updates."""
    await ctx.info(f"Starting {name}")
    for i in range(10):
        await ctx.report_progress(progress=(i+1)/10, total=1.0, message=f"Step {i+1}/10")
    return "Done"
```

### Resource (read-only data, URI pattern)

```python
@mcp.resource("file://skills/{name}")
def get_skill(name: str) -> str:
    """Read a skill document."""
    with open(f"skills/{name}.md") as f:
        return f.read()
```

### Lifespan (startup/shutdown with shared context)

```python
from contextlib import asynccontextmanager
from dataclasses import dataclass

@dataclass
class AppCtx:
    redis_client: any

@asynccontextmanager
async def lifespan(server: FastMCP):
    import redis.asyncio as redis
    r = redis.from_url("redis://localhost")
    try:
        yield AppCtx(redis_client=r)
    finally:
        await r.close()

mcp = FastMCP("my-server", lifespan=lifespan)

@mcp.tool()
async def get_state(key: str, ctx: Context) -> str:
    """Read from Redis."""
    r = ctx.request_context.lifespan_context.redis_client
    return await r.get(key)
```

### Structured output

Tools with Pydantic model return types produce validated structured output automatically:

```python
from pydantic import BaseModel

class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str

@mcp.tool()
def search(query: str) -> list[SearchResult]:
    """Search and return structured results."""
    return [SearchResult(url="...", title="...", snippet="...")]
```

---

## Transports

| Transport | Use case | Command |
|-----------|----------|---------|
| `stdio` | Local, same-machine (Claude Desktop, Claude Code) | `mcp.run(transport="stdio")` |
| `streamable-http` | Remote, multi-client (HTTP POST + optional SSE) | `mcp.run(transport="streamable-http")` |

**For this project:** all three MCP servers (github, web_search, filesystem) use `stdio` — they run as local child processes spawned by the Deep Agents MCP adapter.

---

## Registering with Claude Code (for testing)

```bash
# Add local stdio server
claude mcp add my-server python mcp/github_server.py

# Add local HTTP server
claude mcp add --transport http my-server http://localhost:8000/mcp
```

---

## MCP Primitives summary

| Primitive | Direction | Method | Purpose |
|-----------|-----------|--------|---------|
| Tools | Server → Client | `tools/list`, `tools/call` | Executable functions |
| Resources | Server → Client | `resources/list`, `resources/read` | Read-only data |
| Prompts | Server → Client | `prompts/list`, `prompts/get` | Reusable templates |
| Sampling | Client → Server | `sampling/complete` | Server asks LLM to generate |
| Elicitation | Client → Server | `elicitation/request` | Server asks user for input |

---

## Gotchas

- **`name` in tool schema must be unique per server.** Clients use it as the primary key for routing.
- **`inputSchema` is JSON Schema** — not Python type hints. FastMCP generates it from type annotations automatically, but for edge cases define it explicitly.
- **`stdio` transport = single client.** One process per client. Don't share a stdio server across multiple concurrent clients.
- **Notifications require `listChanged: true` in capabilities.** Declare it during `initialize` or clients won't expect them.
- **Tool errors:** return `CallToolResult(isError=True, content=[...])` rather than raising — raising crashes the connection.
- **FastMCP vs low-level:** use FastMCP for all three servers in this project. Low-level `Server` class only if you need custom protocol handler logic.


---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context and tools to Large Language Models. It enables seamless integration between LLM applications and external data sources, similar to how Language Server Protocol standardizes language support. Building an MCP server for Perplexity search involves creating tools that expose search capabilities, securing them with OAuth 2.1, and deploying via HTTP transport.

## Recommended library / tool
**FastMCP** — Lightweight Python framework that simplifies MCP server creation with decorators and automatic schema generation, supporting both stdio and streamable-http transports.

## Key patterns

- **Initialize FastMCP server with transport selection:**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  mcp = FastMCP(name="Perplexity Search Server", host="0.0.0.0", port=8000)
  ```

- **Define search tool with input schema:**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  @mcp.tool()
  async def search_perplexity(query: str, num_results: int = 10) -> dict:
      """Search using Perplexity API"""
      # Call Perplexity API endpoint
      response = await perplexity_client.search(query, limit=num_results)
      return {"results": response, "query": query}
  ```

- **Run as streamable-http for production deployment:**
  ```python
  mcp.run(transport="streamable-http")  # Replaces stdio for cloud/containerized environments
  ```

- **Client consumption pattern with session management:**
  ```python
  from mcp.client.streamable_http import streamablehttp_client
  
  async with streamablehttp_client("http://localhost:8000") as (read, write, get_session_id):
      session = ServerSession(read, write)
      result = await session.call_tool("search_perplexity", 
                                       arguments={"query": "AI trends 2025"})
  ```

- **Implement OAuth 2.1 for API credentials:**
  ```python
  import os
  from aiohttp import ClientSession
  
  class PerplexityAuth:
      def __init__(self, api_key: str):
          self.api_key = api_key  # Load from environment for production
          self.headers = {"Authorization": f"Bearer {self.api_key}"}
  
  auth = PerplexityAuth(os.getenv("PERPLEXITY_API_KEY"))
  ```

## Gotchas

- **Stdio vs. HTTP transport confusion:** Stdio transport works locally but fails in containerized/cloud environments. Always use `transport="streamable-http"` for production deployments. Verify with explicit `host` and `port` parameters.

- **Schema generation without validation:** FastMCP auto-generates schemas from function signatures, but complex nested types may not serialize correctly. Test with `mcp_tool_to_responses_schema()` and set `strict=True` to catch issues before deployment.

- **Missing explicit user consent on data access:** The MCP specification mandates explicit user consent before transmitting search results. Log all tool invocations and don't cache/forward results without consent verification, especially with sensitive search queries.

---

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context and tools to Large Language Models. To build an MCP server for Perplexity search, you'll implement tools that expose search capabilities as context resources, then deploy via stdio or HTTP transport. This skill focuses on server implementation patterns and production deployment considerations.

## Recommended library / tool
**FastMCP** — Python framework that simplifies MCP server development with decorators and automatic schema generation, eliminating boilerplate for tool/resource definitions.

## Key patterns

- **Server initialization with FastMCP**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  mcp = FastMCP(name="Perplexity Search Server")
  
  @mcp.tool()
  def search(query: str, num_results: int = 5) -> str:
      """Search using Perplexity API"""
      # Call Perplexity search endpoint
      return results
  
  mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
  ```

- **Resource definition for search results**
  ```python
  @mcp.resource("uri://search/{query}")
  def get_search_resource(query: str) -> str:
      """Expose search results as a resource"""
      return perform_search(query)
  ```

- **HTTP transport for production deployment**
  Use `transport="streamable-http"` with explicit host/port instead of stdio. This enables containerization and cloud deployment (Docker, Kubernetes, AWS Lambda).

- **Client integration pattern**
  ```python
  from mcp.client.streamable_http import streamablehttp_client
  
  async with streamablehttp_client("http://localhost:8000") as (read, write, get_session_id):
      session = await ServerSession.create(read, write)
      result = await session.call_tool("search", {"query": "AI trends"})
  ```

- **Explicit consent & security for production**
  Always obtain user consent before exposing Perplexity API calls. Validate API keys via environment variables (never hardcode). Implement rate limiting and audit logging for tool invocations.

## Gotchas

- **Stdio vs. HTTP confusion**: Stdio transport (`mcp.run()` without transport arg) is for local development only. Production requires `transport="streamable-http"` with explicit host/port binding.

- **Missing input schema validation**: FastMCP auto-generates schemas from function signatures, but complex nested parameters need explicit `InputSchema` objects. Omitting this breaks LLM tool calling.

- **Unhandled Perplexity API errors**: Search calls can timeout or hit rate limits. Wrap API calls in try/except and return structured error messages (not stack traces) to maintain protocol compliance.

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context and tools to Large Language Models. Building an MCP server for Perplexity search involves implementing either stdio or streamable-http transports, exposing search capabilities as tools, and deploying with proper authentication and error handling. MCP enables seamless integration between LLM applications and external data sources while maintaining explicit user consent and data protection.

## Recommended library / tool
**FastMCP** (Python) — Lightweight, decorator-based framework that eliminates boilerplate and simplifies server/tool definition with built-in transport support.

## Key patterns

- **Server initialization with FastMCP:**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  mcp = FastMCP(name="perplexity-search-server")
  
  @mcp.tool()
  def search(query: str, num_results: int = 5) -> str:
      """Search Perplexity for query results"""
      # Call Perplexity API here
      return results
  
  mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
  ```

- **Transport selection:** Use `stdio` for local development/testing, switch to `streamable-http` for production with explicit `host` and `port` parameters.

- **Tool schema enforcement:** MCP automatically generates schemas from function signatures; use type hints strictly and docstrings for descriptions to ensure proper LLM integration.

- **Client consumption pattern:**
  ```python
  from mcp.client.streamable_http import streamablehttp_client
  
  async with streamablehttp_client("http://localhost:8000") as (read, write, get_session_id):
      session = ServerSession(read, write)
      result = await session.call_tool("search", {"query": "AI trends"})
  ```

- **Resource and prompt definitions:** Beyond tools, expose search metadata as **resources** (read-only context) and **prompts** (reusable LLM instructions) for comprehensive context delivery.

## Gotchas

- **User consent & data handling:** MCP spec requires explicit user consent before invoking tools or transmitting resource data. Never silently pass user queries to external APIs without acknowledgment—implement consent checks before Perplexity API calls.

- **Transport mode mismatch in production:** Stdio is blocking and single-session; if deploying to prod with multiple concurrent clients, `streamable-http` is mandatory. Forgetting to set `host="0.0.0.0"` will bind only to localhost and be unreachable.

- **Schema strictness with `strict=True`:** When generating schemas for tools with complex inputs, `strict=True` enforces OpenAPI 3.1 compliance; incompatible types (e.g., `Any`, `Union` without discriminators) cause validation failures. Simplify input types or set `strict=False` only if clients tolerate looser validation.

---

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context and tools to Large Language Models. It enables seamless integration between LLM applications and external data sources, similar to how LSP standardizes language support across development tools. MCP supports multiple transport modes (stdio, streamable-http) and enforces explicit user consent for data access and tool invocation.

## Recommended library / tool
**FastMCP** — Python SDK that simplifies MCP server development with decorators and minimal boilerplate, supporting both stdio and HTTP transports out-of-the-box.

## Key patterns

- **Basic server setup with FastMCP:**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  mcp = FastMCP(name="perplexity-search-server")
  
  @mcp.tool()
  def search(query: str) -> str:
      """Search using Perplexity API"""
      # Implementation
      return results
  
  mcp.run()
  ```

- **HTTP transport for production deployment:**
  ```python
  from mcp.server.fastmcp import FastMCP
  
  mcp = FastMCP(name="perplexity-search-server", host="0.0.0.0", port=8000)
  mcp.run(transport="streamable-http")
  ```

- **Client communication via streamable-http:**
  ```python
  from mcp.client.streamable_http import streamablehttp_client
  
  async with streamablehttp_client("http://localhost:8000") as (read, write, get_session_id):
      result = await session.call_tool("search", arguments={"query": "AI trends"})
  ```

- **Resource and tool metadata retrieval for LLM integration:**
  ```python
  tools = await session.list_tools()
  # Use mcp_tool_to_responses_schema() to generate strict OpenAI-compatible schemas
  schema = mcp_tool_to_responses_schema(tool_name, description, input_schema, strict=True)
  ```

- **Tool definitions with input schemas:**
  ```python
  @mcp.tool()
  def search(query: str, limit: int = 10) -> dict:
      """Search Perplexity with optional result limit
      
      Args:
          query: Search query string
          limit: Max results (default 10)
      """
      # Perplexity API call
      return {"results": [...]}
  ```

## Gotchas

- **User consent is mandatory:** MCP enforces explicit user consent before invoking any tool or accessing resources. Hosts must not transmit resource data without consent, and you must obtain approval before exposing user data to the server—build consent dialogs into your deployment.

- **Transport mode mismatch in production:** Stdio transport works locally during development but fails in containerized/cloud environments. Always use `transport="streamable-http"` for prod deployments with proper host/port binding (use `0.0.0.0` to listen on all interfaces).

- **Schema generation timing:** Call `list_tools()` *after* the server is running and all tools are registered. Generating schemas before registration results in incomplete or missing tool definitions that break LLM routing.

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context, data, and tools to Large Language Models. Building an MCP server for Perplexity search involves creating a standardized interface that exposes search capabilities as tools and resources, then deploying it with proper authentication and monitoring to production.

## Recommended library / tool
**FastMCP** — simplifies server creation with minimal boilerplate and supports both stdio and streamable-http transports out of the box.

## Key patterns

### 1. Initialize FastMCP server for Perplexity integration
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def search(query: str, max_results: int = 10) -> dict:
    """Search Perplexity and return results"""
    # Call Perplexity API with credentials
    results = await perplexity_client.search(query, limit=max_results)
    return {"query": query, "results": results}

@mcp.resource(uri_template="search://{query}")
async def get_search_resource(query: str) -> str:
    """Expose search results as a resource"""
    results = await perplexity_client.search(query)
    return json.dumps(results)
```

### 2. Support both stdio and HTTP transports for flexibility
```python
# For local/development: stdio transport (default)
mcp.run()

# For production: streamable-http transport
mcp.run(host="0.0.0.0", port=8000, transport="streamable-http")
```

### 3. Implement OAuth 2.1 security for Perplexity API access
```python
from mcp.server.fastmcp import FastMCP
import os

mcp = FastMCP(name="perplexity-search-server")

# Load credentials from environment (never hardcode)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

async def call_perplexity(query: str) -> dict:
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.perplexity.ai/chat/completions",
            json={"model": "pplx-7b-online", "messages": [{"role": "user", "content": query}]},
            headers=headers
        ) as resp:
            return await resp.json()
```

### 4. Generate and expose tool schemas for LLM consumption
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def search(query: str, include_citations: bool = True) -> dict:
    """
    Search Perplexity for real-time information
    
    Args:
        query: Search query string
        include_citations: Whether to include source citations
    """
    # Implementation
    pass

# Clients can call list_tools() to discover available operations
# and extract inputSchema for strict schema validation
```

### 5. Production deployment with health checks and logging
```python
import logging
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def health_check() -> dict:
    """Verify server and Perplexity connectivity"""
    try:
        # Test Perplexity API connectivity
        result = await call_perplexity("test")
        logger.info("Health check passed")
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}

# Run with environment-based config
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
```

## Gotchas

1. **API Key exposure**: Store Perplexity credentials in environment variables or secure vaults, never in code. Use `os.getenv()` and fail loudly if keys are missing before server starts.

2. **Transport mode confusion**: stdio transport works locally but cannot handle concurrent requests well; use `streamable-http` for production. The transport parameter must match on both server and client, or connections will silently fail.

3. **Consent and data handling**: MCP spec requires explicit user consent before exposing search results to the LLM. Always document what data flows to Perplexity and implement audit logging for sensitive queries in production.

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context, data, and tools to Large Language Models. Building an MCP server for Perplexity search involves implementing tools/resources that expose search capabilities via either stdio or streamable-http transport, then deploying the server to production infrastructure.

## Recommended library / tool
**FastMCP** (Python) — High-level framework that simplifies MCP server creation with decorators and automatic schema generation, reducing boilerplate compared to raw protocol implementation.

## Key patterns

### 1. Create a FastMCP server with tool decorators
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def search(query: str, max_results: int = 5) -> str:
    """Search Perplexity for a given query."""
    # Call Perplexity API
    results = await perplexity_client.search(query, max_results)
    return format_results(results)

if __name__ == "__main__":
    mcp.run(transport="stdio")  # or "streamable-http"
```

### 2. Expose streamable-http transport for production deployment
```python
# Change transport from stdio to streamable-http for cloud/container deployment
mcp = FastMCP(name="perplexity-search-server")
# ... define tools ...
mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

### 3. Retrieve tool metadata for LLM integration
```python
# Client-side: fetch available tools and generate schemas
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://localhost:8080") as (read, write, get_session_id):
    session = ServerSession(read, write)
    tools = await session.list_tools()
    for tool in tools:
        # Use tool.name, tool.description, tool.inputSchema for LLM function calling
        schema = mcp_tool_to_responses_schema(
            tool.name, tool.description, tool.inputSchema, strict=True
        )
```

### 4. Implement proper error handling and OAuth 2.1 security
```python
@mcp.tool()
async def authenticated_search(query: str, auth_token: str) -> str:
    """Search with authentication."""
    if not validate_oauth_token(auth_token):
        raise ValueError("Invalid or expired OAuth token")
    # Proceed with search using validated token
    return await perplexity_client.search(query)
```

### 5. Deploy with explicit consent and data privacy controls
```python
# Document resource/tool access in server metadata
# Ensure hosts obtain user consent before:
# - Transmitting resource data externally
# - Invoking any tool
# - Exposing user data to the server

# Example: add consent check before search
@mcp.tool()
async def search_with_consent(query: str, user_consented: bool) -> str:
    if not user_consented:
        raise PermissionError("User consent required for search")
    return await perplexity_client.search(query)
```

## Gotchas

1. **Transport mismatch in production**: Stdio transport works for development/testing but doesn't scale for production. Always use `streamable-http` with proper host/port binding for containerized/cloud deployments. Forgetting to change from `transport="stdio"` to `transport="streamable-http"` is the #1 deployment failure.

2. **Missing schema validation and strict mode**: When exposing tools to LLMs, use `strict=True` in `mcp_tool_to_responses_schema()` to enforce proper JSON schemas. Loose schemas cause LLM hallucination and malformed API calls to Perplexity.

3. **Implicit data leakage without consent**: MCP requires explicit user consent before sending data to external services (Perplexity API) and before invoking tools. Deploying without consent checks violates the security model and may expose user queries inadvertently. Always validate user intent before calling external APIs.

recommended_tool: FastMCP

---
## Researcher update

# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how LLM applications integrate with external data sources and tools, similar to how LSP standardizes language support. Building an MCP server for Perplexity search involves exposing search capabilities as tools/resources that LLM hosts can call with proper user consent and security controls. Production deployment requires transport selection (stdio, streamable-http), performance monitoring, and explicit user consent mechanisms.

## Recommended library / tool
**FastMCP** — High-level Python framework that simplifies MCP server development with decorators and automatic schema generation, reducing boilerplate for tool/resource definition.

## Key patterns

### 1. **Basic Server Setup with FastMCP**
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="perplexity-search-server")

@mcp.tool()
async def search_perplexity(query: str, num_results: int = 10) -> dict:
    """Search Perplexity and return relevant results."""
    # Call Perplexity API
    results = await perplexity_client.search(query, num_results)
    return {"results": results, "query": query}

mcp.run(transport="stdio")
```

### 2. **Streamable-HTTP Transport for Production**
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="perplexity-search-server",
    host="0.0.0.0",
    port=8000
)

# Same tool definitions as above
@mcp.tool()
async def search_perplexity(query: str) -> dict:
    ...

# Deploy with HTTP transport
mcp.run(transport="streamable-http")
```

### 3. **Client Integration (Host Side)**
```python
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.session import ServerSession

async with streamablehttp_client("http://localhost:8000") as (read, write, get_session_id):
    session = ServerSession(read, write)
    result = await session.call_tool("search_perplexity", {"query": "quantum computing"})
    print(result)
```

### 4. **User Consent & Security**
```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def search_perplexity(query: str, context: Context) -> dict:
    """Verify user consent before executing search."""
    # Host must explicitly consent; MCP protocol enforces this
    # Never transmit user data without explicit consent
    if not context.user_consent.get("search_enabled"):
        raise PermissionError("User has not consented to search operations")
    return await perplexity_client.search(query)
```

### 5. **Production Monitoring & Metrics**
```python
import time
from collections import defaultdict

class PerplexityServerMetrics:
    def __init__(self):
        self.metrics = {
            "throughput": [],
            "latency_p50": [],
            "latency_p95": [],
            "latency_p99": [],
            "error_rate": [],
            "memory_usage": []
        }
    
    async def track_tool_call(self, tool_name: str):
        start = time.time()
        try:
            # Tool execution tracked here
            yield
        finally:
            latency = (time.time() - start) * 1000  # ms
            self.metrics["latency_p95"].append(latency)
```

## Gotchas

1. **Transport Mode Mismatch in Production** — Don't use `transport="stdio"` for production deployments. Stdio is single-process and blocks on I/O; use `streamable-http` or `sse` (Server-Sent Events) for scalable production with multiple concurrent clients.

2. **Missing User Consent Enforcement** — The MCP spec mandates explicit user consent before data access or tool invocation. Forgetting to validate consent in your tool handlers creates compliance and security issues. Always check the `Context` object or host-side session state.

3. **Unhandled Long-Running Searches** — Perplexity searches may take 5–30 seconds; without proper async/await and timeout handling, clients disconnect. Use task queues (Celery) or streaming responses for long operations, and set reasonable timeouts:
```python
import asyncio
result = await asyncio.wait_for(
    perplexity_client.search(query),
    timeout=30.0
)
```

---

recommended_tool: FastMCP