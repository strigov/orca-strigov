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
