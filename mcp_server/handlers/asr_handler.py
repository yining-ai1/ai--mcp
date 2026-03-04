import asyncio
import uuid

from mcp_server.config import ASR_SUPPORTED_LANGUAGES
from mcp_server.pipelines.asr_pipeline import run_asr_pipeline
from mcp_server.transports.message_bus import get_connection_id, register_session_owner


def _validate_asr_stream_args(args: dict) -> None:
    """在调用 asr 模型服务前校验参数，不合法则抛出 ValueError。"""
    if not args or not isinstance(args, dict):
        raise ValueError("arguments 不能为空")
    audio_source = args.get("audio_source")
    if audio_source is None:
        raise ValueError("缺少必填参数: audio_source")
    if not isinstance(audio_source, str) or not audio_source.strip():
        raise ValueError("audio_source 必须为非空字符串")
    lang = args.get("lang")
    if lang is not None and lang != "":
        s = (lang if isinstance(lang, str) else str(lang)).strip()
        if s and s not in ASR_SUPPORTED_LANGUAGES:
            raise ValueError(
                f"不支持的 lang: {lang!r}，支持: {sorted(ASR_SUPPORTED_LANGUAGES)}"
            )


async def call_asr_stream(args: dict, session):
    """
    Long-running tool entrypoint.
    - 立刻返回 session_id（本次 tools/call 到此结束）
    - 后台任务持续通过 message bus 推送 notifications/message（仅投递给本 connection）
    """
    _validate_asr_stream_args(args)
    session_id = f"asr-{uuid.uuid4().hex}"

    connection_id = get_connection_id()
    if connection_id:
        register_session_owner(session_id, connection_id)

    # 启动后台任务（不要 await）；注意：不能复用 protocol 里短生命周期的 aiohttp session
    asyncio.create_task(run_asr_pipeline(session_id, args))

    # 立刻返回
    return {
        "session_id": session_id,
    }
