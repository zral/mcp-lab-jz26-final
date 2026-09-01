# Lab 3 — A news tool against a real API

The first two labs called nothing, or called something that could not fail. This
one talks to a third party over the network, so it has failure modes the earlier
labs did not have. That is the point of it.

**The solution is in `helper/lab3-solution.md`, ROT13-encoded** so you do not
stumble into it while looking for something else. Decode it when you want it:

```bash
tr 'A-Za-z' 'N-ZA-Mn-za-m' < helper/lab3-solution.md
```

Try it yourself first — the four traps below are the whole value of this lab.

## What you are building

A tool called `get_news` that returns recent headlines about a topic.

Everything happens in `services/mcp-server/app.py`. **The agent needs no
changes** — it discovers the tool from the manifest, which is the whole idea.

## The source

Google News publishes RSS for any search query. No key, no signup, no account:

```
https://news.google.com/rss/search?q=oslo+travel&hl=en&gl=US&ceid=US:en
```

- `q` — the search query
- `hl` — interface language, `gl` — country, `ceid` — the two combined, `gl:hl`

Try it in a browser first. You will get **XML**, not JSON.

That is deliberate. Every other tool in this workshop calls a JSON API, and it
is easy to come away thinking MCP is a JSON-to-JSON pipe. It is not. The MCP
envelope — `content`, `structuredContent`, `isError` — is yours to build no
matter what the upstream speaks.

`xml.etree.ElementTree` in the standard library is all you need. The feed has no
namespaces: `item` elements carry `title`, `link`, `pubDate` and `source`
directly.

## Requirements

**The tool function** returns plain data, with an `error` key on failure. It
never builds an MCP result — that shape belongs in the routing branch, which
keeps the tool testable without the protocol.

1. Take a `topic`, and optionally a `language`
2. Set a timeout on the outbound call
3. `follow_redirects=True` — `httpx` does **not** follow redirects by default
4. Return at most five articles: title, url, source, published

**The manifest entry** in `handle_tools_list()` needs `name`, `title`,
`description`, `inputSchema` and `outputSchema`. Use an `enum` for the languages
you support.

**The routing branch** in `handle_tools_call()` wraps the result:
`resultType: "complete"` on **every** return path, including the error ones.

## Four things that will bite you

**Redirects.** `httpx` returns the 3xx rather than following it. You get an
empty body and no error.

**A 200 that is not XML.** Google can answer with a consent page. `ET.fromstring`
raises `ParseError`, and it needs its own `except` — it is not an `HTTPError`.

**Dates are not localised, but the text is.** `pubDate` is RFC-822:
`Fri, 28 Aug 2026 08:55:25 GMT`. Fetch the Norwegian feed and the headlines are
Norwegian — the date still says `Fri` and `Aug`, because RFC-822 mandates English
abbreviations.

So this breaks:

```python
datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z")     # do NOT do this
```

`%a` and `%b` follow the process locale. On a machine set to `nb_NO` it expects
`fre` and `aug`, gets `Fri` and `Aug`, and raises `ValueError` — on a Norwegian
laptop, against a Norwegian feed. It passes CI and fails on stage.

Use `email.utils.parsedate_to_datetime`, which implements RFC-822 properly and
ignores the locale. Normalise to ISO-8601 on the way out, so every consumer gets
one unambiguous format. A tool that forwards whatever the upstream said has
moved the problem to its caller.

**Zero results is not an error.** A search that matched nothing is a tool that
*worked*: `count: 0`, `isError: false`. Flag it as an error and you tell the
model to retry a call that was fine — and it will, repeatedly.

`isError: true` means the tool ran and failed, and the message is for the model.
A tool that does not exist is something else entirely: a protocol error,
`-32602` with HTTP 400.

## Testing

```bash
docker compose up -d --build mcp-server travel-agent

make curl-list         # three tools now
make curl-news         # call get_news
make curl-news-agent   # the same, through the agent
```

By hand, with the required headers set for you:

```bash
./helper/mcp-curl tools/call '{"name":"get_news","arguments":{"topic":"Oslo travel"}}'
```

Then try to break it: a topic that matches nothing, a language you did not
declare, and no `topic` at all. Each should behave differently.

## Checklist

- [ ] No API key anywhere — the source is open
- [ ] Timeout on the outbound call
- [ ] `follow_redirects=True`
- [ ] `raise_for_status()` so HTTP failures are caught
- [ ] `ET.ParseError` handled separately from `httpx.HTTPError`
- [ ] Dates normalised to ISO-8601, locale-independently
- [ ] Zero results returned as a success, not `isError`
- [ ] `resultType: "complete"` on every return path
- [ ] Both a readable `content` and a machine-readable `structuredContent`
- [ ] Registered in `handle_tools_list()` and routed in `handle_tools_call()`
- [ ] No agent code changed
