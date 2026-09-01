"""
Protocol tests for MCP 2026-07-28.

These run against the server in-process, with no network and no Docker. They
check the part of the spec that is easy to get subtly wrong: that each kind of
violation produces BOTH the right JSON-RPC error code AND the right HTTP status
code.

    pytest services/mcp-server/

WHY THIS FILE EXISTS
--------------------
The revision pairs error codes with status codes. An unknown method is a 404,
not a 200 with an error in the body. A header that disagrees with the body is a
400 with -32020. Getting the code right while getting the status wrong still
breaks clients, and nothing in ordinary use will tell you.

These are also the cases worth breaking on purpose during the workshop. Every
test here has a matching `make curl-*` target if you would rather watch it
happen over HTTP.

NOTE: no test calls the real weather tool. That would reach yr.no and make the
suite slow and flaky. `test_unknown_tool_is_a_protocol_error` uses a tool name
that does not exist, which is rejected before any network call happens.
"""

import base64

import pytest
from fastapi.testclient import TestClient

import app as server
import mcp_protocol

VERSION = mcp_protocol.PROTOCOL_VERSION

META = {
    mcp_protocol.META_PROTOCOL_VERSION: VERSION,
    mcp_protocol.META_CLIENT_CAPABILITIES: {},
    mcp_protocol.META_CLIENT_INFO: {"name": "pytest", "version": "1.0"},
}


@pytest.fixture
def client():
    # raise_server_exceptions=False so a 500 comes back as a response we can
    # assert on, rather than propagating into the test.
    return TestClient(server.app, raise_server_exceptions=False)


def headers(method, name=None, version=VERSION):
    """The headers a conforming client sends."""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
    }
    if name:
        h["Mcp-Name"] = name
    return h


def body(method, params=None, request_id=1, meta=META):
    params = dict(params or {})
    if meta is not None:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def error_code(response):
    try:
        return response.json().get("error", {}).get("code")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The happy paths
# ---------------------------------------------------------------------------

def test_tools_list_succeeds(client):
    r = client.post("/message", json=body("tools/list"), headers=headers("tools/list"))
    assert r.status_code == 200
    result = r.json()["result"]

    # Assert the weather tool is PRESENT, not that it is the only one.
    # Lab 2 and Lab 3 add tools; a test that pins the exact list would fail
    # the moment a participant does the exercise this workshop is built around.
    names = [t["name"] for t in result["tools"]]
    assert "get_weather_forecast" in names


def test_tools_list_carries_caching_hints(client):
    """A cacheable list result MUST carry resultType, ttlMs and cacheScope."""
    r = client.post("/message", json=body("tools/list"), headers=headers("tools/list"))
    result = r.json()["result"]

    assert result["resultType"] == "complete"
    assert isinstance(result["ttlMs"], int) and result["ttlMs"] >= 0
    assert result["cacheScope"] in ("public", "private")


def test_server_discover(client):
    """server/discover is required in this revision."""
    r = client.post("/message", json=body("server/discover"), headers=headers("server/discover"))
    assert r.status_code == 200

    result = r.json()["result"]
    assert result["resultType"] == "complete"
    assert VERSION in result["supportedVersions"]
    assert "tools" in result["capabilities"]
    assert result["_meta"][mcp_protocol.META_SERVER_INFO]["name"]


def test_tool_schemas_are_valid_json_schema(client):
    r = client.post("/message", json=body("tools/list"), headers=headers("tools/list"))
    for tool in r.json()["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]


# ---------------------------------------------------------------------------
# _meta is required on every request  ->  -32602, HTTP 400
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "meta, description",
    [
        (None, "no _meta at all"),
        ({mcp_protocol.META_CLIENT_CAPABILITIES: {}}, "protocolVersion missing"),
        ({mcp_protocol.META_PROTOCOL_VERSION: VERSION}, "clientCapabilities missing"),
    ],
)
def test_missing_meta_field_is_rejected(client, meta, description):
    r = client.post(
        "/message",
        json=body("tools/list", meta=meta),
        headers=headers("tools/list"),
    )
    assert r.status_code == 400, description
    assert error_code(r) == mcp_protocol.INVALID_PARAMS, description


def test_empty_client_capabilities_is_valid(client):
    """An EMPTY capabilities object means "I have none". That is legal."""
    meta = {
        mcp_protocol.META_PROTOCOL_VERSION: VERSION,
        mcp_protocol.META_CLIENT_CAPABILITIES: {},
    }
    r = client.post("/message", json=body("tools/list", meta=meta), headers=headers("tools/list"))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Headers must mirror the body  ->  -32020, HTTP 400
# ---------------------------------------------------------------------------

def test_mcp_method_header_must_match_body(client):
    r = client.post(
        "/message",
        json=body("tools/list"),
        headers=headers("tools/call"),  # disagrees with the body
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


def test_missing_mcp_method_header(client):
    h = headers("tools/list")
    del h["Mcp-Method"]
    r = client.post("/message", json=body("tools/list"), headers=h)
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


def test_missing_protocol_version_header(client):
    h = headers("tools/list")
    del h["MCP-Protocol-Version"]
    r = client.post("/message", json=body("tools/list"), headers=h)
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


def test_protocol_version_header_must_match_meta(client):
    """Header says one version, _meta says another. The body is the truth."""
    r = client.post(
        "/message",
        json=body("tools/list"),
        headers=headers("tools/list", version="2025-11-25"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


TOOL_CALL_PARAMS = {"name": "get_weather_forecast", "arguments": {"location": "Oslo"}}


def test_tools_call_requires_mcp_name_header(client):
    h = headers("tools/call")  # no Mcp-Name
    r = client.post("/message", json=body("tools/call", TOOL_CALL_PARAMS), headers=h)
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


def test_mcp_name_header_must_match_body(client):
    r = client.post(
        "/message",
        json=body("tools/call", TOOL_CALL_PARAMS),
        headers=headers("tools/call", name="something_else"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.HEADER_MISMATCH


def test_mcp_name_base64_sentinel_is_decoded():
    """
    A tool name with non-ASCII characters is wrapped by the client and MUST be
    decoded before comparison. Without this, any tool named with æ, ø or å would
    be rejected as a header mismatch.
    """
    name = "vær_i_Tromsø"
    encoded = "=?base64?" + base64.b64encode(name.encode()).decode() + "?="
    assert mcp_protocol.decode_header_value(encoded) == name


def test_plain_ascii_header_value_passes_through():
    assert mcp_protocol.decode_header_value("get_weather_forecast") == "get_weather_forecast"


# ---------------------------------------------------------------------------
# Version negotiation  ->  -32022, HTTP 400
# ---------------------------------------------------------------------------

def test_unsupported_version_lists_what_is_supported(client):
    """
    -32022 MUST carry data.supported. Without it a client that guessed wrong has
    no way forward except guessing again.
    """
    old = {
        mcp_protocol.META_PROTOCOL_VERSION: "2025-11-25",
        mcp_protocol.META_CLIENT_CAPABILITIES: {},
    }
    r = client.post(
        "/message",
        json=body("tools/list", meta=old),
        headers=headers("tools/list", version="2025-11-25"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.UNSUPPORTED_PROTOCOL_VERSION

    data = r.json()["error"]["data"]
    assert VERSION in data["supported"]
    assert data["requested"] == "2025-11-25"


# ---------------------------------------------------------------------------
# Routing  ->  404, not 200
# ---------------------------------------------------------------------------

def test_unknown_method_returns_404(client):
    """
    This is the one people get wrong. A 404 WITH a JSON-RPC body is how a client
    tells a modern server from a legacy one that has no MCP endpoint at all.
    """
    r = client.post("/message", json=body("resources/list"), headers=headers("resources/list"))
    assert r.status_code == 404
    assert error_code(r) == mcp_protocol.METHOD_NOT_FOUND


def test_unknown_tool_is_a_protocol_error(client):
    """
    An unknown tool is NOT `isError: true`. That flag means "the tool ran and
    failed", which is a message for the model. A tool that does not exist is the
    client asking for something absent, so it surfaces as a protocol error.
    """
    r = client.post(
        "/message",
        json=body("tools/call", {"name": "no_such_tool", "arguments": {}}),
        headers=headers("tools/call", name="no_such_tool"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.INVALID_PARAMS


@pytest.mark.parametrize("method", ["get", "delete", "put", "patch"])
def test_non_post_verbs_are_rejected(client, method):
    """The previous revision used GET and DELETE. This one does not."""
    r = getattr(client, method)("/message")
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# The JSON-RPC envelope
# ---------------------------------------------------------------------------

def test_malformed_json(client):
    r = client.post(
        "/message",
        content=b"{ not json",
        headers=headers("tools/list"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.PARSE_ERROR


def test_notifications_are_rejected(client):
    """
    No id means a notification. This revision defines no client-to-server
    notifications over Streamable HTTP, so the server cannot accept one.
    """
    payload = body("tools/list")
    del payload["id"]
    r = client.post("/message", json=payload, headers=headers("tools/list"))
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.INVALID_REQUEST


@pytest.mark.parametrize("bad_id", [None, 1.5, [], {}, True])
def test_id_must_be_a_string_or_integer(client, bad_id):
    """The spec is stricter than plain JSON-RPC: no null, no float, no bool."""
    r = client.post(
        "/message",
        json=body("tools/list", request_id=bad_id),
        headers=headers("tools/list"),
    )
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.INVALID_REQUEST


def test_wrong_jsonrpc_version(client):
    payload = body("tools/list")
    payload["jsonrpc"] = "1.0"
    r = client.post("/message", json=payload, headers=headers("tools/list"))
    assert r.status_code == 400
    assert error_code(r) == mcp_protocol.INVALID_REQUEST


# ---------------------------------------------------------------------------
# Origin / DNS rebinding  ->  403
# ---------------------------------------------------------------------------

def test_untrusted_origin_is_forbidden(client):
    h = headers("tools/list")
    h["Origin"] = "https://evil.example.com"
    r = client.post("/message", json=body("tools/list"), headers=h)
    assert r.status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        None,  # curl and server-to-server calls send none. That is fine.
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "https://glorious-space-8000.app.github.dev",  # Codespaces
    ],
)
def test_trusted_origins_are_allowed(origin):
    assert mcp_protocol.is_origin_allowed(origin) is True


def test_absent_origin_is_allowed_by_design():
    """
    The requirement applies when the header IS present. The browser sets Origin,
    and the browser is what the DNS rebinding attack travels through.
    """
    assert mcp_protocol.is_origin_allowed(None) is True


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_needs_no_mcp_headers(client):
    """/health is not an MCP endpoint and must not demand the protocol headers."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
