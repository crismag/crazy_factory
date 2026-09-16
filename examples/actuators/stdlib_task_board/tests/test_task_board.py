"""Tests for the stdlib task-board model and persistence."""

from __future__ import annotations

from pathlib import Path

from src.task_board import (
    add_task,
    complete_task,
    delete_task,
    edit_task,
    load_tasks,
    save_tasks,
)


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    add_task("Buy milk", path)
    loaded = load_tasks(path)
    assert loaded[0]["title"] == "Buy milk"
    save_tasks(loaded, path)
    again = load_tasks(path)
    assert again[0]["title"] == "Buy milk"
    assert again[0]["id"] == loaded[0]["id"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_tasks(tmp_path / "missing.json") == []


def test_corrupt_json_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_tasks(path) == []


def test_edit_complete_delete(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    task = add_task("Draft", path)
    edited = edit_task(task["id"], "Ship it", path)
    assert edited is not None
    assert edited["title"] == "Ship it"
    complete_task(task["id"], path)
    assert load_tasks(path)[0]["done"] is True
    assert delete_task(task["id"], path) is True
    assert load_tasks(path) == []
