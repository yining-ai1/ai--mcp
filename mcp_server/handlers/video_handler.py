# -*- coding: utf-8 -*-
"""Video handler: Wan 8004 generate / status / download."""

import base64
import json
from typing import Any

import aiohttp

from mcp_server.config import WAN_HOST


async def call_video_generate(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Submit video generation task."""
    payload = {
        "prompt": args["prompt"],
        "negative_prompt": args.get("negative_prompt", ""),
        "width": args.get("width", 480),
        "height": args.get("height", 480),
        "num_frames": args.get("num_frames", 24),
        "fps": args.get("fps", 24),
        "seed": args.get("seed"),
    }
    if args.get("image"):
        payload["image"] = args["image"]
    async with session.post(
        f"http://{WAN_HOST}/v1/video/generate",
        json=payload,
    ) as resp:
        return await resp.json()


async def call_video_status(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Get video task status."""
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return {"error": "task_id is required"}
    async with session.get(
        f"http://{WAN_HOST}/v1/video/status/{task_id}"
    ) as resp:
        return await resp.json()


async def call_video_download(args: dict, session: aiohttp.ClientSession) -> dict | Any:
    """Download video by task_id; return dict with video_base64 or error."""
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return {"error": "task_id is required"}
    async with session.get(
        f"http://{WAN_HOST}/v1/video/download/{task_id}"
    ) as resp:
        raw = await resp.read()
    if resp.status != 200 or len(raw) < 100:
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            return {
                "error": "video download failed",
                "status_code": resp.status,
                "detail": raw[:500].decode("utf-8", errors="replace") if raw else "",
            }
    video_b64 = base64.b64encode(raw).decode("utf-8")
    return {
        "video_base64": video_b64,
        "content_type": resp.headers.get("content-type") or "video/mp4",
        "bytes": len(raw),
        "task_id": task_id,
    }
