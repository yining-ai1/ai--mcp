# -*- coding: utf-8 -*-
"""Qwen3 streaming TTS 服务配置。"""

from __future__ import annotations

import os

QWEN3_STREAMING_SERVICE_PORT = int(os.getenv("QWEN3_STREAMING_SERVICE_PORT", "8012"))
QWEN3_MODEL_DIR = os.getenv(
    "QWEN3_STREAMING_MODEL_DIR",
    "/root/autodl-tmp/models/Qwen3-TTS-12Hz-1.7B-Base",
)
QWEN3_EMIT_EVERY_FRAMES = int(os.getenv("QWEN3_EMIT_EVERY_FRAMES", "4"))
QWEN3_DECODE_WINDOW_FRAMES = int(os.getenv("QWEN3_DECODE_WINDOW_FRAMES", "80"))
QWEN3_ENABLE_OPTIMIZATIONS = os.getenv("QWEN3_ENABLE_OPTIMIZATIONS", "false").lower() in (
    "1",
    "true",
    "yes",
)
QWEN3_MAX_TEXT_CHARS = int(os.getenv("QWEN3_MAX_TEXT_CHARS", "1000"))
