# MCP Server（ai-services/mcp_server）

本目录实现一个 **MCP（Model Context Protocol）工具服务**，通过 **JSON-RPC 2.0 over HTTP** 对外提供工具（Tools），并支持 **Streamable HTTP（`/message`）+ SSE 推送**用于 long‑running 工具的过程消息（如 ASR 流式识别）。

---

## 服务能力概览

- **传输协议**
  - **POST** `/message`：Streamable HTTP（推荐）
  - **GET** `/message`：SSE（Server‑Sent Events）消息流，用于接收 `notifications/message`
- **鉴权**
  - 可选 Bearer Token：环境变量 `MCP_BEARER_TOKEN`
- **工具（tools）**
  - **TTS**：`tts_generate_base` / `tts_generate_base_06b` / `tts_generate_customvoice` / `tts_generate_customvoice_06b` / `tts_generate_voicedesign`
  - **Video（Wan）**：`video_generate` / `video_status` / `video_download`
  - **ASR（Long‑running + streaming messages）**：`asr_stream`

---

## 目录结构（关键文件）

- `main.py` / `__main__.py`：启动入口（HTTP / stdio）
- `transports/http.py`：FastAPI HTTP 服务（`/message`、SSE）
- `core/protocol.py`：JSON-RPC 分发（`initialize`、`tools/list`、`tools/call`）
- `core/registry.py`：工具 handler 注册表（`tool_name -> async handler`）
- `core/types.py`：把 handler 原始结果封装为 MCP `content[]`（`audio`/`video`/`text`）
- `tools/*.py`：tools 声明（name/description/inputSchema）
- `handlers/*.py`：tools 的后端调用逻辑
- `pipelines/asr_pipeline.py`：ASR long‑running 后台任务与消息推送

---

## 环境与依赖

### Python 依赖（运行 MCP Server）

至少需要：
- `fastapi`
- `uvicorn`
- `aiohttp`

可选：
- `python-dotenv`（用于加载 `.env`）

### 系统依赖（ASR）

`asr_stream` 需要：
- **ffmpeg**（用于把任意音频解码为 16kHz mono float32 PCM）
- **ASR 后端服务**：`asr_service`（默认 `127.0.0.1:8005`，见下文配置）

---

## 配置（环境变量）

### `.env` 加载规则

启动 `python -m mcp_server` 时会尝试加载两份 `.env`：
1. **当前工作目录**下的 `.env`
2. **本包目录**下的 `.env`（`mcp_server/.env`）

因此把 MCP 相关配置写在 `mcp_server/.env` 即可，不依赖从哪个目录启动。

### 关键环境变量

- `MCP_BEARER_TOKEN`：若设置，则 `POST/GET /message` 需要请求头 `Authorization: Bearer <token>`
- `ASR_HOST`：ASR 后端地址（默认 `127.0.0.1:8005`）

---

## 启动方式

### 1）HTTP 模式（推荐）

在 `ai-services` 目录启动：

```bash
python -m mcp_server --mode http --port 6006
```

健康检查：

```bash
curl -sS http://127.0.0.1:6006/health
```

### 2）stdio 模式

```bash
python -m mcp_server --mode stdio
```

---

## 协议与端点

### JSON-RPC 2.0

所有工具调用通过 JSON-RPC：
- `initialize`
- `tools/list`
- `tools/call`

示例：列出工具

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Streamable HTTP（Claude 等客户端）

客户端可配置为：
- `type`: `"streamable-http"`
- `url`: `http://127.0.0.1:6006/message`
- `headers`：可选 `Authorization: Bearer ...`

示例：

```json
{
  "mcpServers": {
    "ai-tools": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:6006/message",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

---

## Tools 清单与用法

下面的 tools 名称与入参 schema 均来自 `mcp_server/tools/*.py`。

### 1）TTS：`tts_generate_base` / `tts_generate_base_06b`

- **作用**：从参考音频做音色克隆（Base）。**必填**：`text`、`ref_audio`（须为 http(s) URL 或 `data:...;base64,...`）。可选：`ref_text`、`x_vector_only_mode`、`response_format`、`speed` 等。
- **返回**：MCP `content[]` 中为 `audio` 类型（base64）

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":10,
    "method":"tools/call",
    "params":{
      "name":"tts_generate_base",
      "arguments":{
        "text":"你好，这是一次 TTS 测试。",
        "ref_audio":"https://example.com/ref.wav",
        "response_format":"wav",
        "speed":1.0
      }
    }
  }'
```

> 注意：TTS 工具成功时返回形如 `result.content[0] = {"type":"audio","mimeType":"audio/wav","data":"<base64>"}`。

### 2）TTS：`tts_generate_customvoice` / `tts_generate_customvoice_06b`

- **作用**：预设音色 TTS（默认 `Vivian`）。1.7B 支持 `instructions` 风格控制；0.6B 不支持 `instructions`。
- **返回**：`audio` content

### 3）TTS：`tts_generate_voicedesign`

- **作用**：根据自然语言描述设计音色。**必填**：`text`、`instructions`（音色描述，最多 500 字符）。
- **返回**：`audio` content

---

### 4）Video：`video_generate`

- **作用**：提交视频生成任务（T2V；若传 `image` 则 I2V）
- **返回**：MCP `content[]` 中为 `text` 类型；`result.content[0].text` 是一个 **JSON 字符串**（需要再 `json.loads` 一次），通常包含 `task_id`

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":20,
    "method":"tools/call",
    "params":{
      "name":"video_generate",
      "arguments":{
        "prompt":"a cat running on the grass",
        "width":480,
        "height":480,
        "num_frames":24,
        "fps":24
      }
    }
  }'
```

### 5）Video：`video_status`

- **作用**：查询任务状态
- **返回**：同上，`result.content[0].text` 为 JSON 字符串（需二次解析）

### 6）Video：`video_download`

- **作用**：下载已完成任务的视频
- **返回**：MCP `content[]` 中为 `video` 类型（base64，通常 `video/mp4`）

---

## ASR：Long‑running tool + streaming messages（`asr_stream`）

`asr_stream` 按以下模型工作：

1. **tools/call 只做一件事：启动会话并立刻返回句柄**
2. ASR 后台任务继续运行
3. 识别过程中持续发送 **JSON-RPC `notifications/message`**（通过 `GET /message` 的 SSE 流）
4. 结束时发送 `asr.final`（可选再发 `asr.done`）

**Session 级路由**：多连接并发时，每条 GET 连接只会收到**自己发起的** asr_stream 的推送。做法：GET /message 建连后，响应头或首条事件中会给出 `Mcp-Session-Id`；**POST 调用 asr_stream 时请求头必须带相同的 `Mcp-Session-Id`**，服务端才会建立「asr_session_id → connection」映射，并把该 asr 的 partial/final/done 只投递给该 GET 连接。

### 1）先建立 SSE 连接（接收通知）

```bash
curl -N http://127.0.0.1:6006/message
```

服务会先发送两条可选的通知：
- `type=endpoint`
- `type=session`

### 2）启动 ASR 会话（tools/call）

若要做 session 路由，POST 时请带与 GET 相同的 `Mcp-Session-Id`（见上一步响应头或首条事件中的 `session_id`）：

```bash
curl -sS http://127.0.0.1:6006/message \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <与 GET 建连返回的 session_id 一致>" \
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
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "session_id": "asr-abc123"
  }
}
```

### 3）识别过程消息（SSE 内收到的 JSON）

中间结果（可能多条）：

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

### 4）失败语义（推荐客户端处理）

当音频不可解码、ASR 后端不可用等错误发生时，服务仍会发送 `asr.final`/`asr.done`，并在 `params.error` 中携带错误信息，避免客户端无限等待。

---

## 常见问题（Troubleshooting）

- **`ModuleNotFoundError: aiohttp`**
  - 说明当前 Python 环境未安装 `aiohttp`；请在运行 MCP 的同一解释器环境中安装依赖。
- **SSE 收到 `asr.final` 且 `error` 为 `ffmpeg decode failed`**
  - `audio_source` 不是有效音频（或 base64/data-url 不正确），或系统缺少 `ffmpeg`。
- **ASR 无响应**
  - 确认 `asr_service` 已启动且可访问：`curl -sS http://127.0.0.1:8005/health`
  - 如需修改端口/地址，设置 `ASR_HOST`

