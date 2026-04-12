# fly-workers

## Overview
Fly.io workers enable you to run long-running background tasks, image processing, and async jobs outside your main application thread. They're ideal for deep research agents that need to perform multiple API calls, data aggregation, and analysis without blocking user requests. Python workers on Fly.io scale efficiently across distributed infrastructure, making them well-suited for agents that coordinate multiple concurrent research operations.

## Recommended library / tool
**LangChain ReAct Agent** — Provides a research-focused agent framework with built-in tool integration, web search capabilities, and Python REPL execution for deep analytical tasks.

## Key patterns

**1. Worker task queue with Flask background jobs**
```python
from flask import Flask
import backgroundjobs

app = Flask(__name__)

@app.route('/research', methods=['POST'])
def start_research():
    query = request.json.get('query')
    job_id = backgroundjobs.enqueue(deep_research_task, query)
    return {'job_id': job_id}, 202

def deep_research_task(query):
    # Long-running research logic
    results = agent.invoke({'query': query})
    return results
```

**2. Agent with tool composition for research**
```python
from langchain.agents import ReActAgent
from langchain.tools import Tool
import httpx

tools = [
    Tool(name="search", func=search_api, description="Search the web"),
    Tool(name="fetch", func=fetch_url, description="Get page content"),
    Tool(name="analyze", func=analyze_text, description="Extract insights")
]

agent = ReActAgent.from_tools(tools, llm=model)
result = agent.invoke({'input': 'Research topic X in depth'})
```

**3. Structured output with Pydantic models**
```python
from pydantic import BaseModel
from typing import List

class ResearchResult(BaseModel):
    sources: List[str]
    findings: str
    confidence: float

def deep_research_task(query: str) -> ResearchResult:
    # Agent performs research
    return ResearchResult(
        sources=[...],
        findings="...",
        confidence=0.95
    )
```

**4. Async coordination across multiple workers**
```python
import asyncio
import httpx

async def parallel_research(queries: List[str]):
    async with httpx.AsyncClient() as client:
        tasks = [fetch_and_analyze(q, client) for q in queries]
        results = await asyncio.gather(*tasks)
    return results

async def fetch_and_analyze(query, client):
    response = await client.get(f"https://api.example.com/search?q={query}")
    return agent.invoke({'data': response.json()})
```

**5. Health checks and task monitoring**
```python
from fly import fly_client

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'region': os.getenv('FLY_REGION')}

def report_research_progress(job_id, progress):
    fly_client.log(f"Job {job_id}: {progress}% complete")
```

## Gotchas

**1. Memory and timeout limits** — Long research operations can exceed default worker timeouts (usually 30s). Use Fly.io's concurrency limits and set explicit timeouts on HTTP requests to external APIs. Break large research tasks into smaller checkpointed steps saved to a database.

**2. Cold starts on first invocation** — Python workers have slower cold starts than Node.js. Pre-warm workers with dummy requests or use Fly.io's always-on feature for critical agents. Keep dependencies lean; avoid heavy imports at module level.

**3. API rate limits and external dependencies** — Research agents making multiple concurrent API calls can hit rate limits. Implement exponential backoff, request queueing, and cache responses aggressively. Always add timeout parameters to HTTP clients to prevent hanging requests.

recommended_tool: LangChain ReAct Agent