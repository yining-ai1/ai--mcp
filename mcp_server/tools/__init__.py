# -*- coding: utf-8 -*-
from mcp_server.tools.tts import get_tts_tools
from mcp_server.tools.video import get_video_tools
from mcp_server.tools.asr import get_asr_tools


def get_tools() -> dict:
    """Aggregate all tool declarations."""
    return {**get_tts_tools(), **get_video_tools(), **get_asr_tools()}


__all__ = ["get_tools", "get_tts_tools", "get_video_tools", "get_asr_tools"]
