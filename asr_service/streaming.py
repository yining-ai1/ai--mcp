# -*- coding: utf-8 -*-
"""流式 ASR 会话管理：创建会话、按块送入 PCM、结束会话并返回结果。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class _Session:
    state: Any
    last_seen: float


_SESSIONS: dict[str, _Session] = {}


def _gc_sessions(ttl_sec: float) -> None:
    now = time.time()
    dead = [sid for sid, s in _SESSIONS.items() if now - s.last_seen > ttl_sec]
    for sid in dead:
        _SESSIONS.pop(sid, None)


def create_session(
    asr: Any,
    *,
    language: str | None = None,
    chunk_size_sec: float,
    unfixed_chunk_num: int,
    unfixed_token_num: int,
    ttl_sec: float,
) -> str:
    """创建流式会话，返回 session_id。"""
    _gc_sessions(ttl_sec)
    state = asr.init_streaming_state(
        language=language or "",
        unfixed_chunk_num=unfixed_chunk_num,
        unfixed_token_num=unfixed_token_num,
        chunk_size_sec=chunk_size_sec,
    )
    session_id = uuid.uuid4().hex
    now = time.time()
    _SESSIONS[session_id] = _Session(state=state, last_seen=now)
    return session_id


def get_session(session_id: str, ttl_sec: float) -> _Session | None:
    """获取会话；若不存在或已过期返回 None。"""
    _gc_sessions(ttl_sec)
    s = _SESSIONS.get(session_id)
    if s is None:
        return None
    s.last_seen = time.time()
    return s


def chunk(
    asr: Any,
    session_id: str,
    pcm_float32: np.ndarray,
    ttl_sec: float,
) -> tuple[str, str]:
    """送入一段 PCM（16kHz float32），返回当前 (language, text)。若 session 无效抛出 ValueError。"""
    s = get_session(session_id, ttl_sec)
    if s is None:
        raise ValueError("invalid or expired session_id")
    asr.streaming_transcribe(pcm_float32, s.state)
    language = getattr(s.state, "language", "") or ""
    text = getattr(s.state, "text", "") or ""
    return language, text


def finish_session(asr: Any, session_id: str, ttl_sec: float) -> tuple[str, str]:
    """结束会话：flush 剩余缓冲，返回最终 (language, text)，并删除会话。若 session 无效抛出 ValueError。"""
    s = get_session(session_id, ttl_sec)
    if s is None:
        raise ValueError("invalid or expired session_id")
    asr.finish_streaming_transcribe(s.state)
    language = getattr(s.state, "language", "") or ""
    text = getattr(s.state, "text", "") or ""
    _SESSIONS.pop(session_id, None)
    return language, text
