#!/usr/bin/env python3
"""
Third-party compliance test for MCP 2026-07-28.

This client is deliberately NOT ours. It uses the official `mcp` Python SDK
(2.0.0, reworked for this revision) and talks to the workshop server over the
Streamable HTTP transport. Nothing here shares code with the server.

That distinction matters. The previous version of this file spoke raw httpx
and printed "FULLY COMPLIANT" after two happy-path calls — a client we wrote
ourselves, validating our own server, against our own understanding of the
spec. If we had misread the spec, both sides would have been wrong together
and the test would still have passed.

The SDK cannot be talked into agreeing with us. If it negotiates a version,
reads our capabilities and parses our results, that is evidence.

WHAT THIS DOES AND DOES NOT PROVE
---------------------------------
It exercises the paths a normal client takes, plus a handful of protocol
violations the SDK will not produce on its own (those go over raw httpx).

It is not a conformance suite. It does not cover SSE responses, MRTR,
subscriptions, pagination or authorization. Passing means "no problems found
in what was checked", which is a weaker claim than "compliant" — and the
weaker claim is the honest one.

Usage:
    python test_mcp_sdk.py

Environment:
    MCP_SERVER_URL   default http://mcp-server:8000
"""

import asyncio
import os
import sys

import httpx
from mcp import Client, MCPError

PROTOCOL_VERSION = "2026-07-28"

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

BASE_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000")
ENDPOINT = f"{BASE_URL}/message"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((PASS if ok else FAIL, name, detail))
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# Part 1: the official SDK, doing what a normal client does
# ---------------------------------------------------------------------------

async def check_with_sdk() -> None:
    print("\n1. Official mcp SDK over Streamable HTTP")
    print("-" * 70)

    async with Client(ENDPOINT) as client:
        # The SDK discovers the server before doing anything else. If our
        # server/discover is wrong, we never get this far.
        record(
            "negotiated protocol version",
            client.protocol_version == PROTOCOL_VERSION,
            f"got {client.protocol_version!r}",
        )

        info = client.server_info
        record(
            "server identified itself",
            info is not None and bool(info.name),
            f"{info.name} {info.version}" if info else "missing serverInfo",
        )

        caps = client.server_capabilities
        record(
            "declared a tools capability",
            caps is not None and caps.tools is not None,
            "tools capability present",
        )

        record(
            "returned instructions",
            bool(client.instructions),
            f"{len(client.instructions or '')} chars",
        )

        # --- tools/list -----------------------------------------------------
        listing = await client.list_tools()

        record(
            "tools/list carries resultType",
            listing.result_type == "complete",
            f"resultType={listing.result_type!r}",
        )
        record(
            "tools/list carries a valid ttlMs",
            isinstance(listing.ttl_ms, int) and listing.ttl_ms >= 0,
            f"ttlMs={listing.ttl_ms}",
        )
        record(
            "tools/list carries a cacheScope",
            listing.cache_scope in ("public", "private"),
            f"cacheScope={listing.cache_scope!r}",
        )

        names = [t.name for t in listing.tools]
        record("tools/list returned tools", bool(names), ", ".join(names))

        schemas_ok = all(
            t.input_schema and t.input_schema.get("type") == "object"
            for t in listing.tools
        )
        record("every tool has an object inputSchema", schemas_ok)

        if not names:
            return

        # --- tools/call -----------------------------------------------------
        tool = names[0]
        result = await client.call_tool(tool, {"location": "Oslo"})

        record(
            "tools/call carries resultType",
            result.result_type == "complete",
            f"resultType={result.result_type!r}",
        )
        record("tools/call reported no error", result.is_error is False)
        record(
            "tools/call returned content",
            bool(result.content),
            f"{len(result.content)} block(s)",
        )

        structured = result.structured_content
        record(
            "tools/call returned structuredContent",
            isinstance(structured, dict) and "current" in structured,
            f"Oslo: {structured['current']['temperature']}°C, "
            f"{structured['current']['description']}"
            if isinstance(structured, dict) and "current" in structured
            else "missing",
        )

        # --- an error the SDK surfaces --------------------------------------
        try:
            await client.call_tool("no_such_tool", {})
            record("unknown tool raised a protocol error", False, "no error raised")
        except MCPError as exc:
            record("unknown tool raised a protocol error", True, str(exc)[:50])


# ---------------------------------------------------------------------------
# Part 2: protocol violations, over raw httpx
#
# The SDK will not build a malformed request for us — that is rather the
# point of an SDK. To check that the server rejects what it must reject, we
# have to be rude by hand.
# ---------------------------------------------------------------------------

def meta() -> dict:
    return {
        META_PROTOCOL_VERSION: PROTOCOL_VERSION,
        META_CLIENT_CAPABILITIES: {},
    }


async def check_rejections() -> None:
    print("\n2. Protocol violations, sent by hand")
    print("-" * 70)

    cases = [
        (
            "missing _meta → 400 / -32602",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/list"},
            400, -32602,
        ),
        (
            "Mcp-Method disagrees with body → 400 / -32020",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": meta()}},
            {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/call"},
            400, -32020,
        ),
        (
            "missing MCP-Protocol-Version → 400 / -32020",
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"_meta": meta()}},
            {"Mcp-Method": "tools/list"},
            400, -32020,
        ),
        (
            "unsupported version → 400 / -32022",
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list",
             "params": {"_meta": {META_PROTOCOL_VERSION: "2025-11-25",
                                  META_CLIENT_CAPABILITIES: {}}}},
            {"MCP-Protocol-Version": "2025-11-25", "Mcp-Method": "tools/list"},
            400, -32022,
        ),
        (
            "unknown method → 404 / -32601",
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list", "params": {"_meta": meta()}},
            {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "resources/list"},
            404, -32601,
        ),
    ]

    async with httpx.AsyncClient(timeout=20) as http:
        for name, body, headers, want_status, want_code in cases:
            headers = {"Content-Type": "application/json", **headers}
            r = await http.post(ENDPOINT, json=body, headers=headers)
            try:
                code = r.json().get("error", {}).get("code")
            except Exception:
                code = None
            record(
                name,
                r.status_code == want_status and code == want_code,
                f"got {r.status_code} / {code}",
            )

        # -32022 must tell the client what to retry with. Without this a
        # client has no way forward except guessing.
        r = await http.post(
            ENDPOINT,
            json={"jsonrpc": "2.0", "id": 6, "method": "tools/list",
                  "params": {"_meta": {META_PROTOCOL_VERSION: "1999-01-01",
                                       META_CLIENT_CAPABILITIES: {}}}},
            headers={"Content-Type": "application/json",
                     "MCP-Protocol-Version": "1999-01-01",
                     "Mcp-Method": "tools/list"},
        )
        supported = r.json().get("error", {}).get("data", {}).get("supported")
        record(
            "-32022 lists supported versions",
            isinstance(supported, list) and PROTOCOL_VERSION in supported,
            f"supported={supported}",
        )

        # DNS rebinding protection.
        r = await http.post(
            ENDPOINT,
            json={"jsonrpc": "2.0", "id": 7, "method": "tools/list",
                  "params": {"_meta": meta()}},
            headers={"Content-Type": "application/json",
                     "MCP-Protocol-Version": PROTOCOL_VERSION,
                     "Mcp-Method": "tools/list",
                     "Origin": "https://evil.example.com"},
        )
        record("untrusted Origin → 403", r.status_code == 403, f"got {r.status_code}")

        # Legacy verbs from the previous revision.
        r = await http.get(ENDPOINT)
        record("GET on the MCP endpoint → 405", r.status_code == 405, f"got {r.status_code}")


# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 70)
    print(f"MCP {PROTOCOL_VERSION} — third-party check via the official SDK")
    print("=" * 70)
    print(f"\nServer: {ENDPOINT}")

    try:
        await check_with_sdk()
        await check_rejections()
    except Exception as exc:
        print(f"\n✗ Aborted: {type(exc).__name__}: {exc}")
        return 2

    failed = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 70)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")

    if failed:
        print("\nFailures:")
        for _, name, detail in failed:
            print(f"  ✗ {name}  — {detail}")
        return 1

    # Deliberately not the word "compliant". See the module docstring.
    print("\nNo problems found in what was checked.")
    print("Not covered: SSE responses, MRTR, subscriptions, pagination, authorization.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
