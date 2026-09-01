"""Tiny in-memory todo CLI used as a planning fixture."""
import argparse
import sys

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
