#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gradio UI entry: build chat tab and wire events."""

from __future__ import annotations

import json
import uuid

import httpx
import gradio as gr

from chat_agent import config
from chat_agent.adapter.mcp_adapter import mcp_tools_to_openai_tools
from chat_agent.service.agent import chat_agent_turn

# ========== 工具缓存（按 mcp_base 缓存） ==========
_TOOLS_CACHE: dict[str, list[dict]] = {}


def _get_tools(mcp_base: str) -> list[dict]:
    mcp_base = (mcp_base or "").rstrip("/")
    if not mcp_base:
        return []
    if mcp_base in _TOOLS_CACHE:
        return _TOOLS_CACHE[mcp_base]
    tools = mcp_tools_to_openai_tools(mcp_base)
    _TOOLS_CACHE[mcp_base] = tools
    return tools


def _gateway_video_status(gateway_base: str, task_id: str) -> str:
    tid = (task_id or "").strip()
    if not tid:
        return json.dumps({"error": "请先提供 task_id"}, ensure_ascii=False, indent=2)
    url = f"{gateway_base.rstrip('/')}/wan/v1/video/status/{tid}"
    try:
        with httpx.Client(timeout=config.GATEWAY_TIMEOUT, verify=False) as client:
            resp = client.get(url)
        data = resp.json()
        return json.dumps(data, ensure_ascii=False, indent=2)[:4000]
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)


def _gateway_video_download(gateway_base: str, task_id: str) -> tuple[str | None, str]:
    tid = (task_id or "").strip()
    if not tid:
        return None, "请先提供 task_id"
    url = f"{gateway_base.rstrip('/')}/wan/v1/video/download/{tid}"
    try:
        with httpx.Client(timeout=config.GATEWAY_TIMEOUT, verify=False) as client:
            resp = client.get(url)
        if resp.status_code != 200 or len(resp.content) < 100:
            return None, resp.text[:2000]
        out_path = f"/tmp/chat_video_{uuid.uuid4().hex}.mp4"
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path, f"下载成功，{len(resp.content)} bytes"
    except Exception as e:
        return None, str(e)


def build_chat_tab(blocks: gr.Blocks, mcp_base: str, gateway_base: str) -> None:
    """
    在给定 blocks 下创建「聊天」Tab。
    - mcp_base/gateway_base 由 gradio_app 传入，保证单一来源
    """
    with gr.Tab("聊天"):
        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### 聊天（LLM + MCP Agent）")
                chat_bot = gr.Chatbot(label="对话", height=420)
                user_in = gr.Textbox(
                    label="输入",
                    placeholder="例如：用 Vivian 读一下这句话；或上传参考音频后说「用这个声音读xxx」。也可直接说「读上一句」、生成视频等。",
                    lines=1,
                    max_lines=6,
                )
                with gr.Row():
                    ref_audio = gr.File(
                        label="参考音频（可选，用于 Base 克隆）",
                        file_types=["audio"],
                        type="filepath",
                    )
                    send_btn = gr.Button("发送", variant="primary")
                    new_btn = gr.Button("新会话", variant="secondary", elem_id="chat_new_btn")
                with gr.Row():
                    temperature = gr.Slider(0.1, 1.0, value=0.7, step=0.05, label="temperature")
                    max_tokens = gr.Number(value=2048, precision=0, label="max_tokens")

            with gr.Column(scale=2):
                # 仅在本轮调用了对应工具时才展示
                block_tts = gr.Column(visible=False)
                with block_tts:
                    gr.Markdown("### 本轮生成的语音")
                    tts_audio = gr.Audio(label="", type="filepath", show_label=False)

                block_video = gr.Column(visible=False)
                with block_video:
                    gr.Markdown("### 视频任务")
                    video_task_id = gr.Textbox(label="task_id", value="", interactive=True)
                    with gr.Row():
                        video_status_btn = gr.Button("查询状态")
                        video_download_btn = gr.Button("下载视频")
                    video_status_out = gr.Textbox(label="状态响应", lines=8)
                    video_player = gr.Video(label="视频")
                    video_dl_info = gr.Textbox(label="下载信息", lines=2)

        # State: OpenAI 消息 + Chatbot messages（用于展示）
        messages_state = gr.State(value=[])
        chat_messages_state = gr.State(value=[])
        last_video_task_id_state = gr.State(value="")  # 会话内已展示过的 video task_id，避免「查询进度」等后续轮把右侧视频区块收掉

        def _reset():
            return [], [], [], None, "", "", None, "", "", gr.update(visible=False), gr.update(visible=False), ""

        def _send(message: str, messages: list, chat_messages: list, t: float, mt: float, last_video_task_id: str, ref_audio_in):
            text = (message or "").strip()
            if not text:
                return chat_messages, messages, chat_messages, None, "", "", None, "", "", gr.update(visible=False), gr.update(visible=False), last_video_task_id or ""

            # 参考音频路径：本轮回话可选附带，用于 Base 克隆
            ref_audio_path = None
            if ref_audio_in is not None:
                if isinstance(ref_audio_in, str):
                    ref_audio_path = ref_audio_in
                elif isinstance(ref_audio_in, (list, tuple)) and len(ref_audio_in):
                    ref_audio_path = ref_audio_in[0] if isinstance(ref_audio_in[0], str) else None

            messages = list(messages or [])
            messages.append({"role": "user", "content": text})

            tools = _get_tools(mcp_base)
            updated_messages, assistant_content, _reasoning, audio_path, vid_task_id, video_path = chat_agent_turn(
                messages=messages,
                tools=tools,
                temperature=float(t),
                max_tokens=int(mt),
                mcp_base=mcp_base,
                ref_audio_path=ref_audio_path,
            )

            # 更新 Chatbot messages 展示
            chat_messages = list(chat_messages or [])
            chat_messages.append({"role": "user", "content": text})
            chat_messages.append({"role": "assistant", "content": assistant_content})

            task_id_out = (vid_task_id or "").strip()
            # 本轮有新 task_id 则更新，否则沿用会话内已有（这样「查询进度」等后续轮仍显示视频区块）
            stored_task_id = task_id_out or (last_video_task_id or "").strip()
            show_tts = audio_path is not None
            # 有 task_id 或本轮通过 video_download 得到视频时展示视频区块
            show_video = bool(stored_task_id) or (video_path is not None)
            # 本轮若 agent 调用了 video_download，用返回的 video_path 填充播放器
            video_player_value = video_path if video_path is not None else None

            # 有 task_id 时自动查一次状态（本轮新的或沿用之前的）
            status_text = ""
            if stored_task_id:
                status_text = _gateway_video_status(gateway_base, stored_task_id)

            return (
                chat_messages,
                updated_messages,
                chat_messages,
                audio_path,
                stored_task_id,
                status_text,
                video_player_value,
                "",
                "",
                gr.update(visible=show_tts),
                gr.update(visible=show_video),
                stored_task_id,
            )

        _send_inputs = [user_in, messages_state, chat_messages_state, temperature, max_tokens, last_video_task_id_state, ref_audio]
        _send_outputs = [chat_bot, messages_state, chat_messages_state, tts_audio, video_task_id, video_status_out, video_player, video_dl_info, user_in, block_tts, block_video, last_video_task_id_state]
        send_btn.click(_send, inputs=_send_inputs, outputs=_send_outputs)
        user_in.submit(_send, inputs=_send_inputs, outputs=_send_outputs)
        new_btn.click(
            _reset,
            outputs=[chat_bot, messages_state, chat_messages_state, tts_audio, video_task_id, video_status_out, video_player, video_dl_info, user_in, block_tts, block_video, last_video_task_id_state],
        )

        def _status(task_id: str):
            return _gateway_video_status(gateway_base, task_id)

        def _download(task_id: str):
            return _gateway_video_download(gateway_base, task_id)

        video_status_btn.click(_status, inputs=[video_task_id], outputs=[video_status_out])
        video_download_btn.click(_download, inputs=[video_task_id], outputs=[video_player, video_dl_info])

