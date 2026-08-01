#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$PROJECT_DIR"
UV_BIN="${UV_BIN:-uv}"
# Only clean the process recorded by this launcher, never every project server.
PROJECT_KEY="${PROJECT_DIR//\//_}"
PID_FILE="${TMPDIR:-/tmp}/openlist-mcp-${PROJECT_KEY}.pid"


find_server_pids() {
    local pid launcher_pid command

    [[ -f "$PID_FILE" ]] || return 0
    if ! IFS=' ' read -r pid launcher_pid < "$PID_FILE"; then
        return 0
    fi
    [[ "$pid" =~ ^[0-9]+$ && "$launcher_pid" =~ ^[0-9]+$ ]] || return 0
    [[ "$pid" != "$$" ]] || return 0
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command" == *"$PROJECT_DIR"* && "$command" == *"openlist-mcp"* ]]; then
        printf '%s\n' "$pid"
    fi
}

cleanup_stale_processes() {
    local stale_pids pid
    local pids=()
    local remaining=()

    stale_pids="$(find_server_pids)"
    [[ -z "$stale_pids" ]] && return 0

    while IFS= read -r pid; do
        [[ -n "$pid" ]] && pids+=("$pid")
    done <<< "$stale_pids"

    printf '[start] 清理残留 OpenList MCP 进程: %s\n' "${pids[*]}"
    kill -TERM "${pids[@]}" 2>/dev/null || true

    for _ in {1..20}; do
        remaining=()
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                remaining+=("$pid")
            fi
        done
        [[ "${#remaining[@]}" -eq 0 ]] && return 0
        sleep 0.1
    done

    printf '[start] 强制结束未退出进程: %s\n' "${remaining[*]}" >&2
    kill -KILL "${remaining[@]}" 2>/dev/null || true
}

clear_pid_file() {
    local pid launcher_pid

    [[ -f "$PID_FILE" ]] || return 0
    if ! IFS=' ' read -r pid launcher_pid < "$PID_FILE"; then
        return 0
    fi
    if [[ "$launcher_pid" == "$$" ]]; then
        : > "$PID_FILE"
    fi
    return 0
}


on_exit() {
    local status=$?
    trap - EXIT
    cleanup_stale_processes
    clear_pid_file

    exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! command -v "$UV_BIN" >/dev/null 2>&1; then
    printf '错误: 找不到 uv，请先安装 uv 或设置 UV_BIN。\n' >&2
    exit 127
fi

cleanup_stale_processes

uv_args=(run --project "$PROJECT_DIR")
if [[ -f "$PROJECT_DIR/.env" ]]; then
    uv_args+=(--env-file "$PROJECT_DIR/.env")
fi

printf '[start] 前台启动 OpenList MCP Server，按 Ctrl-C 退出\n'
/bin/sh -c '
    pid_file=$1
    launcher_pid=$2
    shift 2
    printf "%s %s\n" "$$" "$launcher_pid" > "$pid_file"
    exec "$@"
' openlist-mcp-launcher "$PID_FILE" "$$" "$UV_BIN" "${uv_args[@]}" openlist-mcp
