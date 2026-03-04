# -*- coding: utf-8 -*-
"""MCP server package: TTS (base/customvoice/voicedesign) + Wan video."""

__version__ = "1.0.0"

# 导入 handlers 以触发 core.registry 注册，再导出 protocol/transports
import mcp_server.handlers  # noqa: F401
from mcp_server.core.protocol import MCPServer
from mcp_server.transports.http import app

__all__ = ["__version__", "MCPServer", "app"]
