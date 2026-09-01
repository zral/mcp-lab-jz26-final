# MCP Travel Weather — JavaZone 2026 workshop

An AI agent that actually does things: it discovers tools over the **Model Context
Protocol**, calls them, and answers in natural language.

Three services, one protocol, real weather data from yr.no.

**[Presentation](./doc/ws-pres-cut.md)** ·
**[What changed in 2026-07-28](./doc/mcp-2026-07-28-changes.md)**

---

## What this is

The agent does **not** hardcode its tools. On start-up it asks the MCP server what
exists, converts the manifest into the format the model understands, and from then
on the model decides when to call what.

That means **adding a tool requires no agent code at all** — you change the MCP
server and restart. That is the point of the workshop, and it is the same argument
one layer down from swapping the LLM provider (see below).

```
Browser  →  Web (8080)  →  Agent (8001)  →  MCP Server (8000)  →  yr.no
                                ↓
                          Gemini (LLM)
```

| Service | Port | Does |
| --- | --- | --- |
| `agent-web` | 8080 | Chat interface, proxies to the agent |
| `travel-agent` | 8001 | Talks to the LLM, calls MCP tools, keeps history |
| `mcp-server` | 8000 | The MCP endpoint. Hosts tools, calls yr.no and Nominatim |
| `datasette` | 8090 | Optional. Browse the conversation database (`make db-view`) |
| `mcp-sdk-client` | — | Optional. Third-party compliance check |

## Quick start

```bash
git clone https://github.com/zral/mcp-lab-jz26-final.git
cd mcp-lab-jz26-final

cp .env.example .env
# Put a Gemini key in OPENAI_API_KEY — see below

make up
make status
```

`make up` is `docker compose up -d` plus a check that your `.env` is in step with
`.env.example`. The check warns and continues rather than blocking: lab 1 is pure
curl against the MCP server and needs no LLM key at all.

Then open **http://localhost:8080**.

### Getting an API key

1. Go to <https://aistudio.google.com/apikey>
2. Sign in with a Google account
3. **Create API key** — under a minute, no credit card
4. Paste it into `OPENAI_API_KEY` in `.env`

Free tier on `gemini-3.5-flash-lite`: **500 requests/day, 15/minute**. A query costs
two calls (one to choose the tool, one to phrase the answer), so that is roughly 250
questions per day. The plain Flash models are capped at **20/day** — hence the lite
model.

Weather data comes from **yr.no (api.met.no)** and needs no key at all.

## MCP 2026-07-28: what every request must carry

This revision made MCP **stateless**. There is no `initialize`, no session. Every
request carries the protocol version and client capabilities itself, in
`params._meta`, mirrored into HTTP headers so intermediaries can route without
parsing the body.

```http
POST /message
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: get_weather_forecast

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_weather_forecast",
    "arguments": { "location": "Oslo" },
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

Leave any of that out and a conforming server answers `400`. **Error codes are now
paired with HTTP status codes:**

| Code | Name | HTTP | When |
| --- | --- | --- | --- |
| `-32700` | Parse error | 400 | invalid JSON |
| `-32600` | Invalid Request | 400 | not valid JSON-RPC 2.0 |
| `-32601` | Method not found | **404** | unknown method |
| `-32602` | Invalid params | 400 | missing `_meta` or parameters |
| `-32020` | HeaderMismatch | 400 | a header disagrees with the body |
| `-32022` | UnsupportedProtocolVersion | 400 | we do not speak that version |
| `1001` | Origin not allowed | 403 | untrusted `Origin` |

The `404` is deliberate: it lets a client tell a modern server from a legacy one
that does not host the endpoint at all.

`Mcp-Name` only applies to methods with a name parameter (`tools/call`,
`resources/read`, `prompts/get`). `tools/list` has none.

## Testing

Typing four headers and a `_meta` block by hand, forty times, is how you end up
debugging your own typos instead of the protocol. Use the wrapper:

```bash
make curl-discover     # server/discover: versions, capabilities, identity
make curl-list         # tools/list
make curl-weather      # tools/call for Oslo
make curl-agent        # the whole path, through the agent
```

Or call `helper/mcp-curl` directly:

```bash
./helper/mcp-curl tools/list
./helper/mcp-curl tools/call '{"name":"get_weather_forecast","arguments":{"location":"Bergen"}}'
```

### Break it on purpose

The fastest way to understand the rules is to violate them:

```bash
make curl-mismatch     # 400 + -32020  header disagrees with the body
make curl-nometa       # 400 + -32602  no _meta
make curl-badversion   # 400 + -32022  with data.supported
make curl-unknown      # 404 + -32601  unknown method
make curl-origin       # 403           DNS rebinding protection
```

### Protocol tests

```bash
make test-protocol     # 38 tests, in-process, no network
make test              # protocol tests + the SDK check
```

These assert that each violation produces both the right JSON-RPC error code and
the right HTTP status code. Getting the code right while getting the status wrong
still breaks clients, and nothing in ordinary use will tell you.

### Third-party compliance

```bash
make test-compliance
```

This runs the official **`mcp` 2.0.0** Python SDK against the server. It is not our
client and cannot be talked into agreeing with us: it negotiates a version, reads
our capabilities and parses our results. It reports "no problems found in what was
checked" rather than "compliant" — SSE, MRTR, subscriptions, pagination and
authorization are not covered.

## Adding a tool

1. Write the implementation in `services/mcp-server/app.py`:

```python
async def my_tool(param: str) -> Dict[str, Any]:
    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": result}],
        "structuredContent": {...},
        "isError": False,
    }
```

2. Add it to the manifest in `handle_tools_list()`: `name`, `title`,
   `description`, `inputSchema` and `outputSchema` (JSON Schema 2020-12). No
   `endpoint` or `method` field — there is exactly one endpoint.
3. Add routing in `handle_tools_call()`, with `resultType` on every return path.
4. `docker compose restart mcp-server travel-agent`

The agent discovers it automatically. No agent code changes.

Labs 2 and 3 walk through this: `helper/lab2-exercise.md` and
`helper/lab3-exercise.md`.

## The provider underneath is infrastructure you do not control

This workshop ran on GitHub Models. It was retired on **30 July 2026** with six
weeks' notice and no migration path — the inference API answers `410` to everyone.

Migrating to Gemini cost an API key, a base URL and a model name, all in `.env`:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-3.5-flash-lite
```

Same SDK, same tool definitions, same message format, same agent loop. That is not
luck, it is architecture: we speak a *protocol* rather than to a *vendor*, and the
provider is bound in exactly one place.

Swapping to OpenAI, Groq or a local Ollama model is the same three lines — see
`.env.example`.

## Development

```bash
make up                # start everything
make down              # stop
make logs-mcp          # follow one service
make health            # check all three
make diagrams          # rebuild the architecture diagrams from Mermaid source
make slides            # diagrams + presentation HTML
make help              # every target
```

### Looking at the conversation database

Every question and answer is stored in SQLite, in a Docker volume rather than on
your disk. Two ways in:

```bash
make db-shell          # SQL prompt, no extra container
make db-view           # Datasette in the browser, on 8090
make db-stats          # row counts and sizes
make db-reset          # wipe it and start a fresh session (asks first)
```

`db-shell` uses the SQLite REPL that ships with Python 3.12+, so it needs nothing
that is not already in the agent image. Note it has no `.tables` or `.schema` —
use `select name from sqlite_master where type='table';` instead.

`db-view` pulls Datasette on demand (324MB, once). It sits behind a Compose
profile so `make up` does not download it for everyone.

`db-reset` deletes the database file and restarts the agent, which recreates the
schema. The restart is not optional: the agent holds one session id from
start-up, so wiping the tables under a running agent would leave it writing
messages against a session that no longer exists. To throw away the volume
entirely instead — history, logs and images — use `make clean`.

Rebuild after code changes:

```bash
docker compose up -d --build mcp-server travel-agent
```

## Troubleshooting

**Everything returns `400`.** Read the error code in the body. `-32602` means
`_meta` is missing; `-32020` means a header disagrees with it.

**`404` on a method you know exists.** Check the spelling in *both* `Mcp-Method` and
the body. And remember `404` is the correct answer for an unknown method now.

**The agent answers but never calls a tool.** Check `docker compose logs
travel-agent` for `Loaded N tools`. If it says `continuing without tools`, the agent
could not reach the MCP server.

**Rate limited.** Free tier is 15 requests/minute. Two calls per question means
about seven questions a minute.

**`Conflict. The container name "/travel-weather-mcp" is already in use`.**
You have containers left over from a run under a different Compose project name.
Every service here has an explicit `container_name`, and those are global rather
than project-scoped, so two projects collide.

```bash
make clean          # clears both project names and any stale containers
make up-build
```

If your `.env` still contains a `COMPOSE_PROJECT_NAME` line, delete it. It is no
longer in `.env.example`: with it set, running `docker compose` with and without
`.env` created two different projects, which is what caused the conflict.

## Layout

```
services/
├── mcp-server/        MCP endpoint and tools
│   ├── app.py         tools, handlers, yr.no integration
│   ├── mcp_protocol.py  _meta and header validation, error/status codes
│   └── test_mcp_protocol.py  38 protocol tests
├── agent/             the agent
│   ├── app.py         LLM client, MCP client, tool loop
│   └── conversation_memory.py
├── web/               chat interface
└── mcp-sdk-client/    third-party compliance check
helper/mcp-curl        curl wrapper that sets the required headers
helper/lab2-exercise.md, lab3-exercise.md   the labs, written out
helper/lab2-solution.md, lab3-solution.md   solutions, ROT13-encoded
doc/                   presentation, diagrams, protocol notes
```

The solutions are ROT13 so you cannot read them by accident. Decode one with
`tr 'A-Za-z' 'N-ZA-Mn-za-m' < helper/lab2-solution.md`.

## Specification

<https://modelcontextprotocol.io/specification/2026-07-28>
