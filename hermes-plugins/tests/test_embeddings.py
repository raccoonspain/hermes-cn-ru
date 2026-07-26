import requests

from project_index import embeddings


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def test_fetch_embedding_success(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return _FakeResponse(200, {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": embeddings.EMBEDDING_MODEL,
        })

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст запроса", "fake-key")
    assert result == [0.1, 0.2, 0.3]
    assert len(calls) == 1
    url, headers, payload, _timeout = calls[0]
    assert url == embeddings.EMBEDDING_URL
    assert headers["Authorization"] == "Bearer fake-key"
    assert payload == {"model": embeddings.EMBEDDING_MODEL, "content": "текст запроса"}


def test_fetch_embedding_credits_exhausted_no_retry(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(429, text="Error: user reached the limit")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 1


def test_fetch_embedding_rate_limit_retries_once_then_gives_up(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(429, text="too many requests")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 2


def test_fetch_embedding_rate_limit_retry_succeeds(monkeypatch):
    responses = [
        _FakeResponse(429, text="too many requests"),
        _FakeResponse(200, {"data": [{"embedding": [1.0]}]}),
    ]

    def fake_post(url, headers, json, timeout):
        return responses.pop(0)

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result == [1.0]


def test_fetch_embedding_server_error_retries_once(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(500, text="internal error")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 2


def test_fetch_embedding_network_error_returns_none(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
