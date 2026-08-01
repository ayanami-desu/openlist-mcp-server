"""Advanced file operation tools for OpenList MCP Server.

Includes offline download, archive decompression, and related utilities.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import posixpath
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver import MCPServer as FastMCP

from ..client import get_client
from ..config import get_config
from . import (
    _list_items,
    action_result,
    compact_file_entry,
    compact_json,
    compact_user,
    enforce_path_allowed,
    enforce_writable,
    first_present,
    list_value,
    normalize_names,
    validate_name,
    validate_path,
)

# Internal IP ranges that should be blocked for SSRF prevention.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# URL schemes allowed for offline download. Add new protocols here.
_SAFE_SCHEMES = {"http", "https", "magnet", "ftp", "sftp"}


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address string belongs to a private/internal network."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in network for network in _PRIVATE_NETWORKS)


def _reject_internal_url(url: str) -> None:
    """Reject URLs that resolve to internal/private IP addresses (SSRF prevention).

    Resolves the hostname to IP address(es) and raises ValueError if any
    resolved IP is in a private or loopback range.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {url}")

    # Direct IP check first (no DNS lookup needed)
    try:
        ipaddress.ip_address(host)
        if _is_private_ip(host):
            raise ValueError(
                f"URL points to a private/internal IP address ({host}), "
                "which is not allowed for security reasons."
            )
        # Public IP is fine, no need for DNS resolution
        return
    except ValueError:
        # Not a bare IP — resolve the hostname
        pass

    # DNS resolution for hostnames
    try:
        addrinfo = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(
            f"Cannot resolve hostname '{host}' for SSRF check: {exc}. "
            f"If this is a valid external host, try again or use a direct IP URL."
        ) from exc

    for info in addrinfo:
        ip_str = str(info[4][0])
        if _is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to a private/internal IP address ({ip_str}), "
                "which is not allowed for security reasons."
            )


def _stable_strings(data: object, fields: tuple[str, ...]) -> list[str]:
    values = list_value(data, fields)
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, str) and item.strip() and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _download_tool_names(data: object) -> list[str]:
    """Extract stable download-tool names from known response containers."""
    result: list[str] = []
    seen: set[str] = set()
    values = list_value(data, ("value", "data"))
    if (
        not values
        and isinstance(data, Mapping)
        and any(field in data for field in ("name", "tool", "id"))
    ):
        values = [data]
    for item in values:
        name = item if isinstance(item, str) else None
        if isinstance(item, Mapping):
            name = first_present(item, ("name", "tool", "id"))
        if isinstance(name, str) and name.strip() and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _compact_torrent(
    data: Mapping[str, Any],
    include_torrent_data: bool = False,
) -> dict[str, Any]:
    """Project torrent metadata and file paths without raw response fields."""
    info_value = data.get("info")
    info: Mapping[str, Any] = info_value if isinstance(info_value, Mapping) else {}

    def value(fields: tuple[str, ...]) -> Any:
        item = first_present(data, fields)
        return first_present(info, fields) if item is None else item

    result: dict[str, Any] = {}
    for output, fields in (
        ("name", ("name", "torrent_name")),
        ("info_hash", ("info_hash", "infohash")),
        ("total_size", ("total_size", "size")),
    ):
        item = value(fields)
        if item is not None:
            result[output] = item

    files = list_value(data, ("files", "content", "value"))
    if not files and isinstance(info, Mapping):
        files = list_value(info, ("files", "content", "value"))
    compact_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, Mapping):
            continue
        path = first_present(item, ("path", "name"))
        if not isinstance(path, str) or not path.strip():
            continue
        size = item.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool):
            size = 0
        compact_files.append({"path": path, "size": size})
    result["files"] = compact_files
    torrent_data = data.get("torrent_data")
    if include_torrent_data and isinstance(torrent_data, str) and torrent_data:
        result["torrent_data"] = torrent_data
    return result


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register advanced file operation MCP tools."""

    @mcp.tool()
    async def get_capabilities() -> str:
        """Summarize this MCP server's OpenList capabilities and safety settings.

        Returns:
            JSON string with authentication, features, and MCP safety summaries.
        """
        config = get_config()
        client = await get_client()
        download_tools: list[str] = []
        try:
            download_tools_data = await client.request(
                "GET",
                "public/offline_download_tools",
                require_auth=False,
            )
            download_tools = _download_tool_names(download_tools_data)
        except Exception:
            pass

        capabilities = {
            "authentication": {
                "credentials_configured": config.is_authenticated,
                "totp_secret_configured": config.has_totp_secret,
            },
            "features": {
                "file_browse": True,
                "file_manage": True,
                "file_transfer": True,
                "shares": True,
                "tasks": True,
                "offline_download_tools": download_tools,
                "archive_decompress": True,
            },
            "mcp_safety": {
                "high_impact_operations_require_confirm": True,
                "read_only": config.read_only,
                "allowed_paths": config.allowed_paths,
                "local_upload_roots_configured": bool(
                    os.environ.get("OPENLIST_LOCAL_UPLOAD_ROOTS", "")
                ),
            },
        }
        return compact_json(capabilities)

    @mcp.tool()
    async def offline_download(
        url: str,
        path: str = "/",
        tool: str = "aria2",
        delete_policy: str = "",
    ) -> str:
        """Download a file from a remote URL directly to the OpenList server.

        The server fetches the file in the background. Use get_task_info with the
        returned task ID to monitor progress.

        Available download tools on the server can be queried via `list_download_tools`.
        Common options include: "aria2" (supports http/https/magnet/torrent),
        "qbittorrent" (BitTorrent/HTTP), "transmission" (BitTorrent/HTTP).

        Args:
            url: Remote URL to download from.
            path: Destination directory on OpenList (e.g. "/downloads"). Defaults to root.
            tool: Download tool name. Defaults to "aria2". Use `list_download_tools`
                  to see what's available on this server.
            delete_policy: Optional delete policy for completed tasks.

        Returns:
            Compact action JSON with operation, task_type, task_ids, and message.
        """
        enforce_path_allowed(path)
        enforce_writable("offline_download")

        # SSRF prevention: only allow http/https/magnet URLs
        parsed = urlparse(url)
        if parsed.scheme not in _SAFE_SCHEMES:
            raise ValueError(
                f"Unsupported URL scheme '{parsed.scheme}'. "
                "Only http, https, magnet, ftp, and sftp URLs are allowed for offline download."
            )

        # SSRF prevention: reject URLs pointing to internal/private networks
        # Magnet links have no hostname and can't be used for SSRF, skip check
        if parsed.scheme != "magnet":
            _reject_internal_url(url)

        client = await get_client()
        body: dict[str, Any] = {"urls": [url], "path": path}
        if tool:
            body["tool"] = tool
        if delete_policy:
            body["delete_policy"] = delete_policy
        data = await client.request("POST", "fs/add_offline_download", json=body)
        return compact_json(action_result(data, "offline_download", task_type="offline_download"))

    @mcp.tool()
    async def batch_download(
        urls: list[str],
        path: str = "/",
        tool: str = "aria2",
        delete_policy: str = "",
    ) -> str:
        """Download multiple files from remote URLs at once.

        Each URL is added as a separate offline download task. Use
        `list_tasks` or `get_task_info` to monitor progress.

        Args:
            urls: List of remote URLs to download.
            path: Destination directory on OpenList (e.g. "/downloads").
            tool: Download tool name. Defaults to "aria2".
            delete_policy: Optional delete policy for completed tasks.

        Returns:
            JSON array with one compact result per URL.
        """
        enforce_path_allowed(path)
        enforce_writable("batch_download")

        if not urls:
            return compact_json([])

        # SSRF check for each URL
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme not in _SAFE_SCHEMES:
                raise ValueError(
                    f"Unsupported URL scheme '{parsed.scheme}' in '{url}'. "
                    "Only http, https, magnet, ftp, and sftp URLs are allowed."
                )
            if parsed.scheme != "magnet":
                _reject_internal_url(url)

        client = await get_client()
        results: list[dict[str, Any]] = []
        for url in urls:
            try:
                body: dict[str, Any] = {"urls": [url], "path": path}
                if tool:
                    body["tool"] = tool
                if delete_policy:
                    body["delete_policy"] = delete_policy
                data = await client.request("POST", "fs/add_offline_download", json=body)
                summary = action_result(data, "offline_download", task_type="offline_download")
                entry: dict[str, Any] = {"url": url, "ok": True}
                for field in ("task_ids", "message"):
                    if field in summary:
                        entry[field] = summary[field]
                results.append(entry)
            except Exception as exc:
                results.append({"url": url, "ok": False, "error": str(exc)})

        return compact_json(results)

    @mcp.tool()
    async def find_duplicates(
        path: str = "/",
        by: str = "name_size",
        password: str = "",
    ) -> str:
        """Find potentially duplicate files in a directory tree.

        Groups files by name+size (default) or by size only, and returns
        groups with more than one member as potential duplicates.

        Args:
            path: Directory to search. Defaults to "/".
            by: Grouping criteria: "name_size" (default) or "size_only".
            password: Password if the path is password-protected.

        Returns:
            JSON string with grouped potential duplicates.
        """
        client = await get_client()
        groups: dict[str, list[dict]] = {}
        seen = set()

        async def _walk(dir_path: str, depth: int = 0) -> None:
            if depth > 8:
                return
            if dir_path in seen:
                return
            seen.add(dir_path)

            items = await _list_items(client, dir_path, password)
            if not items:
                return

            for item in items:
                if not isinstance(item, Mapping):
                    continue
                compact = compact_file_entry(item)
                if compact is None:
                    continue
                name = compact["name"]
                size = compact["size"]
                is_dir = compact["is_dir"]

                if is_dir:
                    sub_path = f"{dir_path.rstrip('/')}/{name}"
                    await _walk(sub_path, depth + 1)
                else:
                    # Build group key
                    key = f"size:{size}" if by == "size_only" else f"{name}:{size}"

                    entry = {"path": f"{dir_path.rstrip('/')}/{name}", "size": size}
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(entry)

        await _walk(path)

        # Filter groups with more than one entry
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        result = {
            "path": path,
            "group_by": by,
            "total_duplicate_groups": len(duplicates),
            "total_duplicate_files": sum(len(v) for v in duplicates.values()),
            "duplicates": [
                {
                    "size": v[0]["size"],
                    "files": [entry["path"] for entry in v],
                }
                for v in sorted(duplicates.values(), key=lambda entries: -len(entries))
            ],
        }
        return compact_json(result)

    @mcp.tool()
    async def content_preview(
        path: str,
        max_chars: int = 5000,
        password: str = "",
    ) -> str:
        """Preview the first portion of a text file's content.

        Useful for quickly inspecting log files, CSV data, source code,
        configuration files, or other text-based files without downloading
        the entire file. Fetches the raw content via download URL.

        For binary files or very large files, the preview may be truncated.

        Args:
            path: Full path to the file to preview.
            max_chars: Maximum number of characters to return. Defaults to 5000.
            password: Password if the path is password-protected.

        Returns:
            JSON object with path, content, truncated, and optional language.
        """
        enforce_path_allowed(path)
        client = await get_client()

        # Get the file info to find raw_url
        data = await client.request(
            "POST",
            "fs/get",
            json={"path": path, "password": password},
        )
        raw_url = data.get("raw_url", "") if isinstance(data, dict) else ""

        if not raw_url:
            return compact_json({"ok": False, "error": "No download URL available for this file."})

        # Fetch with range to limit bytes

        try:
            async with httpx.AsyncClient(timeout=15) as hc:
                resp = await hc.get(raw_url, headers={"Range": f"bytes=0-{max_chars * 2}"})
                content_bytes = resp.content
        except Exception as e:
            return compact_json({"ok": False, "error": f"Failed to fetch content: {e}"})

        # Try to decode as text
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1")
            except Exception:
                return compact_json(
                    {"ok": False, "error": "File is binary — cannot preview as text."}
                )

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        # Wrap in a code block for readability
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        lang_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "html": "html",
            "css": "css",
            "json": "json",
            "xml": "xml",
            "yaml": "yaml",
            "yml": "yaml",
            "md": "markdown",
            "sh": "bash",
            "bash": "bash",
            "csv": "csv",
            "txt": "text",
        }
        lang = lang_map.get(ext, "")

        result: dict[str, Any] = {
            "path": path,
            "content": text,
            "truncated": truncated,
        }
        if lang:
            result["language"] = lang
        return compact_json(result)

    @mcp.tool()
    async def get_archive_extensions() -> str:
        """Get the list of archive file extensions supported by the server.

        Helps determine which archive formats can be decompressed (zip, rar,
        7z, tar.gz, etc.).

        Returns:
            JSON object with the supported extension names.
        """
        client = await get_client()
        data = await client.request("GET", "public/archive_extensions", require_auth=False)
        return compact_json(
            {"extensions": _stable_strings(data, ("extensions", "value", "content", "data"))}
        )

    @mcp.tool()
    async def get_archive_meta(
        path: str,
        archive_pass: str = "",
        refresh: bool = False,
    ) -> str:
        """Get metadata of an archive file without extracting it.

        Returns format, encryption status, size, and modification time only.

        Args:
            path: Full path to the archive file (e.g. "/downloads/data.zip").
            archive_pass: Optional password for encrypted archives.
            refresh: Whether to refresh archive cache.

        Returns:
            JSON object containing path and optional archive metadata fields.
        """
        enforce_path_allowed(path)

        client = await get_client()
        body: dict[str, Any] = {
            "path": path,
            "refresh": refresh,
        }
        if archive_pass:
            body["archive_pass"] = archive_pass

        data = await client.request("POST", "fs/archive/meta", json=body)
        result: dict[str, Any] = {"path": path}
        for output, fields in (
            ("format", ("format", "type")),
            ("encrypted", ("encrypted", "is_encrypted")),
            ("size", ("size",)),
            ("modified", ("modified",)),
        ):
            value = first_present(data, fields) if isinstance(data, Mapping) else None
            if value is not None:
                result[output] = value
        return compact_json(result)

    @mcp.tool()
    async def decompress_archive(
        src_dir: str,
        names: list[str] | str,
        dst_dir: str = "",
        archive_pass: str = "",
        overwrite: bool = False,
        put_into_new_dir: bool = False,
    ) -> str:
        """Decompress an archive file (zip, rar, 7z, tar.gz, etc.) on the OpenList server.

        The archive file must already exist on the server.

        Args:
            src_dir: Directory containing the archive file(s) (e.g. "/downloads").
            names: List of archive filenames or comma-separated string to decompress
                   (e.g. ["data.zip", "backup.7z"] or "data.zip,backup.7z").
            dst_dir: Optional extraction target directory. Defaults to same as src_dir.
            archive_pass: Optional password for encrypted archives.
            overwrite: Whether to overwrite existing files. Defaults to false.
            put_into_new_dir: Whether to place extracted files in a new directory named after the archive. Defaults to false.

        Returns:
            Compact action JSON with operation, task_type, task_ids, and message.
        """
        enforce_path_allowed(src_dir)
        enforce_writable("decompress_archive")
        name_list = normalize_names(names)
        if not name_list:
            return compact_json({"ok": False, "error": "No archive files specified."})

        client = await get_client()
        body: dict[str, Any] = {
            "src_dir": src_dir,
            "name": name_list,
            "overwrite": overwrite,
            "put_into_new_dir": put_into_new_dir,
        }
        if dst_dir:
            enforce_path_allowed(dst_dir)
            body["dst_dir"] = dst_dir
        if archive_pass:
            body["archive_pass"] = archive_pass
        data = await client.request("POST", "fs/archive/decompress", json=body)
        return compact_json(action_result(data, "decompress", task_type="decompress"))

    @mcp.tool()
    async def list_archive_files(
        src_dir: str,
        name: str,
        inner_path: str = "/",
        archive_pass: str = "",
        refresh: bool = False,
    ) -> str:
        """List files inside an archive without extracting it.

        Args:
            src_dir: Directory containing the archive file.
            name: Archive filename, not a full path.
            inner_path: Inner archive directory to list. Defaults to "/".
            archive_pass: Optional password for encrypted archives.
            refresh: Whether to refresh archive cache when supported by OpenList.

        Returns:
            JSON object with archive, inner_path, and compact entries.
        """
        enforce_path_allowed(src_dir)
        validate_name(name)
        validate_path(inner_path)
        archive_path = posixpath.join(src_dir.rstrip("/") or "/", name)
        client = await get_client()
        body: dict[str, Any] = {
            "path": archive_path,
            "inner_path": inner_path,
            "refresh": refresh,
        }
        if archive_pass:
            body["archive_pass"] = archive_pass

        data = await client.request("POST", "fs/archive/list", json=body)
        entries = []
        for item in list_value(data, ("content", "value")):
            if isinstance(item, Mapping):
                entry = compact_file_entry(item)
                if entry is not None:
                    entries.append(entry)
        return compact_json({"archive": archive_path, "inner_path": inner_path, "entries": entries})

    @mcp.tool()
    async def get_me() -> str:
        """Get the current authenticated user's profile information.

        Returns:
            JSON string with the compact user summary.
        """
        client = await get_client()
        data = await client.request("GET", "me")
        return compact_json(compact_user(data) if isinstance(data, Mapping) else {})

    @mcp.tool()
    async def logout() -> str:
        """Logout from the OpenList server and invalidate the current token.

        After logout, the next API call will trigger automatic re-login
        using configured credentials.
        """
        client = await get_client()
        await client.request("GET", "auth/logout")
        # Clear the cached token via the public method
        client.clear_token()
        return "Logged out successfully. Token invalidated."

    @mcp.tool()
    async def list_download_tools() -> str:
        """List available offline download tools configured on this OpenList server.

        The result depends on which download tools (aria2, Transmission, qBittorrent, etc.)
        are installed and configured on the OpenList server. Only tools that are
        properly set up will appear in the list.

        Returns:
            JSON object with a tools array of available tool names.
        """
        client = await get_client()
        data = await client.request("GET", "public/offline_download_tools", require_auth=False)
        return compact_json({"tools": _download_tool_names(data)})

    @mcp.tool()
    async def parse_torrent(
        torrent_data: str,
    ) -> str:
        """Parse a torrent file and return compact metadata and file paths.

        Provide the torrent file content as a base64-encoded string.

        Args:
            torrent_data: Base64-encoded content of the .torrent file.

        Returns:
            JSON string with compact torrent name, hash, size, and files.
        """
        client = await get_client()
        data = await client.request(
            "POST",
            "fs/torrent/parse",
            json={"torrent_data": torrent_data},
        )
        return compact_json(_compact_torrent(data))

    @mcp.tool()
    async def torrent_upload_parse(
        torrent_data: str,
        include_torrent_data: bool = False,
    ) -> str:
        """Upload and parse a torrent file via multipart form.

        Unlike parse_torrent (which sends base64 in JSON body), this sends the
        torrent file as a multipart form upload. The parsed metadata is compacted;
        the returned base64 copy is included only when include_torrent_data is true.

        Args:
            torrent_data: Base64-encoded content of the .torrent file.
            include_torrent_data: Include the returned base64 only when true.

        Returns:
            JSON string with compact torrent info; torrent_data is omitted by default.
        """

        client = await get_client()
        raw_bytes = base64.b64decode(torrent_data)
        data = await client.multipart_form(
            "fs/torrent/upload_parse",
            field_name="torrent",
            file_bytes=raw_bytes,
            file_name="file.torrent",
            content_type="application/x-bittorrent",
        )
        return compact_json(_compact_torrent(data, include_torrent_data))

    @mcp.tool()
    async def generate_torrent(
        path: str,
    ) -> str:
        """Generate a .torrent file for an existing file on the OpenList server.

        Creates a BitTorrent metainfo file that can be used to share the file
        via BitTorrent. The generated torrent is stored alongside the original file.

        Args:
            path: Full path to the file on OpenList (e.g. "/downloads/myfile.iso").

        Returns:
            Compact action JSON with operation, task IDs, message, and optional path.
        """
        enforce_path_allowed(path)
        enforce_writable("generate_torrent")
        client = await get_client()
        data = await client.request(
            "POST",
            "fs/torrent/generate",
            json={"path": path},
        )
        output_path = (
            first_present(data, ("path", "torrent_path")) if isinstance(data, Mapping) else None
        )
        extras = {"path": output_path} if output_path is not None else None
        return compact_json(action_result(data, "generate_torrent", extras=extras))

    @mcp.tool()
    async def torrent_rapid_upload(
        torrent_data: str,
        path: str = "/",
    ) -> str:
        """Rapid upload (server-side import) from a torrent file.

        If the storage backend supports CAS (Content Addressable Storage)
        and already has the files referenced in the torrent, this can complete
        instantly without downloading. This feature depends on the storage
        driver — local storage typically does not support CAS.

        Falls back to a normal message if CAS is not available on the backend.

        Args:
            torrent_data: Base64-encoded content of the .torrent file.
            path: Destination directory path on OpenList (e.g. "/downloads").

        Returns:
            Compact action JSON with operation, task IDs, and an optional message.
        """
        enforce_writable("torrent_rapid_upload")
        enforce_path_allowed(path)
        client = await get_client()
        data = await client.request(
            "POST",
            "fs/torrent/rapid_upload",
            json={"torrent_data": torrent_data, "path": path},
        )
        return compact_json(action_result(data, "torrent_rapid_upload"))
