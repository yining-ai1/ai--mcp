#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI Services 测试前端（Gradio）
- 通过公网地址调用 MCP (6006) 和 Gateway (6008) 的各项服务
- 可部署在任意主机
"""

from dotenv import load_dotenv
load_dotenv()

import json
import base64
import httpx
import gradio as gr
from typing import Optional

from chat_agent.entry.gradio_ui import build_chat_tab

# ========== 公网基址（硬编码，便于迁移） ==========
MCP_BASE = "https://u662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443"
GATEWAY_BASE = "https://uu662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443"

# HTTP 客户端超时
TIMEOUT = httpx.Timeout(300.0, connect=10.0)


# ========== 通用工具函数 ==========
def safe_json(resp: httpx.Response) -> dict:
    """安全解析 JSON 响应"""
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:2000], "status_code": resp.status_code}


def mcp_call(method: str, params: dict = None) -> dict:
    """调用 MCP JSON-RPC"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.post(f"{MCP_BASE}/mcp", json=payload)
        return safe_json(resp)


def mcp_tool_call(tool_name: str, arguments: dict) -> dict:
    """调用 MCP tools/call"""
    return mcp_call("tools/call", {"name": tool_name, "arguments": arguments})


def parse_mcp_result(resp: dict):
    """解析 MCP tools/call 返回：支持新 content 格式（audio/video/text）与旧 text JSON。返回 (content_list, legacy_parsed)。"""
    content = resp.get("result", {}).get("content", [])
    if not content:
        return content, resp
    first = content[0] if isinstance(content[0], dict) else {}
    if first.get("type") in ("audio", "video", "text"):
        return content, None
    text = first.get("text", "")
    if text:
        try:
            return content, json.loads(text)
        except Exception:
            pass
    return content, resp


# ========== 1. 健康检查 ==========
def check_mcp_health():
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.get(f"{MCP_BASE}/health")
        return safe_json(resp)


def check_gateway_health():
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.get(f"{GATEWAY_BASE}/health")
        return safe_json(resp)


# ========== 2. MCP: initialize & tools/list ==========
def mcp_initialize():
    return mcp_call("initialize")


def mcp_tools_list():
    return mcp_call("tools/list")


# ========== 3. MCP: TTS ==========
# Qwen3-TTS CustomVoice 官方说话人（与模型文档一致）；(展示文案, 传参值)
TTS_CUSTOMVOICE_VOICES = [
    "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
    "Ryan", "Aiden", "Ono_Anna", "Sohee",
]
TTS_CUSTOMVOICE_VOICE_CHOICES = [
    ("Vivian - 明亮、略带锐气的年轻女声（中文）", "Vivian"),
    ("Serena - 温暖柔和的年轻女声（中文）", "Serena"),
    ("Uncle_Fu - 音色低沉醇厚的成熟男声（中文）", "Uncle_Fu"),
    ("Dylan - 清晰自然的北京青年男声（中文/北京方言）", "Dylan"),
    ("Eric - 活泼、略带沙哑明亮感的成都男声（中文/四川方言）", "Eric"),
    ("Ryan - 富有节奏感的动态男声（英语）", "Ryan"),
    ("Aiden - 清晰中频的阳光美式男声（英语）", "Aiden"),
    ("Ono_Anna - 轻快灵活的俏皮日语女声（日语）", "Ono_Anna"),
    ("Sohee - 富含情感的温暖韩语女声（韩语）", "Sohee"),
]


def _tts_model_to_visibility(tts_model: str):
    """根据 tts_model 返回各模型专用参数的 visible 更新（用于 MCP TTS / Gateway TTS）"""
    if tts_model == "Base":
        return (
            gr.update(visible=False),   # voice
            gr.update(visible=False),   # language
            gr.update(visible=False),   # instructions
            gr.update(visible=True),    # ref_audio
            gr.update(visible=True),    # ref_text
        )
    if tts_model == "CustomVoice":
        return (
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )
    # VoiceDesign
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
    )


# 模型名 -> MCP 工具名
TTS_MODEL_TO_TOOL = {
    "Base": "tts_generate_base",
    "CustomVoice": "tts_generate_customvoice",
    "VoiceDesign": "tts_generate_voicedesign",
}

MIME_TO_EXT = {
    "audio/wav": "wav", "audio/mpeg": "mp3", "audio/flac": "flac",
    "audio/pcm": "pcm", "audio/aac": "aac", "audio/opus": "opus",
}


def mcp_tts_generate(
    text: str,
    tts_model: str,
    voice: str,
    language: str,
    instructions: str,
    response_format: str,
    speed: float,
    ref_audio_file,  # Gradio File 组件
    ref_text: str,
):
    """通过 MCP 三个 TTS 工具之一合成语音（按 tts_model 选择工具）"""
    tool_name = TTS_MODEL_TO_TOOL.get(tts_model, "tts_generate_customvoice")
    args = {"text": text, "response_format": response_format, "speed": speed}
    if voice and voice.strip():
        args["voice"] = voice.strip()
    if language and language != "Auto":
        args["language"] = language
    if instructions and instructions.strip():
        args["instructions"] = instructions.strip()
    if ref_text and ref_text.strip():
        args["ref_text"] = ref_text.strip()
    if ref_audio_file is not None:
        with open(ref_audio_file, "rb") as f:
            audio_bytes = f.read()
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        args["ref_audio"] = f"data:audio/wav;base64,{b64}"
    if tts_model == "Base" and ref_audio_file is not None:
        args["x_vector_only_mode"] = not (ref_text and ref_text.strip())

    resp = mcp_tool_call(tool_name, args)
    content_list, legacy_parsed = parse_mcp_result(resp)

    # 新格式：content 项 type == "audio"
    if content_list and isinstance(content_list[0], dict):
        item = content_list[0]
        if item.get("type") == "audio" and item.get("data"):
            try:
                audio_bytes = base64.b64decode(item["data"])
            except Exception as e:
                return None, json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)
            mime = item.get("mimeType", "audio/wav")
            ext = MIME_TO_EXT.get(mime, "wav")
            out_path = f"/tmp/mcp_tts_output.{ext}"
            with open(out_path, "wb") as f:
                f.write(audio_bytes)
            info = {"response_format": ext, "audio_bytes": len(audio_bytes)}
            return out_path, json.dumps(info, ensure_ascii=False, indent=2)
        if item.get("type") == "text":
            raw = item.get("text", "")
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict) and obj.get("error"):
                    return None, json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return None, raw if isinstance(raw, str) else json.dumps(content_list, ensure_ascii=False, indent=2)

    # 旧格式
    result = legacy_parsed if legacy_parsed is not None else resp
    if isinstance(result, dict) and "error" in result:
        return None, json.dumps(result, ensure_ascii=False, indent=2)
    if isinstance(result, dict) and "audio_base64" in result:
        audio_bytes = base64.b64decode(result["audio_base64"])
        ext = (result.get("response_format") or response_format or "wav").strip().lower()
        if ext not in ("wav", "mp3", "flac", "pcm", "aac", "opus"):
            ext = "wav"
        out_path = f"/tmp/mcp_tts_output.{ext}"
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        info = {k: v for k, v in result.items() if k != "audio_base64"}
        info["audio_bytes"] = len(audio_bytes)
        return out_path, json.dumps(info, ensure_ascii=False, indent=2)
    return None, json.dumps(result, ensure_ascii=False, indent=2)


# ========== 4. MCP: Video ==========
def _image_to_data_url(file_path):
    """将上传的图片文件转为 data URL，供 I2V 使用"""
    if file_path is None:
        return None
    with open(file_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("utf-8")
    ext = (file_path.split(".")[-1] or "png").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64,{b64}"


def mcp_video_generate(prompt: str, negative_prompt: str, width: int, height: int, num_frames: int, fps: int, seed: str, image_file):
    args = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "fps": fps,
    }
    if seed and seed.strip():
        try:
            args["seed"] = int(seed.strip())
        except ValueError:
            pass
    img_data = _image_to_data_url(image_file)
    if img_data:
        args["image"] = img_data
    resp = mcp_tool_call("video_generate", args)
    content_list, legacy = parse_mcp_result(resp)
    result = legacy if legacy is not None else _content_first_text_json(content_list, resp)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _content_first_text_json(content_list, fallback):
    """从 content 首项 type=text 解析 JSON，否则返回 fallback。"""
    if content_list and isinstance(content_list[0], dict) and content_list[0].get("type") == "text":
        t = content_list[0].get("text", "")
        if t:
            try:
                return json.loads(t)
            except Exception:
                pass
    return fallback


def mcp_video_status(task_id: str):
    tid = (task_id or "").strip()
    if not tid:
        return json.dumps({"error": "请先填写或粘贴 task_id 再查询状态"}, ensure_ascii=False, indent=2)
    resp = mcp_tool_call("video_status", {"task_id": tid})
    content_list, legacy = parse_mcp_result(resp)
    result = legacy if legacy is not None else _content_first_text_json(content_list, resp)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ========== 5. Gateway: Embedding ==========
def gateway_embedding(text: str):
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.post(
            f"{GATEWAY_BASE}/embedding/v1/embeddings",
            json={"model": "Qwen3-Embedding-8B", "input": text}
        )
        data = safe_json(resp)
        # 截断 embedding 向量（太长）
        if "data" in data and data["data"]:
            for item in data["data"]:
                if "embedding" in item and len(item["embedding"]) > 10:
                    item["embedding"] = item["embedding"][:10] + ["...(truncated)"]
        return json.dumps(data, ensure_ascii=False, indent=2)


# ========== 6. Gateway: TTS ==========
def gateway_tts(
    text: str,
    tts_model: str,
    voice: str,
    language: str,
    instructions: str,
    response_format: str,
    speed: float,
    ref_audio_file,
    ref_text: str,
):
    """通过 Gateway TTS 路由合成语音"""
    body = {
        "input": text,
        "response_format": response_format,
        "speed": speed,
    }
    if voice and voice.strip():
        body["voice"] = voice.strip()
    if language and language != "Auto":
        body["language"] = language
    if instructions and instructions.strip():
        body["instructions"] = instructions.strip()
    if ref_text and ref_text.strip():
        body["ref_text"] = ref_text.strip()

    if ref_audio_file is not None:
        with open(ref_audio_file, "rb") as f:
            audio_bytes = f.read()
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        body["ref_audio"] = f"data:audio/wav;base64,{b64}"

    # Base 模式：仅参考音频 → x_vector_only；参考音频+转写 → ICL
    if tts_model == "Base" and ref_audio_file is not None:
        body["x_vector_only_mode"] = not (ref_text and ref_text.strip())

    url = f"{GATEWAY_BASE}/tts/{tts_model}/v1/audio/speech"

    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.post(url, json=body)

    content_type = resp.headers.get("content-type", "")
    if "audio" in content_type or resp.content[:4] == b"RIFF":
        # 按请求的 response_format 使用正确扩展名
        ext = (body.get("response_format") or "wav").strip().lower()
        if ext not in ("wav", "mp3", "flac", "pcm", "aac", "opus"):
            ext = "mp3" if "mpeg" in content_type else "wav"
        out_path = f"/tmp/gateway_tts_output.{ext}"
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path, f"成功，{len(resp.content)} bytes"
    else:
        return None, resp.text[:2000]


# ========== 7. Gateway: Wan Video ==========
def gateway_video_generate(prompt: str, negative_prompt: str, width: int, height: int, num_frames: int, fps: int, seed: str, image_file):
    body = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "fps": fps,
    }
    if seed and seed.strip():
        try:
            body["seed"] = int(seed.strip())
        except ValueError:
            pass
    img_data = _image_to_data_url(image_file)
    if img_data:
        body["image"] = img_data

    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.post(f"{GATEWAY_BASE}/wan/v1/video/generate", json=body)
        return json.dumps(safe_json(resp), ensure_ascii=False, indent=2)


def gateway_video_status(task_id: str):
    tid = (task_id or "").strip()
    if not tid:
        return json.dumps({"error": "请先填写或粘贴 task_id 再查询状态"}, ensure_ascii=False, indent=2)
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.get(f"{GATEWAY_BASE}/wan/v1/video/status/{tid}")
        return json.dumps(safe_json(resp), ensure_ascii=False, indent=2)


def gateway_video_download(task_id: str):
    tid = (task_id or "").strip()
    if not tid:
        return None, "请先填写 task_id 再下载"
    url = f"{GATEWAY_BASE}/wan/v1/video/download/{tid}"
    with httpx.Client(timeout=TIMEOUT, verify=False) as client:
        resp = client.get(url)
    if resp.status_code == 200 and len(resp.content) > 100:
        out_path = "/tmp/gateway_video.mp4"
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path, f"下载成功，{len(resp.content)} bytes"
    else:
        return None, resp.text[:2000]


# ========== 字体与样式 ==========
# 中英文兼顾的字体栈：优先 Noto Sans SC / 思源黑体，再回退到系统无衬线
FONT_CSS = """
.gradio-container, .gradio-container * {
    font-family: "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC",
                 "PingFang SC", "Microsoft YaHei", "WenQuanYi Micro Hei",
                 "Hiragino Sans GB", system-ui, -apple-system, sans-serif !important;
}
"""


# ========== Gradio UI ==========
def build_ui():
    with gr.Blocks(title="AI Services") as app:
        gr.Markdown("# AI Services")

        # ===== Chat: LLM + MCP Agent =====
        build_chat_tab(app, MCP_BASE, GATEWAY_BASE)

        # ===== Tab 1: 健康检查 =====
        with gr.Tab("健康检查"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### MCP (6006)")
                    mcp_health_btn = gr.Button("检查 MCP 健康")
                    mcp_health_out = gr.JSON(label="MCP /health")
                with gr.Column():
                    gr.Markdown("### Gateway (6008)")
                    gw_health_btn = gr.Button("检查 Gateway 健康")
                    gw_health_out = gr.JSON(label="Gateway /health")

            mcp_health_btn.click(check_mcp_health, outputs=mcp_health_out)
            gw_health_btn.click(check_gateway_health, outputs=gw_health_out)

        # ===== Tab 2: MCP 协议 =====
        with gr.Tab("MCP 协议"):
            with gr.Row():
                init_btn = gr.Button("initialize")
                list_btn = gr.Button("tools/list")
            mcp_proto_out = gr.JSON(label="响应")
            init_btn.click(mcp_initialize, outputs=mcp_proto_out)
            list_btn.click(mcp_tools_list, outputs=mcp_proto_out)

        # ===== Tab 3: MCP TTS =====
        with gr.Tab("MCP TTS"):
            with gr.Row():
                with gr.Column():
                    mcp_tts_text = gr.Textbox(label="文本", value="你好，这是一次测试。", lines=2)
                    mcp_tts_model = gr.Dropdown(["Base", "CustomVoice", "VoiceDesign"], value="CustomVoice", label="tts_model")
                    mcp_tts_voice = gr.Dropdown(choices=TTS_CUSTOMVOICE_VOICE_CHOICES, value="Vivian", label="voice（CustomVoice 说话人）", visible=True)
                    mcp_tts_lang = gr.Dropdown(["Auto", "Chinese", "English", "Japanese", "Korean"], value="Auto", label="language", visible=True)
                    mcp_tts_instr = gr.Textbox(label="instructions", placeholder="用自然语言描述声音风格", visible=False)
                    mcp_tts_fmt = gr.Dropdown(["wav", "mp3", "flac", "pcm", "aac", "opus"], value="wav", label="response_format")
                    mcp_tts_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label="speed")
                    mcp_tts_ref_audio = gr.File(label="ref_audio（必选）", file_types=["audio"], visible=False)
                    mcp_tts_ref_text = gr.Textbox(label="ref_text（可选：参考音频文本，填则 ICL，不填则 x_vector_only）", visible=False)
                    mcp_tts_btn = gr.Button("生成语音", variant="primary")
                with gr.Column():
                    mcp_tts_audio = gr.Audio(label="生成的音频", type="filepath")
                    mcp_tts_info = gr.Textbox(label="响应信息", lines=10)

            mcp_tts_model.change(
                _tts_model_to_visibility,
                inputs=[mcp_tts_model],
                outputs=[mcp_tts_voice, mcp_tts_lang, mcp_tts_instr, mcp_tts_ref_audio, mcp_tts_ref_text],
            )
            mcp_tts_btn.click(
                mcp_tts_generate,
                inputs=[mcp_tts_text, mcp_tts_model, mcp_tts_voice, mcp_tts_lang, mcp_tts_instr, mcp_tts_fmt, mcp_tts_speed, mcp_tts_ref_audio, mcp_tts_ref_text],
                outputs=[mcp_tts_audio, mcp_tts_info]
            )

        # ===== Tab 4: MCP Video =====
        with gr.Tab("MCP Video"):
            with gr.Row():
                with gr.Column():
                    mcp_vid_prompt = gr.Textbox(label="prompt", value="a cat running on the grass", lines=2)
                    mcp_vid_neg = gr.Textbox(label="negative_prompt")
                    with gr.Row():
                        mcp_vid_w = gr.Number(label="width", value=480, precision=0)
                        mcp_vid_h = gr.Number(label="height", value=480, precision=0)
                    with gr.Row():
                        mcp_vid_frames = gr.Number(label="num_frames", value=24, precision=0)
                        mcp_vid_fps = gr.Number(label="fps", value=24, precision=0)
                    mcp_vid_seed = gr.Textbox(label="seed（可选）")
                    mcp_vid_image = gr.File(label="I2V 首帧图（可选，上传则为图文生视频）", file_types=["image"])
                    mcp_vid_gen_btn = gr.Button("提交生成任务", variant="primary")
                with gr.Column():
                    mcp_vid_gen_out = gr.Textbox(label="生成响应", lines=6)
                    mcp_vid_task_id = gr.Textbox(label="task_id（粘贴后查询状态 / 下载）")
                    mcp_vid_status_btn = gr.Button("查询状态")
                    mcp_vid_status_out = gr.Textbox(label="状态响应", lines=6)
                    mcp_vid_dl_btn = gr.Button("下载视频（经 Gateway 公网）", variant="secondary")
                    mcp_vid_video = gr.Video(label="视频")
                    mcp_vid_dl_info = gr.Textbox(label="下载说明", lines=2)

            mcp_vid_gen_btn.click(
                mcp_video_generate,
                inputs=[mcp_vid_prompt, mcp_vid_neg, mcp_vid_w, mcp_vid_h, mcp_vid_frames, mcp_vid_fps, mcp_vid_seed, mcp_vid_image],
                outputs=mcp_vid_gen_out
            )
            mcp_vid_status_btn.click(mcp_video_status, inputs=mcp_vid_task_id, outputs=mcp_vid_status_out)
            mcp_vid_dl_btn.click(
                gateway_video_download,
                inputs=mcp_vid_task_id,
                outputs=[mcp_vid_video, mcp_vid_dl_info]
            )

        # ===== Tab 5: Gateway Embedding =====
        with gr.Tab("Gateway Embedding"):
            gw_emb_text = gr.Textbox(label="输入文本", value="hello world", lines=2)
            gw_emb_btn = gr.Button("生成 Embedding", variant="primary")
            gw_emb_out = gr.Textbox(label="响应（embedding 已截断）", lines=15)
            gw_emb_btn.click(gateway_embedding, inputs=gw_emb_text, outputs=gw_emb_out)

        # ===== Tab 6: Gateway TTS =====
        with gr.Tab("Gateway TTS"):
            with gr.Row():
                with gr.Column():
                    gw_tts_text = gr.Textbox(label="文本", value="你好，这是一次测试。", lines=2)
                    gw_tts_model = gr.Dropdown(["Base", "CustomVoice", "VoiceDesign"], value="CustomVoice", label="路由前缀（模型）")
                    gw_tts_voice = gr.Dropdown(choices=TTS_CUSTOMVOICE_VOICE_CHOICES, value="Vivian", label="voice（CustomVoice 说话人）", visible=True)
                    gw_tts_lang = gr.Dropdown(["Auto", "Chinese", "English", "Japanese", "Korean"], value="Auto", label="language", visible=True)
                    gw_tts_instr = gr.Textbox(label="instructions", placeholder="用自然语言描述声音风格", visible=False)
                    gw_tts_fmt = gr.Dropdown(["wav", "mp3", "flac", "pcm", "aac", "opus"], value="wav", label="response_format")
                    gw_tts_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label="speed")
                    gw_tts_ref_audio = gr.File(label="ref_audio（必选）", file_types=["audio"], visible=False)
                    gw_tts_ref_text = gr.Textbox(label="ref_text（可选：填则 ICL，不填则 x_vector_only）", visible=False)
                    gw_tts_btn = gr.Button("生成语音", variant="primary")
                with gr.Column():
                    gw_tts_audio = gr.Audio(label="生成的音频", type="filepath")
                    gw_tts_info = gr.Textbox(label="响应信息", lines=6)

            gw_tts_model.change(
                _tts_model_to_visibility,
                inputs=[gw_tts_model],
                outputs=[gw_tts_voice, gw_tts_lang, gw_tts_instr, gw_tts_ref_audio, gw_tts_ref_text],
            )
            gw_tts_btn.click(
                gateway_tts,
                inputs=[gw_tts_text, gw_tts_model, gw_tts_voice, gw_tts_lang, gw_tts_instr, gw_tts_fmt, gw_tts_speed, gw_tts_ref_audio, gw_tts_ref_text],
                outputs=[gw_tts_audio, gw_tts_info]
            )

        # ===== Tab 7: Gateway Wan Video =====
        with gr.Tab("Gateway Wan Video"):
            with gr.Row():
                with gr.Column():
                    gw_vid_prompt = gr.Textbox(label="prompt", value="smoke test", lines=2)
                    gw_vid_neg = gr.Textbox(label="negative_prompt")
                    with gr.Row():
                        gw_vid_w = gr.Number(label="width", value=480, precision=0)
                        gw_vid_h = gr.Number(label="height", value=480, precision=0)
                    with gr.Row():
                        gw_vid_frames = gr.Number(label="num_frames", value=24, precision=0)
                        gw_vid_fps = gr.Number(label="fps", value=24, precision=0)
                    gw_vid_seed = gr.Textbox(label="seed（可选）")
                    gw_vid_image = gr.File(label="I2V 首帧图（可选）", file_types=["image"])
                    gw_vid_gen_btn = gr.Button("提交生成任务", variant="primary")
                with gr.Column():
                    gw_vid_gen_out = gr.Textbox(label="生成响应", lines=6)
                    gw_vid_task_id = gr.Textbox(label="task_id")
                    gw_vid_status_btn = gr.Button("查询状态")
                    gw_vid_status_out = gr.Textbox(label="状态响应", lines=6)
                    gw_vid_dl_btn = gr.Button("下载视频")
                    gw_vid_video = gr.Video(label="视频")
                    gw_vid_dl_info = gr.Textbox(label="下载信息")

            gw_vid_gen_btn.click(
                gateway_video_generate,
                inputs=[gw_vid_prompt, gw_vid_neg, gw_vid_w, gw_vid_h, gw_vid_frames, gw_vid_fps, gw_vid_seed, gw_vid_image],
                outputs=gw_vid_gen_out
            )
            gw_vid_status_btn.click(gateway_video_status, inputs=gw_vid_task_id, outputs=gw_vid_status_out)
            gw_vid_dl_btn.click(gateway_video_download, inputs=gw_vid_task_id, outputs=[gw_vid_video, gw_vid_dl_info])

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=gr.themes.Soft(), css=FONT_CSS)
