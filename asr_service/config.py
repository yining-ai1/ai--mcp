# -*- coding: utf-8 -*-
"""ASR 服务配置：从环境变量读取，带默认值。"""

from __future__ import annotations

import os

ASR_MODEL_PATH: str = os.getenv("ASR_MODEL_PATH", "/root/autodl-tmp/models/Qwen3-ASR-1.7B")
ASR_PORT: int = int(os.getenv("ASR_PORT", "8005"))
ASR_GPU_MEMORY_UTILIZATION: float = float(os.getenv("ASR_GPU_MEMORY_UTILIZATION", "0.3"))
ASR_CHUNK_SIZE_SEC: float = float(os.getenv("ASR_CHUNK_SIZE_SEC", "1.0"))
ASR_UNFIXED_CHUNK_NUM: int = int(os.getenv("ASR_UNFIXED_CHUNK_NUM", "4"))
ASR_UNFIXED_TOKEN_NUM: int = int(os.getenv("ASR_UNFIXED_TOKEN_NUM", "5"))
ASR_SESSION_TTL_SEC: float = float(os.getenv("ASR_SESSION_TTL_SEC", "600"))
