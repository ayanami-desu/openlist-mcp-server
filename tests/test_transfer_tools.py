"""Behavior tests for transfer MCP tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_upload_file_validates_file_name(transfer_tools) -> None:
    tools, client = transfer_tools

    with pytest.raises(ValueError, match="path separators"):
        await tools["upload_file"]("/docs", "bad/name.txt", "aGVsbG8=")

    assert client.uploads == []


@pytest.mark.asyncio
async def test_upload_file_sends_decoded_content(transfer_tools) -> None:
    tools, client = transfer_tools

    result = await tools["upload_file"]("/docs", "note.txt", "aGVsbG8=", as_task=False)

    assert result == "File uploaded successfully: /docs/note.txt"
    assert client.uploads == [
        {
            "path": "/docs",
            "file_content": b"hello",
            "file_name": "note.txt",
            "as_task": False,
        }
    ]


@pytest.mark.asyncio
async def test_get_download_url_hides_missing_raw_response(transfer_tools) -> None:
    tools, client = transfer_tools
    client.responses["POST", "fs/get"] = {
        "name": "report.txt",
        "type": 0,
        "size": 12,
        "raw_url": "",
        "sign": "secret",
        "hashinfo": "secret",
    }

    result = await tools["get_download_url"]("/docs/report.txt")

    assert orjson.loads(result) == {
        "ok": False,
        "path": "/docs/report.txt",
        "error": "No download URL available.",
    }


@pytest.mark.asyncio
async def test_get_download_url_returns_only_direct_link(transfer_tools) -> None:
    tools, client = transfer_tools
    client.responses["POST", "fs/get"] = {
        "raw_url": "https://download.invalid/signed",
        "thumb": "secret",
        "hash_info": "secret",
    }

    result = await tools["get_download_url"]("/docs/report.txt")

    assert orjson.loads(result) == {
        "download_url": "https://download.invalid/signed",
        "path": "/docs/report.txt",
    }
