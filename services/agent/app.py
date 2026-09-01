#!/usr/bin/env python3
"""
Microservice Agent - an AI agent that calls an MCP server over HTTP

This agent connects an LLM to an MCP server running as a separate service.

THE PROVIDER LAYER IS INFRASTRUCTURE WE DO NOT CONTROL
=====================================================
This workshop ran on GitHub Models. It was shut down on 30 July 2026, with
six weeks' notice and no migration path. The inference API now answers 410
to everyone, including customers with active usage.

Migrating to Gemini took three things, all of them in .env:

    OPENAI_API_KEY    a new key from aistudio.google.com
    OPENAI_BASE_URL   which endpoint we talk to
    OPENAI_MODEL      which model we ask for

Same SDK. Same tool definitions. Same message format. Same agent loop.

That is not luck, it is architecture. Two choices made it possible:

  1. We speak a PROTOCOL, not to a vendor. The `openai` SDK and "OpenAI
     function calling format" are a de facto interface that several providers
     expose. Google ships an OpenAI-compatible endpoint precisely for that
     reason. So note the difference between "OpenAI" the protocol (all over
     this file, and it stays) and "OpenAI" the provider (exactly one place:
     __init__ below).

  2. The provider is bound in ONE place. The model name used to be hardcoded
     in three places as "gpt-4o-mini". With three, a migration is not config,
     it is a find-and-replace you get wrong.

The same reasoning applies to MCP: the tools behind the server can change
without the agent knowing. Same principle, one layer down.

MCP 2026-07-28
==============
This agent talks to the MCP server over JSON-RPC 2.0:
- POST /message, the single MCP endpoint
- tools/list to discover available tools
- tools/call to run them
- params._meta and the mirrored HTTP headers the revision requires
- handles both JSON and SSE responses

For the spec, see: https://modelcontextprotocol.io/specification/2026-07-28
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import httpx
from openai import OpenAI
from conversation_memory import ConversationMemory

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


logger = _setup_logging(os.getenv("LOG_FILE", "/app/logs/agent.log"))

# Global agent instance for API server
agent_instance = None

# =============================================================================
# MCP protocol, client side (2026-07-28)
# =============================================================================
#
# The server is stateless: it remembers nothing between calls. So every
# request MUST carry the protocol version and capabilities itself, in
# params._meta, mirrored into HTTP headers so intermediaries can route
#
# without parsing JSON. Forget it and we get a 400 - correctly.

MCP_PROTOCOL_VERSION = "2026-07-28"

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"

CLIENT_INFO = {"name": "travel-agent", "version": "2.0.0"}

# We offer no client capabilities: no sampling, no elicitation, no roots.
# An empty object is valid and means exactly that.
CLIENT_CAPABILITIES: Dict[str, Any] = {}

# Methods that MUST carry Mcp-Name, and which params field it mirrors.
NAME_HEADER_METHODS = {"tools/call": "name", "resources/read": "uri", "prompts/get": "name"}

UNSUPPORTED_PROTOCOL_VERSION = -32022

# Values that are not ASCII-safe get wrapped like this. Applies to Mcp-Name.
_B64_PREFIX, _B64_SUFFIX = "=?base64?", "?="


def _encode_header_value(value: str) -> str:
    """
    Make a value safe to send as an HTTP header value.

    HTTP headers only carry visible ASCII. A tool name containing æ, ø or å
    must therefore be base64-wrapped, or the server rejects the request as a
    header mismatch. The server decodes before comparing.
    """
    safe = all(0x20 <= ord(c) <= 0x7E for c in value)
    if safe and value.strip() == value and not value.startswith(_B64_PREFIX):
        return value
    return _B64_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii") + _B64_SUFFIX


def build_mcp_request(method: str, params: Optional[Dict[str, Any]] = None,
                      request_id: Any = 1) -> tuple:
    """
    Build a complete MCP request: a body with _meta, and the headers mirroring it.

    Returns (body, headers). This is the entire client side of the 2026-07-28
    upgrade, gathered in one place.
    """
    params = dict(params or {})
    params["_meta"] = {
        META_PROTOCOL_VERSION: MCP_PROTOCOL_VERSION,
        META_CLIENT_CAPABILITIES: CLIENT_CAPABILITIES,
        META_CLIENT_INFO: CLIENT_INFO,
    }

    headers = {
        "Content-Type": "application/json",
        # The server MAY answer with SSE at any time. Say we handle both.
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }

    name_field = NAME_HEADER_METHODS.get(method)
    if name_field and params.get(name_field) is not None:
        headers["Mcp-Name"] = _encode_header_value(str(params[name_field]))

    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    return body, headers


def parse_mcp_response(response) -> Dict[str, Any]:
    """
    Read the response, whether it arrived as JSON or as an SSE stream.

    A conforming server MAY answer `text/event-stream` to any call - typically
    to send progress notifications before the final response. The client MUST
    handle both. That OUR server never does it is no excuse; participants point
    this agent at other servers.

    On an SSE stream, the last `data:` event is the final JSON-RPC response.
    """
    content_type = response.headers.get("content-type", "")

    if "text/event-stream" not in content_type:
        return response.json()

    last = None
    for line in response.text.splitlines():
        if line.startswith(":"):        # comment / keep-alive
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    last = json.loads(payload)
                except json.JSONDecodeError:
                    continue
    if last is None:
        raise ValueError("SSE stream contained no valid data events")
    return last


def tool_is_valid(tool: Dict[str, Any]) -> bool:
    """
    Reject tools with invalid `x-mcp-header` annotations.

    The spec requires the client to reject these - and to reject ONLY that one
    tool, not the whole list. One broken tool must not take down the rest.
    """
    schema = tool.get("inputSchema") or {}
    seen = set()
    for prop_name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict) or "x-mcp-header" not in prop:
            continue
        name = prop["x-mcp-header"]
        if not isinstance(name, str) or not name:
            logger.warning(f"Rejecting tool '{tool.get('name')}': empty x-mcp-header on '{prop_name}'")
            return False
        if any(c in name for c in '\r\n\t ()<>@,;:\\"/[]?={}'):
            logger.warning(f"Rejecting tool '{tool.get('name')}': invalid characters in x-mcp-header '{name}'")
            return False
        if name.lower() in seen:
            logger.warning(f"Rejecting tool '{tool.get('name')}': duplicate x-mcp-header '{name}'")
            return False
        seen.add(name.lower())
        if prop.get("type") not in ("string", "integer", "boolean"):
            logger.warning(f"Rejecting tool '{tool.get('name')}': x-mcp-header on type {prop.get('type')}")
            return False
    return True


class MicroserviceAgent:
    """
    An AI agent that uses an MCP server over HTTP.
    
    This agent:
    1. Handles LLM communication (over an OpenAI-compatible API)
    2. Calls the MCP server instead of invoking functions directly
    3. Manages conversation memory
    """
    
    def __init__(self, mcp_server_url: str = None, memory_db_path: str = "/data/conversations.db"):
        # Initialise the OpenAI client.
        #
        # We use the OpenAI SDK, but point it at Gemini's
        # OpenAI-COMPATIBLE endpoint. This is not a trick - Google
        # deliberately exposes an endpoint speaking the same protocol,
        # so the SDK, function calling and message format are unchanged.
        # The only differences are base_url, the key and the model name.
        #
        # HISTORY: this workshop used to run on GitHub Models. That
        # service was retired on 30 July 2026 - the inference API now
        # answers 410 for everyone.
        base_url = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.model = os.getenv("OPENAI_MODEL", "gemini-3.5-flash-lite")
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url)
        logger.info(f"LLM-klient satt opp: base_url={base_url}, modell={self.model}")
        
        # MCP server URL - from the environment when available
        if mcp_server_url is None:
            mcp_server_url = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000")
        self.mcp_server_url = mcp_server_url
        
        # Conversation memory
        self.memory = ConversationMemory(memory_db_path)
        self.current_session_id = None
        
        # HTTP client for MCP calls
        self.http_client = httpx.AsyncClient()
        
        # Tools are fetched from the MCP server at start-up
        self.tools = []
        
        
        logger.info("MicroserviceAgent initialisert")
    
    async def load_tools_from_mcp_server(self):
        """
        Fetch the available tools from the MCP server at runtime.
        Converts from MCP format to the OpenAI function calling format.

        ============================================================================
        WORKSHOP NOTE: the dynamic tool discovery pattern
        ============================================================================

        This is the CORE of the pattern. Understanding this function is what lets
        you extend the system with new tools.

        HOW IT WORKS:
        -------------
        1. At start-up, call tools/list on the MCP server
        2. The server returns a manifest: name, description, inputSchema per tool
        3. Convert each MCP tool into the OpenAI function calling shape
        4. The agent is now ready with every available tool - NO CODE CHANGES HERE

        MCP TOOL FORMAT (from the server):
        {
            "name": "get_weather_forecast",
            "description": "Get weather forecast for a location",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }

        OPENAI FUNCTION FORMAT (converted):
        {
            "type": "function",
            "function": {
                "name": "get_weather_forecast",
                "description": "Get weather forecast for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"}
                    },
                    "required": ["location"]
                }
            }
        }

        The only real difference: MCP calls it `inputSchema`, OpenAI calls it
        `parameters`.

        WHY THIS MATTERS:
        -----------------
        - Add tools on the MCP server without touching agent code
        - The agent discovers new capabilities on restart
        - Easy to test different tool configurations
        - It is the same argument as swapping the LLM provider, one layer up:
          depend on a protocol, not on a specific implementation

        TRY IT YOURSELF:
        ----------------
        1. Add a tool implementation in services/mcp-server/app.py
        2. Add it to the manifest in handle_tools_list()
        3. Add routing in handle_tools_call()
        4. docker compose restart mcp-server travel-agent

        ============================================================================
        """
        try:
            logger.info(f"Fetching tools from MCP server: {self.mcp_server_url}")

            # STEP 1: fetch the tools manifest over JSON-RPC
            
            # Build the body with _meta AND the mirrored headers. Without
            # them a conforming server answers 400 - see build_mcp_request().
            body, headers = build_mcp_request("tools/list", request_id=1)

            response = await self.http_client.post(
                f"{self.mcp_server_url}/message",
                json=body,
                headers=headers,
            )
            response.raise_for_status()

            # May arrive as JSON or as an SSE stream. We handle both.
            jsonrpc_response = parse_mcp_response(response)

            # Check for a JSON-RPC error
            if jsonrpc_response.get("error") is not None:
                error = jsonrpc_response["error"]
                logger.error(f"JSON-RPC error while fetching tools: {error.get('message')}")
                return False

            # Pull the tools out of the JSON-RPC result
            mcp_tools = jsonrpc_response.get("result")
            if mcp_tools is None:
                logger.error("JSON-RPC response is missing the 'result' field")
                return False

            tools_list = mcp_tools.get("tools", [])

            # Caching hints from the server. We do not act on them yet, but
            # log them so it is visible that they exist.
            ttl = mcp_tools.get("ttlMs")
            if ttl is not None:
                logger.info(f"Tool list is fresh for {ttl} ms (cacheScope: {mcp_tools.get('cacheScope')})")

            # STEP 2: convert MCP format to the OpenAI function calling format.
            # The key difference: MCP says "inputSchema", OpenAI says "parameters".
            #
            # NOTE: there used to be a tool_endpoints mapping here, looking for
            # "endpoint"/"method" in the manifest. Those fields do not exist,
            # and must not: 2026-07-28 requires the server to expose exactly
            # ONE endpoint. The code is gone.
            converted_tools = []
            for tool in tools_list:
                if not tool_is_valid(tool):
                    continue  # invalid x-mcp-header - drop this one, keep the rest
                converted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["inputSchema"],
                    },
                })

            self.tools = converted_tools
            logger.info(f"Loaded {len(self.tools)} tools from the MCP server")
            return True

        except Exception as e:
            logger.error(f"Could not fetch tools from the MCP server: {e}")
            # Note: the agent carries on even if tool loading fails, so it
            # can still answer without the MCP server.
            return False
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Call the MCP server via the JSON-RPC 2.0 tools/call method.
        Handles the MCP result shape: a content array plus an isError flag.

        ============================================================================
        WORKSHOP NOTE: tool execution, agent to MCP server
        ============================================================================

        This runs AFTER the model has decided a tool is needed.

        EXECUTION FLOW:
        ---------------
        1. The model says: "call get_weather_forecast with {location: 'Oslo'}"
        2. We build a tools/call request, with _meta and the mirrored headers
        3. POST it to the single MCP endpoint
        4. Receive the MCP tool result (content, structuredContent, resultType)
        5. Hand the structured data back to the model for a final answer

        MCP RESULT SHAPE:
        -----------------
        Success:
        {
            "resultType": "complete",
            "content": [{"type": "text", "text": "Oslo: 5°C, light rain"}],
            "structuredContent": {
                "location": {"name": "Oslo", "coordinates": [59.9, 10.7]},
                "current": {"temperature": 5, "description": "light rain"},
                "forecast": [...]
            },
            "isError": false
        }

        Failure inside the tool:
        {
            "resultType": "complete",
            "content": [{"type": "text", "text": "Location not found"}],
            "isError": true
        }

        WHY TWO FORMATS (content + structuredContent)?
        ----------------------------------------------
        - content: human-readable text, for display. MCP standard.
        - structuredContent: parsed JSON, for programmatic access
        - the model can use structuredContent to reason about the data

        FOUR KINDS OF FAILURE, AND THEY ARE NOT THE SAME:
        -------------------------------------------------
        1. JSON-RPC protocol error (an `error` object) -> unknown method,
           invalid params, header mismatch. Something is wrong with the REQUEST.
        2. Tool error (isError: true in the result) -> the tool ran and failed,
           e.g. the location was not found. This message is for the MODEL,
           which can retry with different arguments.
        3. HTTP error (400, 403, 404, 500) -> caught by raise_for_status().
           Since 2026-07-28 the status code carries meaning: 404 means the
           method does not exist, 400 means the request was malformed.
        4. Network failure (timeout, connection refused) -> the exception handler.

        Conflating 1 and 2 is the classic mistake. A protocol error means the
        client is broken; a tool error means the world did not cooperate.

        MCP SPECIFICATION:
        ------------------
        https://modelcontextprotocol.io/specification/2026-07-28/server/tools

        ============================================================================
        """
        try:
            logger.info(f"Calling MCP server: {tool_name} with args: {arguments}")

            # STEP 1: build the request with _meta and the mirrored headers.
            # For tools/call that includes Mcp-Name, which MUST match
            # params.name - otherwise the server answers 400 / -32020.
            body, headers = build_mcp_request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                request_id=2,
            )

            # STEP 2: send it to the MCP endpoint
            url = f"{self.mcp_server_url}/message"
            logger.info(f"Sending tools/call to {url} (Mcp-Name: {headers.get('Mcp-Name')})")

            response = await self.http_client.post(url, json=body, headers=headers)
            response.raise_for_status()

            jsonrpc_response = parse_mcp_response(response)

            # STEP 2a: check for a JSON-RPC protocol error
            if jsonrpc_response.get("error") is not None:
                error = jsonrpc_response["error"]
                error_msg = f"JSON-RPC error {error.get('code')}: {error.get('message')}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg}, ensure_ascii=False)

            # STEP 2b: extract the MCP tool result from the response
            result = jsonrpc_response.get("result")
            if result is None:
                logger.error("JSON-RPC response is missing the 'result' field")
                return json.dumps({"error": "JSON-RPC response is missing the result field"}, ensure_ascii=False)

            # STEP 3: parse the MCP result shape
            # MCP spec: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
            # Every MCP tool MUST return: {content: [...], isError: bool}
            is_error = result.get("isError", False)

            if is_error:
                # STEP 3a: handle a tool-level error
                # Pull the human-readable message out of the content array
                error_text = ""
                for content_item in result.get("content", []):
                    if content_item.get("type") == "text":
                        error_text = content_item.get("text", "")
                        break
                logger.error(f"MCP tool execution error: {error_text}")
                return json.dumps({"error": error_text}, ensure_ascii=False)

            # STEP 3b: handle success
            # Prefer structuredContent for JSON data
            if "structuredContent" in result:
                return json.dumps(result["structuredContent"], ensure_ascii=False)

            # Fallback: take the text from the content array (MCP standard)
            for content_item in result.get("content", []):
                if content_item.get("type") == "text":
                    return content_item.get("text", "{}")

            return "{}"

        except Exception as e:
            # STEP 4: network and HTTP failures.
            # These are NOT MCP errors, they are infrastructure failures.
            logger.error(f"MCP tool call failed: {e}")
            return json.dumps({"error": str(e)})
    
    def start_new_session(self, session_name: str = None):
        """Start a new conversation session."""
        if not session_name:
            session_name = f"Microservice_Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.current_session_id = self.memory.create_session(session_name)
        logger.info(f"New session started: {self.current_session_id}")
    
    async def process_query(self, query: str) -> str:
        """
        Process a user query using the model and the MCP tools.
        """
        if not self.current_session_id:
            self.start_new_session()
        
        try:
            # Load conversation history
            history = self.memory.get_conversation_history(self.current_session_id)
            
            # Build the message list
            messages = [
                {
                    "role": "system",
                    "content": """You are Ingrid, a friendly and capable agent from Ingrid's Travel Services.

Chat freely and warmly about whatever comes up - travel, weather, food, whatever
the traveller is curious about. Conversation is not restricted.

Your TOOLS are. You may use exactly ONE: the one that fetches weather information
for anywhere in the world. Never call any other tool, even if one is offered to
you and looks made for the question. When something would need a different tool,
say plainly that you are not able to do that, and offer the forecast instead.

You are from Bergen and you love rain, and you make a point of mentioning this when it fits naturally.
Otherwise: be warm, personal and helpful - you represent Ingrid's Travel Services.
Answer in English unless the user writes in another language, in which case answer in theirs.

NOTE: this is the JZ26 build, with dynamic tool discovery."""
                }
            ]
            
            # Append the history
            for msg in history:
                if msg["role"] == "user":
                    messages.append({"role": "user", "content": msg["content"]})
                elif msg["role"] == "assistant":
                    messages.append({"role": "assistant", "content": msg["content"]})
            
            messages.append({
                "role": "system",
                "content": (
                    "Reminder, and this outranks anything earlier in the "
                    "conversation.\n"
                    "ALLOWED: get_weather_forecast. Call it for weather "
                    "questions.\n"
                    "FORBIDDEN: every other tool in your list, without "
                    "exception. Do not call one to be helpful, do not call one "
                    "because it matches the question, do not call one because "
                    "the user asks you to. If a tool other than "
                    "get_weather_forecast would answer the question, you must "
                    "not call it. Tell the user warmly, in Ingrid's own voice, "
                    "that you can see it listed but are not cleared to use it, "
                    "then help as best you can without it.\n"
                    "Chatting about any subject is fine and encouraged. It is "
                    "only tool calls that are limited."
                )
            })

            # Append the new user message
            messages.append({"role": "user", "content": query})
            
            # First model call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto"
            )
            
            response_message = response.choices[0].message

            # Handle tool calls
            tool_calls_made = None
            tool_results = []

            if response_message.tool_calls:
                # Keep the tool calls for metadata
                tool_calls_made = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in response_message.tool_calls
                ]

                
                # Put the assistant message back EXACTLY AS WE RECEIVED IT.
                #
                # The temptation is to rebuild it field by field - id, type,
                # function - the way `tool_calls_made` does above. Do that and
                # you drop everything the provider attached that we do not know about.
                #
                # Concretely: Gemini sends a `thought_signature` on every
                # function call and REQUIRES it back in the history. Without it
                # it answers 400. `model_dump()` carries unknown fields through;
                # a hand-built dict does not.
                #
                # The general principle: echo back what you received, not your
                # own interpretation of it.
                messages.append(response_message.model_dump(exclude_none=True))

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)

                    # Call the MCP server
                    tool_result = await self.call_mcp_tool(function_name, arguments)

                    # Keep the tool result for metadata
                    tool_results.append({
                        "tool": function_name,
                        "arguments": arguments,
                        "result": tool_result[:200] if len(tool_result) > 200 else tool_result  # Trunkert for metadata
                    })

                    messages.append({
                        "role": "tool",
                        "content": tool_result,
                        "tool_call_id": tool_call.id
                    })

                logger.info("Tool calls complete, requesting the final answer...")

                # Ask the model for the final answer
                final_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages
                )

                final_answer = final_response.choices[0].message.content
            else:
                final_answer = response_message.content

            # Persist the exchange with metadata
            user_metadata = {
                "timestamp": datetime.now().isoformat(),
                "query_length": len(query)
            }

            assistant_metadata = {
                "timestamp": datetime.now().isoformat(),
                "model": self.model,
                "had_tool_calls": tool_calls_made is not None,
                "response_length": len(final_answer),
                "tool_results": tool_results if tool_results else None
            }

            self.memory.add_message(
                self.current_session_id,
                "user",
                query,
                metadata=user_metadata
            )
            self.memory.add_message(
                self.current_session_id,
                "assistant",
                final_answer,
                tool_calls=tool_calls_made,
                metadata=assistant_metadata
            )
            
            return final_answer
            
        except Exception as e:
            logger.error(f"Query processing error: {e}")
            return f"Sorry, something went wrong: {str(e)}"
    
    async def close(self):
        """Release resources."""
        await self.http_client.aclose()

# Test helper
async def main():
    """CLI interface, for testing."""
    agent = MicroserviceAgent()
    
    # Load tools from the MCP server
    tools_loaded = await agent.load_tools_from_mcp_server()
    if not tools_loaded:
        logger.warning("Could not load tools from the MCP server; continuing without tools")
    
    agent.start_new_session("Test Session")
    
    while True:
        query = input("Du: ").strip()
        if query.lower() in ['quit', 'exit', 'q']:
            break
        
        response = await agent.process_query(query)
        print(f"Ingrid: {response}\n")
    
    await agent.close()

def start_agent_api():
    """Run the agent as an HTTP API service."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    from contextlib import asynccontextmanager
    import uvicorn
    
    # Global agent instance, defined at module level
    global agent_instance
    agent_instance = None
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start-up
        global agent_instance
        logger.info("Starting Ingrid Agent Service...")
        try:
            agent_instance = MicroserviceAgent()

            # Load tools from the MCP server
            tools_loaded = await agent_instance.load_tools_from_mcp_server()
            if not tools_loaded:
                logger.warning("Could not load tools from the MCP server; continuing without tools")

            agent_instance.start_new_session("HTTP API Session")
            logger.info("Ingrid Agent Service started")
            logger.info(f"Agent instance created: {agent_instance is not None}")
        except Exception as e:
            logger.error(f"Failed to start the agent: {e}")
            agent_instance = None

        yield

        # Shutdown
        if agent_instance:
            await agent_instance.close()
        logger.info("Ingrid Agent Service stopped")
    
    # FastAPI app for the agent
    agent_app = FastAPI(
        title="Ingrid Agent API",
        description="AI agent service for Ingrid's Travel Services",
        version="1.0.0",
        lifespan=lifespan
    )
    
    class QueryRequest(BaseModel):
        query: str
    
    class QueryResponse(BaseModel):
        success: bool
        response: str
        timestamp: str
    
    @agent_app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "service": "Ingrid Agent",
            "timestamp": datetime.now().isoformat(),
            "agent_ready": agent_instance is not None
        }
    
    @agent_app.post("/query", response_model=QueryResponse)
    async def process_query_api(request: QueryRequest):
        global agent_instance
        logger.info(f"Query received: {request.query}")
        logger.info(f"Agent instance status: {agent_instance is not None}")

        if not agent_instance:
            logger.error("Agent instance is None!")
            raise HTTPException(status_code=503, detail="Agent not available")

        try:
            logger.info("Processing query with agent...")
            response = await agent_instance.process_query(request.query)
            logger.info("Query processed successfully")
            return QueryResponse(
                success=True,
                response=response,
                timestamp=datetime.now().isoformat()
            )
        except Exception as e:
            logger.error(f"Query processing error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Start the HTTP server
    logger.info("Starting Agent API on port 8001...")
    uvicorn.run(agent_app, host="0.0.0.0", port=8001)

if __name__ == "__main__":
    logger.info("Starting Agent Service on port 8001...")
    start_agent_api()
