# -*- coding: utf-8 -*-
"""Register all handlers with core.registry (side-effect on import)."""

from mcp_server.core.registry import register
from mcp_server.handlers import tts_handler, video_handler, asr_handler

register("tts_generate_base", tts_handler.call_tts_base)
register("tts_generate_customvoice", tts_handler.call_tts_customvoice)
register("tts_generate_voicedesign", tts_handler.call_tts_voicedesign)
register("tts_generate_base_06b", tts_handler.call_tts_base_06b)
register("tts_generate_customvoice_06b", tts_handler.call_tts_customvoice_06b)
register("tts_stream_voxtream", tts_handler.call_tts_stream_voxtream)
register("tts_stream_cosyvoice", tts_handler.call_tts_stream_cosyvoice)
register("tts_stream_qwen3", tts_handler.call_tts_stream_qwen3)
register("video_generate", video_handler.call_video_generate)
register("video_status", video_handler.call_video_status)
register("video_download", video_handler.call_video_download)
register("asr_stream", asr_handler.call_asr_stream)

__all__ = ["tts_handler", "video_handler", "asr_handler"]
