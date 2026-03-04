# -*- coding: utf-8 -*-
"""
CosyVoice TTS 服务：支持中文、流式、零样本音色克隆。
提供 /v1/audio/speech 与 /v1/audio/speech/stream（SSE）。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import sys
import tempfile
import traceback
from pathlib import Path

# CosyVoice 需从 CosyVoice 仓库根目录加载
COSYVOICE_ROOT = Path(__file__).resolve().parent.parent / "CosyVoice"
if str(COSYVOICE_ROOT) not in sys.path:
    sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(COSYVOICE_ROOT / "third_party" / "Matcha-TTS"))

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from CosyVoice_service import config as svc_config  # noqa: E402

logger = logging.getLogger(__name__)
app = FastAPI(title="CosyVoice Service", version="1.0")

# 模型实例，启动时加载
_cosyvoice = None


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


def _format_prompt_text(prompt_text: str) -> str:
    """CosyVoice3 零样本需带前缀；若无则自动添加。"""
    t = (prompt_text or "").strip()
    if "<|endofprompt|>" in t:
        return t
    return f"You are a helpful assistant.<|endofprompt|>{t}"


@app.on_event("startup")
async def _startup() -> None:
    global _cosyvoice
    model_dir = svc_config.COSYVOICE_MODEL_DIR
    if not Path(model_dir).exists():
        raise FileNotFoundError(
            f"CosyVoice 模型目录不存在: {model_dir}。"
            f"请设置 COSYVOICE_MODEL_DIR 或下载模型到该路径。"
        )
    from cosyvoice.cli.cosyvoice import AutoModel
    _cosyvoice = AutoModel(model_dir=model_dir)
    logger.info("CosyVoice model loaded from %s", model_dir)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "CosyVoice_service"}


@app.post("/v1/audio/speech")
async def v1_audio_speech(request: Request):
    """一次性返回完整 WAV。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="需要 JSON 请求体")
    text = (body.get("text") or body.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 或 input")
    prompt_audio = (body.get("prompt_audio") or body.get("ref_audio") or "").strip()
    if not prompt_audio:
        raise HTTPException(status_code=400, detail="缺少 prompt_audio")
    prompt_text = (body.get("prompt_text") or body.get("ref_text") or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="缺少 prompt_text（参考音频转写）")
    stream_req = bool(body.get("full_stream", False))
    if len(text) > svc_config.COSYVOICE_MAX_TEXT_CHARS:
        text = text[: svc_config.COSYVOICE_MAX_TEXT_CHARS]

    prompt_path = None
    try:
        prompt_path = _resolve_prompt_audio_to_path(prompt_audio)
        prompt_text_fmt = _format_prompt_text(prompt_text)

        def run_inference():
            frames = []
            for out in _cosyvoice.inference_zero_shot(text, prompt_text_fmt, str(prompt_path), stream=stream_req):
                frames.append(out["tts_speech"].numpy())
            return np.concatenate(frames, axis=1) if frames else np.zeros((1, 0))

        audio = await asyncio.to_thread(run_inference)
        sr = _cosyvoice.sample_rate
        buf = io.BytesIO()
        sf.write(buf, audio.T, sr, format="WAV")
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("CosyVoice inference failed: %s", e)
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
    """流式返回 SSE，每行 data: {"audio_base64":"...","sample_rate":22050}。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="需要 JSON 请求体")
    text = (body.get("text") or body.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 或 input")
    prompt_audio = (body.get("prompt_audio") or body.get("ref_audio") or "").strip()
    if not prompt_audio:
        raise HTTPException(status_code=400, detail="缺少 prompt_audio")
    prompt_text = (body.get("prompt_text") or body.get("ref_text") or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="缺少 prompt_text")
    stream_req = bool(body.get("full_stream", True))
    if len(text) > svc_config.COSYVOICE_MAX_TEXT_CHARS:
        text = text[: svc_config.COSYVOICE_MAX_TEXT_CHARS]

    async def event_stream():
        prompt_path = None
        try:
            prompt_path = _resolve_prompt_audio_to_path(prompt_audio)
            prompt_text_fmt = _format_prompt_text(prompt_text)

            queue: asyncio.Queue = asyncio.Queue()

            def run_inference():
                try:
                    for out in _cosyvoice.inference_zero_shot(text, prompt_text_fmt, str(prompt_path), stream=stream_req):
                        queue.put_nowait(("chunk", out["tts_speech"].numpy()))
                    queue.put_nowait(("done", None))
                except Exception as ex:
                    queue.put_nowait(("error", str(ex)))

            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, run_inference)

            sr = _cosyvoice.sample_rate
            while True:
                kind, data = await queue.get()
                if kind == "error":
                    raise RuntimeError(data)
                if kind == "done":
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
                buf = io.BytesIO()
                sf.write(buf, data.T, sr, format="WAV")
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode("ascii")
                yield f"data: {json.dumps({'audio_base64': b64, 'sample_rate': sr})}\n\n"
        except Exception as e:
            logger.exception("CosyVoice stream failed: %s", e)
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
