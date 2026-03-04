# -*- coding: utf-8 -*-
"""JSON-RPC / MCP protocol: handle_request, dispatch via registry."""
import aiohttp
from typing import Any

from mcp_server.core import registry, types
from mcp_server.tools import get_tools


class MCPServer:
    def __init__(self):
        self.tools = get_tools()

    async def handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        req_id = request.get("id")

        if method == "initialize":
            return self._response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-tools-server", "version": "1.0.0"},
            })

        if method == "tools/list":
            return self._response(req_id, {"tools": list(self.tools.values())})

        if method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            handler = registry.get(tool_name)
            if handler is None:
                content = types.build_content_for_tool_result(
                    tool_name, {"error": f"Unknown tool: {tool_name}"}
                )
                return self._response(req_id, {"content": content})
            try:
                # long-running 工具：本次 tools/call 只返回 session_id，后续通过 notifications/message 推送
                if tool_name in ("asr_stream", "tts_stream_voxtream", "tts_stream_cosyvoice", "tts_stream_qwen3"):
                    raw_result = await handler(arguments, None)
                    return self._response(req_id, raw_result if isinstance(raw_result, dict) else {"result": raw_result})
                async with aiohttp.ClientSession() as session:
                    raw_result = await handler(arguments, session)
                content = types.build_content_for_tool_result(tool_name, raw_result)
                return self._response(req_id, {"content": content})
            except ValueError as e:
                return self._error(req_id, -32602, f"Invalid params: {e}")

        return self._error(req_id, -32601, f"Method not found: {method}")

    def _response(self, req_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
