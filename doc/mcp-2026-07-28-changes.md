# What is new in MCP 2026-07-28

A summary of the upgrade from specification `2025-11-25` to `2026-07-28` — both
what changed in the code and what has to change in the workshop.

This document is written for instructors and for participants who have been
through an earlier edition of the lab. The full gap analysis with all 25 findings
lives in `doc/mcp-2026-07-28-gap.md` (working note, not in the repo).

**Status as of 2026-08-23:** step 1 of 7 is implemented. See
[What remains](#what-remains) at the bottom.

---

## In short

`2026-07-28` is a breaking revision. The big idea is that **MCP is now explicitly
stateless**. The spec says so outright:

> "The Model Context Protocol (MCP) is a stateless protocol: all the information
> needed to process a request is contained in the request itself."

Everything that used to live in a handshake and a session now has to travel with
*every single request*.

### Removed

| What | Comment |
| --- | --- |
| `initialize` / `notifications/initialized` | No handshake any more |
| Protocol sessions and `Mcp-Session-Id` | No state between requests |
| The GET endpoint (standalone SSE stream) | GET/DELETE must answer `405` |
| SSE resumability (`Last-Event-ID`) | Streams cannot be resumed |
| `resources/subscribe` | Replaced by `subscriptions/listen` |
| `ping`, `logging/setLevel` | Retired |

This repo got off lightly: the server was hand-rolled stateless on top of FastAPI
instead of using the SDK, so most of what was removed we never had.

### New

| What | Level |
| --- | --- |
| `params._meta` carrying protocol version and client capabilities on every request | **MUST** |
| HTTP headers mirroring the body: `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` | **MUST** |
| `server/discover` — versions, capabilities and identity in one call | **MUST** |
| `resultType` on all results (`"complete"` / `"input_required"`) | **MUST** |
| `ttlMs` and `cacheScope` on list results | **MUST** |
| `Origin` validation against DNS rebinding | **MUST** |
| JSON-RPC error codes paired with HTTP status codes | **MUST** |
| MRTR — the server asks for input in a *result*, the client retries | out of scope for the lab |

---

## Before and after

The same call, `tools/call` against the weather tool.

### 2025-11-25

```http
POST /message
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_weather_forecast",
    "arguments": { "location": "Oslo, Norway" }
  }
}
```

### 2026-07-28

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
    "arguments": { "location": "Oslo, Norway" },
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {},
      "io.modelcontextprotocol/clientInfo": {
        "name": "travel-agent",
        "version": "1.0.0"
      }
    }
  }
}
```

One header became four, and the body gained a `_meta` block.

**Why both header and body?** The body is the truth. The headers exist so that
intermediaries — load balancers, gateways, observability tooling — can route and
inspect without parsing JSON. The server **MUST** check that the two agree. If
they diverge you have an attack surface: a gateway that waves through
`Mcp-Name: read_document` while the body says `delete_everything`.

Note that `Mcp-Name` only applies to methods that take a name parameter
(`tools/call`, `resources/read`, `prompts/get`). `tools/list` and
`server/discover` have none.

---

## Error codes and status codes now go together

This is the biggest change to get used to in practice. The server used to answer
HTTP 200 for everything and put the error in the body. Now each violation has its
own status code.

| Code | Name | HTTP | When |
| --- | --- | --- | --- |
| `-32700` | Parse error | 400 | invalid JSON |
| `-32600` | Invalid Request | 400 | not valid JSON-RPC 2.0 |
| `-32601` | Method not found | **404** | unknown method |
| `-32602` | Invalid params | 400 | missing `_meta` or parameters |
| `-32603` | Internal error | 500 | unexpected server-side failure |
| `-32020` | HeaderMismatch | 400 | header disagrees with the body |
| `-32021` | MissingRequiredClientCapability | 400 | the client lacks a required capability |
| `-32022` | UnsupportedProtocolVersion | 400 | we do not speak that version |
| `1001` | Origin not allowed | 403 | invalid `Origin` (our own code) |

**404 on an unknown method** is not a detail. It lets a client tell a modern
server (404 *with* a JSON-RPC body) from an old HTTP+SSE server that does not
have the endpoint at all (404 without such a body). Without the status code the
two are indistinguishable.

### A new policy for error codes

JSON-RPC reserves `-32000` through `-32099` for implementation-defined errors.
MCP now subdivides that range:

- `-32000`–`-32019` — **legacy.** Do not adopt. No defined meaning.
- `-32020`–`-32099` — **reserved for the spec.** Use only defined codes, and only
  with the meaning the spec gives them.

Your own errors that the spec does not cover belong **outside** `-32768`–`-32000`.
That is why our `Origin not allowed` is a positive number (`1001`), not `-32000`.

---

## New in the code

### `services/mcp-server/mcp_protocol.py` (new file)

The protocol layer. The server's doorkeeper: it validates that the request
carries what it must, and translates violations into the right error code *and*
the right status code.

The validation order is deliberate and documented in the file:

1. The `_meta` fields → `-32602`
2. The headers mirror the body → `-32020`
3. The version is supported → `-32022`

The body is the truth, so we first check that it is complete. Swap 1 and 2 and a
client that forgot `_meta` gets told "header mismatch" against a value that does
not exist — a useless error message.

The file also handles:

- **`Origin` validation.** An absent `Origin` is fine (curl and the agent send
  none — it is the browser that sets it, and the browser is what the attack goes
  through). Allowed are `localhost`, `127.0.0.1`, `*.app.github.dev` for
  Codespaces, plus whatever you put in the `MCP_ALLOWED_ORIGINS` environment
  variable. The value `*` turns the check off.
- **The base64 sentinel.** HTTP headers only tolerate visible ASCII, so values
  that are not ASCII-safe get wrapped: `Mcp-Name: =?base64?VHJvbXPDuA==?=`. The
  server **MUST** decode before comparing against the body — otherwise a tool
  name containing æ, ø or å would always be rejected as a header mismatch.

### `services/mcp-server/app.py`

`handle_jsonrpc` has been rewritten. The request is no longer parsed with
Pydantic: Pydantic would answer `422` in its own error format, which no MCP
client understands, and the spec requires specific status codes. The body is now
parsed manually and `mcp_protocol.py` decides both code and status.

An unknown tool now yields `-32602` instead of an `isError` result. The
distinction is worth making from the stage:

- `isError: true` means "the tool ran, but it went wrong". That message is meant
  for the model, which can retry with different arguments.
- A tool that does not exist, on the other hand, is the client asking for
  something that is not there, and should surface as a JSON-RPC error so the
  client can re-fetch `tools/list`.

### `services/mcp-server/Dockerfile`

It only copied `app.py`. Now it copies `mcp_protocol.py` too — without that the
container crashes on start-up.

---

## What changed in the workshop

### Curl is no longer "just send JSON"

That is currently one of the selling points, both in the module docstring in
`app.py` and in the presentation. It does not hold any more: every example goes
from one `-H` to four plus a `_meta` block in the body.

Affected:

- **`Makefile`** — four targets call the MCP server directly and need the
  headers: `curl-list`, `curl-weather`, `curl-fact` (lab 2), `curl-news`
  (lab 3). The four that go through the agent on port 8001 (`curl-agent`,
  `curl-fact-agent`, `curl-news-agent`, `curl-combo`) need no change — the agent
  is the client.
- **`README.md`** and both presentations — roughly 40 JSON-RPC examples.
- **Lab exercise 1** (`Test tools/list`, `Test tools/call`), **lab exercise 2**
  (step 4, compliance testing) and **lab exercise 3** (the news API).
- **The test-strategy slide** ("Unit testing", "Integration testing").

In a two-hour workshop this is a real cost. The plan is new `make curl-*` targets
that set the headers, so participants do not have to copy-paste the mistake four
times.

It is also an honest lesson to convey from the stage: **this is the price the
protocol paid to become stateless.** The simplicity did not disappear, it moved —
from the server's state handling to the client's request building.

### Slides that need rewriting

- **"MCP Standard 2025-11-25"** → `2026-07-28`, with a new list of what the lab
  simplifies.
- **"🔄 JSON-RPC 2.0 Protocol"** — the message-handler example no longer matches
  the code.
- **"Agent - Fetching tools from the MCP server"** and **"Agent calls with
  JSON-RPC"** — must show `_meta` and the headers.
- **"Security considerations"** — there is now something concrete to show, see
  below.

### Adding a new tool is almost unchanged

Good news for lab exercises 2 and 3: the pattern holds. You still add a tool
definition in `handle_tools_list()`, a branch in `handle_tools_call()`, and
restart. Dynamic tool discovery — the whole point of the architecture — is
untouched by the revision.

The only thing that changes is how you *test* it with curl.

### The `endpoint`/`method` section of the manifest has to go

`CLAUDE.md` documents `endpoint` and `method` fields under "Tools Manifest
Structure". The server stopped sending them at the yr.no switch, and the agent's
`load_tools_from_mcp_server()` is still looking for them — it always logs
"0 endpoint mappings".

That section is to be **removed, not updated.** `2026-07-28` requires the server
to expose exactly one endpoint, so the extension teaches the opposite of the
spec.

### New teaching value

The revision actually gives the workshop some better points than it had:

- **`Origin` and DNS rebinding** are no longer a formality. The workshop runs in
  Codespaces with forwarded ports, so the threat is real and can be demonstrated
  live.
- **Statelessness** is easier to explain once the handshake is gone: look at one
  request and you see everything the server knows.
- **Error code + status code** gives a concrete exercise: send the wrong header,
  watch 400 with `-32020`. Ask for a method that does not exist, watch 404.
- **MRTR** is worth mentioning as the new mental model — the server asks for
  input in a result, the client retries — even though we do not implement it.

### The compliance client has to be rewritten

`services/mcp-sdk-client/test_mcp_sdk.py` prints "FULLY COMPLIANT with MCP
2025-11-25" after two happy-path calls. It does not use the MCP SDK at all, only
`httpx`, and tests neither error codes, status codes nor format requirements.

More importantly: **it will fail the moment the server becomes compliant**,
because it sends none of the required headers. Rewriting it is not optional.

The Python SDK `mcp` **2.0.0** landed on PyPI on 28 July 2026, the same day as
the spec, and supports the revision. `requirements.txt` already carries
`mcp[cli]>=1.2.0` without importing it anywhere. Switching to the SDK gives real
third-party validation instead of a self-written client validating its own
server — and we should let it, not us, pronounce on compliance.

---

## What remains

The order comes from the gap analysis:

| # | Step | Status |
| --- | --- | --- |
| 1 | `mcp_protocol.py`: `_meta`, headers, error codes, status codes | **done** |
| 2 | `server/discover` + capabilities + `serverInfo` | not started |
| 3 | `resultType`, `ttlMs`, `cacheScope` on the existing handlers | not started |
| 4 | The agent: headers + `_meta` + `resultType` tolerance + SSE | not started |
| 5 | `test_mcp_sdk.py` → `mcp>=2.0.0` | not started |
| 6 | Makefile targets and a curl wrapper | not started |
| 7 | Documentation and both presentations | not started |

Step 1 covers findings 2, 3, 5, 6, 7, 8, 9, 11 and 12 of the 25 in the gap
analysis.

> **Note:** the agent cannot talk to the server until step 4 is done. It sends
> neither headers nor `_meta`, so it gets a 400 on every request. The same goes
> for `test_mcp_sdk.py` and every curl example not yet updated. This is baked
> into the ordering — the server becomes compliant first, the clients follow.

---

## References

- [MCP 2026-07-28 — overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/index)
- [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [server/discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)
- [Caching (`ttlMs`, `cacheScope`)](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)
- [Changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
