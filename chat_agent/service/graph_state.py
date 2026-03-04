#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LangGraph agent state definition."""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """State for the agent graph. All keys optional to allow partial updates."""

    messages: list[dict]
    """OpenAI-format messages (system/user/assistant/tool)."""

    assistant_content: str
    """Latest assistant text (final reply when no tool_calls)."""

    reasoning_content: str
    """Reasoning from LLM if present."""

    audio_path: str | None
    """Latest tts_generate output path."""

    video_task_id: str | None
    """Latest video_generate task_id."""

    video_path: str | None
    """Latest video_download output path (local mp4 file)."""

    tool_calls: list[dict]
    """Current turn's tool_calls from LLM (consumed by tools_node)."""

    _config: dict
    """Runtime config (temperature, max_tokens, mcp_base, tools). 由 chat_agent_turn 写入，节点从 state 读取，不依赖 LangGraph 传 config。"""
