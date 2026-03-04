# -*- coding: utf-8 -*-
"""
HTTP transport: FastAPI app with /health and Streamable HTTP /message.
Streamable HTTP: POST /message (JSON-RPC), GET /message (SSE); optional Bearer auth.
Client mcpServers config: type "streamable-http", url = base + "/message", headers = { "Authorization": "Bearer ...", ... }.
"""

import json
import uuid
import asyncio
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse

from mcp_server.config import MCP_BEARER_TOKEN
from mcp_server.core.protocol import MCPServer
from mcp_server.transports.message_bus import (
    register_connection,
    set_connection_id,
    subscribe,
    unregister_connection,
    unsubscribe,
)

app = FastAPI()
server = MCPServer()


def _check_bearer(request: Request) -> None:
    """If MCP_BEARER_TOKEN is set, require Authorization: Bearer <token>."""
    if not MCP_BEARER_TOKEN:
        return
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[7:].strip()
    if token != MCP_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


async def _read_json_body(request: Request) -> dict | None:
    """读取请求体为 JSON；空或非法时返回 None，不抛异常。"""
    raw = await request.body()
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def _jsonrpc_parse_error(req_id=None):
    """JSON-RPC 2.0 Parse error (-32700)：请求体不是合法 JSON。"""
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32700, "message": "Parse error"}}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-server"}

# ---------- Streamable HTTP (type: "streamable-http", url + headers) ----------
@app.post("/message")
async def streamable_http_post(request: Request, _: None = Depends(_check_bearer)):
    """
    Streamable HTTP 主端点：POST JSON-RPC，返回 200 + JSON。
    调用 asr_stream 时若带 Mcp-Session-Id（与 GET /message 建连时的会话一致），
    该 ASR 的推送消息仅会发给该 GET 连接。
    """
    body = await _read_json_body(request)
    if body is None:
        return _jsonrpc_parse_error()
    connection_id = request.headers.get("Mcp-Session-Id") or ""
    if connection_id:
        set_connection_id(connection_id.strip())
    try:
        response = await server.handle_request(body)
        return response
    finally:
        set_connection_id(None)


@app.get("/message")
async def streamable_http_get(request: Request, _: None = Depends(_check_bearer)):
    """
    Streamable HTTP GET：建立 SSE 流，返回 Mcp-Session-Id。
    仅会收到「本连接发起的 asr_stream」对应的 asr.partial/final/done（需 POST 时带相同 Mcp-Session-Id）。
    """
    connection_id = request.headers.get("Mcp-Session-Id") or str(uuid.uuid4())

    async def gen():
        queue = asyncio.Queue()

        def on_msg(msg):
            queue.put_nowait(msg)

        register_connection(connection_id, on_msg)
        try:
            yield (
                "data: "
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {"type": "endpoint", "uri": "/message"},
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {"type": "session", "session_id": connection_id},
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )

            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            unregister_connection(connection_id)

    res = StreamingResponse(gen(), media_type="text/event-stream")
    res.headers["Mcp-Session-Id"] = connection_id
    res.headers["Cache-Control"] = "no-cache"
    res.headers["X-Accel-Buffering"] = "no"
    return res


@app.get("/sse")
async def sse():
    async def gen():
        queue = asyncio.Queue()

        def on_msg(msg):
            queue.put_nowait(msg)

        subscribe(on_msg)
        try:
            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            unsubscribe(on_msg)

    return StreamingResponse(gen(), media_type="text/event-stream")