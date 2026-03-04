# -*- coding: utf-8 -*-
"""TTS tool declarations (name / description / inputSchema)."""

from mcp_server.config import TTS_CUSTOMVOICE_VOICES


def _text_input_props(required_text: bool = True):
    props = {
        "text": {"type": "string", "description": "要转换的文本内容"},
        "input": {"type": "string", "description": "等价于 text，二选一（OpenAI 兼容）"},
    }
    return props, ["text"] if required_text else []


def get_tts_tools() -> dict:
    """Return TTS tools dict keyed by tool name."""
    return {
        "tts_generate_base": {
            "name": "tts_generate_base",
            "description": "TTS Base 基础模型：支持从用户提供的音频输入中实现约 3 秒快速音色克隆。需提供 text 与 ref_audio（必填）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "response_format": {
                        "type": "string",
                        "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）",
                    },
                    "speed": {"type": "number", "description": "语速，0.25-4.0，默认 1.0", "default": 1.0},
                    "ref_audio": {
                        "type": "string",
                        "description": "参考音频：须为 http/https URL 或 data:...;base64,... 格式（必填）",
                    },
                    "ref_text": {"type": "string", "description": "参考音频转写文本（可选，非 x_vector_only 时推荐）"},
                    "x_vector_only_mode": {
                        "type": "boolean",
                        "description": "仅使用说话人 embedding（可选）",
                    },
                    "max_new_tokens": {"type": "integer", "description": "最大生成 token，1-4096（可选）"},
                },
                "required": ["text", "ref_audio"],
            },
        },
        "tts_generate_customvoice": {
            "name": "tts_generate_customvoice",
            "description": "TTS CustomVoice 模型：通过用户指令对目标音色进行风格控制；支持 9 种优质音色（Vivian、Serena、Uncle_Fu 等）。需提供 text，可选 voice、instructions。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "voice": {
                        "type": "string",
                        "description": "说话人，建议用其母语。默认 Vivian",
                        "enum": TTS_CUSTOMVOICE_VOICES,
                        "default": "Vivian",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "风格/情感指令（可选），如「用开心的语气说」「Speak with enthusiasm」",
                    },
                    "language": {
                        "type": "string",
                        "description": "语言：Auto/Chinese/English/Japanese/Korean/German/French/Russian/Portuguese/Spanish/Italian（可选）",
                    },
                    "response_format": {
                        "type": "string",
                        "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）",
                    },
                    "speed": {"type": "number", "description": "语速，0.25-4.0，默认 1.0", "default": 1.0},
                },
                "required": ["text"],
            },
        },
        "tts_generate_voicedesign": {
            "name": "tts_generate_voicedesign",
            "description": "TTS VoiceDesign 模型：根据用户提供的描述进行音色设计。需提供 text 与 instructions（必填）。instructions 最多 500 字符。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "instructions": {"type": "string", "description": "音色/风格描述（必填），如「温柔女声」「成熟男声、语速慢」；最多 500 字符"},
                    "language": {
                        "type": "string",
                        "description": "语言：Auto/Chinese/English/Japanese/Korean/German/French/Russian/Portuguese/Spanish/Italian（可选）",
                    },
                    "response_format": {
                        "type": "string",
                        "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）",
                    },
                    "speed": {"type": "number", "description": "语速，0.25-4.0，默认 1.0", "default": 1.0},
                },
                "required": ["text", "instructions"],
            },
        },
        "tts_generate_base_06b": {
            "name": "tts_generate_base_06b",
            "description": "TTS Base 0.6B 轻量模型：音色克隆，约 3 秒参考音频即可。需提供 text 与 ref_audio（必填）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "response_format": {
                        "type": "string",
                        "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）",
                    },
                    "speed": {"type": "number", "description": "语速，0.25-4.0，默认 1.0", "default": 1.0},
                    "ref_audio": {
                        "type": "string",
                        "description": "参考音频：须为 http/https URL 或 data:...;base64,... 格式（必填）",
                    },
                    "ref_text": {"type": "string", "description": "参考音频转写文本（可选，非 x_vector_only 时推荐）"},
                    "x_vector_only_mode": {
                        "type": "boolean",
                        "description": "仅使用说话人 embedding（可选）",
                    },
                    "max_new_tokens": {"type": "integer", "description": "最大生成 token，1-4096（可选）"},
                },
                "required": ["text", "ref_audio"],
            },
        },
        "tts_generate_customvoice_06b": {
            "name": "tts_generate_customvoice_06b",
            "description": "TTS CustomVoice 0.6B 轻量模型：9 种优质音色（Vivian、Serena、Ryan 等）。需提供 text，可选 voice、language。注意：0.6B 不支持 instructions 风格指令（仅 1.7B CustomVoice 支持）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "voice": {
                        "type": "string",
                        "description": "说话人，建议用其母语。默认 Vivian",
                        "enum": TTS_CUSTOMVOICE_VOICES,
                        "default": "Vivian",
                    },
                    "language": {
                        "type": "string",
                        "description": "语言：Auto/Chinese/English/Japanese/Korean/German/French/Russian/Portuguese/Spanish/Italian（可选）",
                    },
                    "response_format": {
                        "type": "string",
                        "description": "音频格式：wav/mp3/flac/pcm/aac/opus（默认 wav）",
                    },
                    "speed": {"type": "number", "description": "语速，0.25-4.0，默认 1.0", "default": 1.0},
                },
                "required": ["text"],
            },
        },
        "tts_stream_voxtream": {
            "name": "tts_stream_voxtream",
            "description": "VoXtream 流式 TTS（long-running）：tools/call 立刻返回 session_id；合成过程中通过 notifications/message 推送 tts.audio_chunk（含 audio_base64、sample_rate），最后推送 tts.done。客户端可边收边播。需 text、prompt_audio、prompt_text；可选 full_stream。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "prompt_audio": {
                        "type": "string",
                        "description": "参考音频：http(s) URL 或 data:audio/...;base64,...（必填，约 3–5 秒）",
                    },
                    "ref_audio": {"type": "string", "description": "同 prompt_audio，二选一"},
                    "prompt_text": {
                        "type": "string",
                        "description": "参考音频的转写文本（必填，最多 250 字符）",
                    },
                    "ref_text": {"type": "string", "description": "同 prompt_text，二选一"},
                    "full_stream": {
                        "type": "boolean",
                        "description": "是否启用 full-stream，默认 true",
                        "default": True,
                    },
                },
                "required": ["text"],
            },
        },
        "tts_stream_cosyvoice": {
            "name": "tts_stream_cosyvoice",
            "description": "CosyVoice 流式 TTS（long-running）：支持中文、9 语言、18+ 方言。tools/call 立刻返回 session_id；合成过程中通过 notifications/message 推送 tts.audio_chunk（含 audio_base64、sample_rate），最后推送 tts.done。必填 text、prompt_audio、prompt_text；可选 full_stream。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "prompt_audio": {
                        "type": "string",
                        "description": "参考音频（零样本音色克隆）：http(s) URL 或 data:audio/wav;base64,...（必填，建议 3–5 秒 WAV）",
                    },
                    "ref_audio": {"type": "string", "description": "同 prompt_audio，二选一"},
                    "prompt_text": {
                        "type": "string",
                        "description": "参考音频的转写内容（必填），须与参考音频逐字一致。支持中文，服务端会自动添加 CosyVoice 所需前缀",
                    },
                    "ref_text": {"type": "string", "description": "同 prompt_text，二选一"},
                    "full_stream": {
                        "type": "boolean",
                        "description": "是否流式生成，默认 true",
                        "default": True,
                    },
                },
                "required": ["text"],
            },
        },
        "tts_stream_qwen3": {
            "name": "tts_stream_qwen3",
            "description": "Qwen3 streaming 流式 TTS（long-running）：基于 dffdeeq/Qwen3-TTS-streaming fork。tools/call 立刻返回 session_id；合成过程中通过 notifications/message 推送 tts.audio_chunk（含 audio_base64、sample_rate），最后推送 tts.done。必填 text、ref_audio；x_vector_only_mode=false 时必填 ref_text。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **_text_input_props(required_text=True)[0],
                    "ref_audio": {
                        "type": "string",
                        "description": "参考音频：http(s) URL、data:audio/...;base64,... 或本地路径（必填）",
                    },
                    "prompt_audio": {"type": "string", "description": "同 ref_audio，二选一"},
                    "ref_text": {
                        "type": "string",
                        "description": "参考音频转写文本。x_vector_only_mode=false 时必填",
                    },
                    "prompt_text": {"type": "string", "description": "同 ref_text，二选一"},
                    "x_vector_only_mode": {
                        "type": "boolean",
                        "description": "仅用 embedding 时可不填 ref_text。默认 false",
                        "default": False,
                    },
                    "language": {
                        "type": "string",
                        "description": "语言：Auto/Chinese/English/Russian 等。默认 Auto",
                        "default": "Auto",
                    },
                },
                "required": ["text"],
            },
        },
    }
