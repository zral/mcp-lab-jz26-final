# Corrections made during the upgrade to MCP 2026-07-28

A log of concrete errors found and fixed, kept separate from
`doc/mcp-2026-07-28-changes.md` — that document describes *what the revision
changes*, this one describes *what was wrong and got fixed*.

Working note. Consider adding it to `.gitignore` alongside the gap analysis if it
is not meant to be part of the workshop material.

**Last updated:** 2026-08-23, after steps 1–7.

---

## A. Spec violations fixed in the code

All in `services/mcp-server/`. The numbering refers to the findings in
`doc/mcp-2026-07-28-gap.md`.

| Finding | Was | Is now |
| --- | --- | --- |
| 2 | `_meta` was ignored entirely | `protocolVersion` and `clientCapabilities` are validated on every request |
| 3 | Missing `_meta` returned HTTP 200 | HTTP 400 + `-32602` |
| 5 | `MCP-Protocol-Version` was never read | Read and compared against `_meta` |
| 6 | No validation of `Mcp-Method` / `Mcp-Name` | Both validated against the body |
| 7 | Header/body mismatch did not exist as an error | HTTP 400 + `-32020` |
| 8 | An unknown protocol version was not checked | HTTP 400 + `-32022` with `data.supported` |
| 9 | An unknown method returned HTTP 200 | HTTP **404** + `-32601` |
| 11 | `Origin` was never checked | Invalid `Origin` → HTTP 403 |
| 12 | An unknown tool came back as an `isError` result | Protocol error `-32602` |

### Choices made along the way

**The order of validation.** `_meta` is checked before the headers. The spec
defines both as MUSTs, but does not say which should win when both are violated.
We let the body be the truth: a client that forgets `_meta` entirely should be
told "you are missing `_meta`", not "header mismatch" against a value that does
not exist.

**The error code for `Origin`.** The spec requires 403 but defines no JSON-RPC
code. We use `1001` — a positive number, because the new policy says your own
codes belong outside `-32768`–`-32000`. The tempting choice, `-32000`, is now
explicitly legacy.

**Pydantic was taken out of the request path.** `handle_jsonrpc` previously took
a `JSONRPCRequest` model. Pydantic answers 422 in its own error format, which no
MCP client understands and which cannot be mapped to the status codes the spec
requires. The body is now parsed manually. The models `JSONRPCRequest`,
`JSONRPCError` and `JSONRPCResponse` have been removed — nothing referenced them
any more.

---

## B. Errors found along the way, not spec-related

These were there beforehand and had nothing to do with the revision.

### B1. The Dockerfile only copied `app.py` — **fixed**

`services/mcp-server/Dockerfile` had `COPY app.py .`. The new `mcp_protocol.py`
would not have made it into the image, and the container would have crashed on
`import mcp_protocol` at start-up. There is no bind mount in
`docker-compose.yml` for this service, so it would not have been masked locally
either.

Fixed to `COPY app.py mcp_protocol.py ./`.

**Lesson:** if you add more files to `mcp-server` during the workshop, the
Dockerfile has to be updated. Worth a sentence from the stage.

### B2. The module docstring claimed compliance falsely — **fixed**

`app.py` opened with `✅ MCP 2025-11-25 COMPLIANT`. At that point the server was
missing `_meta` handling, status codes and `Origin` validation. The claim was
untrue even before the revision.

Replaced with a list of what is actually implemented and what remains.

The same overclaim exists in `services/mcp-sdk-client/test_mcp_sdk.py`, which
prints `FULLY COMPLIANT with MCP 2025-11-25` after two happy-path calls without
testing either error codes or status codes. **Not yet fixed** — it is to be
rewritten against `mcp>=2.0.0` in step 5.

### B3. Unbalanced `<div>` on slide 18 — **fixed**

The slide opened `<div class="columns">` and two `<div>`s, but closed only two.
Marp tolerates it, so the files rendered — a latent error, not a visible one. It
only became a problem when a new `columns` slide landed right after it.

The presentations have since been consolidated into a single English deck, and it
is balanced. Verify with:

```bash
awk '/^---$/{if(o!=c && n>0) print "slide "n": <div>="o" </div>="c; n++; o=0; c=0; next}
     {o+=gsub(/<div/,"&"); c+=gsub(/<\/div>/,"&")}' doc/ws-pres-cut.md
```

### B4. The agenda numbering skipped — **fixed**

The list went `1, 2, 3, 4, 5, 8, 9, 10`. Items 6 and 7 were missing.

### B5. Outdated fork URL — **fixed**

The presentations sent participants to `github.com/zral/mcp-lab03`, which is the
Booster edition. (The JavaZone edition was `zral/mcp-lab-jz26` at the time; it is
now `zral/mcp-lab-jz26-final`, which is what README and the deck point at.)

This was the error with the largest practical consequence in the room:
participants would have forked the wrong repo and got a workshop that did not
match what was shown from the stage.

### B7. The architecture diagrams — **two of four have factual errors, not fixed**

All four exist as PNGs on Cloudinary. **The source files do not exist in the
repo** — there is no `.mmd`, no Mermaid blocks, nothing. The diagrams appear to
be Mermaid-rendered, but have to be recreated from scratch before they can be
corrected.

Reviewed against the code on 2026-08-23:

| Diagram | Slide | Status |
| --- | --- | --- |
| `overordnet_1_xxnp4q.png` | System Architecture | ❌ wrong weather source |
| `docker-ws_hsahin.png` | Deployment | ✅ correct |
| `oppstart_1_dqqr1a.png` | Data Flow – Startup | ❌ shows dead code |
| `dataflyt_1_p11d46.png` | Data Flow – Request | ❌ wrong weather source + wrong number of calls |

#### `overordnet_1` — System Architecture

- ❌ The box **"OpenWeatherMap API"** should be **yr.no / api.met.no**
  (Locationforecast 2.0). No code references OpenWeatherMap any more —
  `grep -rn "openweather" services/` returns nothing. The neighbouring slides say
  explicitly "weather data is fetched from yr.no — no API key required", so the
  diagram contradicts its own presentation.
- ✅ "Web Service … FastAPI + Jinja2" is **correct**. Note that `CLAUDE.md` is
  wrong here — it describes the web service as Flask, while `services/web/app.py`
  imports `FastAPI` and `Jinja2Templates`. **The diagram is right, CLAUDE.md
  needs fixing.**
- ✅ Ports, JSON-RPC arrows and Nominatim are correct.

#### `docker-ws` — Deployment

No errors found. Service names (`agent-web`, `travel-agent`, `mcp-server`),
ports, internal URLs (`http://mcp-server:8000`) and the volume keys (`logs`,
`agent-data`) all match `docker-compose.yml`.

It omits `datasette` (8090) and `mcp-sdk-client`, but both are optional profiles
— that is a reasonable simplification, not an error.

#### `oppstart_1` — Startup

- ❌ The note **"Store endpoint mappings"** documents `tool_endpoints`, which is
  dead code (see B6). The server has never sent those fields since the yr.no
  switch. It should simply be removed from the diagram.
- ⚠️ Step 4, `POST /message (JSON-RPC tools/list)`, is correct in form but is
  missing `MCP-Protocol-Version` / `Mcp-Method` / `_meta` for `2026-07-28`.
- ⚠️ Step 6, **"Create default session"**, is *not* wrong — it is the agent's
  conversation session in SQLite, not an MCP protocol session. But the word
  "session" becomes confusing now that the revision has removed protocol
  sessions. It should be renamed to "Create conversation session (SQLite)" so
  nobody takes it for the MCP handshake.

#### `dataflyt_1` — Request flow

- ❌ The lifeline **"OpenWeatherMap"** should be **yr.no (api.met.no)**.
- ❌ Step 6 "Fetch current weather" and step 8 "Fetch 5-day forecast" show **two**
  calls to the weather service. The code makes **one**: a single call to
  `locationforecast/2.0/compact`, with both `current` and `forecast` derived from
  the same `timeseries` response (`app.py` has only two `http_client.get` calls
  in total — one Nominatim, one yr.no). The two steps should be merged into one.
- ⚠️ Step 5, `POST /message (JSON-RPC tools/call)`, is missing the headers and
  `_meta`.
- ✅ "Geocode via Nominatim", `structuredContent`, the conversation DB and the
  port numbers are all correct.

**Consequence:** two of the diagrams teach the wrong weather source from the
stage, in a workshop where "yr.no requires no API key" is an explicit point. This
is independent of the protocol upgrade and was already wrong before it started.

### B6. Dead code in the agent — **not fixed**

`tool_endpoints` in `services/agent/app.py` looks for `endpoint` and `method`
fields in the manifest. The server stopped sending them at the yr.no switch, so
the log always says "0 endpoint mappings".

To be deleted in step 4, not revived: `2026-07-28` requires the server to expose
exactly one endpoint. The corresponding section in `CLAUDE.md` ("Tools Manifest
Structure") is to be removed for the same reason.

---

## C. Course corrections during the working session

### C1. `ws-pres-en.md` was edited in place instead of copied

I read "make a new variant" as "update the file", and made 15 targeted changes to
`doc/ws-pres-en.md`. That was wrong — a new file was what was wanted.

Fixed by copying the work product to `doc/ws-pres.md` and running
`git checkout -- doc/ws-pres-en.md`. The original is bit-identical to `HEAD`;
`git diff doc/ws-pres-en.md` is empty.

Nothing was lost, because the file was committed and clean before the edit.

---

## D. Still to be fixed

| # | What | Where | Comes in |
| --- | --- | --- | --- |
| 1 | `server/discover` missing | `mcp-server/app.py` | step 2 |
| 4 | `resultType` missing on all results | `mcp-server/app.py` | step 3 |
| 10 | `ttlMs` / `cacheScope` missing on lists | `mcp-server/app.py` | step 3 |
| 13 | The `tools` capability is not declared | `mcp-server/app.py` | step 2 |
| 14 | `serverInfo` missing from the results' `_meta` | `mcp-server/app.py` | step 2 |
| 15–25 | The entire client side | `agent/app.py` | step 4 |
| B2 | The `FULLY COMPLIANT` overclaim | `mcp-sdk-client/` | step 5 |
| B6 | `tool_endpoints` dead code | `agent/app.py` + `CLAUDE.md` | step 4 |
| B3–B5 | div, agenda, fork URL | `ws-pres.md` (Norwegian) | step 7 |
| B7 | 3 of 4 architecture diagrams | Cloudinary — **no source in the repo** | step 7 |
| B7 | "Flask" should be "FastAPI + Jinja2" | `CLAUDE.md` | any time |

### Known temporary breakage

The agent cannot talk to the server until step 4. It sends neither headers nor
`_meta`, so it gets HTTP 400 on every request. The same goes for
`test_mcp_sdk.py` and every `curl` example that has not been updated.

This is baked into the ordering from the gap analysis — the server becomes
compliant first, the clients follow — but it does mean that `docker compose up`
does not give a working system right now.

---

## Verification

Step 1 is covered by a smoke test with 19 cases: every combination of error code
and status code above, plus the base64 sentinel in `Mcp-Name`, `GET → 405` and an
unchanged `/health`. All 19 pass, and a real `tools/call` against yr.no still
answers correctly.

The test currently lives outside the repo. `pytest` and `pytest-asyncio` are
already in `requirements.txt`, so it can be moved in as
`services/mcp-server/test_mcp_protocol.py` if participants are to run it against
their own changes.

The new presentation builds cleanly:

```bash
make slides
```
