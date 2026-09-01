#!/usr/bin/env python3
"""
MCP API Server - JSON-RPC 2.0 over Streamable HTTP

MCP-compliant HTTP server with JSON-RPC 2.0 protocol.
Participants can extend this with their own tools.

MCP 2026-07-28:
===============
This server implements the official MCP Streamable HTTP transport:
- JSON-RPC 2.0 message protocol
- POST /message endpoint for all operations (the MCP endpoint)
- server/discover for versions, capabilities and identity
- tools/list for tool discovery, tools/call for execution
- Per-request `_meta` and mirrored HTTP headers (see mcp_protocol.py)
- Spec-mandated pairing of JSON-RPC error codes and HTTP status codes
- `resultType` on every result, `ttlMs` / `cacheScope` on cacheable ones

Why JSON-RPC?:
- Standard protocol (not custom)
- Production-ready and spec-compliant
- Same complexity as REST but more powerful

Note: since 2026-07-28, curl is no longer "just send JSON". Every request
needs four headers and a `_meta` block. That is the price the protocol paid
to become stateless. Use the `make curl-*` targets.

For MCP specification, see: https://modelcontextprotocol.io/specification/2026-07-28
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import mcp_protocol
from mcp_protocol import ProtocolError

# Logging
def _setup_logging(log_file: str) -> logging.Logger:
    """
    Log to stdout AND to a file, without a shell pipeline.

    The compose files used to run `sh -c "python app.py | tee /app/logs/x.log"`.
    That made /bin/sh PID 1, and sh does not forward SIGTERM to its children --
    so Python never saw the signal, uvicorn never shut down gracefully, and the
    lifespan shutdown below never ran. Doing the tee in Python instead lets the
    process be PID 1 and receive signals directly.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file))
    except OSError:
        # No log directory -- running outside Docker. stdout is enough.
        pass

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(__name__)


logger = _setup_logging(os.getenv("LOG_FILE", "/app/logs/mcp-server.log"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start-up and shutdown, as a single context manager.

    Everything before `yield` runs at start-up, everything after at shutdown.
    This replaces @app.on_event("startup") / ("shutdown"), which FastAPI
    deprecated: two separate hooks could not share state, so anything opened at
    start-up had to live in a module global just to be closable later.
    """
    logger.info("Starting MCP API Server...")
    yield
    await http_client.aclose()
    logger.info("MCP API Server stopped")


# FastAPI app
app = FastAPI(
    title="MCP Travel Weather Server",
    description="MCP 2026-07-28 server for the workshop - weather tools only",
    version="2.0.0",
    lifespan=lifespan,
)

# Upstream API constants
YR_API_BASE = "https://api.met.no/weatherapi/locationforecast/2.0"
YR_USER_AGENT = "IngridReisetjenester/1.0 (workshop-booster26)"
NOMINATIM_API_BASE = "https://nominatim.openstreetmap.org"

# Maps yr.no symbol_code values to human-readable descriptions
SYMBOL_CODE_MAP = {
    "clearsky": "clear sky",
    "fair": "fair",
    "partlycloudy": "partly cloudy",
    "cloudy": "cloudy",
    "lightrainshowers": "light rain showers",
    "rainshowers": "rain showers",
    "heavyrainshowers": "heavy rain showers",
    "lightrainshowersandthunder": "light rain showers and thunder",
    "rainshowersandthunder": "rain showers and thunder",
    "heavyrainshowersandthunder": "heavy rain showers and thunder",
    "lightsleetshowers": "light sleet showers",
    "sleetshowers": "sleet showers",
    "heavysleetshowers": "heavy sleet showers",
    "lightsnowshowers": "light snow showers",
    "snowshowers": "snow showers",
    "heavysnowshowers": "heavy snow showers",
    "lightrain": "light rain",
    "rain": "rain",
    "heavyrain": "heavy rain",
    "lightrainandthunder": "light rain and thunder",
    "rainandthunder": "rain and thunder",
    "heavyrainandthunder": "heavy rain and thunder",
    "lightsleet": "light sleet",
    "sleet": "sleet",
    "heavysleet": "heavy sleet",
    "lightsnow": "light snow",
    "snow": "snow",
    "heavysnow": "heavy snow",
    "fog": "fog",
}

# HTTP client
http_client = httpx.AsyncClient()

# Request/response models

# JSON-RPC 2.0 models
#
# NOTE: the request is NOT parsed with Pydantic any more. MCP 2026-07-28
# requires specific HTTP status codes (400/403/404) and specific JSON-RPC
# error codes per violation. Pydantic would answer 422 in its own error
# format, which no MCP client understands. So we parse the body ourselves in
# handle_jsonrpc() and let mcp_protocol.py decide both code and status.

def jsonrpc_result(request_id: Any, result: Dict[str, Any]) -> JSONResponse:
    """Build a JSON-RPC 2.0 success response (HTTP 200)."""
    return JSONResponse(
        status_code=200,
        content={"jsonrpc": "2.0", "id": request_id, "result": result},
    )

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    timestamp: str

def translate_symbol_code(symbol_code: str) -> str:
    """Translate a yr.no symbol_code into a readable description."""
    # Strip the _day/_night/_polartwilight suffix
    base = symbol_code.split("_")[0] if "_" in symbol_code else symbol_code
    return SYMBOL_CODE_MAP.get(base, symbol_code)


async def geocode_location(location: str) -> Optional[Dict[str, float]]:
    """Geocode a place name into coordinates."""
    try:
        params = {
            "q": location,
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        }

        response = await http_client.get(
            f"{NOMINATIM_API_BASE}/search",
            params=params,
            headers={"User-Agent": YR_USER_AGENT}
        )
        response.raise_for_status()

        data = response.json()
        if not data:
            return None

        result = data[0]
        return {
            "lat": float(result["lat"]),
            "lon": float(result["lon"])
        }

    except Exception as e:
        logger.error(f"Geocoding error: {e}")
        return None

async def get_weather_forecast(location: str) -> Dict[str, Any]:
    """Fetch a forecast for a destination from yr.no (api.met.no)."""
    try:
        # Geocode the location
        coords = await geocode_location(location)
        if not coords:
            return {"error": f"Could not find location: {location}"}

        # Fetch the yr.no forecast
        yr_url = f"{YR_API_BASE}/compact"
        yr_params = {
            "lat": round(coords["lat"], 4),
            "lon": round(coords["lon"], 4),
        }
        yr_headers = {"User-Agent": YR_USER_AGENT}

        response = await http_client.get(yr_url, params=yr_params, headers=yr_headers)
        response.raise_for_status()
        yr_data = response.json()

        timeseries = yr_data["properties"]["timeseries"]
        if not timeseries:
            return {"error": "No weather data available from yr.no"}

        # Current conditions come from the first entry
        now_entry = timeseries[0]
        now_details = now_entry["data"]["instant"]["details"]
        now_symbol = ""
        if "next_1_hours" in now_entry["data"]:
            now_symbol = now_entry["data"]["next_1_hours"]["summary"]["symbol_code"]
        elif "next_6_hours" in now_entry["data"]:
            now_symbol = now_entry["data"]["next_6_hours"]["summary"]["symbol_code"]

        result = {
            "location": {
                "name": location,
                "coordinates": [coords["lat"], coords["lon"]]
            },
            "current": {
                "temperature": round(now_details["air_temperature"]),
                "feels_like": round(now_details["air_temperature"]),  # yr.no does not provide feels_like
                "humidity": round(now_details["relative_humidity"]),
                "description": translate_symbol_code(now_symbol),
                "wind_speed": now_details["wind_speed"],
                "timestamp": now_entry["time"]
            },
            "forecast": []
        }

        # Group the timeseries by day for a 5-day forecast
        daily_forecasts: Dict[str, Dict[str, Any]] = {}
        today = datetime.fromisoformat(timeseries[0]["time"].replace("Z", "+00:00")).strftime("%Y-%m-%d")

        for entry in timeseries:
            dt = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
            date_key = dt.strftime("%Y-%m-%d")

            # Skip today - it is already in `current`
            if date_key == today:
                continue

            details = entry["data"]["instant"]["details"]
            temp = details["air_temperature"]

            # symbol_code comes from next_1_hours or next_6_hours
            symbol = ""
            if "next_1_hours" in entry["data"]:
                symbol = entry["data"]["next_1_hours"]["summary"]["symbol_code"]
            elif "next_6_hours" in entry["data"]:
                symbol = entry["data"]["next_6_hours"]["summary"]["symbol_code"]

            if date_key not in daily_forecasts:
                daily_forecasts[date_key] = {
                    "date": date_key,
                    "temp_min": temp,
                    "temp_max": temp,
                    "descriptions": [],
                    "humidity": details["relative_humidity"],
                    "wind_speed": details["wind_speed"]
                }

            daily_forecasts[date_key]["temp_min"] = min(daily_forecasts[date_key]["temp_min"], temp)
            daily_forecasts[date_key]["temp_max"] = max(daily_forecasts[date_key]["temp_max"], temp)
            if symbol:
                daily_forecasts[date_key]["descriptions"].append(translate_symbol_code(symbol))

        # Format the daily forecast (at most 5 days)
        for date_key in sorted(daily_forecasts.keys())[:5]:
            day = daily_forecasts[date_key]
            descriptions = day["descriptions"]
            description = max(set(descriptions), key=descriptions.count) if descriptions else "unknown"
            result["forecast"].append({
                "date": day["date"],
                "temp_min": round(day["temp_min"]),
                "temp_max": round(day["temp_max"]),
                "description": description,
                "humidity": round(day["humidity"]),
                "wind_speed": day["wind_speed"]
            })

        return result

    except Exception as e:
        logger.error(f"Weather forecast error: {e}")
        return {"error": f"Could not fetch weather data: {str(e)}"}

# API Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check."""
    return HealthResponse(
        status="healthy",
        service="MCP Travel Weather Server",
        timestamp=datetime.now().isoformat()
    )

# The methods this server implements. Used both for routing and for
# `data.supported` in the 404 returned for an unknown method.
SUPPORTED_METHODS = ["server/discover", "tools/list", "tools/call"]


@app.post("/message")
async def handle_jsonrpc(request: Request):
    """
    JSON-RPC 2.0 message handler - the MCP endpoint.

    ============================================================================
    WORKSHOP NOTE: the MCP endpoint in 2026-07-28
    ============================================================================

    This is THE MCP ENDPOINT. The spec requires a server to expose exactly ONE
    HTTP endpoint that accepts POST. Every operation goes through it.

    WHAT'S NEW SINCE 2025-11-25
    --------------------------------
    There is no `initialize` handshake and no session any more. The protocol is
    explicitly STATELESS: "all the information needed to process a request is
    contained in the request itself".

    So every single request has to carry two things:

      1. `params._meta`, with protocol version and client capabilities
      2. HTTP headers that MIRROR selected fields from the body

    The body is the truth. The headers exist so intermediaries (load balancers,
    gateways, observability tooling) can route and inspect without parsing
    JSON. The server MUST check that the two agree. When they disagree you have
    an attack surface, and the answer is 400.

    REQUEST FORMAT:
    ---------------
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
            "arguments": {"location": "Oslo, Norway"},
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

    Note that `Mcp-Name` only applies to methods with a name parameter
    (`tools/call`, `resources/read`, `prompts/get`). `tools/list` has none.

    ERROR CODES AND STATUS CODES - NOW THEY ARE PAIRED:
    -----------------------------------------------
    This is the biggest change to get used to. Before, the server always
    answered HTTP 200 and put the error in the body. Now each violation has its

    Code    Name                       HTTP  When
    ------  -------------------------  ----  --------------------------------
    -32700  Parse error                400   invalid JSON
    -32600  Invalid Request            400   not valid JSON-RPC 2.0
    -32601  Method not found           404   unknown method
    -32602  Invalid params             400   missing `_meta` or parameters
    -32603  Internal error             500   unexpected server-side failure
    -32020  HeaderMismatch             400   header disagrees with the body
    -32022  UnsupportedProtocolVersion  400   we do not speak that version
      1001  Origin not allowed         403   untrusted `Origin` (DNS rebinding)

    The 404 on an unknown method is not a detail: it lets a client tell a
    modern server from a legacy HTTP+SSE server that does not host the endpoint
    at all. See mcp_protocol.method_not_found().

    IMPLEMENTATION PATTERN:
    ----------------------
    1. Validate `Origin` (before anything else - DNS rebinding)
    2. Parse the JSON and validate the JSON-RPC 2.0 envelope
    3. Validate `_meta` and the headers (mcp_protocol.validate_request)
    4. Route to the right method handler
    5. Return a JSON-RPC response with the same id

    MCP SPECIFICATION:
    ------------------
    https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http

    ============================================================================
    """
    # --- Step 1: Origin ---------------------------------------------------
    # First of all, before we even read the body. The spec: "Servers MUST
    # validate the Origin header on all incoming connections to prevent DNS
    # rebinding attacks." Genuinely relevant here: the workshop runs in
    # Codespaces with forwarded ports.
    try:
        mcp_protocol.validate_origin(request.headers.get("origin"))
    except ProtocolError as exc:
        logger.warning(f"Avviste request: {exc.message}")
        return exc.to_response()

    # --- Step 2: parse and validate the JSON-RPC envelope -----------------
    try:
        payload = await request.json()
    except Exception as exc:
        return ProtocolError(
            code=mcp_protocol.PARSE_ERROR,
            message=f"Parse error: {exc}",
            http_status=400,
        ).to_response()

    if not isinstance(payload, dict):
        return ProtocolError(
            code=mcp_protocol.INVALID_REQUEST,
            message="Invalid Request: body must be a single JSON-RPC object",
            http_status=400,
        ).to_response()

    if payload.get("jsonrpc") != "2.0":
        return ProtocolError(
            code=mcp_protocol.INVALID_REQUEST,
            message="Invalid Request: only JSON-RPC 2.0 is supported",
            http_status=400,
        ).to_response()

    if "id" not in payload:
        # No id means a notification. This revision defines no
        # client-to-server notifications over Streamable HTTP, and this server
        # accepts none. The spec: if the server cannot accept it, it MUST
        # answer with an HTTP error status.
        return ProtocolError(
            code=mcp_protocol.INVALID_REQUEST,
            message="Invalid Request: this server accepts no notifications",
            http_status=400,
        ).to_response()

    request_id = payload["id"]
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        # The spec is stricter than JSON-RPC here: id MUST be a string or an
        # integer, and MUST NOT be null.
        return ProtocolError(
            code=mcp_protocol.INVALID_REQUEST,
            message="Invalid Request: id must be a string or integer, and must not be null",
            http_status=400,
        ).to_response()

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        return ProtocolError(
            code=mcp_protocol.INVALID_REQUEST,
            message="Invalid Request: 'method' is required",
            http_status=400,
        ).to_response()

    try:
        # --- Step 3: _meta + the mirrored headers -------------------------
        mcp_request = mcp_protocol.validate_request(
            method=method,
            params=payload.get("params"),
            headers=request.headers,
            request_id=request_id,
        )

        # --- Step 4: route to the right handler ---------------------------
        if method == "server/discover":
            result = await handle_server_discover()
            return jsonrpc_result(request_id, result)

        if method == "tools/list":
            result = await handle_tools_list()
            return jsonrpc_result(request_id, result)

        if method == "tools/call":
            # validate_request() has already established that `name` exists and
            # that it matches the Mcp-Name header.
            tool_name = mcp_request.params["name"]
            arguments = mcp_request.params.get("arguments", {})
            result = await handle_tools_call(tool_name, arguments)
            return jsonrpc_result(request_id, result)

        # Unknown method -> 404, not 200
        raise mcp_protocol.method_not_found(method, SUPPORTED_METHODS)

    except ProtocolError as exc:
        logger.warning(f"Avviste {method}: [{exc.code}] {exc.message}")
        return exc.to_response(request_id)

    except Exception as exc:
        logger.error(f"JSON-RPC handler error: {exc}")
        return ProtocolError(
            code=mcp_protocol.INTERNAL_ERROR,
            message=f"Internal error: {exc}",
            http_status=500,
        ).to_response(request_id)

async def handle_tools_list() -> Dict[str, Any]:
    """
    Handler for the tools/list method.
    Returns the available tools in MCP format.

    ============================================================================
    WORKSHOP NOTE: the MCP tools manifest - dynamic tool discovery
    ============================================================================

    This is the KEY to the dynamic tool discovery pattern.
    The agent calls it to learn which tools exist.

    HOW TO ADD A NEW TOOL:
    --------------------------------
    1. Add a tool definition to the tools array below
    2. Add routing logic in handle_tools_call()
    3. Restart the services: docker compose restart mcp-server travel-agent
    4. The agent picks up the new tool automatically

    FIELDS REQUIRED BY THE MCP SPEC:
    -------------------------
    Required:
    - name: unique identifier for the tool
    - description: what the tool does (the model reads this)
    - inputSchema: JSON Schema for the parameters (JSON Schema 2020-12)

    Optional but recommended:
    - title: human-readable display name
    - outputSchema: JSON Schema for the response structure

    ============================================================================
    """
    tools = [
        {
            "name": "get_weather_forecast",
            "title": "Weather Forecast Provider",
            "description": "Fetch a weather forecast for a destination, with current conditions and a 5-day outlook",
            "inputSchema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name (e.g. 'Oslo', 'Bergen', 'New York')"
                    }
                },
                "required": ["location"],
                "additionalProperties": False
            },
            "outputSchema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "location": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "coordinates": {
                                "type": "array",
                                "items": {"type": "number"}
                            }
                        }
                    },
                    "current": {
                        "type": "object",
                        "properties": {
                            "temperature": {"type": "number"},
                            "feels_like": {"type": "number"},
                            "humidity": {"type": "number"},
                            "description": {"type": "string"},
                            "wind_speed": {"type": "number"},
                            "timestamp": {"type": "string"}
                        }
                    },
                    "forecast": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string"},
                                "temp_min": {"type": "number"},
                                "temp_max": {"type": "number"},
                                "description": {"type": "string"},
                                "humidity": {"type": "number"},
                                "wind_speed": {"type": "number"}
                            }
                        }
                    }
                }
            }
        },
        # ADD YOUR OWN TOOLS HERE -- paste a new {...} block right here.
        # The trailing comma above is deliberate: it means you can paste
        # without editing the line before, and the diff stays to one entry.
        # Copy the structure above and adapt it to your use case.
    ]

    # 2026-07-28 requires three things of any list result:
    #
    #   resultType   "complete" (or "input_required" under MRTR)
    #   ttlMs        how long a client MAY treat the answer as fresh, >= 0
    #   cacheScope   "public" when the answer is not user-specific
    #
    # Our tool list is the same for everyone and only changes when someone
    # edits this file, so "public" and five minutes is plenty.
    return {
        "resultType": "complete",
        "tools": tools,
        "ttlMs": 300_000,
        "cacheScope": "public",
        "_meta": {mcp_protocol.META_SERVER_INFO: mcp_protocol.SERVER_INFO},
    }

async def handle_server_discover() -> Dict[str, Any]:
    """
    Handler for server/discover.

    ============================================================================
    WORKSHOP NOTE: the server's calling card
    ============================================================================

    New in 2026-07-28, and the spec says servers MUST implement it.

    It replaces part of what the `initialize` handshake did: in one call the
    client learns which protocol versions we speak, what we can do, and who we
    are. The difference is that this establishes no session - the answer is
    just information, and a client MAY skip the call entirely.

    Note `supportedVersions`. That is what a client uses to recover when it
    gets -32022 back: it sees what we actually support and retries with a
    version from the list.
    ============================================================================
    """
    return {
        "resultType": "complete",
        "supportedVersions": mcp_protocol.SUPPORTED_VERSIONS,
        "capabilities": {
            # We expose tools, but do not notify on list changes (that would
            # require subscriptions/listen).
            "tools": {"listChanged": False},
        },
        "instructions": (
            "Weather forecasts for any location, via yr.no (api.met.no). "
            "Call tools/list to see the available tools."
        ),
        "ttlMs": 3_600_000,
        "cacheScope": "public",
        "_meta": {mcp_protocol.META_SERVER_INFO: mcp_protocol.SERVER_INFO},
    }

async def handle_tools_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for the tools/call method.
    Routes to the right tool by name.

    Args:
        tool_name: name of the tool to call (e.g. "get_weather_forecast")
        arguments: arguments for the tool (e.g. {"location": "Oslo"})

    Returns:
        An MCP tool result: content, structuredContent, isError
    """
    # Route to the right tool implementation
    if tool_name == "get_weather_forecast":
        # Check that the location parameter is present
        location = arguments.get("location")
        if not location:
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": "Missing required parameter: 'location'"}],
                "isError": True
            }

        # Call the forecast logic
        result = await get_weather_forecast(location)

        # Check for business-logic failures
        if "error" in result:
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": True
            }

        # Success
        # NOTE: tools/call is NOT cacheable per the spec, so no ttlMs or
        # cacheScope here - only resultType.
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "structuredContent": result,
            "isError": False
        }

    else:
        # An unknown tool is a PROTOCOL ERROR, not a tool result.
        #
        # The distinction is worth noting. `isError: true` means "the tool ran,
        # but it went wrong" - that message is for the model, which can retry
        # with different arguments. A tool that does not exist is instead the
        # client asking for something that is not there, and that surfaces as a
        # JSON-RPC error so the client can re-fetch `tools/list`.
        raise ProtocolError(
            code=mcp_protocol.INVALID_PARAMS,
            message=f"Invalid params: unknown tool '{tool_name}'",
            http_status=400,
        )

if __name__ == "__main__":
    logger.info("Starting MCP Travel Weather Server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)