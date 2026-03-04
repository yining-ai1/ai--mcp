# -*- coding: utf-8 -*-
"""CosyVoice 服务配置。"""

from __future__ import annotations

import os

COSYVOICE_SERVICE_PORT: int = int(os.getenv("COSYVOICE_SERVICE_PORT", "8011"))

# 模型目录（Fun-CosyVoice3-0.5B）
COSYVOICE_MODEL_DIR: str = os.getenv(
    "COSYVOICE_MODEL_DIR",
    os.path.join(os.path.expanduser("~"), "autodl-tmp", "models", "Fun-CosyVoice3-0.5B"),
)

COSYVOICE_MAX_TEXT_CHARS: int = int(os.getenv("COSYVOICE_MAX_TEXT_CHARS", "1000"))
