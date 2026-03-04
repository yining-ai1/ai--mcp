# -*- coding: utf-8 -*-
"""
Message bus with session-level routing.

- POST /message 调用 asr_stream 时带上 Mcp-Session-Id（与 GET /message 的会话一致），
  会注册 asr_session_id -> connection_id，后续 asr.partial/final/done 只投递给该 connection。
- GET /message 用 register_connection(connection_id, cb)；断开时 unregister_connection。
"""
from __future__ import annotations

import contextvars
from collections.abc import Callable

Subscriber = Callable[[dict], None]

# ---------- 无路由的广播（如 GET /sse） ----------
_subscribers: set[Subscriber] = set()


def subscribe(cb: Subscriber) -> None:
    _subscribers.add(cb)


def unsubscribe(cb: Subscriber) -> None:
    _subscribers.discard(cb)


# ---------- Session 级路由：connection_id <-> asr session_id ----------
_connection_callbacks: dict[str, Subscriber] = {}
_session_to_connection: dict[str, str] = {}

# POST 请求时设置，供 asr_handler 读取并注册 session 归属
_current_connection_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_connection_id", default=None
)


def set_connection_id(connection_id: str | None) -> None:
    _current_connection_id.set(connection_id)


def get_connection_id() -> str | None:
    return _current_connection_id.get(None)


def register_connection(connection_id: str, cb: Subscriber) -> None:
    """GET /message 建连时调用；断开时 unregister_connection。"""
    _connection_callbacks[connection_id] = cb


def unregister_connection(connection_id: str) -> None:
    """GET /message 断开时调用。"""
    _connection_callbacks.pop(connection_id, None)


def register_session_owner(session_id: str, connection_id: str) -> None:
    """asr_stream 启动时调用：该 asr session 属于该 connection，仅向该 connection 投递。"""
    _session_to_connection[session_id] = connection_id


def unregister_session_owner(session_id: str) -> None:
    """asr.done 后可选调用，避免映射无限增长。"""
    _session_to_connection.pop(session_id, None)


async def send(msg: dict) -> None:
    """
    - 若 msg.params.session_id 存在：仅投递给注册了该 session 归属的 connection。
    - 否则：投递给所有 _subscribers（兼容 GET /sse 等广播场景）。
    """
    params = msg.get("params") or {}
    session_id = params.get("session_id")

    if session_id:
        connection_id = _session_to_connection.get(session_id)
        cb = _connection_callbacks.get(connection_id) if connection_id else None
        if cb:
            try:
                cb(msg)
            except Exception:
                pass
        return

    for cb in list(_subscribers):
        try:
            cb(msg)
        except Exception:
            continue
