import csv
import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys

import pytest

import todo_export


def _run_import(storage_path: Path, import_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TODO_FILE"] = str(storage_path)
    return subprocess.run(
        [
            sys.executable,
            str(Path(todo_export.__file__).resolve()),
            "import",
            str(import_path),
        ],
        cwd=storage_path.parent,
        env=env,
        capture_output=True,
        text=True,
    )


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as import_file:
        writer = csv.writer(import_file, lineterminator="\n")
        writer.writerow(["id", "text", "done"])
        writer.writerows(rows)


def test_import_merges_rows_preserves_positions_and_prints_csv_order(tmp_path):
    storage_path = tmp_path / "todo.json"
    storage_path.write_text(
        json.dumps(
            [
                {"id": 1, "text": "keep-before", "done": False},
                {"id": 3, "text": "old-three", "done": True},
                {"id": 5, "text": "keep-after", "done": False},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import_path = tmp_path / "input.csv"
    _write_csv(
        import_path,
        [
            [3, "three-updated", False],
            [2, "new-two", True],
            [4, 'new, "four"', False],
            [3, "three-final", True],
            [2, "new-two-final", False],
        ],
    )

    result = _run_import(storage_path, import_path)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == (
        "{'id': 3, 'text': 'three-updated', 'done': False}\n"
        "{'id': 2, 'text': 'new-two', 'done': True}\n"
        "{'id': 4, 'text': 'new, \"four\"', 'done': False}\n"
        "{'id': 3, 'text': 'three-final', 'done': True}\n"
        "{'id': 2, 'text': 'new-two-final', 'done': False}\n"
    )
    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "keep-before", "done": False},
        {"id": 3, "text": "three-final", "done": True},
        {"id": 5, "text": "keep-after", "done": False},
        {"id": 2, "text": "new-two-final", "done": False},
        {"id": 4, "text": 'new, "four"', "done": False},
    ]


def test_import_preserves_empty_text_and_csv_quoting(tmp_path):
    storage_path = tmp_path / "todo.json"
    storage_path.write_text(
        json.dumps([{"id": 1, "text": "old", "done": True}]), encoding="utf-8"
    )
    import_path = tmp_path / "input.csv"
    _write_csv(import_path, [[1, "", False], [2, 'comma, "quoted"', True]])

    result = _run_import(storage_path, import_path)

    assert result.returncode == 0
    assert result.stdout == (
        "{'id': 1, 'text': '', 'done': False}\n"
        "{'id': 2, 'text': 'comma, \"quoted\"', 'done': True}\n"
    )
    assert result.stderr == ""
    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "", "done": False},
        {"id": 2, "text": 'comma, "quoted"', "done": True},
    ]


def test_import_accepts_text_longer_than_default_csv_field_limit_and_restores_it(
    tmp_path,
):
    import_path = tmp_path / "large-input.csv"
    previous_field_size_limit = csv.field_size_limit()
    long_text = "x" * (previous_field_size_limit + 1)
    _write_csv(import_path, [[1, long_text, False]])

    rows = todo_export._read_import_rows(import_path)

    assert rows == [{"id": 1, "text": long_text, "done": False}]
    assert csv.field_size_limit() == previous_field_size_limit


@pytest.mark.parametrize("storage_exists", [True, False])
def test_import_header_only_is_a_byte_for_byte_noop(tmp_path, storage_exists):
    storage_path = tmp_path / "todo.json"
    if storage_exists:
        storage_bytes = b' [ {"id": 9, "text": "untouched", "done": false} ]\n'
        storage_path.write_bytes(storage_bytes)
    import_path = tmp_path / "header.csv"
    import_path.write_text("id,text,done\n", encoding="utf-8", newline="")

    result = _run_import(storage_path, import_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    if storage_exists:
        assert storage_path.read_bytes() == storage_bytes
    else:
        assert not storage_path.exists()
    assert not storage_path.with_name(storage_path.name + ".lock").exists()


@pytest.mark.parametrize(
    ("case", "content", "expected_line"),
    [
        ("missing", None, 1),
        ("directory", None, 1),
        ("empty", "", 1),
        ("invalid-header", "id,text\n", 1),
        ("wrong-columns", "id,text,done\n1,x\n", 2),
        ("non-integer-id", "id,text,done\nnot-an-int,x,False\n", 2),
        ("id-less-than-one", "id,text,done\n0,x,False\n", 2),
        ("invalid-done", "id,text,done\n1,x,yes\n", 2),
        (
            "late-invalid-row",
            "id,text,done\n1,valid,False\nnot-an-int,later,False\n",
            3,
        ),
    ],
)
def test_import_rejects_invalid_input_without_partial_storage_write(
    tmp_path, case, content, expected_line
):
    storage_path = tmp_path / "todo.json"
    storage_bytes = b' [ {"id": 9, "text": "untouched", "done": true} ]\n'
    storage_path.write_bytes(storage_bytes)
    import_path = tmp_path / "input.csv"
    if case == "missing":
        pass
    elif case == "directory":
        import_path.mkdir()
    else:
        import_path.write_text(content, encoding="utf-8", newline="")

    result = _run_import(storage_path, import_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert f"line {expected_line}" in result.stderr
    assert storage_path.read_bytes() == storage_bytes
    assert not storage_path.with_name(storage_path.name + ".lock").exists()


def test_merge_uses_first_existing_duplicate_and_snapshots_each_row():
    items = [
        {"id": 1, "text": "first", "done": False},
        {"id": 1, "text": "second", "done": True},
    ]
    rows = [
        {"id": 1, "text": "updated", "done": True},
        {"id": 2, "text": "new", "done": False},
        {"id": 2, "text": "new-final", "done": True},
    ]

    snapshots = todo_export._merge_import_rows(items, rows)

    assert snapshots == [
        {"id": 1, "text": "updated", "done": True},
        {"id": 2, "text": "new", "done": False},
        {"id": 2, "text": "new-final", "done": True},
    ]
    assert items == [
        {"id": 1, "text": "updated", "done": True},
        {"id": 1, "text": "second", "done": True},
        {"id": 2, "text": "new-final", "done": True},
    ]


def test_import_helper_loads_and_saves_only_inside_shared_lock(monkeypatch, tmp_path):
    storage_path = tmp_path / "todo.json"
    storage_path.write_text(
        json.dumps([{"id": 1, "text": "old", "done": False}]), encoding="utf-8"
    )
    import_path = tmp_path / "input.csv"
    rows = [{"id": 1, "text": "updated", "done": True}]
    active = False
    events = []
    load_calls = []
    save_calls = []
    real_load = todo_export.todo._load_items
    real_save = todo_export.todo._save_items

    def read_rows(path):
        events.append("validate")
        assert path == import_path
        return rows

    def resolve_storage_path():
        events.append("storage-path")
        return storage_path

    @contextmanager
    def observed_lock(path):
        nonlocal active
        assert path == storage_path
        events.append("lock-enter")
        active = True
        try:
            yield
        finally:
            active = False
            events.append("lock-exit")

    def observed_load(path):
        assert active
        load_calls.append(path)
        events.append("load")
        return real_load(path)

    def observed_save(path, items):
        assert active
        save_calls.append((path, items))
        events.append("save")
        return real_save(path, items)

    monkeypatch.setattr(todo_export, "_read_import_rows", read_rows)
    monkeypatch.setattr(todo_export.todo, "_storage_path", resolve_storage_path)
    monkeypatch.setattr(todo_export.todo, "_storage_lock", observed_lock)
    monkeypatch.setattr(todo_export.todo, "_load_items", observed_load)
    monkeypatch.setattr(todo_export.todo, "_save_items", observed_save)

    snapshots = todo_export._import_csv(import_path)

    assert snapshots == [{"id": 1, "text": "updated", "done": True}]
    assert events == ["validate", "storage-path", "lock-enter", "load", "save", "lock-exit"]
    assert load_calls == [storage_path]
    assert len(save_calls) == 1
    assert json.loads(storage_path.read_text(encoding="utf-8")) == [
        {"id": 1, "text": "updated", "done": True}
    ]


def test_import_helper_header_only_does_not_touch_storage(monkeypatch, tmp_path):
    import_path = tmp_path / "header.csv"

    def fail_storage_access(*args):
        raise AssertionError("header-only import must not access storage")

    monkeypatch.setattr(todo_export, "_read_import_rows", lambda path: [])
    monkeypatch.setattr(todo_export.todo, "_storage_path", fail_storage_access)
    monkeypatch.setattr(todo_export.todo, "_storage_lock", fail_storage_access)
    monkeypatch.setattr(todo_export.todo, "_load_items", fail_storage_access)
    monkeypatch.setattr(todo_export.todo, "_save_items", fail_storage_access)

    assert todo_export._import_csv(import_path) == []
