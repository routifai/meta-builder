# Anthropic Python SDK

## Source
https://platform.claude.com/docs/en/api/sdks/python

## Installation

```bash
pip install anthropic
pip install "anthropic[aiohttp]"   # better async performance
```

Python 3.9+ required.

---

## Sync client

```python
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])  # or omit — reads env by default

message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "Hello"}],
)
print(message.content[0].text)
```

---

## Async client

```python
import asyncio
from anthropic import AsyncAnthropic, DefaultAioHttpClient

async def main():
    async with AsyncAnthropic(
        http_client=DefaultAioHttpClient(),   # aiohttp for better concurrency
    ) as client:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Hello"}],
        )
        print(message.content[0].text)

asyncio.run(main())
```

---

## Tool use (client-side)

Claude returns `stop_reason: "tool_use"` when it wants to call a tool. Your code executes it and returns a `tool_result`.

### Define tools

```python
tools = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, e.g. 'San Francisco, CA'"
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "default": "celsius"
                }
            },
            "required": ["location"]
        }
    }
]
```

### Agentic loop

```python
messages = [{"role": "user", "content": "What's the weather in London?"}]

while True:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=tools,
        messages=messages,
    )

    if response.stop_reason == "end_turn":
        print(response.content[0].text)
        break

    if response.stop_reason == "tool_use":
        # append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # execute each tool call
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # append tool results as user turn
        messages.append({"role": "user", "content": tool_results})
```

### `@beta_tool` decorator helper

```python
from anthropic import beta_tool

@beta_tool
def get_weather(location: str) -> str:
    """Get the weather for a given location."""
    return f"Sunny, 22°C"

runner = client.beta.messages.tool_runner(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[get_weather],
    messages=[{"role": "user", "content": "Weather in Paris?"}],
)
for message in runner:
    print(message)
```

### Strict tool use

Add `"strict": True` to any tool definition to enforce schema conformance:

```python
{"name": "get_weather", "strict": True, "input_schema": {...}}
```

---

## Prompt caching

Caching reduces cost to 10% of input token price on cache hits (5-minute TTL by default, 1-hour available).

### Minimum token thresholds for caching to activate

| Model | Min tokens |
|-------|-----------|
| claude-opus-4-6, claude-opus-4-5 | 4,096 |
| claude-sonnet-4-6 | 2,048 |
| claude-sonnet-4-5, claude-sonnet-4 | 1,024 |
| claude-haiku-4-5 | 4,096 |

### Automatic caching (recommended for conversations)

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},       # top-level: auto-moves breakpoint
    system="Long system prompt...",
    messages=[...],
)
print(response.usage.cache_read_input_tokens)   # 0 on first call, >0 on hits
print(response.usage.cache_creation_input_tokens)
```

### Explicit breakpoints (fine-grained control — up to 4 per request)

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "Large static system context...",
            "cache_control": {"type": "ephemeral"}   # cache everything up to here
        }
    ],
    messages=[{"role": "user", "content": "question"}],
)
```

### 1-hour TTL (for agentic workflows > 5 min)

```python
{"cache_control": {"type": "ephemeral", "ttl": "1h"}}
```

### Cost structure

| Type | Multiplier |
|------|-----------|
| Cache write (5m) | 1.25x |
| Cache write (1h) | 2.0x  |
| Cache read       | 0.1x  |
| Normal input     | 1.0x  |

**Cache invalidation triggers:** changing tool definitions, toggling web search, changing tool_choice, adding/removing images.

**Best practice:** place static content first (system prompt → tools → examples → dynamic context). Never put timestamps or per-request context at the breakpoint.

---

## Streaming

```python
# Streaming with context manager (accumulates final message)
async with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Tell me a story"}],
) as stream:
    async for text in stream.text_stream:
        print(text, end="", flush=True)
    final = await stream.get_final_message()
```

---

## Error handling

```python
import anthropic

try:
    response = client.messages.create(...)
except anthropic.APIConnectionError as e:
    # network error — underlying httpx exception in e.__cause__
except anthropic.RateLimitError:
    # 429 — SDK retries 2x by default with exponential backoff
except anthropic.APIStatusError as e:
    print(e.status_code, e.response)
```

**Error codes:**

| Code | Exception |
|------|-----------|
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 429 | `RateLimitError` |
| 500+ | `InternalServerError` |
| N/A | `APIConnectionError`, `APITimeoutError` |

SDK auto-retries: connection errors, 408, 409, 429, 5xx — 2 times by default with exponential backoff.

```python
client = Anthropic(max_retries=5)   # override default of 2
client.with_options(max_retries=0)  # per-request override
```

---

## Timeouts

```python
import httpx

client = Anthropic(
    timeout=httpx.Timeout(60.0, read=30.0, write=10.0, connect=5.0),
)
# Default is 10 minutes. For long agent runs, use streaming instead.
```

---

## Token counting

```python
# Count before sending
count = client.messages.count_tokens(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Hello"}],
)
print(count.input_tokens)

# Inspect after response
print(response.usage)  # Usage(input_tokens=..., output_tokens=...)
```

---

## Models reference

| Model ID | Use case |
|----------|----------|
| `claude-opus-4-6` | Most capable, complex reasoning |
| `claude-sonnet-4-6` | Balanced speed + capability (default choice) |
| `claude-haiku-4-5-20251001` | Fastest, highest throughput |

---

## Gotchas

- **Async with aiohttp:** use `DefaultAioHttpClient()` for parallel agent calls — httpx default has worse concurrency under load.
- **Streaming for long runs:** non-streaming requests > ~10 min throw `ValueError`. Always stream in agentic loops with large outputs.
- **`cache_control` invalidation:** even small changes to tools or tool_choice bust the cache. Keep tool definitions static; put dynamic context after the breakpoint.
- **`stop_reason` must be checked:** never assume `end_turn` — always handle `tool_use` in the loop.
- **Request ID for debugging:** `response._request_id` — log this on any error for Anthropic support.
