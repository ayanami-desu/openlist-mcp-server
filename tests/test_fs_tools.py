"""Behavior tests for filesystem MCP tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_create_folder_uses_mkdir_without_name_validation(fs_tools) -> None:
    tools, client = fs_tools

    result = await tools["create_folder"]("/projects/new")

    assert result == "Folder created successfully: /projects/new"
    assert client.requests == [("POST", "fs/mkdir", {"json": {"path": "/projects/new"}})]


@pytest.mark.asyncio
async def test_read_only_blocks_write_tools(fs_tools, monkeypatch) -> None:
    tools, client = fs_tools
    monkeypatch.setenv("OPENLIST_READONLY", "true")
    monkeypatch.setattr("openlist_mcp.config._config", None)

    with pytest.raises(PermissionError, match="OPENLIST_READONLY"):
        await tools["create_folder"]("/projects/new")

    assert client.requests == []


@pytest.mark.asyncio
async def test_allowed_paths_blocks_out_of_scope_reads(fs_tools, monkeypatch) -> None:
    tools, client = fs_tools
    monkeypatch.setenv("OPENLIST_ALLOWED_PATHS", "/safe,/team/docs")
    monkeypatch.setattr("openlist_mcp.config._config", None)

    with pytest.raises(PermissionError, match="outside OPENLIST_ALLOWED_PATHS"):
        await tools["list_files"]("/private")

    assert client.requests == []


@pytest.mark.asyncio
async def test_allowed_paths_allows_child_paths(fs_tools, monkeypatch) -> None:
    tools, client = fs_tools
    monkeypatch.setenv("OPENLIST_ALLOWED_PATHS", "/safe")
    monkeypatch.setattr("openlist_mcp.config._config", None)

    await tools["list_files"]("/safe/nested")

    assert client.requests == [
        (
            "POST",
            "fs/list",
            {
                "json": {
                    "path": "/safe/nested",
                    "page": 1,
                    "per_page": 50,
                    "password": "",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_list_dirs_sends_expected_payload(fs_tools) -> None:
    tools, client = fs_tools

    result = await tools["list_dirs"]("/projects", password="secret", force_root=True)

    assert orjson.loads(result) == {"path": "/projects", "directories": []}
    assert client.requests == [
        (
            "POST",
            "fs/dirs",
            {
                "json": {
                    "path": "/projects",
                    "password": "secret",
                    "force_root": True,
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_rename_validates_new_name(fs_tools) -> None:
    tools, client = fs_tools

    with pytest.raises(ValueError, match="path separators"):
        await tools["rename"]("/projects/old", "../bad")

    assert client.requests == []


@pytest.mark.asyncio
async def test_rename_sends_expected_payload(fs_tools) -> None:
    tools, client = fs_tools

    result = await tools["rename"]("/projects/old", "new")

    assert result == "Renamed successfully: /projects/old -> new"
    assert client.requests == [
        ("POST", "fs/rename", {"json": {"path": "/projects/old", "name": "new"}})
    ]


@pytest.mark.asyncio
async def test_batch_rename_validates_names(fs_tools) -> None:
    tools, client = fs_tools

    with pytest.raises(ValueError, match="path separators"):
        await tools["batch_rename"](
            "/projects",
            [{"src_name": "good.txt", "new_name": "bad/name.txt"}],
        )

    assert client.requests == []


@pytest.mark.asyncio
async def test_batch_rename_sends_expected_payload(fs_tools) -> None:
    tools, client = fs_tools

    result = await tools["batch_rename"](
        "/projects",
        [
            {"src_name": "old-a.txt", "new_name": "new-a.txt"},
            {"src_name": "old-b.txt", "new_name": "new-b.txt"},
        ],
    )

    assert orjson.loads(result) == {"ok": True, "operation": "batch_rename", "affected": 2}
    assert client.requests == [
        (
            "POST",
            "fs/batch_rename",
            {
                "json": {
                    "src_dir": "/projects",
                    "rename_objects": [
                        {"src_name": "old-a.txt", "new_name": "new-a.txt"},
                        {"src_name": "old-b.txt", "new_name": "new-b.txt"},
                    ],
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_copy_validates_each_name(fs_tools) -> None:
    tools, client = fs_tools

    with pytest.raises(ValueError, match="path separators"):
        await tools["copy"]("/src", "/dst", ["good.txt", "bad/name.txt"])

    assert client.requests == []


@pytest.mark.asyncio
async def test_list_files_projects_only_stable_entries(fs_tools) -> None:
    tools, client = fs_tools
    client.responses["POST", "fs/list"] = {
        "value": [
            {
                "name": "report.txt",
                "type": 0,
                "size": 12,
                "modified": "yesterday",
                "thumb": "secret",
                "sign": "secret",
                "hashinfo": "secret",
                "provider": "secret",
            },
            {"name": "docs", "type": 1, "size": 0, "hash_info": "secret"},
            {"type": 0, "size": 99},
            "not-an-entry",
        ],
        "total": 8,
    }

    result = await tools["list_files"]("/projects", page=2, per_page=10)

    assert orjson.loads(result) == {
        "path": "/projects",
        "page": 2,
        "per_page": 10,
        "total": 8,
        "entries": [
            {"name": "report.txt", "is_dir": False, "size": 12},
            {"name": "docs", "is_dir": True, "size": 0},
        ],
    }


@pytest.mark.asyncio
async def test_search_files_builds_compact_full_paths(fs_tools) -> None:
    tools, client = fs_tools
    client.responses["POST", "fs/search"] = {
        "content": [
            {"name": "a.txt", "parent": "/docs/", "type": 0, "size": 4, "hashinfo": "secret"},
            {"name": "folder", "type": 1, "size": 0, "thumb": "secret"},
            {"name": "", "parent": "/docs", "type": 0, "size": 1},
        ],
        "total": 2,
    }

    result = await tools["search_files"](parent="/docs", keywords="a")

    assert orjson.loads(result) == {
        "parent": "/docs",
        "page": 1,
        "per_page": 50,
        "total": 2,
        "entries": [
            {"path": "/docs/a.txt", "name": "a.txt", "is_dir": False, "size": 4},
            {"path": "/docs/folder", "name": "folder", "is_dir": True, "size": 0},
        ],
    }


@pytest.mark.asyncio
async def test_get_file_info_uses_fallback_name_and_safe_fields(fs_tools) -> None:
    tools, client = fs_tools
    client.responses["POST", "fs/get"] = {
        "type": 0,
        "size": 21,
        "modified": "2026-01-01",
        "created": "2025-01-01",
        "provider": "local",
        "raw_url": "https://secret.invalid/file",
        "thumb": "secret",
        "sign": "secret",
        "hash_info": "secret",
        "readme": "secret",
    }

    result = await tools["get_file_info"]("/docs/report.txt")

    assert orjson.loads(result) == {
        "path": "/docs/report.txt",
        "name": "report.txt",
        "is_dir": False,
        "size": 21,
        "modified": "2026-01-01",
        "created": "2025-01-01",
        "provider": "local",
    }


@pytest.mark.asyncio
async def test_disk_usage_drops_human_mirrors(fs_tools) -> None:
    tools, client = fs_tools
    client.responses["POST", "fs/list"] = {
        "content": [{"name": "report.txt", "type": 0, "size": 12, "thumb": "secret"}]
    }

    result = await tools["disk_usage"]("/docs")

    assert orjson.loads(result) == {
        "path": "/docs",
        "total_size": 12,
        "total_files": 1,
        "top_directories": [],
        "by_file_type": [{"extension": "txt", "count": 1, "size": 12}],
    }


@pytest.mark.asyncio
async def test_file_actions_project_task_ids(fs_tools) -> None:
    tools, client = fs_tools
    client.responses["POST", "fs/batch_rename"] = {
        "task": {"id": "rename-1"},
        "message": "queued",
        "token": "secret",
    }
    client.responses["POST", "fs/copy"] = {"value": {"tid": "copy-1"}}
    client.responses["POST", "fs/remove_empty_directory"] = {"data": {"task_id": "remove-1"}}

    renamed = await tools["batch_rename"]("/docs", [{"src_name": "a", "new_name": "b"}])
    copied = await tools["copy"]("/docs", "/backup", ["a"])
    removed = await tools["remove_empty_dirs"]("/docs", confirm=True)

    assert orjson.loads(renamed) == {
        "ok": True,
        "operation": "batch_rename",
        "task_ids": ["rename-1"],
        "message": "queued",
        "affected": 1,
    }
    assert orjson.loads(copied) == {
        "ok": True,
        "operation": "copy",
        "task_ids": ["copy-1"],
        "affected": 1,
    }
    assert orjson.loads(removed) == {
        "ok": True,
        "operation": "remove_empty_dirs",
        "task_ids": ["remove-1"],
    }
