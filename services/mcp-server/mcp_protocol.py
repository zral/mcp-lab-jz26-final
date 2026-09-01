#!/usr/bin/env python3
"""
MCP protocol layer for specification 2026-07-28.

============================================================================
WORKSHOP NOTE: why does this file exist?
============================================================================

In MCP 2025-11-25 a client opened with `initialize`, got a session, and the
server remembered protocol version and capabilities for the rest of it.

2026-07-28 removed all of that. The spec says so outright:

    "The Model Context Protocol (MCP) is a stateless protocol: all the
     information needed to process a request is contained in the request
     itself."

The consequence: *every single request* has to carry the protocol version
and client capabilities itself, in `params._meta`, and mirror selected
fields into HTTP headers so intermediaries (load balancers, gateways,
observability tooling) can route and inspect without parsing the body.

This module is the doorman: it checks that a request actually carries what
it must, and turns any violation into the right JSON-RPC error code *and*
the right HTTP status code. The spec makes both a MUST.

References:
- https://modelcontextprotocol.io/specification/2026-07-28/basic/index
- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
============================================================================
"""

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Protocol versions
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "2026-07-28"

# Versions this server actually implements, newest first.
# We deliberately support ONLY 2026-07-28: the workshop is about the new
# model, not backwards-compatibility acrobatics.
SUPPORTED_VERSIONS: List[str] = [PROTOCOL_VERSION]

SERVER_INFO: Dict[str, str] = {
    "name": "mcp-travel-weather",
    "version": "2.0.0",
}

# ---------------------------------------------------------------------------
# Reserved _meta keys (spec: "Per-request protocol fields")
#
# The `io.modelcontextprotocol/` prefix is reserved for MCP itself. Your own
# fields belong under reverse-DNS with your own domain, e.g. `no.javazone/`.
# ---------------------------------------------------------------------------

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# ---------------------------------------------------------------------------
# Error codes
#
# JSON-RPC 2.0 reserves -32000..-32099 for implementation-defined errors.
# MCP 2026-07-28 partitions that range:
#
#   -32000..-32019  LEGACY. Do not adopt. No defined meaning.
#   -32020..-32099  Reserved for the spec. Use ONLY codes the spec defines,
#                   and only with the meaning the spec gives them.
#
# Errors the spec does not cover must live OUTSIDE -32768..-32000.
# That is why ORIGIN_NOT_ALLOWED is a positive number (see below).
# ---------------------------------------------------------------------------

# Standard JSON-RPC 2.0
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Defined by MCP 2026-07-28
HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022

# Application-defined (outside the JSON-RPC reserved range, as the spec requires)
ORIGIN_NOT_ALLOWED = 1001

# ---------------------------------------------------------------------------
# Header mirroring
#
# The spec table "Standard Request Headers":
#
#   Header                 Source in the body          Required for
#   ---------------------  --------------------------  ---------------------------
#   MCP-Protocol-Version   _meta[.../protocolVersion]  all requests
#   Mcp-Method             method                      all requests
#   Mcp-Name               params.name / params.uri    tools/call, resources/read,
#                                                      prompts/get
# ---------------------------------------------------------------------------

# Methods that MUST carry Mcp-Name, and which params field it mirrors.
NAME_HEADER_METHODS: Dict[str, str] = {
    "tools/call": "name",
    "resources/read": "uri",
    "prompts/get": "name",
}

# Base64 sentinel for header values that cannot be expressed as plain ASCII
# ("Bergen, Vestland" is fine; "Tromsø" is not).
_B64_PREFIX = "=?base64?"
_B64_SUFFIX = "?="


class ProtocolError(Exception):
    """
    A protocol violation that becomes BOTH a JSON-RPC error and an HTTP status.

    Pairing the two is new in 2026-07-28 and the whole point of this class: a
    client must be able to tell "a modern server said no" (400 with a JSON-RPC
    body) from "there is no MCP server here" (a bare 404), without guessing.
    """

    def __init__(
        self,
        code: int,
        message: str,
        http_status: int,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data

    def to_response(self, request_id: Any = None) -> JSONResponse:
        """Build a JSON-RPC error response with the right HTTP status code."""
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data

        body: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "error": error}
        return JSONResponse(status_code=self.http_status, content=body)


@dataclass
class ValidatedRequest:
    """A request that has passed every protocol check."""

    id: Any
    method: str
    params: Dict[str, Any]
    protocol_version: str
    client_capabilities: Dict[str, Any]
    client_info: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Origin validation
# ---------------------------------------------------------------------------

def _allowed_origin_patterns() -> List[str]:
    """
    Read the allowed origins from the environment.

    `MCP_ALLOWED_ORIGINS` is comma-separated. A value of `*` disables the check
    entirely - handy when debugging, but you lose the protection with it.
    """
    raw = os.getenv("MCP_ALLOWED_ORIGINS", "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


# Hostnames that are always fine: local development, plus the forwarded
# ports Codespaces uses (the workshop runs there).
_DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
_DEFAULT_ALLOWED_SUFFIXES = (".app.github.dev", ".github.dev")


def is_origin_allowed(origin: Optional[str]) -> bool:
    """
    Is this `Origin` header acceptable?

    The spec: "Servers MUST validate the Origin header on all incoming
    connections to prevent DNS rebinding attacks."

    Note that the requirement applies when the header IS present.
    Server-to-server calls (the agent, curl) send no Origin and must not be
    rejected for it. The browser is what sets Origin, and the browser is what
    the attack travels through.
    """
    if origin is None:
        return True

    patterns = _allowed_origin_patterns()
    if "*" in patterns:
        return True
    if origin in patterns:
        return True

    hostname = urlparse(origin).hostname
    if hostname is None:
        return False
    if hostname in _DEFAULT_ALLOWED_HOSTS:
        return True
    return any(hostname.endswith(suffix) for suffix in _DEFAULT_ALLOWED_SUFFIXES)


def validate_origin(origin: Optional[str]) -> None:
    """Raise ProtocolError (HTTP 403) if Origin is present and untrusted."""
    if not is_origin_allowed(origin):
        raise ProtocolError(
            code=ORIGIN_NOT_ALLOWED,
            message=f"Origin not allowed: {origin}",
            http_status=403,
        )


# ---------------------------------------------------------------------------
# Header values
# ---------------------------------------------------------------------------

def decode_header_value(value: str) -> str:
    """
    Decode a header value that may be base64-wrapped.

    HTTP headers only carry visible ASCII, so a client wraps values that are
    not ASCII-safe:

        Mcp-Name: =?base64?VHJvbXPDuA==?=

    The markers are case-sensitive and MUST look exactly like that. The server
    MUST decode before comparing against the body - otherwise any tool name
    containing æ, ø or å would be rejected as a header mismatch.
    """
    if not (value.startswith(_B64_PREFIX) and value.endswith(_B64_SUFFIX)):
        return value

    payload = value[len(_B64_PREFIX):-len(_B64_SUFFIX)]
    try:
        return base64.b64decode(payload, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ProtocolError(
            code=HEADER_MISMATCH,
            message=f"Header mismatch: malformed base64 header value: {exc}",
            http_status=400,
        ) from exc


# ---------------------------------------------------------------------------
# The main validation
# ---------------------------------------------------------------------------

def _require_meta(params: Dict[str, Any]) -> Dict[str, Any]:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        raise ProtocolError(
            code=INVALID_PARAMS,
            message="Invalid params: params._meta is required on every request",
            http_status=400,
            data={"required": [META_PROTOCOL_VERSION, META_CLIENT_CAPABILITIES]},
        )
    return meta


def validate_request(
    *,
    method: str,
    params: Optional[Dict[str, Any]],
    headers: Any,
    request_id: Any,
) -> ValidatedRequest:
    """
    Validate an incoming MCP request against 2026-07-28.

    `headers` must be a case-insensitive mapping (Starlette's `request.headers`
    is exactly that).

    THE ORDER IS DELIBERATE, and worth understanding:

      1. the `_meta` fields        -> -32602, HTTP 400
      2. headers mirror the body  -> -32020, HTTP 400
      3. the version is supported -> -32022, HTTP 400

    The body is the truth; the headers are mirrors for intermediaries. So we
    check first that the body is complete (if it is not, the request is
    malformed whatever the headers say), then that the headers agree with it,
    and last whether we actually speak the version the client asked for.

    Swap 1 and 2 and the errors become useless: a client that forgot `_meta`
    entirely would be told "header mismatch" against a value that does not
    exist, instead of "you are missing _meta".

    Raises:
        ProtocolError: on any violation. The caller turns it into a response.
    """
    params = params if isinstance(params, dict) else {}

    # --- Step 1: the required _meta fields --------------------------------
    meta = _require_meta(params)

    protocol_version = meta.get(META_PROTOCOL_VERSION)
    if not isinstance(protocol_version, str) or not protocol_version:
        raise ProtocolError(
            code=INVALID_PARAMS,
            message=f"Invalid params: _meta['{META_PROTOCOL_VERSION}'] is required",
            http_status=400,
            data={"required": [META_PROTOCOL_VERSION]},
        )

    client_capabilities = meta.get(META_CLIENT_CAPABILITIES)
    if not isinstance(client_capabilities, dict):
        # Note: an EMPTY object is valid - it means "I have no capabilities".
        # It is the absence of the key that is the error.
        raise ProtocolError(
            code=INVALID_PARAMS,
            message=f"Invalid params: _meta['{META_CLIENT_CAPABILITIES}'] is required",
            http_status=400,
            data={"required": [META_CLIENT_CAPABILITIES]},
        )

    raw_client_info = meta.get(META_CLIENT_INFO)
    client_info = raw_client_info if isinstance(raw_client_info, dict) else None

    # --- Step 2: the headers must mirror the body -------------------------
    _validate_mirrored_headers(
        method=method,
        params=params,
        headers=headers,
        protocol_version=protocol_version,
    )

    # --- Step 3: do we support the version? -------------------------------
    if protocol_version not in SUPPORTED_VERSIONS:
        raise ProtocolError(
            code=UNSUPPORTED_PROTOCOL_VERSION,
            message=f"Unsupported protocol version: {protocol_version}",
            http_status=400,
            data={"supported": SUPPORTED_VERSIONS, "requested": protocol_version},
        )

    return ValidatedRequest(
        id=request_id,
        method=method,
        params=params,
        protocol_version=protocol_version,
        client_capabilities=client_capabilities,
        client_info=client_info,
    )


def _header_mismatch(message: str) -> ProtocolError:
    return ProtocolError(
        code=HEADER_MISMATCH,
        message=f"Header mismatch: {message}",
        http_status=400,
    )


def _validate_mirrored_headers(
    *,
    method: str,
    params: Dict[str, Any],
    headers: Any,
    protocol_version: str,
) -> None:
    """
    Check that MCP-Protocol-Version, Mcp-Method and Mcp-Name match the body.

    Why care? Because an intermediary may route on the header while the server
    executes what the body says. When those disagree you have an attack
    surface: a gateway waving through `Mcp-Name: read_document` while the body
    says `delete_everything`. The spec therefore requires a 400.
    """
    header_version = headers.get("mcp-protocol-version")
    if header_version is None:
        raise _header_mismatch("required header 'MCP-Protocol-Version' is missing")
    if header_version != protocol_version:
        raise _header_mismatch(
            f"MCP-Protocol-Version header value '{header_version}' does not match "
            f"body value '{protocol_version}'"
        )

    header_method = headers.get("mcp-method")
    if header_method is None:
        raise _header_mismatch("required header 'Mcp-Method' is missing")
    if header_method != method:
        raise _header_mismatch(
            f"Mcp-Method header value '{header_method}' does not match "
            f"body value '{method}'"
        )

    name_field = NAME_HEADER_METHODS.get(method)
    if name_field is None:
        # Methods with no name parameter (tools/list, server/discover) must
        # not carry Mcp-Name at all.
        return

    body_name = params.get(name_field)
    if body_name is None:
        # The body is missing the parameter itself. That is invalid params,
        # not a header mismatch.
        raise ProtocolError(
            code=INVALID_PARAMS,
            message=f"Invalid params: '{name_field}' is required for {method}",
            http_status=400,
        )

    header_name = headers.get("mcp-name")
    if header_name is None:
        raise _header_mismatch(f"required header 'Mcp-Name' is missing for {method}")

    decoded_name = decode_header_value(header_name)
    if decoded_name != str(body_name):
        raise _header_mismatch(
            f"Mcp-Name header value '{decoded_name}' does not match "
            f"body value '{body_name}'"
        )

    # NOTE: the `Mcp-Param-{Name}` headers (from `x-mcp-header` in a tool's
    # inputSchema) are not validated here, because no tool in this repo
    # annotates parameters with `x-mcp-header`. If you add one that does,
    # you MUST validate those headers against `arguments` too - same rule,
    # same -32020.


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def method_not_found(method: str, supported: List[str]) -> ProtocolError:
    """
    Unknown method -> HTTP 404, not 200.

    This surprises people. The reason is backwards compatibility: a client that
    hits a 404 must be able to distinguish "modern server, unknown method"
    (404 WITH a JSON-RPC body carrying -32601) from "a legacy HTTP+SSE server
    that does not host this endpoint at all" (404 without such a body).
    Without the status code the two are indistinguishable.
    """
    return ProtocolError(
        code=METHOD_NOT_FOUND,
        message=f"Method not found: {method}",
        http_status=404,
        data={"supported": supported},
    )
