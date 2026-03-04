# MCP Client 调用指南

---

## 1. 服务端点与协议

### 1.1 Base URL

以下以本机为例：
- Base：`http://127.0.0.1:6006`

### 1.2 HTTP 端点

- **GET** `/health`：健康检查
- **POST** `/message`：JSON-RPC 2.0 请求入口（Streamable HTTP）
- **GET** `/message`：SSE 流（持续接收 `notifications/message`）

### 1.3 鉴权（可选）

如果服务端设置了环境变量 `MCP_BEARER_TOKEN`，则所有 `/message` 请求需要：
- Header：`Authorization: Bearer <token>`

---

## 2. JSON-RPC 基础

请求体统一为：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
```

响应为：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": { "...": "..." }
}
```

错误响应为：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": { "code": -32601, "message": "..." }
}
```

---

## 3. tools/list

### 3.1 请求

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### 3.2 响应要点

工具声明在：
- `result.tools`（数组）

工具名（`name`）即用于 `tools/call` 的 `params.name`。

---

## 4. tools/call（通用）

### 4.1 请求格式

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "工具名",
    "arguments": { "参数": "..." }
  }
}
```

### 4.2 响应格式（两类）

#### A) 大多数工具：返回 `result.content[]`

在本实现里，除 `asr_stream`、`tts_stream_voxtream`、`tts_stream_cosyvoice`、`tts_stream_qwen3` 外，工具结果放在：
- `result.content`（数组）

其中：
- `type="audio"`：`data` 为 base64 音频
- `type="video"`：`data` 为 base64 视频
- `type="text"`：`text` 为 **JSON 字符串**（需要二次 `json.loads`）

#### B) long-running 工具：直接返回 `result.session_id`

`asr_stream`、`tts_stream_voxtream`、`tts_stream_cosyvoice`、`tts_stream_qwen3` 是 long-running 工具，本次 `tools/call` **立刻结束**，仅返回句柄：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": { "session_id": "asr-abc123" }
}
```

后续过程/结果通过 SSE 推送（见第 6 节）。

---

## 5. 工具列表与返回解析

### 5.1 TTS（8 个）

- `tts_generate_base`：Base 音色克隆，**必填** `text`、`ref_audio`（http(s) URL 或 data: base64）
- `tts_generate_base_06b`：Base 0.6B，同上
- `tts_generate_customvoice`：预设音色，必填 `text`，可选 `voice`、`instructions`（1.7B 支持）
- `tts_generate_customvoice_06b`：CustomVoice 0.6B，不支持 `instructions`
- `tts_generate_voicedesign`：音色设计，**必填** `text`、`instructions`（音色描述，最多 500 字符）
- `tts_stream_voxtream`：VoXtream 流式 TTS（long-running），**仅支持英文** `prompt_text`，**必填** `text`、`prompt_audio`、`prompt_text`；可选 `full_stream`。详见第 7 节
- `tts_stream_cosyvoice`：CosyVoice 流式 TTS（long-running），**支持中文**及 9 语言 18+ 方言，**必填** `text`、`prompt_audio`、`prompt_text`；可选 `full_stream`。详见第 8 节
- `tts_stream_qwen3`：Qwen3 streaming 流式 TTS（long-running），基于 dffdeeq/Qwen3-TTS-streaming。**必填** `text`、`ref_audio`；`x_vector_only_mode=false` 时必填 `ref_text`。详见第 9 节

上述 5 个一次性 TTS 成功时返回：
- `result.content[0].type == "audio"`
- `result.content[0].data`：base64 音频
- `result.content[0].mimeType`：例如 `audio/wav`

客户端处理：
1. base64 解码
2. 按需落盘或直接播放

### 5.2 Video（3 个）

- `video_generate`：返回 `text` content，`text` 是 JSON 字符串（常含 `task_id`）
- `video_status`：返回 `text` content，`text` 是 JSON 字符串
- `video_download`：返回 `video` content（base64 mp4）

客户端处理 `video_generate/video_status`：
1. 取 `result.content[0].text`
2. `json.loads(text)` 得到真正的业务 JSON

---

## 6. ASR

### 6.1 为什么需要 `Mcp-Session-Id`

1. 先 GET `/message` 建立 SSE，服务端会返回（header + 首条事件）一个 `Mcp-Session-Id`（下文称 **connection_id**）
2. POST `/message` 调用 `asr_stream` 时，**必须在请求头带同一个 `Mcp-Session-Id`**
3. 服务端之后只向该 SSE 连接推送该会话的 partial/final/done

如果 **POST asr_stream 不带 `Mcp-Session-Id`**：服务端无法建立映射，ASR 推送不会投递到任何 `/message` SSE 连接。

### 6.2 建立 SSE 连接

```bash
curl -N http://127.0.0.1:6006/message
```

你会先收到两条 `notifications/message`（示意）：

```json
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"endpoint","uri":"/message"}}
```

```json
{"jsonrpc":"2.0","method":"notifications/message","params":{"type":"session","session_id":"<connection_id>"}} 
```

同时响应头也会带：
- `Mcp-Session-Id: <connection_id>`

### 6.3 启动 ASR（tools/call）

`lang`（可选）须传 ASR 支持的**完整语言名**，如 `Chinese`、`English`、`Japanese`，不要传代码（如 zh/en/ja）。

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <connection_id>" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"asr_stream",
      "arguments":{
        "audio_source":"<URL 或 base64 或 data:audio/...;base64,xxx>",
        "lang":"Chinese"
      }
    }
  }'
```

立刻返回：

```json
{"jsonrpc":"2.0","id":1,"result":{"session_id":"asr-abc123"}}
```

### 6.4 过程推送（SSE 消息）

中间结果：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "type": "asr.partial",
    "session_id": "asr-abc123",
    "text": "你好"
  }
}
```

最终结果：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "type": "asr.final",
    "session_id": "asr-abc123",
    "text": "你好世界"
  }
}
```

可选完成事件：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "type": "asr.done",
    "session_id": "asr-abc123"
  }
}
```

### 6.5 失败语义

发生错误时仍会收到 `asr.final` / `asr.done`，并在 `params.error` 携带错误信息，例如：
- `ffmpeg decode failed: ...`

---

## 7. VoXtream 流式 TTS（tts_stream_voxtream）

### 7.1 流程概览

与 ASR 相同：需先 GET `/message` 建立 SSE，拿到 `Mcp-Session-Id`；POST 调用 `tts_stream_voxtream` 时在请求头带上该 Session-Id；服务端通过 SSE 推送 `tts.audio_chunk`（含 `audio_base64`、`sample_rate`）、`tts.done`。

### 7.2 参数

- `text`（必填）：要合成的文本
- `prompt_audio`（必填）：参考音频，http(s) URL 或 `data:audio/...;base64,...`，约 3–5 秒
- `prompt_text`（必填）：参考音频的转写文本，最多 250 字符
- `ref_audio` / `ref_text`：与 `prompt_audio` / `prompt_text` 等价
- `full_stream`（可选）：是否启用 full-stream，默认 true

### 7.3 请求示例

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <connection_id>" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"tts_stream_voxtream",
      "arguments":{
        "text":"你好，这是一次测试。",
        "prompt_audio":"<URL 或 data:...;base64,...>",
        "prompt_text":"参考音频的转写文本"
      }
    }
  }'
```

返回 `{"result":{"session_id":"tts-voxtream-xxx"}}`。

### 7.4 SSE 推送

音频块（可边收边播）：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "type": "tts.audio_chunk",
    "session_id": "tts-voxtream-xxx",
    "audio_base64": "<base64 编码的 WAV 块>",
    "sample_rate": 24000
  }
}
```

结束：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/message",
  "params": {
    "type": "tts.done",
    "session_id": "tts-voxtream-xxx"
  }
}
```

失败时 `tts.done` 会带 `params.error`。

---

## 8. CosyVoice 流式 TTS（tts_stream_cosyvoice）

### 8.1 流程概览

与 VoXtream 相同：需先 GET `/message` 建立 SSE，拿到 `Mcp-Session-Id`；POST 调用 `tts_stream_cosyvoice` 时在请求头带上该 Session-Id；服务端通过 SSE 推送 `tts.audio_chunk`（含 `audio_base64`、`sample_rate`）、`tts.done`。

### 8.2 参数

- `text`（必填）：要合成的文本
- `prompt_audio`（必填）：参考音频（零样本音色克隆），http(s) URL 或 `data:audio/wav;base64,...`，建议 3–5 秒 WAV
- `prompt_text`（必填）：参考音频的转写内容，须与参考音频逐字一致，**支持中文**；服务端会自动添加 CosyVoice 所需前缀
- `ref_audio` / `ref_text`：与 `prompt_audio` / `prompt_text` 等价
- `full_stream`（可选）：是否流式生成，默认 true

### 8.3 与 VoXtream 的区别

| 项目 | VoXtream | CosyVoice |
|------|----------|-----------|
| `prompt_text` | 仅支持英文 | 支持中文及多语言 |
| 参考音频 | 约 3–5 秒 | 建议 3–5 秒 WAV |

### 8.4 请求示例

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <connection_id>" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"tts_stream_cosyvoice",
      "arguments":{
        "text":"你好，这是一次 CosyVoice 测试。",
        "prompt_audio":"<URL 或 data:audio/wav;base64,...>",
        "prompt_text":"参考音频的转写内容（支持中文）"
      }
    }
  }'
```

返回 `{"result":{"session_id":"tts-cosyvoice-xxx"}}`。

### 8.5 SSE 推送

格式与 VoXtream 相同：`tts.audio_chunk`（含 `audio_base64`、`sample_rate`）、`tts.done`。失败时 `tts.done` 会带 `params.error`。

---

## 9. Qwen3 streaming 流式 TTS（tts_stream_qwen3）

### 9.1 流程概览

与 VoXtream/CosyVoice 相同：需先 GET `/message` 建立 SSE，拿到 `Mcp-Session-Id`；POST 调用 `tts_stream_qwen3` 时在请求头带上该 Session-Id；服务端通过 SSE 推送 `tts.audio_chunk`（含 `audio_base64`、`sample_rate`）、`tts.done`。后端为 Qwen3_streaming_service（默认 8012）。

### 9.2 参数

- `text`（必填）：要合成的文本
- `ref_audio`（必填）：参考音频，http(s) URL、本地路径或 `data:audio/...;base64,...`
- `ref_text`（条件必填）：参考音频转写文本。`x_vector_only_mode=false` 时必填；`x_vector_only_mode=true` 时可省略
- `prompt_audio` / `prompt_text`：与 `ref_audio` / `ref_text` 等价
- `x_vector_only_mode`（可选）：仅用 embedding 时可不填 ref_text，默认 false
- `language`（可选）：`Auto` / `Chinese` / `English` / `Russian` 等，默认 Auto

### 9.3 请求示例

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <connection_id>" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"tts_stream_qwen3",
      "arguments":{
        "text":"你好世界",
        "ref_audio":"<URL 或 data:audio/...;base64,...>",
        "ref_text":"参考音频的转写文本",
        "language":"Chinese"
      }
    }
  }'
```

返回 `{"result":{"session_id":"tts-qwen3-xxx"}}`。

### 9.4 SSE 推送

格式与 VoXtream/CosyVoice 相同：`tts.audio_chunk`（含 `audio_base64`、`sample_rate` 24000）、`tts.done`。失败时 `tts.done` 会带 `params.error`。

---