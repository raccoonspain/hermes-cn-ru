import asyncio
import logging
import subprocess
import threading

import pytest

from hermes_web import permissions


def test_ensure_ownership_sync_calls_sudo_script_with_project_root(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")

    assert captured["cmd"] == [
        "sudo", "-n", permissions.FIX_SCRIPT_PATH, "/home/hermes/workspace/dem/ALL/a",
    ]
    assert captured["capture_output"] is True
    assert captured["timeout"] == 30


def test_ensure_ownership_sync_never_raises_on_nonzero_exit(monkeypatch, caplog):
    def fake_run(cmd, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"refuse: outside root")

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")  # не должно бросить

    assert "refuse: outside root" in caplog.text


def test_ensure_ownership_sync_never_raises_on_timeout(monkeypatch, caplog):
    def fake_run(cmd, capture_output, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")  # не должно бросить

    assert "timed out" in caplog.text.lower() or "timeout" in caplog.text.lower()


@pytest.mark.asyncio
async def test_ensure_ownership_runs_off_event_loop(monkeypatch):
    calling_thread = threading.current_thread()
    seen = {}

    def fake_sync(project_root):
        seen["thread"] = threading.current_thread()
        seen["project_root"] = project_root

    monkeypatch.setattr(permissions, "ensure_ownership_sync", fake_sync)

    await permissions.ensure_ownership("/home/hermes/workspace/dem/ALL/a")

    assert seen["project_root"] == "/home/hermes/workspace/dem/ALL/a"
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()
