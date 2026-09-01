---
slug: todo-json-persistence
created: 2026-09-01
status: in-progress
orca_run: run_edc41ebcb977
phases:
  - id: Ф1
    scope: "JSON-хранилище и атомарные операции чтения/записи с pytest-обвязкой"
    status: in-progress
  - id: Ф2
    scope: "Подключение add/list/done к хранилищу без изменения CLI-контракта"
    status: pending
verify:
  - "python3 -m pytest -q spikes/fixture/tests"
---

## Goal

Добавить `spikes/fixture/todo.py` файловую персистентность между отдельными запусками процесса, сохранив существующие команды, аргументы, коды успешного завершения и формат вывода.

Состояние хранится в JSON рядом со скриптом либо по пути из `TODO_FILE`; чтение устойчиво к отсутствующему, пустому и повреждённому файлу, а запись не оставляет целевой файл частично обновлённым.

## Acceptance criteria

- `add`, выполненный в одном процессе, создаёт JSON-хранилище, а последующие отдельные запуски `list` и `done` читают и изменяют то же состояние.
- При отсутствии `TODO_FILE` используется `spikes/fixture/todo.json`; непустой `TODO_FILE` полностью переопределяет этот путь.
- Каждая изменяющая операция пишет полный JSON во временный файл в каталоге цели и заменяет цель через `os.replace`; при ошибке до замены прежний целевой файл остаётся без изменений, временный файл удаляется.
- Отсутствующий, пустой, состоящий только из пробелов, синтаксически повреждённый или структурно неверный JSON читается как пустой список без ошибки разбора; последующий `add` начинает состояние с `id == 1`.
- CLI сохраняет поверхности `add TEXT`, `list [--open]`, `done ID`, успешный код `0` и текущий вывод Python `repr(dict)` без заголовков и дополнительных сообщений.
- Команда `python3 -m pytest -q spikes/fixture/tests` проходит и покрывает путь по умолчанию/`TODO_FILE`, `add/list/done`, пустой и повреждённый файл и наблюдаемую атомарность записи.

## Non-goals / deferred

- Новые подкоманды, CLI-флаги, пользовательские сообщения, обработка неизвестного `done ID` или иной формат вывода.
- Блокировки и разрешение конфликтов между конкурентными писателями; атомарная замена не превращается в транзакцию read-modify-write.
- Резервная копия, восстановление содержимого или миграция повреждённого/старого JSON; по требованию он рассматривается как пустое состояние.
- Автоматическое создание отсутствующих родительских каталогов для `TODO_FILE`, сохранение режима доступа существующего файла и `fsync` каталога после rename.
- Разбиение fixture на пакет, сторонние зависимости, рефакторинг argparse или расширение документации за пределами требуемой реализации и тестов.

## Global Constraints

- Изменяемый скрипт: `spikes/fixture/todo.py`.
- JSON-файл по умолчанию хранится рядом со скриптом.
- Путь переопределяется переменной окружения `TODO_FILE`.
- Запись атомарная (`temp-file + rename`).
- Повреждённый/пустой файл трактуется как пустой список без падения.
- CLI-контракт (`add/list/done`, форматы вывода) не менять.
- Добавить pytest-тесты на `add/list/done` и на атомарность/повреждённый файл.
- Это smoke-прогон протокола `orca-dev` на fixture-репозитории; работать по протоколу полностью, без сокращений.
- Не добавлять спекулятивные функции или зависимости.
- Сохранять совместимость с проверенным окружением Python `3.10.11`.

## Files

### Ф1 — JSON-хранилище и атомарная запись

- `spikes/fixture/todo.py` — добавить приватные функции выбора пути, безопасного чтения и атомарной записи, пока не меняя тела публичных todo-функций.
- `spikes/fixture/pytest.ini` — задать fixture-local `testpaths = tests` и отключить pytest cache provider, не изменяя корневой `.gitignore`.
- `spikes/fixture/conftest.py` — явно добавить каталог fixture в `sys.path` для `import todo` из `tests/`.
- `spikes/fixture/tests/test_storage.py` — проверить разрешение пути, JSON-схему, пустое/повреждённое состояние и атомарную замену.

### Ф2 — интеграция доменных функций и CLI

- `spikes/fixture/todo.py` — убрать `_ITEMS`, подключить хранилище к `add`, `complete`, `list_items`, сохранив `main()` и CLI-вывод.
- `spikes/fixture/tests/test_cli.py` — проверить `add/list/done` в отдельных процессах, точный stdout, `list --open` и поведение повреждённого файла.

## Contracts

### Путь к хранилищу

В `spikes/fixture/todo.py` создаются следующие приватные интерфейсы:

```python
_DEFAULT_TODO_FILE: Path = Path(__file__).resolve().with_name("todo.json")

def _storage_path() -> Path: ...
def _load_items(path: Path) -> list[dict]: ...
def _save_items(path: Path, items: list[dict]) -> None: ...
```

`_storage_path()` читает окружение при каждом вызове. Непустое значение `TODO_FILE` возвращается как `Path(value).expanduser()`; относительный путь остаётся относительным к текущему рабочему каталогу. При отсутствующем или пустом `TODO_FILE` возвращается `_DEFAULT_TODO_FILE`.

### JSON-форма и чтение

Файл — UTF-8 JSON без envelope и версии, верхний уровень — список объектов:

```json
[
  {"id": 1, "text": "x", "done": false}
]
```

Корректный элемент имеет ровно ключи `id`, `text`, `done`; `type(id) is int`, `type(text) is str`, `type(done) is bool`. Отсутствующий файл, пустой/whitespace-only файл, `json.JSONDecodeError`, `UnicodeDecodeError`, неверный верхний уровень или элемент неверной формы дают `[]`. Остальные ошибки файловой системы, включая `PermissionError`, не маскируются.

Чтение ничего не создаёт и не переписывает. Первая последующая изменяющая операция сохраняет нормальный список и тем самым заменяет пустой или повреждённый файл; резервная копия повреждённых байтов не создаётся.

### Атомарная запись

`_save_items()` сериализует весь список через `json.dump(..., ensure_ascii=False)` во временный файл `tempfile.NamedTemporaryFile` с `delete=False` в `path.parent`. После успешной сериализации выполняются `flush()`, `os.fsync()` и закрытие файла, затем `os.replace(temp_path, path)`.

Временный файл всегда находится в том же каталоге, что и цель, поэтому replace остаётся в одной файловой системе. Блок `finally` удаляет незаменённый temp-файл при ошибке сериализации, flush/fsync или `os.replace`; исходная цель до успешного `os.replace` не открывается на запись и остаётся неизменной.

### Существующие доменные интерфейсы

Сигнатуры остаются точными:

```python
def add(text: str) -> dict: ...
def complete(item_id: int) -> dict: ...
def list_items(show_done: bool = True) -> list[dict]: ...
def main(argv: list[str] | None = None) -> int: ...
```

`add()` выполняет `_load_items(_storage_path())`, создаёт `{"id": len(items) + 1, "text": text, "done": False}`, добавляет его, атомарно сохраняет полный список и возвращает этот dict. Тем самым сохраняется действующая логика выдачи ID; исправление вручную созданных разрывов/дубликатов не входит в план.

`complete()` загружает список, ищет первый элемент с указанным `id`, устанавливает `done = True`, атомарно сохраняет список и возвращает изменённый dict. При отсутствии ID сохраняется действующий `raise KeyError(item_id)`, файл не переписывается.

`list_items()` загружает состояние и возвращает все элементы при `show_done=True` либо только элементы с `done is False` при `show_done=False`; функция не записывает файл.

### CLI-поверхность и вывод

- `python3 todo.py add TEXT` печатает ровно один dict вида `{'id': 1, 'text': 'x', 'done': False}\n`.
- `python3 todo.py done ID` печатает ровно один обновлённый dict вида `{'id': 1, 'text': 'x', 'done': True}\n`.
- `python3 todo.py list` печатает по одному dict на строку в порядке JSON-списка; пустой список не печатает ничего.
- `python3 todo.py list --open` использует существующее `show_done=not ns.open` и не печатает выполненные элементы.
- Для корректных команд `main()` возвращает `0`; argparse-конструкция, имена/позиции аргументов и обработка неизвестного ID не меняются.

### Pytest-обвязка

`spikes/fixture/pytest.ini` содержит fixture-local `testpaths = tests` и `addopts = -p no:cacheprovider`. `spikes/fixture/conftest.py` добавляет `spikes/fixture/` в начало `sys.path`; тесты импортируют существующий одиночный модуль `todo`, не превращая каталог в пакет.

## Test strategy

### Ф1

- Unit: при удалённом `TODO_FILE` `_storage_path()` равен `Path(todo.__file__).resolve().with_name("todo.json")`; непустой override, включая `~`, выбирается вместо default, не создавая файл.
- Unit: `_load_items()` возвращает `[]` для отсутствующего, пустого, whitespace-only, синтаксически неверного JSON, неверного top-level и элемента неверной формы; валидный список проходит round-trip без изменения русскоязычного текста.
- Unit/observability: успешный `_save_items()` оставляет валидную цель и не оставляет temp-файлов. При monkeypatch `todo.os.replace`, который фиксирует аргументы и выбрасывает `OSError`, тест подтверждает, что source — отдельный полностью записанный файл в том же каталоге, target сохраняет прежние байты, а temp затем удалён.
- Тесты используют только `tmp_path` и `monkeypatch`; ни один тест не создаёт `spikes/fixture/todo.json`.
- Цикл фазы: `python3 -m pytest -q spikes/fixture/tests`.

### Ф2

- Integration/e2e: через `subprocess.run([sys.executable, todo.py, ...])` и общий `TODO_FILE` в `tmp_path` выполнить отдельными процессами `add "x"`, `list`, `done 1`, повторный `list` и `list --open`.
- Для каждого шага проверить `returncode == 0`, точный stdout в текущем формате `repr(dict)` и отсутствие дополнительного stderr; после `done` проверить `done: True` и пустой вывод `list --open`.
- Integration: заранее записать пустой и повреждённый файлы, убедиться, что `list` завершается без ошибки и без вывода, затем `add` выдаёт элемент с `id == 1` и оставляет валидный JSON-список.
- Не тестировать детали whitespace/indent JSON, конкретное имя temp-файла, OS-level power loss, конкурентные записи, неизвестный `done ID`, права файла и отсутствующий parent directory.
- Цикл фазы: `python3 -m pytest -q spikes/fixture/tests`.

## Risks / unknowns / assumptions

- Имя default-файла пользователь не задал; план фиксирует естественное имя по stem скрипта — `spikes/fixture/todo.json`.
- Атомарность `os.replace` требует temp-файл в каталоге цели; вынесенный в системный temp-каталог файл мог бы оказаться на другой файловой системе, поэтому это запрещено контрактом.
- Требование считать повреждённое хранилище пустым означает, что следующий `add` намеренно заменит повреждённые байты без backup; это прямое следствие спецификации, а не механизм восстановления.
- Без file lock два параллельных процесса могут прочитать одно состояние и последний replace потеряет изменение первого; конкурентная согласованность явно отложена.
- В репозитории нет `pyproject.toml`, `setup.cfg`, `tox.ini`, общего `pytest.ini` или существующих тестов. Fixture-local расположение `spikes/fixture/tests/`, `pytest.ini` и `conftest.py` соответствует ранее зафиксированному исследованию `docs/spikes/probe-opus-plan.md`.
- Проверенное локальное окружение — Python `3.10.11`, pytest `9.0.3`; отдельного lint/typecheck-командного контракта репозиторий не содержит, поэтому `verify:` включает только узкий fixture pytest-прогон.

## Phases

Фазы последовательны: Ф2 потребляет проверенный слой хранения из Ф1; `parallel_group` не применяется, поскольку обе фазы изменяют `spikes/fixture/todo.py`.

## Ф1: JSON-хранилище и атомарные операции

**Files in this phase:**
- Modify: `spikes/fixture/todo.py` — добавить приватный слой хранения, оставив текущий in-memory вызов публичных функций рабочим до Ф2.
- Create: `spikes/fixture/pytest.ini` — fixture-local discovery и отключение cache provider.
- Create: `spikes/fixture/conftest.py` — импорт `todo` из каталога `tests/`.
- Test: `spikes/fixture/tests/test_storage.py` — тесты пути, чтения, схемы и атомарной записи.

**Interfaces:**
- Consumes: frozen in `## Contracts`: `_DEFAULT_TODO_FILE: Path`, `_storage_path() -> Path`, `_load_items(path: Path) -> list[dict]`, `_save_items(path: Path, items: list[dict]) -> None`, JSON-форма и атомарная последовательность.
- Produces: `_storage_path() -> Path`; `_load_items(path: Path) -> list[dict]`; `_save_items(path: Path, items: list[dict]) -> None` с поведением, зафиксированным в `## Contracts`.

1. Добавить только стандартные импорты `json`, `os`, `tempfile`, `Path` и `_DEFAULT_TODO_FILE`; сторонние зависимости не вводить.
2. Реализовать `_storage_path()` с runtime-чтением `TODO_FILE` и default рядом с реальным файлом скрипта.
3. Реализовать полную проверку загруженной JSON-формы и возврат `[]` для отсутствующего/пустого/повреждённого состояния, не подавляя посторонние I/O-ошибки.
4. Реализовать `_save_items()` с temp-файлом в `path.parent`, полной сериализацией, flush/fsync, закрытием, `os.replace` и гарантированной очисткой незаменённого temp-файла.
5. Создать fixture-local pytest-обвязку и storage-тесты; изолировать все файловые операции в `tmp_path`.
6. Выполнить `python3 -m pytest -q spikes/fixture/tests`; фаза готова к отдельному коммиту только при зелёном результате и неизменённом поведении текущего CLI.

## Ф2: Персистентные add/list/done без изменения CLI

**Files in this phase:**
- Modify: `spikes/fixture/todo.py` — перевести существующие функции на слой хранения и удалить `_ITEMS`.
- Test: `spikes/fixture/tests/test_cli.py` — создать межпроцессные CLI-тесты `add/list/done`, формата и повреждённого файла.

**Interfaces:**
- Consumes: `_storage_path() -> Path`; `_load_items(path: Path) -> list[dict]`; `_save_items(path: Path, items: list[dict]) -> None`, произведённые Ф1.
- Produces: `add(text: str) -> dict`; `complete(item_id: int) -> dict`; `list_items(show_done: bool = True) -> list[dict]`; `main(argv: list[str] | None = None) -> int` с персистентностью и неизменённым CLI-контрактом.

1. Удалить `_ITEMS` и переписать только тела `add`, `complete`, `list_items` как load → mutate/filter → save по контракту; не менять их сигнатуры.
2. Оставить argparse-парсер, имена и порядок аргументов, ветвление `main()`, `print(dict)` и возврат `0` без новых флагов и сообщений.
3. Добавить subprocess-тесты, которые используют один `TODO_FILE` в `tmp_path`, но отдельный Python-процесс для каждого шага; зафиксировать точный stdout исходного CLI.
4. Добавить CLI-проверки пустого/повреждённого хранилища и последующего `add`, не тестируя отложенные сценарии.
5. Выполнить `python3 -m pytest -q spikes/fixture/tests`; фаза готова к отдельному коммиту только при прохождении storage- и CLI-наборов вместе.
