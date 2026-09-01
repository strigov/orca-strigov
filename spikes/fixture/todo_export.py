"""CSV export module and CLI for todo items."""
import argparse
import csv
import os
from pathlib import Path
import sys
from typing import TextIO

import todo


def _write_rows(stream: TextIO, items: list[dict]) -> None:
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["id", "text", "done"])
    for item in items:
        writer.writerow([item["id"], item["text"], item["done"]])


def write_csv(stream: TextIO, show_done: bool = True) -> None:
    _write_rows(stream, todo.list_items(show_done=show_done))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="todo_export")
    p.add_argument("--out")
    p.add_argument("--open", action="store_true")
    ns = p.parse_args(argv)

    items = todo.list_items(show_done=not ns.open)

    if ns.out:
        out_path = Path(ns.out)
        storage_path = Path(todo._storage_path())
        if out_path.resolve() == storage_path.resolve() or (
            out_path.exists()
            and storage_path.exists()
            and os.path.samefile(out_path, storage_path)
        ):
            sys.stderr.write(
                f"todo_export: refusing to overwrite the active storage: {ns.out}\n"
            )
            return 2
        with open(ns.out, "w", encoding="utf-8", newline="") as f:
            _write_rows(f, items)
    else:
        _write_rows(sys.stdout, items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
