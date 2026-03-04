# -*- coding: utf-8 -*-
"""
Qwen3 streaming TTS 服务：流式音色克隆。
提供 POST /v1/audio/speech/stream（SSE），基于 dffdeeq/Qwen3-TTS-streaming fork。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import sys
from pathlib import Path

# 若用户 clone 到 autodl-tmp 但未 pip install，可从此路径加载
QWEN3_STREAMING_ROOT = Path(__file__).resolve().parent.parent.parent / "Qwen3-TTS-streaming"
if QWEN3_STREAMING_ROOT.exists() and str(QWEN3_STREAMING_ROOT) not in sys.path:
    sys.path.insert(0, str(QWEN3_STREAMING_ROOT))

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from Qwen3_streaming_service import config as svc_config
from qwen_tts import Qwen3TTSModel

logger = logging.getLogger(__name__)
app = FastAPI(title="Qwen3 Streaming TTS Service", version="1.0")

# 模型实例，启动时加载
_model = None

# Ampere+ GPU 性能优化
torch.set_float32_matmul_precision("high")


@app.on_event("startup")
async def _startup() -> None:
    global _model
    model_dir = svc_config.QWEN3_MODEL_DIR
    if not Path(model_dir).exists():
        raise FileNotFoundError(
            f"Qwen3 模型目录不存在: {model_dir}。"
            f"请设置 QWEN3_STREAMING_MODEL_DIR 或下载模型到该路径。"
        )
    _model = Qwen3TTSModel.from_pretrained(
        model_dir,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="flash_attention_2",
    )
    logger.info("Qwen3 streaming model loaded from %s", model_dir)

    if svc_config.QWEN3_ENABLE_OPTIMIZATIONS:
        _model.enable_streaming_optimizations(
            decode_window_frames=svc_config.QWEN3_DECODE_WINDOW_FRAMES,
            use_compile=True,
            use_cuda_graphs=False,
            compile_mode="reduce-overhead",
            use_fast_codebook=False,
            compile_codebook_predictor=True,
            compile_talker=True,
        )
        logger.info("Qwen3 streaming optimizations enabled")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "Qwen3_streaming_service"}


@app.post("/v1/audio/speech/stream")
async def v1_audio_speech_stream(request: Request):
    """
    流式返回 SSE，每行 data: {"audio_base64":"...","sample_rate":24000}。
    请求体：{text, ref_audio, ref_text?, language?, x_vector_only_mode?}
    x_vector_only_mode=true 时可不传 ref_text。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="需要 JSON 请求体")

    text = (body.get("text") or body.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 或 input")
    ref_audio = (body.get("ref_audio") or body.get("prompt_audio") or "").strip()
    if not ref_audio:
        raise HTTPException(status_code=400, detail="缺少 ref_audio")
    ref_text = (body.get("ref_text") or body.get("prompt_text") or "").strip()
    x_vector_only_mode = bool(body.get("x_vector_only_mode", False))
    if not x_vector_only_mode and not ref_text:
        raise HTTPException(
            status_code=400,
            detail="x_vector_only_mode=false 时需提供 ref_text（参考音频转写）",
        )
    language = (body.get("language") or "Auto").strip()

    if len(text) > svc_config.QWEN3_MAX_TEXT_CHARS:
        text = text[: svc_config.QWEN3_MAX_TEXT_CHARS]

    emit_every = svc_config.QWEN3_EMIT_EVERY_FRAMES
    decode_window = svc_config.QWEN3_DECODE_WINDOW_FRAMES

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def run_inference():
            try:
                prompt_items = _model.create_voice_clone_prompt(
                    ref_audio=ref_audio,
                    ref_text=ref_text or "",
                    x_vector_only_mode=x_vector_only_mode,
                )
                vc_prompt = prompt_items[0]
                for chunk, sr in _model.stream_generate_voice_clone(
                    text=text,
                    language=language,
                    voice_clone_prompt=vc_prompt,
                    emit_every_frames=emit_every,
                    decode_window_frames=decode_window,
                    overlap_samples=0,
                ):
                    queue.put_nowait(("chunk", chunk, sr))
                queue.put_nowait(("done", None, None))
            except Exception as ex:
                queue.put_nowait(("error", str(ex), None))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_inference)

        try:
            while True:
                kind, a, b = await queue.get()
                if kind == "error":
                    yield f"data: {json.dumps({'error': a})}\n\n"
                    return
                if kind == "done":
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return
                chunk, sr = a, b
                buf = io.BytesIO()
                # chunk 为 1D float32 numpy；模型输出可能超出 [-1,1]，需归一化/裁剪避免炸麦
                if chunk.ndim > 1:
                    chunk = np.mean(chunk, axis=-1).astype(np.float32)
                chunk = chunk.astype(np.float32)
                m = np.max(np.abs(chunk)) if chunk.size else 0.0
                if m > 1.0 + 1e-6:
                    chunk = chunk / (m + 1e-12)
                chunk = np.clip(chunk, -1.0, 1.0)
                sf.write(buf, chunk, int(sr) if sr else 24000, format="WAV")
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode("ascii")
                yield f"data: {json.dumps({'audio_base64': b64, 'sample_rate': int(sr) if sr else 24000})}\n\n"
        except Exception as e:
            logger.exception("Qwen3 stream failed: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
