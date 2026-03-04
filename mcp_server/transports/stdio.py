# -*- coding: utf-8 -*-
"""Stdio transport: read JSON-RPC lines from stdin, write responses to stdout."""

import asyncio
import json
import sys

from mcp_server.core.protocol import MCPServer


async def run_stdio() -> None:
    server = MCPServer()
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            request = json.loads(line.strip())
            response = await server.handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()
