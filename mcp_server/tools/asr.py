def get_asr_tools() -> dict:
    return {
        "asr_stream": {
            "name": "asr_stream",
            "description": "启动流式 ASR 会话（long-running tool）：tools/call 立刻返回 session_id；识别过程中会通过 notifications/message 持续推送 asr.partial/asr.final。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "audio_source": {
                        "type": "string",
                        "description": "音频来源：URL 或 base64（也支持 data-url: data:audio/...;base64,xxx）"
                    },
                    "lang": {
                        "type": "string",
                        "description": "语言（可选），传 asr 支持的完整语言名，如 Chinese、English、Japanese"
                    }
                },
                "required": ["audio_source"]
            }
        }
    }
