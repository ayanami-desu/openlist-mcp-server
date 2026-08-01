"""System administration tools for OpenList MCP Server.

Provides read-only (storage, driver, setting, index, user, meta) and
write (index build, setting save, etc.) tools for server administration.
All destructive write operations require confirm=true for safety.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from ..client import get_client
from . import (
    compact_fields,
    compact_json,
    compact_user,
    enforce_writable,
    first_present,
    list_value,
    validate_pagination,
)


def _compact_storage(data: Mapping[str, Any], *, include_details: bool = False) -> dict[str, Any]:
    """Project storage metadata without provider configuration details."""
    result: dict[str, Any] = {}
    for output, fields in (
        ("id", ("id",)),
        ("mount_path", ("mount_path",)),
        ("driver", ("driver",)),
        ("status", ("status",)),
        ("enabled", ("enabled", "enable")),
        ("total", ("total",)),
        ("free", ("free",)),
    ):
        value = first_present(data, fields)
        if value is not None:
            result[output] = value
    if include_details:
        for field in ("remark", "description"):
            value = first_present(data, (field,))
            if value is not None:
                result[field] = value
    return result


def _compact_meta(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project directory metadata while exposing only sensitive-field state."""
    result: dict[str, Any] = {}
    for field in ("id", "path", "enabled", "write", "hide"):
        value = first_present(data, (field,))
        if value is not None:
            result[field] = value
    password_protected = False
    for field in ("password_protected", "has_password", "pwd"):
        if field in data:
            password_protected = bool(data[field])
            break
    result["password_protected"] = password_protected
    result["readme_present"] = bool(data.get("readme"))
    result["header_present"] = bool(data.get("header"))
    return result


def register_admin_tools(mcp: FastMCP) -> None:
    """Register system administration MCP tools."""

    # ─────────────────────────── Storage (read-only) ───────────────────────────

    @mcp.tool()
    async def list_storages() -> str:
        """List all configured storage backends on the OpenList server.

        Returns details about each storage including mount path, driver type,
        status, total space, and free space. Read-only — no modification.

        Returns:
            JSON string with a storages array containing id, mount_path, driver,
            status, enabled, total, and free.
        """
        client = await get_client()
        data = await client.request("GET", "admin/storage/list")
        items = list_value(data, ("value", "storages", "content"))
        storages = [_compact_storage(item) for item in items if isinstance(item, Mapping)]
        return compact_json({"storages": storages})

    @mcp.tool()
    async def get_storage_info(storage_id: int) -> str:
        """Get detailed information about a specific storage backend.

        Args:
            storage_id: The numeric ID of the storage to query. Use list_storages
                       to see available IDs.

        Returns:
            JSON string with compact storage details and optional remark/description.
        """
        client = await get_client()
        data = await client.request("GET", "admin/storage/get", params={"id": storage_id})
        return compact_json(
            _compact_storage(data, include_details=True) if isinstance(data, Mapping) else {}
        )

    # ─────────────────────────── Driver (read-only) ────────────────────────────

    @mcp.tool()
    async def list_drivers() -> str:
        """List all registered storage driver names on the server.

        Shows what storage backend types are available (Local, S3, OneDrive,
        **************, etc.).

        Returns:
            JSON object with the stable, de-duplicated driver names.
        """
        client = await get_client()
        data = await client.request("GET", "admin/driver/names")
        drivers: list[str] = []
        seen: set[str] = set()
        items = list_value(data, ("drivers", "value", "content"))
        if not items and isinstance(data, Mapping) and isinstance(data.get("name"), str):
            items = [data]
        for item in items:
            name = (
                item
                if isinstance(item, str)
                else item.get("name")
                if isinstance(item, Mapping)
                else None
            )
            if isinstance(name, str) and name.strip() and name not in seen:
                seen.add(name)
                drivers.append(name)
        return compact_json({"drivers": drivers})

    @mcp.tool()
    async def get_driver_info(driver: str) -> str:
        """Get detailed information about a specific storage driver.

        Shows the driver's configuration fields and their types.

        Args:
            driver: Driver name (e.g. "Local", "S3", "189PC"). Use list_drivers
                   to see available names.

        Returns:
            JSON string with driver info.
        """
        client = await get_client()
        data = await client.request("GET", "admin/driver/info", params={"driver": driver})
        return compact_json(data)

    @mcp.tool()
    async def list_drivers_detail() -> str:
        """List all storage drivers with full configuration templates.

        Unlike list_drivers (which only returns driver names), this endpoint
        returns detailed configuration fields and their types for every
        registered driver. Useful when creating or updating storage backends.

        Returns:
            JSON array of drivers with their configuration templates.
        """
        client = await get_client()
        data = await client.request("GET", "admin/driver/list")
        return compact_json(data)

    # ─────────────────────────── Settings (read + write) ───────────────────────

    @mcp.tool()
    async def get_settings() -> str:
        """List all global settings on the OpenList server.

        Returns all configuration key-value pairs including site title,
        pagination settings, preview options, etc. Read-only.

        Returns:
            JSON object with sorted setting keys and their total count.
        """
        client = await get_client()
        data = await client.request("GET", "admin/setting/list")
        list_container: list[Any] | None = None
        mapping_container: Mapping[str, Any] | None = None
        if isinstance(data, Mapping):
            for field in ("value", "content"):
                candidate = data.get(field)
                if isinstance(candidate, list):
                    list_container = candidate
                    break
                if mapping_container is None and isinstance(candidate, Mapping):
                    mapping_container = candidate
        if list_container is not None:
            keys = [
                item["key"]
                for item in list_container
                if isinstance(item, Mapping)
                and isinstance(item.get("key"), str)
                and item["key"].strip()
            ]
        else:
            source = mapping_container if mapping_container is not None else data
            keys = (
                [key for key in source if isinstance(key, str) and key.strip()]
                if isinstance(source, Mapping)
                else []
            )
        keys = sorted(set(keys))
        return compact_json({"keys": keys, "total": len(keys)})

    @mcp.tool()
    async def get_setting(key: str) -> str:
        """Get a single global setting by its key.

        Args:
            key: The setting key (e.g. "site_title", "pagination_type",
                "logo", "favicon"). Use get_settings to see all keys.

        Returns:
            Compact JSON with the setting response.
        """
        client = await get_client()
        data = await client.request("GET", "admin/setting/get", params={"key": key})
        return compact_json(data)

    @mcp.tool()
    async def save_settings(
        settings: list[dict],
        confirm: bool = False,
    ) -> str:
        """Update one or more global system settings.

        Provide settings as a list of objects with "key" and "value" fields.
        All settings are saved atomically in a single request.

        Examples:
          - Set site title:  [{"key": "site_title", "value": "My Cloud"}]
          - Change pagination: [{"key": "pagination_type", "value": "0"}]

        Args:
            settings: List of {"key": "...", "value": "..."} objects to update.
            confirm: Must be true to actually save. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return "⚠️ Settings save not performed. Re-run with confirm=true to save these settings."
        if not settings:
            return "No settings provided to save."
        enforce_writable("save_settings")
        client = await get_client()
        await client.request("POST", "admin/setting/save", json=settings)
        return f"Settings saved successfully ({len(settings)} key(s))."

    @mcp.tool()
    async def delete_setting(
        key: str,
        confirm: bool = False,
    ) -> str:
        """Delete a custom setting by its key.

        Removes a previously saved custom setting from the server.
        Built-in settings may not be deletable.

        Args:
            key: The setting key to delete (e.g. "custom_logo").
            confirm: Must be true to actually delete. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return (
                "⚠️ Setting deletion not performed. Re-run with confirm=true to delete this setting."
            )
        if not key:
            return "No setting key provided."
        enforce_writable("delete_setting")
        client = await get_client()
        await client.request("POST", "admin/setting/delete", json={"key": key})
        return f"Setting deleted successfully: {key}"

    # ─────────────────────────── Search Index ──────────────────────────────────

    @mcp.tool()
    async def get_index_progress() -> str:
        """Get the current search index building progress.

        Useful for determining whether search results are up to date.

        Returns:
            JSON object containing only status, progress, total, completed, and error.
        """
        client = await get_client()
        data = await client.request("GET", "admin/index/progress")
        return compact_json(
            compact_fields(data, ("status", "progress", "total", "completed", "error"))
        )

    @mcp.tool()
    async def build_search_index(confirm: bool = False) -> str:
        """Build the full-text search index for all storages.

        This scans all mounted storage backends and rebuilds the search index
        from scratch. May take a long time on large deployments. Use
        get_index_progress to monitor progress.

        Args:
            confirm: Must be true to actually build. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return (
                "Search index build not performed. "
                "⚠️ Re-run with confirm=true to build the search index."
            )
        enforce_writable("build_search_index")
        client = await get_client()
        await client.request("POST", "admin/index/build")
        return "Search index build started. Use get_index_progress to monitor."

    @mcp.tool()
    async def update_search_index(
        paths: list[str] | None = None,
        confirm: bool = False,
    ) -> str:
        """Update the search index for specific paths.

        Unlike a full rebuild, this incrementally updates the index for
        the specified paths only. Faster than a full rebuild when only
        certain directories have changed.

        Args:
            paths: List of directory paths to re-index. If omitted or empty,
                   the server may update all paths.
            confirm: Must be true to actually update. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return (
                "Search index update not performed. "
                "⚠️ Re-run with confirm=true to update the search index."
            )
        enforce_writable("update_search_index")
        client = await get_client()
        body = {"paths": paths} if paths else {}
        await client.request("POST", "admin/index/update", json=body)
        return "Search index update started."

    @mcp.tool()
    async def stop_indexing(confirm: bool = False) -> str:
        """Stop the current search index building or updating operation.

        Useful when an indexing operation is taking too long or consuming
        too many server resources.

        Args:
            confirm: Must be true to actually stop. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return "⚠️ Indexing stop not performed. Re-run with confirm=true to stop indexing."
        enforce_writable("stop_indexing")
        client = await get_client()
        await client.request("POST", "admin/index/stop")
        return "Indexing operation stopped."

    @mcp.tool()
    async def clear_search_index(confirm: bool = False) -> str:
        """Delete all search index data.

        WARNING: This removes the entire search index. Searching will return
        no results until a new index is built via build_search_index.

        Args:
            confirm: Must be true to actually clear. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return (
                "Search index clear not performed. "
                "⚠️ Re-run with confirm=true to clear the search index."
            )
        enforce_writable("clear_search_index")
        client = await get_client()
        await client.request("POST", "admin/index/clear")
        return "Search index cleared. Use build_search_index to rebuild."

    # ─────────────────────────── User Management ───────────────────────────────

    @mcp.tool()
    async def list_users(
        page: int = 1,
        per_page: int = 30,
    ) -> str:
        """List all user accounts on the server (Admin only).

        Returns paginated list of users with their roles, permissions,
        and account status. Read-only — no modification.

        Args:
            page: Page number for pagination. Defaults to 1.
            per_page: Number of items per page. Defaults to 30.

        Returns:
            JSON string with page, per_page, total, and compact users.
        """
        validate_pagination(page, per_page, max_per_page=200)
        client = await get_client()
        data = await client.request(
            "GET",
            "admin/user/list",
            params={"page": page, "per_page": per_page},
        )
        items = list_value(data, ("value", "users", "content"))
        users = [compact_user(item) for item in items if isinstance(item, Mapping)]
        total = data.get("total") if isinstance(data, Mapping) else None
        if not isinstance(total, int) or isinstance(total, bool):
            total = len(users)
        return compact_json({"page": page, "per_page": per_page, "total": total, "users": users})

    @mcp.tool()
    async def get_user(user_id: int) -> str:
        """Get detailed information about a specific user (Admin only).

        Shows user details including username, role, permissions bitmap,
        base path, 2FA status, and whether the account is disabled.

        Args:
            user_id: The numeric ID of the user to query. Use list_users
                    to see available user IDs.

        Returns:
            JSON string with the compact user summary.
        """
        client = await get_client()
        data = await client.request("GET", "admin/user/get", params={"id": user_id})
        return compact_json(compact_user(data) if isinstance(data, Mapping) else {})

    # ─────────────────────────── Meta Management ───────────────────────────────

    @mcp.tool()
    async def list_metas() -> str:
        """List all metadata configurations on the server (Admin only).

        Returns only metadata identifiers, visibility flags, and boolean presence
        indicators for passwords, readme, and header content.

        Returns:
            JSON array wrapper containing compact metadata projections.
        """
        client = await get_client()
        data = await client.request("GET", "admin/meta/list")
        metas = [
            _compact_meta(item)
            for item in list_value(data, ("value", "metas", "content"))
            if isinstance(item, Mapping)
        ]
        return compact_json({"metas": metas})

    @mcp.tool()
    async def get_meta(meta_id: int) -> str:
        """Get a specific metadata configuration by its ID (Admin only).

        Args:
            meta_id: The numeric ID of the metadata to query. Use list_metas
                    to see available IDs.

        Returns:
            JSON string with the compact metadata projection.
        """
        client = await get_client()
        data = await client.request("GET", "admin/meta/get", params={"id": meta_id})
        return compact_json(_compact_meta(data) if isinstance(data, Mapping) else {})

    # ─────────────────────────── Token Management ──────────────────────────────

    @mcp.tool()
    async def reset_api_token(confirm: bool = False) -> str:
        """Reset the server API token (Admin only).

        Generates a new API token. The current token will be invalidated
        immediately. All active sessions using the old token will need to
        re-authenticate.

        Args:
            confirm: Must be true to actually reset. Defaults to false.

        Returns:
            Success message or confirmation-required message.
        """
        if not confirm:
            return (
                "⚠️ API token reset not performed. Re-run with confirm=true to reset the API token."
            )
        enforce_writable("reset_api_token")
        client = await get_client()
        await client.request("POST", "admin/setting/reset_token")
        return "API token reset successfully."
