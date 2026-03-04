# -*- coding: utf-8 -*-
"""FastAPI 应用：启动时加载 Qwen3-ASR 模型，提供流式 ASR HTTP API。"""

from __future__ import annotations

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from asr_service import config
from asr_service.streaming import create_session, chunk as streaming_chunk, finish_session

app = FastAPI(title="ASR Streaming Service", version="1.0")


@app.on_event("startup")
async def _startup() -> None:
    from qwen_asr import Qwen3ASRModel

    app.state.asr = Qwen3ASRModel.LLM(
        model=config.ASR_MODEL_PATH,
        gpu_memory_utilization=config.ASR_GPU_MEMORY_UTILIZATION,
        max_new_tokens=32,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "asr_service"}


@app.post("/api/start")
async def api_start(request: Request):
    body: dict = {}
    if request.headers.get("content-type", "").strip().lower().startswith("application/json"):
        try:
            body = await request.json()
        except Exception:
            pass
    language = body.get("language")
    if language is not None and not isinstance(language, str):
        language = str(language)
    if language is not None and not language.strip():
        language = None

    asr = app.state.asr
    session_id = create_session(
        asr,
        language=language,
        chunk_size_sec=config.ASR_CHUNK_SIZE_SEC,
        unfixed_chunk_num=config.ASR_UNFIXED_CHUNK_NUM,
        unfixed_token_num=config.ASR_UNFIXED_TOKEN_NUM,
        ttl_sec=config.ASR_SESSION_TTL_SEC,
    )
    return {"session_id": session_id}


@app.post("/api/chunk")
async def api_chunk(request: Request):
    session_id = request.query_params.get("session_id", "").strip()
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid or expired session_id"},
        )
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/octet-stream" not in ctype:
        return JSONResponse(
            status_code=400,
            content={"error": "expect Content-Type: application/octet-stream"},
        )
    raw = await request.body()
    if len(raw) % 4 != 0:
        return JSONResponse(
            status_code=400,
            content={"error": "body length must be multiple of 4 (float32)"},
        )
    pcm = np.frombuffer(raw, dtype=np.float32).reshape(-1)

    asr = app.state.asr
    try:
        language, text = streaming_chunk(
            asr,
            session_id,
            pcm,
            ttl_sec=config.ASR_SESSION_TTL_SEC,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"language": language, "text": text}


@app.post("/api/finish")
async def api_finish(request: Request):
    session_id = request.query_params.get("session_id", "").strip()
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid or expired session_id"},
        )

    asr = app.state.asr
    try:
        language, text = finish_session(asr, session_id, ttl_sec=config.ASR_SESSION_TTL_SEC)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"language": language, "text": text}
