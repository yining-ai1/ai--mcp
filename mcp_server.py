#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Server - 提供 TTS 和 Wan 视频生成的 MCP 接口
- TTS: 后端 8001/8002/8003（不同模型，需显式选择）
- Wan: 后端 8004
"""

import json
import asyncio
import aiohttp
import base64
from typing import Any
import sys

# ========== MCP 协议实现 ==========

# 后端服务地址（内网）
TTS_PORTS = [8001, 8002, 8003]  # 三个 TTS 实例（不同模型，建议显式选择）
TTS_MODEL_TO_PORT = {
    "base": 8001,
    "customvoice": 8002,
    "voicedesign": 8003,
}
# 后端 API 要求 task_type 为 Literal['Base','CustomVoice','VoiceDesign']，必须与字面量完全一致（区分大小写）
TTS_MODEL_TO_TASK_TYPE = {
    "base": "Base",
    "customvoice": "CustomVoice",
    "voicedesign": "VoiceDesign",
}
TTS_PORT_TO_MODEL = {v: k for k, v in TTS_MODEL_TO_PORT.items()}
# Qwen3-TTS CustomVoice 官方说话人（母语建议：Vivian/Serena/Uncle_Fu/Dylan/Eric 中文，Ryan/Aiden 英语，Ono_Anna 日语，Sohee 韩语）
TTS_CUSTOMVOICE_VOICES = [
    "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
    "Ryan", "Aiden", "Ono_Anna", "Sohee",
]
WAN_HOST = "127.0.0.1:8004"


class MCPServer:
    def __init__(self):
        self.tools = {
            "tts_generate": {
                "name": "tts_generate",
                "description": "将文本转换为语音，返回 base64 音频数据",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "要转换的文本内容"
                        },
                        "input": {
                            "type": "string",
                            "description": "OpenAI 兼容字段：等价于 text（两者二选一）"
                        },
                        "tts_model": {
                            "type": "string",
                            "description": "选择具体 TTS 模型：Base/CustomVoice/VoiceDesign（默认 Base）",
                            "enum": ["Base", "CustomVoice", "VoiceDesign"],
                            "default": "Base"
                        },
                        "tts_port": {
                            "type": "integer",
                            "description": "选择具体 TTS 后端端口（不同模型），默认 8001",
                            "enum": [8001, 8002, 8003],
                            "default": 8001
                        },
                        "voice": {
                            "type": "string",
                            "description": "CustomVoice 说话人，建议用其母语以获得最佳音质。默认 Vivian",
                            "enum": TTS_CUSTOMVOICE_VOICES,
                            "default": "Vivian"
                        },
                        "language": {
                            "type": "string",
                            "description": "语言：Auto/Chinese/English/Japanese/Korean（可选）"
                        },
                        "instructions": {
                            "type": "string",
                            "description": "风格/情感指令（可选）"
                        },
                        "response_format": {
                            "type": "string",
                            "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）"
                        },
                        "speed": {
                            "type": "number",
                            "description": "语速，默认1.0",
                            "default": 1.0
                        },
                        "ref_audio": {
                            "type": "string",
                            "description": "Base 声音克隆：参考音频 URL 或 base64/data-url（可选；Base 推荐提供）"
                        },
                        "ref_text": {
                            "type": "string",
                            "description": "Base 声音克隆：参考音频转写文本（可选）"
                        },
                        "x_vector_only_mode": {
                            "type": "boolean",
                            "description": "Base 声音克隆：仅使用说话人 embedding（可选）"
                        },
                        "max_new_tokens": {
                            "type": "integer",
                            "description": "最大生成 token（可选）"
                        }
                    },
                    "required": []
                }
            },
            "video_generate": {
                "name": "video_generate",
                "description": "根据文本提示生成视频（T2V）；若提供 image 则为图文生视频（I2V）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "视频生成提示词"
                        },
                        "negative_prompt": {
                            "type": "string",
                            "description": "负面提示词（可选）"
                        },
                        "width": {
                            "type": "integer",
                            "description": "视频宽度",
                            "default": 480
                        },
                        "height": {
                            "type": "integer",
                            "description": "视频高度",
                            "default": 480
                        },
                        "num_frames": {
                            "type": "integer",
                            "description": "帧数（可选，默认 24）"
                        },
                        "fps": {
                            "type": "integer",
                            "description": "帧率（可选，默认 24）"
                        },
                        "seed": {
                            "type": "integer",
                            "description": "随机种子（可选）"
                        },
                        "image": {
                            "type": "string",
                            "description": "I2V 首帧/参考图：图片 URL 或 base64/data URL。不传则为纯 T2V"
                        }
                    },
                    "required": ["prompt"]
                }
            },
            "video_status": {
                "name": "video_status",
                "description": "查询视频生成任务状态",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "任务ID"
                        }
                    },
                    "required": ["task_id"]
                }
            },
            "video_download": {
                "name": "video_download",
                "description": "根据 task_id 下载已完成的视频，返回 base64 编码的视频数据（mp4）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "视频生成任务ID（由 video_generate 返回）"
                        }
                    },
                    "required": ["task_id"]
                }
            }
        }
    
    async def handle_request(self, request: dict) -> dict:
        """处理 MCP 请求"""
        method = request.get("method", "")
        req_id = request.get("id")
        
        if method == "initialize":
            return self._response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-tools-server", "version": "1.0.0"}
            })
        
        elif method == "tools/list":
            return self._response(req_id, {
                "tools": list(self.tools.values())
            })
        
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            result = await self._call_tool(tool_name, arguments)
            return self._response(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        
        else:
            return self._error(req_id, -32601, f"Method not found: {method}")

    def _resolve_tts_target(self, args: dict) -> tuple[int | None, str | None, dict | None]:
        """解析并校验 TTS 目标（端口 + 模型类型）。

        目标：避免把错误 task_type 发到不匹配的模型上导致引擎崩溃。

        规则：
        - 若同时提供 tts_model + tts_port：必须一致，否则直接报错
        - 若仅提供 tts_port：推断对应模型类型
        - 若仅提供 tts_model：映射到对应端口
        """
        port: int | None = None
        model_key: str | None = None

        if "tts_port" in args and args.get("tts_port") is not None:
            try:
                port = int(args.get("tts_port"))
            except Exception:
                return None, None, {"error": "Invalid tts_port (must be integer)", "allowed_tts_ports": TTS_PORTS}

        if "tts_model" in args and args.get("tts_model") is not None:
            model_raw = args.get("tts_model")
            model_key = str(model_raw).strip().lower()
            if model_key not in TTS_MODEL_TO_PORT:
                return None, None, {
                    "error": "Invalid tts_model; must be Base/CustomVoice/VoiceDesign",
                    "allowed_tts_models": ["Base", "CustomVoice", "VoiceDesign"],
                }

        # infer missing side
        if port is None and model_key is not None:
            port = TTS_MODEL_TO_PORT.get(model_key)
        if model_key is None and port is not None:
            model_key = TTS_PORT_TO_MODEL.get(port)

        if port not in TTS_PORTS or model_key not in TTS_MODEL_TO_PORT:
            return None, None, {
                "error": "Cannot resolve tts target; provide tts_model and/or tts_port",
                "allowed_tts_models": ["Base", "CustomVoice", "VoiceDesign"],
                "allowed_tts_ports": TTS_PORTS,
            }

        # consistency check when both explicitly provided
        if "tts_port" in args and "tts_model" in args:
            expected_port = TTS_MODEL_TO_PORT.get(model_key)
            if expected_port != port:
                return None, None, {
                    "error": "tts_port does not match tts_model (blocked for safety)",
                    "tts_model": args.get("tts_model"),
                    "tts_port": port,
                    "expected_port_for_model": expected_port,
                    "expected_model_for_port": TTS_MODEL_TO_TASK_TYPE.get(TTS_PORT_TO_MODEL.get(port), ""),
                }

        return port, model_key, None

    def _tts_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/v1/audio/speech"

    def _tts_payload(self, args: dict, task_type: str) -> dict | None:
        """构造 vllm-omni /v1/audio/speech 请求体（OpenAI 兼容）。"""
        text = args.get("input") or args.get("text")
        if not text or not str(text).strip():
            return None

        payload: dict = {
            "input": str(text),
            "task_type": task_type,
            "speed": args.get("speed", 1.0),
            "response_format": args.get("response_format", "wav"),
        }

        # Optional fields (keep as-is when provided)
        for k in ("voice", "language", "instructions", "ref_audio", "ref_text", "x_vector_only_mode", "max_new_tokens", "model"):
            if k in args and args.get(k) is not None and args.get(k) != "":
                payload[k] = args.get(k)

        # Sensible default for CustomVoice
        if "voice" not in payload and task_type == "CustomVoice":
            payload["voice"] = "Vivian"

        return payload

    async def _call_tool(self, name: str, args: dict) -> Any:
        """调用具体工具"""
        async with aiohttp.ClientSession() as session:
            if name == "tts_generate":
                port, model_key, err = self._resolve_tts_target(args)
                if err:
                    return err
                assert port is not None and model_key is not None
                task_type = TTS_MODEL_TO_TASK_TYPE[model_key]
                url = self._tts_url(port)
                payload = self._tts_payload(args, task_type=task_type)
                if not payload:
                    return {
                        "error": "Invalid args. Require text/input; model must be Base/CustomVoice/VoiceDesign; port must be one of 8001/8002/8003",
                        "allowed_tts_models": ["Base", "CustomVoice", "VoiceDesign"],
                        "allowed_tts_ports": TTS_PORTS,
                    }
                async with session.post(
                    url,
                    json=payload
                ) as resp:
                    content_type = (resp.headers.get("content-type") or "").lower()
                    raw = await resp.read()

                    # If server returns JSON error, surface it as JSON
                    if "application/json" in content_type:
                        try:
                            return json.loads(raw.decode("utf-8", errors="replace"))
                        except Exception:
                            return {"error": "tts backend returned json but failed to decode", "raw": raw[:200].decode("utf-8", errors="replace")}

                    audio_b64 = base64.b64encode(raw).decode("utf-8")
                    return {
                        "audio_base64": audio_b64,
                        "content_type": content_type or "application/octet-stream",
                        "bytes": len(raw),
                        "tts_model": payload.get("task_type"),
                        "response_format": payload.get("response_format"),
                    }
            
            elif name == "video_generate":
                payload = {
                    "prompt": args["prompt"],
                    "negative_prompt": args.get("negative_prompt", ""),
                    "width": args.get("width", 480),
                    "height": args.get("height", 480),
                    "num_frames": args.get("num_frames", 24),
                    "fps": args.get("fps", 24),
                    "seed": args.get("seed"),
                }
                if args.get("image"):
                    payload["image"] = args.get("image")
                async with session.post(
                    f"http://{WAN_HOST}/v1/video/generate",
                    json=payload,
                ) as resp:
                    return await resp.json()
            
            elif name == "video_status":
                async with session.get(
                    f"http://{WAN_HOST}/v1/video/status/{args['task_id']}"
                ) as resp:
                    return await resp.json()

            elif name == "video_download":
                task_id = (args.get("task_id") or "").strip()
                if not task_id:
                    return {"error": "task_id is required"}
                async with session.get(
                    f"http://{WAN_HOST}/v1/video/download/{task_id}"
                ) as resp:
                    raw = await resp.read()
                    if resp.status != 200 or len(raw) < 100:
                        try:
                            return json.loads(raw.decode("utf-8", errors="replace"))
                        except Exception:
                            return {
                                "error": "video download failed",
                                "status_code": resp.status,
                                "detail": raw[:500].decode("utf-8", errors="replace") if raw else "",
                            }
                    video_b64 = base64.b64encode(raw).decode("utf-8")
                    return {
                        "video_base64": video_b64,
                        "content_type": resp.headers.get("content-type") or "video/mp4",
                        "bytes": len(raw),
                        "task_id": task_id,
                    }
            
            else:
                return {"error": f"Unknown tool: {name}"}
    
    def _response(self, req_id, result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    
    def _error(self, req_id, code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ========== stdio 模式运行 ==========
async def run_stdio():
    server = MCPServer()
    
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            
            request = json.loads(line.strip())
            response = await server.handle_request(request)
            
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            
        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


# ========== HTTP 模式运行（用于调试或 SSE） ==========
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()
server = MCPServer()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-server"}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """HTTP JSON-RPC 端点"""
    body = await request.json()
    response = await server.handle_request(body)
    return response


@app.get("/sse")
async def sse_endpoint():
    """SSE 端点（用于流式）"""
    async def event_stream():
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["stdio", "http"], default="http")
    parser.add_argument("--port", type=int, default=6006)
    args = parser.parse_args()
    
    if args.mode == "stdio":
        asyncio.run(run_stdio())
    else:
        uvicorn.run(app, host="0.0.0.0", port=args.port)