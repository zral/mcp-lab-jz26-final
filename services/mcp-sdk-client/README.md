# Third-Party MCP HTTP Client

## Purpose

This is a **completely independent MCP client** that proves the workshop MCP server follows the official Model Context Protocol specification.

Now runs in Docker for seamless integration with the complete system.

## What This Proves

✅ **Standard Compliance** - Server implements MCP 2025-11-25 spec correctly
✅ **Interoperability** - Any third-party client can connect without modifications
✅ **Protocol Correctness** - JSON-RPC 2.0 over HTTP works as specified
✅ **No Vendor Lock-in** - No custom protocol extensions required
✅ **Container Ready** - Runs in Docker with full service integration

## Installation & Usage

### Option 1: Docker (Recommended)

Run as a one-off compliance test container:

```bash
# Start the full stack with compliance test
docker compose --profile compliance-test up mcp-sdk-client

# Or run just the test container against existing services
docker compose up -d mcp-server  # if not already running
docker compose --profile compliance-test run mcp-sdk-client
```

### Option 2: Local Python

For local testing during development:

```bash
# Install dependencies
pip install -r requirements.txt

# Set MCP server URL (defaults to Docker service name)
export MCP_SERVER_URL=http://localhost:8000  # For local testing
# or
export MCP_SERVER_URL=http://mcp-server:8000  # For Docker network

# Run compliance test
python3 test_mcp_sdk.py
```

## Docker Configuration

The service is configured with a `compliance-test` profile to keep it optional in normal deployments.

## What It Tests

### 1. Tool Discovery (tools/list)

Sends standard JSON-RPC 2.0 request:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

Validates response contains:
- ✅ Valid JSON-RPC 2.0 format
- ✅ `result.tools` array
- ✅ Tool schemas with inputSchema and outputSchema

### 2. Tool Execution (tools/call)

Sends standard JSON-RPC 2.0 request:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_weather_forecast",
    "arguments": {"location": "Oslo"}
  }
}
```

Validates response contains:
- ✅ Valid JSON-RPC 2.0 format
- ✅ MCP `content` array
- ✅ `structuredContent` object
- ✅ `isError` boolean flag

## Docker Deployment

### Service Configuration

```yaml
mcp-sdk-client:
  build:
    context: ./services/mcp-sdk-client
    dockerfile: Dockerfile
  environment:
    - MCP_SERVER_URL=http://mcp-server:8000
  depends_on:
    mcp-server:
      condition: service_healthy
  profiles:
    - compliance-test
```

### Running in Docker

**Run as part of the full stack:**
```bash
# All services including compliance test
docker compose --profile compliance-test up

# Just the test container (assumes mcp-server is running)
docker compose --profile compliance-test run mcp-sdk-client
```

**View test results:**
```bash
docker compose logs mcp-sdk-client
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_URL` | `http://mcp-server:8000` | MCP server endpoint |
| `PYTHONUNBUFFERED` | `1` | Real-time log output |

## What It Tests

## Expected Output

```
======================================================================
MCP SDK HTTP Client - Official Third-Party Compliance Test
======================================================================

Connecting to MCP server: http://localhost:8000

1. Testing tools/list (Tool Discovery)
----------------------------------------------------------------------
✅ Successfully discovered 1 tool(s)
   - get_weather_forecast: Fetch a weather forecast for a destination...

2. Testing tools/call (Tool Execution)
----------------------------------------------------------------------
✅ Tool executed successfully
   Response type: text
   ✅ Structured content included
   Error status: False

======================================================================
✅ MCP Server is FULLY COMPLIANT with MCP 2025-11-25
======================================================================

Compliance verified:
  ✅ JSON-RPC 2.0 protocol
  ✅ POST /message endpoint
  ✅ tools/list method
  ✅ tools/call method
  ✅ MCP-compliant response format
  ✅ Structured content support
```

## Code Structure

The client is intentionally simple and independent:

```python
# 1. Create JSON-RPC 2.0 request
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
}

# 2. Send via HTTP POST
response = await client.post(
    f"{mcp_url}/message",
    json=request
)

# 3. Validate MCP-compliant response
result = response.json()
if "result" in result and "tools" in result["result"]:
    print("✅ MCP compliant!")
```

## Why This Matters

### For Workshop Participants

Shows that the MCP server you're learning with:
- Uses real industry standards
- Isn't a simplified "training wheel" version
- Works with production-ready tools

### For Technical Validation

Proves that:
- Server follows official MCP spec
- No custom protocol extensions
- Compatible with any MCP client
- Production-ready implementation

## Comparison with Workshop Client

| Client | Type | Purpose | Shared Code |
|--------|------|---------|-------------|
| **This (mcp-sdk-client)** | Third-party | Compliance proof | ❌ None |
| **Workshop Agent** | Workshop | Full demo | ✅ Uses same server |

## MCP Specification Reference

- **Spec Version:** 2025-11-25
- **Transport:** Streamable HTTP (non-streaming mode)
- **Protocol:** JSON-RPC 2.0
- **Endpoint:** POST /message
- **Docs:** https://modelcontextprotocol.io/specification/2025-11-25

## Troubleshooting

### "Connection refused" (Local Testing)

Ensure MCP server is running:
```bash
curl http://localhost:8000/health
```

### "Connection refused" (Docker)

Ensure both containers are on the same network:
```bash
# Check if mcp-server is running and healthy
docker compose ps

# View mcp-server logs
docker compose logs mcp-server

# Restart services
docker compose restart mcp-server
docker compose --profile compliance-test run mcp-sdk-client
```

### "Invalid response format"

Check server is running the latest version:
```bash
docker compose logs mcp-server | tail -20
```

### "httpx not installed" (Local Testing)

```bash
pip install httpx
```

### Test Container Exits Immediately

This is normal - the test runs once and exits. View results with:
```bash
docker compose logs mcp-sdk-client
```

To keep it running for interactive testing, override the command:
```bash
docker compose --profile compliance-test run mcp-sdk-client sleep 3600
```

## Next Steps

After proving compliance, try:

1. **Test with your own tools** - Add new tools to MCP server
2. **Create your own client** - Follow the same JSON-RPC 2.0 pattern
3. **Connect other tools** - Any MCP client should work now

## License

Same as workshop project - educational purposes.
