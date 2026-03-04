from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from typing import Any

import aiohttp
import numpy as np

from mcp_server.config import ASR_HOST
from mcp_server.transports import message_bus
from mcp_server.transports.message_bus import unregister_session_owner


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _decode_audio_source_to_bytes(audio_source: str) -> bytes:
    """
    支持：
    - URL：交由调用方下载（这里不处理）
    - data-url：data:audio/xxx;base64,....
    - base64：纯 base64 字符串
    """
    s = (audio_source or "").strip()
    if not s:
        raise ValueError("audio_source is required")
    if s.startswith("data:"):
        # data:audio/wav;base64,xxxx
        try:
            header, b64 = s.split(",", 1)
        except ValueError:
            raise ValueError("invalid data URL")
        if ";base64" not in header.lower():
            raise ValueError("data URL must be base64 encoded")
        return base64.b64decode(b64)
    # 纯 base64
    return base64.b64decode(s)


def _pcm16k_float32_mono_from_audio_bytes(audio_bytes: bytes) -> np.ndarray:
    """
    用 ffmpeg 把任意音频解码为：16kHz, mono, float32 PCM（f32le）。
    依赖系统存在 ffmpeg。
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "pipe:1",
    ]
    p = subprocess.run(
        cmd,
        input=audio_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode != 0:
        detail = (p.stderr or b"")[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg decode failed: {detail}")
    raw = p.stdout or b""
    if len(raw) % 4 != 0:
        raise RuntimeError("ffmpeg output length not multiple of 4 (float32)")
    pcm = np.frombuffer(raw, dtype=np.float32).reshape(-1)
    return pcm


def _jsonrpc_notification(params: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": params,
    }


async def _send_asr_event(event_type: str, session_id: str, **extra: Any) -> None:
    params = {"type": event_type, "session_id": session_id, **extra}
    await message_bus.send(_jsonrpc_notification(params))


async def run_asr_pipeline(session_id: str, args: dict) -> None:
    """
    后台 ASR 任务：
    1) 拉取/解码音频为 16k float32 PCM
    2) 调用 asr_service：start -> chunk* -> finish
    3) 持续发送 notifications/message: asr.partial / asr.final（可选 asr.done）
    """
    audio_source = (args.get("audio_source") or "").strip()
    lang = args.get("lang")
    if lang is not None:
        lang = str(lang).strip() or None

    try:
        async with aiohttp.ClientSession() as session:
            # 1) 获取音频 bytes
            if _is_url(audio_source):
                async with session.get(audio_source) as resp:
                    audio_bytes = await resp.read()
                    if resp.status != 200 or not audio_bytes:
                        raise RuntimeError(f"failed to download audio_source, status={resp.status}")
            else:
                audio_bytes = _decode_audio_source_to_bytes(audio_source)

            # 2) 解码 -> PCM float32 16k mono
            # ffmpeg 解码是阻塞操作（subprocess.run），必须放到线程里，避免阻塞事件循环
            pcm = await asyncio.to_thread(_pcm16k_float32_mono_from_audio_bytes, audio_bytes)
            if pcm.size == 0:
                raise RuntimeError("decoded pcm is empty")

            # 3) 启动 asr_service session
            async with session.post(
                f"http://{ASR_HOST}/api/start",
                json={"language": lang} if lang else {},
            ) as resp:
                start_obj = await resp.json()
                if resp.status != 200 or "session_id" not in start_obj:
                    raise RuntimeError(f"asr_service /api/start failed: {json.dumps(start_obj, ensure_ascii=False)}")
                backend_sid = str(start_obj["session_id"]).strip()
                if not backend_sid:
                    raise RuntimeError("asr_service returned empty session_id")

            # 4) 按块送入（按 1s chunk；与 asr_service 默认 chunk_size_sec=1.0 对齐）
            sr = 16000
            chunk_samples = sr  # 1.0 sec
            last_text = ""
            for i in range(0, pcm.size, chunk_samples):
                chunk = pcm[i : i + chunk_samples]
                if chunk.size == 0:
                    continue
                async with session.post(
                    f"http://{ASR_HOST}/api/chunk",
                    params={"session_id": backend_sid},
                    data=chunk.astype(np.float32, copy=False).tobytes(),
                    headers={"Content-Type": "application/octet-stream"},
                ) as resp:
                    obj = await resp.json()
                    if resp.status != 200:
                        raise RuntimeError(f"asr_service /api/chunk failed: {json.dumps(obj, ensure_ascii=False)}")
                    text = str(obj.get("text") or "")
                    if text and text != last_text:
                        last_text = text
                        await _send_asr_event("asr.partial", session_id, text=text)

            # 5) 结束会话
            async with session.post(
                f"http://{ASR_HOST}/api/finish",
                params={"session_id": backend_sid},
            ) as resp:
                obj = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"asr_service /api/finish failed: {json.dumps(obj, ensure_ascii=False)}")
                final_text = str(obj.get("text") or last_text or "")

            await _send_asr_event("asr.final", session_id, text=final_text)
            await _send_asr_event("asr.done", session_id)

    except Exception as e:
        # 发生错误也以 final/done 结束，避免客户端永远等不到终止事件
        await _send_asr_event("asr.final", session_id, text="", error=str(e))
        await _send_asr_event("asr.done", session_id, error=str(e))
    finally:
        unregister_session_owner(session_id)
