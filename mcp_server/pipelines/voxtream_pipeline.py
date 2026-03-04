# -*- coding: utf-8 -*-
"""
VoXtream 流式 TTS 后台任务：调用 VoXtream_service /v1/audio/speech/stream，
按 SSE 收到每个音频块后通过 message_bus 推送 tts.audio_chunk，最后推送 tts.done。
"""

from __future__ import annotations

import json

import aiohttp

from mcp_server.config import TTS_VOXTREAM_HOST
from mcp_server.transports import message_bus
from mcp_server.transports.message_bus import unregister_session_owner


def _jsonrpc_notification(params: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": params,
    }


async def _send_tts_event(event_type: str, session_id: str, **extra) -> None:
    params = {"type": event_type, "session_id": session_id, **extra}
    await message_bus.send(_jsonrpc_notification(params))


def _voxtream_stream_url() -> str:
    return f"http://{TTS_VOXTREAM_HOST}/v1/audio/speech/stream"


async def run_voxtream_pipeline(session_id: str, args: dict) -> None:
    """
    后台 VoXtream 流式 TTS：
    1) POST VoXtream_service /v1/audio/speech/stream
    2) 按 SSE 解析每行 data: {...}，推送 tts.audio_chunk（audio_base64, sample_rate）
    3) 结束或出错时推送 tts.done
    """
    text = (args.get("input") or args.get("text") or "").strip()
    prompt_audio = (args.get("prompt_audio") or args.get("ref_audio") or "").strip()
    prompt_text = (args.get("prompt_text") or args.get("ref_text") or "").strip()
    full_stream = bool(args.get("full_stream", True))

    payload = {
        "text": text,
        "prompt_audio": prompt_audio,
        "prompt_text": prompt_text,
        "full_stream": full_stream,
    }

    try:
        async with aiohttp.ClientSession() as session:
            url = _voxtream_stream_url()
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    await _send_tts_event("tts.done", session_id, error=f"backend status {resp.status}: {body[:200]}")
                    return
                content_type = (resp.headers.get("content-type") or "").lower()
                if "text/event-stream" not in content_type:
                    await _send_tts_event("tts.done", session_id, error="backend did not return SSE")
                    return

                buffer = ""
                async for chunk in resp.content.iter_chunked(8192):
                    if not chunk:
                        continue
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            obj = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if "error" in obj:
                            await _send_tts_event("tts.done", session_id, error=obj["error"])
                            return
                        if "audio_base64" in obj:
                            await _send_tts_event(
                                "tts.audio_chunk",
                                session_id,
                                audio_base64=obj["audio_base64"],
                                sample_rate=obj.get("sample_rate", 24000),
                            )

                if buffer.strip() and buffer.strip().startswith("data:"):
                    try:
                        obj = json.loads(buffer.strip()[5:].strip())
                        if "error" in obj:
                            await _send_tts_event("tts.done", session_id, error=obj["error"])
                        elif "audio_base64" in obj:
                            await _send_tts_event(
                                "tts.audio_chunk",
                                session_id,
                                audio_base64=obj["audio_base64"],
                                sample_rate=obj.get("sample_rate", 24000),
                            )
                    except json.JSONDecodeError:
                        pass
                await _send_tts_event("tts.done", session_id)
    except Exception as e:
        await _send_tts_event("tts.done", session_id, error=str(e))
    finally:
        unregister_session_owner(session_id)
