"""wormsoft.ru embeddings client — single supported model, explicit error taxonomy.

Implements the error matrix from docs/wormsoft-api.md (hermes-cn-ru repo):
a 429 "user reached the limit" means subscription-window credits are
gone (retrying won't help within this call); a 429 without that message
is a rate limit (120 req/min on the Payed tier), and 500 is a transient
upstream failure — both of those are worth exactly one retry.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

EMBEDDING_URL = "https://ai.wormsoft.ru/api/gpt/embedding"
EMBEDDING_MODEL = "qwen/qwen3-embedding:8b"
_TIMEOUT_SECONDS = 20.0
_RETRY_DELAY_SECONDS = 4.0


class CreditsExhausted(Exception):
    """429 'user reached the limit' — subscription window credits are gone."""


class TransientEmbeddingError(Exception):
    """Rate limit (429 without the credits message) or 500 — worth one retry."""


def _request_embedding(text: str, api_key: str) -> list:
    response = requests.post(
        EMBEDDING_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "content": text},
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        body_text = (response.text or "").lower()
        if "reached the limit" in body_text:
            raise CreditsExhausted(response.text)
        raise TransientEmbeddingError(f"rate limited: {response.text}")
    if response.status_code >= 500:
        raise TransientEmbeddingError(f"server error {response.status_code}: {response.text}")
    response.raise_for_status()
    data = response.json()
    return data["data"][0]["embedding"]


def fetch_embedding(text: str, api_key: str) -> Optional[list]:
    """Fetch an embedding, tolerating transient failures.

    Never raises — returns None when the embedding could not be
    obtained, so callers can persist the project without an embedding
    rather than blocking on wormsoft.ru availability.
    """
    try:
        return _request_embedding(text, api_key)
    except CreditsExhausted:
        return None
    except TransientEmbeddingError:
        time.sleep(_RETRY_DELAY_SECONDS)
        try:
            return _request_embedding(text, api_key)
        except Exception:
            return None
    except requests.RequestException:
        return None
