# 调用指南（6006 MCP + 6008 Gateway）


## 0. 公网基址

- **MCP** → `https://u662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443`
- **Gateway** → `https://uu662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443`

说明：
- Gateway 的 `/health` 会返回 `{"service":"gateway" ...}`；MCP 的 `/health` 返回 `{"service":"mcp-server"}`。


## 1. 6006（MCP）：JSON-RPC over HTTP

### 1.1 健康检查

- **GET** `/health`

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/health"
```

### 1.2 JSON-RPC 入口

- **POST** `/mcp`
- Header：`Content-Type: application/json`
- JSON-RPC 字段：`jsonrpc: "2.0"`, `id`, `method`, `params`

#### initialize

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

#### tools/list

```bash
curl -sS "https://u662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

当前实际工具：

- **TTS 非流式**：`tts_generate_base`、`tts_generate_customvoice`、`tts_generate_voicedesign`、`tts_generate_base_06b`、`tts_generate_customvoice_06b`
- **TTS 流式（long-running）**：`tts_stream_voxtream`、`tts_stream_cosyvoice`、`tts_stream_qwen3`
- **ASR 流式（long-running）**：`asr_stream`
- **视频**：`video_generate`、`video_status`、`video_download`

### 1.2.1 Streamable HTTP 与 mcpServers 配置（type: "streamable-http"）

MCP 服务支持 **Streamable HTTP**，可用于 Cursor 等客户端的 `mcpServers` 配置：

- **type**：`"streamable-http"`
- **url**：服务基址 + 路径。例如 `https://your-host:6006/message` 或 `https://your-host:6006/mcp`（二者等价，推荐 `/message`）。
- **headers**：客户端会在每次请求中携带，服务端会接收并可选校验：
  - `Content-Type: application/json`
  - `Authorization: Bearer <token>`（若服务端设置了环境变量 `MCP_BEARER_TOKEN`，则必须携带且一致，否则 401）

配置示例：

```json
{
  "mcpServers": {
    "ai-tools": {
      "url": "https://your-host:6006/message",
      "type": "streamable-http",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer Your Token"
      }
    }
  }
}
```

- **POST /message**：与 POST /mcp 相同，请求体为 JSON-RPC，响应为 200 + JSON。
- **GET /message**：建立 SSE 流，返回 `Mcp-Session-Id` 及 endpoint/session 事件（供需要 GET 的客户端）。未设置 `MCP_BEARER_TOKEN` 时无需 Authorization。

#### tools/call（通用格式）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "工具名",
    "arguments": { "工具参数": "..." }
  }
}
```

**重要：** MCP 的 `tools/call` 返回格式因工具类型而异：

- **普通工具**（TTS 非流式、视频等）：业务结果在 `result.content[0].text`，为 JSON 字符串，需再解析
- **long-running 工具**（流式 TTS、ASR）：直接返回 `result: {session_id: "..."}`，后续通过 `notifications/message` 推送事件

---

### 1.3 工具：TTS（非流式，返回 base64 音频）

MCP 将请求转发到本机 TTS 后端（8001 Base / 8002 CustomVoice / 8003 VoiceDesign / 8006 Base-0.6B / 8007 CustomVoice-0.6B）`/v1/audio/speech`，并把返回的音频二进制做 base64 封装，放在 `result.content[0].text` 的 JSON 中（含 `audio_base64` 等）。

#### 1.3.1 `tts_generate_base`（基础模型，3 秒快速音色克隆）

- 支持从用户提供的音频输入中实现约 3 秒快速音色克隆。支持语言：中文、英文、日文、韩文、德文、法文、俄文、葡萄牙文、西班牙文、意大利文。
- **text** / **input**：必填其一，要转换的文本
- **ref_audio**：可选，参考音频（URL 或 base64/data-url）
- **ref_text**：可选，参考音频转写
- **response_format**：`wav` / `mp3` / `flac` / `pcm` / `aac` / `opus`（默认 `wav`）
- **speed**：默认 `1.0`
- **x_vector_only_mode**、**max_new_tokens**：可选

#### 1.3.2 `tts_generate_customvoice`（预设音色）

- 通过用户指令对目标音色进行风格控制；支持 9 种优质音色，涵盖性别、年龄、语言和方言的多种组合。支持语言同上。
- **text** / **input**：必填其一
- **voice**：说话人，默认 `Vivian`；可选：`Vivian`、`Serena`、`Uncle_Fu`、`Dylan`、`Eric`、`Ryan`、`Aiden`、`Ono_Anna`、`Sohee`
- **language**：`Auto` / `Chinese` / `English` / `Japanese` / `Korean` 等（可选）
- **response_format**、**speed**：同上

#### 1.3.3 `tts_generate_voicedesign`（根据描述进行音色设计）

- 根据用户提供的描述进行音色设计。支持语言同上。
- **text** / **input**：必填其一
- **instructions**：音色/风格描述（可选，建议提供）
- **language**、**response_format**、**speed**：同上

#### 1.3.4 `tts_generate_base_06b`（Base 0.6B 轻量模型）

- 音色克隆，约 3 秒参考音频即可。转发到 8006。
- **text** / **input**：必填
- **ref_audio**：必填（URL 或 base64 data URL）
- **ref_text**、**response_format**、**speed**：可选

#### 1.3.5 `tts_generate_customvoice_06b`（CustomVoice 0.6B 轻量模型）

- 9 种优质音色（Vivian、Serena、Ryan 等）。转发到 8007。0.6B 不支持 instructions。
- **text** / **input**：必填
- **voice**、**language**、**response_format**、**speed**：可选

#### 示例：调用 `tts_generate_customvoice` 并落盘 wav

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":10,
    "method":"tools/call",
    "params":{
      "name":"tts_generate_customvoice",
      "arguments":{
        "text":"你好，这是一次公网调用测试。",
        "voice":"Vivian",
        "language":"Chinese",
        "response_format":"wav",
        "speed":1.0
      }
    }
  }' \
| python3 - <<'PY'
import sys, json, base64
d = json.load(sys.stdin)
txt = d["result"]["content"][0]["text"]
obj = json.loads(txt)
if "error" in obj:
    raise SystemExit(obj)
audio = base64.b64decode(obj["audio_base64"])
open("out.wav","wb").write(audio)
print("wrote out.wav bytes=", len(audio))
PY
```

---

### 1.3.6 工具：流式 TTS（long-running，通过 notifications 推送）

以下工具为 **long-running**：`tools/call` 立刻返回 `session_id`，合成过程中通过 `notifications/message` 推送 `tts.audio_chunk`（含 `audio_base64`、`sample_rate`），最后推送 `tts.done`。客户端需订阅 notifications 才能边收边播。

- **`tts_stream_voxtream`**：VoXtream 流式，支持英文。必填 text、prompt_audio、prompt_text。
- **`tts_stream_cosyvoice`**：CosyVoice 流式，支持中文、多语言。必填 text、prompt_audio、prompt_text。
- **`tts_stream_qwen3`**：Qwen3 streaming（dffdeeq  fork）。必填 text、ref_audio；`x_vector_only_mode=false` 时必填 ref_text。

后端分别对应：VoXtream（8010）、CosyVoice（8011）、Qwen3_streaming（8012）。

#### 示例：调用 `tts_stream_qwen3`（返回 session_id）

```bash
curl -sS "https://u662216-jqwt-e7cb3b9f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":11,
    "method":"tools/call",
    "params":{
      "name":"tts_stream_qwen3",
      "arguments":{
        "text":"你好世界",
        "ref_audio":"https://example.com/ref.wav",
        "ref_text":"参考音频转写文本",
        "language":"Chinese"
      }
    }
  }'
```

响应中含 `session_id`；客户端需通过 SSE/notifications 接收 `tts.audio_chunk` 与 `tts.done`。

---

### 1.3.7 工具：`asr_stream`（流式 ASR，long-running）

- 流式语音识别，立刻返回 `session_id`，识别过程中通过 `notifications/message` 推送 `asr.partial`、`asr.final` 等。
- 必填参数见工具 schema；后端为 ASR 服务（默认 8005）。

---

### 1.4 工具：`video_generate`（提交视频任务，T2V / I2V）

转发到本机 Wan 服务（Wan2.2-TI2V-5B）：`POST http://127.0.0.1:8004/v1/video/generate`。不传 `image` 为纯文本生视频（T2V），传 `image` 为图文生视频（I2V）。

#### 参数（arguments）

- **prompt**：`string`（必填）
- **negative_prompt**：`string`（可选）
- **width**：`integer`（默认 480）
- **height**：`integer`（默认 480）
- **num_frames**：`integer`（默认 24）
- **fps**：`integer`（默认 24）
- **seed**：`integer`（可选）
- **image**：`string`（可选，I2V 首帧/参考图。支持：图片 URL、`data:image/xxx;base64,xxx`、或纯 base64。不传则 T2V）

#### 示例

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/mcp" \
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

响应（解析 `result.content[0].text` 后）包含 `task_id`。

---

### 1.5 工具：`video_status`（查询视频任务状态）

转发到本机 Wan 服务：`GET http://127.0.0.1:8004/v1/video/status/{task_id}`。

#### 参数（arguments）

- **task_id**：`string`（必填）

#### 示例

先用上一节 `video_generate` 返回的 `task_id`，把它**原样填入**下面 JSON 的 `task_id` 字段：

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":21,
    "method":"tools/call",
    "params":{
      "name":"video_status",
      "arguments":{
        "task_id":"把上一响应中的 task_id 粘贴到这里"
      }
    }
  }'
```

（此处 `task_id` 必然是动态值，需从上一步响应中复制。）

---

### 1.6 工具：`video_download`（下载已完成视频，返回 base64）

转发到本机 Wan 服务：`GET http://127.0.0.1:8004/v1/video/download/{task_id}`，将响应体做 base64 封装返回。仅当任务状态为 `completed` 时才能成功下载。

#### 参数（arguments）

- **task_id**：`string`（必填）

#### 成功响应（解析 `result.content[0].text` 后）

- **video_base64**：`string`，视频文件（mp4）的 base64 编码
- **content_type**：`string`，如 `video/mp4`
- **bytes**：`integer`，原始字节数
- **task_id**：`string`

失败时返回 `{"error": "..."}` 等。客户端解码 `video_base64` 即可得到 mp4 二进制。

#### 示例

```bash
curl -sS "https://u662216-t87v-3d64fe3f.westd.seetacloud.com:8443/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":22,
    "method":"tools/call",
    "params":{
      "name":"video_download",
      "arguments":{"task_id":"把已完成任务的 task_id 粘贴到这里"}
    }
  }'
```

---

## 2. 6008（Gateway）：HTTP 反向代理

### 2.1 健康检查

- **GET** `/health`

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/health"
```

### 2.2 端口代理（按端口转发）

- **Path**：`/proxy/{port}/{forward_path}`
- `port` 白名单：`8000, 8001, 8002, 8003, 8004`

示例：访问 Wan 健康检查（等价于直连 `8004/health`）：

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/proxy/8004/health"
```

---

## 3. Embedding（8000，经 Gateway 调用）

### 3.1 可用路径

Embedding 服务由 `vllm serve ... --port 8000` 提供：

- **GET** `/embedding/health`
- **GET** `/embedding/v1/models` （列出已加载模型）
- **POST** `/embedding/v1/embeddings` （生成 embedding）
- **GET** `/embedding/openapi.json` （OpenAPI）
- **GET** `/embedding/docs` （Swagger UI）

### 3.2 生成 embedding（最小请求体）

#### 请求

- **POST** `https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/embedding/v1/embeddings`
- Header：`Content-Type: application/json`
- Body（最小字段）：
  - **model**：`"Qwen3-Embedding-8B"`
  - **input**：`string` 或 `string[]`

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/embedding/v1/embeddings" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-Embedding-8B","input":"hello"}'
```

返回是 OpenAI 兼容的 embedding 响应（包含 `data[0].embedding` 浮点数组）。

---

## 4. TTS（8001/8002/8003，经 Gateway 调用）

TTS 后端为 vllm-omni，接口为 OpenAI 兼容的：

- **POST** `/v1/audio/speech`

Gateway 提供三条固定前缀路由（会去掉前缀再转发到对应端口）：

- **Base（8001）**：`/tts/Base/v1/audio/speech`
- **CustomVoice（8002）**：`/tts/CustomVoice/v1/audio/speech`
- **VoiceDesign（8003）**：`/tts/VoiceDesign/v1/audio/speech`

### 4.1 Gateway 的 task_type 自动补全（实际实现）

对以上三条路由：
- 当请求为 **POST** 且路径为 **`/v1/audio/speech`**
- 且 `Content-Type: application/json`
- 且请求体 JSON **没有 `task_type` 字段**

Gateway 会自动补上：
- Base → `task_type="Base"`
- CustomVoice → `task_type="CustomVoice"`
- VoiceDesign → `task_type="VoiceDesign"`

### 4.2 `/v1/audio/speech` 请求体字段（来自 vLLM-Omni 文档 + 本地 OpenAPI）

本地 OpenAPI（8001/8002/8003 的 `/openapi.json`）显示 **必填字段只有 `input`**，其余均为可选字段：

- **input**：`string`（必填）
- **voice**：`string`（CustomVoice 常用；服务端默认 `Vivian`）
- **response_format**：`wav` / `pcm` / `flac` / `mp3` / `aac` / `opus`
- **speed**：`number`
- **language**：`Auto` / `Chinese` / `English` / `Japanese` / `Korean`
- **instructions**：`string`（风格/情绪指令；**VoiceDesign 强烈建议提供**，用于“用自然语言描述声音风格”）
- **task_type**：`CustomVoice` / `VoiceDesign` / `Base`
- **ref_audio**：**Base 必选**：参考音频（URL/base64/本地路径）；缺失会报错：`Base task requires 'ref_audio' for voice cloning`
- **ref_text**：Base 可选：参考音频转写；**仅 Base 允许**，非 Base 传入会报错：`'ref_text' is only valid for Base task`
- **x_vector_only_mode**：Base 可选
- **max_new_tokens**：可选

参考：`https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen3_tts/`

### 4.3 示例：CustomVoice（最小体）输出到 wav

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/tts/CustomVoice/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"input":"你好，这是一次公网调用测试。","response_format":"wav"}' \
  -o customvoice.wav
```

### 4.4 Base / CustomVoice / VoiceDesign 说明

- **Base**：基础模型，支持约 3 秒快速音色克隆；需把参考音频 URL 或 base64/data-url 填到 `ref_audio`，本地文件需先转成 base64/data-url。
- **CustomVoice**：通过指令对目标音色做风格控制，支持 9 种优质音色（如 Vivian、Serena 等），涵盖性别、年龄、语言和方言。
- **VoiceDesign**：根据用户描述进行音色设计；除 `input` 外建议提供 `instructions` 描述声音风格。

---

## 5. Wan（8004，经 Gateway 调用）

Wan 服务后端（8004）为 **Wan2.2-TI2V-5B**（`wan_server.py`），支持**文本生视频（T2V）**与**图文生视频（I2V）**。实际路径：

- **GET** `/wan/health`
- **POST** `/wan/v1/video/generate`
- **GET** `/wan/v1/video/status/{task_id}`
- **GET** `/wan/v1/video/download/{task_id}`

### 5.1 提交任务

请求体字段：**prompt**（必填）、**negative_prompt**（可选）、**width** / **height**（默认 480）、**num_frames**（默认 24）、**fps**（默认 24）、**seed**（可选）、**image**（可选，I2V 用。支持图片 URL、`data:image/xxx;base64,xxx` 或纯 base64）。不传 `image` 为 T2V，传则为 I2V。

**T2V 示例：**

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/wan/v1/video/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"smoke test","width":480,"height":480,"num_frames":24,"fps":24}'
```

**I2V**：在 body 中增加 `"image":"<URL 或 data URL 或 base64>"` 即可。

返回包含 `task_id`。

### 5.2 查询状态

把上一步返回的 `task_id` **原样填入 URL**：

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/wan/v1/video/status/把上一响应中的task_id粘贴到这里"
```

### 5.3 下载视频

```bash
curl -sS "https://uu662216-t87v-3d64fe3f.westd.seetacloud.com:8443/wan/v1/video/download/把上一响应中的task_id粘贴到这里" -o out.mp4
```

