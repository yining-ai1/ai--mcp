# -*- coding: utf-8 -*-
# 不在此处导入 protocol，避免 handlers 导入 registry 时连带加载 protocol（依赖 aiohttp）
from mcp_server.core.registry import get as get_handler, register
from mcp_server.core.types import build_content_for_tool_result

__all__ = ["get_handler", "register", "build_content_for_tool_result"]
