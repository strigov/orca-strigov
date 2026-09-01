import json
import os
from pathlib import Path
import subprocess
import sys

import todo
import todo_export


def _run_export(storage_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TODO_FILE"] = str(storage_path)
    return subprocess.run(
        [sys.executable, str(Path(todo_export.__file__).resolve()), *args],
        cwd=storage_path.parent,
        env=env,
        capture_output=True,
        text=True,
    )


def _run_todo(storage_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TODO_FILE"] = str(storage_path)
    return subprocess.run(
        [sys.executable, str(Path(todo.__file__).resolve()), *args],
        cwd=storage_path.parent,
        env=env,
        capture_output=True,
        text=True,
    )


def _assert_success(result: subprocess.CompletedProcess[str], stdout: str) -> None:
    assert result.returncode == 0
    assert result.stdout == stdout
    assert result.stderr == ""


def test_export_stdout_all_items_preserves_order(tmp_path):
    storage_path = tmp_path / "todo.json"
    items = [
        {"id": 1, "text": "x", "done": True},
        {"id": 2, "text": "y", "done": False},
        {"id": 3, "text": "плов", "done": False},
    ]
    storage_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    expected = (
        "id,text,done\n"
        "1,x,True\n"
        "2,y,False\n"
        "3,плов,False\n"
    )
    _assert_success(_run_export(storage_path), expected)


def test_export_open_filters_completed_items(tmp_path):
    storage_path = tmp_path / "todo.json"
    items = [
        {"id": 1, "text": "x", "done": True},
        {"id": 2, "text": "y", "done": False},
        {"id": 3, "text": "плов", "done": False},
    ]
    storage_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    expected = (
        "id,text,done\n"
        "2,y,False\n"
        "3,плов,False\n"
    )
    _assert_success(_run_export(storage_path, "--open"), expected)


def test_export_out_writes_file_and_leaves_stdout_empty(tmp_path):
    storage_path = tmp_path / "todo.json"
    items = [
        {"id": 1, "text": "x", "done": True},
        {"id": 2, "text": "y", "done": False},
        {"id": 3, "text": "плов", "done": False},
    ]
    initial_bytes = json.dumps(items, ensure_ascii=False).encode("utf-8")
    storage_path.write_bytes(initial_bytes)

    out_file = tmp_path / "out.csv"
    _assert_success(_run_export(storage_path, "--out", str(out_file)), "")
    with open(out_file, "r", encoding="utf-8", newline="") as f:
        assert f.read() == (
            "id,text,done\n"
            "1,x,True\n"
            "2,y,False\n"
            "3,плов,False\n"
        )

    out_open_file = tmp_path / "out_open.csv"
    _assert_success(_run_export(storage_path, "--out", str(out_open_file), "--open"), "")
    with open(out_open_file, "r", encoding="utf-8", newline="") as f:
        assert f.read() == (
            "id,text,done\n"
            "2,y,False\n"
            "3,плов,False\n"
        )

    assert storage_path.read_bytes() == initial_bytes


def test_export_escapes_csv_fields(tmp_path):
    storage_path = tmp_path / "todo.json"
    items = [
        {"id": 1, "text": 'a,b "q"', "done": False},
    ]
    storage_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    expected = (
        "id,text,done\n"
        '1,"a,b ""q""",False\n'
    )
    _assert_success(_run_export(storage_path), expected)


def test_export_handles_empty_and_damaged_storage_without_mutating(tmp_path):
    storage_path = tmp_path / "todo.json"

    if storage_path.exists():
        storage_path.unlink()
    _assert_success(_run_export(storage_path), "id,text,done\n")
    assert not storage_path.exists()

    storage_path.write_text("{", encoding="utf-8")
    _assert_success(_run_export(storage_path), "id,text,done\n")
    assert storage_path.read_text(encoding="utf-8") == "{"


def test_export_shares_storage_with_todo_cli(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_todo(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_todo(storage_path, "add", "y"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_todo(storage_path, "done", "1"),
        "{'id': 1, 'text': 'x', 'done': True}\n",
    )

    _assert_success(
        _run_export(storage_path),
        "id,text,done\n"
        "1,x,True\n"
        "2,y,False\n",
    )
    _assert_success(
        _run_export(storage_path, "--open"),
        "id,text,done\n"
        "2,y,False\n",
    )


def test_export_out_same_as_storage_refuses_overwrite_and_preserves_bytes(tmp_path):
    storage_path = tmp_path / "todo.json"
    items = [
        {"id": 1, "text": "x", "done": True},
        {"id": 2, "text": "y", "done": False},
    ]
    initial_bytes = json.dumps(items, ensure_ascii=False).encode("utf-8")
    storage_path.write_bytes(initial_bytes)

    result = _run_export(storage_path, "--out", str(storage_path))
    assert result.returncode != 0
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert storage_path.read_bytes() == initial_bytes
