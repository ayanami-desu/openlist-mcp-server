"""Behavior tests for share management MCP tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_create_share_sends_files_array(share_tools) -> None:
    tools, client = share_tools

    await tools["create_share"](
        files=["/docs/report.pdf", "/docs/summary.csv"],
        pwd="secret",
    )

    assert client.requests == [
        (
            "POST",
            "share/create",
            {
                "json": {
                    "files": ["/docs/report.pdf", "/docs/summary.csv"],
                    "pwd": "secret",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_create_share_rejects_empty_files(share_tools) -> None:
    tools, client = share_tools

    result = await tools["create_share"](files=[])

    assert "error" in result.lower() or "must" in result.lower()
    assert client.requests == []


@pytest.mark.asyncio
async def test_update_share_sends_id_and_files(share_tools) -> None:
    tools, client = share_tools

    await tools["update_share"](
        share_id="abc123",
        files=["/docs/report.pdf"],
        pwd="newpass",
    )

    assert client.requests == [
        (
            "POST",
            "share/update",
            {
                "json": {
                    "id": "abc123",
                    "files": ["/docs/report.pdf"],
                    "pwd": "newpass",
                }
            },
        ),
    ]


@pytest.mark.asyncio
async def test_create_share_projects_only_safe_fields(share_tools) -> None:
    tools, client = share_tools
    client.responses["POST", "share/create"] = {
        "id": "share-1",
        "url": "https://share.invalid/1",
        "expires": "2026-12-31",
        "pwd": "secret",
        "password": "secret",
        "files": ["/docs/report.pdf"],
        "enabled": True,
        "max_accessed": 9,
        "remark": "drop",
    }

    result = await tools["create_share"](files=["/docs/report.pdf"], pwd="secret")

    assert orjson.loads(result) == {
        "share_id": "share-1",
        "share_url": "https://share.invalid/1",
        "expires": "2026-12-31",
        "password_protected": True,
    }


@pytest.mark.asyncio
async def test_list_and_get_share_project_password_and_files(share_tools) -> None:
    tools, client = share_tools
    client.responses["GET", "share/list"] = {
        "value": [
            {
                "id": "share-1",
                "enabled": False,
                "expires": "2026-12-31",
                "has_password": True,
                "max_access": 5,
                "access_count": 2,
                "remark": "docs",
                "pwd": "secret",
                "files": ["/docs/report.pdf"],
            }
        ],
        "total": 9,
    }
    client.responses["GET", "share/get"] = {
        "share_id": "share-1",
        "share_url": "https://share.invalid/1",
        "password_protected": True,
        "pwd": "secret",
        "files": ["/docs/report.pdf", {"path": "/docs/summary.csv"}, {"secret": "drop"}],
        "token": "drop",
    }

    listed = await tools["list_shares"](page=2, per_page=10)
    detail = await tools["get_share_info"]("share-1")

    assert orjson.loads(listed) == {
        "page": 2,
        "per_page": 10,
        "total": 9,
        "shares": [
            {
                "share_id": "share-1",
                "enabled": False,
                "expires": "2026-12-31",
                "password_protected": True,
                "max_accessed": 5,
                "accessed": 2,
                "remark": "docs",
            }
        ],
    }
    assert orjson.loads(detail) == {
        "share_id": "share-1",
        "share_url": "https://share.invalid/1",
        "password_protected": True,
        "files": ["/docs/report.pdf", "/docs/summary.csv"],
    }


@pytest.mark.asyncio
async def test_disable_share_sends_id(share_tools) -> None:
    tools, client = share_tools

    await tools["disable_share"](share_id="abc123")

    assert client.requests == [("POST", "share/disable", {"json": {"id": "abc123"}})]


@pytest.mark.asyncio
async def test_enable_share_sends_id(share_tools) -> None:
    tools, client = share_tools

    await tools["enable_share"](share_id="abc123")

    assert client.requests == [("POST", "share/enable", {"json": {"id": "abc123"}})]


@pytest.mark.asyncio
async def test_delete_share_requires_confirm(share_tools) -> None:
    tools, client = share_tools

    result = await tools["delete_share"](share_id="abc123", confirm=False)

    assert "not performed" in result.lower()
    assert client.requests == []


@pytest.mark.asyncio
async def test_delete_share_with_confirm_uses_query_param(share_tools) -> None:
    tools, client = share_tools

    await tools["delete_share"](share_id="abc123", confirm=True)

    assert client.requests == [("POST", "share/delete", {"params": {"id": "abc123"}})]


@pytest.mark.asyncio
async def test_read_only_blocks_share_write_tools(share_tools, monkeypatch) -> None:
    tools, client = share_tools
    monkeypatch.setenv("OPENLIST_READONLY", "true")
    monkeypatch.setattr("openlist_mcp.config._config", None)

    with pytest.raises(PermissionError, match="OPENLIST_READONLY"):
        await tools["create_share"](files=["/test.txt"])

    assert client.requests == []


@pytest.mark.asyncio
async def test_allowed_paths_blocks_out_of_scope_files(share_tools, monkeypatch) -> None:
    tools, client = share_tools
    monkeypatch.setenv("OPENLIST_ALLOWED_PATHS", "/safe")
    monkeypatch.setattr("openlist_mcp.config._config", None)

    with pytest.raises(PermissionError, match="outside OPENLIST_ALLOWED_PATHS"):
        await tools["create_share"](files=["/private/file.txt"])

    assert client.requests == []
