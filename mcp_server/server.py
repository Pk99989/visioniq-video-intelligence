"""VisionIQ MCP server (independent implementation).

Two transports, same tool registry as the backend agent:
- stdio JSON-RPC: `initialize`, `tools/list`, `tools/call`
  (used by MCP clients; run `python server.py` from mcp_server/)
- HTTP: `python server.py --http` serves POST /tools and /tools/call on
  port 8001, with the same JWT bearer check as the backend API.

Tools: video_search, video_qa, video_summarize, clip_retrieval,
event_analysis. Tool calls never invent evidence: video_qa returns the
agent's evidence-grounded answer (or an explicit no-evidence answer).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.security import decode_token  # noqa: E402
from app.services import agent  # noqa: E402
from app.services.retrieval import search_frames  # noqa: E402
from app.services.summarization import summarize_video  # noqa: E402

TOOLS = agent.TOOLS


def call_tool(name: str, args: dict):
    db = SessionLocal()
    try:
        if name == "video_search":
            return search_frames(db, args["query"], video_id=args.get("video_id"),
                                 top_k=int(args.get("top_k", 10)))
        if name == "video_qa":
            return agent.answer_question(db, args["question"], video_id=args.get("video_id"))
        if name == "video_summarize":
            return summarize_video(db, int(args["video_id"]),
                                   length=args.get("length", "medium"))
        if name == "clip_retrieval":
            hits = search_frames(db, args["query"], video_id=args.get("video_id"), top_k=5)
            return [{"video_id": h["video_id"],
                     "start_seconds": max(0.0, h["timestamp_seconds"] - 2),
                     "end_seconds": h["timestamp_seconds"] + 2,
                     "caption": h["caption"]} for h in hits]
        if name == "event_analysis":
            from app.models import Event

            q = db.query(Event)
            if args.get("video_id"):
                q = q.filter_by(video_id=int(args["video_id"]))
            return [{"timestamp_seconds": e.timestamp_seconds, "title": e.title,
                     "severity": e.severity, "verified": e.verified}
                    for e in q.order_by(Event.timestamp_seconds).limit(50).all()]
        raise ValueError(f"Unknown tool: {name}")
    finally:
        db.close()


def serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            method, req_id = req.get("method"), req.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "visioniq", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params", {})
                result = {"content": [{"type": "text",
                                       "text": json.dumps(call_tool(params["name"], params.get("arguments", {})), default=str)}]}
            else:
                result = {"error": f"Unknown method: {method}"}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        except Exception as e:  # noqa: BLE001
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32603, "message": str(e)}}) + "\n")
            sys.stdout.flush()


def serve_http(port: int) -> None:
    from fastapi import FastAPI, Header, HTTPException
    import uvicorn

    app = FastAPI(title="VisionIQ MCP Server")

    def _auth(authorization: str | None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing bearer token")
        if decode_token(authorization[7:]) is None:
            raise HTTPException(401, "Invalid token")

    @app.get("/tools")
    def tools(authorization: str | None = Header(default=None)):
        _auth(authorization)
        return TOOLS

    @app.post("/tools/call")
    def call(body: dict, authorization: str | None = Header(default=None)):
        _auth(authorization)
        return call_tool(body["name"], body.get("arguments", {}))

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        serve_http(args.port)
    else:
        serve_stdio()
