"""Behavior tests for task MCP tools."""

import orjson
import pytest


@pytest.mark.asyncio
async def test_list_tasks_uses_typed_task_endpoint(task_tools) -> None:
    tools, client = task_tools
    client.responses["GET", "task/offline_download/done"] = {
        "value": [
            {
                "id": "task-1",
                "title": "download",
                "state": "done",
                "percent": 0,
                "dst_path": "/downloads/file.iso",
                "error_message": "",
                "created": "today",
                "updated": "now",
                "token": "secret",
            }
        ],
        "total": 9,
    }

    result = await tools["list_tasks"](
        task_type="offline_download",
        status="done",
        page=2,
        per_page=25,
    )

    assert orjson.loads(result) == {
        "task_type": "offline_download",
        "status": "done",
        "page": 2,
        "per_page": 25,
        "total": 9,
        "tasks": [
            {
                "task_id": "task-1",
                "name": "download",
                "status": "done",
                "progress": 0,
                "path": "/downloads/file.iso",
                "created_at": "today",
                "updated_at": "now",
            }
        ],
    }
    assert client.requests == [
        (
            "GET",
            "task/offline_download/done",
            {"params": {"page": 2, "per_page": 25}},
        )
    ]


@pytest.mark.asyncio
async def test_list_tasks_all_queries_all_categories(task_tools) -> None:
    tools, client = task_tools
    client.responses["GET", "task/copy/undone"] = {
        "value": [{"id": "copy-1", "name": "copy", "status": "running", "secret": "drop"}],
        "total": 99,
    }

    result = await tools["list_tasks"](task_type="all", status="undone")

    assert client.requests == [
        ("GET", "task/copy/undone", {"params": {"page": 1, "per_page": 50}}),
        ("GET", "task/decompress/undone", {"params": {"page": 1, "per_page": 50}}),
        ("GET", "task/decompress_upload/undone", {"params": {"page": 1, "per_page": 50}}),
        ("GET", "task/offline_download/undone", {"params": {"page": 1, "per_page": 50}}),
        ("GET", "task/offline_download_transfer/undone", {"params": {"page": 1, "per_page": 50}}),
        ("GET", "task/upload/undone", {"params": {"page": 1, "per_page": 50}}),
    ]
    data = orjson.loads(result)
    assert data == {
        "task_type": "all",
        "status": "undone",
        "page": 1,
        "per_page": 50,
        "total": 1,
        "tasks": [
            {
                "task_id": "copy-1",
                "name": "copy",
                "status": "running",
                "task_type": "copy",
            }
        ],
    }


@pytest.mark.asyncio
async def test_get_task_info_uses_tid_query_param(task_tools) -> None:
    tools, client = task_tools

    result = await tools["get_task_info"]("task-123", task_type="offline_download")

    assert orjson.loads(result) == {
        "task_id": "task-123",
        "task_type": "offline_download",
    }
    assert client.requests == [
        (
            "POST",
            "task/offline_download/info",
            {"params": {"tid": "task-123"}},
        )
    ]


@pytest.mark.asyncio
async def test_task_tools_validate_task_type(task_tools) -> None:
    tools, client = task_tools

    with pytest.raises(ValueError, match="Unsupported task_type"):
        await tools["get_task_info"]("task-123", task_type="bad")

    assert client.requests == []


@pytest.mark.asyncio
async def test_cancel_task_uses_typed_endpoint(task_tools) -> None:
    tools, client = task_tools

    result = await tools["cancel_task"](
        "task-123",
        task_type="offline_download",
        confirm=True,
    )

    assert result == "Task cancelled: task-123"
    assert client.requests == [
        (
            "POST",
            "task/offline_download/cancel",
            {"params": {"tid": "task-123"}},
        )
    ]


@pytest.mark.asyncio
async def test_batch_cancel_tasks_sends_array(task_tools) -> None:
    tools, client = task_tools

    result = await tools["batch_cancel_tasks"](
        task_ids=["t1", "t2"],
        task_type="offline_download",
        confirm=True,
    )

    assert "submitted" in result.lower()
    assert client.requests == [
        (
            "POST",
            "task/offline_download/cancel_some",
            {"json": ["t1", "t2"]},
        )
    ]


@pytest.mark.asyncio
async def test_batch_delete_tasks_sends_array(task_tools) -> None:
    tools, client = task_tools

    result = await tools["batch_delete_tasks"](
        task_ids=["t1"],
        task_type="offline_download",
        confirm=True,
    )

    assert "submitted" in result.lower()
    assert client.requests == [
        (
            "POST",
            "task/offline_download/delete_some",
            {"json": ["t1"]},
        )
    ]


@pytest.mark.asyncio
async def test_batch_retry_tasks_sends_array(task_tools) -> None:
    tools, client = task_tools

    result = await tools["batch_retry_tasks"](
        task_ids=["t1", "t2", "t3"],
        task_type="offline_download",
    )

    assert "submitted" in result.lower()
    assert client.requests == [
        (
            "POST",
            "task/offline_download/retry_some",
            {"json": ["t1", "t2", "t3"]},
        )
    ]


@pytest.mark.asyncio
async def test_clear_done_tasks(task_tools) -> None:
    tools, client = task_tools

    result = await tools["clear_done_tasks"](task_type="offline_download")

    assert "cleared" in result.lower()
    assert client.requests == [("POST", "task/offline_download/clear_done", {})]


@pytest.mark.asyncio
async def test_clear_succeeded_tasks(task_tools) -> None:
    tools, client = task_tools

    result = await tools["clear_succeeded_tasks"](task_type="offline_download")

    assert "cleared" in result.lower()
    assert client.requests == [("POST", "task/offline_download/clear_succeeded", {})]


@pytest.mark.asyncio
async def test_retry_failed_tasks(task_tools) -> None:
    tools, client = task_tools

    result = await tools["retry_failed_tasks"](task_type="offline_download")

    assert "retry" in result.lower()
    assert client.requests == [("POST", "task/offline_download/retry_failed", {})]


@pytest.mark.asyncio
async def test_batch_tasks_require_confirm(task_tools) -> None:
    tools, client = task_tools

    result = await tools["batch_cancel_tasks"](task_ids=["t1"], confirm=False)
    assert "not performed" in result.lower()
    assert client.requests == []


@pytest.mark.asyncio
async def test_batch_tasks_require_nonempty_ids(task_tools) -> None:
    tools, client = task_tools

    result = await tools["batch_cancel_tasks"](task_ids=[], confirm=True)
    assert "no task" in result.lower()
    assert client.requests == []

    result = await tools["batch_delete_tasks"](task_ids=[], confirm=True)
    assert "no task" in result.lower()

    result = await tools["batch_retry_tasks"](task_ids=[], task_type="offline_download")
    assert "no task" in result.lower()


@pytest.mark.asyncio
async def test_list_tasks_all_reports_failed_categories(task_tools) -> None:
    tools, client = task_tools
    client.responses["GET", "task/copy/undone"] = RuntimeError("copy unavailable")

    result = await tools["list_tasks"](task_type="all")

    data = orjson.loads(result)
    assert data["total"] == 0
    assert data["tasks"] == []
    assert data["errors"] == [{"task_type": "copy", "error": "copy unavailable"}]
