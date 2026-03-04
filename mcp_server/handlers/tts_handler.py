# -*- coding: utf-8 -*-
"""TTS handler: call backend by fixed port (base/customvoice/voicedesign)."""

import asyncio
import base64
import json
import uuid
from typing import Any

import aiohttp

from mcp_server.config import (
    TTS_PORT_BASE,
    TTS_PORT_BASE_06B,
    TTS_PORT_CUSTOMVOICE,
    TTS_PORT_CUSTOMVOICE_06B,
    TTS_PORT_VOICEDESIGN,
    TTS_TASK_TYPE_BASE,
    TTS_TASK_TYPE_CUSTOMVOICE,
    TTS_TASK_TYPE_VOICEDESIGN,
    TTS_VOXTREAM_HOST,
)
from mcp_server.pipelines.cosyvoice_pipeline import run_cosyvoice_pipeline
from mcp_server.pipelines.qwen3_streaming_pipeline import run_qwen3_streaming_pipeline
from mcp_server.pipelines.voxtream_pipeline import run_voxtream_pipeline
from mcp_server.transports.message_bus import get_connection_id, register_session_owner


def _tts_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1/audio/speech"


def _ref_audio_valid(ref_audio: str) -> bool:
    """vLLM-Omni 要求 ref_audio 为 http(s) URL 或 data: 开头。"""
    s = (ref_audio or "").strip()
    return s.startswith(("http://", "https://")) or s.startswith("data:")


def _tts_payload(args: dict, task_type: str) -> dict | None:
    """Build vllm-omni /v1/audio/speech body. text from input or text."""
    text = args.get("input") or args.get("text")
    if not text or not str(text).strip():
        return None
    payload = {
        "input": str(text),
        "task_type": task_type,
        "speed": args.get("speed", 1.0),
        "response_format": args.get("response_format", "wav"),
    }
    for k in ("voice", "language", "instructions", "ref_audio", "ref_text", "x_vector_only_mode", "max_new_tokens", "model"):
        if k in args and args.get(k) is not None and args.get(k) != "":
            payload[k] = args[k]
    if "voice" not in payload and task_type == TTS_TASK_TYPE_CUSTOMVOICE:
        payload["voice"] = "Vivian"
    return payload


async def call_tts_base(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call TTS Base (8001). Returns raw result dict or error dict."""
    ref_audio = (args.get("ref_audio") or "").strip()
    if not ref_audio:
        return {"error": "Base task requires ref_audio (URL or base64 data URL)"}
    if not _ref_audio_valid(ref_audio):
        return {"error": "ref_audio must be http/https URL or data:...;base64,..."}
    payload = _tts_payload(args, TTS_TASK_TYPE_BASE)
    if not payload:
        return {"error": "Missing text or input"}
    url = _tts_url(TTS_PORT_BASE)
    return await _post_tts(url, payload, session)


async def call_tts_customvoice(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call TTS CustomVoice (8002)."""
    payload = _tts_payload(args, TTS_TASK_TYPE_CUSTOMVOICE)
    if not payload:
        return {"error": "Missing text or input"}
    url = _tts_url(TTS_PORT_CUSTOMVOICE)
    return await _post_tts(url, payload, session)


async def call_tts_voicedesign(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call TTS VoiceDesign . 服务端要求 instructions 必填。"""
    if not args.get("instructions") or not str(args.get("instructions")).strip():
        return {"error": "VoiceDesign task requires 'instructions' to describe the voice"}
    payload = _tts_payload(args, TTS_TASK_TYPE_VOICEDESIGN)
    if not payload:
        return {"error": "Missing text or input"}
    url = _tts_url(TTS_PORT_VOICEDESIGN)
    return await _post_tts(url, payload, session)


async def call_tts_base_06b(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call TTS Base 0.6B (8006)."""
    ref_audio = (args.get("ref_audio") or "").strip()
    if not ref_audio:
        return {"error": "Base task requires ref_audio (URL or base64 data URL)"}
    if not _ref_audio_valid(ref_audio):
        return {"error": "ref_audio must be http/https URL or data:...;base64,..."}
    payload = _tts_payload(args, TTS_TASK_TYPE_BASE)
    if not payload:
        return {"error": "Missing text or input"}
    url = _tts_url(TTS_PORT_BASE_06B)
    return await _post_tts(url, payload, session)


async def call_tts_customvoice_06b(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call TTS CustomVoice 0.6B (8007). 0.6B 不支持 instructions，此处不传给后端。"""
    args = {k: v for k, v in args.items() if k != "instructions"}
    payload = _tts_payload(args, TTS_TASK_TYPE_CUSTOMVOICE)
    if not payload:
        return {"error": "Missing text or input"}
    url = _tts_url(TTS_PORT_CUSTOMVOICE_06B)
    return await _post_tts(url, payload, session)


def _voxtream_url() -> str:
    return f"http://{TTS_VOXTREAM_HOST}/v1/audio/speech"


def _check_prompt_text_english(prompt_text: str) -> None:
    """VoXtream aligner 仅支持英文，prompt_text 须包含英文字母。"""
    import re
    cleaned = re.sub(r"[^a-z'.,?!\-]", "", prompt_text.lower())
    if not cleaned or len(cleaned.strip()) < 2:
        raise ValueError(
            "prompt_text 须包含英文内容（VoXtream 仅支持英文参考）。"
            "若参考音频为中文，请使用英文参考音频或支持中文的 TTS 模型。"
        )


def _validate_voxtream_args(args: dict) -> None:
    """流式 VoXtream 调用前校验参数，不合法则抛出 ValueError。"""
    if not args or not isinstance(args, dict):
        raise ValueError("arguments 不能为空")
    text = args.get("input") or args.get("text")
    if not text or not str(text).strip():
        raise ValueError("缺少必填参数: text 或 input")
    prompt_audio = (args.get("prompt_audio") or args.get("ref_audio") or "").strip()
    if not prompt_audio:
        raise ValueError("VoXtream 需要 prompt_audio（或 ref_audio）")
    if not _ref_audio_valid(prompt_audio):
        raise ValueError("prompt_audio/ref_audio 须为 http(s) URL 或 data:...;base64,...")
    prompt_text = (args.get("prompt_text") or args.get("ref_text") or "").strip()
    if not prompt_text:
        raise ValueError("VoXtream 需要 prompt_text（或 ref_text），即参考音频的转写文本")
    _check_prompt_text_english(prompt_text)


def _validate_cosyvoice_args(args: dict) -> None:
    """CosyVoice 支持中文，无需英文校验。"""
    if not args or not isinstance(args, dict):
        raise ValueError("arguments 不能为空")
    text = args.get("input") or args.get("text")
    if not text or not str(text).strip():
        raise ValueError("缺少必填参数: text 或 input")
    prompt_audio = (args.get("prompt_audio") or args.get("ref_audio") or "").strip()
    if not prompt_audio:
        raise ValueError("CosyVoice 需要 prompt_audio（或 ref_audio）")
    if not _ref_audio_valid(prompt_audio):
        raise ValueError("prompt_audio/ref_audio 须为 http(s) URL 或 data:...;base64,...")
    prompt_text = (args.get("prompt_text") or args.get("ref_text") or "").strip()
    if not prompt_text:
        raise ValueError("CosyVoice 需要 prompt_text（或 ref_text），即参考音频的转写文本")


def _validate_qwen3_streaming_args(args: dict) -> None:
    """Qwen3 streaming 参数校验：text、ref_audio 必填；x_vector_only_mode=false 时 ref_text 必填。"""
    if not args or not isinstance(args, dict):
        raise ValueError("arguments 不能为空")
    text = args.get("input") or args.get("text")
    if not text or not str(text).strip():
        raise ValueError("缺少必填参数: text 或 input")
    ref_audio = (args.get("ref_audio") or args.get("prompt_audio") or "").strip()
    if not ref_audio:
        raise ValueError("Qwen3 streaming 需要 ref_audio（或 prompt_audio）")
    # 支持 URL、base64、本地路径（后端 fork 均支持）
    if ref_audio.startswith(("http://", "https://", "data:")):
        pass  # 格式有效
    elif len(ref_audio) < 2:
        raise ValueError("ref_audio 须为 http(s) URL、data:...;base64,... 或有效路径")
    x_vector_only_mode = bool(args.get("x_vector_only_mode", False))
    if not x_vector_only_mode:
        ref_text = (args.get("ref_text") or args.get("prompt_text") or "").strip()
        if not ref_text:
            raise ValueError(
                "x_vector_only_mode=false 时需提供 ref_text（或 prompt_text），即参考音频转写"
            )


async def call_tts_stream_cosyvoice(args: dict, session) -> dict:
    """
    CosyVoice 流式 TTS（long-running）：支持中文。
    立刻返回 session_id，后台通过 notifications/message 推送 tts.audio_chunk、tts.done。
    """
    _validate_cosyvoice_args(args)
    session_id = f"tts-cosyvoice-{uuid.uuid4().hex}"
    connection_id = get_connection_id()
    if connection_id:
        register_session_owner(session_id, connection_id)
    asyncio.create_task(run_cosyvoice_pipeline(session_id, args))
    return {"session_id": session_id}


async def call_tts_stream_qwen3(args: dict, session) -> dict:
    """
    Qwen3 streaming 流式 TTS（long-running）：基于 dffdeeq/Qwen3-TTS-streaming。
    立刻返回 session_id，后台通过 notifications/message 推送 tts.audio_chunk、tts.done。
    """
    _validate_qwen3_streaming_args(args)
    session_id = f"tts-qwen3-{uuid.uuid4().hex}"
    connection_id = get_connection_id()
    if connection_id:
        register_session_owner(session_id, connection_id)
    asyncio.create_task(run_qwen3_streaming_pipeline(session_id, args))
    return {"session_id": session_id}


async def call_tts_stream_voxtream(args: dict, session) -> dict:
    """
    流式 VoXtream（long-running tool）。
    立刻返回 session_id，后台通过 notifications/message 推送 tts.audio_chunk、tts.done。
    """
    _validate_voxtream_args(args)
    session_id = f"tts-voxtream-{uuid.uuid4().hex}"
    connection_id = get_connection_id()
    if connection_id:
        register_session_owner(session_id, connection_id)
    asyncio.create_task(run_voxtream_pipeline(session_id, args))
    return {"session_id": session_id}


async def call_tts_voxtream(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Call VoXtream 流式 TTS。需 text、prompt_audio、prompt_text；可选 full_stream。"""
    text = args.get("input") or args.get("text")
    if not text or not str(text).strip():
        return {"error": "Missing text or input"}
    prompt_audio = (args.get("prompt_audio") or args.get("ref_audio") or "").strip()
    if not prompt_audio:
        return {"error": "VoXtream 需要 prompt_audio（或 ref_audio）"}
    if not _ref_audio_valid(prompt_audio):
        return {"error": "prompt_audio/ref_audio 须为 http(s) URL 或 data:...;base64,..."}
    prompt_text = (args.get("prompt_text") or args.get("ref_text") or "").strip()
    if not prompt_text:
        return {"error": "VoXtream 需要 prompt_text（或 ref_text），即参考音频的转写文本"}
    payload = {
        "text": str(text).strip(),
        "prompt_audio": prompt_audio,
        "prompt_text": prompt_text,
        "full_stream": bool(args.get("full_stream", True)),
        "response_format": "wav",
        "task_type": "VoXtream",
    }
    url = _voxtream_url()
    return await _post_tts(url, payload, session)


async def _post_tts(
    url: str, payload: dict, session: aiohttp.ClientSession
) -> dict:
    async with session.post(url, json=payload) as resp:
        content_type = (resp.headers.get("content-type") or "").lower()
        raw = await resp.read()
    if "application/json" in content_type:
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            return {
                "error": "tts backend returned json but failed to decode",
                "raw": raw[:200].decode("utf-8", errors="replace"),
            }
    audio_b64 = base64.b64encode(raw).decode("utf-8")
    return {
        "audio_base64": audio_b64,
        "content_type": content_type or "application/octet-stream",
        "bytes": len(raw),
        "tts_model": payload.get("task_type"),
        "response_format": payload.get("response_format"),
    }
