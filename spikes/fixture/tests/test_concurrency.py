import json
import os
from contextlib import contextmanager
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest

import todo


PROCESS_COUNT = 8
ADDS_PER_PROCESS = 25


def test_lock_path_is_adjacent_stable_and_non_destructive(tmp_path):
    storage_path = tmp_path / "todo.json"
    storage_bytes = b'{"storage": "untouched"}'
    storage_path.write_bytes(storage_bytes)
    lock_path = todo._lock_path(storage_path)
    lock_path.write_bytes(b"existing lock contents")

    with todo._storage_lock(storage_path):
        assert lock_path.exists()
        assert lock_path != storage_path

    assert todo._lock_path(Path("todo.json")) == Path("todo.json.lock")
    assert storage_path.read_bytes() == storage_bytes
    assert lock_path.read_bytes() == b"existing lock contents"


def test_storage_lock_unlocks_after_body_exception(monkeypatch, tmp_path):
    storage_path = tmp_path / "todo.json"
    calls = []
    real_flock = todo.fcntl.flock

    def spy_flock(fd, operation):
        calls.append(operation)
        return real_flock(fd, operation)

    monkeypatch.setattr(todo.fcntl, "flock", spy_flock)

    with pytest.raises(RuntimeError, match="body failed"):
        with todo._storage_lock(storage_path):
            raise RuntimeError("body failed")

    assert calls == [todo.fcntl.LOCK_EX, todo.fcntl.LOCK_UN]


def test_mutation_releases_lock_after_save_exception_for_other_process(
    monkeypatch, tmp_path
):
    storage_path = tmp_path / "todo.json"
    monkeypatch.setattr(todo, "_storage_path", lambda: storage_path)

    def fail_save(path, items):
        raise OSError("save failed")

    monkeypatch.setattr(todo, "_save_items", fail_save)

    with pytest.raises(OSError, match="save failed"):
        todo.add("will fail")

    probe_script = """
import fcntl
import sys

with open(sys.argv[1], "a+") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
"""
    probe = subprocess.run(
        [sys.executable, "-c", probe_script, str(todo._lock_path(storage_path))],
        cwd=storage_path.parent,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout == ""


@pytest.mark.parametrize(
    ("operation", "initial_items", "item_id", "text", "expected"),
    [
        (
            "add",
            [],
            None,
            "new",
            {"id": 1, "text": "new", "done": False},
        ),
        (
            "complete",
            [{"id": 1, "text": "old", "done": False}],
            1,
            None,
            {"id": 1, "text": "old", "done": True},
        ),
        (
            "remove",
            [{"id": 1, "text": "old", "done": False}],
            1,
            None,
            {"id": 1, "text": "old", "done": False},
        ),
        (
            "edit",
            [{"id": 1, "text": "old", "done": True}],
            1,
            "updated",
            {"id": 1, "text": "updated", "done": True},
        ),
    ],
)
def test_mutations_keep_read_modify_write_inside_one_storage_lock(
    monkeypatch, tmp_path, operation, initial_items, item_id, text, expected
):
    storage_path = tmp_path / "todo.json"
    storage_path.write_text(json.dumps(initial_items), encoding="utf-8")
    monkeypatch.setattr(todo, "_storage_path", lambda: storage_path)
    active = False
    events = []
    load_paths = []
    save_paths = []
    real_load = todo._load_items
    real_save = todo._save_items

    @contextmanager
    def observed_lock(path):
        nonlocal active
        assert path == storage_path
        assert not active
        active = True
        events.append("acquire")
        try:
            yield
        finally:
            active = False
            events.append("release")

    def observed_load(path):
        assert active
        load_paths.append(path)
        return real_load(path)

    def observed_save(path, items):
        assert active
        save_paths.append(path)
        return real_save(path, items)

    monkeypatch.setattr(todo, "_storage_lock", observed_lock)
    monkeypatch.setattr(todo, "_load_items", observed_load)
    monkeypatch.setattr(todo, "_save_items", observed_save)

    if operation == "add":
        result = todo.add(text)
    elif operation == "complete":
        result = todo.complete(item_id)
    elif operation == "remove":
        result = todo.remove(item_id)
    else:
        result = todo.edit(item_id, text)

    assert result == expected
    assert load_paths == [storage_path]
    assert save_paths == [storage_path]
    assert events == ["acquire", "release"]


@pytest.mark.parametrize("operation", ["complete", "remove", "edit"])
def test_mutations_release_lock_on_unknown_id_without_saving(
    monkeypatch, tmp_path, operation
):
    storage_path = tmp_path / "todo.json"
    initial_items = [{"id": 1, "text": "old", "done": False}]
    storage_path.write_text(json.dumps(initial_items), encoding="utf-8")
    monkeypatch.setattr(todo, "_storage_path", lambda: storage_path)
    active = False
    events = []
    load_paths = []
    save_calls = []
    real_load = todo._load_items

    @contextmanager
    def observed_lock(path):
        nonlocal active
        assert path == storage_path
        active = True
        events.append("acquire")
        try:
            yield
        finally:
            active = False
            events.append("release")

    def observed_load(path):
        assert active
        load_paths.append(path)
        return real_load(path)

    def observed_save(path, items):
        assert active
        save_calls.append((path, items))

    monkeypatch.setattr(todo, "_storage_lock", observed_lock)
    monkeypatch.setattr(todo, "_load_items", observed_load)
    monkeypatch.setattr(todo, "_save_items", observed_save)

    with pytest.raises(KeyError, match="99"):
        if operation == "complete":
            todo.complete(99)
        elif operation == "remove":
            todo.remove(99)
        else:
            todo.edit(99, "unused")

    assert load_paths == [storage_path]
    assert save_calls == []
    assert events == ["acquire", "release"]
    assert storage_path.read_text(encoding="utf-8") == json.dumps(initial_items)


def test_list_items_does_not_open_storage_lock(monkeypatch, tmp_path):
    storage_path = tmp_path / "todo.json"
    storage_path.write_text(
        json.dumps(
            [
                {"id": 1, "text": "done", "done": True},
                {"id": 2, "text": "open", "done": False},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(todo, "_storage_path", lambda: storage_path)

    def fail_lock(path):
        raise AssertionError("list_items must not acquire a storage lock")

    monkeypatch.setattr(todo, "_storage_lock", fail_lock)

    assert todo.list_items(show_done=False) == [
        {"id": 2, "text": "open", "done": False}
    ]
    assert not todo._lock_path(storage_path).exists()


_STRESS_WORKER = """
import sys

sys.path.insert(0, sys.argv[2])
import todo

print("ready", flush=True)
if sys.stdin.readline() != "go\\n":
    raise SystemExit("start gate was not opened")

for item_index in range(25):
    todo.add(f"worker-{sys.argv[1]}-item-{item_index}")
"""


def _wait_for_workers_ready(processes, timeout):
    pending = {process.stdout: index for index, process in enumerate(processes)}
    ready = set()
    deadline = time.monotonic() + timeout

    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"workers did not become ready: {pending.values()}")
        readable, _, _ = select.select(list(pending), [], [], remaining)
        if not readable:
            continue
        for stream in readable:
            line = stream.readline()
            index = pending.pop(stream)
            if line != "ready\n":
                raise AssertionError(f"worker {index} readiness output: {line!r}")
            ready.add(index)

    assert ready == set(range(len(processes)))


def test_eight_processes_each_add_twenty_five_items_without_lost_updates(tmp_path):
    storage_path = tmp_path / "todo.json"
    fixture_dir = str(Path(todo.__file__).resolve().parent)
    processes = []

    try:
        env = os.environ.copy()
        env["TODO_FILE"] = str(storage_path)
        for worker_index in range(PROCESS_COUNT):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        _STRESS_WORKER,
                        str(worker_index),
                        fixture_dir,
                    ],
                    cwd=storage_path.parent,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )

        _wait_for_workers_ready(processes, timeout=15)
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("go\n")
            process.stdin.flush()

        results = []
        for process in processes:
            returncode = process.wait(timeout=30)
            assert process.stdout is not None
            assert process.stderr is not None
            results.append(
                (returncode, process.stdout.read(), process.stderr.read())
            )

        for returncode, stdout, stderr in results:
            assert returncode == 0, stderr
            assert stdout == ""
            assert stderr == ""

        items = json.loads(storage_path.read_text(encoding="utf-8"))
        assert isinstance(items, list)
        assert len(items) == PROCESS_COUNT * ADDS_PER_PROCESS == 200
        assert all(
            set(item) == {"id", "text", "done"}
            and type(item["id"]) is int
            and type(item["text"]) is str
            and type(item["done"]) is bool
            for item in items
        )
        ids = [item["id"] for item in items]
        texts = [item["text"] for item in items]
        assert len(set(ids)) == 200
        assert sorted(ids) == list(range(1, 201))
        assert len(set(texts)) == 200
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
