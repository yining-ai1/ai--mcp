#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
chat_agent 配置层

注意：
- 仅负责从环境变量读取配置与定义常量
- 不输出敏感信息（例如 OPENAI_API_KEY）
"""

from __future__ import annotations

import os

import httpx


# ========== LLM 配置（环境变量） ==========
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "Qwen3-30B-A3B")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://region-42.seetacloud.com:25700/v1").rstrip("/")


def get_openai_api_key() -> str | None:
    """运行时读取，避免导入时缓存导致不生效。"""
    return os.getenv("OPENAI_API_KEY") or None


# ========== Agent 行为 ==========
MAX_AGENT_ROUNDS: int = int(os.getenv("MAX_AGENT_ROUNDS", "5"))


# ========== 超时配置 ==========
CHAT_LLM_TIMEOUT = httpx.Timeout(
    float(os.getenv("CHAT_LLM_TIMEOUT_TOTAL", "120.0")),
    connect=float(os.getenv("CHAT_LLM_TIMEOUT_CONNECT", "10.0")),
)
MCP_TIMEOUT = httpx.Timeout(
    float(os.getenv("MCP_TIMEOUT_TOTAL", "300.0")),
    connect=float(os.getenv("MCP_TIMEOUT_CONNECT", "10.0")),
)
GATEWAY_TIMEOUT = httpx.Timeout(
    float(os.getenv("GATEWAY_TIMEOUT_TOTAL", "300.0")),
    connect=float(os.getenv("GATEWAY_TIMEOUT_CONNECT", "10.0")),
)


# ========== System Prompt ==========
CHAT_SYSTEM_PROMPT: str = os.getenv(
    "CHAT_SYSTEM_PROMPT",
    "\n".join(
        [
            "你是一个专业的中文助手，支持多轮对话，并且可以在必要时调用工具来完成任务。",
            "",
            "你可以使用的工具包括：",
            "- tts_generate_base：TTS Base 基础模型，支持约 3 秒快速音色克隆（从参考音频），需 text，可选 ref_audio、ref_text。",
            "- tts_generate_customvoice：TTS CustomVoice，通过指令对目标音色做风格控制，支持 9 种优质音色（需 text，可选 voice：Vivian、Serena、Uncle_Fu、Dylan、Eric、Ryan、Aiden、Ono_Anna、Sohee）。",
            "- tts_generate_voicedesign：TTS VoiceDesign，根据用户描述进行音色设计（需 text，可选 instructions）。",
            "- video_generate：根据提示词（可选附带图片）生成视频任务（用于生成短视频）。",
            "- video_status：根据 task_id 查询视频任务状态（用于查看生成进度/结果）。",
            "- video_download：根据 task_id 下载已完成视频（返回视频文件，仅当任务状态为 completed 时可用）。",
            "",
            "当用户明确要求朗读/生成语音时，按以下规则选择 TTS 工具：",
            "  - 用户上传了参考音频或要求克隆声音：使用 tts_generate_base（3 秒快速音色克隆），传 text（及可选 ref_audio、ref_text）。",
            "  - 用户指定了预设音色（Vivian、Serena、Uncle_Fu 等）或要对音色做风格控制：使用 tts_generate_customvoice，传 text 与对应 voice。",
            "  - 用户用自然语言描述音色（如「温柔女声」「成熟男声、语速慢」）：使用 tts_generate_voicedesign（根据描述进行音色设计），传 text 与 instructions。",
            "  - 若用户只说「读一下」「读我上句话」等且未指定音色、也未上传参考音频：不要直接调用 TTS，仅用文字询问用户想用哪种音色（可列预设名或让用户描述），等用户回复后再根据其选择调用对应工具。",
            "当用户明确要求生成视频时，使用 video_generate。",
            "当用户询问视频生成进度或需要结果时，使用 video_status。",
            "当用户要求下载或获取已完成的视频文件时，使用 video_download（需先有 task_id 且任务已完成）。",
            "若你在本轮中调用了 video_generate 并获得了 task_id，应紧接着在同一轮内调用 video_status 查询一次当前状态，将结果告知用户，而不是仅用文字说「将查询」或「稍等」。",
            "",
            "若某 TTS 工具返回错误（例如 Base 不可用），请勿重复用相同参数重试；可改用 tts_generate_customvoice 再试一次，或直接以文字回复用户说明限制。",
            "工具调用结果会由系统以组件形式展示给用户（例如语音播放器、视频任务ID、状态和下载入口）。",
            "请保持回复清晰、可靠、简洁；当信息不足时先提出必要的澄清问题。",
        ]
    ),
)

