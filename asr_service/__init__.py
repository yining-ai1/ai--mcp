# -*- coding: utf-8 -*-
"""ASR 流式服务：Qwen3-ASR-1.7B + streaming_transcribe HTTP API。"""

from asr_service.app import app
from asr_service import config

__all__ = ["app", "config"]
