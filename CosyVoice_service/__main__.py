# -*- coding: utf-8 -*-
"""入口：uvicorn 启动 CosyVoice 服务。"""

from __future__ import annotations

import uvicorn

from CosyVoice_service import config
from CosyVoice_service.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.COSYVOICE_SERVICE_PORT,
    )
