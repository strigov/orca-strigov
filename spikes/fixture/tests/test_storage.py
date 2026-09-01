import json
from pathlib import Path

import pytest

import todo


def test_storage_path_uses_default_without_environment(monkeypatch):
    monkeypatch.delenv("TODO_FILE", raising=False)

    assert todo._storage_path() == Path(todo.__file__).resolve().with_name("todo.json")


def test_storage_path_expands_nonempty_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TODO_FILE", "~/nested/todo.json")
    expected = tmp_path / "nested" / "todo.json"

    assert todo._storage_path() == expected
    assert not expected.exists()


def test_load_items_returns_empty_for_missing_empty_whitespace_and_invalid_files(tmp_path):
    path = tmp_path / "todo.json"

    assert todo._load_items(path) == []

    invalid_contents = [
        "",
        " \t\n",
        "{",
        "{}",
        "null",
        '"text"',
        '["item"]',
        '[{"id": 1, "text": "x"}]',
        '[{"id": 1, "text": "x", "done": false, "extra": true}]',
        '[{"id": true, "text": "x", "done": false}]',
        '[{"id": 1, "text": 2, "done": false}]',
        '[{"id": 1, "text": "x", "done": 0}]',
    ]
    for content in invalid_contents:
        path.write_text(content, encoding="utf-8")
        assert todo._load_items(path) == []


def test_save_and_load_items_round_trip_utf8_json(tmp_path):
    path = tmp_path / "todo.json"
    items = [{"id": 1, "text": "купить чай", "done": False}]

    todo._save_items(path, items)

    assert json.loads(path.read_text(encoding="utf-8")) == items
    assert todo._load_items(path) == items
    assert "купить чай" in path.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [path]


def test_save_items_keeps_target_and_cleans_temp_when_replace_fails(monkeypatch, tmp_path):
    path = tmp_path / "todo.json"
    old_bytes = b'[{"id": 1, "text": "old", "done": false}]'
    path.write_bytes(old_bytes)
    new_items = [{"id": 2, "text": "новый", "done": False}]
    replace_observation = {}

    def fail_replace(source, target):
        source_path = Path(source)
        replace_observation["source"] = source_path
        replace_observation["target"] = Path(target)
        replace_observation["source_exists"] = source_path.exists()
        replace_observation["source_bytes"] = source_path.read_bytes()
        raise OSError("replace failed")

    monkeypatch.setattr(todo.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        todo._save_items(path, new_items)

    assert replace_observation["source"] != path
    assert replace_observation["source"].parent == path.parent
    assert replace_observation["target"] == path
    assert replace_observation["source_exists"] is True
    assert json.loads(replace_observation["source_bytes"]) == new_items
    assert path.read_bytes() == old_bytes
    assert not replace_observation["source"].exists()
    assert list(tmp_path.iterdir()) == [path]
