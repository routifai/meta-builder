# mcp-protocol

## Overview
The Model Context Protocol (MCP) is an open protocol that standardizes how LLM applications access external data sources and tools, similar to how LSP standardized language support. Building an MCP server for Perplexity search involves implementing tools/resources that the server exposes via stdio or HTTP transport, then deploying the server to Fly.io for persistent access.

## Recommended library / tool
**FastMCP** — lightweight Python decorator-based framework for building MCP servers with minimal boilerplate, supporting both stdio and streamable-http transports.

## Key patterns

- **Initialize FastMCP server with transport type:**
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Perplexity Search Server")
# For HTTP deployment: mcp = FastMCP(name="...", host="0.0.0.0", port=8000)
```

- **Define tools using decorators:**
```python
@mcp.tool()
def search_perplexity(query: str) -> str:
    """Search using Perplexity API and return results."""
    # Call Perplexity API here
    return results

mcp.run(transport="streamable-http")  # or "stdio"
```

- **For Fly.io deployment, use HTTP transport and expose port 8000:**
  - Set `host="0.0.0.0"` and `port=8000` in FastMCP initialization
  - Clients connect via `streamablehttp_client("http://<fly-app-name>.fly.dev")` 
  - Include `fly.toml` with `internal_port = 8000` and allow HTTP traffic

- **Client-side tool invocation pattern:**
```python
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://perplexity-server.fly.dev") as (read, write, get_session_id):
    session = ServerSession(read, write)
    result = await session.call_tool("search_perplexity", {"query": "latest AI news"})
```

- **Obtain tool schemas dynamically for LLM integration:**
```python
tools_list = await session.list_tools()
# Extract input_schema from each tool for function calling
for tool in tools_list:
    schema = tool.input_schema
```

## Gotchas

- **Transport mismatch:** stdio transport (default) works for local testing but won't work with Fly.io; always switch to `streamable-http` before deployment and ensure clients use the matching `streamablehttp_client`.

- **Port binding:** Fly.io expects services to bind to `0.0.0.0` (not `localhost`); forgetting this will cause health checks to fail. Set `host="0.0.0.0"` explicitly in FastMCP initialization.

- **User consent and data safety:** MCP requires explicit user consent before exposing Perplexity search data or invoking tools; document what data flows through your server and obtain approval before production use, especially if serving multiple users.

recommended_tool: FastMCP