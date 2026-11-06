"""VisionIQ MCP server (independent implementation).

Two transports, same tool registry as the backend agent:
- stdio JSON-RPC: `initialize`, `tools/list`, `tools/call`
  (used by MCP clients; run `python server.py` from mcp_server/)
- HTTP: `python server.py --http` serves POST /tools and /tools/call on
  port 8001, with the same JWT bearer check as the backend API.

Tools (8): video_search, video_qa, video_summarize, clip_retrieval,
event_analysis, detection_analytics, timeline_analysis,
report_generation. Tool calls never invent evidence: video_qa returns
the agent's evidence-grounded answer (or an explicit no-evidence
answer). All calls go through `agent.run_tool`, the same entry point
the HTTP chat endpoint uses, so MCP and the API can never drift apart.

Hardening (Phase 5): request ids are preserved on error responses,
unknown tools and missing arguments return JSON-RPC -32602 (invalid
params) instead of -32603, malformed JSON returns -32700, and the
HTTP transport returns 400 (not 500) for unknown tools and bad
bodies. Non-admin callers only ever see their own videos.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import decode_token  # noqa: E402
from app.services import agent  # noqa: E402

TOOLS = agent.TOOLS
_TOOL_NAMES = {t["name"] for t in TOOLS}
_REQUIRED = {t["name"]: set(t.get("inputSchema", {}).get("required", []))
             for t in TOOLS}
VERSION = "0.12.0"


def _scoped_user_id(user):
    """Non-admin callers only ever see their own videos; admins see all."""
    return user.id if user is not None and user.role != "admin" else None


def validate_call(name, args):
    """Returns an error string, or None when the call is well-formed."""
    if not isinstance(name, str) or name not in _TOOL_NAMES:
        return f"Unknown tool: {name}"
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    missing = _REQUIRED[name] - set(args)
    if missing:
        return f"Missing required argument(s): {', '.join(sorted(missing))}"
    return None


def call_tool(name: str, args: dict, user=None):
    """user=None means unscoped (stdio transport: the local operator runs
    it on their own machine with direct DB access). The HTTP transport
    always passes the JWT-authenticated user, so one tenant can never
    read another tenant's captions, clips or events through MCP."""
    error = validate_call(name, args)
    if error:
        return {"error": error}
    db = SessionLocal()
    try:
        return agent.run_tool(name, db, args, user_id=_scoped_user_id(user))
    finally:
        db.close()


def serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700,
                                                   "message": f"Parse error: {e}"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            method, req_id = req.get("method"), req.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "visioniq", "version": VERSION}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError("params must be an object")
                error = validate_call(params.get("name"), params.get("arguments", {}))
                if error:
                    sys.stdout.write(json.dumps(
                        {"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": -32602, "message": error}}) + "\n")
                    sys.stdout.flush()
                    continue
                result = {"content": [{"type": "text",
                                       "text": json.dumps(call_tool(params["name"],
                                                                    params.get("arguments", {})),
                                                          default=str)}]}
            else:
                sys.stdout.write(json.dumps(
                    {"jsonrpc": "2.0", "id": req_id,
                     "error": {"code": -32601, "message": f"Method not found: {method}"}}) + "\n")
                sys.stdout.flush()
                continue
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        except Exception as e:  # noqa: BLE001
            # The request id is preserved (previously it was dropped to
            # None, so a client could not match the error to its call).
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id,
                                         "error": {"code": -32603, "message": str(e)}}) + "\n")
            sys.stdout.flush()


def create_http_app():
    """The HTTP MCP app, factored out so tests can exercise it without
    starting uvicorn (see tests/test_mcp.py)."""
    from fastapi import FastAPI, Header, HTTPException

    app = FastAPI(title="VisionIQ MCP Server")

    def _auth(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing bearer token")
        data = decode_token(authorization[7:])
        if not data:
            raise HTTPException(401, "Invalid token")
        db = SessionLocal()
        try:
            user = db.get(User, int(data["sub"]))
        finally:
            db.close()
        if not user:
            raise HTTPException(401, "Invalid token")
        return user

    @app.get("/tools")
    def tools(authorization: str | None = Header(default=None)):
        _auth(authorization)
        return TOOLS

    @app.post("/tools/call")
    def call(body: dict, authorization: str | None = Header(default=None)):
        user = _auth(authorization)
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            raise HTTPException(400, "Body must be {name, arguments}")
        error = validate_call(body["name"], body.get("arguments", {}))
        if error:
            raise HTTPException(400, error)
        return call_tool(body["name"], body.get("arguments", {}), user=user)

    return app


def serve_http(port: int) -> None:
    import uvicorn

    uvicorn.run(create_http_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        serve_http(args.port)
    else:
        serve_stdio()
