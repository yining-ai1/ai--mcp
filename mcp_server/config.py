# -*- coding: utf-8 -*-
"""MCP server configuration constants."""

import os

# TTS backend ports (one per model)
TTS_PORT_BASE = 8001
TTS_PORT_CUSTOMVOICE = 8002
TTS_PORT_VOICEDESIGN = 8003
# 0.6B 轻量模型
TTS_PORT_BASE_06B = 8006
TTS_PORT_CUSTOMVOICE_06B = 8007
TTS_PORTS = [TTS_PORT_BASE, TTS_PORT_CUSTOMVOICE, TTS_PORT_VOICEDESIGN, TTS_PORT_BASE_06B, TTS_PORT_CUSTOMVOICE_06B]

# VoXtream_service 流式 TTS 后端（host:port）
TTS_VOXTREAM_HOST = os.getenv("TTS_VOXTREAM_HOST", "127.0.0.1:8010")

# CosyVoice_service 流式 TTS 后端（支持中文）
TTS_COSYVOICE_HOST = os.getenv("TTS_COSYVOICE_HOST", "127.0.0.1:8011")

# Qwen3_streaming_service 流式 TTS 后端（dffdeeq/Qwen3-TTS-streaming fork）
TTS_QWEN3_STREAMING_HOST = os.getenv("TTS_QWEN3_STREAMING_HOST", "127.0.0.1:8012")

# Backend API task_type must match exactly (case-sensitive)
TTS_TASK_TYPE_BASE = "Base"
TTS_TASK_TYPE_CUSTOMVOICE = "CustomVoice"
TTS_TASK_TYPE_VOICEDESIGN = "VoiceDesign"

# Qwen3-TTS CustomVoice official voices
TTS_CUSTOMVOICE_VOICES = [
    "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
    "Ryan", "Aiden", "Ono_Anna", "Sohee",
]

WAN_HOST = "127.0.0.1:8004"

# ASR streaming backend (see asr_service)
ASR_HOST = os.getenv("ASR_HOST", "127.0.0.1:8005")

# ASR 支持的语言名（与 asr_service/qwen_asr 一致），用于 MCP 端参数校验
ASR_SUPPORTED_LANGUAGES = frozenset({
    "Chinese", "English", "Cantonese", "Arabic", "German", "French", "Spanish",
    "Portuguese", "Indonesian", "Italian", "Korean", "Russian", "Thai", "Vietnamese",
    "Japanese", "Turkish", "Hindi", "Malay", "Dutch", "Swedish", "Danish", "Finnish",
    "Polish", "Czech", "Filipino", "Persian", "Greek", "Romanian", "Hungarian", "Macedonian",
})

# Optional: require Authorization: Bearer <token>. If set, POST /mcp and POST /message reject missing/wrong token.
# If unset, no auth (backward compatible). Client config headers are passed through.
MCP_BEARER_TOKEN: str | None = os.environ.get("MCP_BEARER_TOKEN") or None
