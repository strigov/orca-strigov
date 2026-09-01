---
slug: probe-opus-plan
created: 2026-09-01
status: draft
target: spikes/fixture
phases:
  - id: P1
    scope: "pytest-обвязка: pytest.ini, conftest.py, sys.path, характеризующий smoke-тест текущего поведения, .gitignore"
    status: pending
  - id: P2
    scope: "слой хранения в todo.py: default_path/resolve_path/atomic_write_json/load/save + TodoStoreError"
    status: pending
  - id: P3
    scope: "перевод add/complete/list_items на файловый стор, удаление глобала _ITEMS, исправление выдачи id"
    status: pending
  - id: P4
    scope: "CLI: флаг --file на корневом парсере, build_parser(), проброс пути во все подкоманды"
    status: pending
  - id: P5
    scope: "документация: README.md фикстуры и докстринг модуля"
    status: pending
---
**Исполнитель этого плана:** модель `claude-opus-5` (Opus 5) — по системному промпту сессии («You are powered by the model named Opus 5. The exact model ID is claude-opus-5»). **Effort определить не могу:** в контексте сессии нет тега `reasoning_effort` (в отличие от probe-claude-fable, где он был виден), в окружении нет ни одной переменной с effort/reasoning (проверено `env | grep -iE 'model|effort|reason'`). Иных способов узнать effort изнутри сессии нет.

---

## Goal

Убрать заявленный в `spikes/fixture/README.md:2` пробел («nothing persists between invocations»): состояние списка задач переезжает из модульного глобала `_ITEMS` (`spikes/fixture/todo.py:5`) в JSON-файл. Три требования:

1. **Персистентность через JSON-файл** с **атомарной записью**: запись во временный файл в том же каталоге → `fsync` → `os.replace`. Инвариант: в любой момент времени целевой файл содержит либо полностью старое, либо полностью новое состояние; частично записанного JSON не существует никогда, включая падение процесса и ошибку сериализации на середине.
2. **Флаг `--file`** со значением по умолчанию `~/.todo.json`.
3. **Набор тестов на pytest**, покрывающий и доменную логику, и наблюдаемую гарантию атомарности.

Не входит в объём: команды удаления/редактирования, блокировки для конкурентного доступа, миграции формата, смена формата вывода `print(item)`.

### Что есть сейчас (проверено чтением файла)

`spikes/fixture/todo.py`, 44 строки, 2 импорта (`argparse`, `sys`):

| Строка | Объект | Текущее поведение |
|---|---|---|
| 5 | `_ITEMS: list[dict] = []` | модульный глобал, живёт только внутри процесса |
| 8 | `add(text: str) -> dict` | `id = len(_ITEMS) + 1`, `{"id","text","done"}` |
| 14 | `complete(item_id: int) -> dict` | линейный поиск, при промахе `raise KeyError(item_id)` |
| 22 | `list_items(show_done: bool = True) -> list[dict]` | фильтр `show_done or not i["done"]` |
| 26 | `main(argv: list[str] \| None = None) -> int` | `prog="todo"`, `add_subparsers(dest="cmd", required=True)`, подкоманды `add <text>` / `done <id:int>` / `list [--open]`; всегда `return 0` |
| 43–44 | `sys.exit(main())` | точка входа |

Окружение: Python 3.10.11, pytest 9.0.3 (оба проверены запуском). В репозитории нет `pyproject.toml`, `setup.cfg`, `pytest.ini`, `tox.ini`, каталога `tests/` — обвязку надо создавать с нуля. `.gitignore` содержит `.superpowers/` и `__pycache__/`.

---

## Files (per phase)

### P1 — обвязка тестов

| Файл | Действие | Содержание |
|---|---|---|
| `spikes/fixture/pytest.ini` | создать | `[pytest]`, `testpaths = tests`, `addopts = -q` |
| `spikes/fixture/conftest.py` | создать | явная вставка каталога фикстуры в `sys.path`; общие фикстуры `store_path`, `home` |
| `spikes/fixture/tests/test_todo.py` | создать | характеризующие тесты текущего API (пока без персистентности) |
| `.gitignore` | изменить | добавить `.pytest_cache/` |

`conftest.py` кладём именно в `spikes/fixture/`, а не в `tests/`: при импорт-режиме `prepend` pytest добавляет в `sys.path` базовый каталог модуля — первый каталог вверх по дереву без `__init__.py`. Для `tests/test_todo.py` это `tests/`, откуда `import todo` не разрешается. `conftest.py` уровнем выше делает `spikes/fixture/` импортируемым. Полагаться на этот побочный эффект неявно не стоит — в `conftest.py` пишем вставку пути явно, это дешевле одной строки и переживает смену `importmode`.

### P2 — слой хранения

| Файл | Действие |
|---|---|
| `spikes/fixture/todo.py` | изменить: добавить `import json`, `import os`, `import tempfile`, `from pathlib import Path`; добавить `TodoStoreError`, `DEFAULT_FILENAME`, `default_path`, `resolve_path`, `atomic_write_json`, `load`, `save`, `next_id` |
| `spikes/fixture/tests/test_storage.py` | создать |

### P3 — доменные функции поверх стора

| Файл | Действие |
|---|---|
| `spikes/fixture/todo.py` | изменить: удалить `_ITEMS` (строка 5), переписать тела `add`/`complete`/`list_items` (строки 8–23) на `load → mutate → save`, `id` через `next_id` |
| `spikes/fixture/tests/test_todo.py` | изменить: характеризующие тесты P1 дополняются проверками персистентности |

### P4 — CLI

| Файл | Действие |
|---|---|
| `spikes/fixture/todo.py` | изменить: выделить `build_parser()`, добавить `--file` на корневой парсер, прокинуть путь в три ветки `main()` (строки 33–39), добавить обработку `TodoStoreError`/`KeyError` с кодом возврата |
| `spikes/fixture/tests/test_cli.py` | создать |

### P5 — документация

| Файл | Действие |
|---|---|
| `spikes/fixture/README.md` | изменить: снять формулировку «Known gap: nothing persists» (строка 2), поправить примеры запуска (строка 3) под новый порядок аргументов, снять «No tests yet» (строка 4), добавить команду запуска тестов |
| `spikes/fixture/todo.py` | изменить: докстринг строки 1 («Tiny **in-memory** todo CLI…») больше не соответствует реальности |

---

## Contracts (function signatures)

Всё живёт в одном модуле `spikes/fixture/todo.py`. Разбиение на пакет намеренно не делаем: `README.md:3` документирует запуск `python3 todo.py …`, а пакет потребовал бы либо `-m`, либо возни с `sys.path` в самом модуле.

```python
DEFAULT_FILENAME = ".todo.json"


class TodoStoreError(Exception):
    """Хранилище нечитаемо: битый JSON или структура не того типа."""


def default_path() -> Path:
    """Path.home() / DEFAULT_FILENAME. Вычисляется ПРИ ВЫЗОВЕ, не на импорте."""


def resolve_path(raw: str | os.PathLike[str] | None) -> Path:
    """None -> default_path(); иначе Path(raw).expanduser(). Без .resolve()."""


def atomic_write_json(path: Path, data: object) -> None:
    """Атомарно заменить содержимое path сериализацией data.

    Инвариант: path либо не меняется вовсе, либо содержит валидный JSON
    целиком. Промежуточных состояний не наблюдается никогда.

    Порядок: mkdir(parents=True, exist_ok=True) для path.parent ->
    tempfile.NamedTemporaryFile(dir=path.parent, delete=False) ->
    json.dump(..., ensure_ascii=False, indent=2) + "\n" ->
    flush() -> os.fsync(fileno()) -> close() -> os.chmod(tmp, 0o600) ->
    os.replace(tmp, path). Любое исключение -> os.unlink(tmp) в finally,
    исключение пробрасывается наверх.
    """


def load(path: Path) -> list[dict]:
    """Прочитать список задач.

    Отсутствующий файл -> []. Пустой файл -> [].
    Битый JSON -> TodoStoreError (from json.JSONDecodeError).
    Валидный JSON, но не список -> TodoStoreError.
    """


def save(path: Path, items: list[dict]) -> None:
    """Тонкая обёртка над atomic_write_json(path, items)."""


def next_id(items: list[dict]) -> int:
    """max(i["id"] for i in items) + 1, при пустом списке -> 1."""


# --- доменные функции: позиционные части сигнатур не меняются ---

def add(text: str, path: Path | None = None) -> dict:
    """load -> append {"id": next_id(items), "text": text, "done": False} -> save.
    Возвращает добавленный элемент (как сейчас, todo.py:11)."""


def complete(item_id: int, path: Path | None = None) -> dict:
    """load -> найти по id -> done=True -> save. Возвращает элемент.
    Промах по id -> raise KeyError(item_id) — контракт todo.py:19 сохраняется.
    При промахе save НЕ вызывается."""


def list_items(show_done: bool = True, path: Path | None = None) -> list[dict]:
    """load -> тот же фильтр, что в todo.py:23: [i for i in items
    if show_done or not i["done"]]. Read-only, save не вызывается."""


def build_parser() -> argparse.ArgumentParser:
    """Существующий парсер из todo.py:27-31 плюс --file на КОРНЕВОМ парсере:
    p.add_argument("--file", dest="file", default=None, metavar="PATH",
                   help="JSON store (default: ~/.todo.json)")"""


def main(argv: list[str] | None = None) -> int:
    """0 — успех; 1 — KeyError от complete (нет такой задачи);
    2 — TodoStoreError (нечитаемое хранилище). Сообщения об ошибках в stderr."""
```

### Почему `--file` только на корневом парсере

Вариант «общий родитель через `parents=[common]` и на корневом парсере, и на подкомандах» даёт флаг в обеих позициях, но **молча теряет значение**. Проверено запуском на целевом интерпретаторе (Python 3.10.11):

```
parent-only:              Namespace(file='X', cmd='add', text='hi')
both, flag BEFORE sub:    Namespace(file=None, cmd='add', text='hi')   # <-- потеря
both, flag AFTER  sub:    Namespace(file='X', cmd='add', text='hi')
```

Подпарсер пишет свой `default=None` в тот же `Namespace` поверх уже разобранного корневого значения. Пользователь, написавший `todo --file work.json add "x"`, тихо получил бы запись в `~/.todo.json`. Поэтому: флаг объявляется ровно один раз, на корневом парсере, порядок — `todo --file PATH <subcommand> …`. Цена — изменение порядка аргументов в примерах `README.md:3` (фаза P5).

### Почему путь по умолчанию вычисляется при вызове

`default=Path.home() / ".todo.json"` в `add_argument` вычислился бы на импорте модуля и заморозил `HOME`. Тест, подменяющий `HOME` через `monkeypatch`, не смог бы проверить резолвинг по умолчанию. Поэтому `default=None`, а `~` раскрывается в `resolve_path()` уже во время выполнения.

---

## Test strategy

Прогон: `cd spikes/fixture && python3 -m pytest`. Ни один тест не имеет права коснуться настоящего `~/.todo.json` — все пути идут либо из `tmp_path`, либо из подменённого `HOME`.

**Общие фикстуры (`spikes/fixture/conftest.py`):**

```python
@pytest.fixture
def store_path(tmp_path): return tmp_path / "todo.json"

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))   # Path.home() читает HOME на POSIX
    return tmp_path
```

**`tests/test_storage.py` — слой хранения (P2):**

| Тест | Проверяет |
|---|---|
| `test_default_path_uses_home` | `default_path() == home / ".todo.json"` при подменённом `HOME` |
| `test_resolve_path_expands_tilde` | `resolve_path("~/x.json")` раскрывает `~` (кейс закавыченного аргумента, который шелл не раскрыл) |
| `test_resolve_path_none_falls_back_to_default` | `resolve_path(None) == default_path()` |
| `test_load_missing_file_returns_empty` | отсутствующий файл → `[]`, файл при этом **не создаётся** |
| `test_load_empty_file_returns_empty` | нулевая длина → `[]` |
| `test_load_corrupt_json_raises` | содержимое `"{"` → `TodoStoreError` |
| `test_load_non_list_raises` | содержимое `'{"a": 1}'` → `TodoStoreError` |
| `test_save_load_roundtrip` | список словарей возвращается идентичным |
| `test_unicode_survives_roundtrip` | `"купить хлеб"` не превращается в `\uXXXX` (следствие `ensure_ascii=False`) — и в файле на диске тоже |
| `test_save_creates_missing_parent_dirs` | `tmp_path / "a" / "b" / "todo.json"` |
| `test_atomic_write_leaves_no_temp_files` | после `save` в каталоге ровно один файл — целевой |

**Атомарность — как её вообще проверить.** Убить процесс между `write` и `replace` из теста нельзя, поэтому проверяем не сам сбой, а **наблюдаемый инвариант** на двух точках отказа, куда падение и приводит:

| Тест | Как |
|---|---|
| `test_original_survives_replace_failure` | записать валидное состояние; `monkeypatch.setattr(os, "replace", boom)`; `pytest.raises` на `save`; убедиться, что `load` возвращает **старое** состояние и в каталоге не осталось временных файлов |
| `test_original_survives_serialization_failure` | записать валидное состояние; `save(path, [{"id": 1, "obj": object()}])` → `TypeError`; `load` возвращает старое состояние |
| `test_target_file_is_never_partially_written` | тот же кейс сериализации, но проверяем побайтово: файл на диске равен старому содержимому |

Второй кейс — не теоретический. `json.dump` пишет в поток инкрементально и падает **после** частичного вывода; проверено:

```
json.dump raised TypeError after emitting: '{"a": 1, "b": '
```

То есть сериализация напрямую в целевой файл гарантированно оставила бы битый JSON. Именно temp-файл, а не `os.replace`, спасает в этом сценарии.

**`tests/test_todo.py` — доменная логика (P1 характеризация → P3 персистентность):**

| Тест | Проверяет |
|---|---|
| `test_add_returns_item_shape` | ключи `id`/`text`/`done`, `done is False` |
| `test_add_persists_across_calls` | `add(...)` → независимый `load(path)` видит задачу (регрессия на исходный пробел) |
| `test_ids_are_unique_after_manual_deletion` | файл с id `[1, 3]` → `add` даёт `4`, не `3`. Прямая регрессия на `len(_ITEMS) + 1` (`todo.py:9`) |
| `test_complete_marks_done_and_persists` | `done is True` и в возвращённом элементе, и в файле |
| `test_complete_unknown_id_raises_keyerror` | контракт `todo.py:19` не сломан |
| `test_complete_unknown_id_does_not_touch_file` | mtime/содержимое файла не изменились |
| `test_list_items_default_shows_all` | `show_done=True` возвращает и выполненные |
| `test_list_items_open_only_filters_done` | `show_done=False` отсекает `done=True` |
| `test_list_items_does_not_write` | read-only: файл не создаётся, если его не было |

**`tests/test_cli.py` — CLI (P4), через `main([...])`, без подпроцессов:**

| Тест | Проверяет |
|---|---|
| `test_cli_add_then_list` | `main(["--file", p, "add", "x"]) == 0`, затем `list` печатает задачу (`capsys`) |
| `test_cli_file_flag_before_subcommand` | значение `--file` доезжает до записи — регрессия ровно на подтверждённый выше баг подпарсера |
| `test_cli_defaults_to_home_when_flag_absent` | при подменённом `HOME` запись уходит в `home / ".todo.json"` |
| `test_cli_open_flag_filters` | `list --open` не печатает выполненные (`ns.open` — проверено, атрибут читается именно так) |
| `test_cli_done_unknown_id_exits_nonzero` | код возврата 1, сообщение в stderr, трассировка наружу не летит |
| `test_cli_corrupt_store_exits_two` | код возврата 2 на битом файле |
| `test_cli_expands_tilde_in_file_flag` | `--file "~/notes.json"` при подменённом `HOME` |

Тесты CLI вызывают `main()` внутрипроцессно: `sys.exit` не срабатывает (он только в `__main__`-ветке, `todo.py:44`), код возврата берётся напрямую.

---

## Risks

1. **`os.replace` переносит на цель права ВРЕМЕННОГО файла.** Проверено:
   ```
   target mode before: 0o644 -> tmp mode: 0o600 -> target mode after replace: 0o600
   ```
   Существовавший `~/.todo.json` с правами `0644` после первой же записи станет `0600`. Для личного тудо-листа это скорее улучшение, но изменение молчаливое и необратимое. Митигация: `os.chmod(tmp, 0o600)` **явно** перед `os.replace` и строка в README. Альтернатива — читать `stat` цели и переносить её режим на temp — усложняет код ради сохранения более слабых прав; отвергнута.

2. **Потеря значения `--file` при `parents=[...]` на подкомандах.** Подтверждено экспериментом (см. Contracts). Самый вероятный способ провалить эту задачу «красиво»: сделать удобный синтаксис `todo add --file X "y"` и получить молчаливую запись не в тот файл. Защита: флаг только на корневом парсере + `test_cli_file_flag_before_subcommand`.

3. **`json.dump` пишет частично перед исключением.** Подтверждено (`'{"a": 1, "b": '`). Любая реализация, которая «оптимизирует» temp-файл и пишет прямо в цель, теряет данные не при падении процесса, а при обычной ошибке типа. Защита — тест `test_original_survives_serialization_failure`.

4. **`len(_ITEMS) + 1` (`todo.py:9`) становится источником коллизий id.** Пока состояние жило в памяти и ничего не удалялось, инвариант «длина = максимальный id» держался. С файлом его ломает любое ручное редактирование `~/.todo.json`. Тогда `complete(3)` пометит не ту задачу. Обязательный переход на `next_id()`; тест `test_ids_are_unique_after_manual_deletion`.

5. **`os.replace` требует temp-файл на той же файловой системе.** `tempfile.NamedTemporaryFile(dir=path.parent)` это гарантирует; `tempfile.gettempdir()` — нет (`OSError: [Errno 18] Invalid cross-device link`, если `~` смонтирован отдельно). Параметр `dir=` — не стилистика, а условие корректности.

6. **`fsync` обязателен.** Без `flush() + os.fsync()` `os.replace` может стать видимым раньше, чем данные дойдут до диска: после отключения питания получаем корректно переименованный файл нулевой длины. Тестом это не ловится — только код-ревью. Опционально: `fsync` на дескрипторе родительского каталога делает durable и сам rename; на POSIX работает, на Windows — нет, поэтому обёрнуто в `try/except OSError` и помечено как best-effort.

7. **Конкурентная запись не защищена.** Два одновременных `todo add` дают last-writer-wins: оба читают одно состояние, второй `os.replace` затирает задачу первого. Атомарность защищает от *битого* файла, но не от *потерянного обновления*. Файловые блокировки в объём не входят — фиксируется как известное ограничение в README, не как баг. Тест на это не пишем: недетерминированно.

8. **Формат вывода `print(add(...))` (`todo.py:34`)** — это `repr` словаря Python, а не JSON. Тесты CLI не должны на него завязываться дословно, иначе любое будущее изменение вывода сломает их без причины. Проверяем `in`-вхождение текста задачи, а не полное равенство строки.

9. **`Path.home()` на POSIX читает `HOME`, но не только его** — при пустом `HOME` уходит в `pwd`. Фикстура `home` подменяет `HOME` через `monkeypatch.setenv`; если тесты когда-нибудь поедут на Windows, подменять придётся `USERPROFILE`. Сейчас платформа одна (darwin 24.6.0), фиксируем как ограничение фикстуры.

10. **Порядок фаз обязателен.** P1 (обвязка) должна пройти до P2, иначе тесты P2 негде запускать; P3 удаляет `_ITEMS`, на который опираются характеризующие тесты P1 — их нужно править в той же фазе, а не позже, иначе между P3 и P4 дерево остаётся красным. P5 (README) переписывать до P4 нельзя: окончательный порядок аргументов CLI фиксируется именно в P4.

11. **Область изменений.** Затрагиваются только `spikes/fixture/*` и одна строка в `.gitignore`. Файлы `docs/spikes/probe-*.md`, принадлежащие другим воркерам спайка, не трогаются ни на одной фазе.
