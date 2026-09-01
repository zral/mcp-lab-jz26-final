# Lab 2 — Add a tool the agent has never heard of

The weather tool was there when you cloned this. This one is yours, and the point
is what you *do not* have to touch to make it work.

**The solution is in `helper/lab2-solution.md`, ROT13-encoded** so you do not
stumble into it while looking for something else. Decode it when you want it:

```bash
tr 'A-Za-z' 'N-ZA-Mn-za-m' < helper/lab2-solution.md
```

Try it yourself first — it is a short lab.

## What you are building

A tool called `get_random_fact` that returns a random fact, by category.

Everything happens in `services/mcp-server/app.py`. **The agent needs no
changes** — it asks the server what exists at start-up, so a tool you add on the
server appears in the agent without a line of agent code. That claim is the whole
architecture, and this lab is where you test it rather than take it on faith.

There is no upstream API here. The facts are a dict in your own code. That is
deliberate: lab 3 adds a real network call and the failure modes that come with
it, and it is easier to learn one thing at a time.

## The three places you touch

**1. The tool function.** Takes a `category`, returns plain data — the category,
the fact, and a timestamp. On failure it returns something with an `error` key.

It does **not** build an MCP result. That shape belongs in the routing branch, so
the function stays testable without the protocol wrapped around it.

**2. The manifest entry** in `handle_tools_list()`: `name`, `title`,
`description`, `inputSchema` and `outputSchema`. Use JSON Schema 2020-12, and an
`enum` for the categories you actually support.

There is **no** `endpoint` or `method` field, and there must not be. MCP
`2026-07-28` requires the server to expose exactly one endpoint, so there is
nothing to route and nothing to declare.

**3. The routing branch** in `handle_tools_call()`, which wraps the plain data in
the MCP envelope.

## Two things that will bite you

**`resultType` is required on every result** in this revision — including the
error paths. Miss it on the branch you only hit when something fails, and you
have a bug that passes every test you thought to write.

`tools/call` results are **not** cacheable, so they carry no `ttlMs` or
`cacheScope`. `tools/list` results do. Do not copy one shape into the other.

**`isError: true` is not a protocol error.** It means the tool ran and failed —
an unknown category, a timeout. That message is for the *model*, which can retry
with different arguments.

A tool that does not exist is something else entirely: a protocol error,
`-32602` with HTTP `400`. That is the *client* asking for something absent, and
the right response is to re-fetch `tools/list`. Conflating the two is the classic
mistake, and you will see the distinction again in lab 3.

## Testing

```bash
docker compose up -d --build mcp-server travel-agent

make curl-list         # two tools now, where there was one
make curl-fact         # call get_random_fact directly
make curl-fact-agent   # the same, through the agent
```

By hand, with the four required headers set for you:

```bash
./helper/mcp-curl tools/call '{"name":"get_random_fact","arguments":{"category":"space"}}'
```

Watch the agent log while it starts. It should say it loaded **two** tools.

## Checklist

- [ ] JSON-RPC 2.0 over the single `/message` endpoint
- [ ] `inputSchema` using JSON Schema 2020-12
- [ ] `outputSchema` for the response shape
- [ ] No `endpoint` or `method` field in the manifest entry
- [ ] `resultType: "complete"` on every return path, errors included
- [ ] Failures returned with `isError: true`, not as a protocol error
- [ ] Registered in `handle_tools_list()` and routed in `handle_tools_call()`
- [ ] No agent code changed

## When it works

`make curl-fact` returns your fact. `make curl-list` shows two tools. The agent
log says two tools loaded.

Now ask the agent for a fact through the web UI at http://localhost:8080 and see
what happens.
