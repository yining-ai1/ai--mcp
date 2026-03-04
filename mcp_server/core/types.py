# -*- coding: utf-8 -*-
"""MCP content types: build text/audio/video content from raw handler result."""

import json
from typing import Any


TTS_TOOL_NAMES = frozenset({
    "tts_generate_base",
    "tts_generate_customvoice",
    "tts_generate_voicedesign",
    "tts_generate_base_06b",
    "tts_generate_customvoice_06b",
})


def _mime_for_audio_format(fmt: str) -> str:
    fmt = (fmt or "wav").strip().lower()
    m = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "pcm": "audio/pcm",
        "aac": "audio/aac",
        "opus": "audio/opus",
    }
    return m.get(fmt, "audio/wav")


def build_content_for_tool_result(tool_name: str, raw_result: Any) -> list[dict]:
    """
    Convert raw tool result to MCP content list.
    - TTS success: [{"type": "audio", "mimeType": "...", "data": "<base64>"}]
    - video_download success: [{"type": "video", "mimeType": "video/mp4", "data": "<base64>"}]
    - Error or text-only: [{"type": "text", "text": "..."}]
    """
    if not isinstance(raw_result, dict):
        return [{"type": "text", "text": json.dumps(raw_result, ensure_ascii=False)}]

    if raw_result.get("error"):
        text = json.dumps(raw_result, ensure_ascii=False)
        return [{"type": "text", "text": text}]

    if tool_name in TTS_TOOL_NAMES and raw_result.get("audio_base64"):
        fmt = raw_result.get("response_format", "wav")
        return [
            {
                "type": "audio",
                "mimeType": _mime_for_audio_format(fmt),
                "data": raw_result["audio_base64"],
            }
        ]

    if tool_name == "video_download" and raw_result.get("video_base64"):
        return [
            {
                "type": "video",
                "mimeType": raw_result.get("content_type", "video/mp4"),
                "data": raw_result["video_base64"],
            }
        ]

    return [{"type": "text", "text": json.dumps(raw_result, ensure_ascii=False)}]
