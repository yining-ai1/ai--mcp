# 智能外呼技术方案——模型部署与 MCP 服务

**文档版本**：v0.1  
**负责人**：王文艺
**日期**：2025-03

---

## 1. 概述

### 1.1 职责范围

本方案覆盖智能外呼系统中由本人负责的两部分：

- **模型部署**：ASR（语音识别）、TTS（语音合成）等推理服务的部署与配置
- **MCP 服务**：基于 Model Context Protocol 的工具网关，为外呼 Agent 提供统一工具调用能力

### 1.2 与外呼系统的关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        外呼系统（其他方）                          │
│  电话接入 / 信令 / 媒体流 / 通话控制 / Agent 调度                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │ 工具调用（JSON-RPC）
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP 服务（本方案）                              │
│  tools/call → ASR / TTS / 其他工具                                 │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   模型部署（本方案）                                │
│  ASR 服务(8005) | TTS 服务(8001-8012) | 其他推理服务               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 模型部署方案

### 2.1 部署架构

| 服务 | 端口 | 模型/能力 | 用途说明 |
|------|------|-----------|----------|
| ASR | 8005 | Qwen3-ASR-1.7B | 实时语音转文字，支持流式 |
| TTS Base | 8001 | Qwen3-TTS Base | 音色克隆（约 3 秒参考音频） |
| TTS CustomVoice | 8002 | Qwen3-TTS CustomVoice | 预设音色（Vivian、Serena 等） |
| TTS VoiceDesign | 8003 | Qwen3-TTS VoiceDesign | 自然语言描述音色 |
| TTS Base 0.6B | 8006 | Base 轻量版 | 低延迟、省显存 |
| TTS CustomVoice 0.6B | 8007 | CustomVoice 轻量版 | 低延迟、省显存 |
| VoXtream 流式 | 8010 | VoXtream | 流式 TTS，**仅英文** |
| CosyVoice 流式 | 8011 | CosyVoice3-0.5B | 流式 TTS，**支持中文** |
| Qwen3 Streaming | 8012 | Qwen3-TTS-12Hz-1.7B-Base | 流式音色克隆 |

### 2.2 ASR 服务（核心）

**作用**：外呼场景中，将用户（被叫方）的语音实时转为文字，供 Agent 决策。

**技术要点**：

- 基于 `qwen_asr` / Qwen3-ASR-1.7B
- 流式 API：`/api/start` → `/api/chunk`（16kHz float32 PCM）→ `/api/finish`
- 支持 30+ 语言（Chinese、English、Japanese 等，需传完整语言名）
- 音频输入要求：ffmpeg 解码为 16kHz mono float32 PCM

**资源**：建议 1 张 GPU，显存约 4–6GB。

### 2.3 TTS 服务（核心）

**作用**：将 Agent 生成的文本转为语音播放给被叫方。

#### 2.3.1 非流式 TTS（8001/8002/8003/8006/8007）

- 一次性返回完整 WAV/MP3，适合预录制或首包延迟不敏感场景
- Base：3 秒参考音频即可音色克隆，适合「真人录音风格」外呼
- CustomVoice：9 种预设音色，适合标准话术
- VoiceDesign：用自然语言描述音色（如「温柔女声、语速稍慢」）

#### 2.3.2 流式 TTS（8010/8011/8012）

- 边合成边输出，降低首包延迟，适合实时对话
- **CosyVoice（8011）**：推荐用于中文外呼，支持零样本音色克隆
- **VoXtream（8010）**：仅英文，参考音频转写须为英文
- **Qwen3 Streaming（8012）**：支持中英文，需 ref_audio + ref_text

### 2.4 资源配置建议

| 场景 | ASR | TTS 非流式 | TTS 流式 | 建议 GPU |
|------|-----|------------|----------|----------|
| 低成本验证 | 8005 | 8006/8007 | - | 1× 16GB |
| 标准外呼 | 8005 | 8001/8002 | 8011 | 1× 24GB 或 2× 16GB |
| 高并发/多音色 | 8005 | 全量 | 8011+8012 | 2× 24GB+ |

---

## 3. MCP 服务方案

### 3.1 架构设计

MCP 服务作为**工具网关**，将外呼 Agent 的 tool call 转发到对应模型服务，并统一协议与错误处理。

```
                    Agent / 外呼调度
                           │
                           │ POST /message (JSON-RPC 2.0)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      MCP Server (6006)                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │
│  │ initialize  │  │ tools/list  │  │ tools/call              │   │
│  │ tools/list  │  │             │  │  → registry → handler   │   │
│  └─────────────┘  └─────────────┘  └───────────┬─────────────┘   │
│                                                  │                │
│  ┌──────────────────────────────────────────────┴──────────────┐ │
│  │ Handlers: tts_handler | asr_handler | video_handler | ...   │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                  │                │
│  ┌──────────────────────────────────────────────┴──────────────┐ │
│  │ Long-running: asr_stream, tts_stream_* → pipeline → SSE     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ASR(8005)    TTS(8001-8012)      Video(8004) [可选]
```

### 3.2 工具清单（外呼相关）

#### 3.2.1 必选工具

| 工具名 | 类型 | 说明 | 外呼用途 |
|--------|------|------|----------|
| `asr_stream` | long-running | 流式 ASR | 实时识别被叫方语音 |
| `tts_generate_base` | 同步 | 音色克隆 TTS | 用 3 秒录音克隆外呼坐席音色 |
| `tts_generate_customvoice` | 同步 | 预设音色 TTS | 标准话术播报 |
| `tts_stream_cosyvoice` | long-running | 流式中文 TTS | 实时对话、低延迟 |

#### 3.2.2 可选工具

| 工具名 | 说明 |
|--------|------|
| `tts_generate_voicedesign` | 自然语言描述音色 |
| `tts_generate_base_06b` / `tts_generate_customvoice_06b` | 轻量 TTS |
| `tts_stream_voxtream` | 英文流式 TTS |
| `tts_stream_qwen3` | Qwen3 流式音色克隆 |

### 3.3 接口协议

**Base URL**：`http://<host>:6006`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/message` | POST | JSON-RPC 2.0 入口 |
| `/message` | GET | SSE 流，接收 long-running 工具的推送 |

**鉴权**：可配置 `MCP_BEARER_TOKEN`，请求头需带 `Authorization: Bearer <token>`。

**JSON-RPC 示例**：

```bash
# 列出工具
curl -X POST http://host:6006/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# 调用 TTS（同步）
curl -X POST http://host:6006/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"tts_generate_customvoice",
      "arguments":{"text":"您好，请问是张先生吗？","voice":"Vivian","language":"Chinese"}
    }
  }'
```

### 3.4 Long-running 工具与 SSE（重点）

`asr_stream`、`tts_stream_cosyvoice` 等为 **long-running**，`tools/call` 立即返回 `session_id`，实际结果通过 SSE 推送。

**客户端流程**：

1. **GET** `/message` 建立 SSE 连接，获得 `Mcp-Session-Id`（响应头或首条 `type=session` 事件）
2. **POST** `tools/call` 时，请求头带 `Mcp-Session-Id: <与 GET 相同>`
3. 在 SSE 流中接收 `asr.partial` / `asr.final` / `tts.audio_chunk` / `tts.done` 等事件

**ASR 推送示例**：

```json
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"asr.partial","session_id":"asr-xxx","text":"你好"}}
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"asr.final","session_id":"asr-xxx","text":"你好，我是"}}
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"asr.done","session_id":"asr-xxx"}}
```

**TTS 流式推送示例**：

```json
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"tts.audio_chunk","session_id":"tts-cosyvoice-xxx","audio_base64":"...","sample_rate":22050}}
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"tts.done","session_id":"tts-cosyvoice-xxx"}}
```

### 3.5 返回格式

- **同步 TTS 成功**：`result.content[0] = { "type": "audio", "mimeType": "audio/wav", "data": "<base64>" }`
- **同步 TTS 错误**：`result.content[0] = { "type": "text", "text": "{\"error\":\"...\"}" }`
- **Long-running**：`result = { "session_id": "asr-xxx" }`，后续通过 SSE 推送

---

## 4. 与外呼系统集成要点

### 4.1 音频格式

- **ASR 输入**：支持 URL、base64、`data:audio/...;base64,...`；内部经 ffmpeg 转 16kHz float32 PCM
- **TTS 输出**：WAV base64，采样率 22050/24000（依模型而定）

### 4.2 实时链路建议

1. 外呼媒体网关将用户语音按 1 秒 chunk 送入 MCP `asr_stream`
2. MCP 将 PCM 转码后转发至 ASR 服务，通过 SSE 回传 partial/final 文本
3. Agent 根据识别结果决策，生成回复文本
4. 调用 `tts_stream_cosyvoice`，边合成边通过 SSE 获取 `tts.audio_chunk`，边播放

### 4.3 超时与错误

- ASR/TTS 超时建议：30–60 秒
- 错误时仍会收到 `asr.final` / `tts.done`，其中 `params.error` 携带错误信息，便于重试或降级

---

## 5. 环境依赖

| 组件 | 依赖 |
|------|------|
| MCP Server | Python 3.10+，fastapi、uvicorn、aiohttp |
| ASR Pipeline | ffmpeg、numpy、qwen_asr |
| TTS 各服务 | 见各服务 requirements.txt |

---