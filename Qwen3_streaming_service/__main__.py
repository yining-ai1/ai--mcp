# -*- coding: utf-8 -*-
"""入口：uvicorn 启动 Qwen3 streaming TTS 服务。"""

from __future__ import annotations

import uvicorn

from Qwen3_streaming_service import config
from Qwen3_streaming_service.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.QWEN3_STREAMING_SERVICE_PORT,
    )
