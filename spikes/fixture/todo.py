"""Tiny in-memory todo CLI used as a planning fixture."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterator

_DEFAULT_TODO_FILE: Path = Path(__file__).resolve().with_name("todo.json")


def _storage_path() -> Path:
    value = os.environ.get("TODO_FILE")
    if value:
        return Path(value).expanduser()
    return _DEFAULT_TODO_FILE


def _lock_path(storage_path: Path) -> Path:
    return storage_path.with_name(storage_path.name + ".lock")


@contextmanager
def _storage_lock(storage_path: Path) -> Iterator[None]:
    lock_path = _lock_path(storage_path)
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_items(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8") as storage_file:
            items = json.load(storage_file)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return []

    if not isinstance(items, list):
        return []
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "text", "done"}
            or type(item["id"]) is not int
            or type(item["text"]) is not str
            or type(item["done"]) is not bool
        ):
            return []
    return items


def _save_items(path: Path, items: list[dict]) -> None:
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=path.parent
        ) as storage_file:
            temp_path = storage_file.name
            json.dump(items, storage_file, ensure_ascii=False)
            storage_file.flush()
            os.fsync(storage_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

def _next_id(items: list[dict]) -> int:
    return max((item["id"] for item in items), default=0) + 1


def add(text: str) -> dict:
    path = _storage_path()
    with _storage_lock(path):
        items = _load_items(path)
        item = {"id": _next_id(items), "text": text, "done": False}
        items.append(item)
        _save_items(path, items)
        return item


def complete(item_id: int) -> dict:
    path = _storage_path()
    with _storage_lock(path):
        items = _load_items(path)
        for item in items:
            if item["id"] == item_id:
                item["done"] = True
                _save_items(path, items)
                return item
        raise KeyError(item_id)


def remove(item_id: int) -> dict:
    path = _storage_path()
    with _storage_lock(path):
        items = _load_items(path)
        for idx, item in enumerate(items):
            if item["id"] == item_id:
                del items[idx]
                _save_items(path, items)
                return item
        raise KeyError(item_id)


def edit(item_id: int, text: str) -> dict:
    path = _storage_path()
    with _storage_lock(path):
        items = _load_items(path)
        for item in items:
            if item["id"] == item_id:
                item["text"] = text
                _save_items(path, items)
                return item
        raise KeyError(item_id)


def list_items(show_done: bool = True) -> list[dict]:
    items = _load_items(_storage_path())
    return [i for i in items if show_done or not i["done"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="todo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add").add_argument("text")
    sub.add_parser("done").add_argument("id", type=int)
    sub.add_parser("remove").add_argument("id", type=int)
    edit_parser = sub.add_parser("edit")
    edit_parser.add_argument("id", type=int)
    edit_parser.add_argument("text")
    sub.add_parser("list").add_argument("--open", action="store_true")
    ns = p.parse_args(argv)
    if ns.cmd == "add":
        print(add(ns.text))
    elif ns.cmd == "done":
        print(complete(ns.id))
    elif ns.cmd == "remove":
        print(remove(ns.id))
    elif ns.cmd == "edit":
        print(edit(ns.id, ns.text))
    else:
        for i in list_items(show_done=not ns.open):
            print(i)
    return 0


if __name__ == "__main__":
    sys.exit(main())
