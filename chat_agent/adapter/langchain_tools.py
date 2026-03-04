#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP OpenAI-format tools -> LangChain tools thin adapter.

Each tool is a LangChain BaseTool that forwards execution to
mcp_adapter.execute_mcp_tool(mcp_base, name, arguments).
Used so ChatOpenAI.bind_tools() receives tools with correct name/description/parameters;
actual execution in the graph is still via tools_node -> execute_mcp_tool.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model

from chat_agent.adapter.mcp_adapter import execute_mcp_tool

logger = logging.getLogger(__name__)


def _schema_to_pydantic_model(name: str, parameters: dict) -> type:
    """Build a dynamic Pydantic model from OpenAI-style parameters (JSON schema)."""
    params = parameters if isinstance(parameters, dict) else {}
    props = params.get("properties") or {}
    required = set(params.get("required") or [])

    type_map = {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    fields: dict[str, Any] = {}
    for k, v in props.items():
        if not isinstance(v, dict):
            fields[k] = (Optional[str], None)
            continue
        t = type_map.get(v.get("type"), str)
        if k in required:
            fields[k] = (t, ...)
        else:
            fields[k] = (Optional[t], None)
    if not fields:
        fields["_placeholder"] = (Optional[str], None)
    return create_model(f"{name}_args", **fields)


def mcp_openai_tools_to_langchain_tools(mcp_base: str, openai_tools: list[dict]) -> list[BaseTool]:
    """
    Convert MCP OpenAI-format tools to LangChain BaseTool list.

    Each tool invokes execute_mcp_tool(mcp_base, name, arguments) when called.
    mcp_base is captured in closure.
    """
    result: list[BaseTool] = []
    for item in openai_tools or []:
        try:
            fn = item.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            description = fn.get("description") or ""
            parameters = fn.get("parameters") or {"type": "object", "properties": {}}

            try:
                args_schema = _schema_to_pydantic_model(name, parameters)
            except Exception as e:
                logger.warning(
                    "langchain_tools: skip schema for %s: %s; use minimal schema",
                    name, e, exc_info=False,
                )
                args_schema = create_model(f"{name}_args", _placeholder=(Optional[str], None))

            def _make_invoke(n: str, base: str):
                def _invoke(**kwargs: Any) -> str:
                    # 去掉 Pydantic 可能注入的 _placeholder 等
                    args = {k: v for k, v in kwargs.items() if not k.startswith("_") and v is not None}
                    out, _, _, _ = execute_mcp_tool(base, n, args)
                    return out
                return _invoke

            tool = StructuredTool.from_function(
                name=name,
                description=description,
                func=_make_invoke(name, mcp_base),
                args_schema=args_schema,
            )
            result.append(tool)
        except Exception as e:
            logger.warning("langchain_tools: skip tool %s: %s", item.get("function", {}).get("name"), e, exc_info=False)
            continue
    return result
