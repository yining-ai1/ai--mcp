#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
6008 网关服务：把外部请求转发到内部服务（8000-8004 多路由）
"""

import argparse
import json
from typing import Dict, Iterable, Optional, Tuple

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _filter_request_headers(headers: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in headers:
        lk = k.lower()
        if lk in HOP_BY_HOP_HEADERS or lk in {"host", "content-length"}:
            continue
        out[k] = v
    return out


def _filter_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP_HEADERS:
            continue
        out[k] = v
    return out


ALLOWED_PORTS = {8000, 8001, 8002, 8003, 8004}


async def _proxy_request(
    *,
    session: aiohttp.ClientSession,
    request: Request,
    upstream_base: str,
    forward_path: str,
    body_override: bytes | None = None,
):
    upstream_base = upstream_base.rstrip("/")
    forward_path = forward_path.lstrip("/")
    target_url = f"{upstream_base}/{forward_path}" if forward_path else upstream_base

    method = request.method
    params = request.query_params
    body = body_override if body_override is not None else await request.body()
    req_headers = _filter_request_headers(request.headers.items())

    try:
        resp = await session.request(
            method,
            target_url,
            params=params,
            data=body if body else None,
            headers=req_headers,
        )

        resp_headers = _filter_response_headers(resp.headers)
        content_type: Optional[str] = resp.headers.get("content-type")

        async def _iter():
            try:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    yield chunk
            finally:
                resp.release()

        return StreamingResponse(
            _iter(),
            status_code=resp.status,
            headers=resp_headers,
            media_type=content_type,
        )
    except aiohttp.ClientError as e:
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "detail": str(e), "upstream": upstream_base},
        )


def create_app(upstream: str) -> FastAPI:
    async def _proxy_tts_with_task_type(
        *,
        upstream_port: int,
        task_type: str,
        forward_path: str,
        request: Request,
    ):
        """对 /v1/audio/speech 自动补全 task_type，避免默认值误用炸引擎。"""
        session: aiohttp.ClientSession = app.state.session

        body_override = None
        if request.method.upper() == "POST" and forward_path.lstrip("/") == "v1/audio/speech":
            ctype = (request.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                raw = await request.body()
                try:
                    obj = json.loads(raw.decode("utf-8"))
                    if isinstance(obj, dict) and "task_type" not in obj:
                        obj["task_type"] = task_type
                        body_override = json.dumps(obj).encode("utf-8")
                except Exception:
                    # 解析失败就不改写，按原样转发
                    body_override = None

        return await _proxy_request(
            session=session,
            request=request,
            upstream_base=f"http://127.0.0.1:{upstream_port}",
            forward_path=forward_path,
            body_override=body_override,
        )

    app = FastAPI(title="AI Gateway", version="1.0")
    upstream = upstream.rstrip("/")

    @app.on_event("startup")
    async def _startup():
        timeout = aiohttp.ClientTimeout(total=None)
        app.state.session = aiohttp.ClientSession(timeout=timeout)

    @app.on_event("shutdown")
    async def _shutdown():
        session: aiohttp.ClientSession = app.state.session
        await session.close()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "gateway",
            "default_upstream": upstream,
            "allowed_ports": sorted(ALLOWED_PORTS),
        }

    @app.api_route(
        "/proxy/{port}/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_by_port(port: int, forward_path: str, request: Request):
        session: aiohttp.ClientSession = app.state.session
        if port not in ALLOWED_PORTS:
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden port", "allowed_ports": sorted(ALLOWED_PORTS)},
            )
        upstream_base = f"http://127.0.0.1:{port}"
        return await _proxy_request(
            session=session,
            request=request,
            upstream_base=upstream_base,
            forward_path=forward_path,
        )

    @app.api_route(
        "/embedding/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_embedding(forward_path: str, request: Request):
        session: aiohttp.ClientSession = app.state.session
        return await _proxy_request(
            session=session,
            request=request,
            upstream_base="http://127.0.0.1:8000",
            forward_path=forward_path,
        )

    @app.api_route(
        "/tts/Base/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_tts_base(forward_path: str, request: Request):
        return await _proxy_tts_with_task_type(
            upstream_port=8001,
            task_type="Base",
            forward_path=forward_path,
            request=request,
        )

    @app.api_route(
        "/tts/CustomVoice/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_tts_customvoice(forward_path: str, request: Request):
        return await _proxy_tts_with_task_type(
            upstream_port=8002,
            task_type="CustomVoice",
            forward_path=forward_path,
            request=request,
        )

    @app.api_route(
        "/tts/VoiceDesign/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_tts_voicedesign(forward_path: str, request: Request):
        return await _proxy_tts_with_task_type(
            upstream_port=8003,
            task_type="VoiceDesign",
            forward_path=forward_path,
            request=request,
        )

    @app.api_route(
        "/wan/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_wan(forward_path: str, request: Request):
        session: aiohttp.ClientSession = app.state.session
        return await _proxy_request(
            session=session,
            request=request,
            upstream_base="http://127.0.0.1:8004",
            forward_path=forward_path,
        )

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy_default(full_path: str, request: Request):
        # /health 保留本地
        if full_path == "health":
            return await health()
        session: aiohttp.ClientSession = app.state.session
        return await _proxy_request(
            session=session,
            request=request,
            upstream_base=upstream,
            forward_path=full_path,
        )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6008)
    parser.add_argument("--upstream", type=str, default="http://127.0.0.1:8000")
    args = parser.parse_args()

    app = create_app(args.upstream)
    uvicorn.run(app, host="0.0.0.0", port=args.port)

