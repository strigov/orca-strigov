import json
import os
from pathlib import Path
import subprocess
import sys

import todo


def _run_cli(storage_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def test_cli_persists_items_and_preserves_order_across_processes(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_cli(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "y"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "list"),
        "{'id': 1, 'text': 'x', 'done': False}\n"
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "done", "1"),
        "{'id': 1, 'text': 'x', 'done': True}\n",
    )
    _assert_success(
        _run_cli(storage_path, "list"),
        "{'id': 1, 'text': 'x', 'done': True}\n"
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "list", "--open"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )

    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "x", "done": True},
        {"id": 2, "text": "y", "done": False},
    ]


def test_cli_recovers_id_one_from_empty_and_damaged_storage(tmp_path):
    storage_path = tmp_path / "todo.json"

    for contents in ("", "{"):
        storage_path.write_text(contents, encoding="utf-8")

        _assert_success(_run_cli(storage_path, "list"), "")
        _assert_success(
            _run_cli(storage_path, "add", "recovered"),
            "{'id': 1, 'text': 'recovered', 'done': False}\n",
        )
        assert json.loads(storage_path.read_text(encoding="utf-8")) == [
            {"id": 1, "text": "recovered", "done": False}
        ]


def _assert_unknown_id_failure(
    result: subprocess.CompletedProcess[str],
    storage_path: Path,
    expected_bytes: bytes,
    item_id: int,
) -> None:
    assert result.returncode != 0
    assert result.stdout == ""
    assert f"KeyError: {item_id}" in result.stderr
    assert storage_path.read_bytes() == expected_bytes


def test_cli_remove_deletes_item_and_preserves_order(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_cli(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "y"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "z"),
        "{'id': 3, 'text': 'z', 'done': False}\n",
    )

    _assert_success(
        _run_cli(storage_path, "remove", "2"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "list"),
        "{'id': 1, 'text': 'x', 'done': False}\n"
        "{'id': 3, 'text': 'z', 'done': False}\n",
    )

    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "x", "done": False},
        {"id": 3, "text": "z", "done": False},
    ]


def test_cli_does_not_reuse_ids_after_remove(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_cli(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "y"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "z"),
        "{'id': 3, 'text': 'z', 'done': False}\n",
    )

    _assert_success(
        _run_cli(storage_path, "remove", "2"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "w"),
        "{'id': 4, 'text': 'w', 'done': False}\n",
    )

    _assert_success(
        _run_cli(storage_path, "remove", "1"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "remove", "3"),
        "{'id': 3, 'text': 'z', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "remove", "4"),
        "{'id': 4, 'text': 'w', 'done': False}\n",
    )

    _assert_success(
        _run_cli(storage_path, "add", "first"),
        "{'id': 1, 'text': 'first', 'done': False}\n",
    )
    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "first", "done": False}
    ]


def test_cli_edit_updates_text_and_preserves_done_and_order(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_cli(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "add", "y"),
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )
    _assert_success(
        _run_cli(storage_path, "done", "1"),
        "{'id': 1, 'text': 'x', 'done': True}\n",
    )

    _assert_success(
        _run_cli(storage_path, "edit", "1", "новый"),
        "{'id': 1, 'text': 'новый', 'done': True}\n",
    )
    _assert_success(
        _run_cli(storage_path, "list"),
        "{'id': 1, 'text': 'новый', 'done': True}\n"
        "{'id': 2, 'text': 'y', 'done': False}\n",
    )

    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "новый", "done": True},
        {"id": 2, "text": "y", "done": False},
    ]


def test_cli_unknown_id_fails_and_keeps_storage_intact(tmp_path):
    storage_path = tmp_path / "todo.json"

    _assert_success(
        _run_cli(storage_path, "add", "x"),
        "{'id': 1, 'text': 'x', 'done': False}\n",
    )
    expected_bytes = storage_path.read_bytes()

    for cmd_args in (
        ("done", "99"),
        ("remove", "99"),
        ("edit", "99", "z"),
    ):
        result = _run_cli(storage_path, *cmd_args)
        _assert_unknown_id_failure(result, storage_path, expected_bytes, 99)
