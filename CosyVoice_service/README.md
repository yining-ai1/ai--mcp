# CosyVoice_service

基于 [Fun-CosyVoice3-0.5B](https://www.modelscope.cn/models/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) 的流式 TTS 服务，**支持中文**，提供 HTTP API（一次性 WAV 与 SSE 流式）。

## 启动

```bash
cd /root/autodl-tmp/ai-services
conda activate cosyvoice
python -m CosyVoice_service
```

默认监听 **8011**。健康检查：`curl http://127.0.0.1:8011/health`

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COSYVOICE_SERVICE_PORT` | `8011` | 服务端口 |
| `COSYVOICE_MODEL_DIR` | `~/autodl-tmp/models/Fun-CosyVoice3-0.5B` | 模型目录 |
| `COSYVOICE_MAX_TEXT_CHARS` | `1000` | 单次最大字符数 |

## API

- `POST /v1/audio/speech`：一次性返回 WAV
- `POST /v1/audio/speech/stream`：SSE 流式，每行 `data: {"audio_base64":"...","sample_rate":24000}`

请求体：`{"text":"...","prompt_audio":"URL或base64","prompt_text":"参考音频转写"}`，可选 `full_stream`。

## MCP 工具

工具名 `tts_stream_cosyvoice`，参数同 VoXtream，**支持中文 prompt_text**。
