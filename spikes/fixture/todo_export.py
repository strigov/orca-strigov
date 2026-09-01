"""CSV export module and CLI for todo items."""
import argparse
import csv
import os
from pathlib import Path
import sys
from typing import TextIO

import todo


class _CsvImportError(Exception):
    line_number: int

    def __init__(self, line_number: int):
        self.line_number = line_number
        super().__init__(line_number)


def _read_import_rows(path: Path) -> list[dict]:
    previous_field_size_limit = csv.field_size_limit()
    reader = None
    try:
        csv.field_size_limit(sys.maxsize)
        with path.open("r", encoding="utf-8", newline="") as import_file:
            reader = csv.reader(import_file, strict=True)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise _CsvImportError(1) from exc
            if header != ["id", "text", "done"]:
                raise _CsvImportError(1)

            rows = []
            for row in reader:
                line_number = reader.line_num
                if len(row) != 3:
                    raise _CsvImportError(line_number)
                try:
                    item_id = int(row[0])
                except ValueError as exc:
                    raise _CsvImportError(line_number) from exc
                if item_id < 1 or row[2] not in {"True", "False"}:
                    raise _CsvImportError(line_number)
                rows.append(
                    {
                        "id": item_id,
                        "text": row[1],
                        "done": row[2] == "True",
                    }
                )
            return rows
    except _CsvImportError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        line_number = reader.line_num if reader is not None else 1
        raise _CsvImportError(max(line_number, 1)) from exc
    finally:
        csv.field_size_limit(previous_field_size_limit)


def _merge_import_rows(items: list[dict], rows: list[dict]) -> list[dict]:
    snapshots = []
    for row in rows:
        for item in items:
            if item["id"] == row["id"]:
                item["text"] = row["text"]
                item["done"] = row["done"]
                break
        else:
            item = {"id": row["id"], "text": row["text"], "done": row["done"]}
            items.append(item)
        snapshots.append(item.copy())
    return snapshots


def _import_csv(path: Path) -> list[dict]:
    rows = _read_import_rows(path)
    if not rows:
        return []

    storage_path = todo._storage_path()
    with todo._storage_lock(storage_path):
        items = todo._load_items(storage_path)
        snapshots = _merge_import_rows(items, rows)
        todo._save_items(storage_path, items)
    return snapshots


def _write_rows(stream: TextIO, items: list[dict]) -> None:
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["id", "text", "done"])
    for item in items:
        writer.writerow([item["id"], item["text"], item["done"]])


def write_csv(stream: TextIO, show_done: bool = True) -> None:
    _write_rows(stream, todo.list_items(show_done=show_done))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "import":
        import_parser = argparse.ArgumentParser(prog="todo_export")
        import_parser.add_argument("command", choices=["import"])
        import_parser.add_argument("path")
        ns = import_parser.parse_args(args)
        try:
            snapshots = _import_csv(Path(ns.path))
        except _CsvImportError as exc:
            sys.stderr.write(
                f"todo_export: invalid CSV input at line {exc.line_number}\n"
            )
            return 2
        for item in snapshots:
            print(item)
        return 0

    p = argparse.ArgumentParser(prog="todo_export")
    p.add_argument("--out")
    p.add_argument("--open", action="store_true")
    ns = p.parse_args(args)

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
