# -*- coding: utf-8 -*-
"""MCP 服务入口：解析命令行，选择 stdio 或 http 传输。"""

import argparse
import asyncio
import os
import uvicorn

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    import warnings
    warnings.warn("python-dotenv 未安装，.env 不会被加载；可选: pip install python-dotenv", UserWarning)

# 先导入 handlers，触发 registry 注册，再使用 protocol/transports
import mcp_server.handlers  # noqa: F401
from mcp_server.transports import app, run_stdio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["stdio", "http"], default="http")
    parser.add_argument("--port", type=int, default=6006)
    args = parser.parse_args()
    if args.mode == "stdio":
        asyncio.run(run_stdio())
    else:
        uvicorn.run(app, host="0.0.0.0", port=args.port)
