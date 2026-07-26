"""Thin async client for the Hermes API server (gateway/platforms/api_server.py).

Contract verified by reading the real handler code on the deployed VPS —
see Global Constraints in the implementation plan. No third-party SDK:
this is three small HTTP calls plus an SSE line parser.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional


class HermesClientError(Exception):
    """Raised when the Hermes API server returns a non-2xx status."""


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def create_session(http_session, base_url: str, api_key: str, session_id: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/sessions"
    async with http_session.post(url, json={"id": session_id}, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"create_session failed: {resp.status} {text}")
        return await resp.json()


async def stream_chat(
    http_session,
    base_url: str,
    api_key: str,
    hermes_session_id: str,
    message: str,
    system_message: Optional[str] = None,
) -> AsyncIterator[tuple[str, dict]]:
    url = f"{base_url.rstrip('/')}/api/sessions/{hermes_session_id}/chat/stream"
    body: dict[str, Any] = {"message": message}
    if system_message:
        body["system_message"] = system_message

    async with http_session.post(url, json=body, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"stream_chat failed: {resp.status} {text}")

        event_name: Optional[str] = None
        data_lines: list[str] = []
        async for raw_line in resp.content:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith(":"):
                continue
            if line == "":
                if event_name is not None:
                    payload = json.loads("\n".join(data_lines)) if data_lines else {}
                    yield event_name, payload
                event_name = None
                data_lines = []
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())


async def get_messages(http_session, base_url: str, api_key: str, hermes_session_id: str) -> list:
    url = f"{base_url.rstrip('/')}/api/sessions/{hermes_session_id}/messages"
    async with http_session.get(url, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"get_messages failed: {resp.status} {text}")
        data = await resp.json()
        return data["data"]
