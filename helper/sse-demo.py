#!/usr/bin/env python3
"""
Streamable HTTP, both response shapes, in one runnable file.

The point this demonstrates:

    One endpoint. One POST. The SERVER decides whether the answer comes back
    as a single JSON object or as an SSE stream whose last event is that same
    JSON-RPC result. Either way the exchange is over when the response ends.
    There is no session, nothing held open, nothing to resume.

This is what survived in 2026-07-28. What was removed is the *standalone* SSE
stream: a GET that stayed open and pushed notifications unrelated to any
request. A GET here answers 405, exactly as the real server does.

Standard library only - no FastAPI, no httpx - so it runs anywhere python3 does:

    python3 helper/sse-demo.py           # server + client, prints the timeline
    python3 helper/sse-demo.py --serve   # just the server, poke it with curl

    curl -N -X POST http://127.0.0.1:8099/message \
      -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
           "params":{"name":"slow_tool","arguments":{}}}'

    (-N matters: without it curl buffers and the streaming is invisible.)

This is a transport simulation. It deliberately skips `_meta`, the mirrored
headers and Origin validation - that is what the real server in
services/mcp-server/ is for.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", 8099))
ENDPOINT = f"http://{HOST}:{PORT}/message"


# ===========================================================================
# SERVER SIDE
# ===========================================================================

def run_tool(name):
    """
    A tool that yields progress before its result.

    Yielding is the whole trick: a fast tool returns, a slow one reports as it
    goes. The transport can carry both because SSE lets one response arrive in
    pieces.
    """
    if name == "fast_tool":
        return

    for step in ("geocoding Oslo", "fetching forecast", "formatting"):
        time.sleep(0.6)
        yield step


def sse_frame(payload, event=None):
    """
    One SSE event.

    The wire format is text: optional `event:` line, one `data:` line holding
    the JSON, then a BLANK LINE that terminates the event. Forget the blank
    line and the client waits forever for an event that never ends.
    """
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(payload)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        """No standalone stream to open. 2026-07-28 removed it."""
        body = b'{"error":"GET is not an MCP stream. POST /message."}'
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # The docstring invites people to poke this with curl, so a missing or
        # malformed body is an expected case, not an exceptional one. Answering
        # 400 / -32700 is also what the real server does.
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return self.respond_error(-32700, "Parse error: body is not valid JSON")

        tool = request.get("params", {}).get("name", "fast_tool")

        # THE SERVER CHOOSES. The client advertised that it handles both, so
        # either answer is legal; this one streams when it has progress worth
        # sending. A client that assumes JSON here is a client that breaks
        # against somebody else's server.
        accepts_sse = "text/event-stream" in self.headers.get("Accept", "")
        if tool == "fast_tool" or not accepts_sse:
            return self.respond_json(request, tool)
        return self.respond_sse(request, tool)

    def respond_error(self, code, message):
        body = json.dumps({
            "jsonrpc": "2.0", "id": None,
            "error": {"code": code, "message": message},
        }).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_json(self, request, tool):
        for _ in run_tool(tool):      # drain progress nobody can hear
            pass
        body = json.dumps(result_for(request, tool)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_sse(self, request, tool):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # No Content-Length: the length is not known when the headers go out.
        # That is precisely why streaming needs its own content type.
        self.end_headers()

        # A client that walks away mid-stream is normal for streaming, not an
        # error: Ctrl-C on the curl command in the docstring does exactly this.
        try:
            for step in run_tool(tool):
                self.wfile.write(sse_frame({
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {"message": step},
                }, event="progress"))
                self.wfile.flush()    # without this, nothing leaves early

            # The LAST data event is the JSON-RPC response. Same object the
            # JSON branch would have returned - only the delivery differed.
            self.wfile.write(sse_frame(result_for(request, tool)))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return                    # the client hung up; nothing to clean up

    def log_message(self, *args):
        pass                          # keep the demo output readable


def result_for(request, tool):
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {
            "resultType": "complete",
            "content": [{"type": "text", "text": f"{tool} finished: Oslo, 18C, cloudy"}],
            "isError": False,
        },
    }


# ===========================================================================
# CLIENT SIDE
# ===========================================================================

def call_tool(name, on_progress=None):
    """
    Call the tool and return the JSON-RPC response, whichever shape it arrives in.

    This mirrors parse_mcp_response() in services/agent/app.py. The client does
    not get to pick the shape - it says it handles both and then handles both.
    """
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }).encode()

    request = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json",
        # Saying both is what makes a streamed answer legal.
        "Accept": "application/json, text/event-stream",
    })

    with urllib.request.urlopen(request) as response:
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            return json.loads(response.read())

        # Read line by line as it arrives - do NOT .read() the whole body,
        # that waits for the end and throws away the reason to stream at all.
        last = None
        for raw in response:
            line = raw.decode().rstrip("\n")
            if not line or line.startswith(":"):    # blank = end of event
                continue                            # ":" = keep-alive comment
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if "result" in payload or "error" in payload:
                    last = payload                  # a response, not a notification
                    continue
                message = payload.get("params", {}).get("message")
                if message and on_progress:         # some other notification
                    on_progress(message)            # shape: ignore it
        if last is None:
            raise ValueError("SSE stream contained no JSON-RPC response")
        return last


# ===========================================================================

def main():
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"Cannot listen on {HOST}:{PORT} - {exc}")
        print("Stop the other sse-demo, or run with PORT=9099")
        return 1
    threading.Thread(target=server.serve_forever, daemon=True).start()

    if "--serve" in sys.argv:
        print(f"Serving {ENDPOINT} - Ctrl-C to stop")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return 0

    started = time.time()

    def stamp(text):
        print(f"  [{time.time() - started:5.2f}s] {text}")

    print("\n1. fast_tool - the server answers application/json")
    print("   one object, nothing to stream")
    response = call_tool("fast_tool", on_progress=stamp)
    stamp(response["result"]["content"][0]["text"])

    started = time.time()
    print("\n2. slow_tool - the server answers text/event-stream")
    print("   progress arrives DURING the call, then the same result")
    response = call_tool("slow_tool", on_progress=stamp)
    stamp(response["result"]["content"][0]["text"])

    print("\n3. GET /message - the removed standalone stream")
    try:
        urllib.request.urlopen(ENDPOINT)
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code} - there is no stream to open")

    print("\nSame endpoint, same result object, two deliveries.")
    print("Both exchanges are over. Nothing is still open.\n")
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
