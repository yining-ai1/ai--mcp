# -*- coding: utf-8 -*-
"""入口：uvicorn 启动 VoXtream 服务。"""

from __future__ import annotations

import uvicorn

from VoXtream_service import config
from VoXtream_service.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.VOXTREAM_SERVICE_PORT,
    )
