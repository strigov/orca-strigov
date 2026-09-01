"""Tiny in-memory todo CLI used as a planning fixture."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_DEFAULT_TODO_FILE: Path = Path(__file__).resolve().with_name("todo.json")


def _storage_path() -> Path:
    value = os.environ.get("TODO_FILE")
    if value:
        return Path(value).expanduser()
    return _DEFAULT_TODO_FILE


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

_ITEMS: list[dict] = []


def add(text: str) -> dict:
    item = {"id": len(_ITEMS) + 1, "text": text, "done": False}
    _ITEMS.append(item)
    return item


def complete(item_id: int) -> dict:
    for item in _ITEMS:
        if item["id"] == item_id:
            item["done"] = True
            return item
    raise KeyError(item_id)


def list_items(show_done: bool = True) -> list[dict]:
    return [i for i in _ITEMS if show_done or not i["done"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="todo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add").add_argument("text")
    sub.add_parser("done").add_argument("id", type=int)
    sub.add_parser("list").add_argument("--open", action="store_true")
    ns = p.parse_args(argv)
    if ns.cmd == "add":
        print(add(ns.text))
    elif ns.cmd == "done":
        print(complete(ns.id))
    else:
        for i in list_items(show_done=not ns.open):
            print(i)
    return 0


if __name__ == "__main__":
    sys.exit(main())
