"""OpenList MCP Tools package."""

import posixpath
from collections.abc import Mapping, Sequence
from typing import Any

import orjson

from ..config import get_config


def validate_path(path: str) -> None:
    """Validate that a path does not contain directory traversal sequences.

    Rejects paths with '..' as a path component to prevent directory traversal.
    Unlike a simple substring match, this only rejects '..' when it appears
    as a standalone component between separators, allowing legitimate names
    like 'backup..2024.tar.gz' or '/foo.v2/bar'.
    """
    if not path:
        raise ValueError("Path must not be empty")

    normalized_separators = path.replace("\\", "/")

    # Check each path component - reject only exact '..', not filenames containing '..'
    parts = normalized_separators.split("/")
    if ".." in parts:
        raise ValueError(f"Path must not contain directory traversal: {path}")

    # OpenList paths are URL/POSIX-style paths, even when the MCP server runs on Windows.
    normalized = posixpath.normpath(normalized_separators)
    if normalized_separators == "/":
        return
    if normalized_separators != normalized:
        raise ValueError(f"Path must not contain unsafe path components: {path}")


def enforce_path_allowed(path: str) -> None:
    """Validate a path and enforce optional MCP path allowlist."""
    validate_path(path)
    config = get_config()
    allowed_paths = config.allowed_paths
    if not allowed_paths:
        return

    normalized = path.replace("\\", "/")
    if normalized != "/":
        normalized = posixpath.normpath(normalized)

    for allowed in allowed_paths:
        if allowed == "/" or normalized == allowed or normalized.startswith(f"{allowed}/"):
            return
    raise PermissionError(
        f"Path is outside OPENLIST_ALLOWED_PATHS: {path}. Allowed paths: {', '.join(allowed_paths)}"
    )


def enforce_writable(operation: str) -> None:
    """Block write/high-impact tools when OPENLIST_READONLY is enabled."""
    if get_config().read_only:
        raise PermissionError(f"{operation} is disabled because OPENLIST_READONLY is enabled")


def validate_name(name: str) -> None:
    """Validate that a name is a single file/folder name, not a path."""
    if not name:
        raise ValueError("Name must not be empty")
    if name in (".", ".."):
        raise ValueError(f"Name must not be current or parent directory: {name}")
    if "/" in name or "\\" in name:
        raise ValueError(f"Name must not contain path separators: {name}")


def normalize_names(names: list[str] | str) -> list[str]:
    """Normalize and validate one or more filename-only values."""
    if isinstance(names, str):
        name_list = [name.strip() for name in names.split(",") if name.strip()]
    else:
        name_list = [name.strip() for name in names if name.strip()]

    for name in name_list:
        validate_name(name)
    return name_list


def validate_pagination(page: int, per_page: int, max_per_page: int = 200) -> None:
    """Validate pagination values before forwarding them to OpenList."""
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if per_page < 1 or per_page > max_per_page:
        raise ValueError(f"per_page must be between 1 and {max_per_page}")


async def _list_items(client: Any, path: str, password: str = "") -> list[Any]:
    """List items in a directory, returning parsed items or empty list on error."""
    try:
        data = await client.request(
            "POST", "fs/list", json={"path": path, "page": 1, "per_page": 200, "password": password}
        )
        items = data.get("content", data.get("value", []))
        if not isinstance(items, list):
            items = []
        return items
    except Exception:
        return []


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def compact_json(payload: object) -> str:
    """Serialize a tool response without formatting whitespace."""
    return orjson.dumps(payload).decode("utf-8")


def _has_compact_value(value: Any) -> bool:
    return value is not None and value != "" and value != {} and value != []


def compact_fields(data: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Keep explicitly requested fields that have meaningful values."""
    return {
        field: data[field] for field in fields if field in data and _has_compact_value(data[field])
    }


def first_present(data: Mapping[str, Any], fields: Sequence[str]) -> Any | None:
    """Return the first requested field whose value is meaningful."""
    for field in fields:
        if field in data and _has_compact_value(data[field]):
            return data[field]
    return None


def list_value(data: object, fields: Sequence[str]) -> list[Any]:
    """Extract a list from a direct response or known mapping containers."""
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for field in fields:
            value = data.get(field)
            if isinstance(value, list):
                return value
    return []


def collect_task_ids(payload: object) -> list[str]:
    """Collect stable task identifiers from an action response."""
    task_ids: list[str] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for field in ("task_id", "tid", "id"):
                candidate = value.get(field)
                if candidate is None or candidate == "" or isinstance(candidate, (Mapping, list)):
                    continue
                task_id = str(candidate)
                if task_id not in seen:
                    seen.add(task_id)
                    task_ids.append(task_id)
            for field in ("task", "tasks", "value", "data"):
                if field in value:
                    visit(value[field])
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return task_ids


def compact_file_entry(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project an OpenList file item to the stable browser entry shape."""
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    is_dir_value = item.get("is_dir")
    is_dir = (
        is_dir_value if isinstance(is_dir_value, bool) else item.get("type") in (1, "dir", "folder")
    )
    size = item.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool):
        size = 0
    return {"name": name, "is_dir": is_dir, "size": size}


def compact_user(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project a user object without credentials or permission internals."""
    result: dict[str, Any] = {}
    for output, aliases in (
        ("id", ("id",)),
        ("username", ("username", "name")),
        ("role", ("role",)),
        ("base_path", ("base_path",)),
        ("disabled", ("disabled",)),
        ("two_factor_enabled", ("two_factor_enabled", "two_factor")),
    ):
        value = first_present(data, aliases)
        if value is not None:
            result[output] = value
    return result


def action_result(
    payload: object,
    operation: str,
    *,
    task_type: str = "",
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project an action response to a small success DTO."""
    result: dict[str, Any] = {"ok": True, "operation": operation}
    if task_type:
        result["task_type"] = task_type
    task_ids = collect_task_ids(payload)
    if task_ids:
        result["task_ids"] = task_ids
    message: Any = payload if isinstance(payload, str) else None
    if (not isinstance(message, str) or not message) and isinstance(payload, Mapping):
        message = first_present(payload, ("message", "msg"))
    if isinstance(message, str) and message:
        result["message"] = message
    if extras:
        result.update(compact_fields(extras, tuple(extras)))
    return result
