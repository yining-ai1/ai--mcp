#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 tts_stream_cosyvoice MCP 工具：
1. 用 tts_generate_customvoice 生成参考音频
2. 用该参考音频调用 tts_stream_cosyvoice 流式合成
3. 将流式结果保存为 WAV 文件

前置条件：
- MCP server 运行在 127.0.0.1:6006
- CosyVoice_service 运行在 127.0.0.1:8011
- CustomVoice 服务运行在 127.0.0.1:8002（用于生成参考音频）
"""

import base64
import io
import json
import os
import sys
import threading
import time
import wave

import requests

MCP_BASE = os.getenv("MCP_BASE", "http://127.0.0.1:6006")
OUTPUT_WAV = os.getenv("OUTPUT_WAV", "/tmp/cosyvoice_test_output.wav")
# 若 CustomVoice 未启动，可设置 PROMPT_AUDIO_URL 为参考音频的 http(s) URL，同时设置 PROMPT_TEXT
PROMPT_AUDIO_URL = os.getenv("PROMPT_AUDIO_URL", "")
# 参考音频转写（与音频内容逐字一致）
PROMPT_TEXT = os.getenv("PROMPT_TEXT", "希望你以后能够做的比我还好呦。")
# CosyVoice 要合成的目标文本
TARGET_TEXT = "你好，这是一次 CosyVoice 流式 TTS 的测试。"


def call_tool(name: str, arguments: dict) -> dict:
    """POST tools/call 并返回 result 或 error。"""
    resp = requests.post(
        f"{MCP_BASE}/message",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"JSON-RPC error: {data['error']}")
    return data.get("result", {})


def get_ref_audio() -> str:
    """
    获取参考音频。
    若 PROMPT_AUDIO_URL 已设置，直接使用该 URL；
    否则调用 tts_generate_customvoice 生成，返回 data:audio/wav;base64,... 或 http URL。
    """
    if PROMPT_AUDIO_URL.strip():
        print("[1/4] 使用 PROMPT_AUDIO_URL 作为参考音频...")
        return PROMPT_AUDIO_URL.strip()

    print("[1/4] 调用 tts_generate_customvoice 生成参考音频...")
    result = call_tool(
        "tts_generate_customvoice",
        {"text": PROMPT_TEXT, "voice": "Vivian"},
    )
    content = result.get("content") or []
    for c in content:
        if c.get("type") == "audio" and c.get("data"):
            b64 = c["data"]
            return f"data:audio/wav;base64,{b64}"
        if c.get("type") == "text" and "error" in (c.get("text") or "").lower():
            raise RuntimeError(f"CustomVoice 返回错误: {c.get('text')}")
    raise RuntimeError("tts_generate_customvoice 未返回音频，请确认 CustomVoice 服务 (8002) 已启动")


def run_cosyvoice_stream(prompt_audio: str) -> str:
    """建立 SSE，调用 tts_stream_cosyvoice，收集音频块并保存为 WAV。返回输出路径。"""
    print("[2/4] 建立 SSE 连接...")
    conn_session_id = None
    tts_session_id_ref: dict = {}  # 主线程写入 tts session_id
    chunks: list = []
    done: dict = {"received": False, "error": None, "sample_rate": 22050}

    def run_sse():
        nonlocal conn_session_id
        with requests.get(
            f"{MCP_BASE}/message",
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=180,
        ) as r:
            r.raise_for_status()
            conn_session_id = r.headers.get("Mcp-Session-Id")
            buf = ""
            for line in r.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if line.startswith("data:"):
                    buf = line[5:].strip()
                elif line == "" and buf:
                    try:
                        obj = json.loads(buf)
                        params = obj.get("params") or {}
                        t = params.get("type")
                        if t == "session" and params.get("session_id"):
                            conn_session_id = conn_session_id or params.get("session_id")
                        sid = tts_session_id_ref.get("id")
                        if sid and params.get("session_id") == sid:
                            if t == "tts.audio_chunk":
                                b64 = params.get("audio_base64")
                                if b64:
                                    chunks.append(b64)
                                    if "sample_rate" not in done or done.get("sample_rate") is None:
                                        done["sample_rate"] = params.get("sample_rate", 22050)
                            elif t == "tts.done":
                                done["error"] = params.get("error")
                                done["received"] = True
                                return
                    except json.JSONDecodeError:
                        pass
                    buf = ""

    th = threading.Thread(target=run_sse, daemon=True)
    th.start()
    for _ in range(20):
        time.sleep(0.25)
        if conn_session_id:
            break
    if not conn_session_id:
        raise RuntimeError("未能获取 Mcp-Session-Id")
    print(f"      Mcp-Session-Id: {conn_session_id}")

    print("[3/4] 调用 tts_stream_cosyvoice...")
    result = requests.post(
        f"{MCP_BASE}/message",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "tts_stream_cosyvoice",
                "arguments": {
                    "text": TARGET_TEXT,
                    "prompt_audio": prompt_audio,
                    "prompt_text": PROMPT_TEXT,
                },
            },
        },
        headers={"Content-Type": "application/json", "Mcp-Session-Id": conn_session_id},
        timeout=30,
    )
    result.raise_for_status()
    data = result.json()
    sid = (data.get("result") or {}).get("session_id")
    if not sid:
        err = data.get("error") or data
        raise RuntimeError(f"tts_stream_cosyvoice 调用失败: {err}")
    tts_session_id_ref["id"] = sid

    # 等待 tts.done
    for _ in range(120):
        if done["received"]:
            break
        time.sleep(0.5)
    th.join(timeout=3)

    if done.get("error"):
        raise RuntimeError(f"CosyVoice 流式合成失败: {done['error']}")
    if not chunks:
        raise RuntimeError("未收到任何音频块")

    print("[4/4] 保存 WAV...")
    sample_rate = done.get("sample_rate") or 22050
    # 每个 chunk 是完整 WAV（CosyVoice_service 用 sf.write 输出），需解析并拼接 PCM
    pcm_frames = []
    for c in chunks:
        raw = base64.b64decode(c)
        with wave.open(io.BytesIO(raw), "rb") as w:
            pcm_frames.append(w.readframes(w.getnframes()))
    all_pcm = b"".join(pcm_frames)
    with wave.open(OUTPUT_WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(all_pcm)

    return OUTPUT_WAV


def main():
    print("=" * 50)
    print("CosyVoice MCP 工具测试")
    print(f"  MCP: {MCP_BASE}")
    print(f"  参考句: {PROMPT_TEXT}")
    print(f"  目标句: {TARGET_TEXT}")
    print("=" * 50)

    try:
        prompt_audio = get_ref_audio()
        if prompt_audio.startswith("data:"):
            print(f"      参考音频: base64, {len(prompt_audio)} 字符")
        else:
            print(f"      参考音频: URL")
    except Exception as e:
        print(f"  [错误] {e}")
        print("  提示: 请确保 CustomVoice 服务运行在 127.0.0.1:8002")
        print("  或设置 PROMPT_AUDIO_URL 为参考音频 URL，PROMPT_TEXT 为其转写内容")
        sys.exit(1)

    try:
        out = run_cosyvoice_stream(prompt_audio)
        print(f"  成功! 输出: {out}")
        print(f"  文件大小: {os.path.getsize(out)} bytes")
    except Exception as e:
        print(f"  [错误] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
