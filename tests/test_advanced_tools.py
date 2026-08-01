"""Behavior tests for advanced MCP tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_get_capabilities_summarizes_safe_features(advanced_tools) -> None:
    tools, client = advanced_tools
    client.responses["GET", "public/offline_download_tools"] = {
        "value": ["aria2", {"name": "aria2"}, {"tool": "wget"}, {"secret": "drop"}]
    }

    result = await tools["get_capabilities"]()
    data = orjson.loads(result)

    assert data == {
        "authentication": {
            "credentials_configured": True,
            "totp_secret_configured": False,
        },
        "features": {
            "file_browse": True,
            "file_manage": True,
            "file_transfer": True,
            "shares": True,
            "tasks": True,
            "offline_download_tools": ["aria2", "wget"],
            "archive_decompress": True,
        },
        "mcp_safety": {
            "high_impact_operations_require_confirm": True,
            "read_only": False,
            "allowed_paths": [],
            "local_upload_roots_configured": False,
        },
    }
    assert client.requests == [
        ("GET", "public/offline_download_tools", {"require_auth": False}),
    ]


@pytest.mark.asyncio
async def test_list_archive_files_validates_archive_name(advanced_tools) -> None:
    tools, client = advanced_tools

    with pytest.raises(ValueError, match="path separators"):
        await tools["list_archive_files"]("/archives", "bad/name.zip")

    assert client.requests == []


@pytest.mark.asyncio
async def test_list_archive_files_sends_expected_payload(advanced_tools) -> None:
    tools, client = advanced_tools

    result = await tools["list_archive_files"](
        "/archives",
        "bundle.zip",
        inner_path="/docs",
        archive_pass="secret",
        refresh=True,
    )

    assert orjson.loads(result) == {
        "archive": "/archives/bundle.zip",
        "inner_path": "/docs",
        "entries": [],
    }
    assert client.requests == [
        (
            "POST",
            "fs/archive/list",
            {
                "json": {
                    "path": "/archives/bundle.zip",
                    "inner_path": "/docs",
                    "refresh": True,
                    "archive_pass": "secret",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_archive_meta_sends_path(advanced_tools) -> None:
    tools, client = advanced_tools

    client.responses["POST", "fs/archive/meta"] = {
        "format": "zip",
        "encrypted": False,
        "size": 100,
        "modified": "today",
        "comment": "secret",
        "tree": [{"name": "secret"}],
    }
    result = await tools["get_archive_meta"]("/data/backup.zip")

    assert orjson.loads(result) == {
        "path": "/data/backup.zip",
        "format": "zip",
        "encrypted": False,
        "size": 100,
        "modified": "today",
    }

    assert client.requests == [
        ("POST", "fs/archive/meta", {"json": {"path": "/data/backup.zip", "refresh": False}})
    ]


@pytest.mark.asyncio
async def test_get_archive_meta_with_pass_and_refresh(advanced_tools) -> None:
    tools, client = advanced_tools

    await tools["get_archive_meta"](
        "/data/encrypted.7z",
        archive_pass="hunter2",
        refresh=True,
    )

    assert client.requests == [
        (
            "POST",
            "fs/archive/meta",
            {
                "json": {
                    "path": "/data/encrypted.7z",
                    "refresh": True,
                    "archive_pass": "hunter2",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_torrent_upload_parse_sends_multipart(advanced_tools) -> None:
    tools, client = advanced_tools

    result = await tools["torrent_upload_parse"]("ZGVhZGJlZWY=")
    explicit = await tools["torrent_upload_parse"]("ZGVhZGJlZWY=", include_torrent_data=True)

    assert client.requests == [
        (
            "MULTIPART",
            "fs/torrent/upload_parse",
            {
                "field_name": "torrent",
                "file_name": "file.torrent",
                "content_type": "application/x-bittorrent",
                "size": 8,
            },
        ),
        (
            "MULTIPART",
            "fs/torrent/upload_parse",
            {
                "field_name": "torrent",
                "file_name": "file.torrent",
                "content_type": "application/x-bittorrent",
                "size": 8,
            },
        ),
    ]
    assert orjson.loads(result) == {
        "name": "parsed",
        "info_hash": "a" * 40,
        "files": [{"path": "file.txt", "size": 100}],
    }
    assert orjson.loads(explicit)["torrent_data"] == "ZHVtbXk="


@pytest.mark.asyncio
async def test_archive_extensions_and_entries_are_compact(advanced_tools) -> None:
    tools, client = advanced_tools
    client.responses["GET", "public/archive_extensions"] = {
        "value": ["zip", "zip", "7z", {"name": "drop"}]
    }
    client.responses["POST", "fs/archive/list"] = {
        "content": [
            {"name": "inside.txt", "type": 0, "size": 10, "hashinfo": "secret"},
            {"type": 0, "size": 20},
        ]
    }

    extensions = await tools["get_archive_extensions"]()
    entries = await tools["list_archive_files"]("/archives", "bundle.zip")

    assert orjson.loads(extensions) == {"extensions": ["zip", "7z"]}
    assert orjson.loads(entries) == {
        "archive": "/archives/bundle.zip",
        "inner_path": "/",
        "entries": [{"name": "inside.txt", "is_dir": False, "size": 10}],
    }


@pytest.mark.asyncio
async def test_find_duplicates_and_batch_download_drop_raw_fields(advanced_tools) -> None:
    tools, client = advanced_tools
    client.responses["POST", "fs/list"] = {
        "value": [
            {"name": "a.txt", "type": 0, "size": 5, "hashinfo": "secret"},
            {"name": "b.txt", "type": 0, "size": 5, "hash_info": "secret"},
        ]
    }
    client.responses["POST", "fs/add_offline_download"] = {
        "task": {"id": "download-1"},
        "message": "queued",
        "result": {"token": "drop"},
    }

    duplicates = await tools["find_duplicates"]("/docs", by="size_only")
    downloads = await tools["batch_download"](
        urls=["https://example.invalid/a", "https://example.invalid/b"],
        path="/downloads",
    )

    assert orjson.loads(duplicates) == {
        "path": "/docs",
        "group_by": "size_only",
        "total_duplicate_groups": 1,
        "total_duplicate_files": 2,
        "duplicates": [{"size": 5, "files": ["/docs/a.txt", "/docs/b.txt"]}],
    }
    assert orjson.loads(downloads) == [
        {
            "url": "https://example.invalid/a",
            "ok": True,
            "task_ids": ["download-1"],
            "message": "queued",
        },
        {
            "url": "https://example.invalid/b",
            "ok": True,
            "task_ids": ["download-1"],
            "message": "queued",
        },
    ]


@pytest.mark.asyncio
async def test_content_preview_reports_truncation_without_duplicate_suffix(
    advanced_tools, monkeypatch
) -> None:
    tools, client = advanced_tools
    client.responses["POST", "fs/get"] = {
        "raw_url": "https://download.invalid/file",
        "thumb": "secret",
    }

    class FakeResponse:
        content = b"abcdef"

    class FakeHTTPClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            assert url == "https://download.invalid/file"
            assert headers == {"Range": "bytes=0-6"}
            return FakeResponse()

    monkeypatch.setattr(
        "openlist_mcp.tools.advanced.httpx.AsyncClient",
        lambda timeout: FakeHTTPClient(),
    )

    result = await tools["content_preview"]("/docs/readme.txt", max_chars=3)

    assert orjson.loads(result) == {
        "path": "/docs/readme.txt",
        "content": "abc",
        "truncated": True,
        "language": "text",
    }
