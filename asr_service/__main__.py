# -*- coding: utf-8 -*-
"""入口：仅当 __name__ == "__main__" 时启动 uvicorn，避免 vLLM 多进程 spawn 问题。"""

from __future__ import annotations

import uvicorn

from asr_service import config
from asr_service.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.ASR_PORT,
    )
