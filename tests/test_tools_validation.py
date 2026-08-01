"""Tests for tool input validation helpers."""

import pytest

from openlist_mcp.tools import (
    action_result,
    collect_task_ids,
    compact_fields,
    compact_file_entry,
    compact_json,
    compact_user,
    first_present,
    list_value,
    normalize_names,
    validate_name,
    validate_pagination,
    validate_path,
)


class TestValidatePath:
    def test_accepts_openlist_paths(self) -> None:
        for path in ["/", "/downloads", "/foo/bar", "relative/path", "backup..2024.tar.gz"]:
            validate_path(path)

    def test_rejects_unsafe_path_components(self) -> None:
        for path in ["", "/foo/../bar", "/foo/./bar", "/foo//bar", "/..", "../foo"]:
            with pytest.raises(ValueError):
                validate_path(path)


class TestValidateName:
    def test_accepts_filename_only_values(self) -> None:
        for name in ["file.txt", "backup..2024.tar.gz", "..hidden_file"]:
            validate_name(name)

    def test_rejects_paths_and_special_names(self) -> None:
        for name in ["", ".", "..", "dir/file.txt", r"dir\file.txt"]:
            with pytest.raises(ValueError):
                validate_name(name)

    def test_normalize_names_validates_each_item(self) -> None:
        assert normalize_names("a.txt, b.txt") == ["a.txt", "b.txt"]
        with pytest.raises(ValueError):
            normalize_names(["a.txt", "../b.txt"])


class TestValidatePagination:
    def test_accepts_valid_pagination(self) -> None:
        validate_pagination(1, 200)

    def test_rejects_invalid_pagination(self) -> None:
        for page, per_page in [(0, 50), (1, 0), (1, 201)]:
            with pytest.raises(ValueError):
                validate_pagination(page, per_page)


def test_compact_json_and_fields_preserve_zero_values() -> None:
    assert (
        compact_json({"text": "x", "zero": 0, "false": False})
        == '{"text":"x","zero":0,"false":false}'
    )
    assert compact_fields(
        {"empty": "", "none": None, "list": [], "obj": {}, "zero": 0, "false": False},
        ("empty", "none", "list", "obj", "zero", "false"),
    ) == {"zero": 0, "false": False}


def test_response_alias_and_list_helpers_are_ordered() -> None:
    assert (
        first_present({"first": "", "second": 0, "third": "x"}, ("first", "second", "third")) == 0
    )
    assert list_value({"first": "not-list", "second": [1, 2]}, ("first", "second")) == [1, 2]
    assert list_value([3], ("value",)) == [3]
    assert list_value({"value": {"not": "a list"}}, ("value",)) == []


def test_collect_task_ids_stably_deduplicates_known_containers() -> None:
    payload = {
        "id": 1,
        "task": {"tid": "2", "data": {"task_id": 1}},
        "tasks": [{"id": "3"}, {"id": "2"}],
        "unknown": {"id": "secret-not-task"},
    }
    assert collect_task_ids(payload) == ["1", "2", "3"]


def test_compact_file_and_user_helpers_drop_unknown_fields() -> None:
    assert compact_file_entry(
        {
            "name": "report.txt",
            "type": 1,
            "size": "100",
            "thumb": "secret",
            "hashinfo": "secret",
        }
    ) == {"name": "report.txt", "is_dir": True, "size": 0}
    assert compact_file_entry({"name": "", "size": 1}) is None
    assert compact_user(
        {
            "id": 7,
            "name": "alice",
            "role": 2,
            "base_path": "/home",
            "disabled": False,
            "two_factor": True,
            "password": "secret",
            "permissions": 65535,
        }
    ) == {
        "id": 7,
        "username": "alice",
        "role": 2,
        "base_path": "/home",
        "disabled": False,
        "two_factor_enabled": True,
    }


def test_action_result_keeps_only_allowed_summary_fields() -> None:
    assert action_result(
        {"task": {"id": "t1"}, "message": "submitted", "token": "secret"},
        "copy",
        extras={"affected": 0, "empty": ""},
    ) == {
        "ok": True,
        "operation": "copy",
        "task_ids": ["t1"],
        "message": "submitted",
        "affected": 0,
    }
