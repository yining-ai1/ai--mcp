#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LLM HTTP Client (OpenAI-compatible Chat Completions)."""

from __future__ import annotations

import json

import httpx

from chat_agent import config


def chat_completion(
    *,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
) -> dict:
    """
    调用 OpenAI 兼容的 /v1/chat/completions。

    返回响应 JSON（dict）。若请求失败，返回 {"error": "...", "detail": "..."}。
    """
    api_key = config.get_openai_api_key()
    if not api_key:
        return {"error": "Missing OPENAI_API_KEY env var"}

    url = f"{config.LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body: dict = {
        "model": config.LLM_MODEL_NAME,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    if tools:
        body["tools"] = tools

    try:
        with httpx.Client(timeout=config.CHAT_LLM_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json=body)
        if resp.status_code < 200 or resp.status_code >= 300:
            return {
                "error": "LLM request failed",
                "status_code": resp.status_code,
                "detail": resp.text[:2000],
            }
        return resp.json()
    except Exception as e:
        return {"error": "LLM request exception", "detail": str(e), "url": url}

