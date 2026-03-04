#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Wan 视频生成服务（Wan2.2-TI2V-5B）
- 基于 ModelScope/Wan-AI/Wan2.2-TI2V-5B，支持文本生视频(T2V)与图文生视频(I2V)
- 端口: 8004
"""

import base64
import io
import os
import sys
import uuid
import random
import threading
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from PIL import Image
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

# ========== 路径与配置 ==========
WAN22_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Wan2.2")
CKPT_DIR = "/root/autodl-tmp/models/Wan2.2-TI2V-5B-BF16"
OUTPUT_DIR = os.environ.get("WAN_VIDEO_OUTPUT_DIR", "/tmp/wan_videos")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Wan2.2 ti2v-5B 仅支持两种分辨率（见 wan/configs/__init__.py SUPPORTED_SIZES）
TI2V5B_SIZES = {"1280*704": (1280, 704), "704*1280": (704, 1280)}
TI2V5B_MAX_AREA = {"1280*704": 1280 * 704, "704*1280": 704 * 1280}
# frame_num 须为 4n+1，ti2v_5B 默认 121
FRAME_NUM_MIN, FRAME_NUM_MAX = 25, 121

if WAN22_ROOT not in sys.path:
    sys.path.insert(0, WAN22_ROOT)

# ========== 延迟加载 Pipeline ==========
_pipeline = None
_pipeline_lock = threading.Lock()


def _get_pipeline():
    """单例加载 WanTI2V pipeline（首次调用时加载）"""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        import wan
        from wan.configs import ti2v_5B

        _pipeline = wan.WanTI2V(
            config=ti2v_5B,
            checkpoint_dir=CKPT_DIR,
            device_id=0,
            rank=0,
            t5_fsdp=False,
            dit_fsdp=False,
            use_sp=False,
            t5_cpu=True,
            convert_model_dtype=True,
        )
        return _pipeline


def _size_key(width: int, height: int) -> str:
    """将 API 的 width/height 映射到 ti2v-5B 支持的 size key"""
    if width >= height:
        return "1280*704"
    return "704*1280"


def _frame_num_4n1(num_frames: int) -> int:
    """将 num_frames 转为 4n+1 且在 [FRAME_NUM_MIN, FRAME_NUM_MAX] 内"""
    n = max(0, (num_frames - 1) // 4)
    val = n * 4 + 1
    return max(FRAME_NUM_MIN, min(FRAME_NUM_MAX, val))


def _load_image_from_field(image_value: str):
    """
    将 image 字段解析为 PIL.Image（RGB）。
    支持：http(s) URL、data:image/xxx;base64,xxx、或纯 base64 字符串。
    """
    s = (image_value or "").strip()
    if not s:
        return None
    # data URL
    if s.startswith("data:"):
        try:
            header, b64 = s.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception as e:
            raise ValueError(f"Invalid data URL for image: {e}")
    elif s.startswith("http://") or s.startswith("https://"):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(s)
                resp.raise_for_status()
                raw = resp.content
        except Exception as e:
            raise ValueError(f"Failed to fetch image URL: {e}")
    else:
        try:
            raw = base64.b64decode(s)
        except Exception as e:
            raise ValueError(f"Invalid base64 image: {e}")
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise ValueError(f"Failed to decode image: {e}")
    return img


# ========== FastAPI ==========
app = FastAPI(title="Wan Video API (Wan2.2-TI2V-5B)", version="1.0")
tasks = {}


class T2VRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = ""
    width: Optional[int] = 480
    height: Optional[int] = 480
    num_frames: Optional[int] = 24
    fps: Optional[int] = 24
    seed: Optional[int] = None
    # I2V：首帧/参考图。可选。提供则为图文生视频，不提供则为纯文本生视频。
    # 支持：图片 URL（http/https）、data:image/xxx;base64,xxx、或纯 base64 字符串。
    image: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: Optional[float] = 0.0
    video_url: Optional[str] = None
    error: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "model": "Wan2.2-TI2V-5B"}


@app.post("/v1/video/generate")
async def generate_video(req: T2VRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"status": "pending", "progress": 0.0}
    background_tasks.add_task(run_generation, task_id, req)
    return {"task_id": task_id, "status": "pending"}


def run_generation(task_id: str, req: T2VRequest):
    try:
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = 0.0

        from wan.configs import ti2v_5B
        from wan.utils.utils import save_video

        size_key = _size_key(req.width or 480, req.height or 480)
        size = TI2V5B_SIZES[size_key]
        max_area = TI2V5B_MAX_AREA[size_key]
        frame_num = _frame_num_4n1(req.num_frames or 24)
        seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)

        img = None
        if req.image and (req.image or "").strip():
            img = _load_image_from_field(req.image)

        pipeline = _get_pipeline()
        video = pipeline.generate(
            req.prompt,
            img=img,
            size=size,
            max_area=max_area,
            frame_num=frame_num,
            shift=ti2v_5B.sample_shift,
            sample_solver="unipc",
            sampling_steps=ti2v_5B.sample_steps,
            guide_scale=ti2v_5B.sample_guide_scale,
            n_prompt=(req.negative_prompt or "").strip() or "",
            seed=seed,
            offload_model=True,
        )

        output_path = os.path.join(OUTPUT_DIR, f"{task_id}.mp4")
        save_video(
            tensor=video[None],
            save_file=output_path,
            fps=ti2v_5B.sample_fps,
            nrow=1,
            normalize=True,
            value_range=(-1, 1),
        )

        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 1.0
        tasks[task_id]["video_url"] = f"/v1/video/download/{task_id}"
        del video
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)


@app.get("/v1/video/status/{task_id}")
async def get_task_status(task_id: str):
    task_id = (task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    return TaskStatus(
        task_id=task_id,
        status=t["status"],
        progress=t.get("progress", 0),
        video_url=t.get("video_url"),
        error=t.get("error"),
    )


@app.get("/v1/video/download/{task_id}")
async def download_video(task_id: str):
    task_id = (task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    video_path = os.path.join(OUTPUT_DIR, f"{task_id}.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4", filename=f"{task_id}.mp4")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004)
