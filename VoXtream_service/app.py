# -*- coding: utf-8 -*-
"""FastAPI 应用：启动时加载 VoXtream，提供 TTS HTTP API（支持流式生成、一次性返回 WAV）。"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import tempfile
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


def _check_prompt_text_for_aligner(prompt_text: str) -> None:
    """
    VoXtream 使用 Charsiu 英文 aligner，prompt_text 须包含可识别的英文内容。
    _get_words 会过滤掉非 a-z 字符，若过滤后为空会触发 get_phone_ids 的 IndexError。
    """
    import re
    cleaned = re.sub(r"[^a-z'.,?!\-]", "", prompt_text.lower())
    if not cleaned or len(cleaned.strip()) < 2:
        raise ValueError(
            "prompt_text 须包含英文内容（VoXtream aligner 仅支持英文）。"
            "若参考音频为中文，请先用英文参考音频测试，或使用支持中文的 TTS 模型。"
        )


import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from VoXtream_service import config as svc_config

app = FastAPI(title="VoXtream Service", version="1.0")


def _resolve_prompt_audio_to_path(prompt_audio: str) -> Path:
    """将 prompt_audio（URL 或 data:...;base64,...）转为本地临时文件 Path。"""
    s = (prompt_audio or "").strip()
    if not s:
        raise ValueError("prompt_audio 必填")
    if s.startswith("data:"):
        try:
            _, b64 = s.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception as e:
            raise ValueError(f"无效的 data URL: {e}") from e
        suf = ".wav"
        if "audio/" in (s.split(";")[0] or "").lower():
            if "mp3" in s:
                suf = ".mp3"
            elif "ogg" in s:
                suf = ".ogg"
        f = tempfile.NamedTemporaryFile(suffix=suf, delete=False)
        f.write(raw)
        f.close()
        return Path(f.name)
    if s.startswith("http://") or s.startswith("https://"):
        import urllib.request
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            urllib.request.urlretrieve(s, tmp.name)
            return Path(tmp.name)
    raise ValueError("prompt_audio 须为 http(s) URL 或 data:...;base64,...")


def _maybe_patch_hf_hub_for_local_model() -> None:
    """若设置了 VOXTREAM_LOCAL_MODEL_DIR，让 Voxtream 从本地加载主模型，不拉 HF。"""
    local_dir = getattr(svc_config, "VOXTREAM_LOCAL_MODEL_DIR", None)
    if not local_dir:
        return
    local_path = Path(local_dir)
    if not local_path.is_dir():
        return
    local_files = {"model.safetensors", "config.json", "phoneme_to_token.json"}
    if not all((local_path / f).exists() for f in local_files):
        return

    from huggingface_hub import hf_hub_download as _orig

    def _patched(repo_id: str, filename: str, **kwargs):
        if repo_id in ("herimor/voxtream", "AI-ModelScope/voxtream") and filename in local_files:
            p = local_path / filename
            if p.exists():
                return str(p)
        return _orig(repo_id, filename, **kwargs)

    import huggingface_hub
    huggingface_hub.hf_hub_download = _patched


@app.on_event("startup")
async def _startup() -> None:
    _maybe_patch_hf_hub_for_local_model()

    config_path = Path(svc_config.VOXTREAM_CONFIG_PATH)
    if not config_path.exists():
        raise FileNotFoundError(
            f"VoXtream 配置不存在: {config_path}。"
            "请从 https://github.com/herimor/voxtream 仓库复制 configs/generator.json 到该路径，或设置 VOXTREAM_CONFIG_PATH。"
        )
    with open(config_path) as f:
        cfg_dict = json.load(f)
    from voxtream.generator import SpeechGenerator, SpeechGeneratorConfig
    cfg = SpeechGeneratorConfig(**cfg_dict)
    app.state.generator = SpeechGenerator(cfg)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "VoXtream_service"}


@app.post("/v1/audio/speech")
async def v1_audio_speech(request: Request):
    """
    请求体 JSON: text, prompt_audio (URL 或 data:base64), prompt_text [, full_stream=false]。
    返回: 完整 WAV 二进制（内部为流式生成，对外一次性返回）。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="需要 JSON 请求体")
    text = (body.get("text") or body.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 或 input")
    prompt_audio = (body.get("prompt_audio") or "").strip()
    if not prompt_audio:
        raise HTTPException(status_code=400, detail="缺少 prompt_audio")
    prompt_text = (body.get("prompt_text") or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="缺少 prompt_text")
    try:
        _check_prompt_text_for_aligner(prompt_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    full_stream = bool(body.get("full_stream", False))

    if len(text) > svc_config.VOXTREAM_MAX_TEXT_CHARS:
        text = text[: svc_config.VOXTREAM_MAX_TEXT_CHARS]

    prompt_path = None
    try:
        prompt_path = _resolve_prompt_audio_to_path(prompt_audio)
        gen = app.state.generator
        if full_stream:
            from voxtream.utils.generator import text_generator
            text_input = text_generator(text)
        else:
            text_input = text

        def run_stream():
            s = gen.generate_stream(
                prompt_text=prompt_text,
                prompt_audio_path=prompt_path,
                text=text_input,
            )
            return [af for af, _ in s]

        frames = await asyncio.to_thread(run_stream)
        if not frames:
            raise HTTPException(status_code=500, detail="未生成任何音频")
        audio = np.concatenate(frames)
        sr = gen.config.mimi_sr
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("VoXtream generate_stream failed: %s", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if prompt_path and prompt_path.exists():
            try:
                prompt_path.unlink()
            except Exception:
                pass


@app.post("/v1/audio/speech/stream")
async def v1_audio_speech_stream(request: Request):
    """
    流式返回：Server-Sent Events，每行一个 JSON：{"audio_base64": "...", "sample_rate": 24000}。
    请求体同 /v1/audio/speech；full_stream 建议 true 以配合 LLM 逐词场景。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="需要 JSON 请求体")
    text = (body.get("text") or body.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 或 input")
    prompt_audio = (body.get("prompt_audio") or "").strip()
    if not prompt_audio:
        raise HTTPException(status_code=400, detail="缺少 prompt_audio")
    prompt_text = (body.get("prompt_text") or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="缺少 prompt_text")
    try:
        _check_prompt_text_for_aligner(prompt_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    full_stream = bool(body.get("full_stream", True))

    if len(text) > svc_config.VOXTREAM_MAX_TEXT_CHARS:
        text = text[: svc_config.VOXTREAM_MAX_TEXT_CHARS]

    async def event_stream():
        prompt_path = None
        try:
            prompt_path = _resolve_prompt_audio_to_path(prompt_audio)
            gen = app.state.generator
            if full_stream:
                from voxtream.utils.generator import text_generator
                text_input = text_generator(text)
            else:
                text_input = text

            def collect_frames():
                s = gen.generate_stream(
                    prompt_text=prompt_text,
                    prompt_audio_path=prompt_path,
                    text=text_input,
                )
                return [af for af, _ in s]

            frames = await asyncio.to_thread(collect_frames)
            sr = gen.config.mimi_sr
            for audio_frame in frames:
                buf = io.BytesIO()
                sf.write(buf, audio_frame, sr, format="WAV")
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode("ascii")
                yield f"data: {json.dumps({'audio_base64': b64, 'sample_rate': sr})}\n\n"
        except Exception as e:
            logger.exception("VoXtream generate_stream failed: %s", e)
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if prompt_path and getattr(prompt_path, "exists", lambda: False) and prompt_path.exists():
                try:
                    prompt_path.unlink()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
