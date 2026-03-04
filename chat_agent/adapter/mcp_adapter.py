#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP 适配层：负责 tools/list 与 tools/call 的 HTTP JSON-RPC 调用。

约定：
- MCP 基址由调用方传入（避免 adapter 读取 env，便于复用与测试）
- tools/call 返回 result.content：数组，项为 {type: "audio"|"video"|"text", ...}
  - audio: {type, mimeType, data}；video: {type, mimeType, data}；text: {type, text}
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx

from chat_agent import config

# TTS tool names (server exposes three separate tools)
TTS_TOOL_NAMES = frozenset({
    "tts_generate_base",
    "tts_generate_customvoice",
    "tts_generate_voicedesign",
})

MIME_TO_EXT = {
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
    "audio/pcm": "pcm",
    "audio/aac": "aac",
    "audio/opus": "opus",
}


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:2000], "status_code": resp.status_code}


def _mcp_call(mcp_base: str, method: str, params: dict | None = None) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    with httpx.Client(timeout=config.MCP_TIMEOUT, verify=False) as client:
        resp = client.post(f"{mcp_base.rstrip('/')}/mcp", json=payload)
        return _safe_json(resp)


def _get_content_list(resp: dict) -> list[dict]:
    """Extract result.content from MCP tools/call response."""
    return resp.get("result", {}).get("content", [])


def _parse_mcp_tool_call_result(resp: dict) -> tuple[list[dict], Any]:
    """
    Parse MCP tools/call response. Returns (content_list, fallback_parsed).
    - content_list: result.content array (items with type audio/video/text).
    - fallback_parsed: if single text item, parsed JSON or raw; else None (caller uses content_list).
    """
    content = _get_content_list(resp)
    if not content:
        return [], resp
    # New format: list of {type, mimeType?, data? | text?}
    if isinstance(content[0], dict) and content[0].get("type") in ("audio", "video", "text"):
        return content, None
    # Legacy: single item with "text" (JSON string)
    text = content[0].get("text", "") if content else ""
    if not text:
        return content, resp
    try:
        return content, json.loads(text)
    except Exception:
        return content, resp


def mcp_tools_to_openai_tools(mcp_base: str) -> list[dict]:
    """
    调用 MCP tools/list，并转换为 OpenAI tools 格式。
    """
    resp = _mcp_call(mcp_base, "tools/list", {})
    tools = resp.get("result", {}).get("tools", [])
    out: list[dict] = []
    for t in tools or []:
        try:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                }
            )
        except Exception:
            continue
    return out


def execute_mcp_tool(
    mcp_base: str,
    name: str,
    arguments: dict,
) -> tuple[str, str | None, str | None, str | None]:
    """
    执行单个 MCP 工具。
    返回：(tool_result_for_llm, audio_path, video_task_id, video_path)
    """
    audio_path: str | None = None
    video_task_id: str | None = None
    video_path: str | None = None

    try:
        resp = _mcp_call(mcp_base, "tools/call", {"name": name, "arguments": arguments})
        content_list, legacy_parsed = _parse_mcp_tool_call_result(resp)

        # New MCP content format: content is list of {type, ...}
        if content_list and isinstance(content_list[0], dict):
            text_parts = []
            for item in content_list:
                t = item.get("type")
                if t == "audio" and item.get("data"):
                    try:
                        audio_bytes = base64.b64decode(item["data"])
                    except Exception as e:
                        return json.dumps({"error": f"decode audio failed: {e}"}, ensure_ascii=False), None, None, None
                    mime = item.get("mimeType", "audio/wav")
                    ext = MIME_TO_EXT.get(mime, "wav")
                    audio_path = f"/tmp/chat_tts_{uuid.uuid4().hex}.{ext}"
                    with open(audio_path, "wb") as f:
                        f.write(audio_bytes)
                    text_parts.append(
                        json.dumps(
                            {
                                "status": "ok",
                                "message": "语音已生成（音频将由播放器展示）",
                                "response_format": ext,
                                "audio_bytes": len(audio_bytes),
                            },
                            ensure_ascii=False,
                        )
                    )
                elif t == "video" and item.get("data"):
                    try:
                        video_bytes = base64.b64decode(item["data"])
                    except Exception as e:
                        return json.dumps({"error": f"decode video failed: {e}"}, ensure_ascii=False), None, None, None
                    video_path = f"/tmp/chat_video_{uuid.uuid4().hex}.mp4"
                    with open(video_path, "wb") as f:
                        f.write(video_bytes)
                    text_parts.append(
                        json.dumps(
                            {
                                "status": "ok",
                                "message": "视频已下载（将由播放器展示）",
                                "bytes": len(video_bytes),
                                "task_id": arguments.get("task_id"),
                            },
                            ensure_ascii=False,
                        )
                    )
                elif t == "text":
                    text_parts.append(item.get("text", ""))

            if text_parts:
                tool_result = text_parts[0] if len(text_parts) == 1 else json.dumps({"messages": text_parts}, ensure_ascii=False)
            else:
                tool_result = json.dumps(resp, ensure_ascii=False)

            # Check for error in first text part
            if content_list and content_list[0].get("type") == "text":
                raw_text = content_list[0].get("text", "")
                try:
                    obj = json.loads(raw_text)
                    if isinstance(obj, dict) and obj.get("error"):
                        return tool_result, audio_path, video_task_id, video_path
                except Exception:
                    pass

            # video_generate: extract task_id from text content
            if name == "video_generate" and content_list and content_list[0].get("type") == "text":
                try:
                    obj = json.loads(content_list[0].get("text", "{}"))
                    if isinstance(obj, dict):
                        tid = obj.get("task_id") or obj.get("id")
                        if isinstance(tid, str) and tid.strip():
                            video_task_id = tid.strip()
                except Exception:
                    pass

            return tool_result, audio_path, video_task_id, video_path

        # Legacy path: single text blob (parsed as JSON)
        result = legacy_parsed if legacy_parsed is not None else resp
        if isinstance(result, dict) and result.get("error"):
            return json.dumps(result, ensure_ascii=False), None, None, None

        if name in TTS_TOOL_NAMES and isinstance(result, dict) and result.get("audio_base64"):
            try:
                audio_bytes = base64.b64decode(result["audio_base64"])
            except Exception as e:
                return json.dumps({"error": f"decode audio_base64 failed: {e}"}, ensure_ascii=False), None, None, None
            ext = (result.get("response_format") or arguments.get("response_format") or "wav").strip().lower()
            if ext not in ("wav", "mp3", "flac", "pcm", "aac", "opus"):
                ext = "wav"
            audio_path = f"/tmp/chat_tts_{uuid.uuid4().hex}.{ext}"
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
            summary = {
                "status": "ok",
                "message": "语音已生成（音频将由播放器展示）",
                "response_format": ext,
                "audio_bytes": len(audio_bytes),
            }
            return json.dumps(summary, ensure_ascii=False), audio_path, None, None

        if name == "video_generate" and isinstance(result, dict):
            tid = result.get("task_id") or result.get("id")
            if isinstance(tid, str) and tid.strip():
                video_task_id = tid.strip()
            return json.dumps(result, ensure_ascii=False), None, video_task_id, None

        if name == "video_status":
            return json.dumps(result, ensure_ascii=False), None, None, None

        if name == "video_download" and isinstance(result, dict) and result.get("video_base64"):
            try:
                video_bytes = base64.b64decode(result["video_base64"])
            except Exception as e:
                return json.dumps({"error": f"decode video_base64 failed: {e}"}, ensure_ascii=False), None, None, None
            video_path = f"/tmp/chat_video_{uuid.uuid4().hex}.mp4"
            with open(video_path, "wb") as f:
                f.write(video_bytes)
            summary = {
                "status": "ok",
                "message": "视频已下载（将由播放器展示）",
                "bytes": len(video_bytes),
                "task_id": result.get("task_id") or arguments.get("task_id"),
            }
            return json.dumps(summary, ensure_ascii=False), None, None, video_path

        return json.dumps(result, ensure_ascii=False), None, None, None

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False), None, None, None
