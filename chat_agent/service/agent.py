#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Agent loop: LangGraph-based chat + MCP tool calling.

Streaming: use get_graph() and graph.stream(...) for token-level streaming;
or chat_agent_stream() (currently returns empty iterator; extend later for UI).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from chat_agent import config
from chat_agent.adapter import mcp_adapter
from chat_agent.adapter.langchain_tools import mcp_openai_tools_to_langchain_tools
from chat_agent.service.graph_state import AgentState


def _ensure_system_message(messages: list[dict]) -> list[dict]:
    if not messages:
        return [{"role": "system", "content": config.CHAT_SYSTEM_PROMPT}]
    if messages[0].get("role") != "system":
        return [{"role": "system", "content": config.CHAT_SYSTEM_PROMPT}] + messages
    return messages


def _openai_dict_to_lc_message(d: dict) -> BaseMessage:
    """Convert OpenAI-format message dict to LangChain message."""
    role = (d.get("role") or "").strip().lower()
    content = d.get("content")
    if role == "system":
        return SystemMessage(content=content or "")
    if role == "user":
        return HumanMessage(content=content or "")
    if role == "assistant":
        tool_calls = d.get("tool_calls")
        if tool_calls:
            return AIMessage(
                content=content or "",
                tool_calls=[
                    {
                        "id": tc.get("id", ""),
                        "name": (tc.get("function") or {}).get("name", ""),
                        "args": json.loads((tc.get("function") or {}).get("arguments") or "{}")
                        if isinstance((tc.get("function") or {}).get("arguments"), str)
                        else ((tc.get("function") or {}).get("arguments") or {}),
                    }
                    for tc in tool_calls
                ],
            )
        return AIMessage(content=content or "")
    if role == "tool":
        return ToolMessage(
            content=d.get("content") or "",
            tool_call_id=d.get("tool_call_id") or "",
        )
    return HumanMessage(content=json.dumps(d, ensure_ascii=False))


def _lc_message_to_openai_dict(msg: BaseMessage) -> dict:
    """Convert LangChain message to OpenAI-format dict (for assistant with optional tool_calls)."""
    if isinstance(msg, AIMessage):
        content = msg.content if msg.content is not None else ""
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args") or {}),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        return {"role": "assistant", "content": content}
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content or ""}
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content or ""}
    if isinstance(msg, ToolMessage):
        return {"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content or ""}
    return {"role": "user", "content": str(msg)}


def _passthrough_artifacts(state: AgentState, out: dict) -> None:
    """把 state 里的 audio_path / video_task_id / video_path / _config 写入 out，避免被覆盖丢失。"""
    if state.get("audio_path") is not None:
        out["audio_path"] = state["audio_path"]
    if state.get("video_task_id") is not None:
        out["video_task_id"] = state["video_task_id"]
    if state.get("video_path") is not None:
        out["video_path"] = state["video_path"]
    if state.get("_config") is not None:
        out["_config"] = state["_config"]


def _get_configurable(state: AgentState, config_obj: dict | None = None) -> dict:
    """优先从 state['_config'] 读（invoke 时写入），否则从 LangGraph 传入的 config_obj 读。"""
    c = state.get("_config")
    if not c:
        c = (config_obj or {}).get("configurable") or {}
    return {
        "temperature": c.get("temperature", 0.7),
        "max_tokens": c.get("max_tokens", 2048),
        "mcp_base": (c.get("mcp_base") or "").rstrip("/"),
        "tools": c.get("tools") or [],
        "ref_audio_path": c.get("ref_audio_path"),
    }


def _create_llm(temperature: float, max_tokens: int) -> ChatOpenAI:
    api_key = config.get_openai_api_key()
    return ChatOpenAI(
        base_url=config.LLM_BASE_URL,
        api_key=api_key or "",
        model=config.LLM_MODEL_NAME,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=float(getattr(config.CHAT_LLM_TIMEOUT, "timeout", 120.0)),
    )


def _llm_node(state: AgentState, runnable_config: dict | None = None) -> dict:
    """Call LLM; return state update with messages, assistant_content, reasoning_content, tool_calls."""
    cfg = _get_configurable(state, runnable_config)
    temperature = cfg["temperature"]
    max_tokens = cfg["max_tokens"]
    mcp_base = cfg["mcp_base"]
    openai_tools = cfg["tools"]

    messages_list = state.get("messages") or []
    lc_messages = [_openai_dict_to_lc_message(m) for m in messages_list]

    api_key = config.get_openai_api_key()
    if not api_key:
        err_msg = "Missing OPENAI_API_KEY env var"
        err_assistant = {"role": "assistant", "content": err_msg}
        out = {
            "messages": messages_list + [err_assistant],
            "assistant_content": err_msg,
            "reasoning_content": "",
            "tool_calls": [],
        }
        _passthrough_artifacts(state, out)
        return out

    llm = _create_llm(temperature, max_tokens)
    langchain_tools = mcp_openai_tools_to_langchain_tools(mcp_base, openai_tools)
    if langchain_tools:
        llm = llm.bind_tools(langchain_tools)

    try:
        response = llm.invoke(lc_messages)
    except Exception as e:
        err_msg = f"LLM request exception: {e}"
        err_assistant = {"role": "assistant", "content": err_msg}
        out = {
            "messages": messages_list + [err_assistant],
            "assistant_content": err_msg,
            "reasoning_content": "",
            "tool_calls": [],
        }
        _passthrough_artifacts(state, out)
        return out

    if not isinstance(response, AIMessage):
        err_msg = "LLM 返回异常（非 AIMessage）"
        err_assistant = {"role": "assistant", "content": err_msg}
        out = {
            "messages": messages_list + [err_assistant],
            "assistant_content": err_msg,
            "reasoning_content": "",
            "tool_calls": [],
        }
        _passthrough_artifacts(state, out)
        return out

    assistant_dict = _lc_message_to_openai_dict(response)
    new_messages = messages_list + [assistant_dict]
    content = (response.content or "").strip() if isinstance(response.content, str) else ""
    reasoning = getattr(response, "reasoning_content", None) or getattr(response, "additional_kwargs", {}).get("reasoning_content", "") or ""
    tool_calls_raw = getattr(response, "tool_calls", None) or []
    tool_calls = []
    for tc in tool_calls_raw:
        if hasattr(tc, "get"):
            tid, name, args = tc.get("id", ""), tc.get("name", ""), tc.get("args") or {}
        else:
            tid = getattr(tc, "id", "")
            name = getattr(tc, "name", "")
            args = getattr(tc, "args", None) or {}
        tool_calls.append({
            "id": tid,
            "function": {"name": name, "arguments": json.dumps(args) if isinstance(args, dict) else str(args)},
        })

    out = {
        "messages": new_messages,
        "assistant_content": content,
        "reasoning_content": reasoning,
        "tool_calls": tool_calls,
    }
    _passthrough_artifacts(state, out)
    return out


def _tools_node(state: AgentState, runnable_config: dict | None = None) -> dict:
    """Execute MCP tools from state['tool_calls'], append tool messages; return audio_path/video_task_id when applicable."""
    cfg = _get_configurable(state, runnable_config)
    mcp_base = cfg["mcp_base"]
    messages = list(state.get("messages") or [])
    tool_calls = state.get("tool_calls") or []

    last_audio_path: str | None = state.get("audio_path")
    last_video_task_id: str | None = state.get("video_task_id")
    last_video_path: str | None = state.get("video_path")

    for tc in tool_calls:
        call_id = tc.get("id")
        fn = tc.get("function") or {}
        fn_name = fn.get("name")
        fn_args_raw = fn.get("arguments") or "{}"
        try:
            fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else (fn_args_raw or {})
        except Exception as e:
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"error": f"parse tool_call failed: {e}"}, ensure_ascii=False),
            })
            continue
        if not isinstance(fn_args, dict):
            fn_args = {"_raw": fn_args}

        tool_result, audio_path, video_task_id, video_path = mcp_adapter.execute_mcp_tool(
            mcp_base=mcp_base,
            name=str(fn_name),
            arguments=fn_args,
        )
        if audio_path:
            last_audio_path = audio_path
        if video_task_id:
            last_video_task_id = video_task_id
        if video_path:
            last_video_path = video_path
        messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result})

    update = {"messages": messages}
    if last_audio_path is not None:
        update["audio_path"] = last_audio_path
    if last_video_task_id is not None:
        update["video_task_id"] = last_video_task_id
    if last_video_path is not None:
        update["video_path"] = last_video_path
    if state.get("_config") is not None:
        update["_config"] = state["_config"]
    return update


def _route_after_llm(state: AgentState) -> Literal["tools", "__end__"]:
    """Conditional edge: go to tools if there are tool_calls, else END."""
    tool_calls = state.get("tool_calls") or []
    return "tools" if len(tool_calls) > 0 else "__end__"


def _build_graph() -> StateGraph:
    """Build the agent StateGraph (no tools/mcp_base in closure; passed via config at invoke)."""
    graph = StateGraph(AgentState)
    graph.add_node("llm", _llm_node)
    graph.add_node("tools", _tools_node)
    graph.add_conditional_edges("llm", _route_after_llm, {"tools": "tools", "__end__": END})
    graph.add_edge("tools", "llm")
    graph.set_entry_point("llm")
    return graph


_GRAPH: StateGraph | None = None


def get_graph() -> StateGraph:
    """Return compiled agent graph. Cached after first build. For streaming / reuse."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph().compile()
    return _GRAPH


def chat_agent_turn(
    *,
    messages: list[dict],
    tools: list[dict],
    temperature: float,
    max_tokens: int,
    mcp_base: str,
    ref_audio_path: str | None = None,
) -> tuple[list[dict], str, str, str | None, str | None, str | None]:
    """
    执行一轮对话（LangGraph：可能包含多轮 tool_calls 循环）。

    返回：
    - updated_messages: OpenAI messages（含 tool 消息）
    - assistant_content: 最终助手回复文本
    - reasoning_content: 思考过程（可能为空）
    - audio_path: 若期间执行过 tts_generate，则返回最新音频文件路径
    - video_task_id: 若期间执行过 video_generate，则返回最新 task_id
    - video_path: 若期间执行过 video_download，则返回最新视频文件路径
    """
    initial_messages = _ensure_system_message(list(messages or []))
    # recursion_limit: each step = one node run; one "round" = llm + tools = 2 steps. We want at most MAX_AGENT_ROUNDS LLM calls.
    recursion_limit = 2 * max(1, config.MAX_AGENT_ROUNDS)
    configurable = {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "mcp_base": (mcp_base or "").rstrip("/"),
        "tools": tools or [],
        "ref_audio_path": ref_audio_path or None,
    }
    initial_state: AgentState = {
        "messages": initial_messages,
        "assistant_content": "",
        "reasoning_content": "",
        "audio_path": None,
        "video_task_id": None,
        "video_path": None,
        "tool_calls": [],
        "_config": configurable,
    }
    try:
        compiled = get_graph()
        final_state = compiled.invoke(
            initial_state,
            config={"configurable": configurable, "recursion_limit": recursion_limit},
        )
    except Exception as e:
        err_msg = str(e)
        return (
            initial_messages,
            err_msg,
            "",
            None,
            None,
            None,
        )
    updated_messages = final_state.get("messages") or initial_messages
    assistant_content = (final_state.get("assistant_content") or "").strip()
    reasoning_content = (final_state.get("reasoning_content") or "").strip()
    audio_path = final_state.get("audio_path")
    video_task_id = final_state.get("video_task_id")
    video_path = final_state.get("video_path")
    # If we hit recursion limit without a final text reply, use the same tip as before
    if not assistant_content and (final_state.get("tool_calls") or []):
        tip = "已达到最大工具调用轮数上限，已停止继续调用工具。请你换一种表述或缩小问题范围再试。"
        last_content = (final_state.get("assistant_content") or "").strip()
        if last_content:
            assistant_content = f"{last_content}\n\n（{tip}）"
        else:
            assistant_content = tip
    return (updated_messages, assistant_content, reasoning_content, audio_path, video_task_id, video_path)


def chat_agent_stream(
    *,
    messages: list[dict],
    tools: list[dict],
    temperature: float,
    max_tokens: int,
    mcp_base: str,
):
    """
    流式入口预留。后续 UI 可从此处接入 token 流。
    本期返回空迭代器，不实现实际流式。
    """
    # Placeholder: return empty iterator. Future: yield from get_graph().stream(...)
    return iter([])
