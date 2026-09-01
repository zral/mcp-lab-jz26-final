# MCP Travel Weather — Copilot instructions

A workshop project demonstrating the **Model Context Protocol**. An agent discovers
tools from an MCP server at runtime, calls them, and answers in natural language.

Weather data comes from **yr.no (api.met.no)**, geocoding from **Nominatim**. There
is no Google Travel integration and never has been.

## Architecture

Three services in Docker, plus two optional ones:

| Service | Port | Role |
| --- | --- | --- |
| `mcp-server` | 8000 | The MCP endpoint. Hosts tools, calls yr.no |
| `travel-agent` | 8001 | LLM client + MCP client. Runs the tool loop |
| `agent-web` | 8080 | Chat interface, proxies to the agent |

## Language

**English everywhere**: code, comments, docstrings, UI strings, log messages,
commit messages and documentation. Do not write Norwegian.

The only exceptions are deliberate: `æ`, `ø` and `å` appear as examples of values
that are not ASCII-safe and must be base64-wrapped in the `Mcp-Name` header.

## Protocol: MCP 2026-07-28

This revision is **stateless**. There is no `initialize`, no session. Code you
generate must respect this.

**Every request** carries `params._meta` with `io.modelcontextprotocol/protocolVersion`
and `io.modelcontextprotocol/clientCapabilities`, mirrored into the
`MCP-Protocol-Version`, `Mcp-Method` and (where applicable) `Mcp-Name` headers.

On the client side, build requests with `build_mcp_request()` in
`services/agent/app.py`. Never hand-assemble a JSON-RPC body — you will forget
`_meta` and get a `400`.

**Every result** carries `resultType`. Cacheable list results (`server/discover`,
`tools/list`) also carry `ttlMs` and `cacheScope`. `tools/call` results do not.

**Error codes are paired with HTTP status codes.** Do not return `200` with an
error in the body:

| Code | HTTP | When |
| --- | --- | --- |
| `-32601` | **404** | unknown method |
| `-32602` | 400 | missing `_meta` or parameters |
| `-32020` | 400 | a header disagrees with the body |
| `-32022` | 400 | unsupported protocol version |
| `1001` | 403 | untrusted `Origin` |

New error codes must fall **outside** `-32768`..`-32000`. The range `-32020`..`-32099`
belongs to the spec; `-32000`..`-32019` is legacy and must not be used.

**`isError: true` is not a protocol error.** It means the tool ran and failed, and
the message is for the model, which can retry with different arguments. A tool that
does not exist is a protocol error (`-32602`, HTTP 400).

## Adding a tool

Server-side only. The agent needs no changes — that is the point of dynamic
discovery.

1. Write the implementation in `services/mcp-server/app.py`
2. Add the definition to `handle_tools_list()` — `name`, `description`, `inputSchema`
3. Add routing in `handle_tools_call()`
4. Return `{"resultType": "complete", "content": [...], "structuredContent": {...}, "isError": False}`

There is **one** MCP endpoint. Do not add `endpoint` or `method` fields to the
manifest, and do not create per-tool HTTP routes. The spec requires a single
endpoint, and an earlier `tool_endpoints` map that assumed otherwise has been
deleted.

## The LLM provider is configuration, not code

The agent speaks an **OpenAI-compatible API**. Three environment variables decide
which provider: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`.

Never hardcode a model name, a base URL or a vendor name outside
`MicroserviceAgent.__init__`. The default is Gemini via its OpenAI-compatible
endpoint, after GitHub Models was retired on 30 July 2026 — that migration cost
three lines of config precisely because nothing downstream named a vendor.

When echoing an assistant message back into the conversation history, pass it
through as received (`model_dump()`). Rebuilding it field by field drops
provider-specific fields such as Gemini's `thought_signature`, which it requires
back and will answer `400` without.

## The agent's system prompt is DELIBERATE

`services/agent/app.py` limits which tools the agent may call, and restates that
limit after the conversation history.

**This is intentional and load-bearing. Do not remove, relax or "tidy" it**, and
do not reconcile it with the dynamic tool discovery described above — the tension
between them is on purpose.

If a change appears to require touching it, stop and ask the repo owner.

## Constraints

- **Run in Docker only** — `docker compose`, never bare on localhost
- Python for all services
- Do not hardcode endpoint URLs in the agent; read them from the environment
- Proper error handling and logging on every path
- Document changes in `README.md`

## Testing

```bash
make test-protocol     # 38 protocol tests, in-process, no network
make test-compliance   # the official mcp 2.0.0 SDK against our server
make curl-list         # or helper/mcp-curl, which sets the required headers
```

Tests must not call the real weather tool — that reaches yr.no and makes the suite
slow and flaky.

## Further reading

- `doc/mcp-2026-07-28-changes.md` — what the revision changes and why, including
  the transport decision
- `doc/mcp-2026-07-28-corrections.md` — what was actually wrong and got fixed
