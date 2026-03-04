# -*- coding: utf-8 -*-
"""VoXtream 服务配置。"""

from __future__ import annotations

import os

# 服务端口
VOXTREAM_SERVICE_PORT: int = int(os.getenv("VOXTREAM_SERVICE_PORT", "8010"))

# VoXtream 配置 JSON 路径（需与 herimor/voxtream 仓库中 configs/generator.json 一致，可从该仓库下载）
VOXTREAM_CONFIG_PATH: str = os.getenv(
    "VOXTREAM_CONFIG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "generator.json"),
)

# 参考音频最长秒数（与 VoXtream 默认 max_prompt_sec 一致）
VOXTREAM_MAX_PROMPT_SEC: int = int(os.getenv("VOXTREAM_MAX_PROMPT_SEC", "10"))

# 单次生成最大文本长度（字符）
VOXTREAM_MAX_TEXT_CHARS: int = int(os.getenv("VOXTREAM_MAX_TEXT_CHARS", "1000"))

# 本地模型目录（默认 /root/autodl-tmp/models/voxtream，若存在则自动使用）
# 需含 model.safetensors、config.json、phoneme_to_token.json
_LOCAL_VOXTREAM = os.path.join(os.path.expanduser("~"), "autodl-tmp", "models", "voxtream")
VOXTREAM_LOCAL_MODEL_DIR: str | None = (
    os.environ.get("VOXTREAM_LOCAL_MODEL_DIR")
    or (_LOCAL_VOXTREAM if os.path.exists(os.path.join(_LOCAL_VOXTREAM, "model.safetensors")) else None)
)
