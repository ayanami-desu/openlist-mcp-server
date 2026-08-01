"""Shared test helpers for OpenList MCP tool registration tests."""

from __future__ import annotations

import pytest

from openlist_mcp.tools.advanced import register_advanced_tools
from openlist_mcp.tools.fs import register_fs_tools
from openlist_mcp.tools.task import register_task_tools
from openlist_mcp.tools.transfer import register_transfer_tools


class ToolRecorder:
    """Minimal FastMCP-like recorder for registered tool functions."""

    def __init__(self) -> None:
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class FakeClient:
    def __init__(self) -> None:
        self.requests = []
        self.responses = {}
        self.uploads = []

    async def request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if (method, path) in self.responses:
            response = self.responses[(method, path)]
            if isinstance(response, BaseException):
                raise response
            return response
        if path == "public/settings":
            return {"title": "OpenList Test"}
        if path == "me":
            return {"username": "admin", "role": 2}
        if path == "public/offline_download_tools":
            return ["aria2"]
        return {}

    async def multipart_form(
        self,
        path: str,
        field_name: str,
        file_bytes: bytes,
        file_name: str,
        content_type: str = "application/octet-stream",
    ) -> dict:
        self.requests.append(
            (
                "MULTIPART",
                path,
                {
                    "field_name": field_name,
                    "file_name": file_name,
                    "content_type": content_type,
                    "size": len(file_bytes),
                },
            )
        )
        return {
            "info": {
                "name": "parsed",
                "info_hash": "a" * 40,
                "files": [{"path": "file.txt", "size": 100}],
            },
            "torrent_data": "ZHVtbXk=",
        }

    async def upload(self, **kwargs):
        self.uploads.append(kwargs)
        return {}


@pytest.fixture
def fs_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.delenv("OPENLIST_ALLOWED_PATHS", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.fs.get_client", fake_get_client)
    register_fs_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def transfer_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.delenv("OPENLIST_ALLOWED_PATHS", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.transfer.get_client", fake_get_client)
    register_transfer_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def task_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.task.get_client", fake_get_client)
    register_task_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def advanced_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.setenv("OPENLIST_USERNAME", "admin")
    monkeypatch.setenv("OPENLIST_PASSWORD", "secret")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.delenv("OPENLIST_ALLOWED_PATHS", raising=False)
    monkeypatch.delenv("OPENLIST_LOCAL_UPLOAD_ROOTS", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.advanced.get_client", fake_get_client)
    register_advanced_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def admin_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.admin.get_client", fake_get_client)
    from openlist_mcp.tools.admin import register_admin_tools

    register_admin_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def share_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.delenv("OPENLIST_ALLOWED_PATHS", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.share.get_client", fake_get_client)
    from openlist_mcp.tools.share import register_share_tools

    register_share_tools(recorder)
    return recorder.tools, client


@pytest.fixture
def auth_tools(monkeypatch):
    recorder = ToolRecorder()
    client = FakeClient()

    async def fake_get_client():
        return client

    monkeypatch.setenv("OPENLIST_URL", "https://openlist.example")
    monkeypatch.delenv("OPENLIST_READONLY", raising=False)
    monkeypatch.delenv("OPENLIST_ALLOWED_PATHS", raising=False)
    monkeypatch.setattr("openlist_mcp.config._config", None)
    monkeypatch.setattr("openlist_mcp.tools.auth.get_client", fake_get_client)
    from openlist_mcp.tools.auth import register_auth_tools, register_public_tools

    register_auth_tools(recorder)
    register_public_tools(recorder)
    return recorder.tools, client
