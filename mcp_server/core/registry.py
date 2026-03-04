# -*- coding: utf-8 -*-
"""Tool registry: name -> handler (async args, session -> raw result)."""

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

Handler = Callable[[dict, aiohttp.ClientSession], Awaitable[Any]]

TOOL_HANDLERS: dict[str, Handler] = {}


def register(name: str, handler: Handler) -> None:
    TOOL_HANDLERS[name] = handler


def get(name: str) -> Handler | None:
    return TOOL_HANDLERS.get(name)


def all_names() -> list[str]:
    return list(TOOL_HANDLERS.keys())
